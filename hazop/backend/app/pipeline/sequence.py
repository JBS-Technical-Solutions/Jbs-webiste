"""Ordered rules the engine follows when preparing a HAZOP worksheet.

Each step is applied in order. Later steps must not skip or replace an earlier step.
"""

import re

# Steps are applied in order. Later steps must not skip or replace an earlier step.
STEPS = [
    {
        "id": 1,
        "title": "Read the PFD",
        "rule": (
            "Read the PFD and understand the purpose of the system as well as "
            "all the equipment and components."
        ),
    },
    {
        "id": 2,
        "title": "Read the P&ID and compare with the PFD",
        "rule": (
            "Read the P&ID and compare it with the PFD so that the engine understands "
            "which stream in the PFD corresponds to which line number in the P&ID."
        ),
    },
    {
        "id": 3,
        "title": "Assign operating parameters from the mapping",
        "rule": (
            "Based on the above mapping, the engine will design the operating parameters "
            "for each line and each equipment in the P&ID."
        ),
    },
    {
        "id": 4,
        "title": "Read the piping specification for each P&ID segment",
        "rule": (
            "P&ID will read the piping spec and determine the design parameters "
            "for each piping segment."
        ),
    },
    {
        "id": 5,
        "title": "Identify non-steady-state piping",
        "rule": (
            "Identify the drain, bypass, vent and flare line which are typically not used "
            "during the steady state operation. These piping segments are isolated through "
            "normally closed valves."
        ),
    },
]

_OFF_PROCESS_SERVICES = {"DW", "DH", "VG", "SV", "FL", "BD"}
_NORMALLY_CLOSED_ATTRS = {"NC", "CSC", "LC"}
_ROLE_WORDS = {
    "flare": ("flare", "blowdown", "blow down", "safety valve", "to flare"),
    "vent": ("vent", "to vent", "vent gas"),
    "drain": ("drain", "closed drain", "open drain"),
    "bypass": ("bypass", "by-pass", "by pass"),
}


def step(number):
    for item in STEPS:
        if item["id"] == number:
            return item
    return None


def system_purpose(study):
    """One statement of what the process system is for, from the PFD reading."""
    study = study or {}
    flow = (study.get("process_flow") or "").strip()
    equipment = study.get("equipment") or study.get("route") or []
    names = []
    for item in equipment:
        tag = item.get("tag") or ""
        name = item.get("name") or item.get("kind") or "equipment"
        used = item.get("used_for") or ""
        if tag:
            names.append(f"{tag} ({name})" + (f", {used}" if used else ""))
        elif name:
            names.append(name + (f", {used}" if used else ""))
    if flow and names:
        listed = "; ".join(names[:8])
        more = f" and {len(names) - 8} more" if len(names) > 8 else ""
        return (
            f"{flow.rstrip('.')} "
            f"The PFD equipment and its purpose: {listed}{more}."
        )
    if flow:
        return flow if flow.endswith(".") else flow + "."
    if names:
        listed = "; ".join(names[:8])
        more = f" and {len(names) - 8} more" if len(names) > 8 else ""
        return f"The PFD shows this process system through: {listed}{more}."
    return ""


def equipment_purposes(study):
    """Purpose of every equipment / component step learned from the PFD."""
    out = []
    for item in (study or {}).get("equipment") or (study or {}).get("route") or []:
        tag = item.get("tag") or ""
        name = item.get("name") or item.get("kind") or "equipment"
        what = item.get("what") or ""
        used_for = item.get("used_for") or ""
        work = item.get("work") or item.get("doing") or ""
        purpose = used_for or work or what
        if not purpose:
            continue
        label = f"{tag} ({name})" if tag else name
        out.append({
            "tag": tag,
            "name": name,
            "what": what,
            "used_for": used_for,
            "work": work,
            "purpose": f"{label} is {what + ', ' if what else ''}{purpose}.".replace(" is , ", " is "),
        })
    return out


def apply_step1(study):
    """Attach system and equipment purpose from the PFD before any P&ID worksheet work."""
    study = dict(study or {})
    study["system_purpose"] = system_purpose(study)
    study["equipment_purposes"] = equipment_purposes(study)
    study["sequence_step"] = 1
    study["sequence_rule"] = STEPS[0]["rule"]
    return study


def step1_note(study):
    """Status text once step 1 is done."""
    rule = STEPS[0]["rule"]
    system = (study or {}).get("system_purpose") or ""
    n = len((study or {}).get("equipment_purposes") or [])
    if system and n:
        return (
            f"Step 1 done — {rule} "
            f"System purpose understood. Purpose recorded for {n} equipment / component(s). "
            f"{system[:220]}"
        )
    if system:
        return f"Step 1 done — {rule} {system[:240]}"
    return f"Step 1 — {rule}"


