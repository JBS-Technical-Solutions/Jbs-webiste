"""Rule-based HAZOP generator.

Builds study nodes from extracted P&ID entities and applies a guide-word library
(No/More/Less/Reverse flow, High/Low pressure and temperature, Level, Composition,
Utility failure, Maintenance). Safeguards are taken from the instruments and valves
actually found on the drawing and design limits come from the piping-spec knowledge base.
"""

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
        """Where this node is read from: the inlet connector, or the equipment the process line leaves."""
        if self.sources:
            text = re.sub(r"(?i)^from\s+", "", self.src_text())
            return f"the inlet connector ({text})"
        mains = [e for e in self.equipment if not e.get("offpage") and e.get("kind") not in ("panel", "package") and e.get("box")]
        if mains:
            first = min(mains, key=lambda e: (e["box"][0] + e["box"][2]) / 2)
            return f"{first['tag']}, where the process line originates"
        return "the process equipment"

    def src_text(self):
        if not self.sources:
            return "upstream supply"
        return " and ".join(
            re.sub(r"(?i)^from\s+", "", c["description"]) + (f" ({c['line']})" if c["line"] else "") for c in self.sources)

    def dest_text(self):
        if not self.dests:
            return "downstream users"
        return " and ".join(
            re.sub(r"(?i)^to\s+", "", c["description"]) + (f" ({c['line']})" if c["line"] else "") for c in self.dests)

    def dest_equipment(self):
        offpage = [e for e in self.equipment if e["offpage"]]
        return offpage[0]["tag"] if offpage else (self.dests[0]["description"] if self.dests else "downstream equipment")


# ------------------------------------------------------------- safeguard helpers

def _boundary(ctx, tag, stop_at=None, extra=""):
    """Node description starts at the inlet, or at the equipment the process line leaves."""
    start = ctx.node_start()
    own = start == tag or start.startswith(tag + ",") or start.startswith(tag + " ")
    head = f"From {start}" if own else f"From {start} through {tag}"
    if extra:
        head += extra
    if stop_at:
        return head + f", up to {stop_at}."
    return head + f", to {ctx.dest_text()}."


def sg(text, tag, strong=False):
    return {"text": text, "tag": tag, "strong": strong}


def trip_safeguards(ctx, var, direction):
    """Trips (SIS) for a variable and direction ('H' or 'L'), merged with matching alarms."""
    hh = direction * 2
    out = []
    for t in ctx.find(var=var, cats=("trip",), has=(hh,)):
        alarms = [a for a in ctx.find(var=var, cats=("alarm",), has=(hh,))
                  if a["number"].startswith(t["number"]) or t["number"].startswith(a["number"])]
        word = {"T": "temperature", "P": "pressure", "L": "level", "F": "flow"}.get(var, ctx_var(t))
        lvl = "high-high" if direction == "H" else "low-low"
        text = f"{lvl.capitalize()} {word} trip (SIS)"
        if t.get("voting"):
            text += f", {t['voting']} voting"
        if alarms:
            text += f", with {lvl} alarm"
        out.append(sg(text, ctx.tags([t] + alarms), strong=True))
    if not out:
        for a in ctx.find(var=var, cats=("alarm", "switch"), has=(direction,)):
            word = ctx_var(a)
            out.append(sg(f"{'High' if direction == 'H' else 'Low'} {word} alarm", a["tag"]))
    return out


def ctx_var(i):
    return i["variable"].split(" /")[0].lower()


def controller_safeguard(ctx, var, direction=None):
    out = []
    for c in ctx.find(var=var, cats=("controller",)):
        text = f"{ctx_var(c).capitalize()} control"
        if c.get("set_point"):
            text += f" (set {c['set_point']})"
        if direction:
            text += f" with {'high' if direction == 'H' else 'low'} alarm"
        out.append(sg(text, c["tag"] + (f" ({direction})" if direction else "")))
    return out


