"""Rule-based HAZOP generator.

Builds study nodes from extracted P&ID entities and applies a guide-word library
(No/More/Less/Reverse flow, High/Low pressure and temperature, Level, Composition,
Utility failure, Maintenance). Safeguards are taken from the instruments and valves
actually found on the drawing and design limits come from the piping-spec knowledge base.
"""

import colorsys
import copy
import re
from collections import Counter

from .. import knowledge as kb
from .. import risk
from ..risk import evaluate
from .parse import Tok, _text_lines

DEG = "\u00b0F"
# How far around a part's own tags another tag still belongs to that part (fraction of the page).
PART_RADIUS = 0.16
# Not part of the steady-state process node: drains, vents, blowdown and lines to safety valves.
OFF_PROCESS_SERVICES = {"DW", "DH", "VG", "SV", "FL", "BD"}


def _off_process_line(line):
    service = str(line.get("service") or "").upper()
    name = str(line.get("service_name") or "").lower()
    return service in OFF_PROCESS_SERVICES or any(
        word in name for word in ("drain", "vent", "flare", "blowdown", "blow down", "safety valve"))


class Recs:
    def __init__(self):
        self.items = {}

    def add(self, text):
        for rid, t in self.items.items():
            if t == text:
                return rid
        rid = f"R-{len(self.items) + 1:02d}"
        self.items[rid] = text
        return rid


class Ctx:
    def __init__(self, ext):
        self.ext = ext
        self.instruments = ext["instruments"]
        self.valves = ext["valves"]
        self.lines = ext["lines"]
        self.equipment = ext["equipment"]
        self.connectors = ext["connectors"]
        self.recs = Recs()

        self.off_process_lines = [l for l in self.lines if _off_process_line(l)]
        self.flare_lines = [l for l in self.off_process_lines if str(l.get("service") or "").upper() in ("FL", "SV", "BD", "VG")]
        self.process_lines = [l for l in self.lines if l not in self.off_process_lines]
        svc = Counter(l["service"] for l in self.process_lines)
        self.fluid = kb.service_name(svc.most_common(1)[0][0]).lower() if svc else "process fluid"
        info = kb.services()["codes"]
        self.hydrocarbon = any(info.get(l["service"], {}).get("hydrocarbon") for l in self.process_lines) or not self.process_lines
        self.gas = any(info.get(l["service"], {}).get("phase") in ("gas", "mixed") for l in self.process_lines)
        self.sour = any(l.get("sour") for l in self.lines)
        rated = [l for l in self.process_lines if l.get("rating_psig")]
        self.proc_spec = max(rated, key=lambda l: l["rating_psig"]) if rated else None
        frated = [l for l in self.flare_lines if l.get("rating_psig")]
        self.flare_spec = frated[0] if frated else None
        off_tags = {l["tag"] for l in self.off_process_lines}

        def is_off_process(c):
            text = (c.get("description") or "").upper()
            return c.get("line") in off_tags or any(w in text for w in ("FLARE", "VENT", "DRAIN", "BLOWDOWN", "BLOW DOWN"))

        self.sources = [c for c in self.connectors if c["direction"] == "source" and not is_off_process(c)]
        self.dests = [c for c in self.connectors if c["direction"] == "destination" and not is_off_process(c)]
        self.flare_dests = [c for c in self.connectors if c["direction"] == "destination" and is_off_process(c)]
        self.flare_sources = [c for c in self.connectors if c["direction"] == "source" and is_off_process(c)]
        self.release = ("high-pressure sour (H2S) flammable gas" if self.sour and self.gas else
                        "flammable hydrocarbon" if self.hydrocarbon else self.fluid)
        self.line_relation = list(ext.get("line_relation") or [])

    # ---------------------------------------------------------- instrument queries
    def find(self, var=None, cats=None, has=None, letters=None):
        out = []
        for i in self.instruments:
            if var and i["letters"][0] != var:
                continue
            if cats and i["category"] not in cats:
                continue
            if has and not any(h in i["letters"][1:] for h in has):
                continue
            if letters and i["letters"] not in letters:
                continue
            out.append(i)
        return out

    def valves_of(self, vtype):
        return [v for v in self.valves if v["type"].lower().startswith(vtype)]

    def tags(self, items):
        return " / ".join(i["tag"] for i in items)

    def names(self, items):
        seen = []
        for i in items:
            if i["code"] not in seen:
                seen.append(i["code"])
        return ", ".join(seen)

    def node_start(self):
        """Where this node is read from: one inlet, or the equipment the process line leaves."""
        inlet = self._inlet()
        if inlet:
            text = re.sub(r"(?i)^from\s+", "", inlet.get("description") or "upstream supply")
            line = f" ({inlet['line']})" if inlet.get("line") else ""
            return f"the inlet connector ({text}{line})"
        mains = [e for e in self.equipment if not e.get("offpage") and e.get("kind") not in ("panel", "package") and e.get("box")]
        if mains:
            first = min(mains, key=lambda e: (e["box"][0] + e["box"][2]) / 2)
            return f"{first['tag']}, where the process line originates"
        return "the process equipment"

    def _inlet(self):
        """The upstream connector at the start of the node, not every FROM mark on the sheet."""
        if not self.sources:
            return None
        return min(self.sources, key=lambda c: ((c.get("box") or [1, 1, 1, 1])[0], (c.get("box") or [0, 1, 0, 1])[1]))

    def src_text(self):
        inlet = self._inlet()
        if not inlet:
            return "upstream supply"
        text = re.sub(r"(?i)^from\s+", "", inlet.get("description") or "upstream supply")
        return text + (f" ({inlet['line']})" if inlet.get("line") else "")

    def dest_text(self):
        if not self.dests:
            return "downstream users"
        return " and ".join(
            re.sub(r"(?i)^to\s+", "", c["description"]) + (f" ({c['line']})" if c["line"] else "") for c in self.dests)

    def dest_equipment(self):
        offpage = [e for e in self.equipment if e["offpage"]]
        return offpage[0]["tag"] if offpage else (self.dests[0]["description"] if self.dests else "downstream equipment")


# ------------------------------------------------------------- safeguard helpers

def _equipment_duty(eq, ctx):
    """What this equipment is on the drawing to do."""
    fluid = ctx.fluid
    return {
        "heater": f"heat {fluid}",
        "vessel": f"separate liquid from {fluid}",
        "exchanger": f"transfer heat to or from {fluid}",
        "pump": f"move {fluid}",
        "compressor": f"raise the pressure of {fluid}",
        "tank": f"hold an inventory of {fluid}",
        "package": f"contain the {fluid} equipment mounted on the package",
        "panel": f"control the equipment from a panel",
    }.get(eq.get("kind") or "", f"handle {fluid}")


def _valve_duty(valve):
    """What this piping component is on the drawing to do."""
    kind = str(valve.get("type") or "").lower()
    attrs = set(valve.get("attributes") or [])
    if kind.startswith("check"):
        return "stop reverse flow"
    if kind.startswith("globe"):
        return "throttle flow by hand"
    if kind.startswith("needle"):
        return "vent, drain or bleed a small flow"
    if attrs & {"CSO", "LO", "NO"}:
        return "stay open so this path keeps flowing"
    if attrs & {"CSC", "LC", "NC"}:
        return "stay closed so this path stays isolated"
    if kind.startswith(("ball", "gate", "plug", "butterfly")):
        return "isolate the line when it is closed"
    return "control the path it is installed in"


def _reading_order(items):
    """Top to bottom, then left to right, which is how the P&ID sheet is read."""
    def key(item):
        box = item.get("box") or [0, 0, 0, 0]
        return ((box[1] + box[3]) / 2, (box[0] + box[2]) / 2)
    return sorted(items, key=key)


def _line_function(line):
    """Pipeline identification from the line designation and the piping specification."""
    service = line.get("service_name") or line.get("service") or "process"
    insulation = (kb.services().get("insulation") or {}).get(line.get("insulation") or "", "")
    parts = [f"{line.get('tag')} carries {service}"]
    if insulation:
        parts.append(insulation)
    if line.get("spec"):
        rating = " ".join(x for x in (line.get("rating"), line.get("material")) if x)
        parts.append(f"class {line['spec']}" + (f" {rating}" if rating else ""))
    return ", ".join(parts)


_LARGE_KINDS = {"vessel", "exchanger", "heater", "pump", "compressor", "tank"}
_KIND_PHRASE = {
    "exchanger": "heat exchanger", "heater": "heater", "vessel": "separator",
    "pump": "pump", "compressor": "compressor", "tank": "tank",
}


def _large_equipment(ctx):
    return [e for e in _reading_order(ctx.equipment) if not e.get("offpage") and e.get("kind") in _LARGE_KINDS and e.get("box")]


def _cx(item):
    box = item.get("box") or [0, 0, 0, 0]
    return (box[0] + box[2]) / 2


def _and(parts):
    parts = [p for p in parts if p]
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    return ", ".join(parts[:-1]) + " and " + parts[-1]


def _join_tags(tags):
    tags = [t for t in tags if t]
    if len(tags) <= 1:
        return tags[0] if tags else ""
    matched = [re.match(r"^(.*?)([A-Z]\d+)$", tag) for tag in tags]
    if all(matched) and len({item.group(1) for item in matched}) == 1:
        return matched[0].group(1) + matched[0].group(2) + "/" + "/".join(item.group(2) for item in matched[1:])
    return ", ".join(tags)


def _eq_phrase(eq):
    return f"{_KIND_PHRASE.get(eq.get('kind'), 'equipment')} {eq.get('tag')}"


def _conn_name(conn):
    text = re.sub(r"(?i)^(from|to)\s+", "", str(conn.get("description") or "")).strip(" .")
    return re.sub(r"\s+", " ", text).lower() or "the connector"


def _soft(text):
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    return text.lower() if text.isupper() else text


def _place_name(name):
    name = (name or "").strip()
    if not name:
        return "downstream"
    return name if name.lower().startswith("the ") else f"the {name}"


def _design_conditions(ctx):
    """Design and operating conditions of the main equipment, taken from the P&ID."""
    from .parse import _harvest_design
    _harvest_design(ctx.equipment, ctx.ext.get("tokens") or [])
    sentences = []
    for eq in _large_equipment(ctx)[:6]:
        d = eq.get("design") or {}
        bits = []
        if d.get("p_des"):
            bits.append(f"design pressure {d['p_des']} psig")
        if d.get("p_op"):
            bits.append(f"operating pressure {d['p_op']} psig")
        if d.get("t_des"):
            bits.append(f"design temperature {d['t_des']} {DEG}")
        if d.get("t_op") is not None:
            bits.append(f"operating temperature {d['t_op']} {DEG}")
        if bits:
            sentences.append(f"{eq['tag']}: " + ", ".join(bits))
        else:
            sentences.append(f"{eq['tag']}: design and operating conditions are not shown on the P&ID")
    return ". ".join(sentences)


def _overall_intent(ctx):
    """One sentence for what this node is there to do."""
    fluid = ctx.fluid
    large = _large_equipment(ctx)
    valves = _reading_order(ctx.find(cats=("control_valve",)))
    exchangers = [e for e in large if e.get("kind") == "exchanger"]
    heaters = [e for e in large if e.get("kind") == "heater"]
    vessels = [e for e in large if e.get("kind") == "vessel"]
    compressors = [e for e in large if e.get("kind") == "compressor"]
    pumps = [e for e in large if e.get("kind") == "pump"]
    pressure_valves = [v for v in valves if str(v.get("letters") or "").startswith("P")]
    clauses = []
    if exchangers and pressure_valves and not heaters and not compressors:
        through = _and([e["tag"] for e in exchangers] + [_join_tags([v["tag"] for v in pressure_valves])])
        clauses.append(f"reduce the {fluid} pressure and temperature through {through}")
    else:
        if exchangers:
            clauses.append(f"reduce the {fluid} temperature through {_and([e['tag'] for e in exchangers])}")
        if heaters:
            clauses.append(f"heat the {fluid} through {_and([e['tag'] for e in heaters])}")
        if pressure_valves:
            clauses.append(f"reduce the {fluid} pressure through {_join_tags([v['tag'] for v in pressure_valves])}")
        if compressors:
            clauses.append(f"raise the {fluid} pressure in {_and([e['tag'] for e in compressors])}")
    if vessels:
        clauses.append(f"remove the condensate through {_and([e['tag'] for e in vessels])}")
    elif pumps:
        clauses.append(f"transfer the {fluid} with {_and([e['tag'] for e in pumps])}")
    if not clauses:
        return f"To move {fluid} from {ctx.src_text()} to {ctx.dest_text()}."
    return "To " + clauses[0] + "".join(f", and {clause}" for clause in clauses[1:]) + "."


def _line_phrase(ctx, line):
    """The P&ID line, with the PFD stream that was matched to it."""
    tag = line.get("tag") or "the line"
    stream = ""
    for match in getattr(ctx, "line_relation", None) or []:
        if match.get("pid_line") == tag and re.fullmatch(r"\d{1,3}[A-Z]{0,2}", str(match.get("pfd_stream") or "")):
            stream = match["pfd_stream"]
            break
    if stream:
        return f"P&ID line {tag} (PFD stream {stream})"
    return f"P&ID line {tag}"


def _lines_on_route(ctx, source, target):
    """Process lines from this inlet toward the main equipment, in left-to-right order."""
    box = source.get("box") or [0, 0, 0, 0]
    sy = (box[1] + box[3]) / 2
    sx = _cx(source)
    end_x = _cx(target) if target else 1
    found = []
    seen = set()
    for line in ctx.process_lines:
        tag = line.get("tag")
        if not tag or tag in seen:
            continue
        boxes = line.get("boxes") or ([line["box"]] if line.get("box") else [])
        for candidate in boxes:
            lx = (candidate[0] + candidate[2]) / 2
            ly = (candidate[1] + candidate[3]) / 2
            if sx - 0.08 <= lx <= end_x + 0.1 and abs(ly - sy) <= 0.18:
                seen.add(tag)
                found.append(line)
                break
    return sorted(found, key=_cx)


