"""Turn raw text tokens from a P&ID into engineering entities.

Entities: equipment, instruments (ISA), lines (size-service-spec-number-insulation),
valves (piping spec codes), off-page connectors, spec breaks and design data.
"""

import re
from itertools import count

from .. import knowledge as kb

QUOTES = str.maketrans({"\u2019": '"', "\u2018": '"', "\u2032": '"', "\u2033": '"', "\u201c": '"', "\u201d": '"',
                        "'": '"', "\u00b0": '"', "\u256b": "X", "_": " ", "\u00d7": "X", "\uff1a": ":"})

STOPWORDS = {
    "NOTE", "SET", "AT", "UC", "DVC", "CSO", "CSC", "FIRE", "PSIG", "SKIN", "RTD", "FROM", "TO", "AND", "GAS",
    "FUEL", "HP", "LP", "MP", "DWG", "ON", "OFF", "FC", "FO", "FL", "LC", "LO", "NC", "NO", "TYP", "MIN", "MAX",
    "DES", "OP", "KW", "PNL", "ME", "VB", "VC", "VN", "VGL", "GL", "SP", "FA", "EFV", "TSO", "FB", "CONT", "SEE",
    "DRUM", "TP", "TIE", "IN", "OUT", "AIR", "IA", "PA", "LIFT", "SKID",
}

VOCAB = sorted({
    "FROM", "TO", "AND", "OR", "OF", "THE", "HP", "LP", "MP", "FUEL", "GAS", "EXCHANGER", "K.O.", "KO", "DRUM",
    "METERING", "SKID", "LIFT", "FLOWLINES", "FLOWLINE", "FLARE", "HEADER", "BUYBACK", "PREHEATER", "HEATER",
    "PACKAGE", "CONTINUED", "ON", "DWG", "SYSTEM", "SHUTDOWN", "COMMON", "TROUBLE", "SET", "AT", "NOTE", "PSIG",
    "FIRE", "SEPARATOR", "SCRUBBER", "COMPRESSOR", "PUMP", "TANK", "VESSEL", "INLET", "OUTLET", "WATER", "OIL",
    "PRODUCED", "INJECTION", "DISCHARGE", "SUCTION", "COOLER", "COOLING", "VENT", "DRAIN", "CLOSED", "OPEN",
    "TEST", "PRODUCTION", "GLYCOL", "CONTACTOR", "REBOILER", "FILTER", "COALESCER", "SKIN", "RTD", "OFF",
    "DUTY", "POWER", "PRESSURE", "TEMPERATURE", "DESIGN", "UNIT", "TREATER", "SUMP", "BLOWDOWN", "RELIEF",
    "NITROGEN", "DIESEL", "INSTRUMENT", "UTILITY", "PROCESS", "CONDENSATE", "LIQUID", "VAPOR", "EXPORT",
    "IMPORT", "LINE", "LINES", "TRAIN", "STAGE", "FIRST", "SECOND", "THIRD", "LOW", "HIGH", "TEMP", "KNOCKOUT",
    "OUT", "IN", "FEED", "RETURN", "SUPPLY", "TOP", "BOTTOM", "PANEL",
}, key=len, reverse=True)

EQUIPMENT_KEYWORDS = [
    ("heater", ("PREHEATER", "HEATER", "FURNACE", "BOILER")),
    ("vessel", ("K.O.", "KO DRUM", "KNOCKOUT", "DRUM", "SCRUBBER", "SEPARATOR", "VESSEL", "COALESCER", "FILTER",
                "CONTACTOR", "TREATER")),
    ("exchanger", ("EXCHANGER", "COOLER", "CONDENSER", "REBOILER", "CHILLER")),
    ("pump", ("PUMP",)),
    ("compressor", ("COMPRESSOR", "BLOWER")),
    ("tank", ("TANK", "SUMP")),
    ("package", ("PACKAGE", "SKID")),
    ("panel", ("PANEL",)),
]

API14C_KIND = {"A": "tank", "B": "tank", "C": "compressor", "E": "heater", "H": "exchanger", "M": "vessel",
               "N": "vessel", "P": "pump"}
API14C_MOD_KIND = {"AP": "heater", "AC": "heater", "BC": "exchanger", "BB": "pump", "AE": "compressor"}