def relief_safeguards(ctx):
    out = []
    for p in ctx.find(cats=("relief",)):
        text = "Pressure safety valve"
        if p.get("set_psig"):
            text += f" set at {p['set_psig']} psig"
        text += " to flare" if ctx.flare_lines else ""
        if p.get("fire_case"):
            text += " (sized for fire case)"
        out.append(sg(text, p["tag"], strong=True))
    return out


def check_safeguards(ctx):
    out = [sg("Check valve", i["tag"], strong=True) for i in ctx.find(letters=("FSV",))]
    if not out:
        for v in ctx.valves_of("check")[:2]:
            out.append(sg(f"Check valve {v['size'] or ''} {v['code']}".replace("  ", " "), v["code"], strong=True))
    return out


def skin_safeguards(ctx):
    return [sg("Heater skin / element temperature with trip in heater panel", i["tag"], strong=True)
            for i in ctx.instruments if i.get("remark") == "skin"]


def shutdown_alarms(ctx):
    xa = ctx.find(var="X", cats=("other", "alarm"))
    xa = [i for i in xa if "A" in i["letters"][1:]]
    return [sg("Common trouble / system shutdown alarms", ctx.tags(xa))] if xa else []


# -------------------------------------------------------------------- row helper

def row(cause, consequences, cc, safeguards, c, base_l, recs=()):
    """C and L are this scenario's intents, placed on the levels of the uploaded risk-matrix file."""
    strong = any(s["strong"] for s in safeguards)
    c, l = risk.from_basis(c, max(1, base_l - (1 if strong else 0)))
    safeguards = safeguards[:5]
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