def _node_description(ctx, color=None):
    """A short route summary, read left to right, naming the P&ID line and its PFD stream."""
    fluid = ctx.fluid
    large = _large_equipment(ctx)
    vessels = [e for e in large if e.get("kind") == "vessel"]
    target = vessels[0] if vessels else (large[-1] if large else None)
    sources = sorted(ctx.sources, key=lambda item: (_cx(item), ((item.get("box") or [0, 0, 0, 0])[1])))
    valves = ctx.find(cats=("control_valve",))
    sentences = []
    if not sources and large:
        sources = [{"description": _eq_phrase(large[0]), "box": large[0].get("box"), "_skip": large[0]["tag"]}]
    end_x = _cx(target) if target else 1

    def _on_this_inlet(item, source):
        if source.get("_skip") and item.get("tag") == source.get("_skip"):
            return False
        if target and item.get("tag") == target.get("tag"):
            return False
        x = _cx(item)
        if x < _cx(source) - 0.02 or x > end_x + 0.02:
            return False
        nearest = min(sources, key=lambda s: abs(((s.get("box") or [0, 0, 0, 0])[1] + (s.get("box") or [0, 1, 0, 1])[3]) / 2 - ((item.get("box") or [0, 0, 0, 0])[1] + (item.get("box") or [0, 1, 0, 1])[3]) / 2))
        return nearest is source

    for index, source in enumerate(sources[:4]):
        through = [_eq_phrase(eq) for eq in sorted(large, key=_cx) if _on_this_inlet(eq, source)]
        on_path = sorted([v for v in valves if _on_this_inlet(v, source)], key=_cx)
        if on_path:
            through.append(_join_tags([v.get("tag") for v in on_path]))
        route_lines = _lines_on_route(ctx, source, target)
        where = f" on {_and([_line_phrase(ctx, line) for line in route_lines[:2]])}" if route_lines else ""
        lead = f"{fluid.capitalize()} line" if index == 0 else f"Another {fluid} line"
        origin = _conn_name(source)
        if through and target:
            sentences.append(f"{lead}{where} from {origin} going through {', '.join(through)} to {target['tag']}.")
        elif target:
            sentences.append(f"{lead}{where} from {origin} going to {target['tag']}.")
        elif through:
            sentences.append(f"{lead}{where} from {origin} going through {', '.join(through)}.")
        else:
            sentences.append(f"{lead}{where} from {origin}.")
    if vessels:
        outlet = [line for line in _lines_on_route(ctx, vessels[0], None) if _cx(line) > _cx(vessels[0])]
        outlet_text = f" through {_line_phrase(ctx, outlet[0])}" if outlet else " through the outlet liquid line"
        liquid = [c for c in ctx.dests if any(word in _conn_name(c) for word in ("separat", "liquid", "oil", "condensate", "water"))]
        chosen = liquid or list(ctx.dests)
        if chosen:
            places = _and([_place_name(_conn_name(c)) for c in chosen[:3]])
            sentences.append(
                f"{vessels[0]['tag']} separates the liquid from vapor and liquid flows{outlet_text} going to {places}."
            )
        else:
            sentences.append(f"{vessels[0]['tag']} separates the liquid from vapor.")
    elif not sentences:
        sentences.append(f"{fluid.capitalize()} from {ctx.src_text()} to {ctx.dest_text()}.")
    text = " ".join(sentences)
    return text


def _listed(items, key, limit=12):
    tags = []
    for item in items:
        tag = str(item.get(key) or "").strip()
        if tag and tag not in tags:
            tags.append(tag)
    if not tags:
        return "none read"
    shown = ", ".join(tags[:limit])
    more = f" and {len(tags) - limit} more" if len(tags) > limit else ""
    return shown + more


_TAG_KEY = re.compile(r"\b([A-Z]{1,8}-[A-Z0-9][A-Z0-9./-]*)\b", re.I)


def _safeguard_key(text):
    """One device is one line, even when the drawing repeats the same tag."""
    found = _TAG_KEY.findall(str(text or ""))
    if found:
        return found[0].upper().replace(" ", "")
    return re.sub(r"\s+", " ", str(text or "")).strip().lower()


def _unique_sg(items):
    seen = set()
    out = []
    for item in items or []:
        if isinstance(item, dict):
            tag = re.sub(r"\s+", "", str(item.get("tag") or "")).upper()
            key = tag if tag and tag != "-" else _safeguard_key(item.get("text"))
        else:
            key = _safeguard_key(item)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def sg(text, tag, strong=False):
    return {"text": text, "tag": tag, "strong": strong}


def _tag_number(tag):
    match = re.search(r"(\d{3,})", str(tag or ""))
    return match.group(1) if match else ""


def _numbers_match(left, right):
    if not left or not right:
        return False
    if left == right:
        return True
    short, long = (left, right) if len(left) <= len(right) else (right, left)
    return long.startswith(short) and len(long) - len(short) <= 1


def _owner(ctx, inst):
    """The large equipment this tag belongs to, from the tag number, then from its position."""
    number = _tag_number(inst.get("tag"))
    owners = [item for item in _large_equipment(ctx) if _numbers_match(number, _tag_number(item.get("tag")))]
    if owners:
        return owners[0]
    return _nearest_large(ctx, inst.get("box"))


def _same_equipment(ctx, inst, eq):
    """A safeguard counts for this equipment when it belongs to that equipment."""
    if eq is None:
        return True
    owner = _owner(ctx, inst)
    return bool(owner and owner.get("tag") == eq.get("tag"))


def _has_strong(items):
    return any(item.get("strong") for item in items)


def trip_safeguards(ctx, var, direction, eq=None):
    """Trips and alarms that stop this variable on this equipment. An alarm is not a strong safeguard."""
    word = {"T": "temperature", "P": "pressure", "L": "level", "F": "flow"}.get(var, "process")
    trips, alarms = [], []
    for inst in ctx.instruments:
        letters = str(inst.get("letters") or "")
        if not letters or letters[0] != var or inst.get("category") == "relief":
            continue
        if not _same_equipment(ctx, inst, eq):
            continue
        rest = letters[1:]
        cat = inst.get("category")
        high = "H" in rest
        low = "L" in rest
        if cat == "alarm" and ((direction == "H" and high) or (direction == "L" and low)):
            alarms.append(inst)
        elif cat in ("trip", "switch") or "HH" in rest or "LL" in rest or rest[:1] == "S":
            if (direction == "H" and high) or (direction == "L" and low):
                trips.append(inst)
    out = []
    for inst in trips:
        rest = str(inst.get("letters") or "")[1:]
        if direction == "H":
            limit = "high-high" if "HH" in rest else "high"
        else:
            limit = "low-low" if "LL" in rest else "low"
        closers = _shutdown_for(ctx, inst)
        action = f", closing {_join_tags([c['tag'] for c in closers])}" if closers else ""
        out.append(sg(f"{inst['tag']} {limit} {word} trip{action}", inst["tag"], strong=True))
    for inst in alarms:
        rest = str(inst.get("letters") or "")[1:]
        if direction == "H":
            limit = "high-high" if "HH" in rest else "high"
        else:
            limit = "low-low" if "LL" in rest else "low"
        out.append(sg(f"{inst['tag']} {limit} {word} alarm", inst["tag"]))
    return out


def ctx_var(i):
    return i["variable"].split(" /")[0].lower()


def controller_safeguard(ctx, var, direction=None):
    out = []
    for c in ctx.find(var=var, cats=("controller",)):
        text = f"{c['tag']} {ctx_var(c)} control"
        if c.get("set_point"):
            text += f" (set {c['set_point']})"
        out.append(sg(text, c["tag"]))
    return out


_RELIEF_LETTERS = {"PSV", "PSE", "PZV", "PRV"}
_SHUTDOWN_LETTERS = {"SDV", "ESDV", "XV", "BDV", "USV", "SSV", "UZV"}


def _is_relief(inst):
    letters = str(inst.get("letters") or "")
    return inst.get("category") == "relief" or letters in _RELIEF_LETTERS


def _shutdown_valves(ctx):
    found, seen = [], set()
    for inst in ctx.instruments:
        letters = str(inst.get("letters") or "")
        tag = str(inst.get("tag") or "")
        head = tag.split("-")[0]
        if letters in _SHUTDOWN_LETTERS or head in _SHUTDOWN_LETTERS:
            if tag and tag not in seen:
                seen.add(tag)
                found.append(inst)
    for valve in ctx.valves:
        code = str(valve.get("code") or "")
        if code.split("-")[0] in _SHUTDOWN_LETTERS and code not in seen:
            seen.add(code)
            found.append({"tag": code, "box": valve.get("box"), "loop": "", "letters": code.split("-")[0]})
    return found


def _shutdown_for(ctx, inst):
    """The shutdown valve this trip closes, from the same loop or drawn beside it."""
    loop = str(inst.get("loop") or "")
    box = inst.get("box")
    out = []
    for valve in _shutdown_valves(ctx):
        same_loop = loop and (str(valve.get("loop") or "") == loop or str(valve.get("number") or "").startswith(loop) or loop in str(valve.get("tag") or ""))
        near = box and valve.get("box") and (abs(_cx(valve) - _cx({"box": box})) <= 0.12)
        if same_loop or near:
            out.append(valve)
    return out


def relief_safeguards(ctx, eq=None):
    out = []
    for p in ctx.instruments:
        if not _is_relief(p) or not _same_equipment(ctx, p, eq):
            continue
        text = f"{p['tag']} pressure safety valve"
        if p.get("set_psig"):
            text += f" set at {p['set_psig']} psig"
        here = _equip_name(_nearest_large(ctx, p.get("box")), "")
        if here:
            text += f" on {here}"
        if ctx.flare_lines:
            text += " to flare"
        if p.get("fire_case"):
            text += " (sized for fire case)"
        out.append(sg(text, p["tag"], strong=True))
    return out


def check_safeguards(ctx, eq=None):
    found, seen = [], set()
    for inst in ctx.instruments:
        if not (str(inst.get("letters") or "").startswith("FSV") or inst.get("category") == "safety"):
            continue
        if not _same_equipment(ctx, inst, eq):
            continue
        tag = str(inst.get("tag") or "").upper()
        if not tag or tag in seen:
            continue
        seen.add(tag)
        found.append(inst)
    out = [sg(f"{i['tag']} check valve", i["tag"], strong=True) for i in found]
    if not out:
        for valve in ctx.valves_of("check"):
            code = str(valve.get("code") or "").upper()
            if not code or code in seen:
                continue
            seen.add(code)
            out.append(sg(f"Check valve {valve.get('code')}", valve["code"], strong=True))
            if len(out) >= 4:
                break
    return out


def skin_safeguards(ctx):
    return [sg("Heater skin / element temperature with trip in heater panel", i["tag"], strong=True)
            for i in ctx.instruments if i.get("remark") == "skin"]


def shutdown_alarms(ctx):
    xa = ctx.find(var="X", cats=("other", "alarm"))
    xa = [i for i in xa if "A" in i["letters"][1:]]
    return [sg("Common trouble / system shutdown alarms", ctx.tags(xa))] if xa else []


# -------------------------------------------------------------------- row helper

def _needed_device(deviation, cause):
    """The device that would stop this consequence when the P&ID does not show one."""
    text = str(cause or "")
    head = text.split(" ", 1)[0].upper()
    low = text.lower()
    name = str(deviation or "").lower()
    if head.startswith("LV") and "open" in low:
        return "an independent low-low level trip (LSLL) that stops gas blow-through"
    if head.startswith("LV") and "closed" in low:
        return "an independent high-high level trip (LSHH) on this vessel"
    if head.startswith("PV") and "open" in low:
        return "a pressure safety valve and a high-high pressure trip (PSHH) on this drum"
    if head.startswith("PV") and "closed" in low:
        return "a low-low pressure trip (PSLL)"
    if "relief" in name:
        return "a clear relief path, with the inlet and outlet valves car-sealed open"
    if "low level" in name or ("blow" in low and "level" in name):
        return "an independent low-low level trip (LSLL) that stops gas blow-through"
    if "high level" in name:
        return "an independent high-high level trip (LSHH) on this vessel"
    if "reverse" in name:
        return "a check valve on the line that can flow backwards"
    if "high pressure" in name:
        return "a pressure safety valve and a high-high pressure trip (PSHH) on this equipment"
    if "low pressure" in name or "loss of supply" in low:
        return "a low-low pressure trip (PSLL)"
    if "high temperature" in name:
        return "an independent high-high temperature trip (TSHH)"
    if "low temperature" in name:
        return "a low-low temperature trip (TSLL)"
    if "flow" in name:
        return "a low-low pressure trip (PSLL) on loss of supply"
    return "an independent trip or relief device that stops this consequence"


def _fill_recommendations(node, ctx):
    """Every cause with no stopping device, or only an alarm, gets a recommendation."""
    for group in node.get("deviations") or []:
        deviation = group.get("deviation") or ""
        for item in group.get("rows") or []:
            if item.get("recommendations"):
                continue
            texts = item.get("safeguards") or []
            empty = not texts or texts == ["None identified on this P&ID"]
            stops = any(any(word in text.lower() for word in (
                "trip", "safety valve", "check valve", "fail-closed", "fail-open", "fail closed", "fail open", "car-sealed"))
                        for text in texts)
            if empty:
                device = _needed_device(deviation, item.get("cause"))
                item["recommendations"] = [ctx.recs.add(
                    f"No safeguard on this P&ID stops this consequence. Provide {device}.")]
            elif not stops:
                item["recommendations"] = [ctx.recs.add(
                    "The safeguard shown is an alarm only and does not stop this consequence. "
                    f"Confirm an independent trip is provided. If it is not, provide {_needed_device(deviation, item.get('cause'))}.")]


