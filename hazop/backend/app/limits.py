"""Request limits for a public deployment: per-client hourly rates, a daily AI budget and a job queue cap.

All limits are off (0) unless set in .env; counters live in memory, so they reset when the engine restarts.
"""

import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request

from .config import (AI_JOBS_PER_DAY, MAX_QUEUED_JOBS, RATE_DOCS_PER_HOUR, RATE_EXPORTS_PER_HOUR, RATE_JOBS_PER_HOUR,
                     TRUST_PROXY)

HOUR = 3600
RATES = {
    "jobs": (RATE_JOBS_PER_HOUR, "analyses"),
    "documents": (RATE_DOCS_PER_HOUR, "document checks"),
    "exports": (RATE_EXPORTS_PER_HOUR, "downloads"),
}

_hits: dict[tuple[str, str], deque] = defaultdict(deque)
_ai_runs: deque = deque()
_lock = threading.Lock()


def client(request: Request) -> str:
    if TRUST_PROXY:
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _wait_text(seconds):
    minutes = max(1, round(seconds / 60))
    return f"{minutes} minute{'s' if minutes != 1 else ''}"


def check_rate(request: Request, bucket: str):
    limit, what = RATES[bucket]
    if limit <= 0:
        return
    now = time.time()
    with _lock:
        hits = _hits[bucket, client(request)]
        while hits and now - hits[0] > HOUR:
            hits.popleft()
        if len(hits) >= limit:
            raise HTTPException(429, f"Too many {what} from your network ({limit} per hour). "
                                     f"Please try again in {_wait_text(HOUR - (now - hits[0]))}.")
        hits.append(now)
        if len(_hits) > 10000:
            for key in [k for k, v in _hits.items() if not v or now - v[-1] > HOUR]:
                del _hits[key]


def check_queue(active_jobs: int):
    if MAX_QUEUED_JOBS > 0 and active_jobs >= MAX_QUEUED_JOBS:
        raise HTTPException(503, "The engine is busy with other analyses. Please try again in a few minutes.")


def check_ai_budget():
    if AI_JOBS_PER_DAY <= 0:
        return
    now = time.time()
    with _lock:
        while _ai_runs and now - _ai_runs[0] > 24 * HOUR:
            _ai_runs.popleft()
        if len(_ai_runs) >= AI_JOBS_PER_DAY:
            raise HTTPException(429, "Today's AI-assisted analyses are used up. Use rule-based mode or try again tomorrow.")
        _ai_runs.append(now)