def equipment_node(ctx, eq, nid):
    tag, kind = eq["tag"], eq["kind"]
    d = eq["design"]
    label = KIND_LABEL.get(kind, "equipment")
    desc = eq["description"] or label.capitalize()
    cvs = ctx.find(cats=("control_valve",))
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
    temp_trips = trip_safeguards(ctx, "T", "H")
    flow_trips = trip_safeguards(ctx, "F", "L")
    sg_noflow = flow_trips + (skin_safeguards(ctx) + temp_trips if kind == "heater" else []) + shutdown_alarms(ctx)
    rec_flow = []
    if kind in ("heater", "pump", "compressor") and not flow_trips:
        panel = next((e["tag"] for e in ctx.equipment if e["kind"] == "panel"), f"the {label} control system")
        rec_flow.append(ctx.recs.add(
            f"Confirm that {panel} includes a low-flow / flow-proving permissive that trips {tag} on loss of flow; "
            f"if not, provide a low-low flow trip (FSLL)."))
    devs.append(dev("No / Less Flow", [
        row(f"Loss of supply from {ctx.src_text()}.",
            [no_flow_cons, f"Loss of {ctx.fluid} supply to {ctx.dest_text()} (production loss)."],
            "S" if kind in ("heater", "pump", "compressor") else "A", sg_noflow, 4 if kind == "heater" else 3, 3, rec_flow),
        row(f"Inadvertent closure of an isolation valve upstream / downstream of {tag}.",
            ["As above.", f"Blocked-in {label}; pressure rise (refer High Pressure)."] if kind == "heater" else ["As above."],
            "S" if kind == "heater" else "A", sg_noflow + relief_safeguards(ctx), 4 if kind == "heater" else 3, 2, rec_flow),
        row(f"{cv} fails closed or controller malfunction (refer control valve node).", ["As above."],
            "S" if kind == "heater" else "A", sg_noflow, 4 if kind == "heater" else 3, 3, rec_flow) if cv else None,
    ]))

    if cv:
        more = {"heater": f"Flow exceeds {tag} capacity" + (f" ({d['duty_mmbtu_hr']} MMBtu/hr)" if d.get("duty_mmbtu_hr") else "")
                + "; insufficient heating and low outlet temperature downstream (refer Low Temperature).",
                "vessel": f"High throughput in {tag}; liquid carry-over to gas outlet.",
                }.get(kind, f"Throughput above {label} design rate.")
        devs.append(dev("More Flow", [
            row(f"{cv} fails open / controller malfunction.", [more], "S" if kind == "heater" else "A",
                controller_safeguard(ctx, "T") + trip_safeguards(ctx, "T", "L"), 3, 2),
        ]))

    # ---- reverse flow
    rev_rows = [row(f"Loss of upstream pressure while {ctx.dest_text()} remains pressurized.",
                    [f"Backflow of {ctx.fluid} through {tag} to upstream supply; possible overpressure of lower-rated upstream equipment."],
                    "A", check_safeguards(ctx), 3, 2,
                    [] if check_safeguards(ctx) else [ctx.recs.add(f"Provide a check valve on the outlet of {tag} to prevent reverse flow.")])]
    if len(ctx.sources) >= 2:
        names = " and ".join(c["description"] + (f" ({c['line']})" if c["line"] else "") for c in ctx.sources)
        rev_rows.append(row(
            f"Pressure imbalance between inlet sources {names}; the sources join with no check valves shown on this P&ID.",
            ["Higher-pressure source backflows into the lower-pressure source; possible overpressure / contamination of upstream equipment."],
            "S", [], 4, 2,
            [ctx.recs.add(f"Verify on upstream drawings that check valves are provided on each incoming line ({names}) and that "
                          f"each source is rated for the maximum pressure of the other.")]))
    devs.append(dev("Reverse Flow", rev_rows))

    # ---- high pressure
    hp_rows = []
    psv = relief_safeguards(ctx)
    psv_items = ctx.find(cats=("relief",))
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
            f"High supply pressure from {ctx.src_text()}. Piping spec {spec['spec']} is rated {spec['rating_psig']} psig but "
            f"{tag} design pressure is {p_des} psig.",
            [f"Overpressure of {tag} above design pressure; rupture and loss of containment of {ctx.release} - fire, explosion"
             + (", toxic exposure" if ctx.sour else "") + ", possible fatality."],
            "S", psv + trip_safeguards(ctx, "P", "H"), 5, 3, recs_))
    else:
        hp_rows.append(row(
            f"High supply pressure from {ctx.src_text()}.",
            [f"Overpressure of {tag}; possible loss of containment of {ctx.release}."],
            "S", psv + trip_safeguards(ctx, "P", "H"), sev_loc, 2,
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
        row(f"Loss of supply from {ctx.src_text()}" + (", or vent / drain valve left open to flare." if ctx.flare_lines else "."),
            [f"Low pressure supply to {ctx.dest_text()} (operational)."], "A",
            controller_safeguard(ctx, "P", "L") + trip_safeguards(ctx, "P", "L"), 2, 3),
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
        if not temp_trips:
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
                          ["As above."], "S", sg_ht, 4, 3,
                          [ctx.recs.add(f"Confirm the SIS high-high temperature trip de-energizes {tag} through a contactor / breaker "
                                        f"independent of the BPCS power controller.")] if temp_trips else recs_))
        ht.append(row(f"Low / no flow through {tag} while in service (refer No Flow).", ["As above."], "S", sg_ht, 4, 3, rec_flow))
        devs.append(dev("High Temperature", ht))

        lt = []
        if kind == "heater":
            lt.append(row(f"{tag} trip, loss of power / fuel, or heater switched off.",
                          [f"No heating; low {ctx.fluid} temperature downstream" + (f" of {cv} after pressure letdown (refer control valve node)." if cv else ".")],
                          "S", shutdown_alarms(ctx) + controller_safeguard(ctx, "T", "L") + trip_safeguards(ctx, "T", "L"), 4, 3))
        lt.append(row("Low inlet temperature in cold ambient conditions" + (f" (normal operating {d['t_op']} {DEG})." if d.get("t_op") is not None else "."),
                      [f"Increased duty demand on {tag}; possible hydrate formation if the gas is wet." if ctx.gas else f"Increased duty demand on {tag}."],
                      "A", controller_safeguard(ctx, "T"), 2, 2))
        devs.append(dev("Low Temperature", lt))

    # ---- level (vessels / tanks)
    if kind in ("vessel", "tank"):
        lsh = trip_safeguards(ctx, "L", "H")
        lsl = trip_safeguards(ctx, "L", "L")
        devs.append(dev("High Level", [row(f"Level control failure or liquid outlet blocked on {tag}.",
                                           [f"Liquid carry-over from {tag} to gas outlet / downstream equipment."], "S",
                                           controller_safeguard(ctx, "L", "H") + lsh, 4, 3,
                                           [] if lsh else [ctx.recs.add(f"Provide an independent high-high level trip (LSHH) on {tag}.")])]))
        devs.append(dev("Low Level", [row(f"Level control valve fails open on {tag}.",
                                          [f"Loss of liquid seal; gas blow-by to the downstream liquid system - possible overpressure."],
                                          "S", controller_safeguard(ctx, "L", "L") + lsl, 5, 3,
                                          [] if lsl else [ctx.recs.add(f"Provide an independent low-low level trip (LSLL) on {tag} to prevent gas blow-by.")])]))

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
        "boundary": _boundary(ctx, tag, cv),
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
    devs = []

    devs.append(dev("No / Less Flow", [
        row(f"{tag} {fail_txt if fail == 'FC' else 'closes'} - loss of instrument air / signal, positioner failure, or controller malfunction.",
            [f"Loss of {ctx.fluid} supply to {dest}; possible trip of downstream users (production loss).",
             f"Blocked-in upstream equipment" + (f" ({heater['tag']} energized - refer {heater['tag']} node)." if heater else ".")],
            "A", controller_safeguard(ctx, var.upper()[0], "L") + ([sg("Manual bypass globe valve", ctx.names(bypass[:1]))] if bypass else [])
            + (trip_safeguards(ctx, "T", "H") if heater else []), 3, 3),
        row(f"Isolation valve closed in error or check valve stuck closed.", ["As above."], "A",
            controller_safeguard(ctx, var.upper()[0], "L"), 3, 2),
    ]))

    hp_cons = [f"Downstream pressure rises towards upstream pressure" + (f" ({up_p} psig normal, up to {up_pmax} psig)" if up_p else "")
               + f"; overpressure of {dest_eq} (design pressure not shown on this P&ID) - rupture, release of {ctx.release}, fire / explosion."]
    down = [l for l in ctx.process_lines if any(l["tag"] == c["line"] for c in ctx.dests)]
    if down and up_pmax and down[0].get("rating_psig"):
        if down[0]["rating_psig"] >= up_pmax:
            hp_cons.append(f"Outlet piping {down[0]['tag']} ({down[0]['rating']}) is rated above the upstream design pressure and is not overpressured.")
        else:
            hp_cons.append(f"Outlet piping {down[0]['tag']} ({down[0]['rating']}, {down[0]['rating_psig']} psig) can be overpressured.")
    if heater:
        hp_cons.append(f"High flow exceeds {heater['tag']} capacity - low temperature (refer Low Temperature).")
    more_rows = [row(f"{tag} fails open - transmitter reads low, controller or positioner failure.", hp_cons, "S",
                     controller_safeguard(ctx, var.upper()[0], "H") + trip_safeguards(ctx, "P", "H"), 5, 3,
                     [ctx.recs.add(f"Verify that the relief device(s) on {dest_eq} are sized for gas blow-by through fully open {tag}"
                                   + (f" plus its bypass {ctx.names(bypass[:1])}" if bypass else "")
                                   + " at maximum upstream pressure; if not, consider a PSHH tripping an upstream SDV (subject to SIL assessment).")])]
    if bypass:
        more_rows.append(row(f"{tag} bypass globe valve {ctx.names(bypass[:1])} opened in error or left open after maintenance.",
                             [f"Uncontrolled flow bypassing {tag}; high pressure at {dest_eq} (as above, smaller magnitude)."], "S",
                             controller_safeguard(ctx, var.upper()[0], "H"), 4, 2,
                             [ctx.recs.add(f"Lock closed (LC) the {tag} bypass valve {ctx.names(bypass[:1])} and include it in the lock / car-seal register.")]))
    devs.append(dev("More Flow / High Pressure", more_rows))

    devs.append(dev("Reverse Flow", [row(f"Loss of upstream pressure while {dest} remains pressurized.",
                                         [f"Backflow through {tag} into upstream equipment and supply lines."], "A",
                                         check_safeguards(ctx), 3, 2)]))
    devs.append(dev("Low Pressure", [row(f"{tag} closes or upstream supply is lost; high demand from downstream users.",
                                         [f"Low pressure at {dest}; trip of downstream users."], "A",
                                         controller_safeguard(ctx, var.upper()[0], "L"), 2, 3)]))

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
                           ["As above."] if heater else cons, "S", tsl, 5, 3, recs_ if not heater else recs_[:1]))
        lt_rows.append(row(f"Flow above heating capacity - {tag} fails open or bypass open.", ["As above."], "S", tic + tsl, 5, 2, recs_[:1]))
        devs.append(dev("Low Temperature", lt_rows))

    if heater:
        devs.append(dev("High Temperature", [row(f"Temperature control failure driving {heater['tag']} to maximum output.",
                                                 [f"Hot gas to {dest}; downstream piping above its maximum design temperature."], "A",
                                                 trip_safeguards(ctx, "T", "H") + skin_safeguards(ctx), 4, 3)]))

    devs.append(dev("Utility Failure (Instrument Air / Power)", [row(
        f"Loss of instrument air or power to {tag} positioner.",
        [f"{tag} {fail_txt}" + (f"; loss of supply to {dest} (refer No Flow)." if fail == "FC" else "; refer More Flow." if fail == "FO" else ".")],
        "A", [sg(f"Fail-{'closed' if fail == 'FC' else 'open' if fail == 'FO' else 'safe'} action of {tag}", f"{tag} ({fail})" if fail else tag)]
        if fail else [], 3, 2,
        [] if fail else [ctx.recs.add(f"Confirm the fail-safe action of {tag} on loss of air / signal.")])]))

    pic = ctx.find(var=var.upper()[0], cats=("controller",))
    return {
        "id": str(nid),
        "title": f"{var.capitalize()} control valve {tag} and outlet to {ctx.dest_text()}",
        "boundary": _boundary(ctx, tag, extra=(f" (with bypass {ctx.names(bypass[:1])})" if bypass else "")),
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
        row(f"{psv_tags} plugged by hydrates / ice or corrosion products" + (" (sour service)." if ctx.sour else "."), ["As above."], "S",
            [sg("Periodic relief valve inspection and testing", psv_tags)], 5, 1),
    ]))
    devs.append(dev("More Flow (Passing / Open Vent)", [row(
        f"{psv_tags} passing / leaking" + (f", or manual vent {ctx.names(vent[:1])} left open or passing." if vent else "."),
        ["Continuous loss of gas to flare - flaring, environmental impact, gas loss.", "Severe JT cooling in the flare tail pipe (refer Low Temperature)."],
        "E", [sg("Flare line temperature indication with low alarm", ctx.tags(flare_ti[:1]) + " (L)")] if flare_ti else [], 3, 3)]))
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
              ([sg(f"{fs['spec']} {fs['material'].split(' - ')[-1]} ({fs['min_temp_f']} {DEG})", f"{fs['spec']} spec")] if fs else [])
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
        "boundary": f"Relief branch through {psv_tags}" + (f" and manual vent {ctx.names(vent[:1])}" if vent else "")
                    + " to " + (", ".join(l["tag"] for l in ctx.flare_lines) or "the flare system") + ".",
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
            if len(out) == 3:
                break
        return out

    by_number = {}
    for i, h in enumerate(headers):
        y0 = h["box"][1]
        below = [o for o in headers[i + 1:] if o["box"][1] > y0 + 10]
        y1 = below[0]["box"][1] if below else y0 + 0.18 * scale
        block = [ln["text"] for ln in lines
                 if y0 - 20 <= ln["box"][1] < y1 and abs(ln["box"][0] - h["box"][0]) < 0.2 * scale]
        tags = mentioned(" ".join(block)) or nearest(h["box"])
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
        plan.append({"title": title, "tags": slot["tags"], "design_intent": ""})
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
    eqs = [e for e in ext["equipment"] if e["tag"].upper() in tags and e["kind"] not in ("panel", "package")]
    cvs = [i for i in ctx.find(cats=("control_valve",)) if i["tag"].upper() in tags]
    relief = any(i["tag"].upper() in tags for i in ctx.find(cats=("relief",))) or \
        any(l["tag"].upper() in tags for l in ctx.flare_lines)
    lines = [l for l in ctx.process_lines if l["tag"].upper() in tags]

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
    if (entry.get("design_intent") or "").strip():
        node["design_intent"] = entry["design_intent"].strip()
    return node