def row(cause, consequences, cc, safeguards, c, base_l, recs=()):
    """C and L are this scenario's intents, placed on the levels of the uploaded risk-matrix file."""
    safeguards = _unique_sg(safeguards)[:5]
    strong = any(s["strong"] for s in safeguards)
    c, l = risk.from_basis(c, max(1, base_l - (1 if strong else 0)))
    return {
        "cause": cause,
        "consequences": consequences,
        "cc": cc,
        "safeguards": [s["text"] for s in safeguards] or ["None identified on this P&ID"],
        "tags": [s["tag"] for s in safeguards] or ["-"],
        "c": c,
        "l": l,
        "risk": evaluate(c, l),
        "recommendations": list(recs),
    }


def dev(name, rows):
    rows = [r for r in rows if r]
    return {"deviation": name, "rows": rows} if rows else None


# ------------------------------------------------------------- equipment nodes

KIND_LABEL = {"heater": "heater", "vessel": "vessel", "exchanger": "heat exchanger", "pump": "pump",
              "compressor": "compressor", "tank": "tank", "equipment": "equipment"}


def _point_box(px, py, box):
    dx = max(box[0] - px, 0, px - box[2])
    dy = max(box[1] - py, 0, py - box[3])
    return (dx * dx + dy * dy) ** 0.5


def _nearest_line(lines, box, limit=0.1):
    if not box:
        return None
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    best, dist = None, 1e9
    for line in lines:
        boxes = line.get("boxes") or ([line["box"]] if line.get("box") else [])
        for candidate in boxes:
            d = _point_box(cx, cy, candidate)
            if d < dist:
                best, dist = line, d
    if best is None or (limit is not None and dist > limit):
        return None
    return best


def _isolation_valves(ctx):
    return [v for v in ctx.valves if any(str(v.get("type") or "").lower().startswith(kind) for kind in _ISOLATION)]


def _isolation_cause(ctx, box, anchor):
    """Name the isolation valves next to one component instead of a generic valve."""
    valves = [v for v in _isolation_valves(ctx) if v.get("box") and box and _near_any(v["box"], [box], 0.08)]
    if valves:
        return f"Inadvertent closure of {ctx.names(valves)} on the line through {anchor}."
    line = _nearest_line(ctx.process_lines, box)
    if line:
        return (f"Inadvertent closure of an isolation valve on {line['tag']} "
                f"(piping class {line.get('spec') or 'not read'}) through {anchor}. No valve tag was read on that line.")
    return f"Inadvertent closure of an isolation valve on the line through {anchor}. No valve tag was read next to it."


def _spec_text(code, line_tags):
    shown = ", ".join(line_tags[:4])
    more = f" +{len(line_tags) - 4}" if len(line_tags) > 4 else ""
    where = f" on {shown}{more}" if shown else ""
    info = kb.spec(code)
    if not info:
        return f"{code}{where}: not in the uploaded piping specification"
    psig = kb.spec_rating_psig(code)
    rating = " ".join(x for x in (info.get("rating"), info.get("material"), f"{psig} psig" if psig else "") if x)
    return f"{code}{where}: {rating}"


def _place_row(node, deviation, cause, consequences, safeguards, c, base_l, recs=()):
    """Add one cause under the deviation that matches this component's duty."""
    found = next((d for d in node.setdefault("deviations", [])
                  if str(d.get("deviation") or "").endswith(deviation)), None)
    if found is None:
        found = {"deviation": deviation, "rows": []}
        node["deviations"].append(found)
    found.setdefault("rows", []).append(row(cause, consequences, "A" if c < 4 else "S", safeguards, c, base_l, recs))


def _instrument_duty(inst):
    """What this instrument is on the drawing to do, from its ISA letters."""
    letters = inst.get("letters") or ""
    meaning = kb.describe_instrument(letters) if letters else (inst.get("tag") or "instrument")
    category = inst.get("category")
    if category == "controller":
        point = f" at {inst['set_point']}" if inst.get("set_point") else ""
        return f"control the process ({meaning}{point})"
    if category == "control_valve":
        fail = {"FC": " and close on loss of air", "FO": " and open on loss of air", "FL": " and stay put on loss of air"}.get(inst.get("fail_action") or "", "")
        return f"regulate the process ({meaning}{fail})"
    if category == "trip":
        return f"trip the process ({meaning})"
    if category == "alarm":
        return f"warn the operator ({meaning})"
    if category == "switch":
        return f"switch at the set limit ({meaning})"
    if category == "relief":
        set_at = f", set at {inst['set_psig']} psig" if inst.get("set_psig") else ""
        return f"relieve pressure before the piping or equipment is overpressured{set_at}"
    if category == "indicator":
        return f"show the measurement locally ({meaning})"
    return meaning[0].lower() + meaning[1:] if meaning else "measure the process"


def _instrument_deviation(inst):
    letters = inst.get("letters") or ""
    rest = letters[1:]
    high = "H" in rest
    low = "L" in rest and not high
    var = letters[:1]
    if inst.get("category") == "relief":
        return "High Pressure"
    if inst.get("category") == "control_valve":
        return "No / Less Flow" if inst.get("fail_action") == "FC" else "More Flow"
    return {
        "F": "No / Less Flow" if low or not high else "More Flow",
        "P": "Low Pressure" if low else "High Pressure",
        "T": "Low Temperature" if low else "High Temperature",
        "L": "Low Level" if low else "High Level",
    }.get(var, "No / Less Flow")


def _instrument_effect(inst, duty):
    category = inst.get("category")
    tag = inst.get("tag") or "the instrument"
    if category == "trip":
        return f"{tag} no longer {duty}. The condition it was meant to stop can continue."
    if category == "alarm":
        return f"{tag} no longer {duty}. The operator is not told that the limit has been reached."
    if category == "controller":
        return f"{tag} no longer {duty}. The process variable moves away from its set point."
    if category == "control_valve":
        return f"{tag} no longer {duty}. Flow through the valve is no longer held at the intended rate."
    if category == "relief":
        return f"{tag} no longer {duty}. Pressure can rise above the piping class and equipment design."
    if category == "indicator":
        return f"{tag} no longer {duty}. The measurement is not available at the panel or locally."
    if category == "switch":
        return f"{tag} no longer {duty}. The action at that limit does not happen."
    return f"{tag} no longer does its duty ({duty})."


def _same_variable_safeguards(ctx, inst):
    letters = inst.get("letters") or ""
    if not letters:
        return []
    out = []
    for other in ctx.instruments:
        if other is inst or other.get("tag") == inst.get("tag"):
            continue
        if (other.get("letters") or "")[:1] != letters[:1]:
            continue
        if other.get("category") not in ("trip", "alarm", "controller", "relief", "switch"):
            continue
        out.append(sg(kb.describe_instrument(other.get("letters") or other.get("tag") or ""), other.get("tag") or "-",
                       strong=other.get("category") in ("trip", "relief")))
        if len(out) == 3:
            break
    if letters[:1] == "P":
        out.extend(relief_safeguards(ctx)[:1])
    return out


def _instrument_row(node, ctx, inst):
    duty = _instrument_duty(inst)
    tag = inst.get("tag") or "instrument"
    line = _nearest_line(ctx.lines, inst.get("box"), limit=None)
    where = f" on {line['tag']}" if line else ""
    _place_row(
        node, _instrument_deviation(inst),
        f"If {tag} faults{where}, it can no longer {duty}.",
        [_instrument_effect(inst, duty)],
        _same_variable_safeguards(ctx, inst),
        4 if inst.get("category") in ("trip", "relief", "control_valve") else 3, 2,
    )


def _nearest_large(ctx, box, side=0):
    """side -1 is upstream (to the left), +1 is downstream, 0 is the nearest."""
    items = _large_equipment(ctx)
    if not items:
        return None
    if not box:
        return items[0]
    cx = (box[0] + box[2]) / 2
    if side < 0:
        left = [e for e in items if _cx(e) < cx - 0.005]
        return left[-1] if left else None
    if side > 0:
        right = [e for e in items if _cx(e) > cx + 0.005]
        return right[0] if right else None
    return min(items, key=lambda e: abs(_cx(e) - cx))


def _downstream_drum(ctx, box):
    """The vessel or tank this valve feeds. Pressure relief on that drum is the safeguard."""
    drums = [item for item in _large_equipment(ctx) if item.get("kind") in ("vessel", "tank")]
    if not drums:
        return _nearest_large(ctx, box, 1)
    if not box:
        return drums[0]
    cx = (box[0] + box[2]) / 2
    right = [item for item in drums if _cx(item) >= cx - 0.02]
    pool = right or drums
    return min(pool, key=lambda item: abs(_cx(item) - cx))


def _equip_name(eq, fallback):
    if not eq:
        return fallback
    desc = str(eq.get("description") or "").strip()
    if desc and eq.get("tag") and eq["tag"] not in desc:
        return f"{desc} {eq['tag']}"
    return eq.get("tag") or fallback


def _line_toward(ctx, box, side):
    """The process line immediately left (side -1) or right (side +1) of a point on the P&ID."""
    if not box:
        return None
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    best, dist = None, None
    for line in ctx.process_lines:
        boxes = line.get("boxes") or ([line["box"]] if line.get("box") else [])
        for candidate in boxes:
            lx, ly = (candidate[0] + candidate[2]) / 2, (candidate[1] + candidate[3]) / 2
            if abs(ly - cy) > 0.2:
                continue
            if side < 0 and lx >= cx - 0.005:
                continue
            if side > 0 and lx <= cx + 0.005:
                continue
            gap = abs(lx - cx)
            if dist is None or gap < dist:
                best, dist = line, gap
    return best


def _cause_ltr(ctx, box, anchor, failure):
    """Name the line that reaches this point, without a reading instruction."""
    failure = str(failure).strip().rstrip(".")
    left = _line_toward(ctx, box, -1)
    if left and left["tag"] not in failure:
        return f"{failure} on {left['tag']} at {anchor}."
    return f"{failure}."


def _forward_match(ctx, tag, box):
    """The PFD stream that continues to the right of this point, from the PFD–P&ID line relation."""
    relation = getattr(ctx, "line_relation", None) or []
    right = _line_toward(ctx, box, 1)
    if right:
        for match in relation:
            if match.get("pid_line") and match["pid_line"] == right.get("tag"):
                return match
    tag_u = str(tag or "").upper()
    if not tag_u:
        return None
    for match in relation:
        if match.get("pid_line") and tag_u in str(match.get("pfd_from") or "").upper():
            return match
    return None


def _cons_related(ctx, box, tag, effect):
    """The local effect, then the PFD stream and P&ID line it travels on."""
    effect = str(effect or "").rstrip(".")
    match = _forward_match(ctx, tag, box)
    if not match:
        return effect + "."
    stream = str(match.get("pfd_stream") or "")
    dest = match.get("pfd_to") or "downstream"
    if re.fullmatch(r"\d{1,3}[A-Z]{0,2}", stream):
        carried = f"PFD stream {stream} on P&ID line {match['pid_line']}"
    else:
        carried = f"The PFD stream on P&ID line {match['pid_line']}"
    return f"{effect}. {carried} carries that to {dest}."


def _linked_valves(ctx, inst):
    loop = str(inst.get("loop") or "")
    if not loop:
        return []
    return [v for v in ctx.find(cats=("control_valve",)) if str(v.get("loop") or "") == loop or str(v.get("number") or "").startswith(loop)]


def _limit_word(letters):
    rest = str(letters or "")[1:]
    var = {"P": "pressure", "T": "temperature", "L": "level", "F": "flow"}.get(str(letters or "")[:1], "process condition")
    if "L" in rest and "H" not in rest:
        return "low", var
    if "H" in rest:
        return "high", var
    return "", var


def _named_safeguards(ctx, inst):
    """Devices on this P&ID that still stop the consequence if this instrument fails."""
    letters = str(inst.get("letters") or "")
    var = letters[:1]
    rest = letters[1:]
    direction = "L" if "L" in rest and "H" not in rest else "H"
    found = []
    own = str(inst.get("tag") or "")
    eq = _owner(ctx, inst)
    if var == "P" and direction == "H":
        found.extend(relief_safeguards(ctx, eq))
    if var in ("P", "T", "L", "F"):
        found.extend(trip_safeguards(ctx, var, direction, eq))
    out = []
    for item in found:
        if own and (item.get("tag") == own or own in str(item.get("text") or "")):
            continue
        if any(item.get("tag") == have.get("tag") for have in out):
            continue
        out.append(item)
    return out


