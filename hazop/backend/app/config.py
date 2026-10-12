import os
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BACKEND_DIR / ".env")

KNOWLEDGE_DIR = BACKEND_DIR / "knowledge"
TEMPLATE_DOCX = BACKEND_DIR / "templates" / "hazop_template.docx"
OCR_MODELS_DIR = BACKEND_DIR / "models"
DATA_DIR = BACKEND_DIR / "data"
JOBS_DIR = DATA_DIR / "jobs"
CACHE_DIR = DATA_DIR / "ocr_cache"

for d in (JOBS_DIR, CACHE_DIR):
    d.mkdir(parents=True, exist_ok=True)

RENDER_DPI = int(os.getenv("RENDER_DPI", "300"))
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "25"))
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",") if o.strip()]

# Limits for a public deployment (0 = off). Rates are per client address; TRUST_PROXY=1 reads it from
# X-Forwarded-For, so only enable it behind a reverse proxy (Caddy in docker-compose.yml).
RATE_JOBS_PER_HOUR = int(os.getenv("RATE_JOBS_PER_HOUR", "0"))
RATE_DOCS_PER_HOUR = int(os.getenv("RATE_DOCS_PER_HOUR", "0"))
RATE_EXPORTS_PER_HOUR = int(os.getenv("RATE_EXPORTS_PER_HOUR", "0"))
AI_JOBS_PER_DAY = int(os.getenv("AI_JOBS_PER_DAY", "0"))
MAX_QUEUED_JOBS = int(os.getenv("MAX_QUEUED_JOBS", "0"))
TRUST_PROXY = os.getenv("TRUST_PROXY", "0") == "1"
JOB_TTL_HOURS = float(os.getenv("JOB_TTL_HOURS", "24"))

AI_PROVIDERS = {
    "openai": {
        "key": os.getenv("OPENAI_API_KEY", ""),
        "model": os.getenv("OPENAI_MODEL", "gpt-4o"),
        "label": "OpenAI",
    },
    "anthropic": {
        "key": os.getenv("ANTHROPIC_API_KEY", ""),
        "model": os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-5"),
        "label": "Anthropic Claude",
    },
    "gemini": {
        "key": os.getenv("GEMINI_API_KEY", ""),
        "model": os.getenv("GEMINI_MODEL", "gemini-3.8-flash"),
        "fallbacks": [m.strip() for m in os.getenv("GEMINI_FALLBACK_MODELS", "gemini-3.7-flash,gemini-3.5-flash").split(",") if m.strip()],
        "label": "Google Gemini",
    },
}


def available_ai_providers():
    return [
        {"id": pid, "label": p["label"], "model": p["model"]}
        for pid, p in AI_PROVIDERS.items()
        if p["key"]
    ]
