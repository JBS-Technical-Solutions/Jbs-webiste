"""Background analysis jobs with stage-by-stage progress.

A job reads the drawing (render, OCR, parse) and then builds the worksheet. With user-defined nodes the job stops
after parsing in status "review" with proposed nodes; `submit_nodes` resumes it with the user's node list.
"""

import json
import shutil
import threading
import time
import traceback
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

from . import documents
from . import knowledge as kb
from . import risk
from .config import CACHE_DIR, JOB_TTL_HOURS, JOBS_DIR, RENDER_DPI
from .pipeline import ai, ocr, parse, render, rules

STAGES = [
    {"id": "upload", "label": "Upload received"},
    {"id": "render", "label": "Reading drawing"},
    {"id": "ocr", "label": "Recognising text & tags"},
    {"id": "parse", "label": "Identifying equipment, lines & instruments"},
    {"id": "nodes", "label": "Confirming HAZOP nodes"},
    {"id": "analyse", "label": "Evaluating risk scenarios for each deviation"},
    {"id": "ai", "label": "AI engineering review"},
    {"id": "done", "label": "Worksheet ready"},
]

# Overall progress (0-1) at the start of each stage.
STAGE_START = {"upload": 0.0, "render": 0.03, "ocr": 0.1, "parse": 0.82, "nodes": 0.86, "analyse": 0.88, "ai": 0.92,
               "done": 1.0}
JOB_TTL_S = JOB_TTL_HOURS * 3600
FINISHED_IN_MEMORY_S = 600
BASE_REFERENCES = "ISA 5.1 instrument legend, API RP 14C component identification, line designation, piping component legend"

_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="hazop")
_jobs: dict[str, dict] = {}
_lock = threading.Lock()


class NotAwaitingNodes(LookupError):
    pass


def _public(job):
    return {k: v for k, v in job.items() if not k.startswith("_")}


def _update(job_id, **fields):
    with _lock:
        _jobs[job_id].update(fields)


def _stage(job_id, stage, frac=0.0):
    stages = [s["id"] for s in STAGES]
    nxt = stages[min(stages.index(stage) + 1, len(stages) - 1)]
    lo, hi = STAGE_START[stage], STAGE_START[nxt]
    if stage == "analyse" and not _jobs[job_id]["options"]["mode"] == "ai":
        hi = 1.0
    _update(job_id, stage=stage, progress=round(lo + (hi - lo) * max(0.0, min(1.0, frac)), 4))


def _safe(name):
    return "".join(ch for ch in name if ch.isalnum() or ch in "._- ") or "file"


@contextmanager
def _project(job):
    """Use the job's uploaded piping specs and risk matrix for everything that runs inside."""
    with kb.using_specs(job.get("_specs")), risk.using(job.get("_matrix")):
        yield


def _snapshot(job_id):
    with _lock:
        snapshot = _public(_jobs[job_id])
    (JOBS_DIR / job_id / "job.json").write_text(json.dumps(snapshot, default=str), encoding="utf-8")


def create(data: bytes, filename: str, options: dict, project: dict | None = None) -> dict:
    """project: {"specs", "matrix", "piping_spec": (name, bytes), "risk_matrix": (name, bytes), "optional": [(name, bytes)]}"""
    project = project or {}
    job_id = uuid.uuid4().hex[:12]
    folder = JOBS_DIR / job_id
    folder.mkdir(parents=True)
    (folder / _safe(filename)).write_bytes(data)
    docs_dir = folder / "documents"
    named = [project[k] for k in ("piping_spec", "risk_matrix") if project.get(k)] + list(project.get("optional") or [])
    if named:
        docs_dir.mkdir()
        for name, blob in named:
            (docs_dir / _safe(name)).write_bytes(blob)
    node_mode = options.get("node_mode", "auto")
    job = {
        "id": job_id, "filename": filename, "status": "queued", "stage": "upload", "progress": 0.0,
        "options": options, "error": None, "warnings": [], "created": time.time(),
        "stages": [s for s in STAGES if (s["id"] != "ai" or options.get("mode") == "ai")
                   and (s["id"] != "nodes" or node_mode == "user")],
        "_data": data,
        "_specs": project.get("specs"),
        "_matrix": project.get("matrix"),
        "_optional": list(project.get("optional") or []),
    }
    with _lock:
        _jobs[job_id] = job
    _executor.submit(_extract, job_id)
    return _public(job)