def _specific_instrument_row(node, ctx, inst):
    cat = inst.get("category")
    letters = str(inst.get("letters") or "")
    tag = inst.get("tag") or "the instrument"
    fluid = ctx.fluid
    up = _equip_name(_nearest_large(ctx, inst.get("box"), -1), _soft(ctx.src_text()))
    down = _equip_name(_nearest_large(ctx, inst.get("box"), 1), _soft(ctx.dest_text()))
    here = _equip_name(_nearest_large(ctx, inst.get("box")), down)
    limit, word = _limit_word(letters)
    linked = _linked_valves(ctx, inst)
    names = _join_tags([v.get("tag") for v in linked]) or tag
    if cat == "controller" and letters[:1] == "P":
        deviation, cause = "High Pressure", f"{tag} fails, so pressure control of the {fluid} through {names} is lost."
        cons = [f"{fluid.capitalize()} pressure between {up} and {down} moves off the set point. {down} can see the upstream pressure, or the supply of {fluid} to {down} can stop."]
    elif cat == "controller" and letters[:1] == "T":
        deviation, cause = "High Temperature", f"{tag} fails, so temperature control of the {fluid} through {names} is lost."
        cons = [f"The {fluid} leaves {here} hotter or colder than intended and arrives off specification at {down}."]
    elif cat == "controller" and letters[:1] == "L":
        deviation, cause = "High Level", f"{tag} fails, so level control in {here} is lost."
        cons = [f"Level in {here} rises until liquid carries into the vapour outlet, or falls until gas blows through the liquid outlet toward {down}."]
    elif cat == "controller" and letters[:1] == "F":
        deviation, cause = "More Flow", f"{tag} fails, so flow control of the {fluid} through {names} is lost."
        cons = [f"Flow of {fluid} from {up} to {down} is no longer held at the intended rate."]
    elif cat == "trip":
        deviation = {"P": "High Pressure", "T": "High Temperature", "L": "High Level", "F": "No / Less Flow"}.get(letters[:1], "Other")
        if limit == "low":
            deviation = {"P": "Low Pressure", "T": "Low Temperature", "L": "Low Level", "F": "No / Less Flow"}.get(letters[:1], deviation)
        cause = f"{tag} fails to trip on {limit or word} {word} at {here}."
        cons = [f"The {limit or 'abnormal'} {word} at {here} continues, and {fluid} can leave {here} outside its intended limits toward {down}."]
    elif cat == "alarm":
        deviation = {"P": "High Pressure", "T": "High Temperature", "L": "High Level", "F": "No / Less Flow"}.get(letters[:1], "Other")
        cause = f"{tag} fails, so the operator is not warned of {limit or word} {word} at {here}."
        cons = [f"{(limit or 'Abnormal').capitalize()} {word} at {here} continues with no operator action until a trip or a relief device acts."]
    elif cat == "relief":
        set_at = f" at {inst['set_psig']} psig" if inst.get("set_psig") else ""
        deviation, cause = "High Pressure", f"{tag} fails to open{set_at} to protect {here}."
        cons = [f"Pressure in {here} can rise above the design pressure read on the P&ID. Loss of containment of {ctx.release} can follow."]
    elif cat == "switch":
        deviation, cause = "Other", f"{tag} fails to switch on {limit or word} {word} at {here}."
        cons = [f"The {limit or 'set'} {word} action at {here} does not happen, so {fluid} stays on the path toward {down}."]
    else:
        return
    _place_row(node, deviation, _cause_ltr(ctx, inst.get("box"), tag, cause),
               [_cons_related(ctx, inst.get("box"), here, item) for item in cons],
               _named_safeguards(ctx, inst), 4 if cat in ("trip", "relief") else 3, 2)


def _component_rows(node, ctx):
    """One specific cause for each controlling, trip, alarm or relief instrument on this node."""
    for inst in _reading_order(ctx.instruments):
        if inst.get("category") in ("indicator", "element", "relay", "other", "control_valve", None, ""):
            continue
        if inst.get("category") == "control_valve":
            continue
        mentioned = inst.get("tag") or ""
        if mentioned and mentioned in str(node.get("deviations") or ""):
            continue
        _specific_instrument_row(node, ctx, inst)


def _pinpoint_node(node, ctx, color=None):
    """Name each component by its duty, and write the node description from the start and the equipment."""
    _component_rows(node, ctx)
    node["boundary"] = _node_description(ctx, color)
    node["design_intent"] = _overall_intent(ctx)
    by_spec = {}
    for line in ctx.lines:
        if line.get("spec"):
            by_spec.setdefault(line["spec"], []).append(line["tag"])
    node_tags = {line["tag"] for line in ctx.lines}
    spec_rows = []
    for br in ctx.ext.get("spec_breaks") or []:
        specs = [s for s in (br.get("specs") or []) if s]
        if len(specs) < 2:
            continue
        linked = [t for t in (br.get("lines") or []) if t in node_tags]
        if by_spec and not any(s in by_spec for s in specs) and not linked:
            continue
        where = f" between {' and '.join(linked)}" if linked else ""
        described = " and ".join(_spec_text(code, by_spec.get(code) or []) for code in specs)
        spec_rows.append(row(
            f"Piping class changes at the {' / '.join(specs)} spec break{where}.",
            [f"{described}. The lower-rated class can see the upstream design pressure across this spec break."],
            "S", relief_safeguards(ctx), 4, 2,
            [ctx.recs.add(
                f"Confirm the {' / '.join(specs)} spec break{where or ' in this node'} is on the correct side of the "
                "pressure source and that the downstream class is rated for the upstream design pressure.")],
        ))
    if len(by_spec) > 1 and not spec_rows:
        listing = "; ".join(_spec_text(code, tags) for code, tags in by_spec.items())
        spec_rows.append(row(
            f"This node contains more than one piping class ({listing}), and no spec break was read between them.",
            ["The place where the piping class changes was not read, so the lower-rated line may see the higher-rated pressure."],
            "S", [], 4, 2,
            [ctx.recs.add("Mark the piping spec break on the P&ID and confirm the lower-rated class can withstand the upstream design pressure.")],
        ))
    for code, tags in by_spec.items():
        if kb.spec(code):
            continue
        spec_rows.append(row(
            f"Piping class {code} on {', '.join(tags[:4])} is not in the uploaded piping specification.",
            ["Rating, material and temperature limits for this class were not available, so this line could not be checked against the specification."],
            "A", [], 3, 2,
            [ctx.recs.add(f"Add piping class {code} to the piping specification used for this study.")],
        ))
    if spec_rows:
        node.setdefault("deviations", []).append({"deviation": "Piping Specification", "rows": spec_rows})

    node["design_conditions"] = _design_conditions(ctx) or "Not shown on the P&ID."
    _fill_recommendations(node, ctx)


