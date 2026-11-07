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
OFF_PROCESS_WORDS = (
    "drain", "vent", "flare", "blowdown", "blow down", "bypass", "by-pass", "by pass",
    "safety valve", "relief", "psv", "pzv", "prv", "pse", "to flare", "to vent",
    "closed drain", "open drain",
)


def _off_process_line(line):
    """True for flare, vent, drain and PSV/relief branches — not live in steady-state flow."""
    service = str(line.get("service") or "").upper()
    name = str(line.get("service_name") or "").lower()
    tag = str(line.get("tag") or "").lower()
    if service in OFF_PROCESS_SERVICES:
        return True
    blob = f"{name} {tag}"
    return any(word in blob for word in OFF_PROCESS_WORDS)


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
        self.pfd_conditions = {}
        # Step 1 — system and equipment purpose learned from the PFD before the P&ID worksheet.
        self.pfd_system_purpose = ""
        self.pfd_equipment_purposes = []
        self.stream_line_map = []
        self.line_operating = {}
        self.equipment_operating = {}
        self.line_design = {}
        self.non_steady_segments = []
        self.non_steady_by_role = {}
        self.nc_isolation_valves = []
        # Line tags indicated for the current node (set in _build). Empty = use main process piping.
        self.node_line_tags = set()
        # Upstream is against the pipe arrows. Default is left (drawing reads left to right).
        self.upstream_side = _upstream_side(self)

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
        """Valve std codes with the line number each valve sits on."""
        return _valve_labels(self, items)

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


def _valve_line(ctx, valve):
    """The drawn line this piping valve sits on — required for location with the valve std."""
    box = valve.get("box") if isinstance(valve, dict) else None
    if not box:
        return None
    return (
        _nearest_line(ctx.process_lines, box, limit=0.14)
        or _nearest_line(ctx.lines, box, limit=0.16)
        or _line_toward(ctx, box, 1)
        or _line_toward(ctx, box, -1)
    )


def _valve_label(ctx, valve):
    """Valve std / tag always with its line number so the location is known."""
    if not isinstance(valve, dict):
        text = str(valve or "").strip()
        return text or "valve"
    code = str(valve.get("code") or valve.get("tag") or "").strip() or "valve"
    line = _valve_line(ctx, valve)
    if line and line.get("tag"):
        return f"{code} on {line['tag']}"
    # Control valves / instruments: still try the nearest process line by box.
    if valve.get("box"):
        near = _nearest_line(ctx.process_lines, valve["box"], limit=0.16) or _nearest_line(ctx.lines, valve["box"], limit=0.18)
        if near and near.get("tag"):
            return f"{code} on {near['tag']}"
    return f"{code} (line not read)"


def _valve_labels(ctx, valves):
    """Comma-separated valve stds, each with its line number."""
    labels, seen = [], set()
    for valve in valves or []:
        if isinstance(valve, str):
            label = valve
        else:
            label = _valve_label(ctx, valve)
        key = label.upper()
        if not label or key in seen:
            continue
        seen.add(key)
        labels.append(label)
    if not labels:
        return "valve"
    if len(labels) == 1:
        return labels[0]
    if len(labels) == 2:
        return f"{labels[0]} or {labels[1]}"
    return f"{', '.join(labels[:-1])} or {labels[-1]}"


def _is_check_device(item):
    """FSV / safety category or a piping check valve — objective is reverse-flow prevention."""
    if not item:
        return False
    letters = str(item.get("letters") or "")
    if letters.startswith("FSV") or item.get("category") == "safety":
        return True
    return str(item.get("type") or "").lower().startswith("check")


_NORMALLY_OPEN_ATTRS = {"NO", "LO", "CSO"}


def _is_normally_open(item):
    """True for valves marked normally open / locked open / car-sealed open on the P&ID."""
    if not item:
        return False
    attrs = {str(a).upper() for a in (item.get("attributes") or [])}
    if attrs & _NORMALLY_OPEN_ATTRS:
        return True
    # Fail-open is a control-valve air-failure action, not a reverse-flow initiating cause either.
    if str(item.get("fail_action") or "").upper() == "FO" and item.get("category") == "control_valve":
        return True
    blob = f"{item.get('code') or ''} {item.get('tag') or ''}".upper()
    return bool(re.search(r"(?:^|[\s(])(?:NO|LO|CSO)(?:$|[\s)])", blob))


def _reverse_flow_cause_ok(ctx, cause):
    """Reverse Flow must not blame a normally open valve for cross-pressure backflow."""
    text = str(cause or "")
    low = text.lower()
    # Check / FSV stuck open is the intended reverse-flow device failure.
    if re.search(
        r"\bFSV-\d|\bVC-\d|\bsticks open\b|\bfails to seat\b|"
        r"\binlet check valve\b|\bcheck valve\b.*\bfails open\b",
        text, re.I,
    ):
        return True
    # Pressure reversal without naming a normally open valve.
    if "loss of upstream pressure" in low or "pressure imbalance" in low:
        return True
    if "different pressure" in low and "source" in low:
        return True
    for valve in list(ctx.valves or []) + list(ctx.instruments or []):
        code = str(valve.get("code") or valve.get("tag") or "").strip()
        if not code or code.upper() not in text.upper():
            continue
        if _is_check_device(valve):
            continue
        if _is_normally_open(valve):
            return False
        kind = str(valve.get("type") or "").lower()
        if kind.startswith(("ball", "gate", "globe", "plug", "butterfly", "needle")):
            if re.search(r"\b(open|opened|left open|fails open|fail open)\b", low):
                return False
        if valve.get("category") == "control_valve" and re.search(r"\bfails open\b|\bfail open\b", low):
            return False
    return True


def _scrub_reverse_flow(nodes, ctx=None):
    """Drop Reverse Flow rows that use a normally open valve as the cause."""
    for node in nodes or []:
        for group in node.get("deviations") or []:
            if "reverse flow" not in str(group.get("deviation") or "").lower():
                continue
            kept = []
            for item in group.get("rows") or []:
                cause = item.get("cause")
                text = str(cause or "")
                low = text.lower()
                if ctx is not None and not _reverse_flow_cause_ok(ctx, cause):
                    continue
                # Heuristic scrub (also covers AI-added rows): NO/LO/CSO or isolation "open" + pressure note.
                if re.search(r"\b(NO|LO|CSO)\b", text) and re.search(r"\bopen\b", low):
                    if not re.search(r"\bFSV-\d|\bsticks open\b|\bfails to seat\b", text, re.I):
                        continue
                if re.search(r"\b(VB|VG|VGL|VN|VBF|VP)-\d", text, re.I) and (
                        "different pressure" in low or "backflow" in low or "reverse" in low):
                    if not re.search(r"\bFSV-\d|\bVC-\d|\bcheck valve\b|\bsticks open\b", text, re.I):
                        continue
                if re.search(r"\bfails open\b|\bfail open\b", low) and not re.search(
                        r"\bFSV-\d|\bVC-\d|\bcheck valve\b|\bsticks open\b", text, re.I):
                    continue
                kept.append(item)
            group["rows"] = kept


def _check_tag(item):
    return item.get("tag") or item.get("code") or "the check valve"


def _check_line(ctx, item):
    """The process line this FSV / check valve sits on."""
    box = item.get("box") if isinstance(item, dict) else None
    if not box:
        return None
    return (
        _nearest_line(ctx.process_lines, box, limit=0.14)
        or _line_toward(ctx, box, 1)
        or _line_toward(ctx, box, -1)
        or _nearest_line(ctx.lines, box, limit=0.14)
    )


def _check_phase(ctx, item):
    """liquid / gas / mixed for the line this check valve protects — not the whole-node majority fluid."""
    line = _check_line(ctx, item)
    if line:
        info = (kb.services().get("codes") or {}).get(str(line.get("service") or "").upper()) or {}
        phase = str(info.get("phase") or "").lower()
        name = str(line.get("service_name") or info.get("name") or "").lower()
        tag = str(line.get("tag") or "").lower()
        blob = f"{name} {tag} {line.get('service') or ''}".lower()
        if phase == "liquid" or any(
            word in blob for word in (
                "liquid", "oil", "condensate", "water", "glycol", "diesel", "produced water",
            )
        ):
            return "liquid"
        if phase == "gas" or any(word in blob for word in ("gas", "vapour", "vapor", "fuel gas", "flare")):
            return "gas"
        if phase == "mixed":
            return "mixed"
    # Geometry: under a vessel / tank = liquid outlet; beside a pump = liquid service.
    up = _nearest_large(ctx, item.get("box"), -1)
    down = _nearest_large(ctx, item.get("box"), 1)
    for eq in (up, down):
        if not eq:
            continue
        if eq.get("kind") == "pump":
            return "liquid"
        if eq.get("kind") in ("vessel", "tank") and item.get("box") and eq.get("box"):
            if _cy(item) >= _cy(eq) - 0.02:
                return "liquid"
    for conn in list(ctx.dests) + list(ctx.sources):
        text = str(conn.get("description") or "").lower()
        if any(word in text for word in ("liquid", "oil", "condensate", "water", "separat")):
            if conn.get("box") and item.get("box") and _box_gap(item["box"], conn["box"]) <= 0.2:
                return "liquid"
    return "gas" if ctx.gas else "liquid"


def _check_fluid(ctx, item):
    """Name the fluid on this check valve's own line."""
    phase = _check_phase(ctx, item)
    line = _check_line(ctx, item)
    if line:
        name = line.get("service_name") or kb.service_name(line.get("service") or "")
        if name:
            return str(name).lower()
    if phase == "liquid":
        return "liquid"
    if phase == "gas":
        return "gas" if "gas" in ctx.fluid else ctx.fluid
    return ctx.fluid


def _check_neighbors(ctx, item):
    up = _nearest_large(ctx, item.get("box"), -1)
    down = _nearest_large(ctx, item.get("box"), 1)
    up_name = _equip_name(up, _soft(ctx.src_text()))
    down_name = _equip_name(down, _soft(ctx.dest_text()))
    return up, down, up_name, down_name


def _check_purpose(ctx, item):
    """Objective of a check valve / FSV before any stuck-open or stuck-closed consequence."""
    _, _, up, down = _check_neighbors(ctx, item)
    fluid = _check_fluid(ctx, item)
    phase = _check_phase(ctx, item)
    if phase == "liquid":
        return (
            f"pass forward liquid ({fluid}) from {up} toward {down} "
            f"and stop reverse liquid flow back toward {up}"
        )
    return (
        f"pass forward flow of {fluid} from {up} toward {down} "
        f"and stop reverse flow back toward {up}"
    )


def _check_stuck_open_consequence(ctx, item):
    """Stuck open = latent loss of reverse-flow protection — not 'more forward flow'."""
    tag = _check_tag(item)
    up_eq, down_eq, up, down = _check_neighbors(ctx, item)
    fluid = _check_fluid(ctx, item)
    phase = _check_phase(ctx, item)
    line = _check_line(ctx, item)
    on_line = f" on {line['tag']}" if line and line.get("tag") else ""
    purpose = _check_purpose(ctx, item)
    if phase == "liquid":
        bits = [
            f"{tag} is a check valve (flow safety valve){on_line} in liquid service; its purpose is to {purpose}.",
            f"When {tag} sticks open, it no longer seats against reverse liquid flow.",
        ]
        if (up_eq and up_eq.get("kind") == "pump") or (down_eq and down_eq.get("kind") == "pump"):
            pump = _equip_name(up_eq if up_eq and up_eq.get("kind") == "pump" else down_eq, "the pump")
            bits.append(
                f"If {pump} stops or a higher-pressure liquid source remains at {down}, "
                f"liquid flows backwards through {pump} toward {up}, with reverse rotation, "
                f"seal damage and possible loss of containment of {fluid}."
            )
        elif up_eq and up_eq.get("kind") in ("vessel", "tank"):
            bits.append(
                f"If pressure at {down} exceeds the liquid head at {up}, liquid flows back into {up}, "
                f"raising level / contaminating the inventory, and can drive liquid toward vapour outlets "
                f"or other upstream equipment."
            )
        else:
            bits.append(
                f"If pressure at {down} exceeds pressure at {up}, liquid ({fluid}) flows backwards toward {up}, "
                f"with possible overfill, contamination or overpressure of upstream liquid equipment."
            )
        return " ".join(bits)
    return (
        f"{tag} is a check valve (flow safety valve){on_line}; its purpose is to {purpose}. "
        f"When {tag} sticks open, it no longer seats against reverse flow. "
        f"If pressure at {down} exceeds pressure at {up}, {fluid} flows backwards toward {up}, "
        f"with possible overpressure or contamination of upstream equipment."
    )