def get(job_id: str):
    with _lock:
        job = _jobs.get(job_id)
        if job:
            return _public(job)
    meta = JOBS_DIR / job_id / "job.json"
    if meta.exists():
        job = json.loads(meta.read_text(encoding="utf-8"))
        if job.get("status") == "review":
            job.update(status="error", review=None,
                       error="The engine restarted while this analysis was waiting for its nodes. Please start it again.")
        return job
    return None


def image_path(job_id: str):
    p = JOBS_DIR / job_id / "page.png"
    return p if p.exists() else None


def _stats(result, ext):
    rows = [r for n in result["nodes"] for d in n["deviations"] for r in d["rows"]]
    bands = Counter(r["risk"]["code"] for r in rows)
    return {
        "nodes": len(result["nodes"]),
        "deviations": sum(len(n["deviations"]) for n in result["nodes"]),
        "causes": len(rows),
        "recommendations": len(result["recommendations"]),
        "risk": {code: bands.get(code, 0) for code in ("L", "M", "H", "VH")},
        "equipment": len(ext["equipment"]),
        "instruments": len(ext["instruments"]),
        "lines": len(ext["lines"]),
        "valves": len(ext["valves"]),
    }


def _fail(job_id, e):
    traceback.print_exc()
    with _lock:
        job = _jobs[job_id]
        for key in ("_data", "_page", "_ext", "_optional"):
            job.pop(key, None)
    _update(job_id, status="error", error=str(e) or e.__class__.__name__, finished=time.time())
    _snapshot(job_id)


def _extract(job_id):
    job = _jobs[job_id]
    opts = job["options"]
    folder = JOBS_DIR / job_id
    timings = {}
    try:
        with _project(job):
            _update(job_id, status="running")
            _stage(job_id, "render")
            t0 = time.time()
            page = render.load(job["_data"], job["filename"], RENDER_DPI, int(opts.get("page") or 0))
            (folder / "page.png").write_bytes(page.png_bytes(max_side=3600))
            W, H = page.size
            timings["render"] = round(time.time() - t0, 1)

            _stage(job_id, "ocr")
            t0 = time.time()
            tokens, method = ocr.extract_text(page, progress=lambda f: _stage(job_id, "ocr", f))
            timings["ocr"] = round(time.time() - t0, 1)

            _stage(job_id, "parse")
            t0 = time.time()
            ext = parse.parse(tokens, (W, H))
            timings["parse"] = round(time.time() - t0, 1)

        warnings = []
        if not (ext["equipment"] or ext["instruments"] or ext["lines"]):
            warnings.append("Very little engineering text was recognised. Check that the upload is a P&ID with legible tags.")
        if any(i.get("inferred") for i in ext["instruments"]):
            tags = ", ".join(i["tag"] for i in ext["instruments"] if i.get("inferred"))
            warnings.append(f"{tags} inferred from its control loop (tag text not legible on the drawing).")
        missing = sorted({l["spec"] for l in ext["lines"] if not l["spec_known"]})
        if missing and job.get("_specs"):
            warnings.append(f"Piping spec {', '.join(missing)} used on the drawing is not in the uploaded piping "
                            f"specification; ratings for those lines are not checked.")

        with _lock:
            job.pop("_data", None)
            job.update(_page=page, _ext=ext, _method=method, _timings=timings, _size=(W, H))
            job["warnings"] = warnings
        if opts.get("node_mode") == "user":
            with _project(job):
                proposals = rules.plan_nodes(ext)
            _update(job_id, status="review", stage="nodes", progress=STAGE_START["nodes"], review={
                "image": {"width": W, "height": H, "url": f"/api/jobs/{job_id}/image", "page_count": page.page_count},
                "text_method": method, "extraction": ext, "proposed_nodes": proposals,
            })
            _snapshot(job_id)
            return
    except Exception as e:
        _fail(job_id, e)
        return
    _analyse(job_id)


