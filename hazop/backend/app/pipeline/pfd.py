"""Read a process flow diagram the way a HAZOP scribe reads it.

The main equipment names are written across the top of the sheet. Read those names,
say what that equipment is and what it is used for, then follow the streams and say
what each one is doing on this drawing and how the process proceeds from inlet to outlet.
"""

import re

from .. import knowledge as kb

DUTY = {
    "separator": "separates the stream into vapour and liquid",
    "vessel": "holds the stream so vapour and liquid can disengage",
    "exchanger": "transfers heat and changes the stream temperature",
    "heater": "heats the stream",
    "pump": "raises the pressure of the liquid stream",
    "compressor": "raises the pressure of the gas stream",
    "tank": "stores the stream",
    "package": "treats the stream inside the package",
    "equipment": "processes the stream",
}

# What the equipment is, why it is used, and the work it does. Keyed by the API 14C modifier.
MOD_ROLE = {
    "AP": ("a heater", "to add heat to a process stream", "it raises the stream temperature"),
    "AC": ("a boiler", "to generate a heating medium", "it boils the medium and supplies heat"),
    "BG": ("a shell-and-tube heat exchanger", "to move heat from one stream to another without mixing them", "one stream gives up heat and the other stream takes it"),
    "BC": ("a reboiler", "to boil liquid and return vapour to a column or vessel", "it vaporises part of the liquid"),
    "BD": ("a separator", "to split a mixed stream into vapour and liquid", "vapour leaves one outlet and liquid leaves the other"),
    "BF": ("a scrubber", "to catch liquid carried in a gas stream", "the gas leaves with less liquid in it"),
    "AM": ("a freewater knockout", "to remove free water from the hydrocarbon stream", "water settles and is taken off the bottom"),
    "AF": ("a contactor", "to contact gas with a treating liquid", "the gas is treated as it passes through the liquid"),
    "BJ": ("a tank", "to hold a liquid inventory", "it stores the liquid between the upstream supply and the downstream demand"),
    "AE": ("a compressor", "to raise the pressure of a gas", "it compresses the gas and discharges it at a higher pressure"),
    "BB": ("a pump", "to raise the pressure of a liquid", "it pushes the liquid onward at a higher pressure"),
    "AK": ("a filter-separator", "to remove solids and liquid from a gas", "gas passes through and the contaminants stay behind"),
    "AJ": ("a filter", "to remove solids from a stream", "the stream passes and the solids stay on the filter"),
    "BK": ("a treater", "to treat the stream before it goes on", "it changes the stream so it meets the next step"),
    "AD": ("a coalescer", "to gather fine liquid droplets into drops that can be removed", "the droplets combine and fall out of the gas"),
}
TYPE_ROLE = {
    "H": ("a heat exchanger", "to change a stream temperature by transferring heat", "heat moves into or out of the process stream"),
    "E": ("a fired or exhaust-heated equipment", "to heat a stream with a fire or a hot exhaust", "it adds heat to the stream"),
    "M": ("a pressure vessel", "to give vapour and liquid room to separate", "liquid drops out and vapour leaves by the gas outlet"),
    "N": ("a heated pressure vessel", "to separate or treat a stream while heat is added", "it holds the stream under pressure and heats it"),
    "C": ("a compressor", "to raise gas pressure", "it compresses the gas and sends it onward"),
    "P": ("a pump", "to raise liquid pressure", "it moves the liquid to the downstream pressure"),
    "A": ("an atmospheric tank", "to store liquid at atmospheric pressure", "it holds the liquid inventory"),
    "B": ("a heated atmospheric vessel", "to store or treat liquid while it is heated", "it holds the liquid and adds heat"),
}
NAME_ROLE = (
    (("knock", "k.o", "ko drum"), ("a knockout drum", "to remove liquid from a gas stream", "gas leaves the top and the liquid that drops out leaves the bottom")),
    (("separator",), ("a separator", "to split vapour and liquid", "vapour and liquid leave by separate outlets")),
    (("scrubber",), ("a scrubber", "to catch liquid carried in gas", "the gas leaves drier than it entered")),
    (("contactor",), ("a contactor", "to contact gas with a treating liquid", "the gas is treated as it passes through the liquid")),
    (("preheater", "heater"), ("a heater", "to raise the stream temperature", "it adds heat before the stream goes to the next step")),
    (("exchanger", "cooler"), ("a heat exchanger", "to move heat between streams", "the process stream leaves hotter or colder than it entered")),
    (("compressor",), ("a compressor", "to raise gas pressure", "it discharges the gas at a higher pressure")),
    (("pump",), ("a pump", "to raise liquid pressure", "it discharges the liquid at a higher pressure")),
    (("filter",), ("a filter", "to remove solids or liquid from the stream", "the stream passes and the unwanted material stays behind")),
    (("tank",), ("a tank", "to store liquid", "it holds the inventory")),
)
TOP_NAME = re.compile(
    r"exchanger|heater|preheater|drum|separator|scrubber|compressor|pump|contactor|vessel|tank|cooler|filter|column|treater|knock",
    re.I)
