"""Risk matrices: the generic 5 x 5 matrix and project matrices (e.g. 5 x 5 or 6 x 6) uploaded as Excel.

A matrix is {"name", "source", "severity": [{level, name, desc}], "likelihood": [...], "bands": [{code, name, color}],
"cells": [[code per likelihood] per consequence level]}. The matrix used for evaluation is set per job / request
with `using(matrix)`; everything else falls back to the generic matrix.
"""

import re
from contextlib import contextmanager
from contextvars import ContextVar

BAND_ORDER = ["L", "M", "H", "VH"]
BAND_DEFAULTS = {
    "L": {"name": "Low", "color": "#C6EFCE"},
    "M": {"name": "Medium", "color": "#FFFF80"},
    "H": {"name": "High", "color": "#FFC000"},
    "VH": {"name": "Very High", "color": "#FF7C80"},
}

# Generic matrix: band by score C x L.
RISK_BANDS = [
    {"max": 4, "code": "L", "name": "Low", "color": "#C6EFCE"},
    {"max": 9, "code": "M", "name": "Medium", "color": "#FFFF80"},
    {"max": 16, "code": "H", "name": "High", "color": "#FFC000"},
    {"max": 25, "code": "VH", "name": "Very High", "color": "#FF7C80"},
]

SEVERITY = [
    {"level": 1, "name": "Minor", "desc": "First aid injury; negligible release; minimal production impact"},
    {"level": 2, "name": "Moderate", "desc": "Medical treatment / restricted work; minor release; short production loss"},
    {"level": 3, "name": "Serious", "desc": "Lost time injury; contained release; equipment damage / significant production loss"},
    {"level": 4, "name": "Major", "desc": "Permanent disability or single fatality; significant release / fire"},
    {"level": 5, "name": "Catastrophic", "desc": "Multiple fatalities; major fire / explosion; major environmental damage"},
]

LIKELIHOOD = [
    {"level": 1, "name": "Remote", "desc": "Not expected in facility life (< 1E-4 /yr)"},
    {"level": 2, "name": "Unlikely", "desc": "Could occur in facility life (1E-4 to 1E-3 /yr)"},
    {"level": 3, "name": "Possible", "desc": "Has occurred in industry (1E-3 to 1E-2 /yr)"},
    {"level": 4, "name": "Likely", "desc": "Has occurred at company sites (1E-2 to 1E-1 /yr)"},
    {"level": 5, "name": "Frequent", "desc": "Expected to occur several times (> 1E-1 /yr)"},
]

MIN_LEVELS, MAX_LEVELS = 3, 8


def _score_band(score):
    for b in RISK_BANDS:
        if score <= b["max"]:
            return b
    return RISK_BANDS[-1]


DEFAULT_MATRIX = {
    "name": "Generic 5 x 5 risk matrix",
    "source": None,
    "severity": SEVERITY,
    "likelihood": LIKELIHOOD,
    "bands": [{"code": b["code"], "name": b["name"], "color": b["color"]} for b in RISK_BANDS],
    "cells": [[_score_band(c * l)["code"] for l in range(1, 6)] for c in range(1, 6)],
}

_active = ContextVar("risk_matrix", default=None)


def _levels(items, n):
    out = []
    for i in range(n):
        it = items[i] if i < len(items) and isinstance(items[i], dict) else {}
        out.append({"level": i + 1, "name": str(it.get("name") or f"Level {i + 1}")[:60],
                    "desc": str(it.get("desc") or "")[:300]})
    return out


def validate(m):
    """Return a clean copy of a matrix, or None if it is not usable."""
    if not isinstance(m, dict):
        return None
    cells = m.get("cells")
    if not isinstance(cells, list) or not cells or not all(isinstance(r, list) for r in cells):
        return None
    nc, nl = len(cells), len(cells[0])
    if not (MIN_LEVELS <= nc <= MAX_LEVELS and MIN_LEVELS <= nl <= MAX_LEVELS) or any(len(r) != nl for r in cells):
        return None
    if any(code not in BAND_ORDER for r in cells for code in r):
        return None
    given = {b.get("code"): b for b in m.get("bands") or [] if isinstance(b, dict)}
    used = sorted({code for r in cells for code in r}, key=BAND_ORDER.index)
    bands = []
    for code in used:
        b = given.get(code) or {}
        color = str(b.get("color") or "")
        if not re.fullmatch(r"#[0-9A-Fa-f]{6}", color):
            color = BAND_DEFAULTS[code]["color"]
        bands.append({"code": code, "name": str(b.get("name") or BAND_DEFAULTS[code]["name"])[:40], "color": color.upper()})
    scores = _score_grid(m.get("scores"), nc, nl)
    return {
        "name": str(m.get("name") or f"{nc} x {nl} risk matrix")[:120],
        "source": str(m["source"])[:200] if m.get("source") else None,
        "severity": _levels(m.get("severity") or [], nc),
        "likelihood": _levels(m.get("likelihood") or [], nl),
        "bands": bands,
        "cells": [list(r) for r in cells],
        "scores": scores,
        "score_higher_is_worse": bool(m.get("score_higher_is_worse", True)) if scores else True,
    }


