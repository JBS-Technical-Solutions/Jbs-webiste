"""Optional AI review: a vision LLM refines the rule-based worksheet using the P&ID image.

The model receives the drawing, the extracted entities, the knowledge-base summary and the draft worksheet,
and must return the same JSON schema. Risk is always recomputed server-side from C and L.
"""

import base64
import json
import re
import time

import httpx

from .. import knowledge as kb
from .. import risk
from ..config import AI_PROVIDERS
from ..risk import evaluate

TIMEOUT = httpx.Timeout(240.0, connect=20.0)

SYSTEM = """You are a senior process safety engineer reviewing a HAZOP worksheet (IEC 61882) for an oil & gas facility.
The draft was already written by reading the PFD, then reading each P&ID node from its start to its end. Review that draft against the P&ID. Do not start a new worksheet.

Keep these exactly:
- The same nodes, in the same order. Do not add, merge or remove a node.
- boundary is the node description: a short summary of the route (where the line comes from, what main equipment it passes, and where it goes). Do not list every instrument or valve.
- design_intent is one sentence: the overall purpose of that node.
- design_conditions are the design and operating pressure and temperature of the main equipment only. Use a number only when it is on the P&ID. Do not add piping classes or small valves.

You may improve causes, consequences and safeguards:
- One cause is one credible failure of a device that is on the drawing.
- The consequence is what that cause does to the equipment named on that line.
- A safeguard is a device drawn on the P&ID that prevents that consequence: a trip, an alarm, a relief valve, a shutdown valve or a check valve. Name its tag.
- Do not list a device that does not stop that consequence.
- Never invent a tag, line number or equipment number. If it is not in extracted_entities or the draft, do not write it.
- C and L are levels of the uploaded risk matrix. The ranking is that file's cell. Do not multiply C by L.
- Recommendations must name a real device or a real missing device. Reuse a recommendation id when the action is the same.
- Output ONLY JSON, no markdown, matching exactly this schema:
{"nodes":[{"id":1,"title":"...","boundary":"...","design_intent":"...","design_conditions":"...",
  "deviations":[{"deviation":"No / Less Flow","rows":[{"cause":"...","consequences":["..."],"cc":"S",
  "safeguards":["..."],"tags":["..."],"c":4,"l":2,"recommendations":["R-01"]}]}]}],
 "recommendations":{"R-01":"..."},
 "assumptions":["..."]}"""


class AIError(RuntimeError):
    pass


def _entities_summary(ext):
    def pick(items, keys):
        return [{k: i[k] for k in keys if i.get(k) not in (None, "", [], {})} for i in items]

    return {
        "equipment": pick(ext["equipment"], ("tag", "description", "kind", "api14c", "design", "electric", "offpage")),
        "instruments": pick(ext["instruments"], ("tag", "description", "category", "set_point", "set_psig",
                                                 "fire_case", "fail_action", "voting", "remark", "inferred")),
        "lines": pick(ext["lines"], ("tag", "service_name", "spec", "rating", "rating_psig", "min_temp_f",
                                     "max_temp_f", "sour", "material")),
        "valves": pick(ext["valves"], ("code", "type", "size", "attributes")),
        "connectors": pick(ext["connectors"], ("direction", "description", "line", "ref")),
        "flags": ext.get("flags", {}),
    }


FIXED_NODES = ("Keep every draft node, in this order, including its boundary, design_intent and design_conditions. "
               "Change only causes, consequences and safeguards.")


_TAG = re.compile(r"\b(?:[A-Z]{1,6}-\d{2,5}[A-Z0-9/-]*|\d{1,2}-[A-Z]{1,4}-[A-Z0-9]+(?:-[A-Z0-9]+)+)\b")


def _allowed_tags(ext, draft):
    allowed = set()
    for key, field in (("equipment", "tag"), ("instruments", "tag"), ("lines", "tag"), ("valves", "code"), ("connectors", "tag")):
        for ent in (ext or {}).get(key) or []:
            value = str(ent.get(field) or "").strip().upper()
            if value:
                allowed.add(value)
    for match in _TAG.finditer(json.dumps(draft, default=str).upper()):
        allowed.add(match.group(0))
    return allowed