def _check_stuck_closed_consequence(ctx, item):
    tag = _check_tag(item)
    up_eq, down_eq, up, down = _check_neighbors(ctx, item)
    fluid = _check_fluid(ctx, item)
    phase = _check_phase(ctx, item)
    line = _check_line(ctx, item)
    on_line = f" on {line['tag']}" if line and line.get("tag") else ""
    purpose = _check_purpose(ctx, item)
    if phase == "liquid":
        bits = [
            f"{tag} is a check valve (flow safety valve){on_line} in liquid service; its purpose is to {purpose}.",
            f"When {tag} sticks closed, forward liquid flow from {up} to {down} is blocked.",
        ]
        if up_eq and up_eq.get("kind") in ("vessel", "tank"):
            bits.append(
                f"Liquid cannot leave {up}, the level rises, and liquid can carry over into the vapour outlet. "
                f"Downstream liquid users at {down} lose supply."
            )
        elif up_eq and up_eq.get("kind") == "pump":
            bits.append(
                f"{up} can dead-head against {tag}, with seal damage and loss of liquid supply to {down}."
            )
        else:
            bits.append(
                f"Liquid inventory backs up toward {up} and {down} loses liquid supply."
            )
        return " ".join(bits)
    return (
        f"{tag} is a check valve (flow safety valve){on_line}; its purpose is to {purpose}. "
        f"When {tag} sticks closed, forward flow of {fluid} from {up} to {down} is blocked."
    )


def _cv_purpose(ctx, cv, eq=None):
    """Objective of this control valve from its ISA letter and where it sits."""
    letters = str(cv.get("letters") or "")[:1]
    if letters == "L":
        return _lv_purpose(_level_vessel_for(ctx, cv, eq))
    if letters == "P":
        drum = _downstream_drum(ctx, cv.get("box")) or eq
        where = _equip_name(drum or eq, "the downstream equipment")
        return f"let down / control the pressure of {ctx.fluid} toward {where}"
    if letters == "F":
        return f"control the flow rate of {ctx.fluid}"
    if letters == "T":
        return f"control temperature by regulating the flow of {ctx.fluid}"
    if letters == "H":
        return f"hand-regulate the path of {ctx.fluid}"
    return _instrument_duty(cv, ctx)


def _with_valve_purpose(ctx, item, effect, purpose=None):
    """State the component objective before the failure effect."""
    tag = item.get("tag") or item.get("code") or "the valve"
    letters = str(item.get("letters") or "")
    head = letters[:1]
    if _is_check_device(item):
        kind = "check valve (flow safety valve)"
        purpose = purpose or _check_purpose(ctx, item)
    elif item.get("category") == "control_valve" or (len(letters) >= 2 and head in "LPFTH"):
        kind = {
            "L": "level control valve", "P": "pressure control valve",
            "F": "flow control valve", "T": "temperature control valve",
            "H": "hand control valve",
        }.get(head, "control valve")
        purpose = purpose or _cv_purpose(ctx, item)
    else:
        kind = "valve"
        purpose = purpose or _valve_duty(item)
    effect = str(effect or "").strip()
    effect = effect[0].lower() + effect[1:] if effect else "the intended duty is lost."
    if effect.endswith("."):
        effect = effect[:-1]
    return f"{tag} is a {kind}; its purpose is to {purpose}. When {effect}."


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
    """Design and operating conditions — P&ID block plus Step 3 mapped PFD operating parameters."""
    from .parse import _harvest_design
    _harvest_design(ctx.equipment, ctx.ext.get("tokens") or [])
    sentences = []
    for eq in _large_equipment(ctx)[:6]:
        d = dict(eq.get("design") or {})
        mapped = (getattr(ctx, "equipment_operating", None) or {}).get(str(eq.get("tag") or "").upper()) or {}
        if mapped.get("p_op") is not None and d.get("p_op") is None:
            d["p_op"] = mapped["p_op"]
        if mapped.get("t_op") is not None and d.get("t_op") is None:
            d["t_op"] = mapped["t_op"]
        bits = []
        if d.get("p_des"):
            bits.append(f"design pressure {d['p_des']} psig")
        if d.get("p_op"):
            src = " from PFD map" if mapped.get("p_op") is not None and (eq.get("design") or {}).get("p_op") is None else ""
            bits.append(f"operating pressure {d['p_op']} psig{src}")
        if d.get("t_des"):
            bits.append(f"design temperature {d['t_des']} {DEG}")
        if d.get("t_op") is not None:
            src = " from PFD map" if mapped.get("t_op") is not None and (eq.get("design") or {}).get("t_op") is None else ""
            bits.append(f"operating temperature {d['t_op']} {DEG}{src}")
        if bits:
            sentences.append(f"{eq['tag']}: " + ", ".join(bits))
        else:
            sentences.append(f"{eq['tag']}: design and operating conditions are not shown on the P&ID")
    # Also state a few mapped line operating conditions from Step 3.
    line_ops = getattr(ctx, "line_operating", None) or {}
    for tag, ops in list(line_ops.items())[:4]:
        bits = []
        if ops.get("p_op") is not None:
            bits.append(f"{ops['p_op']} psig")
        if ops.get("t_op") is not None:
            bits.append(f"{ops['t_op']} {DEG}")
        if bits:
            stream = f" (PFD stream {ops['pfd_stream']})" if ops.get("pfd_stream") else ""
            sentences.append(f"Line {tag}{stream}: operating " + ", ".join(bits))
    return ". ".join(sentences)


def _overall_intent(ctx):
    """One sentence for what this node is there to do — prefer PFD equipment purpose from step 1."""
    fluid = ctx.fluid
    large = _large_equipment(ctx)
    # Prefer the purpose already learned from the PFD for equipment on this node.
    pfd_purposes = getattr(ctx, "pfd_equipment_purposes", None) or []
    if pfd_purposes and large:
        tags = {str(e.get("tag") or "").upper() for e in large}
        matched = [
            item for item in pfd_purposes
            if str(item.get("tag") or "").upper() in tags
        ]
        if matched:
            return " ".join(item["purpose"] for item in matched[:3])
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
        system = (getattr(ctx, "pfd_system_purpose", None) or "").strip()
        if system:
            return system.split(".")[0].strip() + "."
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


def _line_size_inches(line):
    """Nominal bore in inches, or None when the size was not read."""
    raw = str(line.get("size") or "").strip().strip('"').replace("″", "").replace("'", "")
    if not raw:
        return None
    raw = raw.replace(" ", "")
    if re.fullmatch(r"\d+-\d+/\d+", raw):
        whole, num, den = re.match(r"(\d+)-(\d+)/(\d+)", raw).groups()
        return float(whole) + float(num) / float(den)
    if "/" in raw:
        num, den = raw.split("/", 1)
        try:
            return float(num) / float(den)
        except ValueError:
            return None
    try:
        return float(raw)
    except ValueError:
        return None


def _is_trim_line(line):
    """Instrument / utility / small-bore hook-up — not the indicated node process piping."""
    if _off_process_line(line):
        return True
    service = str(line.get("service") or "").upper()
    if service in ("GI", "GU", "IA", "N", "SO", "LO"):
        return True
    inches = _line_size_inches(line)
    return inches is not None and inches <= 1.0


def _node_piping(ctx):
    """Indicated process piping for this node — not equipment internals and not trim.

    Prefer line tags marked on the node. Drop flare/vent/drain and small-bore instrument
    trim so the node description follows the indicated pipe only.
    """
    tagged = {str(t).upper() for t in (getattr(ctx, "node_line_tags", None) or []) if t}
    pool = []
    for line in ctx.process_lines:
        tag = str(line.get("tag") or "").upper()
        if not tag:
            continue
        if tagged and tag in tagged:
            pool.append(line)
            continue
        if _is_trim_line(line):
            continue
        if not tagged:
            pool.append(line)
    if tagged:
        indicated = [line for line in pool if str(line.get("tag") or "").upper() in tagged]
        if indicated:
            pool = indicated
    if not pool:
        pool = [line for line in ctx.process_lines if not _is_trim_line(line)] or list(ctx.process_lines)
    large = [line for line in pool if (_line_size_inches(line) or 0) > 1.0]
    if large and len(large) < len(pool):
        tagged_large = [line for line in large if not tagged or str(line.get("tag") or "").upper() in tagged]
        if tagged_large or not tagged:
            return tagged_large or large
    return pool


def _equipment_on_piping(ctx, piping):
    """Large equipment that the indicated node piping meets — not every nearby tag."""
    boxes = []
    for line in piping or []:
        boxes.extend(line.get("boxes") or ([line["box"]] if line.get("box") else []))
    if not boxes:
        return []
    found = []
    for eq in _large_equipment(ctx):
        if eq.get("box") and _near_any(eq["box"], boxes, 0.12):
            found.append(eq)
    return found


def _lines_on_route(ctx, source, target):
    """Indicated node piping from this inlet toward the main equipment, along the flow."""
    box = source.get("box") or [0, 0, 0, 0]
    sy = (box[1] + box[3]) / 2
    sx = _cx(source)
    end_x = _cx(target) if target else 1
    found = []
    seen = set()
    for line in _node_piping(ctx):
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


def _order_along_flow(ctx, items, toward):
    """Order equipment the way the pipe arrows run into the target, not left-to-right by default."""
    if not items:
        return []
    if not toward:
        return sorted(items, key=_cx)
    heading = _heading_at(ctx, toward.get("box"))
    # heading -1 means upstream is to the left of target → feeders should be listed left-to-right into target.
    reverse = heading > 0
    return sorted(items, key=_cx, reverse=reverse)