def _stream_line_map(matches):
    """PFD stream → P&ID line number map the worksheet uses for consequences."""
    mapping = []
    for match in matches or []:
        stream = str(match.get("pfd_stream") or "").strip()
        line = str(match.get("pid_line") or "").strip()
        if not stream:
            continue
        mapping.append({
            "pfd_stream": stream,
            "pid_line": line,
            "pfd_from": match.get("pfd_from") or "",
            "pfd_to": match.get("pfd_to") or "",
            "pid_service": match.get("pid_service") or "",
            "why": match.get("why") or "",
            "matched": bool(line),
        })
    return mapping


def apply_step2(study, relate_result):
    """Attach PFD-stream ↔ P&ID-line comparison after the P&ID has been read."""
    study = dict(study or {})
    relate_result = relate_result or {}
    matches = list(relate_result.get("matches") or study.get("line_relation") or [])
    study["line_relation"] = matches
    study["stream_line_map"] = _stream_line_map(matches)
    study["relation_note"] = relate_result.get("note") or study.get("relation_note") or ""
    linked = sum(1 for item in study["stream_line_map"] if item.get("matched"))
    study["streams_matched"] = linked
    study["streams_compared"] = len(study["stream_line_map"])
    study["sequence_step"] = 2
    study["sequence_rule"] = STEPS[1]["rule"]
    return study


def step2_note(study):
    """Status text once step 2 is done."""
    rule = STEPS[1]["rule"]
    study = study or {}
    linked = study.get("streams_matched")
    total = study.get("streams_compared")
    if linked is None or total is None:
        mapping = study.get("stream_line_map") or []
        total = len(mapping)
        linked = sum(1 for item in mapping if item.get("matched"))
    if total:
        pairs = []
        for item in (study.get("stream_line_map") or [])[:6]:
            if not item.get("matched"):
                continue
            pairs.append(f"PFD stream {item['pfd_stream']} → P&ID line {item['pid_line']}")
        shown = "; ".join(pairs)
        more = f" (+{linked - len(pairs)} more)" if linked > len(pairs) else ""
        detail = f" Matched {linked} of {total} PFD stream(s) to P&ID line numbers."
        if shown:
            detail += f" {shown}{more}."
        return f"Step 2 done — {rule}{detail}"
    note = (study.get("relation_note") or "").strip()
    if note:
        return f"Step 2 done — {rule} {note[:220]}"
    return f"Step 2 — {rule}"


def _stream_data(study, stream_no):
    """Heat-and-material-balance row for one PFD stream number."""
    streams = ((study or {}).get("balance") or {}).get("streams") or {}
    if stream_no in streams:
        return streams[stream_no]
    key = str(stream_no or "").strip()
    return streams.get(key) or streams.get(key.upper()) or streams.get(key.lower()) or {}


def _op_from_stream(data, stream_no):
    """Operating P/T carried by one PFD stream."""
    if not data:
        return {}
    out = {"pfd_stream": str(stream_no)}
    if data.get("pressure") is not None:
        out["p_op"] = data["pressure"]
    if data.get("temperature") is not None:
        out["t_op"] = data["temperature"]
    if data.get("molar_flow") is not None:
        out["molar_flow"] = data["molar_flow"]
    if data.get("mass_flow") is not None:
        out["mass_flow"] = data["mass_flow"]
    if data.get("vapour_fraction") is not None:
        out["vapour_fraction"] = data["vapour_fraction"]
    return out if ("p_op" in out or "t_op" in out) else {}


def _tag_in_text(text):
    match = re.search(r"\b([A-Z]{1,5}-\d{3,5}[A-Z0-9]*)\b", str(text or "").upper())
    return match.group(1) if match else ""