TOP_SKIP = re.compile(
    r"\b(note|revision|rev\b|date|drawn|sheet|drawing|scale|client|project|title|approved|checked|balance|legend)\b",
    re.I)

PROPERTIES = (
    ("temperature", re.compile(r"temp", re.I)),
    ("pressure", re.compile(r"press", re.I)),
    ("molar_flow", re.compile(r"molar", re.I)),
    ("mass_flow", re.compile(r"mass|flow\s*rate|kg\s*/\s*h|lb\s*/\s*h|tonne", re.I)),
    ("volume_flow", re.compile(r"volum|m3\s*/\s*h|sm3|mmscfd|actual\s+flow", re.I)),
    ("vapour_fraction", re.compile(r"vapou?r|quality", re.I)),
    ("molecular_weight", re.compile(r"mol(?:ecular)?\s*(?:wt|weight)|mw\b", re.I)),
    ("enthalpy", re.compile(r"enthalp", re.I)),
    ("density", re.compile(r"densit", re.I)),
)
PROPERTY_LABEL = {
    "temperature": "Temperature",
    "pressure": "Pressure",
    "molar_flow": "Molar flow",
    "mass_flow": "Mass flow",
    "volume_flow": "Volume flow",
    "vapour_fraction": "Vapour fraction",
    "molecular_weight": "Molecular weight",
    "enthalpy": "Enthalpy",
    "density": "Density",
}
STREAM_NO = re.compile(r"^\d{1,3}[A-Z]{0,2}$", re.I)
NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


def _center(box):
    return ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)


def _rows(tokens):
    """Text grouped into lines, in reading order, from the top of each page."""
    ordered = sorted(tokens, key=lambda t: (t.get("page", 0), _center(t["box"])[1], _center(t["box"])[0]))
    rows = []
    for token in ordered:
        page = token.get("page", 0)
        y = _center(token["box"])[1]
        height = max(token["box"][3] - token["box"][1], 0.004)
        if rows and rows[-1]["page"] == page and abs(y - rows[-1]["y"]) <= max(height, rows[-1]["h"]) * 0.7:
            rows[-1]["tokens"].append(token)
            n = len(rows[-1]["tokens"])
            rows[-1]["y"] = (rows[-1]["y"] * (n - 1) + y) / n
            rows[-1]["h"] = max(rows[-1]["h"], height)
        else:
            rows.append({"page": page, "y": y, "h": height, "tokens": [token]})
    for row in rows:
        row["tokens"].sort(key=lambda t: _center(t["box"])[0])
        row["text"] = " ".join(t["text"] for t in row["tokens"]).strip()
    return [row for row in rows if row["text"]]


def _remember(rows):
    lines = [row["text"] for row in rows]
    text = "\n".join(lines)
    if len(text) > 12000:
        text = text[:12000].rsplit("\n", 1)[0]
    return text


def _stream_labels(row):
    labels = []
    for token in row["tokens"]:
        text = re.sub(r"\s+", "", token["text"].strip().upper())
        if STREAM_NO.fullmatch(text):
            labels.append((token, text))
    return labels


def _is_border_grid(labels):
    """Drawing border numbers 1, 2, 3 ... are not stream numbers."""
    if any(not text.isdigit() for _token, text in labels):
        return False
    nums = [int(text) for _token, text in labels]
    return nums == list(range(1, len(nums) + 1))


def _is_stream_header(row):
    labels = _stream_labels(row)
    if len(labels) < 4:
        return None
    xs = [_center(token["box"])[0] for token, _text in labels]
    if max(xs) - min(xs) < 0.12:
        return None
    if _property(row["text"]) or _is_border_grid(labels):
        return None
    return [token for token, _text in labels]


