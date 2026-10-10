import os
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BACKEND_DIR / ".env")

KNOWLEDGE_DIR = BACKEND_DIR / "knowledge"
TEMPLATE_DOCX = BACKEND_DIR / "templates" / "hazop_template.docx"
DATA_DIR = BACKEND_DIR / "data"
JOBS_DIR = DATA_DIR / "jobs"
CACHE_DIR = DATA_DIR / "ocr_cache"

for d in (JOBS_DIR, CACHE_DIR):
    d.mkdir(parents=True, exist_ok=True)

RENDER_DPI = int(os.getenv("RENDER_DPI", "300"))
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "25"))
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",") if o.strip()]

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