def equipment_node(ctx, eq, nid):
    tag, kind = eq["tag"], eq["kind"]
    d = eq["design"]
    label = KIND_LABEL.get(kind, "equipment")
    desc = eq["description"] or label.capitalize()
    cvs = [item for item in ctx.find(cats=("control_valve",)) if _same_equipment(ctx, item, eq)]
    cv = cvs[0]["tag"] if cvs else None
    sev_loc = 5 if ctx.hydrocarbon else 3
    p_des, t_des = d.get("p_des"), d.get("t_des")
    spec = ctx.proc_spec
    devs = []

    # ---- flow
    no_flow_cons = {
        "heater": f"{tag} remains energized with no / low flow; element and skin temperature rise, heater damage / burnout and high outlet temperature.",
        "pump": f"{tag} runs dry / dead-headed; seal damage and loss of containment of {ctx.release}.",
        "compressor": f"{tag} surge / recycle; machine damage.",
        "exchanger": f"Loss of heat transfer in {tag}; off-spec outlet temperature.",
        "vessel": f"Loss of level / inventory in {tag}; possible gas blow-by to downstream.",
    }.get(kind, f"Loss of flow through {tag}.")
    temp_trips = trip_safeguards(ctx, "T", "H", eq)
    flow_trips = trip_safeguards(ctx, "F", "L", eq)
    supply_sg = trip_safeguards(ctx, "P", "L", eq)
    if kind == "heater":
        supply_sg = supply_sg + skin_safeguards(ctx) + temp_trips
    closed_rows, open_rows = [], []
    for item in sorted(cvs, key=lambda valve: _cx(valve)):
        name = item["tag"]
        cv_var = str(item.get("letters") or "")[:1]
        drum = _downstream_drum(ctx, item.get("box")) or eq
        drum_name = _equip_name(drum, tag)
        if cv_var == "L":
            level_eq = eq if kind in ("vessel", "tank") else drum
            closed_sg = trip_safeguards(ctx, "L", "H", level_eq)
            open_sg = trip_safeguards(ctx, "L", "L", level_eq)
            closed_effect = f"{name} fails closed on {tag}. The liquid outlet is blocked and the level rises. Liquid carries into the vapour outlet"
            open_effect = f"{name} fails open on {tag}. Liquid leaves the vessel and the liquid seal is lost. Gas blows through the liquid outlet"
        elif cv_var == "P":
            closed_sg = trip_safeguards(ctx, "P", "L", eq)
            open_sg = relief_safeguards(ctx, drum) + trip_safeguards(ctx, "P", "H", drum)
            closed_effect = f"{name} fails closed. Flow of {ctx.fluid} through {tag} stops"
            open_effect = f"{name} fails open. Pressure letdown is lost and pressure at {drum_name} rises toward the upstream pressure. {drum_name} can be overpressured"
        elif kind == "heater":
            duty = f" ({d['duty_mmbtu_hr']} MMBtu/hr)" if d.get("duty_mmbtu_hr") else ""
            closed_sg = trip_safeguards(ctx, "P", "L", eq)
            open_sg = trip_safeguards(ctx, "T", "L", eq)
            closed_effect = f"{name} fails closed. Flow of {ctx.fluid} through {tag} stops while the heater can stay energised"
            open_effect = f"{name} fails open. Flow exceeds the heating capacity of {tag}{duty}. The outlet stays colder than intended and hydrate formation can follow"
        else:
            closed_sg = trip_safeguards(ctx, "P", "L", eq)
            open_sg = trip_safeguards(ctx, "P", "L", eq)
            closed_effect = f"{name} fails closed. Flow of {ctx.fluid} through {tag} stops"
            open_effect = f"{name} fails open. Flow through {tag} rises above the intended rate"
        closed_rows.append(row(
            _cause_ltr(ctx, item.get("box"), name, f"{name} fails closed."),
            [_cons_related(ctx, item.get("box"), tag, closed_effect)],
            "S" if kind == "heater" else "A", closed_sg, 4 if kind == "heater" else 3, 3))
        open_rows.append(row(
            _cause_ltr(ctx, item.get("box"), name, f"{name} fails open."),
            [_cons_related(ctx, item.get("box"), tag, open_effect)],
            "S" if kind == "heater" or cv_var == "P" else "A", open_sg, 4 if cv_var == "P" else 3, 2))
    rec_flow = []
    if kind in ("heater", "pump", "compressor") and not _has_strong(flow_trips) and not _has_strong(supply_sg):
        panel = next((e["tag"] for e in ctx.equipment if e["kind"] == "panel"), f"the {label} control system")
        rec_flow.append(ctx.recs.add(
            f"Confirm that {panel} includes a low-flow / flow-proving permissive that trips {tag} on loss of flow; "
            f"if not, provide a low-low flow trip (FSLL)."))
    devs.append(dev("No / Less Flow", [
        row(_cause_ltr(ctx, eq.get("box"), tag, "Loss of supply."),
            [_cons_related(ctx, eq.get("box"), tag, no_flow_cons.rstrip(".")),
             _cons_related(ctx, eq.get("box"), tag, f"Loss of {ctx.fluid} supply downstream of {tag}")],
            "S" if kind in ("heater", "pump", "compressor") else "A", supply_sg, 4 if kind == "heater" else 3, 3, rec_flow),
        *closed_rows,
    ]))
    if open_rows:
        devs.append(dev("More Flow", open_rows))

    # ---- reverse flow
    rev_rows = [row(_cause_ltr(ctx, eq.get("box"), tag, "Loss of upstream pressure while downstream stays pressurized."),
                    [_cons_related(ctx, eq.get("box"), tag, f"Backflow of {ctx.fluid} through {tag} toward the upstream side")],
                    "A", check_safeguards(ctx, eq), 3, 2,
                    [] if check_safeguards(ctx, eq) else [ctx.recs.add(f"Provide a check valve on the outlet of {tag} to prevent reverse flow.")])]
    if len(ctx.sources) >= 2:
        names = " and ".join(c["description"] + (f" ({c['line']})" if c["line"] else "") for c in ctx.sources)
        checks = check_safeguards(ctx, eq)
        if checks:
            cause = f"One inlet check valve fails open while the sources {names} are at different pressures."
            safeguards = checks
            recs = []
        else:
            cause = f"Pressure imbalance between inlet sources {names}; the sources join with no check valves shown on this P&ID."
            safeguards = []
            recs = [ctx.recs.add(f"Verify on upstream drawings that check valves are provided on each incoming line ({names}) and that "
                                 f"each source is rated for the maximum pressure of the other.")]
        rev_rows.append(row(cause,
            ["Higher-pressure source backflows into the lower-pressure source; possible overpressure / contamination of upstream equipment."],
            "S", safeguards, 4, 2, recs))
    devs.append(dev("Reverse Flow", rev_rows))

    # ---- high pressure
    hp_rows = []
    psv = relief_safeguards(ctx, eq)
    psv_items = [item for item in ctx.find(cats=("relief",)) if _same_equipment(ctx, item, eq)]
    fire_only = any(p.get("fire_case") for p in psv_items)
    if p_des and spec and spec["rating_psig"] and spec["rating_psig"] > p_des:
        recs_ = []
        if fire_only:
            recs_.append(ctx.recs.add(
                f"{ctx.tags(psv_items)} is noted as sized for FIRE case only. Verify maximum settle-out / shut-in pressure of "
                f"{ctx.src_text()} against {tag} design pressure ({p_des} psig); if it can be exceeded, evaluate the "
                f"blocked-outlet relief case or provide PSHH with inlet SDV (API RP 14C)."))
        elif not psv_items:
            recs_.append(ctx.recs.add(f"Provide overpressure protection for {tag} (design {p_des} psig) against upstream source pressure."))
        hp_rows.append(row(
            _cause_ltr(ctx, eq.get("box"), tag,
                       f"High supply pressure. Piping spec {spec['spec']} is rated {spec['rating_psig']} psig but {tag} design pressure is {p_des} psig."),
            [_cons_related(ctx, eq.get("box"), tag,
                           f"Overpressure of {tag} above design pressure; rupture and loss of containment of {ctx.release}")],
            "S", psv + trip_safeguards(ctx, "P", "H", eq), 5, 3, recs_))
    else:
        hp_rows.append(row(
            _cause_ltr(ctx, eq.get("box"), tag, "High supply pressure."),
            [_cons_related(ctx, eq.get("box"), tag, f"Overpressure of {tag} and possible loss of containment of {ctx.release}")],
            "S", psv + trip_safeguards(ctx, "P", "H", eq), sev_loc, 2,
            [] if psv_items else [ctx.recs.add(f"Confirm overpressure protection of {tag} for the maximum upstream source pressure.")]))
    blocked_cause = f"Blocked outlet ({cv} fails closed or outlet valve closed)" if cv else "Blocked outlet (outlet valve closed)"
    if kind == "heater":
        blocked_cause += " with heater energized - thermal expansion of blocked-in fluid."
    hp_rows.append(row(blocked_cause + ("" if kind == "heater" else "."),
                       [f"Pressure rise in {tag} and outlet piping; potential overpressure of {tag}."],
                       "S", (temp_trips + skin_safeguards(ctx) if kind == "heater" else []) + psv, sev_loc, 2))
    manual_vent = [v for v in ctx.valves_of("globe") if ctx.flare_lines]
    bdv = ctx.find(letters=("BDV",))
    hp_rows.append(row(f"External fire in the area of {tag}.",
                       [f"Overpressure and weakening of {tag} shell and piping; escalation of fire."],
                       "S", psv + [sg("Manual depressuring to flare", ctx.names(manual_vent[:1]))] if manual_vent else psv,
                       sev_loc, 2,
                       [] if bdv else [ctx.recs.add(
                           f"Confirm whether an automatic blowdown valve (BDV) is required for {tag} per the company fire / "
                           f"depressuring philosophy; none is shown on this P&ID.")]))
    devs.append(dev("High Pressure", hp_rows))

    devs.append(dev("Low Pressure", [
        row(_cause_ltr(ctx, eq.get("box"), tag, "Low supply pressure."),
            [_cons_related(ctx, eq.get("box"), tag, f"Low pressure supply downstream of {tag}")], "A",
            trip_safeguards(ctx, "P", "L", eq), 2, 3),
    ]))

    # ---- temperature
    if kind in ("heater", "exchanger", "compressor"):
        ht = []
        tic = ctx.find(var="T", cats=("controller",))
        recs_ = []
        if t_des and spec and spec.get("max_temp_f") is not None and t_des > spec["max_temp_f"]:
            recs_.append(ctx.recs.add(
                f"{tag} design temperature ({t_des} {DEG}) exceeds the {spec['spec']} piping maximum design temperature "
                f"({spec['max_temp_f']} {DEG}). Confirm the high-high temperature trip set point is below {spec['max_temp_f']} {DEG} "
                f"with margin and verify the design temperature of the outlet piping."))
        if not _has_strong(temp_trips):
            recs_.append(ctx.recs.add(f"Provide an independent high-high temperature trip on {tag} outlet."))
        cons = [f"Outlet temperature rises above design limits"
                + (f" (piping {spec['spec']} max {spec['max_temp_f']} {DEG}" if spec and spec.get("max_temp_f") is not None else "")
                + (f", {tag} design {t_des} {DEG})" if t_des else (")" if spec else ""))
                + f"; reduced pressure rating of piping, {label} damage, possible loss of containment."]
        sg_ht = temp_trips + skin_safeguards(ctx) + [sg("Local temperature indication", i["tag"])
                                                       for i in ctx.find(var="T", letters=("TI", "TG"))[:1]] + shutdown_alarms(ctx)
        if tic:
            ht.append(row(f"Temperature control failure - {ctx.tags(tic)} or its transmitter fails, driving {tag} to maximum duty.",
                          cons, "S", sg_ht, 4, 3, recs_))
        if eq.get("electric"):
            ht.append(row(f"Heater power controller in {next((e['tag'] for e in ctx.equipment if e['kind'] == 'panel'), 'the heater panel')} fails 'on'.",
                          [f"{tag} stays at maximum duty. Outlet temperature rises above the design limit and the piping pressure rating falls."],
                          "S", sg_ht, 4, 3,
                          [ctx.recs.add(f"Confirm the SIS high-high temperature trip de-energizes {tag} through a contactor / breaker "
                                        f"independent of the BPCS power controller.")] if _has_strong(temp_trips) else recs_))
        ht.append(row(f"Low or no flow through {tag} while the heater stays in service.",
                      [f"{tag} stays energised with little flow. Element and skin temperature rise, and the outlet temperature goes above the design limit."],
                      "S", sg_ht, 4, 3, rec_flow))
        devs.append(dev("High Temperature", ht))

        lt = []
        if kind == "heater":
            lt.append(row(f"{tag} trip, loss of power / fuel, or heater switched off.",
                          [f"No heating. {ctx.fluid.capitalize()} leaves {tag} colder than intended"
                           + (f" and arrives cold at {cv}." if cv else ".")],
                          "S", shutdown_alarms(ctx) + controller_safeguard(ctx, "T", "L") + trip_safeguards(ctx, "T", "L"), 4, 3))
        lt.append(row("Low inlet temperature in cold ambient conditions" + (f" (normal operating {d['t_op']} {DEG})." if d.get("t_op") is not None else "."),
                      [f"Increased duty demand on {tag}; possible hydrate formation if the gas is wet." if ctx.gas else f"Increased duty demand on {tag}."],
                      "A", controller_safeguard(ctx, "T"), 2, 2))
        devs.append(dev("Low Temperature", lt))

    # ---- level (vessels / tanks)
    if kind in ("vessel", "tank"):
        lsh = trip_safeguards(ctx, "L", "H", eq)
        lsl = trip_safeguards(ctx, "L", "L", eq)
        devs.append(dev("High Level", [row(
            _cause_ltr(ctx, eq.get("box"), tag, f"The liquid outlet of {tag} is blocked."),
            [_cons_related(ctx, eq.get("box"), tag, f"Liquid carries over from {tag} into the gas outlet")], "S",
            lsh, 4, 3,
            [] if _has_strong(lsh) else [ctx.recs.add(f"Provide an independent high-high level trip (LSHH) on {tag}.")])]))
        devs.append(dev("Low Level", [row(
            _cause_ltr(ctx, eq.get("box"), tag, f"The level valve on {tag} fails open."),
            [_cons_related(ctx, eq.get("box"), tag, f"Liquid leaves {tag} and gas blows through the liquid outlet")],
            "S", lsl, 5, 3,
            [] if _has_strong(lsl) else [ctx.recs.add(f"Provide an independent low-low level trip (LSLL) on {tag} to prevent gas blow-by.")])]))

    # ---- composition
    wet_src = [l for l in ctx.process_lines if l["service"] in ("P", "R")]
    if wet_src or kind in ("heater", "vessel", "compressor"):
        src = ", ".join(l["tag"] for l in wet_src) or ctx.src_text()
        cons = {"heater": [f"Liquid entry into {tag} - localized boiling, hot spots, fouling" + (" and sour corrosion." if ctx.sour else "."),
                           "Hydrate formation downstream; liquids carried to downstream equipment."],
                "compressor": [f"Liquid ingress into {tag} - machine damage."]}.get(kind, [f"Liquids / contaminants entering {tag}; off-spec product, fouling, corrosion."])
        kodrum = [e for e in ctx.equipment if e["kind"] == "vessel" and e["tag"] != tag]
        devs.append(dev("Composition / Contamination", [row(
            f"Liquids (water / condensate) or contaminants carried over from {src}.", cons, "A",
            [sg("Downstream knock-out drum", kodrum[0]["tag"])] if kodrum else [], 3, 3,
            [ctx.recs.add(f"Confirm that the feed from {src} is free of liquids; if not, consider an inlet scrubber / filter-separator upstream of {tag}.")]
            if kind in ("heater", "compressor") else [])]))

    # ---- maintenance
    high_class = spec and spec.get("rating") and any(c in spec["rating"] for c in ("900", "1500", "2500"))
    devs.append(dev("Maintenance / Isolation", [row(
        f"Isolation of {tag} for maintenance; venting / draining through bleed valves.",
        [f"Release of residual {ctx.release} to atmosphere - personnel exposure, fire."]
        + ([f"Single isolation valve against high pressure ({spec['rating']}); a passing valve exposes maintenance personnel."] if high_class else []),
        "S", [sg("Isolation valves with bleed valves", ctx.names(ctx.valves_of("ball")[:2]))] if ctx.valves else [], 4, 3,
        [ctx.recs.add(f"Review isolation of {tag} against the company isolation philosophy"
                      + (f" for {spec['rating']} sour service" if high_class and ctx.sour else "")
                      + "; consider double block and bleed and routing vents / drains to a closed system.")])]))

    design = []
    if p_des or d.get("p_op"):
        design.append(f"{tag}: {p_des or '-'} psig (design) / {d.get('p_op', '-')} psig (operating)")
    if t_des or d.get("t_op") is not None:
        design.append(f"{t_des or '-'} {DEG} (design) / {d.get('t_op', '-')} {DEG} (operating)")
    if d.get("duty_mmbtu_hr"):
        design.append(f"duty {d['duty_mmbtu_hr']} MMBtu/hr")
    if d.get("power_kw"):
        design.append(f"power {d['power_kw']} kW")
    if spec:
        design.append(f"Piping spec {spec['spec']}: {spec['rating']}, {spec['material']}, {spec['rating_psig']} psig @ 100 {DEG}, "
                      f"{spec['min_temp_f']} to {spec['max_temp_f']} {DEG}")

    rating = [f"{d['power_kw']} kW electric" if d.get("power_kw") else "",
              f"duty {d['duty_mmbtu_hr']} MMBtu/hr" if d.get("duty_mmbtu_hr") else ""]
    rating = ", ".join(x for x in rating if x)
    intent = {
        "heater": f"Heat {ctx.fluid} in {tag}" + (f" ({rating})" if rating else "")
                  + (f" at {d['p_op']} psig / {d.get('t_op', '-')} {DEG} operating" if d.get("p_op") else "")
                  + (f" so that the gas stays above its control temperature after letdown at {cv}." if cv else "."),
        "vessel": f"Separate liquids from {ctx.fluid} in {tag} and route gas and liquid to downstream systems under level and pressure control.",
        "pump": f"Transfer {ctx.fluid} using {tag} at design rate and discharge pressure.",
        "compressor": f"Compress {ctx.fluid} in {tag} to the required discharge pressure.",
        "exchanger": f"Exchange heat in {tag} to achieve the required outlet temperature.",
        "tank": f"Store {ctx.fluid} in {tag} within level and pressure limits.",
    }.get(kind, f"Transfer {ctx.fluid} through {tag}.")

    return {
        "id": str(nid),
        "title": f"{tag} {desc}".strip(),
        "boundary": _node_description(ctx),
        "design_intent": intent,
        "design_conditions": "; ".join(design) or "Not shown on the P&ID.",
        "deviations": [x for x in devs if x],
    }


# ---------------------------------------------------------- control valve node