def _node_description(ctx, color=None):
    """Short route summary of the indicated node piping only — not trim, not equipment internals."""
    fluid = ctx.fluid
    piping = _node_piping(ctx)
    large = _equipment_on_piping(ctx, piping) or _large_equipment(ctx)
    vessels = [e for e in large if e.get("kind") == "vessel"]
    target = vessels[0] if vessels else (large[-1] if large else None)
    valves = [v for v in ctx.find(cats=("control_valve",)) if not _on_off_process(ctx, v)]
    sentences = []
    # The subject of the description is always the indicated pipe tags.
    line_bits = [_line_phrase(ctx, line) for line in piping[:3]]
    where = f" on {_and(line_bits)}" if line_bits else ""

    feeders = _feeders_of(ctx, target) if target else []
    if target and feeders:
        ordered = _order_along_flow(ctx, feeders, target)
        # Control valves that sit on the indicated piping between feeder and target.
        on_path = []
        for feeder in ordered:
            for valve in valves:
                line = _line_between(ctx, feeder, target)
                if line and line not in piping:
                    continue
                boxes = (line.get("boxes") if line else None) or ([line["box"]] if line and line.get("box") else [])
                if line and valve.get("box") and boxes and _near_any(valve["box"], boxes, 0.1):
                    if valve not in on_path:
                        on_path.append(valve)
        origin = _and([_eq_phrase(eq) for eq in ordered[:3]])
        mid = []
        # Equipment the indicated piping passes — named as way-points, not as piping itself.
        for eq in _order_along_flow(ctx, [e for e in large if e.get("tag") != target.get("tag") and e not in ordered], target):
            mid.append(_eq_phrase(eq))
        if on_path:
            mid.append(_join_tags([v.get("tag") for v in on_path]))
        if mid:
            sentences.append(
                f"{fluid.capitalize()} piping{where} from {origin} passes {', '.join(mid)} to {target['tag']}."
            )
        else:
            sentences.append(f"{fluid.capitalize()} piping{where} from {origin} to {target['tag']}.")
    else:
        sources = sorted(ctx.sources, key=lambda item: (_cx(item), ((item.get("box") or [0, 0, 0, 0])[1])))
        if not sources and large:
            sources = [{"description": _eq_phrase(large[0]), "box": large[0].get("box"), "_skip": large[0]["tag"]}]

        def _on_this_inlet(item, source):
            if source.get("_skip") and item.get("tag") == source.get("_skip"):
                return False
            if target and item.get("tag") == target.get("tag"):
                return False
            if piping and item in _large_equipment(ctx) and item not in large:
                return False
            if target and item in large:
                line = _line_between(ctx, item, target)
                if line and line not in piping and piping:
                    return False
                verdict = _flows_from_to(line, item, target) if line else None
                if verdict is False:
                    return False
            x = _cx(item)
            lo, hi = sorted([_cx(source), _cx(target) if target else 1])
            if x < lo - 0.05 or x > hi + 0.05:
                return False
            nearest = min(sources, key=lambda s: abs(_cy(s) - _cy(item)))
            return nearest is source

        for index, source in enumerate(sources[:4]):
            route_lines = _lines_on_route(ctx, source, target) or piping[:2]
            route_where = f" on {_and([_line_phrase(ctx, line) for line in route_lines[:2]])}" if route_lines else where
            along = _order_along_flow(ctx, [eq for eq in large if _on_this_inlet(eq, source)], target)
            through = [_eq_phrase(eq) for eq in along]
            on_path = [v for v in valves if _on_this_inlet(v, source)]
            on_path = _order_along_flow(ctx, on_path, target) if target else sorted(on_path, key=_cx)
            if on_path:
                through.append(_join_tags([v.get("tag") for v in on_path]))
            lead = f"{fluid.capitalize()} piping" if index == 0 else f"Other {fluid} piping"
            origin = _conn_name(source)
            named = str(source.get("equipment") or "").strip()
            if named:
                origin = named
            if through and target:
                sentences.append(f"{lead}{route_where} from {origin} passes {', '.join(through)} to {target['tag']}.")
            elif target:
                sentences.append(f"{lead}{route_where} from {origin} to {target['tag']}.")
            elif through:
                sentences.append(f"{lead}{route_where} from {origin} passes {', '.join(through)}.")
            else:
                sentences.append(f"{lead}{route_where} from {origin}.")

    if vessels:
        # Outlet on indicated node piping only — not a drain/trim branch.
        outlet_line = _line_toward(ctx, vessels[0].get("box"), 1)
        if outlet_line and outlet_line not in piping and piping:
            outlet_line = next((line for line in piping if _cx(line) >= _cx(vessels[0]) - 0.02), None)
        outlet_text = f" through {_line_phrase(ctx, outlet_line)}" if outlet_line else " through the outlet liquid piping"
        liquid = [c for c in ctx.dests if any(word in _conn_name(c) for word in ("separat", "liquid", "oil", "condensate", "water"))]
        chosen = liquid or list(ctx.dests)
        if chosen:
            places = _and([_place_name(_conn_name(c)) for c in chosen[:3]])
            sentences.append(
                f"{vessels[0]['tag']} separates the liquid from vapor and liquid leaves on the indicated "
                f"piping{outlet_text} going to {places}."
            )
        else:
            sentences.append(f"{vessels[0]['tag']} separates the liquid from vapor.")
    elif not sentences:
        bits = f" on {_and(line_bits)}" if line_bits else ""
        sentences.append(f"{fluid.capitalize()} piping{bits} from {ctx.src_text()} to {ctx.dest_text()}.")
    return " ".join(sentences)


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
    text = i.get("variable") or i.get("letters") or i.get("tag") or ""
    return str(text).split(" /")[0].lower()


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
    """Process-line check valves / FSVs only — drain, flare and root devices are not safeguards here."""
    found, seen = [], set()
    for inst in _process_check_devices(ctx, eq):
        tag = str(inst.get("tag") or inst.get("code") or "").upper()
        if not tag or tag in seen:
            continue
        seen.add(tag)
        found.append(inst)
        if len(found) >= 4:
            break
    return [
        sg(f"{i.get('tag') or i.get('code')} check valve", i.get("tag") or i.get("code"), strong=True)
        for i in found
    ]


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


def _norm_row_text(text):
    return re.sub(r"\s+", " ", str(text or "").strip().lower())


def _cause_device_key(cause):
    """One device failure is one cause: ('LV-8250A', 'closed'). Empty tag → full-text key."""
    text = str(cause or "")
    match = re.search(r"\b([A-Z]{1,5}-\d{3,5}[A-Z0-9]*)\b", text.upper())
    tag = match.group(1) if match else ""
    low = text.lower()
    if "fails closed" in low or "fail closed" in low or "fails shut" in low or "sticks closed" in low:
        action = "closed"
    elif "fails open" in low or "fail open" in low or "sticks open" in low:
        action = "open"
    elif "inadvertent closure" in low or "isolation" in low:
        action = "isolation"
    elif "fails" in low:
        action = "fails"
    else:
        action = _norm_row_text(text)
    if tag:
        return (tag, action)
    return ("", _norm_row_text(text))


def _unique_cause_rows(rows):
    """Keep the first row for each device failure; drop later repeats of the same cause."""
    seen = set()
    out = []
    for item in rows or []:
        key = _cause_device_key(item.get("cause"))
        if key in seen and key[0]:
            continue
        if key[0]:
            seen.add(key)
        elif key[1]:
            if key[1] in seen:
                continue
            seen.add(key[1])
        out.append(item)
    return out


_CAUSE_CROSS_REF = re.compile(
    r"(?i)\b("
    r"refer(?:ring)?\s+to|same\s+as|as\s+above|as\s+before|as\s+per\b|"
    r"see\s+(?:earlier|above|previous|cause|consequence|clause)|"
    r"per\s+(?:earlier|previous|above)\s+(?:cause|consequence|clause)|"
    r"already\s+(?:written|stated|covered)|"
    r"described\s+(?:earlier|above|previously)|"
    r"earlier\s+(?:cause|consequence|clause|row)|"
    r"previous\s+(?:cause|consequence|clause|row)"
    r")\b"
)


def _cause_refers_elsewhere(cause):
    """True when the cause column points at another cause/consequence instead of stating a failure."""
    text = str(cause or "").strip()
    if not text:
        return True
    if _CAUSE_CROSS_REF.search(text):
        return True
    # Bare cross-ref lines such as "Refer to clause 1.2 cause 1."
    if re.match(r"(?i)^(same\s+as|refer\s+to|as\s+above|see\s+)\b", text):
        return True
    return False


def _scrub_cause_cross_refs(nodes):
    """Remove any row whose cause refers to another cause or consequence."""
    for node in nodes or []:
        for group in node.get("deviations") or []:
            group["rows"] = [
                item for item in (group.get("rows") or [])
                if not _cause_refers_elsewhere(item.get("cause"))
            ]


def _dedupe_worksheet(nodes):
    """Drop repeated device/cause rows. Cause never cross-refers; repeated consequence text may point back."""
    seen_causes = {}
    seen_devices = set()
    seen_cons = {}
    for node in nodes or []:
        for group in node.get("deviations") or []:
            label = str(group.get("deviation") or "").strip() or "deviation"
            kept = []
            for index, item in enumerate(group.get("rows") or [], 1):
                cause = str(item.get("cause") or "").strip()
                # Cause states a failure only — never a pointer to another row.
                if _cause_refers_elsewhere(cause):
                    continue
                device = _cause_device_key(cause)
                # Same LV/PV failure already written earlier on this worksheet → drop the repeat.
                if device[0] and device in seen_devices:
                    continue
                if device[0]:
                    seen_devices.add(device)
                key = _norm_row_text(cause)
                if key:
                    if key in seen_causes:
                        # Same cause already written — drop the extra line (do not rewrite as Refer to…).
                        continue
                    seen_causes[key] = f"{label} cause {index}"
                fresh = []
                for cons in item.get("consequences") or []:
                    text = str(cons or "").strip()
                    ck = _norm_row_text(text)
                    if not ck:
                        continue
                    # Do not keep a consequence that only points at a cause; cause owns the failure.
                    if re.search(r"(?i)\brefer(?:ring)?\s+to\b.*\bcause\b", text):
                        continue
                    if re.match(r"^(same as|refer to)\b", text, re.I):
                        continue
                    if ck in seen_cons:
                        fresh.append(f"Refer to clause {seen_cons[ck]}.")
                    else:
                        seen_cons[ck] = f"{label} consequence {index}"
                        fresh.append(text)
                if fresh:
                    item["consequences"] = fresh
                kept.append(item)
            group["rows"] = kept
    _scrub_cause_cross_refs(nodes)


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


def _valve_size_inches(valve):
    """Nominal size of a piping valve, when OCR read one beside the code."""
    return _line_size_inches({"size": valve.get("size")}) if valve.get("size") else None


def _is_root_or_drain_valve(ctx, valve):
    """Instrument root valves and piping drain valves must not be deviation causes.

    A root valve sits on the instrument tap (beside PI/PT/TI/LT/…). A drain valve sits on a
    drain branch or as a small bore dump under the line / equipment — neither blocks main flow.
    """
    kind = str(valve.get("type") or "").lower()
    code = str(valve.get("code") or valve.get("tag") or "").upper()
    # Needle valves are root / bleed / drain by piping practice.
    if kind.startswith("needle") or code.startswith("VN"):
        return True
    if "DRAIN" in code or "BLEED" in code or "VENT" in code or "ROOT" in code:
        return True
    box = valve.get("box")
    if not box:
        return False
    nearest = _nearest_line(ctx.lines, box, limit=0.1)
    if nearest and _off_process_line(nearest):
        return True
    inches = _valve_size_inches(valve)
    # Beside a measuring / indicating instrument and closer to it than to main equipment → root.
    best_inst = None
    for inst in ctx.instruments:
        if not inst.get("box"):
            continue
        if inst.get("category") in ("control_valve", "relief"):
            continue
        letters = str(inst.get("letters") or "")
        # Controllers / trips are not the tap the root valve serves; indicators and transmitters are.
        if inst.get("category") not in ("indicator", "transmitter", "element", "alarm", "switch", None, ""):
            if letters[1:2] not in ("I", "T", "E", "A", "S") and not letters.endswith(("I", "T", "E")):
                continue
        gap = _box_gap(box, inst["box"])
        if gap <= 0.08 and (best_inst is None or gap < best_inst[0]):
            best_inst = (gap, inst)
    if best_inst:
        eq_gap = min(
            (_box_gap(box, eq["box"]) for eq in _large_equipment(ctx) if eq.get("box")),
            default=999.0,
        )
        cv_gap = min(
            (_box_gap(box, cv["box"]) for cv in ctx.find(cats=("control_valve",)) if cv.get("box")),
            default=999.0,
        )
        if best_inst[0] < min(eq_gap, cv_gap) - 0.005:
            return True
        if inches is not None and inches <= 1.0:
            return True
    # Small bore under equipment = typical piping drain, not a process block valve.
    if inches is not None and inches <= 1.0:
        for eq in _large_equipment(ctx):
            if not eq.get("box"):
                continue
            if _box_gap(box, eq["box"]) <= 0.18 and _cy({"box": box}) >= _cy(eq) + 0.01:
                return True
    return False