LINE_RE = re.compile(
    r'(?:(\d{1,2}(?:[./]\d{1,2})*)"?-)?([A-Z]{1,2})-([A-Z]{1,2}\d{1,2}[A-Z]?)-(\d{3,5})(?:-(\d+(?:\.\d+)?"?[A-Z]{1,2}))?'
)
EQUIP_RE = re.compile(r'(?<![A-Z0-9-])([A-Z]{2,4})-(\d{3,5}[A-Z]?)(?![0-9-])')
INST_NUM_RE = re.compile(r'\d{3,5}[A-Z]{0,2}\d?')
VALVE_RE = re.compile(r'(?<![A-Z])V(GL|BF|B|G|C|N|P)-?(\d{2,3})N')
SIZE_RE = re.compile(r'^\.?(\d{1,2}(?:\.\d)?(?:/\d{1,2})?|\d/\d)"$')
NON_EQUIP_PREFIX = {"DPP", "DWG", "VB", "VGL", "VC", "VN", "VG", "VBF", "VP", "CAB", "BEB", "NOTE", "REV"}


# OCR engines tend to drop a round 'O' in P&ID fonts ('FRM', 'NTE', 'PWER').
OCR_FIXES = [
    (re.compile(r"\bFRM(?=\b|[A-Z]{3})"), "FROM"),
    (re.compile(r"\bNTE(?=\s?\d|\b)"), "NOTE"),
    (re.compile(r"\bPWER\b|\bPWER(?=:)"), "POWER"),
    (re.compile(r"\bT0\b"), "TO"),
]


def _norm(text):
    t = text.upper().translate(QUOTES).replace("\u2013", "-")
    t = re.sub(r"\bK\.{1,2}O?\.?(?=\s?DRUM)", "K.O. ", t)
    for rx, repl in OCR_FIXES:
        t = rx.sub(repl, t)
    return re.sub(r"\s+", " ", t).strip()


def _strip_grid(text):
    """Remove drawing grid-reference numbers glued to words, e.g. '42FROM...' or '...HEADER42'."""
    text = re.sub(r'^\d{1,2}(?=[A-Z]{4,})', "", text)
    text = re.sub(r'(?<=[A-Z]{4})\d{1,2}$', "", text)
    return text


def _segment(word):
    """Split OCR text that lost its spaces (e.g. 'BUYBACKGASPREHEATER') using a P&ID vocabulary."""
    if len(word) < 6 or any(ch.isdigit() for ch in word):
        return word
    n = len(word)
    best = [None] * (n + 1)
    best[0] = []
    for i in range(n):
        if best[i] is None:
            continue
        for v in VOCAB:
            if word.startswith(v, i) and (best[i + len(v)] is None or len(best[i + len(v)]) > len(best[i]) + 1):
                best[i + len(v)] = best[i] + [v]
    return " ".join(best[n]) if best[n] else word


VOCAB_SET = set(VOCAB)


def _restore_o(word):
    """'FLWLINES' -> 'FLOWLINES': put back a single dropped 'O' when that yields a known word."""
    if word in VOCAB_SET or len(word) < 3 or not word.isalpha():
        return word
    for i in range(1, len(word)):
        cand = word[:i] + "O" + word[i:]
        if cand in VOCAB_SET:
            return cand
    return word


def _clean_phrase(text):
    words = [_restore_o(w) for w in " ".join(_segment(w) for w in _strip_grid(text).split()).split()]
    return re.sub(r"\s+", " ", " ".join(words)).strip()


class Tok:
    __slots__ = ("text", "raw", "score", "x0", "y0", "x1", "y1", "rot", "used")

    def __init__(self, t):
        self.raw = t["text"]
        self.text = _norm(t["text"])
        self.score = t.get("score", 1.0)
        self.x0, self.y0, self.x1, self.y1 = t["box"]
        self.rot = t.get("rot", 0)
        self.used = False

    @property
    def h(self):
        return max(self.y1 - self.y0, 1)

    @property
    def w(self):
        return max(self.x1 - self.x0, 1)

    @property
    def cx(self):
        return (self.x0 + self.x1) / 2

    @property
    def cy(self):
        return (self.y0 + self.y1) / 2

    @property
    def vertical(self):
        return self.h > 1.5 * self.w

    @property
    def size(self):
        return self.w if self.vertical else self.h

    def box(self):
        return [self.x0, self.y0, self.x1, self.y1]


