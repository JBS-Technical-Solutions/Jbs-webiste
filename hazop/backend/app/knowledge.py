import json
from functools import lru_cache

from .config import KNOWLEDGE_DIR


def _load(name):
    return json.loads((KNOWLEDGE_DIR / name).read_text(encoding="utf-8"))


@lru_cache
def isa():
    return _load("isa_letters.json")


@lru_cache
def api14c():
    return _load("api14c.json")


@lru_cache
def services():
    return _load("services.json")


@lru_cache
def piping():
    return _load("piping_specs.json")


def spec(code):
    return piping()["specs"].get(code)


def spec_rating_psig(code, temp_f=100):
    """Allowable pressure for a piping spec at a temperature (linear interpolation)."""
    s = spec(code)
    if not s:
        return None
    pts = sorted(s["pressure_temp"], key=lambda p: p["temp_f"])
    if temp_f <= pts[0]["temp_f"]:
        return pts[0]["psig"]
    for a, b in zip(pts, pts[1:]):
        if a["temp_f"] <= temp_f <= b["temp_f"]:
            f = (temp_f - a["temp_f"]) / (b["temp_f"] - a["temp_f"])
            return round(a["psig"] + f * (b["psig"] - a["psig"]))
    return pts[-1]["psig"]


def service_name(code):
    s = services()["codes"].get(code)
    return s["name"] if s else code


def valve_type(code):
    prefixes = piping()["valve_prefixes"]
    head = code.split("-")[0]
    for p in sorted(prefixes, key=len, reverse=True):
        if head == p:
            return prefixes[p]
    return "Valve"


def describe_instrument(letters):
    """Decode ISA letters, e.g. TSHH -> Temperature switch high-high."""
    k = isa()
    if not letters or letters[0] not in k["first_letter"]:
        return letters
    variable = k["first_letter"][letters[0]]
    rest = letters[1:]
    words = []
    if letters in api14c()["safety_devices"]:
        return api14c()["safety_devices"][letters]
    if rest in ("V", "CV"):
        return f"{variable.split(' /')[0]} control valve"
    if rest[:1] in ("S",) and rest[1:2] in ("V", "E"):
        words.append("safety")
        rest = rest[1:]
    elif rest[:1] in ("D", "F", "K", "Q") and len(rest) > 1:
        words.append(k["first_letter_modifier"][rest[0]].lower())
        rest = rest[1:]
    funcs, mods = [], []
    for ch in rest:
        if ch in ("H", "L") or (ch in k["succeeding_modifier"] and funcs and ch not in k["succeeding"]):
            mods.append(k["succeeding_modifier"][ch].lower())
        elif ch in k["succeeding"]:
            funcs.append(k["succeeding"][ch].lower())
    text = " ".join([variable.split(" /")[0]] + words + funcs)
    if mods:
        text += " " + "-".join(mods)
    return text[0].upper() + text[1:]


def decode_equipment(prefix):
    """Decode an API RP 14C style equipment prefix, e.g. HAP -> Heat exchanger / Heater."""
    k = api14c()
    first, mod = prefix[:1], prefix[1:3]
    t = k["component_type"].get(first)
    m = k["component_modifier"].get(mod)
    return f"{t} - {m}" if t and m else None