def _isolation_valves(ctx, steady=True):
    """Main-line isolation valves only. steady=True drops flare/vent/drain/PSV, root and drain valves."""
    valves = [v for v in ctx.valves if any(str(v.get("type") or "").lower().startswith(kind) for kind in _ISOLATION)]
    if steady:
        valves = [v for v in valves
                  if not _on_off_process(ctx, v) and not _is_root_or_drain_valve(ctx, v)]
    return valves


def _box_gap(a, b):
    if not a or not b:
        return 999.0
    ax, ay = (a[0] + a[2]) / 2, (a[1] + a[3]) / 2
    bx, by = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
    return ((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5


def _on_off_process(ctx, item):
    """True when a valve or instrument sits on a flare, vent, drain or PSV branch.

    Those paths are not live during steady-state operation, so closing them must not be
    written as the same deviation as closing a valve on the main process supply / outlet.
    """
    box = item.get("box") if isinstance(item, dict) else None
    if not box:
        return False
    # Nearest drawn line decides: if that line is flare/vent/drain/SV, the valve is off-process.
    nearest = _nearest_line(ctx.lines, box, limit=0.12)
    if nearest and _off_process_line(nearest):
        return True
    # Drain / flare tees: FSV often sits on the branch while a process line is also close —
    # any nearby off-process line still means the component is not a process cause.
    for line in ctx.off_process_lines:
        boxes = line.get("boxes") or ([line["box"]] if line.get("box") else [])
        if boxes and _near_any(box, boxes, 0.15):
            return True
    # Beside a drain / flare / vent / blowdown connector.
    for conn in ctx.connectors:
        text = (conn.get("description") or "").upper()
        if not any(w in text for w in ("FLARE", "VENT", "DRAIN", "BLOWDOWN", "BLOW DOWN")):
            continue
        if conn.get("box") and _box_gap(box, conn["box"]) <= 0.14:
            return True
    proc = _nearest_line(ctx.process_lines, box, limit=0.12)
    proc_gap = _box_gap(box, proc.get("box") if proc else None) if proc else 999.0
    # Inlet / outlet isolation drawn beside a PSV, closer to the PSV than to any process line.
    for inst in ctx.instruments:
        letters = str(inst.get("letters") or "")
        is_relief = (
            inst.get("category") == "relief"
            or letters in _RELIEF_LETTERS
            or letters.startswith(("PSV", "PZV", "PRV", "PSE"))
        )
        if not is_relief or not inst.get("box"):
            continue
        psv_gap = _box_gap(box, inst["box"])
        if psv_gap <= 0.09 and psv_gap < proc_gap - 0.01:
            return True
    code = str(item.get("code") or item.get("tag") or "").upper()
    if any(token in code for token in ("BDV", "VENT", "DRAIN", "FLARE", "BLOWDOWN")):
        return True
    return False


def _skip_deviation_cause(ctx, item):
    """Flare / drain / vent piping and instrument root valves must not be deviation causes."""
    if not item:
        return True
    if _on_off_process(ctx, item):
        return True
    if _is_root_or_drain_valve(ctx, item):
        return True
    return False


def _process_check_devices(ctx, eq=None):
    """Check valves / FSVs on live process piping only — not drain, flare or root."""
    found = []
    for inst in ctx.instruments:
        if not _is_check_device(inst):
            continue
        if _skip_deviation_cause(ctx, inst):
            continue
        if eq is not None and not _same_equipment(ctx, inst, eq):
            continue
        found.append(inst)
    if found:
        return found
    for valve in ctx.valves_of("check"):
        if _skip_deviation_cause(ctx, valve):
            continue
        found.append(valve)
    return found


def _isolation_cause(ctx, box, anchor):
    """Name main-line isolation valves with line numbers — not instrument root valves or piping drains."""
    valves = [v for v in _isolation_valves(ctx, steady=True)
              if v.get("box") and box and _near_any(v["box"], [box], 0.08)]
    if valves:
        return f"Inadvertent closure of {_valve_labels(ctx, valves)} through {anchor}."
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


def _is_level_valve(inst):
    letters = str(inst.get("letters") or "")
    return letters[:1] == "L" and inst.get("category") == "control_valve"


def _level_vessel_for(ctx, cv, fallback=None):
    """The vessel whose liquid level this LV holds — the drum upstream of the liquid outlet valve."""
    owner = _owner(ctx, cv)
    if owner and owner.get("kind") in ("vessel", "tank"):
        return owner
    up = _nearest_large(ctx, cv.get("box"), -1)
    if up and up.get("kind") in ("vessel", "tank"):
        return up
    if fallback and fallback.get("kind") in ("vessel", "tank"):
        return fallback
    for eq in _large_equipment(ctx):
        if eq.get("kind") in ("vessel", "tank"):
            return eq
    return fallback or up


def _lv_purpose(vessel):
    """What an LV is for: hold liquid level by releasing liquid from the bottom outlet."""
    name = _equip_name(vessel, "the vessel") if isinstance(vessel, dict) else str(vessel or "the vessel")
    return f"hold the liquid level in {name} by releasing liquid from the bottom / liquid outlet"


def _lv_closed_consequence(ctx, cv, vessel):
    """LV fails closed → liquid cannot leave → high level → carryover to the vapour outlet (not the liquid line)."""
    tag = cv.get("tag") or "the level valve"
    vessel_name = _equip_name(vessel, "the vessel")
    vapour_dest = None
    for conn in ctx.dests:
        text = _conn_name(conn).lower()
        if any(word in text for word in ("gas", "vapour", "vapor", "fuel", "flare", "compress", "scrubber", "header")):
            vapour_dest = _place_name(_conn_name(conn))
            break
    if not vapour_dest:
        down = _nearest_large(ctx, (vessel or {}).get("box") if vessel else cv.get("box"), 1)
        if down and down.get("tag") != (vessel or {}).get("tag"):
            vapour_dest = _equip_name(down, ctx.dest_text())
        else:
            vapour_dest = "the vapour / gas outlet downstream"
    return (
        f"{tag} is the level control valve on the liquid outlet of {vessel_name}; its purpose is to {_lv_purpose(vessel)}. "
        f"When {tag} fails closed, liquid can no longer leave {vessel_name}, the level rises, "
        f"and liquid carries over into the vapour outlet toward {vapour_dest}. "
        f"Downstream gas users can see liquid."
    )


def _lv_open_consequence(ctx, cv, vessel):
    """LV fails open → liquid dumps → low level → gas blows through the liquid outlet."""
    tag = cv.get("tag") or "the level valve"
    vessel_name = _equip_name(vessel, "the vessel")
    liquid_dest = None
    for conn in ctx.dests:
        text = _conn_name(conn).lower()
        if any(word in text for word in ("separat", "liquid", "oil", "condensate", "water", "drain")):
            liquid_dest = _place_name(_conn_name(conn))
            break
    if not liquid_dest:
        liquid_dest = ctx.dest_text()
    effect = (
        f"{tag} is the level control valve on the liquid outlet of {vessel_name}; its purpose is to {_lv_purpose(vessel)}. "
        f"When {tag} fails open, the liquid inventory leaves {vessel_name}, the liquid seal is lost, "
        f"and gas blows through the liquid outlet toward {liquid_dest}."
    )
    # Blow-through travels on the liquid outlet line — name that PFD stream when known.
    return _cons_related(ctx, cv.get("box"), (vessel or {}).get("tag") or tag, effect.rstrip("."))


def _instrument_duty(inst, ctx=None):
    """What this instrument is on the drawing to do, from its ISA letters."""
    letters = inst.get("letters") or ""
    meaning = kb.describe_instrument(letters) if letters else (inst.get("tag") or "instrument")
    category = inst.get("category")
    if category == "safety" or letters.startswith("FSV") or _is_check_device(inst):
        if ctx is not None:
            return _check_purpose(ctx, inst)
        return "stop reverse flow (check valve / flow safety valve)"
    if category == "controller":
        point = f" at {inst['set_point']}" if inst.get("set_point") else ""
        return f"control the process ({meaning}{point})"
    if category == "control_valve":
        fail = {"FC": " and close on loss of air", "FO": " and open on loss of air", "FL": " and stay put on loss of air"}.get(inst.get("fail_action") or "", "")
        if letters[:1] == "L":
            vessel = _level_vessel_for(ctx, inst) if ctx is not None else None
            return _lv_purpose(vessel) + fail
        if letters[:1] == "P":
            return f"let down / control pressure ({meaning}{fail})"
        if letters[:1] == "F":
            return f"control flow ({meaning}{fail})"
        if letters[:1] == "T":
            return f"control temperature ({meaning}{fail})"
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
    if _is_check_device(inst):
        return "Reverse Flow"
    if inst.get("category") == "relief":
        return "High Pressure"
    if inst.get("category") == "control_valve":
        # An LV holds level: closed → high level, open → low level. Not a flow deviation.
        if var == "L":
            return "High Level" if inst.get("fail_action") != "FO" else "Low Level"
        if var == "P":
            return "No / Less Flow" if inst.get("fail_action") == "FC" else "More Flow / High Pressure"
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
    if _is_check_device(inst) or category == "safety":
        return (
            f"{tag} no longer {duty}. Reverse flow is no longer stopped, "
            f"so upstream equipment can see backflow, overpressure or contamination."
        )
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


def _place_check_rows(node, ctx, inst):
    """Write FSV / check causes using the phase of the line the device sits on."""
    if _skip_deviation_cause(ctx, inst) or _is_normally_open(inst):
        return
    tag = _valve_label(ctx, inst)
    owner = _owner(ctx, inst)
    up_eq, _, _, _ = _check_neighbors(ctx, inst)
    phase = _check_phase(ctx, inst)
    _place_row(
        node, "Reverse Flow",
        _cause_ltr(ctx, inst.get("box"), tag, f"{tag} sticks open (fails to seat)."),
        [_check_stuck_open_consequence(ctx, inst)],
        relief_safeguards(ctx, owner) + trip_safeguards(ctx, "P", "H", owner)
        + (trip_safeguards(ctx, "L", "H", up_eq) if phase == "liquid" and up_eq else []),
        4, 2,
    )
    # Liquid outlet of a vessel: stuck closed backs liquid into the drum → high level.
    if phase == "liquid" and up_eq and up_eq.get("kind") in ("vessel", "tank"):
        closed_dev, closed_sg, sev = "High Level", trip_safeguards(ctx, "L", "H", up_eq), 4
    elif phase == "liquid":
        closed_dev, closed_sg, sev = "No / Less Flow", trip_safeguards(ctx, "L", "H", up_eq) + trip_safeguards(ctx, "P", "L", owner), 3
    else:
        closed_dev, closed_sg, sev = "No / Less Flow", trip_safeguards(ctx, "P", "L", owner), 3
    _place_row(
        node, closed_dev,
        _cause_ltr(ctx, inst.get("box"), tag, f"{tag} sticks closed (fails to open)."),
        [_check_stuck_closed_consequence(ctx, inst)],
        closed_sg, sev, 2,
    )


def _instrument_row(node, ctx, inst):
    duty = _instrument_duty(inst, ctx)
    tag = inst.get("tag") or "instrument"
    line = _nearest_line(ctx.lines, inst.get("box"), limit=None)
    where = f" on {line['tag']}" if line else ""
    if _is_check_device(inst):
        _place_check_rows(node, ctx, inst)
        return
    if _is_level_valve(inst):
        vessel = _level_vessel_for(ctx, inst)
        closed = _lv_closed_consequence(ctx, inst, vessel)
        opened = _lv_open_consequence(ctx, inst, vessel)
        loss_sg = trip_safeguards(ctx, "L", "H", vessel)
        open_sg = trip_safeguards(ctx, "L", "L", vessel)
        _place_row(node, "High Level",
                   _cause_ltr(ctx, inst.get("box"), tag, f"{tag} fails closed."),
                   [closed], loss_sg, 4, 3)
        _place_row(node, "Low Level",
                   _cause_ltr(ctx, inst.get("box"), tag, f"{tag} fails open."),
                   [opened], open_sg, 5, 3)
        return
    _place_row(
        node, _instrument_deviation(inst),
        f"If {tag} faults{where}, it can no longer {duty}.",
        [_instrument_effect(inst, duty)],
        _same_variable_safeguards(ctx, inst),
        4 if inst.get("category") in ("trip", "relief", "control_valve", "safety") else 3, 2,
    )


def _cy(item):
    box = item.get("box") or [0, 0, 0, 0]
    return (box[1] + box[3]) / 2


def _flow_to_upstream_heading(flow):
    """Map a line flow compass letter to the geometric side where upstream sits (-1 left/up, +1 right/down)."""
    flow = str(flow or "").upper()
    if flow == "E":
        return -1  # flows east → upstream is west (left)
    if flow == "W":
        return 1
    if flow == "S":
        return -1  # flows south → upstream is north (above); x-fallback uses left
    if flow == "N":
        return 1
    return None


def _nearest_process_line(ctx, box):
    if not box:
        return None
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    best, dist = None, None
    for line in ctx.process_lines:
        boxes = line.get("boxes") or ([line["box"]] if line.get("box") else [])
        for candidate in boxes:
            lx, ly = (candidate[0] + candidate[2]) / 2, (candidate[1] + candidate[3]) / 2
            gap = ((lx - cx) ** 2 + (ly - cy) ** 2) ** 0.5
            if dist is None or gap < dist:
                best, dist = line, gap
    return best


def _heading_at(ctx, box):
    """Upstream geometric heading at this point from the nearest pipe arrow (local, not sheet-wide)."""
    line = _nearest_process_line(ctx, box)
    if line:
        local = _flow_to_upstream_heading(line.get("flow"))
        if local is not None:
            return local
    return getattr(ctx, "upstream_side", -1)


def _flows_from_to(line, source, dest):
    """True when the arrow on this line runs from source equipment to dest equipment."""
    if not line or not source or not dest:
        return None
    flow = str(line.get("flow") or "").upper()
    if not flow:
        return None
    sx, sy = _cx(source), _cy(source)
    dx, dy = _cx(dest), _cy(dest)
    if flow == "E":
        return sx < dx - 0.005
    if flow == "W":
        return sx > dx + 0.005
    if flow == "S":
        return sy < dy - 0.005
    if flow == "N":
        return sy > dy + 0.005
    return None


def _line_between(ctx, left, right):
    """Process line that sits between two equipment boxes (same band)."""
    if not left or not right or not left.get("box") or not right.get("box"):
        return None
    x0, x1 = sorted([_cx(left), _cx(right)])
    y0, y1 = sorted([_cy(left), _cy(right)])
    mid_y = (_cy(left) + _cy(right)) / 2
    best, dist = None, None
    for line in ctx.process_lines:
        boxes = line.get("boxes") or ([line["box"]] if line.get("box") else [])
        for candidate in boxes:
            lx = (candidate[0] + candidate[2]) / 2
            ly = (candidate[1] + candidate[3]) / 2
            if lx < x0 - 0.05 or lx > x1 + 0.05:
                continue
            if abs(ly - mid_y) > max(0.12, (y1 - y0) + 0.08):
                continue
            gap = abs(ly - mid_y)
            if dist is None or gap < dist:
                best, dist = line, gap
    return best


def _feeders_of(ctx, target):
    """Equipment that the pipe arrows show feeding this equipment (e.g. HAP-2850 → scrubber)."""
    if not target:
        return []
    feeders = []
    for eq in _large_equipment(ctx):
        if eq.get("tag") == target.get("tag"):
            continue
        line = _line_between(ctx, eq, target)
        verdict = _flows_from_to(line, eq, target) if line else None
        if verdict is True:
            feeders.append(eq)
            continue
        if verdict is False:
            continue
        # No arrow between them: a FROM connector that names this feeder near the target counts.
        for conn in ctx.sources:
            named = str(conn.get("equipment") or "").upper()
            if named and named == str(eq.get("tag") or "").upper():
                if abs(_cy(conn) - _cy(target)) < 0.2 or abs(_cy(conn) - _cy(eq)) < 0.2:
                    feeders.append(eq)
                    break
    return feeders


def _nearest_large(ctx, box, side=0):
    """side -1 is upstream along the local pipe arrow, +1 is downstream, 0 is the nearest."""
    items = _large_equipment(ctx)
    if not items:
        return None
    if not box:
        return items[0]
    cx = (box[0] + box[2]) / 2
    cy = (box[1] + box[3]) / 2
    if side == 0:
        return min(items, key=lambda e: abs(_cx(e) - cx) + abs(_cy(e) - cy))
    heading = _heading_at(ctx, box) * side
    line = _nearest_process_line(ctx, box)
    flow = str((line or {}).get("flow") or "").upper()
    # Vertical run: pick upstream/downstream by y along the arrow.
    if flow in ("N", "S"):
        if heading < 0:
            pool = [e for e in items if _cy(e) < cy - 0.005]
            return max(pool, key=_cy) if pool else None
        pool = [e for e in items if _cy(e) > cy + 0.005]
        return min(pool, key=_cy) if pool else None
    if heading < 0:
        pool = [e for e in items if _cx(e) < cx - 0.005]
        return pool[-1] if pool else None
    pool = [e for e in items if _cx(e) > cx + 0.005]
    return pool[0] if pool else None


def _downstream_drum(ctx, box):
    """The vessel or tank this valve feeds. Pressure relief on that drum is the safeguard."""
    drums = [item for item in _large_equipment(ctx) if item.get("kind") in ("vessel", "tank")]
    if not drums:
        return _nearest_large(ctx, box, 1)
    if not box:
        return drums[0]
    cx = (box[0] + box[2]) / 2
    cy = (box[1] + box[3]) / 2
    heading = _heading_at(ctx, box)
    line = _nearest_process_line(ctx, box)
    flow = str((line or {}).get("flow") or "").upper()
    if flow in ("N", "S"):
        if heading < 0:
            ahead = [item for item in drums if _cy(item) >= cy - 0.02]
        else:
            ahead = [item for item in drums if _cy(item) <= cy + 0.02]
    elif heading < 0:
        ahead = [item for item in drums if _cx(item) >= cx - 0.02]
    else:
        ahead = [item for item in drums if _cx(item) <= cx + 0.02]
    pool = ahead or drums
    return min(pool, key=lambda item: abs(_cx(item) - cx) + abs(_cy(item) - cy))


def _equip_name(eq, fallback):
    if not eq:
        return fallback
    desc = str(eq.get("description") or "").strip()
    if desc and eq.get("tag") and eq["tag"] not in desc:
        return f"{desc} {eq['tag']}"
    return eq.get("tag") or fallback


def _upstream_side(ctx):
    """Sheet default: -1 when most arrows run left→right. Prefer arrows over connector guesses."""
    votes = Counter()
    for line in getattr(ctx, "process_lines", None) or []:
        flow = str(line.get("flow") or "").upper()
        weight = 3 if line.get("flow_from") == "arrow" else 1 if line.get("flow") else 0
        if not weight:
            continue
        if flow == "E":
            votes[-1] += weight
        elif flow == "W":
            votes[1] += weight
    if votes:
        return votes.most_common(1)[0][0]
    sources = getattr(ctx, "sources", None) or []
    dests = getattr(ctx, "dests", None) or []
    if sources and dests:
        sx = sum(_cx(c) for c in sources) / len(sources)
        dx = sum(_cx(c) for c in dests) / len(dests)
        return -1 if dx >= sx else 1
    return -1


def _line_toward(ctx, box, side):
    """Indicated node piping on the upstream (side -1) or downstream (side +1) side."""
    if not box:
        return None
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    heading = _heading_at(ctx, box) * side
    best, dist = None, None
    for line in _node_piping(ctx) or ctx.process_lines:
        boxes = line.get("boxes") or ([line["box"]] if line.get("box") else [])
        for candidate in boxes:
            lx, ly = (candidate[0] + candidate[2]) / 2, (candidate[1] + candidate[3]) / 2
            if abs(ly - cy) > 0.2:
                continue
            if heading < 0 and lx >= cx - 0.005:
                continue
            if heading > 0 and lx <= cx + 0.005:
                continue
            gap = abs(lx - cx)
            if dist is None or gap < dist:
                best, dist = line, gap
    return best


def _psig_text(value):
    """Normalise a pressure value from the P&ID or the PFD balance for consequence text."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return f"{value:g} psig"
    text = str(value).strip()
    if not text:
        return None
    if re.search(r"psig|psi|bara|barg|kpa|mpa", text, re.I):
        return text
    return f"{text} psig"


def _conditions_at(ctx, tag):
    """Design and operating P/T from the P&ID, Step 3 mapped ops, and the PFD balance."""
    out = {}
    tag_u = str(tag or "").upper()
    if not tag_u:
        return out
    for eq in ctx.equipment:
        if str(eq.get("tag") or "").upper() != tag_u:
            continue
        design = eq.get("design") or {}
        for key in ("p_des", "p_op", "t_des", "t_op"):
            if design.get(key) is not None:
                out[key] = design[key]
        break
    # Line tag: use Step 3 line operating parameters from the PFD stream map.
    line_ops = (getattr(ctx, "line_operating", None) or {}).get(tag) or (
        getattr(ctx, "line_operating", None) or {}
    ).get(tag_u)
    if line_ops:
        if line_ops.get("p_op") is not None and out.get("p_op") is None:
            out["p_op"] = line_ops["p_op"]
            out["p_stream"] = line_ops.get("pfd_stream")
        if line_ops.get("t_op") is not None and out.get("t_op") is None:
            out["t_op"] = line_ops["t_op"]
            out["t_stream"] = line_ops.get("pfd_stream")
    mapped = (getattr(ctx, "equipment_operating", None) or {}).get(tag_u) or {}
    if mapped.get("p_op") is not None and out.get("p_op") is None:
        out["p_op"] = mapped["p_op"]
        out["p_stream"] = mapped.get("p_stream") or mapped.get("pfd_stream")
    if mapped.get("t_op") is not None and out.get("t_op") is None:
        out["t_op"] = mapped["t_op"]
        out["t_stream"] = mapped.get("t_stream") or mapped.get("pfd_stream")
    for key, info in (getattr(ctx, "pfd_conditions", None) or {}).items():
        if key.upper() != tag_u and key.upper() not in tag_u and tag_u not in key.upper():
            continue
        if info.get("p_op") is not None and out.get("p_op") is None:
            out["p_op"] = info["p_op"]
            out["p_stream"] = info.get("p_stream")
        if info.get("t_op") is not None and out.get("t_op") is None:
            out["t_op"] = info["t_op"]
            out["t_stream"] = info.get("t_stream")
        break
    return out


def _overpressure_effect(ctx, here, upstream=None):
    """Consequence text from pressure physics: operating P, design P, and upstream source P."""
    here_tag = here.get("tag") if isinstance(here, dict) else here
    here_name = _equip_name(here, here_tag) if isinstance(here, dict) else str(here_tag or "this equipment")
    cond = _conditions_at(ctx, here_tag)
    up_tag = None
    up_cond = {}
    if upstream is not None:
        up_tag = upstream.get("tag") if isinstance(upstream, dict) else upstream
        up_cond = _conditions_at(ctx, up_tag)
    here_op = _psig_text(cond.get("p_op"))
    here_des = _psig_text(cond.get("p_des"))
    up_op = _psig_text(up_cond.get("p_op") or up_cond.get("p_des"))
    stream = cond.get("p_stream")
    bits = []
    if here_op and up_op and up_tag:
        bits.append(
            f"Pressure at {here_name} rises from its operating {here_op}"
            + (f" (PFD stream {stream})" if stream else "")
            + f" toward the upstream pressure at {up_tag} ({up_op})"
        )
    elif up_op and up_tag:
        bits.append(f"Pressure at {here_name} rises toward the upstream pressure at {up_tag} ({up_op})")
    elif here_op:
        bits.append(f"Pressure at {here_name} rises above its operating {here_op}")
    else:
        bits.append(f"Pressure at {here_name} rises above its normal operating pressure")
    if here_des:
        bits.append(
            f"If that exceeds the design pressure of {here_des}, the shell or outlet piping can rupture "
            f"and release {ctx.release}"
        )
    else:
        bits.append(f"and can overpressure {here_name}; loss of containment of {ctx.release} can follow")
    return ". ".join(bits)


def _outlet_blockers(ctx, eq):
    """Steady-state process valves that close the outlet and trap pressure — not PSV / flare / drain / root."""
    named = []
    eq_box = eq.get("box")
    for cv in ctx.find(cats=("control_valve",)):
        if _skip_deviation_cause(ctx, cv):
            continue
        if _same_equipment(ctx, cv, eq):
            tag = cv.get("tag")
            if not tag:
                continue
            label = _valve_label(ctx, cv)
            if label not in named and not any(tag == str(n).split(" on ")[0] for n in named):
                named.append(label)
    heading = getattr(ctx, "upstream_side", -1)
    for valve in _isolation_valves(ctx, steady=True):
        code = valve.get("code")
        if not code or not valve.get("box") or not eq_box:
            continue
        label = _valve_label(ctx, valve)
        if label in named or any(code == str(n).split(" on ")[0] for n in named):
            continue
        # Outlet side is downstream of the equipment along the flow arrows.
        on_outlet = (_cx(valve) - _cx(eq)) * (-heading) >= -0.02
        if on_outlet and _near_any(valve["box"], [eq_box], 0.16):
            named.append(label)
    for inst in ctx.instruments:
        if _skip_deviation_cause(ctx, inst):
            continue
        letters = str(inst.get("letters") or "")
        head = str(inst.get("tag") or "").split("-")[0]
        if letters not in _SHUTDOWN_LETTERS and head not in _SHUTDOWN_LETTERS:
            continue
        # Blowdown / flare shutdown valves are not a steady-state blocked-outlet cause.
        if letters in ("BDV",) or head in ("BDV",):
            continue
        if not _same_equipment(ctx, inst, eq):
            continue
        tag = inst.get("tag")
        if not tag:
            continue
        label = _valve_label(ctx, inst)
        if label not in named and not any(tag == str(n).split(" on ")[0] for n in named):
            named.append(label)
    return named


def _blocked_outlet_cause(ctx, eq, heater=False):
    """Name the particular valve (with line number) that closes and blocks the outlet."""
    blockers = _outlet_blockers(ctx, eq)
    tag = eq.get("tag") or "the equipment"
    if blockers:
        # Blockers are already valve std + line labels where known.
        listed = _valve_labels(ctx, blockers) if blockers and isinstance(blockers[0], dict) else (
            blockers[0] if len(blockers) == 1
            else f"{', '.join(blockers[:-1])} or {blockers[-1]}"
        )
        cause = f"Blocked outlet: {listed} closed on the outlet of {tag}"
    else:
        outlet = _line_toward(ctx, eq.get("box"), 1)
        if outlet:
            cause = (f"Blocked outlet: isolation valve closed on outlet line {outlet['tag']} from {tag}. "
                     "No valve tag was read on that outlet")
        else:
            cause = f"Blocked outlet: outlet isolation valve closed on {tag}. No valve tag was read on the outlet"
    if heater:
        cause += " while the heater stays energised, so the trapped fluid expands"
    return cause + "."


def _cause_ltr(ctx, box, anchor, failure):
    """Name the upstream line that reaches this point, following the pipe arrows."""
    failure = str(failure).strip().rstrip(".")
    # Valve std already carries its line number — do not repeat another line tag.
    if re.search(r"\bon\s+\d", failure, re.I) or "line not read" in failure.lower():
        if anchor and str(anchor) not in failure:
            return f"{failure} at {anchor}."
        return f"{failure}."
    upstream = _line_toward(ctx, box, -1)
    if upstream and upstream["tag"] not in failure:
        return f"{failure} on {upstream['tag']} at {anchor}."
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
    elif _is_check_device(inst) or cat == "safety" or letters.startswith("FSV"):
        _place_check_rows(node, ctx, inst)
        return
    else:
        return
    _place_row(node, deviation, _cause_ltr(ctx, inst.get("box"), tag, cause),
               [_cons_related(ctx, inst.get("box"), here, item) for item in cons],
               _named_safeguards(ctx, inst), 4 if cat in ("trip", "relief") else 3, 2)


def _component_rows(node, ctx):
    """One specific cause for each controlling, trip, alarm, relief or check device on this node."""
    for inst in _reading_order(ctx.instruments):
        if _skip_deviation_cause(ctx, inst):
            continue
        if inst.get("category") in ("indicator", "element", "relay", "other", "control_valve", None, ""):
            # FSV was historically "other"; still write it when letters say check valve.
            if not _is_check_device(inst):
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


def equipment_node(ctx, eq, nid, done_cvs=None):
    """Write deviations for this equipment, walking its control valves once along the flow."""
    tag, kind = eq["tag"], eq["kind"]
    d = eq["design"]
    label = KIND_LABEL.get(kind, "equipment")
    desc = eq["description"] or label.capitalize()
    done_cvs = done_cvs if done_cvs is not None else set()
    cvs = [item for item in ctx.find(cats=("control_valve",)) if _same_equipment(ctx, item, eq)]
    # Along the pipe arrows: upstream end first, then toward the outlet.
    cvs = _order_along_flow(ctx, cvs, eq) if cvs else []
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
    level_high_rows, level_low_rows = [], []
    for item in cvs:
        # Flare / vent / drain / root valves are not steady-state process deviation causes.
        if _skip_deviation_cause(ctx, item):
            continue
        name = item["tag"]
        if name.upper() in done_cvs:
            continue
        done_cvs.add(name.upper())
        cv_var = str(item.get("letters") or "")[:1]
        drum = _downstream_drum(ctx, item.get("box")) or eq
        drum_name = _equip_name(drum, tag)
        if cv_var == "L":
            # LV purpose is level control on the liquid outlet — not a flow deviation.
            level_eq = _level_vessel_for(ctx, item, eq if kind in ("vessel", "tank") else drum)
            closed_sg = trip_safeguards(ctx, "L", "H", level_eq)
            open_sg = trip_safeguards(ctx, "L", "L", level_eq)
            level_high_rows.append(row(
                _cause_ltr(ctx, item.get("box"), name, f"{name} fails closed."),
                [_lv_closed_consequence(ctx, item, level_eq)],
                "S", closed_sg, 4, 3,
                [] if _has_strong(closed_sg) else [ctx.recs.add(
                    f"Provide an independent high-high level trip (LSHH) on {_equip_name(level_eq, tag)}.")]))
            level_low_rows.append(row(
                _cause_ltr(ctx, item.get("box"), name, f"{name} fails open."),
                [_lv_open_consequence(ctx, item, level_eq)],
                "S", open_sg, 5, 3,
                [] if _has_strong(open_sg) else [ctx.recs.add(
                    f"Provide an independent low-low level trip (LSLL) on {_equip_name(level_eq, tag)} "
                    f"to stop gas blow-through.")]))
            continue
        purpose = _cv_purpose(ctx, item, eq)
        if cv_var == "P":
            closed_sg = trip_safeguards(ctx, "P", "L", eq)
            open_sg = relief_safeguards(ctx, drum) + trip_safeguards(ctx, "P", "H", drum)
            closed_effect = _with_valve_purpose(
                ctx, item,
                f"{name} fails closed, flow of {ctx.fluid} through {tag} stops",
                purpose)
            open_effect = _with_valve_purpose(
                ctx, item,
                f"{name} fails open, pressure letdown is lost. "
                + _overpressure_effect(ctx, drum or drum_name, eq).rstrip("."),
                purpose)
        elif kind == "heater":
            duty = f" ({d['duty_mmbtu_hr']} MMBtu/hr)" if d.get("duty_mmbtu_hr") else ""
            closed_sg = trip_safeguards(ctx, "P", "L", eq)
            open_sg = trip_safeguards(ctx, "T", "L", eq)
            closed_effect = _with_valve_purpose(
                ctx, item,
                f"{name} fails closed, flow of {ctx.fluid} through {tag} stops while the heater can stay energised",
                purpose)
            open_effect = _with_valve_purpose(
                ctx, item,
                f"{name} fails open, flow exceeds the heating capacity of {tag}{duty}. "
                f"The outlet stays colder than intended and hydrate formation can follow",
                purpose)
        else:
            closed_sg = trip_safeguards(ctx, "P", "L", eq)
            open_sg = trip_safeguards(ctx, "P", "L", eq)
            closed_effect = _with_valve_purpose(
                ctx, item,
                f"{name} fails closed, flow of {ctx.fluid} through {tag} stops",
                purpose)
            open_effect = _with_valve_purpose(
                ctx, item,
                f"{name} fails open, flow through {tag} rises above the intended rate",
                purpose)
        closed_rows.append(row(
            _cause_ltr(ctx, item.get("box"), name, f"{name} fails closed."),
            [_cons_related(ctx, item.get("box"), tag, closed_effect.rstrip("."))],
            "S" if kind == "heater" else "A", closed_sg, 4 if kind == "heater" else 3, 3))
        open_rows.append(row(
            _cause_ltr(ctx, item.get("box"), name, f"{name} fails open."),
            [_cons_related(ctx, item.get("box"), tag, open_effect.rstrip("."))],
            "S" if kind == "heater" or cv_var == "P" else "A", open_sg, 4 if cv_var == "P" else 3, 2))
    rec_flow = []
    if kind in ("heater", "pump", "compressor") and not _has_strong(flow_trips) and not _has_strong(supply_sg):
        panel = next((e["tag"] for e in ctx.equipment if e["kind"] == "panel"), f"the {label} control system")
        rec_flow.append(ctx.recs.add(
            f"Confirm that {panel} includes a low-flow / flow-proving permissive that trips {tag} on loss of flow; "
            f"if not, provide a low-low flow trip (FSLL)."))
    flow_rows = [
        row(_cause_ltr(ctx, eq.get("box"), tag, "Loss of supply."),
            [_cons_related(ctx, eq.get("box"), tag, no_flow_cons.rstrip(".")),
             _cons_related(ctx, eq.get("box"), tag, f"Loss of {ctx.fluid} supply downstream of {tag}")],
            "S" if kind in ("heater", "pump", "compressor") else "A", supply_sg, 4 if kind == "heater" else 3, 3, rec_flow),
        *closed_rows,
    ]
    if flow_rows:
        devs.append(dev("No / Less Flow", flow_rows))
    if open_rows:
        devs.append(dev("More Flow", open_rows))
    if level_high_rows:
        devs.append(dev("High Level", level_high_rows))
    if level_low_rows:
        devs.append(dev("Low Level", level_low_rows))

    # ---- reverse flow: check / FSV stuck open or pressure reversal — never normally open valves
    checks_on_eq = [c for c in _process_check_devices(ctx, eq) if not _is_normally_open(c)]
    rev_rows = []
    for check in _reading_order(checks_on_eq):
        ctag = _valve_label(ctx, check)
        cause = _cause_ltr(ctx, check.get("box"), _check_tag(check), f"{ctag} sticks open (fails to seat).")
        if not _reverse_flow_cause_ok(ctx, cause):
            continue
        rev_rows.append(row(
            cause,
            [_check_stuck_open_consequence(ctx, check)],
            "S",
            relief_safeguards(ctx, eq) + trip_safeguards(ctx, "P", "H", eq),
            4, 2,
        ))
    rev_rows.append(row(
        _cause_ltr(ctx, eq.get("box"), tag, "Loss of upstream pressure while downstream stays pressurized."),
        [_cons_related(ctx, eq.get("box"), tag, f"Backflow of {ctx.fluid} through {tag} toward the upstream side")],
        "A", check_safeguards(ctx, eq), 3, 2,
        [] if check_safeguards(ctx, eq) else [ctx.recs.add(
            f"Provide a check valve on the outlet of {tag} to prevent reverse flow.")]))
    if len(ctx.sources) >= 2 and not checks_on_eq:
        # One imbalance scenario — do not list normally open isolation valves as causes.
        names = " and ".join(c["description"] + (f" ({c['line']})" if c["line"] else "") for c in ctx.sources)
        checks = check_safeguards(ctx, eq)
        if checks:
            cause = f"One inlet check valve fails open while the sources {names} are at different pressures."
            cons = [
                "Higher-pressure source backflows into the lower-pressure source; "
                "possible overpressure / contamination of upstream equipment."
            ]
            safeguards = checks
            recs = []
        else:
            cause = (
                f"Pressure imbalance between inlet sources {names}; "
                f"the sources join with no check valves shown on this P&ID."
            )
            cons = [
                "Higher-pressure source backflows into the lower-pressure source; "
                "possible overpressure / contamination of upstream equipment."
            ]
            safeguards = []
            recs = [ctx.recs.add(
                f"Verify on upstream drawings that check valves are provided on each incoming line ({names}) and that "
                f"each source is rated for the maximum pressure of the other.")]
        if _reverse_flow_cause_ok(ctx, cause):
            rev_rows.append(row(cause, cons, "S", safeguards, 4, 2, recs))
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
        up = _nearest_large(ctx, eq.get("box"), -1)
        hp_rows.append(row(
            _cause_ltr(ctx, eq.get("box"), tag,
                       f"High supply pressure. Piping spec {spec['spec']} is rated {spec['rating_psig']} psig but {tag} design pressure is {p_des} psig."),
            [_cons_related(ctx, eq.get("box"), tag, _overpressure_effect(ctx, eq, up))],
            "S", psv + trip_safeguards(ctx, "P", "H", eq), 5, 3, recs_))
    else:
        up = _nearest_large(ctx, eq.get("box"), -1)
        hp_rows.append(row(
            _cause_ltr(ctx, eq.get("box"), tag, "High supply pressure."),
            [_cons_related(ctx, eq.get("box"), tag, _overpressure_effect(ctx, eq, up))],
            "S", psv + trip_safeguards(ctx, "P", "H", eq), sev_loc, 2,
            [] if psv_items else [ctx.recs.add(f"Confirm overpressure protection of {tag} for the maximum upstream source pressure.")]))
    hp_rows.append(row(
        _blocked_outlet_cause(ctx, eq, heater=(kind == "heater")),
        [_cons_related(ctx, eq.get("box"), tag, _overpressure_effect(ctx, eq))],
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

    # ---- level (vessels / tanks). LV rows already cover fail closed / open when an LV is on this vessel.
    if kind in ("vessel", "tank") and not level_high_rows:
        lsh = trip_safeguards(ctx, "L", "H", eq)
        lsl = trip_safeguards(ctx, "L", "L", eq)
        lv = next((item for item in cvs if str(item.get("letters") or "")[:1] == "L"), None)
        if lv:
            high_cause = _cause_ltr(ctx, lv.get("box"), lv["tag"], f"{lv['tag']} fails closed.")
            high_cons = [_lv_closed_consequence(ctx, lv, eq)]
            low_cause = _cause_ltr(ctx, lv.get("box"), lv["tag"], f"{lv['tag']} fails open.")
            low_cons = [_lv_open_consequence(ctx, lv, eq)]
        else:
            high_cause = _cause_ltr(ctx, eq.get("box"), tag, f"The liquid outlet of {tag} is blocked.")
            high_cons = [
                f"Liquid cannot leave {tag}. The level rises and liquid carries over into the vapour outlet. "
                f"Downstream gas users can see liquid."
            ]
            low_cause = _cause_ltr(ctx, eq.get("box"), tag, f"The liquid outlet of {tag} fails open or is left open.")
            low_cons = [
                f"Liquid leaves {tag}, the liquid seal is lost, and gas blows through the liquid outlet."
            ]
        devs.append(dev("High Level", [row(
            high_cause, high_cons, "S", lsh, 4, 3,
            [] if _has_strong(lsh) else [ctx.recs.add(f"Provide an independent high-high level trip (LSHH) on {tag}.")])]))
        devs.append(dev("Low Level", [row(
            low_cause, low_cons, "S", lsl, 5, 3,
            [] if _has_strong(lsl) else [ctx.recs.add(
                f"Provide an independent low-low level trip (LSLL) on {tag} to prevent gas blow-by.")])]))

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
        vessel = _level_vessel_for(ctx, cv, vessel)
        loss_sg = trip_safeguards(ctx, "L", "H", vessel)
        open_sg = trip_safeguards(ctx, "L", "L", vessel)
        vessel_name = _equip_name(vessel, up_name)
        devs.append(dev("High Level", [
            row(_cause_ltr(ctx, cv.get("box"), tag, f"{tag} fails closed."),
                [_lv_closed_consequence(ctx, cv, vessel)],
                "S", loss_sg, 4, 3,
                [] if _has_strong(loss_sg) else [ctx.recs.add(
                    f"Provide an independent high-high level trip (LSHH) on {vessel_name}.")]),
            row(_cause_ltr(ctx, cv.get("box"), tag, _isolation_cause(ctx, cv.get("box"), tag)),
                [f"Isolation on the liquid outlet of {vessel_name} blocks liquid leaving. "
                 f"The level rises and liquid carries over into the vapour outlet. Downstream gas users can see liquid."],
                "S", loss_sg, 4, 2),
        ]))
        devs.append(dev("Low Level", [
            row(_cause_ltr(ctx, cv.get("box"), tag, f"{tag} fails open."),
                [_lv_open_consequence(ctx, cv, vessel)],
                "S", open_sg, 5, 3,
                [] if _has_strong(open_sg) else [ctx.recs.add(
                    f"Provide an independent low-low level trip (LSLL) on {vessel_name} to stop gas blow-through.")]),
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

        down_eq = _nearest_large(ctx, cv.get("box"), 1) or drum
        up_eq = _nearest_large(ctx, cv.get("box"), -1)
        pressure_cons = _overpressure_effect(ctx, down_eq or down_name, up_eq or heater)
        hp_cons = [f"Letdown between {up_name} and {down_name} is lost. {pressure_cons}"]
        down = [l for l in ctx.process_lines if any(l["tag"] == c["line"] for c in ctx.dests)]
        if down and up_pmax and down[0].get("rating_psig"):
            if down[0]["rating_psig"] >= up_pmax:
                hp_cons.append(f"Outlet piping {down[0]['tag']} ({down[0]['rating']}) is rated above the upstream design pressure.")
            else:
                hp_cons.append(f"Outlet piping {down[0]['tag']} ({down[0]['rating']}, {down[0]['rating_psig']} psig) can be overpressured.")
        if heater:
            hp_cons.append(f"Flow through {heater['tag']} rises above its heating capacity and the outlet gas stays cold.")
        more_rows = [row(
            _cause_ltr(ctx, cv.get("box"), tag, f"{tag} fails open."),
            [_cons_related(
                ctx, cv.get("box"), tag,
                _with_valve_purpose(
                    ctx, cv,
                    f"{tag} fails open, letdown between {up_name} and {down_name} is lost. {pressure_cons}",
                    _cv_purpose(ctx, cv)).rstrip("."))],
            "S", open_sg, 5, 3)]
        if bypass:
            more_rows.append(row(
                f"{tag} bypass globe valve {ctx.names(bypass[:1])} opened in error or left open after maintenance.",
                [f"Flow bypasses {tag}. {pressure_cons} The rise is slower than with {tag} fully open."], "S",
                open_sg, 4, 2,
                [ctx.recs.add(f"Lock closed the {tag} bypass valve {ctx.names(bypass[:1])} and include it in the lock register.")]))
        # High pressure from a blocked outlet names the particular valve that closes.
        block_eq = drum or down_eq or {"tag": down_name, "box": cv.get("box"), "design": down_des}
        more_rows.append(row(
            _blocked_outlet_cause(ctx, block_eq if isinstance(block_eq, dict) else {"tag": down_name, "box": cv.get("box")}),
            [_cons_related(ctx, cv.get("box"), tag, pressure_cons)], "S", open_sg, 5, 2))
        devs.append(dev("More Flow / High Pressure", more_rows))

    rev_cv_rows = []
    for check in _reading_order(
            [c for c in _process_check_devices(ctx, drum) if not _is_normally_open(c)]):
        ctag = _valve_label(ctx, check)
        cause = _cause_ltr(ctx, check.get("box"), _check_tag(check), f"{ctag} sticks open (fails to seat).")
        if not _reverse_flow_cause_ok(ctx, cause):
            continue
        rev_cv_rows.append(row(
            cause,
            [_check_stuck_open_consequence(ctx, check)],
            "S",
            relief_safeguards(ctx, drum) + trip_safeguards(ctx, "P", "H", drum),
            4, 2,
        ))
    rev_cv_rows.append(row(
        _cause_ltr(ctx, cv.get("box"), tag, "Loss of upstream pressure while downstream stays pressurized."),
        [_cons_related(ctx, cv.get("box"), tag, f"Backflow through {tag} toward the upstream side")], "A",
        check_safeguards(ctx, drum), 3, 2,
        [] if check_safeguards(ctx, drum) else [ctx.recs.add(
            f"Provide a check valve so {tag} cannot pass reverse flow.")]))
    devs.append(dev("Reverse Flow", rev_cv_rows))
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
    """Combine anchors of one node. Same device failure is kept once (first along the flow)."""
    if len(parts) == 1:
        part = parts[0]
        for group in part.get("deviations") or []:
            group["rows"] = _unique_cause_rows(group.get("rows"))
        return part
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
        "deviations": [{"deviation": name, "rows": _unique_cause_rows(rows)} for name, rows in devs.items()],
    }


def _build(ctx, ext, entry, nid):
    """Walk the node from the upstream end to the downstream end; each valve is written once."""
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
    # Node description follows only these indicated process lines — not trim or every nearby hook-up.
    ctx.node_line_tags = {str(l.get("tag") or "").upper() for l in lines if l.get("tag")}
    if not ctx.node_line_tags and tags:
        ctx.node_line_tags = {t for t in tags if any(str(l.get("tag") or "").upper() == t for l in ctx.process_lines)}

    # Method: upstream end → downstream end. Equipment first in flow order, then any CV not yet written.
    target = next((e for e in eqs if e.get("kind") in ("vessel", "tank")), None) or (eqs[-1] if eqs else None)
    ordered_eqs = _order_along_flow(ctx, eqs, target) if eqs else []
    done_cvs = set()
    parts = []
    for eq in ordered_eqs:
        parts.append(equipment_node(ctx, eq, nid, done_cvs=done_cvs))
    ordered_cvs = _order_along_flow(ctx, cvs, target) if cvs else []
    for cv in ordered_cvs:
        tag = str(cv.get("tag") or "").upper()
        if not tag or tag in done_cvs:
            continue
        done_cvs.add(tag)
        parts.append(control_valve_node(ctx, [cv], nid, heater))
    if relief:
        protected = ordered_eqs[0]["tag"] if ordered_eqs else (main_eq[0]["tag"] if main_eq else None)
        parts.append(relief_node(ctx, nid, protected))
    if not parts:
        anchor = lines[0]["tag"] if lines else (entry.get("title") or next(iter(sorted(tags)), f"Node {nid}"))
        fake = {"tag": anchor, "kind": "equipment", "description": "process piping" if lines else "",
                "design": {}, "electric": False}
        node = equipment_node(ctx, fake, nid, done_cvs=done_cvs)
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
    _dedupe_worksheet(nodes)
    _scrub_cause_cross_refs(nodes)
    _scrub_reverse_flow(nodes)
    if source == "color":
        note = (f"The drawing was studied one node at a time ({len(pieces)} colour-marked nodes). "
                "Each colour was followed from its start to its end, including the piping, instruments and valves on it.")
    else:
        note = (f"The drawing was split into {len(pieces)} parts. Each part was studied on its own, "
                "then the parts were compiled into this worksheet.")
    return {"study": study, "nodes": nodes, "recommendations": recs, "assumptions": [note, *assumptions],
            "node_source": source}


def _worksheet(ext, study, plan, source, dedupe=True):
    ctx = Ctx(ext)
    ctx.line_relation = list((study or {}).get("line_relation") or ext.get("line_relation") or [])
    ctx.pfd_conditions = dict((study or {}).get("pfd_conditions") or ext.get("pfd_conditions") or {})
    ctx.pfd_system_purpose = str((study or {}).get("system_purpose") or ext.get("system_purpose") or "")
    ctx.pfd_equipment_purposes = list(
        (study or {}).get("equipment_purposes") or ext.get("equipment_purposes") or []
    )
    ctx.stream_line_map = list(
        (study or {}).get("stream_line_map") or ext.get("stream_line_map") or []
    )
    ctx.line_operating = dict(
        (study or {}).get("line_operating") or ext.get("line_operating") or {}
    )
    ctx.equipment_operating = dict(
        (study or {}).get("equipment_operating") or ext.get("equipment_operating") or {}
    )
    ctx.line_design = dict(
        (study or {}).get("line_design") or ext.get("line_design") or {}
    )
    ctx.non_steady_segments = list(
        (study or {}).get("non_steady_segments") or ext.get("non_steady_segments") or []
    )
    ctx.non_steady_by_role = dict(
        (study or {}).get("non_steady_by_role") or ext.get("non_steady_by_role") or {}
    )
    ctx.nc_isolation_valves = list(
        (study or {}).get("nc_isolation_valves") or ext.get("nc_isolation_valves") or []
    )
    if not ctx.pfd_conditions and ctx.equipment_operating:
        ctx.pfd_conditions = dict(ctx.equipment_operating)
    # Prefer Step 5 classification when lines were stamped during extract.
    if ctx.non_steady_segments and not ctx.off_process_lines:
        off_tags = {item.get("tag") for item in ctx.non_steady_segments if item.get("tag")}
        ctx.off_process_lines = [l for l in ctx.lines if l.get("tag") in off_tags or l.get("steady_state") is False]
        ctx.process_lines = [l for l in ctx.lines if l not in ctx.off_process_lines]
        ctx.flare_lines = [
            l for l in ctx.off_process_lines
            if (l.get("off_process_role") == "flare")
            or str(l.get("service") or "").upper() in ("FL", "SV", "BD", "VG")
        ]
    # Apply Step 4 design limits onto lines that still lack rating / material.
    for line in ctx.lines:
        tag = str(line.get("tag") or "").strip()
        design = ctx.line_design.get(tag) or {}
        if not design:
            continue
        for key in ("rating", "rating_psig", "min_temp_f", "max_temp_f", "material"):
            if design.get(key) is not None and line.get(key) is None:
                line[key] = design[key]
        if design.get("sour_service") is not None and line.get("sour") is None:
            line["sour"] = design["sour_service"]
        if design.get("spec_known") is not None:
            line["spec_known"] = design["spec_known"]
        line.setdefault("design", design)
    # Prefer stream_line_map when line_relation was not copied onto the study yet.
    if not ctx.line_relation and ctx.stream_line_map:
        ctx.line_relation = [
            {
                "pfd_stream": item.get("pfd_stream"),
                "pid_line": item.get("pid_line"),
                "pfd_from": item.get("pfd_from"),
                "pfd_to": item.get("pfd_to"),
                "pid_service": item.get("pid_service"),
                "why": item.get("why"),
            }
            for item in ctx.stream_line_map
            if item.get("matched")
        ]
    ctx.upstream_side = _upstream_side(ctx)
    main_eq = _main_equipment(ext)
    nodes = [_build(ctx, ext, entry, i) for i, entry in enumerate(plan, 1)]

    for n in nodes:
        for i, d in enumerate(n["deviations"], 1):
            d["deviation"] = f"{n['id']}.{i} {d['deviation']}"
    if dedupe:
        _dedupe_worksheet(nodes)
    _scrub_cause_cross_refs(nodes)
    _scrub_reverse_flow(nodes, ctx)

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
    from . import sequence as hazop_sequence

    step1 = hazop_sequence.STEPS[0]["rule"]
    step2 = hazop_sequence.STEPS[1]["rule"]
    step1_done = (
        f"Sequence step 1 — {step1} "
        + (
            f"System purpose: {(ctx.pfd_system_purpose or '')[:180]} "
            f"Purpose recorded for {len(ctx.pfd_equipment_purposes)} equipment / component(s)."
            if ctx.pfd_system_purpose or ctx.pfd_equipment_purposes
            else "No PFD was available for this run; purpose was taken from the P&ID alone."
        )
    )
    matched = [item for item in (ctx.stream_line_map or []) if item.get("matched")]
    if matched:
        pairs = "; ".join(
            f"PFD stream {item['pfd_stream']} = P&ID line {item['pid_line']}"
            for item in matched[:6]
        )
        more = f" (+{len(matched) - 6} more)" if len(matched) > 6 else ""
        step2_done = f"Sequence step 2 — {step2} Matched: {pairs}{more}."
    elif ctx.line_relation:
        linked = [m for m in ctx.line_relation if m.get("pid_line")]
        step2_done = (
            f"Sequence step 2 — {step2} "
            f"{len(linked)} PFD stream(s) were matched to P&ID line numbers."
        )
    else:
        step2_done = (
            f"Sequence step 2 — {step2} "
            "No PFD–P&ID stream/line pairs were available for this run."
        )
    step3 = hazop_sequence.STEPS[2]["rule"]
    n_line_ops = len(ctx.line_operating or {})
    n_eq_ops = len(ctx.equipment_operating or {})
    if n_line_ops or n_eq_ops:
        step3_done = (
            f"Sequence step 3 — {step3} "
            f"Operating parameters assigned for {n_line_ops} line(s) and {n_eq_ops} equipment item(s) "
            "from the PFD stream map."
        )
    else:
        step3_done = (
            f"Sequence step 3 — {step3} "
            "No mapped operating parameters were available; P&ID design blocks were used where shown."
        )
    step4 = hazop_sequence.STEPS[3]["rule"]
    n_design = len(ctx.line_design or {})
    n_known = sum(1 for d in (ctx.line_design or {}).values() if d.get("spec_known"))
    if n_design:
        step4_done = (
            f"Sequence step 4 — {step4} "
            f"Design parameters set for {n_design} piping segment(s) "
            f"({n_known} matched to the uploaded piping specification)."
        )
    else:
        step4_done = (
            f"Sequence step 4 — {step4} "
            "No piping segments were designed from the piping specification for this run."
        )
    step5 = hazop_sequence.STEPS[4]["rule"]
    if ctx.non_steady_segments:
        role_bits = []
        for role in ("drain", "bypass", "vent", "flare"):
            tags = (ctx.non_steady_by_role or {}).get(role) or []
            if tags:
                role_bits.append(f"{role}={len(tags)}")
        step5_done = (
            f"Sequence step 5 — {step5} "
            f"Identified {len(ctx.non_steady_segments)} non-steady-state segment(s)"
            + (f" ({', '.join(role_bits)})" if role_bits else "")
            + f"; {len(ctx.nc_isolation_valves or [])} normally closed isolation link(s). "
            "These are not used as steady-state process deviation causes."
        )
    else:
        step5_done = (
            f"Sequence step 5 — {step5} "
            "No drain / bypass / vent / flare segments were flagged on this run."
        )
    assumptions = [
        "Worksheet generated automatically by the rule-based engine from text recognised on the P&ID; review by a HAZOP team is required.",
        step1_done,
        step2_done,
        step3_done,
        step4_done,
        step5_done,
        ranking,
        "CC (Consequence Category): S = Safety / People, E = Environment, A = Asset / Production.",
        "Drain lines, vent lines, flare lines and lines to safety valves are left out of the node description. "
        "Valves on those branches are not live in steady-state operation, so closing them is not written as the "
        "same deviation as closing a valve on the main process supply or outlet.",
        "The node description follows only the indicated process piping for that node. "
        "Equipment and instrument trim on the drawing are not treated as the node line itself.",
        "Piping components on flare, drain or vent lines, and instrument root valves, are not used as causes "
        "for process deviations (including FSV / check valves on those branches).",
        "Every valve std / code used as a cause is written with the line number it sits on, so its location is known.",
        "Normally open valves (NO / LO / CSO) are not used as causes under Reverse Flow. "
        "Reverse flow causes are a check / FSV stuck open, or loss of upstream pressure / source pressure imbalance.",
        "The node description is a summary of the process route. Design intent is the overall purpose of the node. "
        "Design conditions are the design and operating pressure and temperature of the main equipment, read from the P&ID. "
        "Each cause names the instrument that fails, the consequence names the equipment that sees it, and the safeguard names the device that stops it. "
        "Flow follows the arrows drawn on each pipe (not a left-to-right guess). "
        "If HAP feeds a scrubber, the arrow between them makes HAP upstream. "
        "Consequences use the operating and design pressures from the P&ID and the PFD. "
        "A repeated consequence may point back to the first place it was written. "
        "The cause column never refers to another cause or consequence; a repeated cause is omitted.",
    ]
    arrowed = sum(1 for line in ctx.process_lines if line.get("flow_from") == "arrow")
    if arrowed:
        assumptions.append(
            f"Flow direction was taken from the arrows drawn on {arrowed} process line(s) on this P&ID."
        )
    elif any(line.get("flow") for line in ctx.process_lines):
        assumptions.append(
            "Flow direction was taken from the FROM / TO connectors where no pipe arrow was read."
        )
    if ctx.pfd_conditions:
        assumptions.append(
            f"Operating pressure and temperature for {len(ctx.pfd_conditions)} equipment item(s) "
            "were taken from the PFD heat and material balance."
        )
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