def _dist(a, b):
    return ((a.cx - b.cx) ** 2 + (a.cy - b.cy) ** 2) ** 0.5


def _near(tokens, ref, radius):
    return [t for t in tokens if t is not ref and _dist(t, ref) <= radius]


def _union(boxes):
    return [min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)]


# ---------------------------------------------------------------- text blocks

def _text_lines(tokens):
    """Group horizontal tokens into text lines."""
    horiz = sorted([t for t in tokens if not t.vertical], key=lambda t: (t.cy, t.x0))
    lines = []
    for t in horiz:
        for ln in lines:
            last = ln[-1]
            if abs(t.cy - last.cy) < 0.6 * max(t.h, last.h) and 0 <= t.x0 - last.x1 < 2.0 * max(t.h, last.h):
                ln.append(t)
                break
        else:
            lines.append([t])
    return [{"tokens": ln, "text": " ".join(x.text for x in ln), "box": _union([x.box() for x in ln]),
             "h": sum(x.h for x in ln) / len(ln)} for ln in lines]


# ------------------------------------------------------------------- entities

def _parse_lines(tokens):
    found = {}
    services = kb.services()["codes"]
    for t in tokens:
        compact = t.text.replace(" ", "")
        for m in LINE_RE.finditer(compact):
            size, service, spec, number, insul = m.groups()
            if service not in services:
                continue
            key = (service, spec, number)
            cur = found.setdefault(key, {"size": None, "service": service, "spec": spec, "number": number,
                                         "insulation": None, "box": t.box(), "_toks": []})
            cur["size"] = cur["size"] or (f'{size}"' if size else None)
            cur["insulation"] = cur["insulation"] or insul
            cur["_toks"].append(t)
            t.used = True
    out = []
    for i, e in enumerate(found.values(), 1):
        spec = kb.spec(e["spec"])
        tag = "-".join(x for x in [e["size"], e["service"], e["spec"], e["number"], e["insulation"]] if x)
        out.append({
            "id": f"L{i}", "tag": tag, "size": e["size"], "service": e["service"],
            "service_name": kb.service_name(e["service"]), "spec": e["spec"], "spec_known": bool(spec),
            "number": e["number"], "insulation": e["insulation"],
            "rating": spec["rating"] if spec else None,
            "rating_psig": kb.spec_rating_psig(e["spec"]) if spec else None,
            "min_temp_f": spec["min_temp_f"] if spec else None,
            "max_temp_f": spec["max_temp_f"] if spec else None,
            "sour": spec["sour_service"] if spec else None,
            "material": spec["material"] if spec else None,
            "box": e["box"], "boxes": [t.box() for t in e["_toks"]], "_toks": e["_toks"],
        })
    return out


def _is_isa_letters(s):
    k = kb.isa()
    if not (2 <= len(s) <= 5) or s in STOPWORDS or not s.isalpha():
        return False
    if s[0] not in k["first_letter"]:
        return False
    allowed = set(k["succeeding"]) | set(k["succeeding_modifier"]) | set(k["first_letter_modifier"])
    return all(ch in allowed for ch in s[1:])


def _instrument_category(letters):
    rest = letters[1:]
    if letters in ("PSV", "PSE", "TSE", "FSV") or letters.endswith("SV"):
        return "relief" if letters in ("PSV", "PSE") else "safety"
    if rest.startswith("S") and any(m in rest for m in ("HH", "LL")):
        return "trip"
    if rest.startswith("S") and rest[1:2] in ("H", "L"):
        return "switch"
    if "A" in rest and any(m in rest for m in ("H", "L")):
        return "alarm"
    if rest in ("V", "CV") or (rest.endswith("V") and "S" not in rest):
        return "control_valve"
    if "C" in rest:
        return "controller"
    if rest in ("E", "W"):
        return "element"
    if rest.startswith("Y"):
        return "relay"
    if "T" in rest or "I" in rest or "G" in rest:
        return "indicator"
    return "other"


