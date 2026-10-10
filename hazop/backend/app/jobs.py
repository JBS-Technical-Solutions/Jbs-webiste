"""Background analysis jobs with stage-by-stage progress."""

import json
import shutil
import threading
import time
import traceback
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

from .config import JOBS_DIR, RENDER_DPI
from .pipeline import ai, ocr, parse, render, rules

STAGES = [
    {"id": "upload", "label": "Upload received"},
    {"id": "render", "label": "Reading drawing"},
    {"id": "ocr", "label": "Recognising text & tags"},
    {"id": "parse", "label": "Identifying equipment, lines & instruments"},
    {"id": "analyse", "label": "Building HAZOP nodes & deviations"},
    {"id": "ai", "label": "AI engineering review"},
    {"id": "done", "label": "Worksheet ready"},
]

# Overall progress (0-1) at the start of each stage.
STAGE_START = {"upload": 0.0, "render": 0.03, "ocr": 0.1, "parse": 0.82, "analyse": 0.88, "ai": 0.92, "done": 1.0}
JOB_TTL_S = 24 * 3600

_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="hazop")
_jobs: dict[str, dict] = {}
_lock = threading.Lock()


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


def create(data: bytes, filename: str, options: dict) -> dict:
    job_id = uuid.uuid4().hex[:12]
    folder = JOBS_DIR / job_id
    folder.mkdir(parents=True)
    safe_name = "".join(ch for ch in filename if ch.isalnum() or ch in "._- ") or "drawing"
    (folder / safe_name).write_bytes(data)
    job = {
        "id": job_id, "filename": filename, "status": "queued", "stage": "upload", "progress": 0.0,
        "options": options, "error": None, "warnings": [], "created": time.time(),
        "stages": [s for s in STAGES if s["id"] != "ai" or options.get("mode") == "ai"],
        "_data": data,
    }
    with _lock:
        _jobs[job_id] = job
    _executor.submit(_run, job_id)
    return _public(job)


def get(job_id: str):
    with _lock:
        job = _jobs.get(job_id)
        if job:
            return _public(job)
    meta = JOBS_DIR / job_id / "job.json"
    if meta.exists():
        return json.loads(meta.read_text(encoding="utf-8"))
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


def _run(job_id):
    job = _jobs[job_id]
    opts = job["options"]
    folder = JOBS_DIR / job_id
    timings = {}
    try:
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

        _stage(job_id, "analyse")
        t0 = time.time()
        study = opts.get("study") or {}
        result = rules.generate(ext, study)
        result["study"].update({k: v for k, v in study.items() if v})
        result["study"].setdefault("drawing", job["filename"])
        if not result["study"].get("drawing"):
            result["study"]["drawing"] = job["filename"]
        result["study"]["analysis"] = "Rule-based engine"
        timings["analyse"] = round(time.time() - t0, 1)

        if opts.get("mode") == "ai":
            _stage(job_id, "ai")
            t0 = time.time()
            try:
                result = ai.review(opts.get("provider"), page.png_bytes(max_side=2400), ext, result)
            except Exception as e:  # keep the rule-based worksheet if the AI call fails
                warnings.append(f"AI review failed, showing the rule-based worksheet instead: {e}")
            timings["ai"] = round(time.time() - t0, 1)

        payload = {
            "image": {"width": W, "height": H, "url": f"/api/jobs/{job_id}/image", "page_count": page.page_count},
            "text_method": method,
            "extraction": ext,
            "worksheet": result,
            "stats": _stats(result, ext),
            "timings": timings,
        }
        _update(job_id, status="done", stage="done", progress=1.0, result=payload, warnings=warnings,
                finished=time.time())
    except Exception as e:
        traceback.print_exc()
        _update(job_id, status="error", error=str(e) or e.__class__.__name__, finished=time.time())
    finally:
        with _lock:
            job.pop("_data", None)
            snapshot = _public(job)
        (folder / "job.json").write_text(json.dumps(snapshot, default=str), encoding="utf-8")


def cleanup():
    now = time.time()
    for folder in JOBS_DIR.iterdir():
        if folder.is_dir() and now - folder.stat().st_mtime > JOB_TTL_S:
            shutil.rmtree(folder, ignore_errors=True)