def control_valve_node(ctx, cvs, nid, heater):
    cv = cvs[0]
    tag = cv["tag"]
    var = ctx_var(cv)
    fail = cv.get("fail_action", "")
    fail_txt = {"FC": "fails closed", "FO": "fails open", "FL": "fails last"}.get(fail, "fails")
    dest = ctx.dest_text()
    dest_eq = ctx.dest_equipment()
    spec = ctx.proc_spec
    up_p = (heater["design"].get("p_op") if heater else None)
    up_pmax = (heater["design"].get("p_des") if heater else None)
    bypass = ctx.valves_of("globe")
    up_name = _equip_name(_nearest_large(ctx, cv.get("box"), -1), ctx.src_text())
    down_name = _equip_name(_nearest_large(ctx, cv.get("box"), 1), dest_eq)
    down_des = (_nearest_large(ctx, cv.get("box"), 1) or {}).get("design") or {}
    devs = []

    var0 = (var or "P").upper()[:1]
    drum = _downstream_drum(ctx, cv.get("box"))
    vessel = _nearest_large(ctx, cv.get("box"), -1)
    if not vessel or vessel.get("kind") not in ("vessel", "tank"):
        vessel = drum if drum and drum.get("kind") in ("vessel", "tank") else vessel
    if var0 == "L":
        loss_sg = trip_safeguards(ctx, "L", "H", vessel)
        open_sg = trip_safeguards(ctx, "L", "L", vessel)
        devs.append(dev("High Level", [
            row(_cause_ltr(ctx, cv.get("box"), tag, f"{tag} fails closed."),
                [_cons_related(ctx, cv.get("box"), up_name, f"The liquid outlet from {up_name} is blocked and liquid carries into the vapour outlet")],
                "S", loss_sg, 4, 3),
            row(_cause_ltr(ctx, cv.get("box"), tag, _isolation_cause(ctx, cv.get("box"), tag)),
                [_cons_related(ctx, cv.get("box"), up_name, f"The liquid outlet from {up_name} is blocked and liquid carries into the vapour outlet")],
                "S", loss_sg, 4, 2),
        ]))
        devs.append(dev("Low Level", [
            row(_cause_ltr(ctx, cv.get("box"), tag, f"{tag} fails open."),
                [_cons_related(ctx, cv.get("box"), up_name, f"Liquid leaves {up_name} and gas blows through the liquid outlet")],
                "S", open_sg, 5, 3),
        ]))
    else:
        loss_sg = trip_safeguards(ctx, "P", "L", drum)
        open_sg = relief_safeguards(ctx, drum) + trip_safeguards(ctx, "P", "H", drum)
        devs.append(dev("No / Less Flow", [
            row(_cause_ltr(ctx, cv.get("box"), tag, f"{tag} {fail_txt if fail == 'FC' else 'fails closed'}."),
                [_cons_related(ctx, cv.get("box"), tag, f"Flow of {ctx.fluid} from {up_name} to {down_name} stops")],
                "A", loss_sg + (trip_safeguards(ctx, "T", "H", heater) if heater else []), 3, 3),
            row(_cause_ltr(ctx, cv.get("box"), tag, _isolation_cause(ctx, cv.get("box"), tag)),
                [_cons_related(ctx, cv.get("box"), tag, f"Flow of {ctx.fluid} from {up_name} to {down_name} stops")], "A",
                loss_sg, 3, 2),
        ]))

        limit = f" above its design pressure of {down_des['p_des']} psig" if down_des.get("p_des") else " above its design pressure"
        hp_cons = [f"Letdown between {up_name} and {down_name} is lost. "
                   f"Pressure at {down_name} rises toward the upstream pressure"
                   + (f" ({up_p} psig operating, {up_pmax} psig design)" if up_p else "")
                   + f" and can take {down_name}{limit}. Release of {ctx.release} can follow."]
        down = [l for l in ctx.process_lines if any(l["tag"] == c["line"] for c in ctx.dests)]
        if down and up_pmax and down[0].get("rating_psig"):
            if down[0]["rating_psig"] >= up_pmax:
                hp_cons.append(f"Outlet piping {down[0]['tag']} ({down[0]['rating']}) is rated above the upstream design pressure.")
            else:
                hp_cons.append(f"Outlet piping {down[0]['tag']} ({down[0]['rating']}, {down[0]['rating_psig']} psig) can be overpressured.")
        if heater:
            hp_cons.append(f"Flow through {heater['tag']} rises above its heating capacity and the outlet gas stays cold.")
        more_rows = [row(_cause_ltr(ctx, cv.get("box"), tag, f"{tag} fails open."),
                         [_cons_related(ctx, cv.get("box"), tag, hp_cons[0].rstrip("."))], "S",
                         open_sg, 5, 3)]
        if bypass:
            more_rows.append(row(f"{tag} bypass globe valve {ctx.names(bypass[:1])} opened in error or left open after maintenance.",
                                 [f"Flow bypasses {tag}. Pressure at {down_name} rises toward the upstream pressure, at a lower rate than a fully open control valve."], "S",
                                 open_sg, 4, 2,
                                 [ctx.recs.add(f"Lock closed the {tag} bypass valve {ctx.names(bypass[:1])} and include it in the lock register.")]))
        devs.append(dev("More Flow / High Pressure", more_rows))

    devs.append(dev("Reverse Flow", [row(
        _cause_ltr(ctx, cv.get("box"), tag, "Loss of upstream pressure while downstream stays pressurized."),
        [_cons_related(ctx, cv.get("box"), tag, f"Backflow through {tag} toward the upstream side")], "A",
        check_safeguards(ctx, drum), 3, 2,
        [] if check_safeguards(ctx, drum) else [ctx.recs.add(f"Provide a check valve so {tag} cannot pass reverse flow.")])]))
    devs.append(dev("Low Pressure", [row(
        _cause_ltr(ctx, cv.get("box"), tag, f"{tag} closes or upstream supply is lost."),
        [_cons_related(ctx, cv.get("box"), tag, f"Pressure falls at {down_name}")], "A",
        trip_safeguards(ctx, "P", "L", drum), 2, 3)]))

    if ctx.gas:
        tsl = trip_safeguards(ctx, "T", "L")
        tic = controller_safeguard(ctx, "T", "L")
        min_t = spec["min_temp_f"] if spec and spec.get("min_temp_f") is not None else None
        cons = [f"Joule-Thomson cooling across {tag} drops the gas temperature well below the control set point.",
                "Hydrate formation, plugging of the control valve and outlet piping, loss of supply."]
        if min_t is not None:
            cons.append(f"Metal temperature potentially below {spec['spec']} minimum design temperature ({min_t} {DEG}) - brittle fracture, "
                        f"loss of containment of {ctx.release}.")
        sdv = ctx.find(letters=("SDV", "XV", "BDV", "USV", "SSV"))
        recs_ = []
        if tsl and not sdv:
            recs_.append(ctx.recs.add(
                f"The final element of the low-low temperature trip {ctx.tags(ctx.find(var='T', cats=('trip',), has=('LL',)))} is not shown "
                f"on this P&ID (no SDV). Define the trip action (e.g. close {tag} and / or an inlet SDV) and verify it meets the required SIL."))
        if min_t is not None:
            recs_.append(ctx.recs.add(
                f"Calculate the minimum downstream temperature for JT letdown across {tag} at maximum pressure drop with heating unavailable; "
                f"confirm {spec['spec']} (minimum {min_t} {DEG}) is suitable or upgrade to low-temperature material."))
        lt_rows = []
        if heater:
            lt_rows.append(row(f"{heater['tag']} trip, power failure or switched off while flow continues.", cons, "S",
                               tic + tsl + shutdown_alarms(ctx), 5, 3, recs_))
        lt_rows.append(row("Temperature controller failure or transmitter reads high, reducing heating.",
                           cons, "S", tsl, 5, 3, recs_ if not heater else recs_[:1]))
        lt_rows.append(row(f"{tag} fails open or its bypass is left open, so flow is above the heating capacity.",
                           [f"The heater cannot hold the outlet temperature. Gas downstream of {tag} stays cold, and hydrate or ice can plug the valve and the outlet piping."],
                           "S", tsl, 5, 2, recs_[:1]))
        devs.append(dev("Low Temperature", lt_rows))

    if heater:
        devs.append(dev("High Temperature", [row(f"Temperature control failure driving {heater['tag']} to maximum output.",
                                                 [f"Hot gas to {dest}; downstream piping above its maximum design temperature."], "A",
                                                 trip_safeguards(ctx, "T", "H", heater) + skin_safeguards(ctx), 4, 3)]))

    devs.append(dev("Utility Failure (Instrument Air / Power)", [row(
        f"Loss of instrument air or power to {tag} positioner.",
        [f"{tag} {fail_txt}. "
         + (f"Flow of {ctx.fluid} to {dest} stops." if fail == "FC"
            else f"Pressure letdown through {tag} is lost and downstream pressure rises." if fail == "FO"
            else f"The valve stays in its last position.")],
        "A", [sg(f"Fail-{'closed' if fail == 'FC' else 'open' if fail == 'FO' else 'safe'} action of {tag}", f"{tag} ({fail})" if fail else tag)]
        if fail else [], 3, 2,
        [] if fail else [ctx.recs.add(f"Confirm the fail-safe action of {tag} on loss of air / signal.")])]))

    pic = ctx.find(var=var.upper()[0], cats=("controller",))
    return {
        "id": str(nid),
        "title": f"{var.capitalize()} control valve {tag} and outlet to {ctx.dest_text()}",
        "boundary": _node_description(ctx),
        "design_intent": f"Control {var} using {tag}" + (f" ({ctx.tags(pic)})" if pic else "")
                         + (f", fail {'closed' if fail == 'FC' else 'open'}" if fail in ("FC", "FO") else "")
                         + f", and deliver {ctx.fluid} to {dest}.",
        "design_conditions": (f"Piping spec {spec['spec']}: {spec['rating']}, {spec['material']}, minimum design temperature "
                              f"{spec['min_temp_f']} {DEG}, {spec['rating_psig']} psig @ 100 {DEG}.") if spec else "Not shown on the P&ID.",
        "deviations": [x for x in devs if x],
    }


# ----------------------------------------------------------------- relief node

def _near_any(box, boxes, dist):
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    for b in boxes:
        dx = max(b[0] - cx, 0, cx - b[2])
        dy = max(b[1] - cy, 0, cy - b[3])
        if (dx * dx + dy * dy) ** 0.5 <= dist:
            return True
    return False


def relief_node(ctx, nid, protected):
    psvs = ctx.find(cats=("relief",))
    psv_tags = ctx.tags(psvs) or "relief valve"
    fs = ctx.flare_spec
    cso = [v for v in ctx.valves if "CSO" in v["attributes"]]
    vent = ctx.valves_of("globe")
    flare_ti = sorted((i for i in ctx.find(var="T", cats=("indicator", "alarm"))
                       if _near_any(i["box"], [b for l in ctx.flare_lines for b in l.get("boxes", [l["box"]])], 0.07)),
                      key=lambda i: len(i["letters"]))
    header = next((l for l in ctx.flare_lines if l["size"] and int(float(l["size"].strip('"').split("/")[0] or 0)) >= 6), None)
    devs = []
    prot = protected or "the protected equipment"

    cso_sg = [sg("Car-sealed-open (CSO) isolation valves", ctx.names(cso))] if cso else []
    devs.append(dev("No Flow (Relief Path Blocked)", [
        row("Relief valve inlet / outlet isolation valve inadvertently closed.",
            [f"{psv_tags} cannot relieve; {prot} overpressure during fire / blocked-in case - rupture, fire, explosion."], "S",
            cso_sg, 5, 2,
            [ctx.recs.add(f"Include the {psv_tags} inlet / outlet CSO valves in the car-seal register with periodic verification.")]
            if cso else [ctx.recs.add(f"Car-seal open (CSO) the {psv_tags} inlet / outlet isolation valves.")]),
        row(f"{psv_tags} plugged by hydrates, ice or corrosion products" + (" in sour service." if ctx.sour else "."),
            [f"{psv_tags} cannot relieve. {prot} is overpressured in a fire or blocked-outlet case, and loss of containment can follow."], "S",
            [sg("Periodic relief valve inspection and testing", psv_tags)], 5, 1),
    ]))
    devs.append(dev("More Flow (Passing / Open Vent)", [row(
        f"{psv_tags} passing / leaking" + (f", or manual vent {ctx.names(vent[:1])} left open or passing." if vent else "."),
        ["Continuous loss of gas to flare: flaring, environmental impact and gas loss.",
         "Joule-Thomson cooling in the flare tail pipe can take the metal below its minimum design temperature."],
        "E", ([sg("Flare line temperature indication with low alarm", ctx.tags(flare_ti[:1]) + " (L)")] if flare_ti else [])
        + trip_safeguards(ctx, "P", "L"), 3, 3)]))
    if header or ctx.flare_dests:
        hdr = header["tag"] if header else ctx.flare_dests[0]["description"]
        devs.append(dev("High Pressure (Back Pressure)", [row(
            f"High back pressure in flare header {hdr} during simultaneous relief from other sources.",
            [f"Reduced capacity / unstable operation of {psv_tags}; inadequate overpressure protection of {prot}."]
            + ([f"Flare piping {fs['spec']} ({fs['rating_psig']} psig) overpressured if the header is blocked."] if fs else []),
            "S", [sg("Flare system designed for governing relief case", "-")], 4, 2,
            [ctx.recs.add(f"Confirm {psv_tags} type (conventional / balanced bellows) is suitable for built-up and superimposed back pressure "
                          f"of flare header {hdr} (flare hydraulic study).")])]))
    if ctx.gas:
        cons = ["JT cooling at the relief / vent valve outlet"
                + (f" - {fs['spec']} flare piping temperature potentially below its minimum design temperature ({fs['min_temp_f']} {DEG})" if fs else "")
                + "; brittle fracture, gas release, fire."]
        if ctx.proc_spec and fs and ctx.proc_spec["spec"] != fs["spec"]:
            cons.append(f"{ctx.proc_spec['spec']} piping (minimum {ctx.proc_spec['min_temp_f']} {DEG}) between the valve outlet and the "
                        f"{ctx.proc_spec['spec']} / {fs['spec']} spec break may be exposed to low temperature.")
        sgs = ([sg("Flare line temperature indication with low alarm", ctx.tags(flare_ti[:1]) + " (L)")] if flare_ti else []) + \
              ([sg(f"{fs['spec']} {fs['material'].split(' - ')[-1]} ({fs['min_temp_f']} {DEG})", f"{fs['spec']} spec")] if fs else []) + \
              trip_safeguards(ctx, "T", "L")
        devs.append(dev("Low Temperature", [row(
            f"{psv_tags} lifting / passing" + (f", or manual depressuring through {ctx.names(vent[:1])}" if vent else "")
            + " from high pressure to flare pressure.", cons, "S", sgs, 5, 3,
            [ctx.recs.add(f"Perform a minimum design metal temperature (MDMT) / depressuring study for {psv_tags} relief"
                          + (f" and manual depressuring via {ctx.names(vent[:1])}" if vent else "")
                          + (f"; confirm {fs['spec']} ({fs['min_temp_f']} {DEG}) is adequate and the spec break location is correct." if fs else "."))])]))
    if len(psvs) == 1:
        devs.append(dev("Maintenance", [row(
            f"Removal of {psv_tags} for testing (single relief valve, no installed spare).",
            [f"{prot} unprotected against overpressure if kept in service."], "S",
            cso_sg + [sg("Permit-to-work", "-")], 5, 2,
            [ctx.recs.add(f"Provide administrative control to ensure {prot} is shut down and isolated whenever {psv_tags} is removed, "
                          f"or consider installing a spare relief valve.")])]))

    psv_set = ", ".join(f"{p['tag']} set {p['set_psig']} psig" for p in psvs if p.get("set_psig"))
    return {
        "id": str(nid),
        "title": "Relief and depressuring to flare",
        "boundary": _node_description(ctx),
        "design_intent": f"Protect {prot} against overpressure and allow depressuring to the flare header.",
        "design_conditions": "; ".join(x for x in [
            psv_set,
            (f"Flare piping spec {fs['spec']}: {fs['rating']}, {fs['material']}, {fs['rating_psig']} psig, "
             f"{fs['min_temp_f']} to {fs['max_temp_f']} {DEG}") if fs else ""] if x) or "Not shown on the P&ID.",
        "deviations": [x for x in devs if x],
    }


# ------------------------------------------------------------------ node planning

def _main_equipment(ext):
    return [e for e in ext["equipment"] if not e["offpage"] and e["kind"] not in ("panel", "package")]


_NODE_HEADER = re.compile(r"^(?:HAZOP\s+)?NODE(?:\s*(?:NO\.?|NUMBER))?\s*[-:#]?\s*(\d{1,3})\b\s*(.*)$")
_NODE_SKIP = re.compile(r"^(REFER|SEE|FROM|TO|CONT|CONTINUED|NOTE|DWG)\b")
_COLOR_NEAR = 0.035  # a line tag is on the coloured pipe when it sits on the stroke
_EQUIP_NEAR = 0.06  # an equipment tag is drawn beside its vessel, not on the stroke
_DEVICE_NEAR = 0.04  # instruments and valves sit on the coloured pipe
_COLOR_LABEL = 0.15  # a NODE label claims the coloured mark nearest to it
_ISOLATION = ("ball", "gate", "plug", "butterfly")


def _color_name(rgb):
    hue, _, _ = colorsys.rgb_to_hsv(*(rgb or (1, 0, 0)))
    stops = (
        (0.04, "red"), (0.10, "orange"), (0.18, "yellow"), (0.28, "lime"),
        (0.42, "green"), (0.54, "cyan"), (0.70, "blue"), (0.82, "purple"), (0.93, "magenta"),
    )
    for limit, name in stops:
        if hue < limit:
            return name
    return "red"