def _property(text):
    for key, pattern in PROPERTIES:
        if pattern.search(text):
            return key
    return None


def _balance(rows):
    """Heat and material balance: one column per stream number, one row per operating condition."""
    best = None
    for index, row in enumerate(rows):
        header = _is_stream_header(row)
        if not header:
            continue
        columns = [(_center(t["box"])[0], re.sub(r"\s+", "", t["text"].strip().upper())) for t in header]
        columns.sort()
        gap = min((b[0] - a[0] for a, b in zip(columns, columns[1:])), default=0.08)
        left = columns[0][0] - gap * 0.6
        streams = {}
        used = 0
        last_y = row["y"]
        for follow in rows[index + 1:index + 40]:
            if follow["page"] != row["page"]:
                break
            if follow["y"] - last_y > 0.08:
                break
            if _is_stream_header(follow):
                break
            last_y = follow["y"]
            names = [t for t in follow["tokens"] if _center(t["box"])[0] < left]
            values = [t for t in follow["tokens"] if _center(t["box"])[0] >= left]
            label = " ".join(t["text"] for t in names).strip(" :-")
            key = _property(label)
            if not key or not values:
                continue
            used += 1
            for token in values:
                x = _center(token["box"])[0]
                stream = min(columns, key=lambda col: abs(col[0] - x))[1]
                if abs(x - min(columns, key=lambda col: abs(col[0] - x))[0]) > gap * 0.7:
                    continue
                streams.setdefault(stream, {})[key] = token["text"].strip()
        if used >= 2 and (best is None or used > best[0]):
            best = (used, streams, row["page"])
    if not best:
        return {"found": False, "streams": {}}
    return {"found": True, "streams": best[1], "page": best[2]}


def _start(exts):
    sources = []
    equipment = []
    for ext in exts:
        sources.extend(c for c in ext.get("connectors") or [] if c.get("direction") == "source" and c.get("box"))
        for item in ext.get("equipment") or []:
            if item.get("offpage") or item.get("kind") in ("panel", "package") or not item.get("box"):
                continue
            equipment.append(item)
    if sources:
        inlet = min(sources, key=lambda c: (_center(c["box"])[0], c.get("page", 0)))
        return {"kind": "inlet", "text": inlet.get("description") or "the inlet", "box": inlet["box"], "page": inlet.get("page", 0)}
    if equipment:
        first = min(equipment, key=lambda e: (e.get("page", 0), _center(e["box"])[0]))
        return {"kind": "equipment", "text": first.get("tag") or "the first equipment", "tag": first.get("tag"),
                "box": first["box"], "page": first.get("page", 0)}
    return {"kind": "page", "text": "the top of the PFD", "box": [0, 0, 0, 0], "page": 0}


def _near_stream(item, tokens, table_pages, known=()):
    """A stream number drawn on the process line just left (inlet) or right (outlet) of an element."""
    box = item.get("box")
    if not box:
        return None, []
    page = item.get("page", 0)
    mid_y = _center(box)[1]
    left, right = [], []
    for token in tokens:
        if token.get("page", 0) != page or _in_table(token, table_pages):
            continue
        if not STREAM_NO.fullmatch(token["text"].strip()):
            continue
        x, y = _center(token["box"])
        if abs(y - mid_y) > 0.08:
            continue
        if box[0] - 0.14 <= x < box[0]:
            left.append((box[0] - x, token["text"].strip()))
        elif box[2] < x <= box[2] + 0.14:
            right.append((x - box[2], token["text"].strip()))
    inlet = min(left)[1] if left else None
    outlets = []
    for _dist, number in sorted(right):
        if number not in outlets:
            outlets.append(number)
    if known:
        known = {str(item).upper() for item in known}
        if inlet and inlet.upper() not in known:
            inlet = None
        outlets = [number for number in outlets if number.upper() in known]
    return inlet, outlets[:3]


def _in_table(token, table_pages):
    info = table_pages.get(token.get("page", 0))
    if not info:
        return False
    _x, y = _center(token["box"])
    return info["top"] - 0.02 <= y <= info["bottom"] + 0.02


def _table_bands(rows):
    """Pages whose heat and material balance occupies a vertical band, so stream numbers there are not process tags."""
    bands = {}
    for index, row in enumerate(rows):
        if not _is_stream_header(row):
            continue
        bottom = row["y"]
        for follow in rows[index + 1:index + 40]:
            if follow["page"] != row["page"] or follow["y"] - bottom > 0.08:
                break
            if _property(follow["text"]):
                bottom = follow["y"]
        if bottom > row["y"]:
            bands[row["page"]] = {"top": row["y"], "bottom": bottom}
    return bands


