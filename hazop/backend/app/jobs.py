"""Background analysis jobs with stage-by-stage progress.

A job reads the drawing (render, OCR, parse) and then builds the worksheet. With user-defined nodes the job stops
after parsing in status "review" with proposed nodes; `submit_nodes` resumes it with the user's node list.
"""

import copy
import json
import re
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
from .config import CACHE_DIR, JOB_TTL_HOURS, JOBS_DIR, MAX_PID_PAGES, RENDER_DPI
from .pipeline import ai, ocr, parse, render, rules

STAGES = [
    {"id": "upload", "label": "Upload received"},
    {"id": "verify", "label": "Checking uploaded drawings"},
    {"id": "render", "label": "Reading drawing"},
    {"id": "ocr", "label": "Recognising text & tags"},
    {"id": "parse", "label": "Identifying equipment, lines & instruments"},
    {"id": "nodes", "label": "Confirming HAZOP nodes"},
    {"id": "analyse", "label": "Evaluating risk scenarios for each deviation"},
    {"id": "done", "label": "Worksheet ready"},
]

# Overall progress (0-1) at the start of each stage.
STAGE_START = {"upload": 0.0, "verify": 0.02, "render": 0.06, "ocr": 0.1, "parse": 0.82, "nodes": 0.86,
               "analyse": 0.88, "done": 1.0}
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


def _tag_bits(row):
    bits = []
    for chunk in row.get("tags") or []:
        bits.extend(part.strip() for part in re.split(r"\s*/\s*|,\s*", str(chunk)) if part.strip() and part.strip() != "-")
    return bits


def _stamp_source(ws, ext, file, page, verified):
    """Each cause records which drawing it came from, and why a reviewer should look again."""
    node_source = ws.get("node_source") or "auto"
    sheet = []
    if node_source == "auto":
        sheet.append("Node was not marked on the drawing")
    inferred = {i["tag"] for i in ext.get("instruments") or [] if i.get("inferred")}
    unknown = sorted({ln["spec"] for ln in ext.get("lines") or [] if ln.get("spec") and not ln.get("spec_known")})
    if unknown:
        shown = ", ".join(unknown[:4])
        more = f" +{len(unknown) - 4}" if len(unknown) > 4 else ""
        sheet.append(f"Piping spec {shown}{more} is not in the uploaded file")
    for node in ws.get("nodes") or []:
        for dev in node.get("deviations") or []:
            for row in dev.get("rows") or []:
                tags = _tag_bits(row)
                review = list(sheet)
                hit = [tag for tag in tags if tag in inferred]
                if hit:
                    review.insert(0, f"Inferred tag {', '.join(hit)}")
                row["source"] = {
                    "file": file,
                    "page": page,
                    "tag": tags[0] if tags else "",
                    "verified": verified,
                    "review": review,
                }


def _unread_worksheet(file, page, problem):
    low = risk.evaluate(1, 1)
    return {
        "study": {},
        "nodes": [{
            "id": 1,
            "title": file,
            "boundary": "",
            "design_intent": "",
            "design_conditions": "",
            "deviations": [{
                "deviation": "Drawing not verified",
                "rows": [{
                    "cause": f"Page {page + 1} of {file} could not be read. {problem}",
                    "consequences": ["No HAZOP causes were generated for this drawing."],
                    "cc": "S",
                    "safeguards": ["None identified on this P&ID"],
                    "tags": ["-"],
                    "c": 1,
                    "l": 1,
                    "risk": low,
                    "recommendations": [],
                    "source": {
                        "file": file,
                        "page": page,
                        "tag": "",
                        "verified": False,
                        "review": ["Page could not be verified"],
                    },
                }],
            }],
        }],
        "recommendations": {},
        "assumptions": [],
        "node_source": "auto",
    }


def _publish_checks(job_id, items, checked):
    _update(job_id, checks={
        "files": len(items),
        "drawings": sum(item["pages"] for item in items),
        "checked": checked,
        "verified": sum(item["verified"] for item in items),
        "items": [dict(item) for item in items],
    })


