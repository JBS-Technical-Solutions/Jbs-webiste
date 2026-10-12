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
    return {
        "name": str(m.get("name") or f"{nc} x {nl} risk matrix")[:120],
        "source": str(m["source"])[:200] if m.get("source") else None,
        "severity": _levels(m.get("severity") or [], nc),
        "likelihood": _levels(m.get("likelihood") or [], nl),
        "bands": bands,
        "cells": [list(r) for r in cells],
    }


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
    return {"score": c * l, "code": b["code"], "name": b["name"], "color": b["color"]}


def worse(a, b):
    """The more severe of two evaluated risks (band first, then C x L score)."""
    if a is None:
        return b
    return b if (rank(b["code"]), b["score"]) > (rank(a["code"]), a["score"]) else a


def _scale(v, n):
    return max(1, min(n, int((int(v) - 1) * (n - 1) / 4 + 1.5)))


def from_basis(c, l, m=None):
    """Map C and L ranked on the rule engine's 5-level basis onto the active matrix size."""
    nc, nl = size(m)
    return _scale(c, nc), _scale(l, nl)


def matrix():
    return current()