def _number(text):
    match = NUMBER.search(str(text).replace(",", ""))
    return float(match.group()) if match else None


def _stream_change(inlet_no, inlet, outlets, streams):
    if not inlet or not outlets:
        return ""
    sentences = []
    for key, label in PROPERTY_LABEL.items():
        before = inlet.get(key)
        if not before:
            continue
        for number in outlets:
            after = (streams.get(number) or {}).get(key)
            if not after or after == before:
                continue
            a, b = _number(before), _number(after)
            if a is None or b is None or a == b:
                sentences.append(f"{label} is {before} on stream {inlet_no} and {after} on stream {number}.")
            elif b < a:
                sentences.append(f"{label} falls from {before} on stream {inlet_no} to {after} on stream {number}.")
            else:
                sentences.append(f"{label} rises from {before} on stream {inlet_no} to {after} on stream {number}.")
            break
    return " ".join(sentences)


def _route(exts, balance, tokens, bands):
    start = _start(exts)
    titles = _top_names(tokens)
    items = []
    for ext in exts:
        for item in ext.get("equipment") or []:
            if item.get("offpage") or item.get("kind") == "panel" or not item.get("box"):
                continue
            items.append(item)
    sources = []
    for ext in exts:
        sources.extend(c for c in ext.get("connectors") or [] if c.get("direction") == "source" and c.get("box"))
    used = set()
    ordered = []
    for source in sorted(sources, key=lambda c: (c.get("page", 0), _center(c["box"])[1], _center(c["box"])[0])):
        sy, sx = _center(source["box"])[1], _center(source["box"])[0]
        group = []
        for item in items:
            if id(item) in used or item.get("page", 0) != source.get("page", 0):
                continue
            x, y = _center(item["box"])
            if abs(y - sy) < 0.16 and x >= sx - 0.08:
                group.append(item)
        for item in sorted(group, key=lambda item: _center(item["box"])[0]):
            used.add(id(item))
            ordered.append(item)
    for item in sorted(items, key=lambda item: (item.get("page", 0), _center(item["box"])[0], _center(item["box"])[1])):
        if id(item) not in used:
            ordered.append(item)
    streams = balance.get("streams") or {}
    route = []
    for item in ordered[:80]:
        inlet_no, outlets = _near_stream(item, tokens, bands, streams)
        inlet = streams.get(inlet_no) if inlet_no else None
        change = _stream_change(inlet_no, inlet, outlets, streams)
        kind = item.get("kind") or "equipment"
        above = _attach_top_name(item, titles) or _name_above(item, tokens)
        caption = _caption(item.get("tag"), tokens)
        given = item.get("description") or ""
        name = above or caption or given or kind
        if re.fullmatch(r"[\d./\s-]+", name):
            name = above or caption or kind
        what, used_for, work = _role(item, name)
        doing = _doing(name, kind, change)
        route.append({
            "tag": item.get("tag"),
            "name": name,
            "kind": kind,
            "what": what,
            "used_for": used_for,
            "work": work,
            "doing": doing,
            "does": doing,
            "inlet_stream": inlet_no,
            "outlet_streams": outlets,
            "stream_change": change,
        })
    return start, route, titles


def read_balance_images(doc, pdf_page, rendered):
    """OCR a heat and material balance that is pasted on the PFD as a picture, not as text."""
    import io

    import numpy as np
    from PIL import Image

    from . import ocr

    if doc is None or pdf_page is None:
        return []
    scale = rendered.dpi / 72.0
    infos = pdf_page.get_image_info()
    tokens = []
    for img in pdf_page.get_images():
        xref, width, height = img[0], img[2], img[3]
        if width < 700 or height < 180:
            continue
        info = next((item for item in infos if item.get("width") == width and item.get("height") == height), None)
        if not info or not info.get("bbox"):
            continue
        raw = doc.extract_image(xref)
        picture = Image.open(io.BytesIO(raw["image"])).convert("RGB")
        words = ocr.read_document(np.asarray(picture))
        x0, y0, x1, y1 = info["bbox"]
        sx = (x1 - x0) / max(width, 1) * scale
        sy = (y1 - y0) / max(height, 1) * scale
        for word in words:
            box = word["box"]
            tokens.append({
                "text": word["text"],
                "box": [x0 * scale + box[0] * sx, y0 * scale + box[1] * sy,
                        x0 * scale + box[2] * sx, y0 * scale + box[3] * sy],
            })
    return tokens


