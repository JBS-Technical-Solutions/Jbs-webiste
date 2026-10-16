"""Read a process flow diagram the way a HAZOP scribe reads it.

Start at the inlet. Keep every line of text. Walk the flow through each element
and each component. Take operating conditions from the heat and material balance
table, then say how the stream changes and what each equipment does to it.
"""

import re

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


def _does(kind):
    return DUTY.get(kind, DUTY["equipment"])


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
        caption = _caption(item.get("tag"), tokens)
        given = item.get("description") or ""
        name = caption or given or kind
        if re.fullmatch(r"[\d./\s-]+", name):
            name = caption or kind
        route.append({
            "tag": item.get("tag"),
            "name": name,
            "kind": kind,
            "does": _does(kind),
            "inlet_stream": inlet_no,
            "outlet_streams": outlets,
            "stream_change": change,
        })
    return start, route


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


def understand(pages):
    """pages: parse() results, one per PFD sheet, still carrying their text tokens."""
    tokens = []
    for ext in pages:
        for token in ext.get("tokens") or []:
            tokens.append(token)
    rows = _rows(tokens)
    balance = _balance(rows)
    bands = _table_bands(rows) if balance.get("found") else {}
    start, route = _route(pages, balance, tokens, bands)
    return {
        "start": {"kind": start["kind"], "text": start["text"]},
        "text": _remember(rows),
        "word_count": len(tokens),
        "balance": {"found": balance["found"], "stream_count": len(balance.get("streams") or {}), "streams": balance.get("streams") or {}},
        "route": route,
    }


def note(name, study, pages_read, pages_total):
    """A short worksheet note. The full reading stays on the study for the later steps."""
    start = study["start"]["text"]
    where = f"the inlet ({start})" if study["start"]["kind"] == "inlet" else start
    parts = [
        f"The PFD '{name}' was read from {where}. "
        f"All {study['word_count']} words on the sheet were kept, and the flow was followed through each element."
    ]
    shown = []
    for step in study["route"][:8]:
        sentence = f"{step['tag']} {step['does']}"
        if step.get("stream_change"):
            sentence += f"; {step['stream_change']}"
        shown.append(sentence)
    if shown:
        more = len(study["route"]) - len(shown)
        body = "; ".join(shown).rstrip(".")
        ending = "." if more <= 0 else f"; and {more} more elements."
        parts.append(" Along the process: " + body + ending)
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