def apply_step3(study, sheets=None):
    """Assign operating parameters to each P&ID line and equipment from the Step 2 mapping."""
    study = dict(study or {})
    # Ensure equipment_conditions exist for tag-based fill.
    if not study.get("equipment_conditions"):
        from . import pfd as pfd_mod
        study["equipment_conditions"] = pfd_mod.equipment_conditions(study)

    line_ops = {}
    for item in study.get("stream_line_map") or []:
        if not item.get("matched"):
            continue
        line = str(item.get("pid_line") or "").strip()
        stream = item.get("pfd_stream")
        if not line or not stream:
            continue
        ops = _op_from_stream(_stream_data(study, stream), stream)
        if not ops:
            continue
        ops = {
            **ops,
            "pfd_from": item.get("pfd_from") or "",
            "pfd_to": item.get("pfd_to") or "",
            "source": "pfd_stream_map",
        }
        # Prefer a stream that has both P and T when several map to one line.
        have = line_ops.get(line) or {}
        if not have or (ops.get("p_op") is not None and ops.get("t_op") is not None and not (
                have.get("p_op") is not None and have.get("t_op") is not None)):
            line_ops[line] = ops

    equip_ops = {}
    # Start from PFD equipment conditions (by tag).
    for tag, cond in (study.get("equipment_conditions") or {}).items():
        tag_u = str(tag or "").upper()
        if not tag_u:
            continue
        entry = {"source": "pfd_equipment", **{k: v for k, v in cond.items() if v is not None}}
        if entry.get("p_op") is not None or entry.get("t_op") is not None:
            equip_ops[tag_u] = entry

    # Enrich equipment from mapped lines that arrive at / leave that tag.
    for item in study.get("stream_line_map") or []:
        if not item.get("matched"):
            continue
        stream = item.get("pfd_stream")
        ops = _op_from_stream(_stream_data(study, stream), stream)
        if not ops:
            continue
        for place in (item.get("pfd_from"), item.get("pfd_to")):
            tag_u = _tag_in_text(place)
            if not tag_u:
                continue
            have = equip_ops.get(tag_u) or {"source": "pfd_stream_map"}
            if ops.get("p_op") is not None and have.get("p_op") is None:
                have["p_op"] = ops["p_op"]
                have["p_stream"] = str(stream)
            if ops.get("t_op") is not None and have.get("t_op") is None:
                have["t_op"] = ops["t_op"]
                have["t_stream"] = str(stream)
            if have.get("p_op") is not None or have.get("t_op") is not None:
                equip_ops[tag_u] = have

    # Optional: stamp the live P&ID extraction so later worksheet steps see the values.
    for page, ext in sheets or []:
        for line in ext.get("lines") or []:
            tag = str(line.get("tag") or "").strip()
            ops = line_ops.get(tag)
            if not ops:
                continue
            if ops.get("p_op") is not None:
                line["p_op"] = ops["p_op"]
            if ops.get("t_op") is not None:
                line["t_op"] = ops["t_op"]
            line["pfd_stream"] = ops.get("pfd_stream")
        for eq in ext.get("equipment") or []:
            tag_u = str(eq.get("tag") or "").upper()
            ops = equip_ops.get(tag_u)
            if not ops:
                continue
            design = eq.setdefault("design", {})
            if ops.get("p_op") is not None and design.get("p_op") is None:
                design["p_op"] = ops["p_op"]
                design["p_op_source"] = "pfd"
            if ops.get("t_op") is not None and design.get("t_op") is None:
                design["t_op"] = ops["t_op"]
                design["t_op_source"] = "pfd"

    study["line_operating"] = line_ops
    study["equipment_operating"] = equip_ops
    # Keep pfd_conditions as the equipment map the worksheet already consumes.
    merged = dict(study.get("equipment_conditions") or {})
    for tag_u, ops in equip_ops.items():
        merged[tag_u] = {**merged.get(tag_u, {}), **ops}
    study["equipment_conditions"] = merged
    study["sequence_step"] = 3
    study["sequence_rule"] = STEPS[2]["rule"]
    return study


def step3_note(study):
    """Status text once step 3 is done."""
    rule = STEPS[2]["rule"]
    study = study or {}
    n_lines = len(study.get("line_operating") or {})
    n_eq = len(study.get("equipment_operating") or {})
    if n_lines or n_eq:
        samples = []
        for tag, ops in list((study.get("line_operating") or {}).items())[:3]:
            bits = []
            if ops.get("p_op") is not None:
                bits.append(f"{ops['p_op']} psig")
            if ops.get("t_op") is not None:
                bits.append(f"{ops['t_op']} F")
            if bits:
                samples.append(f"{tag} ({', '.join(bits)} from PFD stream {ops.get('pfd_stream')})")
        shown = "; ".join(samples)
        return (
            f"Step 3 done — {rule} "
            f"Operating parameters set for {n_lines} P&ID line(s) and {n_eq} equipment item(s)."
            + (f" Examples: {shown}." if shown else "")
        )
    return f"Step 3 — {rule} No stream operating data was available to assign yet."