def _point_seg(px, py, seg):
    x0, y0, x1, y1 = seg
    dx, dy = x1 - x0, y1 - y0
    if dx == 0 and dy == 0:
        return ((px - x0) ** 2 + (py - y0) ** 2) ** 0.5
    t = max(0.0, min(1.0, ((px - x0) * dx + (py - y0) * dy) / (dx * dx + dy * dy)))
    qx, qy = x0 + t * dx, y0 + t * dy
    return ((px - qx) ** 2 + (py - qy) ** 2) ** 0.5


def _nearest_color(point, colors):
    px, py = point
    best, dist = None, 1e9
    for color in colors:
        for seg in color.get("segments") or []:
            d = _point_seg(px, py, seg)
            if d < dist:
                best, dist = color, d
    return best, dist


def _entity_points(ent):
    boxes = list(ent.get("boxes") or [])
    if ent.get("box"):
        boxes.append(ent["box"])
    return [((b[0] + b[2]) / 2, (b[1] + b[3]) / 2) for b in boxes if b and len(b) == 4]


def _color_nodes(ext):
    """One HAZOP node per colour that a NODE label points at.

    The colour is followed from the first stroke to the last. Every line, instrument,
    valve and equipment item sitting on that colour belongs to the node.
    """
    colors = [c for c in (ext.get("node_colors") or []) if c.get("segments")]
    raw = ext.get("tokens") or []
    if not colors or not raw:
        return None
    scale = 10000
    toks = [Tok({"text": t.get("text") or "", "box": [c * scale for c in t["box"]], "score": 1})
            for t in raw if t.get("text") and t.get("box")]
    headers = []
    for ln in _text_lines(toks):
        text = ln["text"].strip()
        if len(text) > 80 or _NODE_SKIP.match(text):
            continue
        m = _NODE_HEADER.match(text)
        if not m:
            continue
        box = ln["box"]
        headers.append({
            "number": int(m.group(1)),
            "rest": m.group(2).strip(" -:."),
            "point": ((box[0] + box[2]) / 2 / scale, (box[1] + box[3]) / 2 / scale),
        })
    if not headers:
        return None

    claimed = {}
    for header in sorted(headers, key=lambda h: h["number"]):
        color, dist = _nearest_color(header["point"], colors)
        if color is None or dist > _COLOR_LABEL:
            continue
        hue = color.get("hue")
        current = claimed.get(hue)
        if current is None or dist < current["dist"]:
            claimed[hue] = {"header": header, "color": color, "dist": dist}
    if not claimed:
        return None

    catalog = []
    for key, tag_key in (("equipment", "tag"), ("instruments", "tag"), ("lines", "tag"), ("valves", "code"),
                         ("connectors", "tag"), ("spec_breaks", "tag")):
        for ent in ext.get(key) or []:
            tag = str(ent.get(tag_key) or "").strip().upper()
            points = _entity_points(ent)
            if tag and points:
                catalog.append((tag, points, key))
    lines_by_tag = {str(ln.get("tag") or "").upper(): ln for ln in ext.get("lines") or []}

    owned = {hue: [] for hue in claimed}
    for tag, points, key in catalog:
        best_hue, best_dist = None, 1e9
        for hue, slot in claimed.items():
            segments = slot["color"].get("segments") or []
            dist = min(_point_seg(px, py, seg) for px, py in points for seg in segments)
            if dist < best_dist:
                best_hue, best_dist = hue, dist
        limit = _EQUIP_NEAR if key == "equipment" else _DEVICE_NEAR if key in ("instruments", "valves") else _COLOR_NEAR
        if best_hue is not None and best_dist <= limit and tag not in owned[best_hue]:
            owned[best_hue].append(tag)

    neighbours = [("equipment", "tag"), ("instruments", "tag"), ("valves", "code")]
    for key, tag_key in neighbours:
        for ent in ext.get(key) or []:
            if key == "equipment" and (ent.get("offpage") or ent.get("kind") in ("panel", "package")):
                continue
            tag = str(ent.get(tag_key) or "").upper()
            points = _entity_points(ent)
            if not tag or not points or any(tag in found for found in owned.values()):
                continue
            best_hue, best_dist = None, 1e9
            for hue, found in owned.items():
                for line_tag in found:
                    line = lines_by_tag.get(line_tag)
                    if not line:
                        continue
                    boxes = line.get("boxes") or ([line["box"]] if line.get("box") else [])
                    for box in boxes:
                        for px, py in points:
                            dist = _point_box(px, py, box)
                            if dist < best_dist:
                                best_hue, best_dist = hue, dist
            if best_hue is not None and best_dist <= _DEVICE_NEAR:
                owned[best_hue].append(tag)

    plan = []
    for hue, slot in sorted(claimed.items(), key=lambda item: item[1]["header"]["number"]):
        tags = owned[hue]
        if not tags:
            continue
        header = slot["header"]
        name = _color_name(slot["color"].get("rgb"))
        title = f"Node {header['number']} - {name}"
        if header["rest"] and not re.fullmatch(r"[\d\s]+", header["rest"]):
            title = f"{title} - {header['rest']}"
        plan.append({
            "title": title,
            "tags": tags,
            "design_intent": "",
            "color": name,
            "number": header["number"],
        })
    claimed_numbers = {slot["header"]["number"] for slot in claimed.values()}
    for header in headers:
        if header["number"] in claimed_numbers:
            continue
        text_tags = _tags_near_header(ext, header["point"])
        text_tags = [tag for tag in text_tags if not any(tag in found for found in owned.values())]
        if not text_tags:
            continue
        title = f"Node {header['number']}"
        if header["rest"] and not re.fullmatch(r"[\d\s]+", header["rest"]):
            title = f"{title} - {header['rest']}"
        plan.append({"title": title, "tags": text_tags, "design_intent": "", "number": header["number"]})
    plan.sort(key=lambda item: item.get("number") or 0)
    return plan or None


def _tags_near_header(ext, point):
    """Tags of the equipment, lines, instruments and valves next to a NODE label that has no colour."""
    px, py = point
    found = []
    for key, tag_key in (("equipment", "tag"), ("lines", "tag"), ("instruments", "tag"), ("valves", "code")):
        for ent in ext.get(key) or []:
            if key == "equipment" and (ent.get("offpage") or ent.get("kind") in ("panel", "package")):
                continue
            tag = str(ent.get(tag_key) or "").strip().upper()
            if not tag or tag in found:
                continue
            limit = 0.12 if key == "equipment" else 0.06
            if any((px - x) ** 2 + (py - y) ** 2 <= limit ** 2 for x, y in _entity_points(ent)):
                found.append(tag)
    return found


def _marked_nodes(ext):
    """Nodes already written on the sheet, e.g. a 'NODE 1' mark and the tags listed with it.

    Returns a plan (title, tags) or None when the drawing has no node marks.
    """
    raw = ext.get("tokens") or []
    if not raw:
        return None
    scale = 10000
    toks = [Tok({"text": t.get("text") or "", "box": [c * scale for c in t["box"]], "score": 1})
            for t in raw if t.get("text") and t.get("box")]
    lines = _text_lines(toks)
    headers = []
    for ln in lines:
        text = ln["text"].strip()
        if len(text) > 80 or _NODE_SKIP.match(text):
            continue
        m = _NODE_HEADER.match(text)
        if m:
            headers.append({"number": int(m.group(1)), "rest": m.group(2).strip(" -:."), "box": ln["box"], "text": text})
    if not headers:
        return None
    headers.sort(key=lambda h: (h["box"][1], h["box"][0]))

    known = []
    for key, tag_key in (("equipment", "tag"), ("instruments", "tag"), ("lines", "tag"), ("valves", "code")):
        for ent in ext.get(key) or []:
            tag = str(ent.get(tag_key) or "").upper()
            box = ent.get("box")
            if tag and box:
                known.append((tag, ((box[0] + box[2]) / 2 * scale, (box[1] + box[3]) / 2 * scale), ent))

    def mentioned(blob):
        found = []
        for tag, _, _ in known:
            if re.search(rf"(?<![A-Z0-9]){re.escape(tag)}(?![A-Z0-9])", blob) and tag not in found:
                found.append(tag)
        return found

    def nearest(box):
        cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
        ranked = []
        for tag, (x, y), ent in known:
            if ent.get("offpage") or ent.get("kind") in ("panel", "package"):
                continue
            if "kind" not in ent:
                continue
            dist = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5
            if dist <= 0.28 * scale:
                ranked.append((dist, tag))
        ranked.sort()
        out = []
        for _, tag in ranked:
            if tag not in out:
                out.append(tag)
        return out

    def expand(tags):
        """Pull in every line, valve, instrument and equipment that sits with the tags already in the node."""
        chosen = list(tags)
        centers = [(x, y) for tag, (x, y), _ in known if tag in chosen]
        for _ in range(2):
            for tag, (x, y), ent in known:
                if tag in chosen or ent.get("offpage"):
                    continue
                if any(((x - cx) ** 2 + (y - cy) ** 2) ** 0.5 <= 0.16 * scale for cx, cy in centers):
                    chosen.append(tag)
                    centers.append((x, y))
        for br in ext.get("spec_breaks") or []:
            tag = str(br.get("tag") or "").upper()
            box = br.get("box")
            if not tag or not box or tag in chosen:
                continue
            cx, cy = _center(box)
            if any(((cx * scale - sx) ** 2 + (cy * scale - sy) ** 2) ** 0.5 <= 0.16 * scale for sx, sy in centers):
                chosen.append(tag)
        return chosen

    by_number = {}
    for i, h in enumerate(headers):
        y0 = h["box"][1]
        below = [o for o in headers[i + 1:] if o["box"][1] > y0 + 10]
        y1 = below[0]["box"][1] if below else y0 + 0.18 * scale
        block = [ln["text"] for ln in lines
                 if y0 - 20 <= ln["box"][1] < y1 and abs(ln["box"][0] - h["box"][0]) < 0.2 * scale]
        tags = expand(mentioned(" ".join(block)) or nearest(h["box"]))
        slot = by_number.setdefault(h["number"], {"rest": h["rest"], "tags": []})
        if h["rest"] and not slot["rest"]:
            slot["rest"] = h["rest"]
        for tag in tags:
            if tag not in slot["tags"]:
                slot["tags"].append(tag)

    plan = []
    for number in sorted(by_number):
        slot = by_number[number]
        if not slot["tags"]:
            continue
        title = f"Node {number}"
        rest = slot["rest"]
        if rest and not re.fullmatch(r"[\d\s]+", rest):
            title = f"{title} - {rest}"
        plan.append({"title": title, "tags": slot["tags"], "design_intent": "", "number": number})
    return plan or None


def _auto_plan(ctx, ext):
    """Default nodes: each major equipment item, the control valve / letdown, and relief to flare."""
    plan = [[e["tag"]] for e in _main_equipment(ext)]
    cvs = ctx.find(cats=("control_valve",))
    if cvs:
        plan.append([cvs[0]["tag"]])
    if ctx.find(cats=("relief",)) or ctx.flare_lines:
        plan.append([p["tag"] for p in ctx.find(cats=("relief",))] + [l["tag"] for l in ctx.flare_lines])
    if not plan and ctx.lines:
        main = ctx.proc_spec or ctx.lines[0]
        plan.append([main["tag"]])
    return [{"title": "", "tags": tags, "design_intent": ""} for tags in plan]


def _merge(parts):
    """Combine the nodes built for each anchor of a user node; same-named deviations share one entry."""
    if len(parts) == 1:
        return parts[0]
    devs = {}
    for p in parts:
        for d in p["deviations"]:
            devs.setdefault(d["deviation"], []).extend(d["rows"])
    join = lambda key, sep: sep.join(dict.fromkeys(p[key] for p in parts if p[key] and p[key] != "Not shown on the P&ID."))
    return {
        "id": parts[0]["id"],
        "title": " / ".join(p["title"] for p in parts),
        "boundary": join("boundary", " "),
        "design_intent": join("design_intent", " "),
        "design_conditions": join("design_conditions", "; ") or "Not shown on the P&ID.",
        "deviations": [{"deviation": name, "rows": rows} for name, rows in devs.items()],
    }


def _build(ctx, ext, entry, nid):
    tags = {t.strip().upper() for t in entry.get("tags") or [] if t and t.strip()}
    main_eq = _main_equipment(ext)
    heater = next((e for e in main_eq if e["kind"] in ("heater", "exchanger")), None)
    eqs = [e for e in ext["equipment"]
           if not e.get("offpage") and e["kind"] not in ("panel", "package")
           and (e["tag"].upper() in tags or entry.get("color"))]
    cvs = [i for i in ctx.find(cats=("control_valve",)) if i["tag"].upper() in tags]
    relief = any(i["tag"].upper() in tags for i in ctx.find(cats=("relief",))) or \
        any(l["tag"].upper() in tags for l in ctx.flare_lines)
    lines = [l for l in ctx.process_lines if l["tag"].upper() in tags] or list(ctx.process_lines)

    parts = [equipment_node(ctx, e, nid) for e in eqs]
    parts += [control_valve_node(ctx, [cv], nid, heater) for cv in cvs]
    if relief:
        protected = eqs[0]["tag"] if eqs else (main_eq[0]["tag"] if main_eq else None)
        parts.append(relief_node(ctx, nid, protected))
    if not parts:
        anchor = lines[0]["tag"] if lines else (entry.get("title") or next(iter(sorted(tags)), f"Node {nid}"))
        fake = {"tag": anchor, "kind": "equipment", "description": "process piping" if lines else "",
                "design": {}, "electric": False}
        node = equipment_node(ctx, fake, nid)
        node["title"] = f"Process line {anchor}" if lines else anchor
        parts.append(node)

    node = _merge(parts)
    if (entry.get("title") or "").strip():
        node["title"] = entry["title"].strip()
    _pinpoint_node(node, ctx, entry.get("color"))
    if (entry.get("design_intent") or "").strip():
        node["design_intent"] = entry["design_intent"].strip()
    return node