def _invented(text, allowed):
    bad = []
    for match in _TAG.finditer(str(text or "").upper()):
        token = match.group(0)
        if token in allowed or any(token in known or known in token for known in allowed):
            continue
        bad.append(token)
    return bad


def _prompt(ext, draft, texts, fixed_nodes):
    specs = {code: {k: v for k, v in s.items() if k != "pressure_temp"} for code, s in kb.specs().items()}
    m = kb.apply_matrix_definitions(risk.current())
    nc, nl = risk.size(m)
    payload = {
        "extracted_entities": _entities_summary(ext),
        "piping_specs": specs,
        "risk_matrix": {
            "consequence_levels": m["severity"], "likelihood_levels": m["likelihood"],
            "rankings": {b["code"]: b["name"] for b in m["bands"]},
            "cells": {f"C{c}": {f"L{l}": m["cells"][c - 1][l - 1] for l in range(1, nl + 1)} for c in range(1, nc + 1)},
        },
        "draft_worksheet": {k: draft[k] for k in ("nodes", "recommendations", "assumptions")},
        "allowed_tags": sorted(_allowed_tags(ext, draft))[:300],
    }
    if texts:
        payload["project_documents"] = texts
    head = (f"Review the attached P&ID and produce the final HAZOP worksheet JSON. C must be 1-{nc} and L must be 1-{nl}.\n\n"
            + kb.model_brief())
    if fixed_nodes:
        head += " " + FIXED_NODES
    return head + "\n\n" + json.dumps(payload, ensure_ascii=False, default=str)


def _parse_json(text):
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < 0:
        raise AIError("The AI response did not contain JSON.")
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError as e:
        raise AIError(f"The AI response was not valid JSON: {e}") from e


def _call_openai(cfg, images, prompt):
    content = [{"type": "text", "text": prompt}]
    for label, b64 in images:
        content += [{"type": "text", "text": label},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}", "detail": "high"}}]
    r = httpx.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {cfg['key']}"},
        json={
            "model": cfg["model"],
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": content},
            ],
        },
        timeout=TIMEOUT,
    )
    if r.status_code >= 400:
        raise AIError(f"OpenAI error {r.status_code}: {r.text[:300]}")
    return r.json()["choices"][0]["message"]["content"]


def _call_anthropic(cfg, images, prompt):
    content = []
    for label, b64 in images:
        content += [{"type": "text", "text": label},
                    {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": b64}}]
    r = httpx.post(
        "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": cfg["key"], "anthropic-version": "2023-06-01"},
        json={
            "model": cfg["model"],
            "max_tokens": 16000,
            "system": SYSTEM,
            "messages": [{"role": "user", "content": content + [{"type": "text", "text": prompt}]}],
        },
        timeout=TIMEOUT,
    )
    if r.status_code >= 400:
        raise AIError(f"Anthropic error {r.status_code}: {r.text[:300]}")
    return "".join(b.get("text", "") for b in r.json()["content"])


def _call_gemini(cfg, images, prompt):
    inputs = []
    for label, b64 in images:
        inputs += [{"text": label}, {"inline_data": {"mime_type": "image/png", "data": b64}}]
    models = [cfg["model"], *cfg.get("fallbacks", []), cfg["model"]]
    for attempt, model in enumerate(models):
        if attempt:
            time.sleep(3 * attempt)
        r = httpx.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            headers={"x-goog-api-key": cfg["key"]},
            json={
                "systemInstruction": {"parts": [{"text": SYSTEM}]},
                "contents": [{"role": "user", "parts": inputs + [{"text": prompt}]}],
                "generationConfig": {"responseMimeType": "application/json"},
            },
            timeout=TIMEOUT,
        )
        if r.status_code not in (404, 429, 500, 503):
            break
    if r.status_code >= 400:
        raise AIError(f"Gemini error {r.status_code}: {r.text[:300]}")
    parts = r.json()["candidates"][0]["content"]["parts"]
    return "".join(p.get("text", "") for p in parts)


CALLERS = {"openai": _call_openai, "anthropic": _call_anthropic, "gemini": _call_gemini}


def _clamp(v, default, top):
    try:
        return max(1, min(top, int(v)))
    except (TypeError, ValueError):
        return min(default, top)


def _as_list(v):
    if v is None:
        return []
    if isinstance(v, str):
        return [v] if v.strip() else []
    return [str(x) for x in v if str(x).strip()]