def plan_nodes(ext):
    """Proposed nodes for the user to review: title, the tags that anchor each node and its generated intent."""
    ctx = Ctx(ext)
    out = []
    for i, entry in enumerate(_marked_nodes(ext) or _auto_plan(ctx, ext), 1):
        node = _build(ctx, ext, entry, i)
        out.append({"title": node["title"], "tags": entry["tags"], "design_intent": "",
                    "auto_intent": node["design_intent"]})
    return out


# ------------------------------------------------------------------------ main

def _center(box):
    return (box[0] + box[2]) / 2, (box[1] + box[3]) / 2


def _scope_extraction(ext, tags):
    """Keep the tags of one part, plus whatever sits next to them on the drawing."""
    wanted = {str(t).strip().upper() for t in tags if t and str(t).strip()}
    groups = ("equipment", "instruments", "lines", "valves", "connectors", "spec_breaks")

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
        scoped[key] = [ent for ent in ext.get(key) or [] if ident(ent) in wanted or close(ent.get("box"))]
    kept_lines = {str(ln.get("tag") or "").upper() for ln in scoped["lines"]}
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
    note = (f"The drawing was split into {len(pieces)} parts. Each part was studied on its own, "
            "then the parts were compiled into this worksheet.")
    return {"study": study, "nodes": nodes, "recommendations": recs, "assumptions": [note, *assumptions],
            "node_source": source}


def _worksheet(ext, study, plan, source):
    ctx = Ctx(ext)
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
    ]
    if source == "user":
        assumptions.append("HAZOP nodes and their boundaries were defined by the user before the worksheet was generated.")
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


def generate(ext, study=None, user_nodes=None, on_part=None):
    """Split the drawing into parts, study each part on its own, then compile one worksheet.

    on_part(index, count, entry) is called before each part when there is more than one.
    """
    marked = None if user_nodes else _marked_nodes(ext)
    plan = user_nodes if user_nodes else (marked or _auto_plan(Ctx(ext), ext))
    source = "user" if user_nodes else ("drawing" if marked else "auto")
    if len(plan) <= 1:
        return _worksheet(ext, study, plan, source)
    pieces = []
    for i, entry in enumerate(plan, 1):
        if on_part:
            on_part(i, len(plan), entry)
        pieces.append(_worksheet(_scope_extraction(ext, entry.get("tags") or []), study, [entry], source))
    return _compile_parts(pieces, source)