def plan_nodes(ext):
    """Proposed nodes for the user to review: title, the tags that anchor each node and its generated intent."""
    ctx = Ctx(ext)
    out = []
    for i, entry in enumerate(_color_nodes(ext) or _marked_nodes(ext) or _auto_plan(ctx, ext), 1):
        node = _build(ctx, ext, entry, i)
        out.append({"title": node["title"], "tags": entry["tags"], "design_intent": "",
                    "auto_intent": node["design_intent"]})
    return out


# ------------------------------------------------------------------------ main

def _center(box):
    return (box[0] + box[2]) / 2, (box[1] + box[3]) / 2


def _gather_along(ext, tags):
    """From the tags already in the node, pull in every instrument, valve, line and equipment along them."""
    chosen = []
    for tag in tags or []:
        text = str(tag).strip().upper()
        if text and text not in chosen:
            chosen.append(text)
    index = []
    for key, tag_key in (("equipment", "tag"), ("instruments", "tag"), ("lines", "tag"), ("valves", "code")):
        for ent in ext.get(key) or []:
            if key == "equipment" and ent.get("offpage"):
                continue
            tag = str(ent.get(tag_key) or "").strip().upper()
            points = _entity_points(ent)
            if tag and points:
                index.append((tag, points))
    for _ in range(3):
        seeds = [point for tag, points in index if tag in chosen for point in points]
        if not seeds:
            break
        for tag, points in index:
            if tag in chosen:
                continue
            near = any((px - sx) ** 2 + (py - sy) ** 2 <= _DEVICE_NEAR ** 2
                       for px, py in points for sx, sy in seeds)
            if near:
                chosen.append(tag)
    return chosen


def _is_safeguard_instrument(inst):
    letters = str(inst.get("letters") or "")
    head = str(inst.get("tag") or "").split("-")[0]
    if inst.get("category") in ("relief", "trip", "alarm", "switch", "safety"):
        return True
    return letters in _RELIEF_LETTERS or letters in _SHUTDOWN_LETTERS or head in _SHUTDOWN_LETTERS or letters.startswith("FSV")


def _is_safeguard_valve(valve):
    kind = str(valve.get("type") or "").lower()
    code = str(valve.get("code") or "")
    return kind.startswith("check") or code.split("-")[0] in _SHUTDOWN_LETTERS


def _keep_safeguards(ext, scoped):
    """A PSV, trip, alarm or shutdown valve protects the node even when it sits off the coloured line."""
    equipment = [e for e in scoped.get("equipment") or [] if e.get("box")]
    loops = {str(i.get("loop") or "") for i in scoped.get("instruments") or [] if i.get("loop")}
    numbers = set()
    for eq in scoped.get("equipment") or []:
        numbers.update(re.findall(r"\d{3,5}", str(eq.get("tag") or "")))
    have_i = {str(i.get("tag") or "").upper() for i in scoped.get("instruments") or []}
    have_v = {str(v.get("code") or "").upper() for v in scoped.get("valves") or []}

    def near(box):
        if not box or not equipment:
            return False
        cx, cy = _center(box)
        return any((cx - sx) ** 2 + (cy - sy) ** 2 <= 0.25 ** 2 for sx, sy in (_center(e["box"]) for e in equipment))

    def same_equipment(tag):
        return bool(numbers & set(re.findall(r"\d{3,5}", str(tag or ""))))

    for inst in ext.get("instruments") or []:
        tag = str(inst.get("tag") or "").upper()
        if not tag or tag in have_i or not _is_safeguard_instrument(inst):
            continue
        if near(inst.get("box")) or str(inst.get("loop") or "") in loops or same_equipment(tag):
            scoped.setdefault("instruments", []).append(inst)
            have_i.add(tag)
    for valve in ext.get("valves") or []:
        code = str(valve.get("code") or "").upper()
        if not code or code in have_v or not _is_safeguard_valve(valve):
            continue
        if near(valve.get("box")):
            scoped.setdefault("valves", []).append(valve)
            have_v.add(code)


def _scope_extraction(ext, tags, strict=False):
    """Keep the tags of one part, plus whatever sits next to them on the drawing.

    A colour node is already the full run of that colour, so nothing outside its tags is added.
    """
    wanted = {str(t).strip().upper() for t in tags if t and str(t).strip()}
    groups = ("equipment", "instruments", "lines", "valves", "connectors")

    def ident(ent):
        return str(ent.get("tag") or ent.get("code") or "").upper()

    seeds = [ent["box"] for key in groups for ent in ext.get(key) or [] if ident(ent) in wanted and ent.get("box")]
    if not seeds:
        return ext

    def close(box):
        if not box:
            return False
        cx, cy = _center(box)
        return any((cx - sx) ** 2 + (cy - sy) ** 2 <= PART_RADIUS ** 2 for sx, sy in (_center(s) for s in seeds))

    scoped = copy.deepcopy({k: ext.get(k) for k in ("flags", "token_count")})
    for key in groups:
        scoped[key] = [
            ent for ent in ext.get(key) or []
            if ident(ent) in wanted or (not strict and close(ent.get("box")))
        ]
    kept_lines = {str(ln.get("tag") or "").upper() for ln in scoped["lines"]}
    node_specs = {str(ln.get("spec") or "").upper() for ln in scoped["lines"]}

    def keep_break(br):
        linked = {str(x).upper() for x in br.get("lines") or []}
        tag = str(br.get("tag") or "").upper()
        specs = {str(s).upper() for s in br.get("specs") or []}
        if tag and tag in wanted:
            return True
        if linked & kept_lines:
            return True
        if specs and specs <= node_specs and (not strict or close(br.get("box"))):
            return True
        return not strict and close(br.get("box"))

    scoped["spec_breaks"] = [br for br in ext.get("spec_breaks") or [] if keep_break(br)]
    scoped["connectors"] = [
        c for c in ext.get("connectors") or []
        if ident(c) in wanted or close(c.get("box")) or str(c.get("line") or "").upper() in kept_lines
    ]
    scoped["tokens"] = [t for t in ext.get("tokens") or [] if close(t.get("box"))]
    scoped["token_count"] = len(scoped["tokens"])
    scoped["flags"] = {
        "sour_service": any(ln.get("sour") for ln in scoped["lines"]),
        "car_sealed": any("CSO" in (v.get("attributes") or []) for v in scoped["valves"]),
        "interlocks": sum(1 for t in scoped["tokens"] if str(t.get("text") or "").strip() == "I"),
    }
    _keep_safeguards(ext, scoped)
    return scoped


def _compile_parts(pieces, source):
    """Renumber the worksheet of each part into one worksheet."""
    nodes, recs = [], {}
    next_r = 1
    assumptions = []
    for result in pieces:
        mapping = {}
        for old, text in (result.get("recommendations") or {}).items():
            new = f"R-{next_r:02d}"
            next_r += 1
            mapping[old] = new
            recs[new] = text
        for node in result.get("nodes") or []:
            node = copy.deepcopy(node)
            nid = len(nodes) + 1
            node["id"] = nid
            for i, dev in enumerate(node.get("deviations") or [], 1):
                name = re.sub(r"^\s*\d+(?:\.\d+)*\s*", "", str(dev.get("deviation") or "Deviation"))
                dev["deviation"] = f"{nid}.{i} {name}"
                for row in dev.get("rows") or []:
                    row["recommendations"] = [mapping[x] for x in row.get("recommendations") or [] if x in mapping]
            nodes.append(node)
        for note in result.get("assumptions") or []:
            if note not in assumptions:
                assumptions.append(note)
    study = dict((pieces[0].get("study") or {}) if pieces else {})
    if source == "color":
        note = (f"The drawing was studied one node at a time ({len(pieces)} colour-marked nodes). "
                "Each colour was followed from its start to its end, including the piping, instruments and valves on it.")
    else:
        note = (f"The drawing was split into {len(pieces)} parts. Each part was studied on its own, "
                "then the parts were compiled into this worksheet.")
    return {"study": study, "nodes": nodes, "recommendations": recs, "assumptions": [note, *assumptions],
            "node_source": source}


def _worksheet(ext, study, plan, source):
    ctx = Ctx(ext)
    ctx.line_relation = list((study or {}).get("line_relation") or ext.get("line_relation") or [])
    main_eq = _main_equipment(ext)
    nodes = [_build(ctx, ext, entry, i) for i, entry in enumerate(plan, 1)]

    for n in nodes:
        for i, d in enumerate(n["deviations"], 1):
            d["deviation"] = f"{n['id']}.{i} {d['deviation']}"

    package = next((e for e in ext["equipment"] if e["kind"] == "package"), None)
    facility = " - ".join(x for x in [
        f"{package['tag']} {package['description']}".strip() if package else "",
        f"{main_eq[0]['tag']} {main_eq[0]['description']}".strip() if main_eq else ""] if x)

    matrix = risk.project_matrix()
    nc, nl = risk.size(matrix)
    ranking = (
        f"C and L are the levels in the uploaded risk matrix '{matrix['source']}' ({nc} x {nl}). "
        "The risk ranking of each cause is the cell of that file, with existing safeguards in place."
    )
    assumptions = [
        "Worksheet generated automatically by the rule-based engine from text recognised on the P&ID; review by a HAZOP team is required.",
        ranking,
        "CC (Consequence Category): S = Safety / People, E = Environment, A = Asset / Production.",
        "Drain lines, vent lines and lines to safety valves are left out of the node description. They are not part of steady-state continuous operation.",
        "The node description is a summary of the process route. Design intent is the overall purpose of the node. "
        "Design conditions are the design and operating pressure and temperature of the main equipment, read from the P&ID. "
        "Each cause names the instrument that fails, the consequence names the equipment that sees it, and the safeguard names the device that stops it.",
    ]
    classes = list(kb.specs())
    if classes:
        shown = ", ".join(classes[:12])
        more = "…" if len(classes) > 12 else ""
        origin = "uploaded piping specification" if kb.has_project_specs() else "piping specification"
        purposes = " ".join(item["purpose"] for item in kb.learn_piping()[:4])
        assumptions.append(
            f"The {origin} was read and learned first, before the PFD and before any P&ID page was opened "
            f"({len(classes)} classes: {shown}{more}). {purposes}"
        )
    if source == "user":
        assumptions.append("HAZOP nodes were defined by the user before the worksheet was generated. Each node was then studied from its start to its end.")
    elif source == "color":
        assumptions.append(
            "Each node is one colour marked against a node number on the P&ID. "
            "That colour was followed from its start to its end, and the piping, instruments and valves on it were studied together."
        )
    elif source == "drawing":
        assumptions.append("HAZOP nodes were taken from the node numbers already marked on this sheet.")
    offpage = [e["tag"] for e in ext["equipment"] if e["offpage"]]
    if offpage:
        assumptions.append(f"Design data for off-page equipment ({', '.join(offpage)}) is not shown on this drawing.")
    if any("NOTE" in t["text"].upper() for t in ext.get("tokens", [])):
        assumptions.append("P&ID notes are referenced on the drawing but their text is not part of the uploaded sheet.")

    return {
        "study": {
            "title": "HAZOP Worksheets",
            "facility": facility or "P&ID study",
            "drawing": (study or {}).get("drawing", ""),
            "reference_documents": "ISA 5.1 instrument legend, API RP 14C component identification, line designation, "
                                   "piping component legend, piping specifications",
        },
        "nodes": nodes,
        "recommendations": ctx.recs.items,
        "assumptions": assumptions,
        "node_source": source,
    }


def _plan_key(entry, index):
    """Node 1, then node 2, then node 3. Entries without a number keep their reading order after those."""
    number = entry.get("number")
    try:
        return (0, int(number), index)
    except (TypeError, ValueError):
        match = re.search(r"\bNode\s+(\d+)\b", str(entry.get("title") or ""), re.I)
        if match:
            return (0, int(match.group(1)), index)
        return (1, index, 0)


def study_plan(ext, user_nodes=None):
    """Read every node on the drawing, then return them in node-number order."""
    colored = None if user_nodes else _color_nodes(ext)
    marked = None if user_nodes or colored else _marked_nodes(ext)
    plan = user_nodes if user_nodes else (colored or marked or _auto_plan(Ctx(ext), ext))
    source = "user" if user_nodes else ("color" if colored else "drawing" if marked else "auto")

    def one(entry):
        entry = dict(entry)
        # A colour node is already the run of that colour. Gathering by distance pulls in the rest of the sheet.
        if not entry.get("color"):
            entry["tags"] = _gather_along(ext, entry.get("tags") or [])
        return entry

    plan = [one(entry) for entry in plan]
    if not user_nodes:
        plan = [entry for _, entry in sorted(enumerate(plan), key=lambda pair: _plan_key(pair[1], pair[0]))]
    return plan, source


def generate(ext, study=None, user_nodes=None, on_part=None, on_plan=None, prepared=None):
    """Read the nodes, then write the worksheet for one node at a time in node-number order.

    on_plan(plan) runs once the nodes have been read and ordered, before the first node is written.
    on_part(index, count, entry) runs before each node when there is more than one.
    prepared is (plan, source) when the caller already read and ordered the nodes.
    """
    if prepared:
        plan, source = prepared
    else:
        plan, source = study_plan(ext, user_nodes)
        if on_plan:
            on_plan(plan)
    if len(plan) <= 1:
        scoped = ext
        if plan and plan[0].get("color"):
            scoped = _scope_extraction(ext, plan[0].get("tags") or [], strict=True)
        return _worksheet(scoped, study, plan, source)
    pieces = []
    for i, entry in enumerate(plan, 1):
        if on_part:
            on_part(i, len(plan), entry)
        pieces.append(_worksheet(
            _scope_extraction(ext, entry.get("tags") or [], strict=bool(entry.get("color"))),
            study, [entry], source,
        ))
    return _compile_parts(pieces, source)