def _dominant_loops(tokens):
    counts = {}
    for t in tokens:
        m = re.fullmatch(r"(\d{3,5})[A-Z]{1,2}\d?", t.text.replace(" ", "").rstrip("/"))
        if m:
            counts[m.group(1)] = counts.get(m.group(1), 0) + 1
    return sorted((k for k, v in counts.items() if v >= 2), key=len, reverse=True)


def _split_numbers(t, loops):
    """A number token may hold several tags side by side (e.g. '2850D2850D')."""
    text = t.text.replace(" ", "").rstrip("/")
    parts = None
    for loop in loops:
        if text.count(loop) > 1 and text.startswith(loop):
            parts = [loop + p for p in text.split(loop)[1:]]
            break
    if parts is None:
        parts = re.findall(r"\d{3,5}[A-Z]{0,2}(?:\d(?!\d{2}))?", text)
    if not parts or "".join(parts) != text or not all(INST_NUM_RE.fullmatch(p) for p in parts):
        return []
    seg_w = t.w / len(parts)
    return [(p, t.x0 + seg_w * (i + 0.5)) for i, p in enumerate(parts)]


def _parse_instruments(tokens):
    letters = [t for t in tokens if not t.vertical and _is_isa_letters(t.text.replace(" ", ""))]
    loops = _dominant_loops(tokens)
    numbers = []
    for t in tokens:
        if t.vertical:
            continue
        for num, cx in _split_numbers(t, loops):
            numbers.append({"num": num, "cx": cx, "tok": t, "taken": False})

    pairs = []
    for L in letters:
        for n in numbers:
            N = n["tok"]
            dy = N.y0 - L.y1
            if not (-0.5 * L.h <= dy <= 1.6 * L.h) or N.cy <= L.cy:
                continue
            dx = abs(n["cx"] - L.cx)
            if dx > max(1.2 * L.w, 2.5 * L.h):
                continue
            pairs.append((dx + abs(dy) * 0.5, L, n))
    pairs.sort(key=lambda p: p[0])
    used_letters, out, seen = set(), [], set()
    for _, L, n in pairs:
        if id(L) in used_letters or n["taken"]:
            continue
        used_letters.add(id(L))
        n["taken"] = True
        L.used = n["tok"].used = True
        lt = L.text.replace(" ", "")
        tag = f"{lt}-{n['num']}"
        if tag in seen:
            continue
        seen.add(tag)
        loop = re.match(r"\d+", n["num"]).group(0)
        out.append({
            "tag": tag, "letters": lt, "number": n["num"], "loop": loop, "variable": kb.isa()["first_letter"][lt[0]],
            "description": kb.describe_instrument(lt), "category": _instrument_category(lt),
            "box": _union([L.box(), n["tok"].box()]), "_tok": L,
        })

    # Tags written on a single token, e.g. 'PSV-2850A' or 'PIC 2850A'
    for t in tokens:
        m = re.fullmatch(r"([A-Z]{2,5})[- ]?(\d{3,5}[A-Z]{0,2}\d?)", t.text.replace(" ", ""))
        if not m or t.used:
            continue
        lt, num = m.groups()
        if not _is_isa_letters(lt) or lt[0] not in "FLPTA" or lt in NON_EQUIP_PREFIX:
            continue
        tag = f"{lt}-{num}"
        if tag in seen:
            continue
        seen.add(tag)
        t.used = True
        out.append({
            "tag": tag, "letters": lt, "number": num, "loop": re.match(r"\d+", num).group(0),
            "variable": kb.isa()["first_letter"][lt[0]], "description": kb.describe_instrument(lt),
            "category": _instrument_category(lt), "box": t.box(), "_tok": t,
        })
    for i, inst in enumerate(sorted(out, key=lambda x: x["tag"]), 1):
        inst["id"] = f"I{i}"
    return sorted(out, key=lambda x: x["tag"])


VALVE_ATTRS = ("CSO", "CSC", "LO", "LC", "NC", "NO", "FB", "FC", "FO")
VALVE_ATTR_FIXES = {"CS": "CSO", "CS0": "CSO", "CSD": "CSO", "CSG": "CSC"}


