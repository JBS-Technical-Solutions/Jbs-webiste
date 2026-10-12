"""HAZOP Studio API."""

import asyncio
import copy
import hashlib
import hmac
import json
import re
import threading
from collections import OrderedDict
from contextlib import asynccontextmanager
from datetime import date
from typing import Any

from fastapi import Body, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from starlette.concurrency import run_in_threadpool

from . import documents, jobs, limits, risk, signup
from .config import (ADMIN_KEY, BACKEND_DIR, CORS_ORIGINS, MAX_UPLOAD_MB, SIGNUP_REQUIRED, SIGNUP_VERIFY_EMAIL,
                     available_ai_providers)
from .exporters import build_docx, build_xlsx
from .pipeline.render import SUPPORTED

SAMPLES_DIR = BACKEND_DIR / "samples"
JOB_ID_RE = re.compile(r"^[0-9a-f]{12}$")
MAX_NODES = 40
MAX_NODE_TAGS = 40

async def _cleanup_hourly():
    while True:
        await run_in_threadpool(jobs.cleanup)
        await asyncio.sleep(3600)


@asynccontextmanager
async def lifespan(_app):
    signup.init()
    task = asyncio.create_task(_cleanup_hourly())
    yield
    task.cancel()


app = FastAPI(title="HAZOP Studio API", version="1.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)


def _job_or_404(job_id):
    if not JOB_ID_RE.match(job_id):
        raise HTTPException(404, "Job not found")
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return job


def _token(request: Request):
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    return token.strip() if scheme.lower() == "bearer" else None


def _require_signup(request: Request):
    if SIGNUP_REQUIRED and not signup.user_for_token(_token(request)):
        raise HTTPException(401, "Sign up free (or sign in) to run an analysis.")


def _options(mode, provider, page, study, node_mode):
    if mode not in ("rules", "ai"):
        raise HTTPException(400, "mode must be 'rules' or 'ai'")
    if node_mode not in ("auto", "user"):
        raise HTTPException(400, "node_mode must be 'auto' or 'user'")
    if mode == "ai":
        ids = [p["id"] for p in available_ai_providers()]
        if not ids:
            raise HTTPException(400, "AI mode needs an API key in backend/.env (OPENAI_API_KEY, ANTHROPIC_API_KEY or GEMINI_API_KEY).")
        provider = provider if provider in ids else ids[0]
    try:
        study_data = json.loads(study) if study else {}
    except json.JSONDecodeError:
        raise HTTPException(400, "study must be a JSON object")
    if not isinstance(study_data, dict):
        raise HTTPException(400, "study must be a JSON object")
    study_data = {k: str(v)[:300] for k, v in study_data.items()
                  if k in ("project", "client", "facility", "drawing", "revision", "date", "team") and v}
    return {"mode": mode, "provider": provider, "page": max(0, page), "study": study_data, "node_mode": node_mode}


async def _read(upload: UploadFile, label: str, allowed: set[str]):
    name = upload.filename or label
    ext = documents.ext_of(name)
    if ext not in allowed:
        kinds = ", ".join(sorted(e.lstrip(".").upper() for e in allowed))
        raise HTTPException(400, f"Unsupported {label} file type '{ext or name}'. Use {kinds}.")
    data = await upload.read()
    if len(data) > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(413, f"The {label} '{name}' is larger than {MAX_UPLOAD_MB} MB.")
    if not data:
        raise HTTPException(400, f"The {label} '{name}' is empty.")
    return name, data


_parsed = OrderedDict()
_parsed_lock = threading.Lock()


def _parse(kind, name, data):
    """Parsed document; the check on upload and the job that follows share one parse (OCR of an image is slow)."""
    key = (kind, name, hashlib.sha256(data).hexdigest())
    with _parsed_lock:
        if key in _parsed:
            _parsed.move_to_end(key)
            return copy.deepcopy(_parsed[key])
    try:
        if kind == "piping-spec":
            parsed = documents.parse_piping_spec(data, name)
        else:
            parsed = documents.parse_risk_matrix(data, name)
    except documents.DocumentError as e:
        raise HTTPException(400, str(e))
    with _parsed_lock:
        _parsed[key] = parsed
        while len(_parsed) > 20:
            _parsed.popitem(last=False)
    return copy.deepcopy(parsed)


def _describe(kind, name, parsed):
    ocr_note = " (scanned, check values)" if documents.ext_of(name) in documents.IMAGE_EXT else ""
    if kind == "piping-spec":
        summary = f"{len(parsed)} piping class{'es' if len(parsed) != 1 else ''}{ocr_note}"
        return {"kind": kind, "name": name, "summary": summary, "specs": documents.spec_summary(parsed)}
    nc, nl = risk.size(parsed)
    summary = f"{nc} x {nl} matrix, {len(parsed['bands'])} risk rankings{ocr_note}"
    return {"kind": kind, "name": name, "summary": summary, "matrix": parsed}


@app.get("/api/health")
def health():
    return {"status": "ok", "providers": available_ai_providers(), "max_upload_mb": MAX_UPLOAD_MB,
            "formats": sorted(SUPPORTED), "optional_formats": sorted(documents.OPTIONAL_EXT),
            "max_optional_docs": documents.MAX_OPTIONAL_DOCS, "signup_required": SIGNUP_REQUIRED,
            "signup_verify": SIGNUP_VERIFY_EMAIL, "samples": [p.name for p in SAMPLES_DIR.glob("*") if p.is_file()]}


@app.post("/api/signup")
def signup_direct(request: Request, payload: dict[str, Any] = Body(...)):
    """Sign up or sign in without an email code. Body: {mode: "signup"|"login", email, first_name, last_name,
    company, role}. Returns {token, user, new}."""
    if SIGNUP_VERIFY_EMAIL:
        raise HTTPException(400, "Confirm your email with the code we send you.")
    limits.check_rate(request, "signup")
    return signup.register(payload)


@app.post("/api/signup/code")
async def signup_code(request: Request, payload: dict[str, Any] = Body(...)):
    """Email a 6-digit code. Body: {mode: "signup"|"login", email, first_name, last_name, company, role}."""
    if not SIGNUP_VERIFY_EMAIL:
        raise HTTPException(404, "Email codes are switched off.")
    limits.check_rate(request, "signup")
    return await run_in_threadpool(signup.request_code, payload)


@app.post("/api/signup/verify")
def signup_verify(payload: dict[str, Any] = Body(...)):
    """Body: {email, code}. Returns {token, user, new}."""
    if not SIGNUP_VERIFY_EMAIL:
        raise HTTPException(404, "Email codes are switched off.")
    return signup.verify_code(payload)


@app.get("/api/signup/me")
def signup_me(request: Request):
    user = signup.user_for_token(_token(request))
    if not user:
        raise HTTPException(401, "Not signed in")
    return user


@app.post("/api/signup/logout")
def signup_logout(request: Request):
    signup.logout(_token(request))
    return {"ok": True}


@app.get("/api/admin/signups.xlsx")
def admin_signups(key: str = ""):
    if not ADMIN_KEY or not hmac.compare_digest(key.encode(), ADMIN_KEY.encode()):
        raise HTTPException(404, "Not found")
    return Response(signup.export_xlsx(), media_type=EXPORTS["xlsx"],
                    headers={"Content-Disposition": f'attachment; filename="HAZOP Studio sign-ups {date.today()}.xlsx"',
                             "Cache-Control": "no-store"})


@app.get("/api/risk-matrix")
def risk_matrix():
    return risk.matrix()


@app.get("/api/templates/{name}")
def template(name: str):
    if name not in documents.TEMPLATES:
        raise HTTPException(404, "Unknown template")
    download, build = documents.TEMPLATES[name]
    return Response(build(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{download}"'})


@app.post("/api/documents/{kind}")
async def check_document(request: Request, kind: str, file: UploadFile = File(...)):
    """Validate a piping specification or risk matrix before the analysis starts."""
    if kind not in ("piping-spec", "risk-matrix"):
        raise HTTPException(404, "Unknown document type")
    _require_signup(request)
    limits.check_rate(request, "documents")
    label = "piping specification" if kind == "piping-spec" else "risk matrix"
    name, data = await _read(file, label, documents.PROJECT_DOC_EXT)
    return _describe(kind, name, await run_in_threadpool(_parse, kind, name, data))


@app.post("/api/jobs")
async def create_job(
    request: Request,
    file: UploadFile = File(...),
    piping_spec: UploadFile = File(...),
    risk_matrix: UploadFile = File(...),
    optional_docs: list[UploadFile] | None = File(None),
    mode: str = Form("rules"),
    provider: str = Form(""),
    page: int = Form(0),
    study: str = Form(""),
    node_mode: str = Form("auto"),
):
    _require_signup(request)
    options = _options(mode, provider, page, study, node_mode)
    limits.check_queue(jobs.active())
    limits.check_rate(request, "jobs")
    name, data = await _read(file, "P&ID", SUPPORTED)
    spec_name, spec_data = await _read(piping_spec, "piping specification", documents.PROJECT_DOC_EXT)
    matrix_name, matrix_data = await _read(risk_matrix, "risk matrix", documents.PROJECT_DOC_EXT)
    optional = [o for o in optional_docs or [] if o.filename]
    if len(optional) > documents.MAX_OPTIONAL_DOCS:
        raise HTTPException(400, f"Attach at most {documents.MAX_OPTIONAL_DOCS} optional documents.")
    optional = [await _read(o, "optional document", documents.OPTIONAL_EXT) for o in optional]
    options["documents"] = {"piping_spec": spec_name, "risk_matrix": matrix_name, "optional": [n for n, _ in optional]}
    project = {
        "specs": await run_in_threadpool(_parse, "piping-spec", spec_name, spec_data),
        "matrix": await run_in_threadpool(_parse, "risk-matrix", matrix_name, matrix_data),
        "piping_spec": (spec_name, spec_data),
        "risk_matrix": (matrix_name, matrix_data),
        "optional": optional,
    }
    if options["mode"] == "ai":
        limits.check_ai_budget()
    return jobs.create(data, name, options, project)


@app.post("/api/jobs/sample")
def create_sample_job(request: Request, name: str = Form(""), mode: str = Form("rules"), provider: str = Form(""),
                      study: str = Form(""), node_mode: str = Form("auto")):
    """Analyse a bundled sample drawing with the built-in piping specs and the default 5 x 5 matrix."""
    samples = sorted(p for p in SAMPLES_DIR.glob("*") if p.is_file())
    sample = next((p for p in samples if p.name == name), samples[0] if samples else None)
    if not sample:
        raise HTTPException(404, "No sample drawing available")
    _require_signup(request)
    options = _options(mode, provider, 0, study, node_mode)
    limits.check_queue(jobs.active())
    limits.check_rate(request, "jobs")
    if options["mode"] == "ai":
        limits.check_ai_budget()
    return jobs.create(sample.read_bytes(), sample.name, options)


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    return _job_or_404(job_id)


def _clean_nodes(nodes):
    if not isinstance(nodes, list) or not nodes:
        raise HTTPException(400, "Define at least one node.")
    if len(nodes) > MAX_NODES:
        raise HTTPException(400, f"Define at most {MAX_NODES} nodes.")
    out = []
    for i, n in enumerate(nodes, 1):
        if not isinstance(n, dict):
            raise HTTPException(400, f"Node {i} is not valid.")
        tags = n.get("tags") if isinstance(n.get("tags"), list) else []
        tags = list(dict.fromkeys(str(t).strip().upper()[:40] for t in tags if str(t).strip()))[:MAX_NODE_TAGS]
        if not tags:
            raise HTTPException(400, f"Node {i} needs at least one equipment, instrument or line tag.")
        out.append({"title": str(n.get("title") or "").strip()[:200], "tags": tags,
                    "design_intent": str(n.get("design_intent") or "").strip()[:600]})
    return out


@app.post("/api/jobs/{job_id}/nodes")
def submit_nodes(job_id: str, payload: dict[str, Any] = Body(...)):
    """Continue a user-defined-nodes job. Body: {nodes: [{title, tags, design_intent}]}."""
    _job_or_404(job_id)
    try:
        return jobs.submit_nodes(job_id, _clean_nodes(payload.get("nodes")))
    except jobs.NotAwaitingNodes:
        raise HTTPException(409, "This analysis is not waiting for nodes.")


@app.get("/api/jobs/{job_id}/image")
def get_job_image(job_id: str):
    _job_or_404(job_id)
    path = jobs.image_path(job_id)
    if not path:
        raise HTTPException(404, "Image not ready")
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})


def _filename(worksheet, ext):
    drawing = (worksheet.get("study") or {}).get("drawing") or "P&ID"
    stem = re.sub(r"\.(pdf|png|jpe?g|tiff?|bmp|webp)$", "", drawing, flags=re.I)
    stem = re.sub(r"[^\w\-. ]+", "_", stem).strip() or "PID"
    return f"HAZOP Worksheet - {stem}.{ext}"


EXPORTS = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


@app.post("/api/export/{fmt}")
def export(request: Request, fmt: str, payload: dict[str, Any] = Body(...)):
    """Export a (possibly edited) worksheet. Body: {worksheet, extraction?}."""
    if fmt not in EXPORTS:
        raise HTTPException(404, "Unknown export format")
    limits.check_rate(request, "exports")
    worksheet = payload.get("worksheet")
    if not isinstance(worksheet, dict) or not worksheet.get("nodes"):
        raise HTTPException(400, "Body must contain a worksheet with nodes")
    worksheet.setdefault("study", {}).setdefault("date", date.today().isoformat())
    with risk.using(worksheet.get("risk_matrix")):
        if fmt == "docx":
            content = build_docx(worksheet)
        else:
            content = build_xlsx(worksheet, payload.get("extraction"))
    return Response(content, media_type=EXPORTS[fmt],
                    headers={"Content-Disposition": f'attachment; filename="{_filename(worksheet, fmt)}"'})