def _design_for_segment(line, line_operating=None):
    """Design parameters for one P&ID piping segment from its piping-spec class."""
    from .. import knowledge as kb

    code = str(line.get("spec") or "").strip()
    tag = str(line.get("tag") or "").strip()
    ops = (line_operating or {}).get(tag) or {}
    info = kb.spec(code) if code else None
    # Rating at the mapped operating temperature when known, else at 100 F.
    temp_f = ops.get("t_op")
    try:
        temp_f = float(temp_f) if temp_f is not None else 100.0
    except (TypeError, ValueError):
        temp_f = 100.0
    rating_psig = kb.spec_rating_psig(code, temp_f) if info else line.get("rating_psig")
    design = {
        "tag": tag,
        "spec": code or None,
        "spec_known": bool(info),
        "size": line.get("size"),
        "service": line.get("service"),
        "service_name": line.get("service_name"),
        "number": line.get("number"),
        "insulation": line.get("insulation"),
        "rating": (info or {}).get("rating") or line.get("rating"),
        "rating_psig": rating_psig,
        "rating_temp_f": temp_f if info else None,
        "min_temp_f": (info or {}).get("min_temp_f") if info else line.get("min_temp_f"),
        "max_temp_f": (info or {}).get("max_temp_f") if info else line.get("max_temp_f"),
        "material": (info or {}).get("material") if info else line.get("material"),
        "sour_service": (info or {}).get("sour_service") if info else line.get("sour"),
        "corrosion_allowance_in": (info or {}).get("corrosion_allowance_in") if info else None,
        "p_op": ops.get("p_op") if ops else line.get("p_op"),
        "t_op": ops.get("t_op") if ops else line.get("t_op"),
        "pfd_stream": ops.get("pfd_stream") or line.get("pfd_stream"),
        "source": "piping_spec" if info else ("line_mark" if code else "unknown"),
    }
    if info and info.get("valves"):
        design["valve_standards"] = {
            kind: list(codes) for kind, codes in (info.get("valves") or {}).items()
        }
    return design


def apply_step4(study, sheets=None):
    """Read the piping specification and set design parameters for every P&ID piping segment."""
    study = dict(study or {})
    line_ops = study.get("line_operating") or {}
    line_design = {}

    def _stamp(ext):
        for line in ext.get("lines") or []:
            tag = str(line.get("tag") or "").strip()
            if not tag:
                continue
            design = _design_for_segment(line, line_ops)
            line_design[tag] = design
            # Stamp the live extraction so the worksheet sees design limits.
            if design.get("rating") is not None:
                line["rating"] = design["rating"]
            if design.get("rating_psig") is not None:
                line["rating_psig"] = design["rating_psig"]
            if design.get("min_temp_f") is not None:
                line["min_temp_f"] = design["min_temp_f"]
            if design.get("max_temp_f") is not None:
                line["max_temp_f"] = design["max_temp_f"]
            if design.get("material") is not None:
                line["material"] = design["material"]
            if design.get("sour_service") is not None:
                line["sour"] = design["sour_service"]
            line["spec_known"] = bool(design.get("spec_known"))
            line["design"] = {
                k: design[k] for k in (
                    "rating", "rating_psig", "rating_temp_f", "min_temp_f", "max_temp_f",
                    "material", "sour_service", "corrosion_allowance_in", "p_op", "t_op",
                    "pfd_stream", "valve_standards", "source",
                )
                if design.get(k) is not None
            }

    if sheets:
        for _page, ext in sheets:
            _stamp(ext)
    known = sum(1 for d in line_design.values() if d.get("spec_known"))
    unknown = sum(1 for d in line_design.values() if d.get("spec") and not d.get("spec_known"))
    study["line_design"] = line_design
    study["piping_segments_designed"] = len(line_design)
    study["piping_specs_known"] = known
    study["piping_specs_unknown"] = unknown
    study["sequence_step"] = 4
    study["sequence_rule"] = STEPS[3]["rule"]
    return study


def step4_note(study):
    """Status text once step 4 is done."""
    rule = STEPS[3]["rule"]
    study = study or {}
    n = study.get("piping_segments_designed")
    if n is None:
        n = len(study.get("line_design") or {})
    known = study.get("piping_specs_known") or 0
    unknown = study.get("piping_specs_unknown") or 0
    if n:
        samples = []
        for tag, design in list((study.get("line_design") or {}).items())[:3]:
            bits = []
            if design.get("spec"):
                bits.append(f"class {design['spec']}")
            if design.get("rating_psig") is not None:
                bits.append(f"{design['rating_psig']} psig")
            if design.get("material"):
                bits.append(str(design["material"]).split(" - ")[0])
            if bits:
                samples.append(f"{tag} ({', '.join(bits)})")
        shown = "; ".join(samples)
        return (
            f"Step 4 done — {rule} "
            f"Design parameters set for {n} piping segment(s) "
            f"({known} from the piping specification"
            + (f", {unknown} class mark(s) not in the uploaded spec" if unknown else "")
            + ")."
            + (f" Examples: {shown}." if shown else "")
        )
    return f"Step 4 — {rule} No piping segments were available to design yet."