def submit_nodes(job_id: str, nodes: list[dict]) -> dict:
    with _lock:
        job = _jobs.get(job_id)
        if not job or job["status"] != "review" or "_ext" not in job:
            raise NotAwaitingNodes(job_id)
        job.update(_nodes=nodes, status="running", stage="analyse", progress=STAGE_START["analyse"])
        job.pop("review", None)
        public = _public(job)
    _executor.submit(_analyse, job_id)
    return public


def _references(job):
    docs = job["options"].get("documents") or {}
    parts = [f"P&ID {job['filename']}"]
    if docs.get("piping_spec"):
        parts.append(f"piping specification {docs['piping_spec']}")
    else:
        parts.append("piping specifications")
    if docs.get("risk_matrix"):
        parts.append(f"risk matrix {docs['risk_matrix']}")
    parts += docs.get("optional") or []
    return f"{BASE_REFERENCES}, " + ", ".join(parts)


def _render_attachment(data, name):
    return render.load(data, name, 150).png_bytes(max_side=1600)


def _analyse(job_id):
    job = _jobs[job_id]
    opts = job["options"]
    timings = job["_timings"]
    ext, page = job["_ext"], job["_page"]
    W, H = job["_size"]
    warnings = list(job["warnings"])
    try:
        with _project(job):
            _stage(job_id, "analyse")
            t0 = time.time()
            study = opts.get("study") or {}
            result = rules.generate(ext, study, job.get("_nodes"))
            result["study"].update({k: v for k, v in study.items() if v})
            if not result["study"].get("drawing"):
                result["study"]["drawing"] = job["filename"]
            result["study"]["reference_documents"] = _references(job)
            result["study"]["analysis"] = "Rule-based engine"
            timings["analyse"] = round(time.time() - t0, 1)

            if opts.get("mode") == "ai":
                _stage(job_id, "ai")
                t0 = time.time()
                attachments = [a for a in (documents.ai_attachment(n, d, _render_attachment) for n, d in job["_optional"]) if a]
                try:
                    result = ai.review(opts.get("provider"), page.png_bytes(max_side=2400), ext, result,
                                       attachments=attachments, fixed_nodes=bool(job.get("_nodes")))
                except Exception as e:  # keep the rule-based worksheet if the AI call fails
                    warnings.append(f"AI review failed, showing the rule-based worksheet instead: {e}")
                timings["ai"] = round(time.time() - t0, 1)
            result["risk_matrix"] = risk.current()

        payload = {
            "image": {"width": W, "height": H, "url": f"/api/jobs/{job_id}/image", "page_count": page.page_count},
            "text_method": job["_method"],
            "extraction": ext,
            "worksheet": result,
            "stats": _stats(result, ext),
            "timings": timings,
        }
        with _lock:
            for key in ("_page", "_ext", "_optional"):
                job.pop(key, None)
        _update(job_id, status="done", stage="done", progress=1.0, result=payload, warnings=warnings,
                finished=time.time())
        _snapshot(job_id)
    except Exception as e:
        _fail(job_id, e)


def active():
    """Jobs waiting for or using the engine (not finished, not waiting for the user's nodes)."""
    with _lock:
        return sum(1 for j in _jobs.values() if j["status"] not in ("done", "error", "review"))


def cleanup():
    """Delete expired job folders and OCR cache entries; finished jobs are served from their job.json on disk."""
    now = time.time()
    for folder in JOBS_DIR.iterdir():
        if folder.is_dir() and now - folder.stat().st_mtime > JOB_TTL_S:
            shutil.rmtree(folder, ignore_errors=True)
    for f in CACHE_DIR.glob("*.json"):
        if now - f.stat().st_mtime > 7 * 24 * 3600:
            f.unlink(missing_ok=True)
    with _lock:
        for job_id in [k for k, j in _jobs.items()
                       if (j["status"] in ("done", "error") and now - (j.get("finished") or now) > FINISHED_IN_MEMORY_S)
                       or (j["status"] == "review" and now - j["created"] > JOB_TTL_S)]:
            del _jobs[job_id]