def _caption(tag, tokens):
    """The equipment title written in the same column as its tag."""
    tag_u = (tag or "").upper()
    if not tag_u:
        return ""
    best = ""
    for anchor in tokens:
        if tag_u not in anchor["text"].upper():
            continue
        ax, ay = _center(anchor["box"])
        below = []
        for token in tokens:
            if token is anchor:
                continue
            x, y = _center(token["box"])
            if abs(x - ax) <= 0.05 and 0 < y - ay <= 0.09:
                below.append((y, token["text"]))
        words = [text for _y, text in sorted(below) if re.search(r"[A-Za-z]{3}", text)]
        phrase = " ".join(words[:6])
        if len(phrase) > len(best):
            best = phrase
    return best


def _clusters(tokens, gap=0.08):
    """Words that sit together horizontally are one equipment name, not one long title."""
    ordered = sorted(tokens, key=lambda token: _center(token["box"])[0])
    groups = []
    for token in ordered:
        x = _center(token["box"])[0]
        if not groups or x - groups[-1]["right"] > gap:
            groups.append({"tokens": [token], "left": x, "right": x})
        else:
            groups[-1]["tokens"].append(token)
            groups[-1]["right"] = x
    named = []
    for group in groups:
        text = " ".join(token["text"] for token in group["tokens"]).strip()
        if len(text) < 4 or not TOP_NAME.search(text) or TOP_SKIP.search(text):
            continue
        xs = [_center(token["box"])[0] for token in group["tokens"]]
        ys = [_center(token["box"])[1] for token in group["tokens"]]
        named.append({
            "text": re.sub(r"\s+", " ", text),
            "page": group["tokens"][0].get("page", 0),
            "x": sum(xs) / len(xs),
            "y": sum(ys) / len(ys),
        })
    return named


def _top_names(tokens):
    """Main equipment names written across the upper part of the PFD."""
    upper = [token for token in tokens if _center(token["box"])[1] <= 0.34 and re.search(r"[A-Za-z]", token["text"])]
    by_page = {}
    for token in upper:
        by_page.setdefault(token.get("page", 0), []).append(token)
    names = []
    for page_tokens in by_page.values():
        names.extend(_clusters(page_tokens))
    return names


def _name_above(item, tokens):
    """The name written above this equipment symbol."""
    box = item.get("box")
    if not box:
        return ""
    cx, top = _center(box)[0], box[1]
    page = item.get("page", 0)
    hits = []
    for token in tokens:
        if token.get("page", 0) != page:
            continue
        x, y = _center(token["box"])
        if abs(x - cx) <= 0.09 and top - 0.16 <= y < top - 0.004 and re.search(r"[A-Za-z]{3}", token["text"]):
            hits.append((y, x, token["text"]))
    hits.sort()
    return " ".join(text for _y, _x, text in hits[:8]).strip()


def _attach_top_name(item, titles):
    box = item.get("box")
    if not box:
        return ""
    cx = _center(box)[0]
    page = item.get("page", 0)
    near = [title for title in titles if title["page"] == page and abs(title["x"] - cx) <= 0.12 and title["y"] < box[1]]
    if not near:
        return ""
    return min(near, key=lambda title: abs(title["x"] - cx))["text"]


def _role(item, name):
    """What this equipment is, why it is used, and the work it does, from its name and its tag."""
    title = (name or "").lower()
    specific = tuple(entry for entry in NAME_ROLE if "exchanger" not in entry[0] and "cooler" not in entry[0])
    for words, role in specific:
        if any(word in title for word in words):
            return role
    prefix = str(item.get("prefix") or "")
    if not prefix and item.get("tag"):
        prefix = str(item["tag"]).split("-")[0]
    modifier = prefix[1:3]
    if modifier in MOD_ROLE:
        return MOD_ROLE[modifier]
    for words, role in NAME_ROLE:
        if any(word in title for word in words):
            return role
    letter = prefix[:1]
    if letter in TYPE_ROLE:
        return TYPE_ROLE[letter]
    decoded = item.get("api14c") or (kb.decode_equipment(prefix[:3]) if len(prefix) >= 3 else None)
    if decoded and " - " in decoded:
        kind_name, modifier_name = decoded.split(" - ", 1)
        return (f"a {modifier_name.lower()}", f"as a {kind_name.lower()}", DUTY.get(item.get("kind"), DUTY["equipment"]))
    kind = item.get("kind") or "equipment"
    return (f"a {kind.replace('_', ' ')}", "to carry out its process duty", DUTY.get(kind, DUTY["equipment"]))