def _infer_control_valves(instruments, tokens):
    """A controller loop with a relay/positioner (e.g. PY) or a fail-action mark normally drives a control valve
    whose letters OCR may have missed; recover it from the orphan loop number near the relay."""
    have = {(i["letters"][0], i["number"]) for i in instruments if i["category"] == "control_valve"}
    added = []
    for ctrl in [i for i in instruments if i["category"] == "controller"]:
        var, num = ctrl["letters"][0], ctrl["number"]
        if (var, num) in have:
            continue
        relay = next((i for i in instruments if i["letters"] == var + "Y" and i["number"] == num), None)
        orphans = [t for t in tokens if not t.used and not t.vertical and t.text.replace(" ", "") == num]
        fail_marks = [t for t in tokens if t.text in ("FC", "FO", "FL")]
        anchor, fail = None, None
        for o in sorted(orphans, key=lambda o: _dist(o, relay["_tok"]) if relay else 0):
            if relay and _dist(o, relay["_tok"]) > 12 * o.h:
                continue
            mark = min(fail_marks, key=lambda f: _dist(f, o), default=None)
            if mark is not None and _dist(mark, o) <= 6 * o.h:
                anchor, fail = o, mark.text
                break
            if relay and anchor is None:
                anchor = o
        if anchor is None:
            continue
        anchor.used = True
        lt = var + "V"
        inst = {
            "tag": f"{lt}-{num}", "letters": lt, "number": num, "loop": ctrl["loop"],
            "variable": kb.isa()["first_letter"][var], "description": kb.describe_instrument(lt),
            "category": "control_valve", "box": anchor.box(), "_tok": anchor, "inferred": True,
        }
        if fail:
            inst["fail_action"] = fail
        added.append(inst)
        have.add((var, num))
    out = sorted(instruments + added, key=lambda x: x["tag"])
    for i, inst in enumerate(out, 1):
        inst["id"] = f"I{i}"
    return out


def _dedupe_tokens(tokens):
    """OCR tiles can read the same text twice ('SET AT' / 'SET_AT', 'NOTE3' / 'NTE3')."""
    kept = []
    for t in sorted(tokens, key=lambda t: -t.score):
        dup = False
        for k in kept:
            ix = max(0, min(t.x1, k.x1) - max(t.x0, k.x0)) * max(0, min(t.y1, k.y1) - max(t.y0, k.y0))
            if ix > 0.6 * min(t.w * t.h, k.w * k.h):
                a, b = t.text.replace(" ", ""), k.text.replace(" ", "")
                if a == b or a in b or b in a:
                    dup = True
                    break
        if not dup:
            kept.append(t)
    return kept


def _set_point(t, tokens):
    """Read the 'SET AT ...' label written directly above a controller bubble."""
    labels = [n for n in tokens if re.match(r"SET\.?\s?AT", n.text)
              and 0 < t.cy - n.cy < 4 * t.h and abs(n.cx - t.cx) < 1.5 * max(t.w, n.w)]
    if not labels:
        return None
    s = min(labels, key=lambda n: t.cy - n.cy)
    follow = [n for n in tokens if n is not s and s.y0 - 0.3 * s.h <= n.y0 <= s.y1 + 0.6 * s.h
              and s.x0 - s.h <= n.x0 <= s.x1 + 3 * s.h and n.cy < t.y0]
    text = " ".join([s.text] + [n.text for n in sorted(follow, key=lambda n: (n.cy, n.x0))])
    m = re.search(r'(-?\d+(?:\.\d+)?)\s*"?\s*(F|PSIG|PSI|C)\b', text)
    if m:
        unit = {"F": "\u00b0F", "C": "\u00b0C"}.get(m.group(2), "psig")
        return f"{m.group(1)} {unit}"
    m = re.search(r"NOTE\s?(\d+)", text)
    if m:
        return f"Per Note {m.group(1)}"
    return None