def _segment_role(line):
    """drain / bypass / vent / flare — or None if the segment is steady-state process piping."""
    service = str(line.get("service") or "").upper()
    name = str(line.get("service_name") or "").lower()
    tag = str(line.get("tag") or "").lower()
    blob = f"{name} {tag}"
    if service in ("FL", "SV", "BD") or any(w in blob for w in _ROLE_WORDS["flare"]):
        return "flare"
    if service == "VG" or any(w in blob for w in _ROLE_WORDS["vent"]):
        return "vent"
    if service in ("DW", "DH") or any(w in blob for w in _ROLE_WORDS["drain"]):
        return "drain"
    if any(w in blob for w in _ROLE_WORDS["bypass"]):
        return "bypass"
    if service in _OFF_PROCESS_SERVICES:
        return "vent" if service == "VG" else "flare" if service in ("FL", "SV", "BD") else "drain"
    return None


def _box_gap(a, b):
    if not a or not b:
        return 999.0
    ax, ay = (a[0] + a[2]) / 2, (a[1] + a[3]) / 2
    bx, by = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
    return ((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5


def _near_line(valve, line, limit=0.14):
    box = valve.get("box")
    if not box:
        return False
    boxes = line.get("boxes") or ([line["box"]] if line.get("box") else [])
    return any(_box_gap(box, candidate) <= limit for candidate in boxes)


def _is_nc_valve(valve):
    attrs = {str(a).upper() for a in (valve.get("attributes") or [])}
    return bool(attrs & _NORMALLY_CLOSED_ATTRS)


def apply_step5(study, sheets=None):
    """Identify drain / bypass / vent / flare segments isolated by normally closed valves."""
    study = dict(study or {})
    segments = []
    by_role = {"drain": [], "bypass": [], "vent": [], "flare": []}
    nc_isolations = []

    for page, ext in sheets or []:
        lines = ext.get("lines") or []
        valves = ext.get("valves") or []
        nc_valves = [v for v in valves if _is_nc_valve(v)]
        for line in lines:
            role = _segment_role(line)
            if not role:
                line["steady_state"] = True
                line["off_process_role"] = None
                continue
            tag = str(line.get("tag") or "").strip()
            isolators = []
            for valve in nc_valves:
                if _near_line(valve, line):
                    code = valve.get("code") or valve.get("tag")
                    if code and code not in isolators:
                        isolators.append(code)
            entry = {
                "tag": tag,
                "role": role,
                "service": line.get("service"),
                "service_name": line.get("service_name"),
                "page": page,
                "steady_state": False,
                "isolated_by_nc": isolators,
                "note": (
                    f"{role.capitalize()} line {tag} is not used in steady-state operation"
                    + (
                        f"; isolated by normally closed valve(s) {', '.join(isolators)}."
                        if isolators
                        else "; typically isolated through normally closed valves."
                    )
                ),
            }
            segments.append(entry)
            by_role[role].append(tag)
            line["steady_state"] = False
            line["off_process_role"] = role
            line["nc_isolation_valves"] = list(isolators)
            for code in isolators:
                nc_isolations.append({"valve": code, "line": tag, "role": role})

    study["non_steady_segments"] = segments
    study["non_steady_by_role"] = {role: tags for role, tags in by_role.items() if tags}
    study["nc_isolation_valves"] = nc_isolations
    study["sequence_step"] = 5
    study["sequence_rule"] = STEPS[4]["rule"]
    return study


def step5_note(study):
    """Status text once step 5 is done."""
    rule = STEPS[4]["rule"]
    study = study or {}
    segments = study.get("non_steady_segments") or []
    if not segments:
        return (
            f"Step 5 done — {rule} "
            "No drain / bypass / vent / flare segments were identified on this P&ID."
        )
    by_role = study.get("non_steady_by_role") or {}
    parts = []
    for role in ("drain", "bypass", "vent", "flare"):
        tags = by_role.get(role) or []
        if tags:
            shown = ", ".join(tags[:4])
            more = f" +{len(tags) - 4}" if len(tags) > 4 else ""
            parts.append(f"{role}: {shown}{more}")
    nc = study.get("nc_isolation_valves") or []
    return (
        f"Step 5 done — {rule} "
        f"Identified {len(segments)} non-steady-state segment(s) "
        f"({'; '.join(parts)}). "
        f"{len(nc)} normally closed isolation valve link(s) recorded."
    )
