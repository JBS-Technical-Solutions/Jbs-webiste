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

SYSTEM = """You are a senior process safety engineer facilitating a HAZOP study (IEC 61882) for an oil & gas facility.
You are given a P&ID image, entities extracted from it by OCR, project standards and a draft worksheet produced by a
rule engine. Produce an improved, complete HAZOP worksheet for this P&ID.

Rules:
- Use only tags, lines and equipment that appear on the drawing or in the extracted entities. Never invent tag numbers.
- Keep the node structure sensible (major equipment, control valve / letdown, relief and flare). Add or merge nodes if
  the drawing clearly warrants it.
- The "boundary" field is the node description. Start it at the inlet or the first equipment, then name every equipment item in the node and what that item is there to do.
- Write each cause, consequence and safeguard from the duty of that valve or equipment. A ball valve isolates, a check valve stops reverse flow, a globe valve throttles, a pump moves fluid, a vessel separates, a heater adds heat, a relief valve protects against overpressure.
- For each node use relevant guide-word deviations (No/Less Flow, More Flow, Reverse Flow, High/Low Pressure,
  High/Low Temperature, High/Low Level, Composition/Contamination, Utility Failure, Maintenance/Start-up).
- Each row: one credible cause, numbered consequences (escalation to the worst credible outcome without safeguards),
  CC (S = Safety, E = Environment, A = Asset), safeguards actually shown on the P&ID with their tags, and C and L.
  C and L must be levels of the uploaded risk matrix in the input. The risk ranking is that file's cell at (C, L).
  Do not invent a ranking from a generic C times L score.
- Additional project documents (e.g. PFD) may be attached; use them for context, but tags must still come from the P&ID.
- Recommendations must be specific and actionable; reuse the same recommendation id when the same action applies.
- Respect piping spec ratings, design pressures/temperatures and sour service when judging consequences.
- A company-standards block is included in the user message. Treat it as the project legend: tag structure, line graphics,
  instrument bubbles, piping symbols, piping classes and the risk-matrix definitions. Prefer it over a generic ISA reading.
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


FIXED_NODES = ("The nodes in the draft worksheet were defined by the user. Keep exactly these nodes, in this order, "
               "with their titles and boundaries; do not add, merge or remove nodes.")


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


def normalise(data, draft):
    """Coerce an AI answer into the worksheet schema; recompute risk; renumber deviations."""
    recs = {str(k): str(v) for k, v in (data.get("recommendations") or {}).items()}
    nc, nl = risk.size()
    nodes = []
    for n_idx, node in enumerate(data.get("nodes") or [], 1):
        devs = []
        for d in node.get("deviations") or []:
            rows = []
            for r in d.get("rows") or []:
                if not r.get("cause"):
                    continue
                c, l = _clamp(r.get("c"), 3, nc), _clamp(r.get("l"), 2, nl)
                rows.append({
                    "cause": str(r["cause"]),
                    "consequences": _as_list(r.get("consequences")),
                    "cc": str(r.get("cc") or "S")[:3],
                    "safeguards": _as_list(r.get("safeguards")) or ["None identified on this P&ID"],
                    "tags": _as_list(r.get("tags")) or ["-"],
                    "c": c, "l": l, "risk": evaluate(c, l),
                    "recommendations": [x for x in _as_list(r.get("recommendations")) if x in recs],
                })
            if rows:
                name = re.sub(r"^\s*\d+(\.\d+)*\s*", "", str(d.get("deviation") or "Deviation"))
                devs.append({"deviation": f"{n_idx}.{len(devs) + 1} {name}", "rows": rows})
        if devs:
            nodes.append({
                "id": n_idx, "title": str(node.get("title") or f"Node {n_idx}"),
                "boundary": str(node.get("boundary") or ""), "design_intent": str(node.get("design_intent") or ""),
                "design_conditions": str(node.get("design_conditions") or ""), "deviations": devs,
            })
    if not nodes:
        raise AIError("The AI response contained no usable worksheet rows.")
    for i, n in enumerate(nodes, 1):
        n["id"] = i
    assumptions = _as_list(data.get("assumptions")) or draft.get("assumptions", [])
    return {"study": draft["study"], "nodes": nodes, "recommendations": recs, "assumptions": assumptions}


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
    result = normalise(_parse_json(text), draft)
    result["study"] = dict(result["study"], analysis=f"AI-assisted ({cfg['label']} {cfg['model']})")
    return result