def _parse_valves(tokens):
    out = []
    for t in tokens:
        for m in VALVE_RE.finditer(t.text.replace(" ", "")):
            vtype, num = m.groups()
            code = f"V{vtype}-{num}N"
            r = 3.0 * t.size
            near = _near(tokens, t, r)
            size = None
            for n in sorted(near, key=lambda x: _dist(x, t)):
                sm = SIZE_RE.match(n.text.replace(" ", ""))
                if sm:
                    size = sm.group(1).replace("1.1/2", "1-1/2") + '"'
                    break
            attrs = sorted({VALVE_ATTR_FIXES.get(n.text, n.text) for n in near
                            if VALVE_ATTR_FIXES.get(n.text, n.text) in VALVE_ATTRS})
            out.append({"code": code, "type": kb.valve_type(code), "size": size, "attributes": attrs, "box": t.box(),
                        "_tok": t})
            t.used = True
    for i, v in enumerate(out, 1):
        v["id"] = f"V{i}"
    return out


def _classify_equipment(prefix, description):
    text = description or ""
    for kind, words in EQUIPMENT_KEYWORDS:
        if any(w in text for w in words):
            return kind
    if prefix == "PNL":
        return "panel"
    if prefix[1:3] in API14C_MOD_KIND:
        return API14C_MOD_KIND[prefix[1:3]]
    return API14C_KIND.get(prefix[0], "equipment")


DESIGN_P_RE = re.compile(r"PRESS(?:URE)?(?:\([A-Z/]*\))?:?(-?\d+(?:\.\d+)?)/(-?\d+(?:\.\d+)?)?")
DESIGN_T_RE = re.compile(r"TEMP(?:ERATURE)?(?:\([A-Z/]*\))?:?(-?\d+(?:\.\d+)?)/(-?\d+(?:\.\d+)?)?(?:/(-?\d+(?:\.\d+)?))?")
DUTY_RE = re.compile(r"DUTY:?(\d+(?:\.\d+)?)MMBTU")
POWER_RE = re.compile(r"P?O?WER:?(\d+(?:\.\d+)?)KW")


def _num(v):
    if v is None:
        return None
    f = float(v)
    return int(f) if f.is_integer() else f


def _parse_equipment(tokens, connector_blocks):
    occurrences = {}
    for t in tokens:
        for m in EQUIP_RE.finditer(t.text.replace(" ", "")):
            prefix, num = m.groups()
            if prefix in NON_EQUIP_PREFIX or _is_line_fragment(t.text):
                continue
            occurrences.setdefault((prefix, num), []).append(t)
            t.used = True

    # Merge truncated tags (e.g. 'ME-765' with 'ME-7650')
    keys = sorted(occurrences, key=lambda k: -len(k[1]))
    for k in list(keys):
        for other in keys:
            if other != k and other[0] == k[0] and other[1].startswith(k[1]) and len(other[1]) > len(k[1]) and k in occurrences:
                occurrences[other] += occurrences.pop(k)
                break

    out = []
    for i, ((prefix, num), toks) in enumerate(sorted(occurrences.items()), 1):
        tag = f"{prefix}-{num}"
        description, design, offpage = "", {}, True
        for t in toks:
            in_conn = any(t in b["tokens"] for b in connector_blocks)
            if not in_conn:
                offpage = False
            region = [n for n in tokens if n is not t and n.y0 >= t.y0 + 0.5 * t.h and n.y0 <= t.y1 + 7 * t.h
                      and t.x0 - t.h <= n.x0 <= t.x0 + 30 * t.h and not n.vertical]
            region.sort(key=lambda n: (round(n.cy / max(n.h, 1)), n.x0))
            text = " ".join(n.text for n in region)
            compact = text.replace(" ", "")
            block = next((b for b in connector_blocks if t in b["tokens"]), None)
            cand = _clean_phrase(block["text"]) if block else ""
            first_line = " ".join(n.text for n in region[:4])
            for kind, words in EQUIPMENT_KEYWORDS:
                if any(w in compact for w in (x.replace(" ", "") for x in words)):
                    lines = _text_lines(region)
                    cand = cand or (_clean_phrase(lines[0]["text"]) if lines else _clean_phrase(first_line))
                    break
            if cand and len(cand) > len(description):
                description = cand
            for rx, keys_ in ((DESIGN_P_RE, ("p_des", "p_op")), (DESIGN_T_RE, ("t_des", "t_op", "t_min"))):
                m = rx.search(compact)
                if m:
                    for key, val in zip(keys_, m.groups()):
                        if val is not None:
                            design.setdefault(key, _num(val))
            if (m := DUTY_RE.search(compact)):
                design.setdefault("duty_mmbtu_hr", _num(m.group(1)))
            if (m := POWER_RE.search(compact)):
                design.setdefault("power_kw", _num(m.group(1)))
        if description.startswith(("FROM ", "TO ")):
            description = description.split(" ", 1)[1]
        description = re.sub(rf"\s*{re.escape(tag)}\s*", " ", description).strip()
        kind = _classify_equipment(prefix, description.upper())
        out.append({
            "id": f"E{i}", "tag": tag, "prefix": prefix, "kind": kind, "description": _title(description) if description else "",
            "api14c": kb.decode_equipment(prefix), "design": design, "electric": "power_kw" in design,
            "offpage": offpage, "box": toks[0].box(), "boxes": [t.box() for t in toks], "_tok": toks[0],
        })
    return out