def _doing(name, kind, change):
    """What this equipment is doing on this PFD, from the stream change across it."""
    low = (change or "").lower()
    title = (name or "").lower()
    if "temperature falls" in low:
        return "cools the stream"
    if "temperature rises" in low:
        return "heats the stream"
    if "pressure falls" in low:
        return "lets the stream pressure down"
    if "pressure rises" in low and kind in ("compressor", "pump"):
        return "raises the stream pressure"
    if "vapour fraction" in low and "falls" in low:
        return "condenses part of the stream and removes liquid"
    if any(word in title for word in ("drum", "separator", "scrubber", "knock", "k.o")) or kind == "vessel":
        return "separates liquid from the gas"
    if kind == "heater" or "heater" in title:
        return "heats the stream"
    if kind == "exchanger" or "exchanger" in title or "cooler" in title:
        return "changes the stream temperature"
    if kind == "compressor":
        return "compresses the gas"
    if kind == "pump":
        return "pumps the liquid onward"
    return DUTY.get(kind, DUTY["equipment"])


def _flow_sentence(start, route):
    """How the process proceeds, from the inlet through each main equipment in order."""
    if not route:
        return f"The process starts at {start['text']}. No main equipment name was read on the PFD, so the path could not be followed."
    where = start["text"]
    sentences = [f"The process starts at {where}."]
    for index, step in enumerate(route):
        name = step["name"]
        tag = f" ({step['tag']})" if step.get("tag") else ""
        inlet = step.get("inlet_stream")
        outlets = step.get("outlet_streams") or []
        move = ""
        if inlet and outlets:
            move = f" Stream {inlet} enters and stream {', '.join(outlets)} leaves."
        elif outlets:
            move = f" The outlet is stream {', '.join(outlets)}."
        change = f" {step['stream_change']}" if step.get("stream_change") else ""
        if index == 0:
            lead = f"From there the stream enters {name}{tag}."
        else:
            previous = route[index - 1]["name"]
            lead = f"From {previous} the stream continues to {name}{tag}."
        sentences.append(f"{lead} {name} is {step['what']}, used {step['used_for']}. On this PFD it {step['doing']}.{move}{change}")
    sentences.append("That is the order in which the process proceeds on this PFD.")
    return " ".join(sentences)


def understand(pages):
    """pages: parse() results, one per PFD sheet, still carrying their text tokens."""
    tokens = []
    for ext in pages:
        for token in ext.get("tokens") or []:
            tokens.append(token)
    rows = _rows(tokens)
    balance = _balance(rows)
    bands = _table_bands(rows) if balance.get("found") else {}
    start, route, titles = _route(pages, balance, tokens, bands)
    named = {step["name"].lower() for step in route}
    unread = [title["text"] for title in titles if title["text"].lower() not in named]
    return {
        "start": {"kind": start["kind"], "text": start["text"]},
        "text": _remember(rows),
        "word_count": len(tokens),
        "balance": {"found": balance["found"], "stream_count": len(balance.get("streams") or {}), "streams": balance.get("streams") or {}},
        "equipment_names": [step["name"] for step in route if step.get("name")],
        "equipment": [
            {"tag": step.get("tag"), "name": step["name"], "what": step["what"], "used_for": step["used_for"],
             "work": step["work"], "doing": step["doing"]}
            for step in route
        ],
        "unread_top_names": unread,
        "process_flow": _flow_sentence(start, route),
        "route": route,
    }