def normalise(data, draft, ext=None):
    """Keep the draft node summary. Accept only causes and safeguards whose tags are on the drawing."""
    recs = {str(k): str(v) for k, v in (data.get("recommendations") or {}).items()}
    allowed = _allowed_tags(ext, draft)
    nc, nl = risk.size()
    ai_nodes = list(data.get("nodes") or [])
    nodes = []
    for n_idx, draft_node in enumerate(draft.get("nodes") or [], 1):
        ai_node = ai_nodes[n_idx - 1] if n_idx <= len(ai_nodes) and isinstance(ai_nodes[n_idx - 1], dict) else {}
        devs = []
        for d in ai_node.get("deviations") or []:
            rows = []
            for r in d.get("rows") or []:
                cause = str(r.get("cause") or "").strip()
                if not cause or _invented(cause, allowed):
                    continue
                safeguards = [s for s in _as_list(r.get("safeguards")) if not _invented(s, allowed)]
                tags = [t for t in _as_list(r.get("tags")) if not _invented(t, allowed)]
                if not safeguards or safeguards == ["None identified on this P&ID"]:
                    borrowed = _draft_safeguards(draft_node, cause)
                    if borrowed:
                        safeguards, tags = borrowed
                c, l = _clamp(r.get("c"), 3, nc), _clamp(r.get("l"), 2, nl)
                rows.append({
                    "cause": cause,
                    "consequences": [c_ for c_ in _as_list(r.get("consequences")) if not _invented(c_, allowed)],
                    "cc": str(r.get("cc") or "S")[:3],
                    "safeguards": safeguards or ["None identified on this P&ID"],
                    "tags": tags or ["-"],
                    "c": c, "l": l, "risk": evaluate(c, l),
                    "recommendations": [x for x in _as_list(r.get("recommendations")) if x in recs and not _invented(recs[x], allowed)],
                })
            if rows:
                name = re.sub(r"^\s*\d+(\.\d+)*\s*", "", str(d.get("deviation") or "Deviation"))
                devs.append({"deviation": f"{n_idx}.{len(devs) + 1} {name}", "rows": rows})
        node = dict(draft_node)
        node.update({
            "id": n_idx,
            "title": str(draft_node.get("title") or f"Node {n_idx}"),
            "boundary": str(draft_node.get("boundary") or ""),
            "design_intent": str(draft_node.get("design_intent") or ""),
            "design_conditions": str(draft_node.get("design_conditions") or ""),
            "deviations": devs or draft_node.get("deviations") or [],
        })
        nodes.append(node)
    if not nodes:
        raise AIError("The AI response contained no usable worksheet rows.")
    assumptions = _as_list(data.get("assumptions")) or draft.get("assumptions", [])
    return {"study": draft["study"], "nodes": nodes, "recommendations": recs, "assumptions": assumptions}


def _draft_safeguards(node, cause):
    wanted = _TAG.findall(str(cause).upper())
    for dev in node.get("deviations") or []:
        for row in dev.get("rows") or []:
            text = str(row.get("cause") or "").upper()
            if wanted and any(tag in text for tag in wanted):
                safeguards = [s for s in row.get("safeguards") or [] if s and s != "None identified on this P&ID"]
                if safeguards:
                    return safeguards, row.get("tags") or ["-"]
    return None


def review(provider, png_bytes, ext, draft, attachments=(), fixed_nodes=False):
    """attachments: optional project documents as {"name", "png"} (rendered page) or {"name", "text"}."""
    cfg = AI_PROVIDERS.get(provider)
    if not cfg or not cfg["key"]:
        raise AIError(f"AI provider '{provider}' is not configured. Add its API key to backend/.env.")
    images = [("P&ID under review:", base64.b64encode(png_bytes).decode())]
    images += [(f"Project document {a['name']} (reference only):", base64.b64encode(a["png"]).decode())
               for a in attachments if a.get("png")][:3]
    texts = [{"name": a["name"], "text": a["text"]} for a in attachments if a.get("text")]
    text = CALLERS[provider](cfg, images, _prompt(ext, draft, texts, fixed_nodes))
    result = normalise(_parse_json(text), draft, ext)
    result["study"] = dict(result["study"], analysis=f"AI-assisted ({cfg['label']} {cfg['model']})")
    return result