def _is_line_fragment(text):
    return bool(re.search(r"[A-Z]{1,2}-[A-Z]{1,2}\d", text.replace(" ", "")))


def _line_words(text):
    """Drop standalone grid numbers and glued grid references from a text line."""
    words = [w for w in text.split() if not re.fullmatch(r"\d{1,2}", w)]
    return " ".join(_strip_grid(w) for w in words).strip()


def _connector_head(text):
    """Return ('FROM'|'TO', rest) if a text line starts an off-page connector description."""
    compact = text.replace(" ", "")
    m = re.match(r"^(FROM|TO)(.+)$", compact)
    if m:
        return m.group(1), _clean_phrase(text[len(m.group(1)):] if text.startswith(m.group(1)) else m.group(2))
    if compact.startswith("T") and len(compact) > 4:
        rest = _segment(compact[1:])
        if rest != compact[1:] and rest.split()[0] in {"HP", "LP", "MP", "FUEL", "GAS", "FLARE", "OIL", "WATER"}:
            return "TO", rest
    return None


def _connector_groups(text_lines):
    lines = sorted(text_lines, key=lambda l: (l["box"][1], l["box"][0]))
    groups = []
    for i, ln in enumerate(lines):
        head = _connector_head(_line_words(ln["text"]))
        if not head:
            continue
        parts, toks, boxes = [head[1]], list(ln["tokens"]), [ln["box"]]
        last = ln
        for nxt in lines[i + 1:]:
            gap = nxt["box"][1] - last["box"][3]
            if gap > 1.0 * max(nxt["h"], last["h"]):
                if nxt["box"][1] > last["box"][3] + 3 * last["h"]:
                    break
                continue
            if abs(nxt["box"][0] - ln["box"][0]) > 3 * ln["h"]:
                continue
            words = _line_words(nxt["text"])
            if not words:
                continue
            if _connector_head(words) or words.startswith("CONTINUED") or LINE_RE.search(words.replace(" ", "")):
                break
            parts.append(_clean_phrase(words))
            toks += nxt["tokens"]
            boxes.append(nxt["box"])
            last = nxt
        groups.append({"direction": head[0], "text": " ".join(parts), "tokens": toks, "box": _union(boxes),
                       "h": ln["h"]})
    return groups


def _parse_connectors(groups, lines, tokens):
    out = []
    for g in groups:
        bx, h = g["box"], g["h"]
        line, best = None, None
        for ln in lines:
            for t in ln["_toks"]:
                if t.vertical:
                    continue
                dy = abs(t.cy - bx[1])
                if dy < 4 * h and bx[0] - 10 * h <= t.cx <= bx[2] + 25 * h and (best is None or dy < best):
                    best, line = dy, ln
        ref = next((t.text for t in tokens if re.fullmatch(r"[A-Z]{2,4}-\d{2}-\d{2,3}(-\d{2})?", t.text)
                    and 0 <= bx[1] - t.cy < 3 * h and bx[0] - 3 * h <= t.cx <= bx[2] + 3 * h), None)
        desc = re.sub(r"\s+", " ", g["text"]).strip()
        out.append({"direction": "source" if g["direction"] == "FROM" else "destination",
                    "description": _title(desc), "line": line["tag"] if line else None, "ref": ref, "box": bx})
    for i, c in enumerate(out, 1):
        c["id"] = f"C{i}"
    return out