def note(name, study, pages_read, pages_total):
    """A short worksheet note. The full reading stays on the study for the later steps."""
    start = study["start"]["text"]
    where = f"the inlet ({start})" if study["start"]["kind"] == "inlet" else start
    parts = [
        f"The PFD '{name}' was read from the equipment names written at the top of the sheet, starting at {where}. "
    ]
    flow = (study.get("process_flow") or "").strip()
    if flow:
        parts.append(flow + " ")
    else:
        parts.append(f"All {study['word_count']} words on the sheet were kept. ")
    balance = study["balance"]
    if balance["found"]:
        parts.append(
            f" Operating conditions were taken from the heat and material balance ({balance['stream_count']} streams)."
        )
    else:
        parts.append(" No heat and material balance table was found, so the operating conditions are not on this PFD.")
    if pages_total > pages_read:
        parts.append(f" The first {pages_read} of {pages_total} PFD pages were read.")
    return "".join(parts)


def _box_center(box):
    return ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)


def _tag_in(text):
    match = re.search(r"\b([A-Z]{2,4}-\d{3,5}[A-Z]?)\b", str(text or "").upper())
    return match.group(1) if match else ""


def _stream_segments(study):
    """Each PFD stream is the line from one equipment (or the inlet) to the next."""
    route = study.get("route") or []
    start = (study.get("start") or {}).get("text") or "the inlet"
    segments = {}

    def label(step):
        if not step:
            return ""
        name = step.get("name") or ""
        tag = step.get("tag") or ""
        if name and tag and tag not in name:
            return f"{name} ({tag})"
        return name or tag

    def put(number, source, dest):
        key = str(number or "").strip().upper()
        if not key or key in segments:
            return
        segments[key] = {"stream": key, "from": source, "to": dest}

    for index, step in enumerate(route):
        previous = label(route[index - 1]) if index else start
        here = label(step)
        following = label(route[index + 1]) if index + 1 < len(route) else "downstream"
        if step.get("inlet_stream"):
            put(step["inlet_stream"], previous, here)
        for outlet in step.get("outlet_streams") or []:
            put(outlet, here, following)
    for index, step in enumerate(route[:-1]):
        here = label(step)
        following = label(route[index + 1])
        covered = any(item["from"] == here and item["to"] == following for item in segments.values())
        if not covered:
            put(f"{step.get('tag') or here}->{route[index + 1].get('tag') or following}", here, following)
    for number in ((study.get("balance") or {}).get("streams") or {}):
        put(number, "", "")
    return list(segments.values())


def _collect(sheets):
    equipment, lines, connectors, tokens = [], [], [], []
    for page, ext in sheets:
        for item in ext.get("equipment") or []:
            if item.get("offpage") or not item.get("box") or not item.get("tag"):
                continue
            equipment.append({**item, "page": item.get("page", page)})
        for item in ext.get("lines") or []:
            if item.get("box") and item.get("tag"):
                lines.append({**item, "page": item.get("page", page)})
        for item in ext.get("connectors") or []:
            connectors.append({**item, "page": item.get("page", page)})
        for item in ext.get("tokens") or []:
            if item.get("box"):
                tokens.append({**item, "page": item.get("page", page)})
    return equipment, lines, connectors, tokens


def _same_tag(equipment, tag, page):
    tag = (tag or "").upper()
    found = [item for item in equipment if str(item.get("tag") or "").upper() == tag]
    if page is None:
        return found[0] if found else None
    on_page = [item for item in found if item.get("page") == page]
    return (on_page or found or [None])[0]


def _line_boxes(line):
    return line.get("boxes") or [line["box"]]


def _stream_on_line(stream, line, tokens):
    best = None
    for token in tokens:
        if token.get("page") != line.get("page"):
            continue
        text = re.sub(r"\s+", "", str(token.get("text") or "")).upper()
        if text != stream:
            continue
        point = _box_center(token["box"])
        for box in _line_boxes(line):
            x, y = point
            dx = max(box[0] - x, 0, x - box[2])
            dy = max(box[1] - y, 0, y - box[3])
            dist = (dx * dx + dy * dy) ** 0.5
            if dist <= 0.08 and (best is None or dist < best):
                best = dist
    return best


def _between(line, left, right):
    if not left or not right or left.get("page") != line.get("page") or right.get("page") != line.get("page"):
        return None
    ax, ay = _box_center(left["box"])
    bx, by = _box_center(right["box"])
    lx, ly = _box_center(line["box"])
    lo, hi = min(ax, bx) - 0.06, max(ax, bx) + 0.06
    if not lo <= lx <= hi:
        return None
    if abs(ly - (ay + by) / 2) > max(abs(ay - by), 0.08) + 0.12:
        return None
    return abs(lx - (ax + bx) / 2) + abs(ly - (ay + by) / 2)