def _stage(job_id, stage, frac=0.0):
    stages = [s["id"] for s in STAGES]
    nxt = stages[min(stages.index(stage) + 1, len(stages) - 1)]
    lo, hi = STAGE_START[stage], STAGE_START[nxt]
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


def create(data: bytes, filename: str, options: dict, project: dict | None = None, more: list | None = None) -> dict:
    """project: {"specs", "matrix", "piping_spec": (name, bytes), "risk_matrix": (name, bytes), "pfd": (name, bytes), "optional": [(name, bytes)]}.

    more: extra P&ID files as (filename, bytes). Together with the first file they are one study, up to MAX_PID_PAGES sheets.
    """
    project = project or {}
    job_id = uuid.uuid4().hex[:12]
    folder = JOBS_DIR / job_id
    folder.mkdir(parents=True)
    draw_dir = folder / "drawings"
    draw_dir.mkdir()
    stored = []
    for index, (name, blob) in enumerate([(filename, data), *(more or [])]):
        path = draw_dir / f"{index:03d}-{_safe(name)}"
        path.write_bytes(blob)
        stored.append({"path": str(path), "name": name})
    filename = filename if len(stored) == 1 else f"{len(stored)} P&IDs"
    docs_dir = folder / "documents"
    named = [project[k] for k in ("piping_spec", "risk_matrix", "pfd") if project.get(k)] + list(project.get("optional") or [])
    if named:
        docs_dir.mkdir()
        for name, blob in named:
            (docs_dir / _safe(name)).write_bytes(blob)
    node_mode = options.get("node_mode", "auto")
    job = {
        "id": job_id, "filename": filename, "status": "queued", "stage": "upload", "progress": 0.0,
        "options": options, "error": None, "warnings": [], "created": time.time(),
        "stages": [s for s in STAGES if s["id"] != "nodes" or node_mode == "user"],
        "_drawings": stored,
        "_specs": project.get("specs"),
        "_matrix": project.get("matrix"),
        "_optional": list(project.get("optional") or []),
        "_pfd": (
            {"path": str(docs_dir / _safe(project["pfd"][0])), "name": project["pfd"][0]}
            if project.get("pfd") else None
        ),
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


def image_path(job_id: str, page: int = 0):
    """Preview of one sheet. Page 0 falls back to the single-page preview written by older jobs."""
    page = max(0, int(page))
    p = JOBS_DIR / job_id / "pages" / f"{page:04d}.png"
    if p.exists():
        return p
    legacy = JOBS_DIR / job_id / "page.png"
    return legacy if page == 0 and legacy.exists() else None


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
        for key in ("_data", "_page", "_ext", "_optional", "_pending", "_pfd_note", "_pfd_study", "_purpose", "_matrix_note"):
            job.pop(key, None)
    _update(job_id, status="error", error=str(e) or e.__class__.__name__, finished=time.time())
    _snapshot(job_id)


_GROUPS = ("equipment", "instruments", "lines", "valves", "connectors", "spec_breaks")


def _blank_extraction():
    return {
        **{k: [] for k in _GROUPS},
        "flags": {"sour_service": False, "car_sealed": False, "interlocks": 0},
        "token_count": 0,
    }


def _stamp_page(ext, page):
    """Mark every entity with its sheet and give it an id that cannot collide with another sheet."""
    for key in _GROUPS:
        for ent in ext.get(key) or []:
            ent["page"] = page
            if ent.get("id"):
                ent["id"] = f"S{page + 1}-{ent['id']}"
    ext.pop("tokens", None)


def _merge_extraction(dst, src):
    for key in _GROUPS:
        dst[key].extend(src.get(key) or [])
    dst["token_count"] += src.get("token_count") or 0
    flags, src_flags = dst["flags"], src.get("flags") or {}
    flags["sour_service"] = flags["sour_service"] or bool(src_flags.get("sour_service"))
    flags["car_sealed"] = flags["car_sealed"] or bool(src_flags.get("car_sealed"))
    flags["interlocks"] += int(src_flags.get("interlocks") or 0)


def _combine_sheets(parts, filename, page_count):
    """One worksheet per node, in node-number order. Recommendation ids are unique across the whole set."""
    nodes, recs = [], {}
    next_r = 1
    collected = []
    for sheet_index, (label, result) in enumerate(parts):
        mapping = {}
        for old, text in (result.get("recommendations") or {}).items():
            new = f"R-{next_r:02d}"
            next_r += 1
            mapping[old] = new
            recs[new] = text
        for node in result.get("nodes") or []:
            node = copy.deepcopy(node)
            match = re.search(r"\bNode\s+(\d+)\b", str(node.get("title") or ""), re.I)
            number = int(match.group(1)) if match else 10000 + sheet_index
            for dev in node.get("deviations") or []:
                for row in dev.get("rows") or []:
                    row["recommendations"] = [mapping[x] for x in row.get("recommendations") or [] if x in mapping]
            collected.append((number, sheet_index, label, node))
    collected.sort(key=lambda item: (item[0], item[1]))
    for number, _sheet, label, node in collected:
        nid = len(nodes) + 1
        node["id"] = nid
        node["title"] = f"{label} · {node.get('title') or 'Node'}" if label else (node.get("title") or "Node")
        for i, dev in enumerate(node.get("deviations") or [], 1):
            name = re.sub(r"^\s*\d+(?:\.\d+)*\s*", "", str(dev.get("deviation") or "Deviation"))
            dev["deviation"] = f"{nid}.{i} {name}"
        nodes.append(node)
    first = parts[0][1]
    study = dict(first.get("study") or {})
    study["facility"] = f"{filename} · {page_count} sheets"
    assumptions = [
        f"The {page_count} P&ID sheets were read first. Each node was then written on its own, in node-number order, "
        "so equipment on one drawing is not mixed with another.",
        *(first.get("assumptions") or []),
    ]
    if any(r.get("node_source") == "drawing" for _, r in parts):
        note = "Where a sheet was already marked with node numbers, those nodes were used for its worksheet."
        if note not in assumptions:
            assumptions.append(note)
    return {"study": study, "nodes": nodes, "recommendations": recs, "assumptions": assumptions}


def _equipment_names(ext, limit=10):
    """On-sheet equipment as 'TAG (name)', in the order the drawing was read."""
    names = []
    for item in ext.get("equipment") or []:
        if item.get("offpage") or item.get("kind") in ("panel", "package"):
            continue
        label = (item.get("description") or item.get("kind") or "equipment").strip()
        names.append(f"{item.get('tag')} ({label})")
        if len(names) >= limit:
            break
    return names


def _learn_pfd(job_id, info):
    """Read the PFD from its inlet, keep every word, and follow the stream through each element."""
    from .pipeline import pfd

    drawing = render.open_drawing_path(info["path"], info["name"], RENDER_DPI)
    pages = []
    try:
        total = drawing.page_count
        cap = min(total, 30)
        _update(job_id, detail=f"Reading PFD '{info['name']}' from its start point ({cap} of {total} page{'s' if total != 1 else ''})")
        for i in range(cap):
            _update(job_id, detail=f"Reading every line of PFD page {i + 1} of {cap} · {info['name']}")
            page = drawing.load_page(i)
            tokens, _method = ocr.extract_text(page)
            extra = pfd.read_balance_images(drawing.doc, drawing.doc[i], page) if drawing.doc is not None else []
            page_ext = parse.parse(tokens, page.size)
            width, height = page.size
            del page
            for token in extra:
                box = token["box"]
                page_ext.setdefault("tokens", []).append({
                    "text": token["text"],
                    "box": [box[0] / width, box[1] / height, box[2] / width, box[3] / height],
                    "page": i,
                })
            for token in page_ext.get("tokens") or []:
                token["page"] = i
            for key in _GROUPS:
                for ent in page_ext.get(key) or []:
                    ent["page"] = i
            pages.append(page_ext)
    finally:
        drawing.close()
    _update(job_id, detail="Reading the heat and material balance, then following the process stream")
    study = pfd.understand(pages)
    tags = [step["tag"] for step in study["route"] if step.get("tag")]
    return {
        "name": info["name"],
        "pages": len(pages),
        "tags": tags,
        "study": study,
        "note": pfd.note(info["name"], study, len(pages), total),
    }


def _purpose_from_docs(pfd):
    """Why the P&ID exists, from the piping specification, PFD and risk matrix, before the drawing is opened."""
    study = (pfd or {}).get("study") or {}
    route = [step["tag"] for step in study.get("route") or [] if step.get("tag")]
    focus = ", ".join(route[:6]) if route else (
        ", ".join((pfd or {}).get("tags") or []) or "the process equipment learned from the PFD")
    flow = f" The PFD was read from its inlet and the stream was followed through {focus}." if route else ""
    classes = list(kb.specs())
    class_note = ""
    if classes:
        listed = ", ".join(classes[:6])
        more = f" and {len(classes) - 6} more" if len(classes) > 6 else ""
        class_note = f" The piping classes learned first ({listed}{more}) set the rating and service of those lines."
    matrix_note = ""
    try:
        matrix = risk.project_matrix()
        nc, nl = risk.size(matrix)
        matrix_note = f" Consequences are ranked on the {nc} x {nl} risk matrix '{matrix['source']}'."
    except risk.MatrixRequired:
        matrix_note = ""
    return (
        "Before the P&ID was opened, the piping specification, the PFD and the risk matrix were read and learned. "
        f"The purpose of the P&ID is the detailed piping, instruments and valves for {focus}.{flow}{class_note}{matrix_note}"
    )


def _purpose_text(pid, pfd, purpose):
    """Confirm the purpose once the P&ID itself has been read."""
    pid_names = _equipment_names(pid, 8)
    pfd_tags = set((pfd or {}).get("tags") or [])
    shared = [name for name in pid_names if name.split(" ", 1)[0] in pfd_tags]
    focus = shared or pid_names
    if not focus:
        return purpose
    link = "confirmed from the PFD" if shared else "read on the P&ID"
    return purpose + " The P&ID was then read, and this purpose was " + link + " on " + ", ".join(focus[:6]) + "."


def _note_warnings(warnings, ext, has_specs):
    if not (ext["equipment"] or ext["instruments"] or ext["lines"]):
        warnings.append("Very little engineering text was recognised. Check that the upload is a P&ID with legible tags.")
    inferred = [i["tag"] for i in ext["instruments"] if i.get("inferred")]
    if inferred:
        shown = ", ".join(inferred[:8])
        more = f" and {len(inferred) - 8} more" if len(inferred) > 8 else ""
        warnings.append(f"{shown}{more} inferred from a control loop (tag text not legible on the drawing).")
    missing = sorted({ln["spec"] for ln in ext["lines"] if not ln["spec_known"]})
    if missing and has_specs:
        shown = ", ".join(missing[:12])
        more = f" and {len(missing) - 12} more" if len(missing) > 12 else ""
        warnings.append(f"Piping spec {shown}{more} used on the drawing is not in the uploaded piping "
                        f"specification; ratings for those lines are not checked.")


def _extract(job_id):
    job = _jobs[job_id]
    opts = job["options"]
    folder = JOBS_DIR / job_id
    timings = {}
    drawing = None
    try:
        with _project(job):
            learned = kb.learn_piping()
            shown = ", ".join(item["code"] for item in learned[:6])
            extra = f" +{len(learned) - 6}" if len(learned) > 6 else ""
            origin = "Uploaded piping specification" if kb.has_project_specs() else "Piping specification"
            _update(job_id, status="running",
                    detail=f"{origin} learned before the PFD and the P&ID: {len(learned)} classes ({shown}{extra})")
            pfd_learned = _learn_pfd(job_id, job["_pfd"]) if job.get("_pfd") else None
            if pfd_learned:
                job["_pfd_study"] = pfd_learned.get("study")
            matrix_note = None
            try:
                matrix_note = risk.describe()
            except risk.MatrixRequired:
                matrix_note = None
            if matrix_note:
                _update(job_id, detail=matrix_note[:180])
            purpose = _purpose_from_docs(pfd_learned)
            _update(job_id, detail=purpose[:180])
            _update(job_id, detail="Purpose understood. Reading the P&ID.")
            _update(job_id, detail="Counting pages in each P&ID")
            _stage(job_id, "verify")
            t0 = time.time()
            inventory = []
            checks = []
            total = 0
            for item in job.get("_drawings") or []:
                try:
                    info = render.describe_drawing(item["path"], item["name"])
                    n_pages = info["pages"]
                    checks.append({
                        "name": item["name"], "kind": info["kind"], "pages": n_pages,
                        "verified": 0, "failed": 0, "status": "ready",
                    })
                except Exception as e:
                    n_pages = 1
                    checks.append({
                        "name": item["name"], "kind": "pdf" if item["name"].lower().endswith(".pdf") else "image",
                        "pages": 1, "verified": 0, "failed": 0, "status": "unreadable",
                        "problem": str(e) or e.__class__.__name__,
                    })
                inventory.append((item, n_pages))
                total += n_pages
            _publish_checks(job_id, checks, 0)
            files = len(checks)
            _update(job_id, detail=f"Found {total} drawing{'s' if total != 1 else ''} in {files} file{'s' if files != 1 else ''}")
            _stage(job_id, "render")
            count = min(total, MAX_PID_PAGES)
            multi = count > 1
            many_files = len(inventory) > 1
            pages_dir = folder / "pages"
            pages_dir.mkdir(exist_ok=True)
            ext = _blank_extraction()
            sizes = []
            methods = []
            pending = []
            failed = []
            seen = 0
            for file_index, (item, n_pages) in enumerate(inventory):
                if seen >= count:
                    break
                check = checks[file_index]
                check["status"] = "checking" if check["status"] != "unreadable" else "unreadable"
                _publish_checks(job_id, checks, seen)
                try:
                    drawing = render.open_drawing_path(item["path"], item["name"], RENDER_DPI)
                except Exception as e:
                    for i in range(n_pages):
                        if seen >= count:
                            break
                        problem = str(e) or e.__class__.__name__
                        failed.append((seen + 1, problem))
                        check["failed"] += 1
                        sizes.append({"width": 800, "height": 520})
                        (pages_dir / f"{seen:04d}.png").write_bytes(render.blank_png())
                        if multi:
                            label = item["name"] if n_pages == 1 else f"{item['name']} p.{seen + 1}"
                            pending.append({
                                "label": label, "file": item["name"], "page": seen, "problem": problem,
                            })
                        seen += 1
                    check["status"] = "unreadable"
                    check["problem"] = str(e) or e.__class__.__name__
                    _publish_checks(job_id, checks, seen)
                    continue
                try:
                    for i in range(n_pages):
                        if seen >= count:
                            break
                        where = item["name"] if n_pages == 1 else f"{item['name']} · page {i + 1} of {n_pages}"
                        _update(job_id, detail=f"Verifying drawing {seen + 1} of {count} · {where}")
                        _stage(job_id, "ocr" if seen else "render", seen / max(count, 1))

                        def _tick(frac, index=seen):
                            _stage(job_id, "ocr", (index + frac) / max(count, 1))

                        label = None
                        if many_files:
                            label = item["name"] if n_pages == 1 else f"{item['name']} p.{i + 1}"
                        elif n_pages > 1:
                            label = f"Sheet {i + 1}"
                        try:
                            page = drawing.load_page(i)
                            W, H = page.size
                            preview_side = 1400 if multi else 3600
                            (pages_dir / f"{seen:04d}.png").write_bytes(page.png_bytes(max_side=preview_side))
                            if seen == 0:
                                (folder / "page.png").write_bytes((pages_dir / "0000.png").read_bytes())
                            sizes.append({"width": W, "height": H})
                            tokens, method = ocr.extract_text(page, progress=_tick)
                            methods.append(method)
                            page_ext = parse.parse(tokens, (W, H))
                            page_ext["node_colors"] = list(getattr(page, "node_colors", None) or [])
                            del page
                            if multi:
                                pending.append({
                                    "label": label, "ext": page_ext, "file": item["name"], "page": seen,
                                })
                                stored = copy.deepcopy(page_ext)
                                stored.pop("node_colors", None)
                                _stamp_page(stored, seen)
                                _merge_extraction(ext, stored)
                            else:
                                ext = page_ext
                        except Exception as e:
                            problem = str(e) or e.__class__.__name__
                            failed.append((seen + 1, problem))
                            check["failed"] += 1
                            sizes.append({"width": 800, "height": 520})
                            (pages_dir / f"{seen:04d}.png").write_bytes(render.blank_png())
                            if multi:
                                pending.append({
                                    "label": label, "file": item["name"], "page": seen, "problem": problem,
                                })
                        else:
                            check["verified"] += 1
                        seen += 1
                        _publish_checks(job_id, checks, seen)
                    if check["status"] != "unreadable":
                        if check["failed"] and check["verified"]:
                            check["status"] = "partial"
                        elif check["failed"]:
                            check["status"] = "unreadable"
                        elif check["verified"]:
                            check["status"] = "ok"
                    _publish_checks(job_id, checks, seen)
                finally:
                    drawing.close()
                    drawing = None
            for check in checks:
                if check["status"] == "ready":
                    check["status"] = "skipped"
            _publish_checks(job_id, checks, seen)
            timings["render"] = round(time.time() - t0, 1)
            if not sizes:
                raise RuntimeError("No P&ID sheets were found in the upload.")
            if len(failed) == count:
                raise RuntimeError(f"None of the {count} sheets could be read. {failed[0][1]}")
            if multi and not any(item.get("ext") for item in pending):
                raise RuntimeError(
                    "No P&ID sheets could be read. Check that the pages are P&IDs with legible tags."
                )
            purpose = _purpose_text(ext, pfd_learned, purpose)
            _update(job_id, detail="P&ID read. Nodes will be studied one at a time, in node-number order.")

        warnings = []
        if total > count:
            warnings.append(
                f"This upload has {total} P&ID sheets. The rule engine analysed the first {count} "
                f"(the limit is {MAX_PID_PAGES})."
            )
        if failed:
            shown = ", ".join(str(n) for n, _ in failed[:12])
            more = f" and {len(failed) - 12} more" if len(failed) > 12 else ""
            warnings.append(f"Sheet {shown}{more} could not be read. The other sheets were still analysed.")
        if multi and opts.get("node_mode") == "user":
            warnings.append("More than one P&ID was uploaded, so the rule engine identified the nodes on every sheet itself.")
        _note_warnings(warnings, ext, bool(job.get("_specs")))
        method = methods[0] if methods and all(m == methods[0] for m in methods) else "mixed"
        W, H = sizes[0]["width"], sizes[0]["height"]
        image = {
            "width": W, "height": H, "url": f"/api/jobs/{job_id}/image",
            "page_count": count, "pages": sizes,
        }

        with _lock:
            job.pop("_data", None)
            job.update(_page=None, _ext=ext, _method=method, _timings=timings, _size=(W, H), _image=image,
                       _pending=pending if multi else None, _purpose=purpose,
                       _pfd_note=(pfd_learned or {}).get("note"), _matrix_note=matrix_note)
            job["warnings"] = warnings
        if not multi and opts.get("node_mode") == "user":
            with _project(job):
                proposals = rules.plan_nodes(ext)
            ext.pop("node_colors", None)
            _update(job_id, status="review", stage="nodes", progress=STAGE_START["nodes"], detail=None, review={
                "image": image, "text_method": method, "extraction": ext, "proposed_nodes": proposals,
            })
            _snapshot(job_id)
            return
    except Exception as e:
        _fail(job_id, e)
        return
    finally:
        if drawing is not None:
            drawing.close()
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


def _plan_number(entry):
    number = entry.get("number")
    try:
        return int(number)
    except (TypeError, ValueError):
        match = re.search(r"\bNode\s+(\d+)\b", str(entry.get("title") or ""), re.I)
        return int(match.group(1)) if match else 10000


def _references(job):
    docs = job["options"].get("documents") or {}
    parts = [f"P&ID {job['filename']}"]
    if docs.get("piping_spec"):
        parts.append(f"piping specification {docs['piping_spec']}")
    else:
        parts.append("piping specifications")
    if docs.get("risk_matrix"):
        parts.append(f"risk matrix {docs['risk_matrix']}")
    if docs.get("pfd"):
        parts.append(f"PFD {docs['pfd']}")
    parts += docs.get("optional") or []
    return f"{BASE_REFERENCES}, " + ", ".join(parts)


def _review_with_model(job_id, result, ext, page, warnings):
    """The reading steps are already done. The model may only tighten causes, consequences and safeguards."""
    job = _jobs[job_id]
    opts = job.get("options") or {}
    if opts.get("mode") != "ai":
        return result
    provider = opts.get("provider") or "gemini"
    png = image_path(job_id, page)
    if png is None or not png.exists():
        warnings.append("The model review was skipped because the drawing preview was not available.")
        return result
    _update(job_id, detail="Reviewing the worksheet on the P&ID. The node summary, purpose and design conditions stay as written.")
    attachments = []
    pfd = job.get("_pfd_study")
    if pfd:
        attachments.append({"name": "PFD", "text": json.dumps(pfd, default=str)[:6000]})
    try:
        reviewed = ai.review(provider, png.read_bytes(), ext, result, attachments, fixed_nodes=True)
    except ai.AIError as e:
        warnings.append(f"The model review was skipped: {e}")
        return result
    note = ("The worksheet was written from the PFD and the P&ID first. "
            "The model then checked causes, consequences and safeguards against the drawing. "
            "The node summary, the overall purpose and the main-equipment conditions were kept, and no new tag was added.")
    notes = reviewed.setdefault("assumptions", [])
    if note not in notes:
        notes.append(note)
    return reviewed


def _analyse(job_id):
    job = _jobs[job_id]
    opts = job["options"]
    timings = job["_timings"]
    ext = job["_ext"]
    pending = job.get("_pending")
    warnings = list(job["warnings"])
    try:
        with _project(job):
            _stage(job_id, "analyse")
            purpose = job.get("_purpose")
            if purpose:
                _update(job_id, detail=purpose[:180])
            t0 = time.time()
            study = opts.get("study") or {}

            def _on_plan(plan, where=""):
                labels = []
                for entry in plan:
                    title = (entry.get("title") or "").strip() or "Node"
                    number = entry.get("number")
                    labels.append(f"{number} {title}" if number else title)
                shown = ", ".join(labels[:8])
                more = f" and {len(labels) - 8} more" if len(labels) > 8 else ""
                prefix = f"{where} · " if where else ""
                _update(job_id, detail=f"{prefix}Nodes read in order: {shown}{more}. Each node is written on its own before the next.")

            def _on_part(i, n, entry, where=""):
                title = (entry.get("title") or "").strip() or f"Node {i}"
                prefix = f"{where} · " if where else ""
                _update(job_id, detail=f"{prefix}Writing node {i} of {n} · {title}")
                _stage(job_id, "analyse", (i - 1) / max(n, 1))

            if pending:
                ordered = []
                for sheet_index, item in enumerate(pending):
                    if item.get("problem"):
                        ordered.append((10 ** 9, sheet_index, item, None, None))
                        continue
                    plan, source = rules.study_plan(item["ext"])
                    if not plan:
                        ordered.append((10 ** 9, sheet_index, item, None, source))
                        continue
                    for entry in plan:
                        ordered.append((_plan_number(entry), sheet_index, item, entry, source))
                ordered.sort(key=lambda unit: (unit[0], unit[1]))
                labels = []
                for number, _sheet, item, entry, _source in ordered:
                    if not entry:
                        continue
                    title = (entry.get("title") or "").strip() or "Node"
                    where = item.get("label") or ""
                    labels.append(f"{where} {title}".strip() if where else title)
                if labels:
                    shown = ", ".join(labels[:8])
                    more = f" and {len(labels) - 8} more" if len(labels) > 8 else ""
                    _update(job_id, detail=f"All nodes read. Writing in order: {shown}{more}.")
                sheets = []
                empty = 0
                writable = [unit for unit in ordered if unit[3]]
                for index, (_number, _sheet, item, entry, source) in enumerate(writable, 1):
                    _on_part(index, len(writable), entry, item.get("label") or "")
                    page_ext = item["ext"]
                    page_ws = rules.generate(page_ext, study, prepared=([entry], source))
                    page_ws = _review_with_model(job_id, page_ws, page_ext, item["page"], warnings)
                    page_ext.pop("node_colors", None)
                    _stamp_source(page_ws, page_ext, item["file"], item["page"], True)
                    if page_ws.get("nodes"):
                        sheets.append((item.get("label"), page_ws))
                    else:
                        empty += 1
                for _number, _sheet, item, entry, _source in ordered:
                    if entry is None and item.get("problem"):
                        sheets.append((item.get("label"), _unread_worksheet(item["file"], item["page"], item["problem"])))
                if empty:
                    warnings.append(f"{empty} nodes had no equipment, lines or instruments to study.")
                if not any(ws.get("nodes") for _label, ws in sheets):
                    raise RuntimeError(
                        "No HAZOP nodes could be built from this PDF. Check that the pages are P&IDs with legible tags."
                    )
                result = _combine_sheets(sheets, job["filename"], job["_image"]["page_count"])
            else:
                result = rules.generate(ext, study, job.get("_nodes"), on_part=_on_part, on_plan=_on_plan)
                result = _review_with_model(job_id, result, ext, 0, warnings)
                ext.pop("node_colors", None)
                _stamp_source(result, ext, job["filename"], 0, True)
            result["study"].update({k: v for k, v in study.items() if v})
            if not result["study"].get("drawing"):
                result["study"]["drawing"] = job["filename"]
            result["study"]["reference_documents"] = _references(job)
            result["study"]["analysis"] = "Rule-based engine"
            notes = result.setdefault("assumptions", [])
            if job.get("_pfd_note") and job["_pfd_note"] not in notes:
                notes.append(job["_pfd_note"])
            if job.get("_pfd_study"):
                result["pfd"] = job["_pfd_study"]
            matrix_note = job.get("_matrix_note") or risk.describe()
            if matrix_note not in notes:
                notes.append(matrix_note)
            if purpose and purpose not in notes:
                notes.append(purpose)
            checked = job.get("checks")
            if checked:
                noun = "drawing" if checked["drawings"] == 1 else "drawings"
                file_noun = "file" if checked["files"] == 1 else "files"
                result.setdefault("assumptions", []).append(
                    f"Before the study, the upload was checked: {checked['drawings']} {noun} in {checked['files']} {file_noun}. "
                    "Each PDF page was counted and every drawing was opened."
                )
            timings["analyse"] = round(time.time() - t0, 1)
            result["risk_matrix"] = risk.current()

        payload = {
            "image": job["_image"],
            "text_method": job["_method"],
            "extraction": ext,
            "worksheet": result,
            "stats": _stats(result, ext),
            "timings": timings,
        }
        with _lock:
            for key in ("_page", "_ext", "_optional", "_pending", "_image", "_pfd_note", "_pfd_study", "_purpose", "_matrix_note"):
                job.pop(key, None)
        _update(job_id, status="done", stage="done", progress=1.0, detail=None, result=payload, warnings=warnings,
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