def _title(text):
    keep = {"HP", "LP", "MP", "K.O.", "KO", "PSV", "SDV", "BDV"}
    return " ".join(w if w in keep or re.search(r"\d", w) else w.capitalize() for w in text.split())


def _attach_instrument_details(instruments, tokens):
    for inst in instruments:
        t = inst["_tok"]
        near = _near(tokens, t, 6 * t.h)
        joined = " ".join(n.text for n in sorted(near, key=lambda n: (n.cy, n.x0))).replace(" ", "")
        if inst["letters"][0] == "T" and any(n.text in ("SKIN", "RTD") for n in _near(tokens, t, 4 * t.h)):
            inst["remark"] = "skin"
        if inst["category"] == "relief":
            m = re.search(r"SETAT(\d{2,5})PSIG", joined) or re.search(r"(\d{2,5})PSIG", joined)
            if m:
                inst["set_psig"] = int(m.group(1))
            inst["fire_case"] = "FIRE" in joined
        if inst["category"] == "control_valve":
            act = [n.text for n in _near(tokens, t, 8 * t.h) if n.text in ("FC", "FO", "FL")]
            if act:
                inst["fail_action"] = act[0]
        if inst["category"] in ("trip", "switch", "alarm", "indicator", "controller"):
            vote = [n.text for n in _near(tokens, t, 10 * t.h) if re.fullmatch(r"[12][O0]{2}[23]", n.text.replace(" ", ""))]
            if vote:
                inst["voting"] = vote[0].replace("0", "o").replace("O", "o")
        if inst["category"] == "controller":
            sp = _set_point(t, tokens)
            if sp:
                inst["set_point"] = sp


def _parse_spec_breaks(tokens, lines):
    specs = {l["spec"] for l in lines if l["spec_known"]}
    marks = [t for t in tokens if t.text.replace(" ", "") in specs]
    out, used = [], set()
    for a in marks:
        for b in marks:
            if a is b or id(a) in used or id(b) in used or a.text == b.text:
                continue
            if _dist(a, b) < 6 * max(a.size, b.size):
                used |= {id(a), id(b)}
                out.append({"specs": sorted({a.text, b.text}), "box": _union([a.box(), b.box()])})
    return out


def parse(raw_tokens, image_size):
    W, H = image_size
    tokens = _dedupe_tokens([Tok(t) for t in raw_tokens if t["text"].strip()])
    connector_groups = _connector_groups(_text_lines(tokens))

    pipe_lines = _parse_lines(tokens)
    instruments = _parse_instruments(tokens)
    valves = _parse_valves(tokens)
    equipment = _parse_equipment(tokens, connector_groups)
    connectors = _parse_connectors(connector_groups, pipe_lines, tokens)
    _attach_instrument_details(instruments, tokens)
    instruments = _infer_control_valves(instruments, tokens)
    spec_breaks = _parse_spec_breaks(tokens, pipe_lines)

    compact_all = " ".join(t.text for t in tokens)
    flags = {
        "sour_service": any(l.get("sour") for l in pipe_lines),
        "car_sealed": any("CSO" in v["attributes"] for v in valves) or "CSO" in compact_all.split(),
        "interlocks": sum(1 for t in tokens if t.text == "I"),
    }

    def norm_box(b):
        return [round(b[0] / W, 5), round(b[1] / H, 5), round(b[2] / W, 5), round(b[3] / H, 5)]

    for group in (pipe_lines, instruments, valves, equipment, connectors, spec_breaks):
        for e in group:
            e.pop("_tok", None)
            e.pop("_toks", None)
            e["box"] = norm_box(e["box"])
            if "boxes" in e:
                e["boxes"] = [norm_box(b) for b in e["boxes"]]

    return {
        "equipment": equipment,
        "instruments": instruments,
        "lines": pipe_lines,
        "valves": valves,
        "connectors": connectors,
        "spec_breaks": spec_breaks,
        "flags": flags,
        "token_count": len(tokens),
        "tokens": [{"text": t.raw, "box": norm_box(t.box())} for t in tokens],
    }