def _beside(line, equipment, upstream):
    if not equipment or equipment.get("page") != line.get("page"):
        return None
    ex, ey = _box_center(equipment["box"])
    lx, ly = _box_center(line["box"])
    if abs(ly - ey) > 0.16:
        return None
    if upstream and lx > ex + 0.02:
        return None
    if not upstream and lx < ex - 0.02:
        return None
    if abs(lx - ex) > 0.28:
        return None
    return abs(lx - ex) + abs(ly - ey)


def relate(study, sheets):
    """Say which PFD stream is which P&ID line, using the equipment both drawings name."""
    equipment, lines, connectors, tokens = _collect(sheets)
    segments = _stream_segments(study)
    ranked = []
    for segment in segments:
        source_tag = _tag_in(segment["from"])
        dest_tag = _tag_in(segment["to"])
        stream = segment["stream"]
        numbered = bool(re.fullmatch(r"\d{1,3}[A-Z]{0,2}", stream))
        for line in lines:
            source = _same_tag(equipment, source_tag, line.get("page"))
            dest = _same_tag(equipment, dest_tag, line.get("page"))
            reasons = []
            score = None
            if numbered:
                marked = _stream_on_line(stream, line, tokens)
                if marked is not None:
                    score = marked
                    reasons.append(f"stream {stream} is written beside this line on the P&ID")
            gap = _between(line, source, dest)
            if gap is not None:
                score = gap + 0.15 if score is None else min(score, gap + 0.15)
                reasons.append(f"this line runs from {source_tag} to {dest_tag}, the same equipment this stream joins on the PFD")
            if score is None and dest and not source:
                side = _beside(line, dest, upstream=True)
                if side is not None:
                    score = side + 0.4
                    reasons.append(f"this line arrives at {dest_tag}, where the PFD stream arrives")
            if score is None and source and not dest:
                side = _beside(line, source, upstream=False)
                if side is not None:
                    score = side + 0.4
                    reasons.append(f"this line leaves {source_tag}, where the PFD stream leaves")
            words = {word for word in re.findall(r"[A-Za-z]{4,}", f"{segment['from']} {segment['to']}".lower())}
            for connector in connectors:
                if connector.get("line") != line.get("tag") or connector.get("page") != line.get("page"):
                    continue
                shared = words & {word for word in re.findall(r"[A-Za-z]{4,}", str(connector.get("description") or "").lower())}
                if shared:
                    score = 0.12 if score is None else min(score, 0.12)
                    reasons.append(f"the P&ID connector '{connector.get('description')}' names the same place as the PFD")
            if score is None:
                continue
            ranked.append((score, stream, line, reasons[0] if reasons else "the equipment on both drawings match"))
    ranked.sort(key=lambda item: item[0])
    taken_lines, taken_streams = set(), set()
    chosen = {}
    for _score, stream, line, reason in ranked:
        if stream in taken_streams or line["tag"] in taken_lines:
            continue
        taken_streams.add(stream)
        taken_lines.add(line["tag"])
        chosen[stream] = (line, reason)
    matches = []
    for segment in segments:
        line, reason = chosen.get(segment["stream"], (None, ""))
        number = segment["stream"] if re.fullmatch(r"\d{1,3}[A-Z]{0,2}", segment["stream"]) else ""
        place = " to ".join(part for part in (segment["from"], segment["to"]) if part)
        matches.append({
            "pfd_stream": number or segment["stream"],
            "pfd_from": segment["from"],
            "pfd_to": segment["to"],
            "pid_line": line["tag"] if line else "",
            "pid_service": line.get("service_name") or "" if line else "",
            "why": reason,
        })
    sentences = []
    for match in matches:
        name = f"PFD stream {match['pfd_stream']}" if re.fullmatch(r"\d{1,3}[A-Z]{0,2}", match["pfd_stream"]) else f"The PFD line from {match['pfd_from']} to {match['pfd_to']}"
        if match["pid_line"]:
            sentences.append(f"{name} ({match['pfd_from']} to {match['pfd_to']}) is P&ID line {match['pid_line']}.")
        elif match["pfd_from"] or match["pfd_to"]:
            sentences.append(f"{name} ({match['pfd_from']} to {match['pfd_to']}) has no corresponding line on the P&ID.")
    note = " ".join(sentences[:12])
    if len(sentences) > 12:
        note += f" {len(sentences) - 12} more streams were compared."
    return {"matches": matches, "note": note}
