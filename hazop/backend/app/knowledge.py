import json
from contextlib import contextmanager
from contextvars import ContextVar
from functools import lru_cache

from .config import KNOWLEDGE_DIR

# Piping specs uploaded for the current job; the bundled knowledge base is used when none are set.
_project_specs = ContextVar("project_piping_specs", default=None)


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


def specs():
    return _project_specs.get() or piping()["specs"]


def has_project_specs():
    """True while an uploaded piping specification is the one the study is using."""
    return _project_specs.get() is not None


@contextmanager
def using_specs(project_specs):
    token = _project_specs.set(project_specs or None)
    try:
        yield
    finally:
        _project_specs.reset(token)


def learn_piping():
    """Read every class before the P&ID: what it is for, and the limit it places on a line."""
    learned = []
    for code, row in specs().items():
        services = ", ".join(row.get("services") or []) or "the service written on the line"
        sour = "sour" if row.get("sour_service") else "non-sour"
        psig = spec_rating_psig(code) if row.get("pressure_temp") else None
        limits = ""
        if psig or row.get("min_temp_f") is not None:
            limits = (
                f" Its limit is {psig or '-'} psig at 100 F, "
                f"{row.get('min_temp_f', '-')} F to {row.get('max_temp_f', '-')} F."
            )
        learned.append({
            "code": code,
            "purpose": (
                f"{code} is a {row.get('rating') or 'piping'} class in {sour} service, "
                f"material {row.get('material') or 'not stated'}, used for {services}.{limits}"
            ),
        })
    return learned


def spec(code):
    return specs().get(code)


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


@lru_cache
def company():
    return _load("company_standards.json")


def apply_matrix_definitions(matrix):
    """Fill empty level descriptions from the company risk matrix when the level names match."""
    if not matrix:
        return matrix
    known = company()["risk_matrix"]
    for axis, key in (("severity", "severity"), ("likelihood", "likelihood")):
        table = known[key]
        levels = matrix.get(axis) or []
        names = {level.get("name") for level in levels}
        if len(levels) != len(table) or names != set(table):
            continue
        for level in levels:
            if not level.get("desc"):
                level["desc"] = table[level["name"]]
    return matrix


def model_brief():
    """What the company standards say, in the form the AI review reads on every drawing."""
    c = company()
    rm = c["risk_matrix"]
    lines = [
        "Company standards learned from the project legend files. Use these meanings; do not invent different ones.",
        "Line number: " + c["tag_patterns"]["line"],
        "Equipment tag: " + c["tag_patterns"]["equipment"],
        "Safety device tag: " + c["tag_patterns"]["safety_device"],
        "Line graphics: " + "; ".join(f"{name.replace('_', ' ')} = {mark}" for name, mark in c["line_graphics"].items()) + ".",
        "Insulation and tracing codes: " + ", ".join(f"{code} = {name}" for code, name in services()["insulation"].items()) + ".",
        "Instrument bubbles: " + "; ".join(f"{name.replace('_', ' ')} = {mark}" for name, mark in c["instrument_bubbles"].items()) + ".",
        "Instrument symbols on the legend: " + ", ".join(c["instrument_symbols"]) + ".",
        "Piping component symbols: " + ", ".join(c["piping_components"]) + ".",
        "A normally closed valve is a safeguard only while it stays closed. A specification break means the piping class changes at that point.",
        f"Risk matrix file '{rm['file']}' ({rm['size']}). {rm['note']}",
    ]
    lines += [f"Consequence {name}: {text}" for name, text in rm["severity"].items()]
    lines += [f"Likelihood {name}: {text}" for name, text in rm["likelihood"].items()]
    lines += ["Risk-score legend: " + " ".join(rm["legend"])]
    specs = piping()["specs"]
    for code, spec in specs.items():
        lines.append(
            f"Piping class {code}: {spec['rating']}, {'sour' if spec['sour_service'] else 'non-sour'} service, "
            f"{spec['material']}, {spec['min_temp_f']} F to {spec['max_temp_f']} F, "
            f"services {', '.join(spec['services'])}."
        )
    return "\n".join(lines)


def decode_equipment(prefix):
    """Decode an API RP 14C style equipment prefix, e.g. HAP -> Heat exchanger / Heater."""
    k = api14c()
    first, mod = prefix[:1], prefix[1:3]
    t = k["component_type"].get(first)
    m = k["component_modifier"].get(mod)
    return f"{t} - {m}" if t and m else None
