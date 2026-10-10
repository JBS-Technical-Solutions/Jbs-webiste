"""HAZOP Studio API."""

import json
import re
from contextlib import asynccontextmanager
from datetime import date
from typing import Any

from fastapi import Body, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response

from . import jobs
from .config import BACKEND_DIR, CORS_ORIGINS, MAX_UPLOAD_MB, available_ai_providers
from .exporters import build_docx, build_xlsx
from .pipeline.render import SUPPORTED
from .risk import matrix

SAMPLES_DIR = BACKEND_DIR / "samples"
JOB_ID_RE = re.compile(r"^[0-9a-f]{12}$")

@asynccontextmanager
async def lifespan(_app):
    jobs.cleanup()
    yield


app = FastAPI(title="HAZOP Studio API", version="1.0.0", lifespan=lifespan)
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


def _options(mode, provider, page, study):
    if mode not in ("rules", "ai"):
        raise HTTPException(400, "mode must be 'rules' or 'ai'")
    if mode == "ai":
        ids = [p["id"] for p in available_ai_providers()]
        if not ids:
            raise HTTPException(400, "AI mode needs an API key in backend/.env (OPENAI_API_KEY, ANTHROPIC_API_KEY or GEMINI_API_KEY).")
        provider = provider if provider in ids else ids[0]
    try:
        study_data = json.loads(study) if study else {}
    except json.JSONDecodeError:
        raise HTTPException(400, "study must be a JSON object")
    study_data = {k: str(v)[:300] for k, v in study_data.items()
                  if k in ("project", "client", "facility", "drawing", "revision", "date", "team") and v}
    return {"mode": mode, "provider": provider, "page": max(0, page), "study": study_data}


@app.get("/api/health")
def health():
    return {"status": "ok", "providers": available_ai_providers(), "max_upload_mb": MAX_UPLOAD_MB,
            "formats": sorted(SUPPORTED), "samples": [p.name for p in SAMPLES_DIR.glob("*") if p.is_file()]}


@app.get("/api/risk-matrix")
def risk_matrix():
    return matrix()


@app.post("/api/jobs")
async def create_job(
    file: UploadFile = File(...),
    mode: str = Form("rules"),
    provider: str = Form(""),
    page: int = Form(0),
    study: str = Form(""),
):
    name = file.filename or "drawing"
    ext = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext not in SUPPORTED:
        raise HTTPException(400, f"Unsupported file type '{ext or name}'. Upload a PDF, PNG, JPG or TIFF P&ID.")
    data = await file.read()
    if len(data) > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(413, f"File is larger than {MAX_UPLOAD_MB} MB.")
    if not data:
        raise HTTPException(400, "The uploaded file is empty.")
    return jobs.create(data, name, _options(mode, provider, page, study))


@app.post("/api/jobs/sample")
def create_sample_job(name: str = Form(""), mode: str = Form("rules"), provider: str = Form(""),
                      study: str = Form("")):
    samples = sorted(p for p in SAMPLES_DIR.glob("*") if p.is_file())
    sample = next((p for p in samples if p.name == name), samples[0] if samples else None)
    if not sample:
        raise HTTPException(404, "No sample drawing available")
    return jobs.create(sample.read_bytes(), sample.name, _options(mode, provider, 0, study))


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    return _job_or_404(job_id)


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
    "json": "application/json",
}


@app.post("/api/export/{fmt}")
def export(fmt: str, payload: dict[str, Any] = Body(...)):
    """Export a (possibly edited) worksheet. Body: {worksheet, extraction?}."""
    if fmt not in EXPORTS:
        raise HTTPException(404, "Unknown export format")
    worksheet = payload.get("worksheet")
    if not isinstance(worksheet, dict) or not worksheet.get("nodes"):
        raise HTTPException(400, "Body must contain a worksheet with nodes")
    worksheet.setdefault("study", {}).setdefault("date", date.today().isoformat())
    if fmt == "docx":
        content = build_docx(worksheet)
    elif fmt == "xlsx":
        content = build_xlsx(worksheet, payload.get("extraction"))
    else:
        content = json.dumps({"worksheet": worksheet, "extraction": payload.get("extraction")}, indent=2).encode()
    return Response(content, media_type=EXPORTS[fmt],
                    headers={"Content-Disposition": f'attachment; filename="{_filename(worksheet, fmt)}"'})