def _score_grid(scores, nc, nl):
    """The risk number written in each matrix cell, or None when the file only has band names."""
    if not isinstance(scores, list) or len(scores) != nc or any(not isinstance(r, list) or len(r) != nl for r in scores):
        return None
    if any(not isinstance(x, int) or isinstance(x, bool) for r in scores for x in r):
        return None
    return [list(r) for r in scores]


def current():
    return _active.get() or DEFAULT_MATRIX


@contextmanager
def using(matrix):
    token = _active.set(validate(matrix) if matrix else None)
    try:
        yield current()
    finally:
        _active.reset(token)


def size(m=None):
    m = m or current()
    return len(m["severity"]), len(m["likelihood"])


def band_info(code, m=None):
    m = m or current()
    b = next((x for x in m["bands"] if x["code"] == code), None)
    return b or {"code": code, **BAND_DEFAULTS.get(code, BAND_DEFAULTS["M"])}


def rank(code):
    return BAND_ORDER.index(code) if code in BAND_ORDER else 0


def evaluate(c, l, m=None):
    m = m or current()
    nc, nl = size(m)
    c, l = max(1, min(nc, int(c))), max(1, min(nl, int(l)))
    b = band_info(m["cells"][c - 1][l - 1], m)
    grid = m.get("scores")
    if grid:
        score = int(grid[c - 1][l - 1])
        higher = bool(m.get("score_higher_is_worse", True))
    else:
        score, higher = c * l, True
    return {"score": score, "code": b["code"], "name": b["name"], "color": b["color"], "higher_is_worse": higher}


def _severity_key(item):
    direction = 1 if item.get("higher_is_worse", True) else -1
    return (rank(item["code"]), direction * item.get("score", 0))


def worse(a, b):
    """The more severe of two evaluated risks (band first, then the matrix cell)."""
    if a is None:
        return b
    return b if _severity_key(b) > _severity_key(a) else a


class MatrixRequired(RuntimeError):
    pass


def project_matrix():
    """The uploaded risk-matrix file. Analysis does not rank on the built-in 5 x 5."""
    m = current()
    if not m.get("source"):
        raise MatrixRequired("Upload the project risk matrix. Every cause is ranked on that file.")
    return m


# The rule engine speaks in five intents. The uploaded file decides which of its own levels that intent is.
_SEVERITY_INTENT = (
    ("minor", "negligible", "first aid", "slight", "insignificant"),
    ("moderate", "medical treatment", "restricted work", "minor release"),
    ("serious", "lost time", "contained release", "significant"),
    ("major", "single fatality", "permanent disability", "severe"),
    ("catastrophic", "multiple fatalities", "disaster", "extreme"),
)
_LIKELIHOOD_INTENT = (
    ("remote", "rare", "incredible", "highly unlikely"),
    ("unlikely", "seldom"),
    ("possible", "occasional", "credible"),
    ("likely", "probable"),
    ("frequent", "almost certain", "expected"),
)


def _hits(text, intents):
    text = " " + re.sub(r"[^a-z0-9]+", " ", text.lower()) + " "
    text = text.replace(" not expected ", " ")
    best = None
    for i, words in enumerate(intents):
        for word in words:
            if f" {word} " in text and (best is None or len(word) > best[0]):
                best = (len(word), i)
    return None if best is None else best[1]


def _anchors(levels, intents):
    """intent index -> that file's level number. One level is kept when several share an intent."""
    n = len(levels)
    buckets = {}
    for lv in levels:
        hit = _hits(f"{lv.get('name', '')} {lv.get('desc', '')}", intents)
        if hit is not None:
            buckets.setdefault(hit, []).append(lv["level"])
    anchors = {}
    for intent, nums in buckets.items():
        ideal = 1 + intent * (n - 1) / 4
        anchors[intent] = min(nums, key=lambda x: (abs(x - ideal), x))
    return anchors


def _scale(v, n):
    return max(1, min(n, int((int(v) - 1) * (n - 1) / 4 + 1.5)))


def _on_axis(v, levels, intents):
    """Place a 1..5 intent on this file's axis, using the level names in the file."""
    n = len(levels)
    v = max(1, min(5, int(v)))
    anchors = _anchors(levels, intents)
    i = v - 1
    if i in anchors:
        return anchors[i]
    lower = max((k for k in anchors if k < i), default=None)
    upper = min((k for k in anchors if k > i), default=None)
    if lower is not None and upper is not None and upper != lower:
        frac = (i - lower) / (upper - lower)
        return max(1, min(n, round(anchors[lower] + frac * (anchors[upper] - anchors[lower]))))
    if anchors:
        nearest = min(anchors, key=lambda k: (abs(k - i), k))
        return max(1, min(n, anchors[nearest] + (i - nearest)))
    return _scale(v, n)


def from_basis(c, l, m=None):
    """Place the rule engine's consequence and likelihood intents on the uploaded matrix."""
    m = m or current()
    return _on_axis(c, m["severity"], _SEVERITY_INTENT), _on_axis(l, m["likelihood"], _LIKELIHOOD_INTENT)


def matrix():
    return current()
