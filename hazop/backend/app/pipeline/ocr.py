"""Text extraction from a P&ID image: tiled OCR plus orientation re-reads of vertical text."""

import hashlib
import json
import re
import threading
import unicodedata

import numpy as np
from PIL import Image

from ..config import CACHE_DIR, OCR_MODELS_DIR

TILE = 1400
OVERLAP = 220
ZOOM = 2
BLANK_THRESHOLD = 252
MIN_SCORE = 0.6
TAG_LIKE = re.compile(r'[A-Z]{1,3}-\d|\d"|-[A-Z]{1,2}\d?-|^[A-Z]{1,3}-?\d{2,3}N$')

_engine = None
_engine_lock = threading.Lock()
_call_lock = threading.Lock()


def _ocr_engine():
    global _engine
    with _engine_lock:
        if _engine is None:
            from rapidocr import ModelType, OCRVersion, RapidOCR

            # The parser is tuned to the PP-OCRv4 models; rapidocr's newer default models misread P&ID symbols.
            v4 = {"ocr_version": OCRVersion.PPOCRV4, "model_type": ModelType.MOBILE}
            models = {
                "Det": "ch_PP-OCRv4_det_infer.onnx",
                "Cls": "ch_ppocr_mobile_v2.0_cls_infer.onnx",
                "Rec": "ch_PP-OCRv4_rec_infer.onnx",
            }
            params = {"Global.log_level": "warning", "Global.use_vertical_padding": False}
            for stage, model in models.items():
                params[f"{stage}.model_path"] = str(OCR_MODELS_DIR / model)
                params.update({f"{stage}.{k}": v for k, v in v4.items()})
            _engine = RapidOCR(params=params)
    return _engine


# RapidOCR keeps use_det/use_cls/use_rec from the previous call, so every call passes all three, and calls from
# different threads (analysis jobs, document checks) are serialised.
def _read_full(engine, img):
    with _call_lock:
        res = engine(img, use_det=True, use_cls=True, use_rec=True, return_word_box=False)
    if res.boxes is None or res.txts is None:
        return []
    return list(zip(res.boxes.tolist(), res.txts, res.scores))


def _read_line(engine, img):
    with _call_lock:
        res = engine(img, use_det=False, use_cls=False, use_rec=True, return_word_box=False)
    if not res.txts:
        return None
    return res.txts[0], res.scores[0]


def _tiles(h, w):
    step = TILE - OVERLAP
    for y in range(0, max(h - OVERLAP, 1), step):
        for x in range(0, max(w - OVERLAP, 1), step):
            yield x, y


def _active_tiles(img):
    h, w = img.shape[:2]
    return [(x, y) for x, y in _tiles(h, w) if img[y:y + TILE, x:x + TILE].mean() <= BLANK_THRESHOLD]


def _rgb(a):
    return np.ascontiguousarray(np.stack([a] * 3, axis=-1))


def _zoom(gray):
    """Enlarge a crop before recognition so small tags stay legible."""
    if ZOOM == 1 or gray.size == 0:
        return gray
    img = Image.fromarray(gray).resize((max(1, gray.shape[1] * ZOOM), max(1, gray.shape[0] * ZOOM)), Image.Resampling.LANCZOS)
    return np.asarray(img)


def _detect(img, progress):
    engine = _ocr_engine()
    tiles = _active_tiles(img)
    out = []
    for i, (x, y) in enumerate(tiles):
        crop = _zoom(img[y:y + TILE, x:x + TILE])
        for box, text, score in _read_full(engine, _rgb(crop)):
            score = float(score)
            if score < MIN_SCORE or not text.strip():
                continue
            xs = [p[0] / ZOOM + x for p in box]
            ys = [p[1] / ZOOM + y for p in box]
            out.append({"text": text.strip(), "score": round(score, 3),
                        "box": [min(xs), min(ys), max(xs), max(ys)], "rot": 0})
        if progress:
            progress((i + 1) / len(tiles) * 0.9)
    return out


def _is_tall(t):
    x0, y0, x1, y1 = t["box"]
    return (y1 - y0) > 1.5 * (x1 - x0)


def _rank(text, score):
    t = text.replace(" ", "").upper()
    return score + (0.5 if TAG_LIKE.search(t) else 0.0)


def _reread_vertical(img, tokens, progress):
    """Vertical labels can come back reversed; re-read each one in both rotations and keep the best."""
    engine = _ocr_engine()
    H, W = img.shape[:2]
    tall = [t for t in tokens if _is_tall(t)]
    for i, t in enumerate(tall):
        x0, y0, x1, y1 = (int(v) for v in t["box"])
        pad = 4
        crop = _zoom(img[max(0, y0 - pad):min(H, y1 + pad), max(0, x0 - pad):min(W, x1 + pad)])
        best = (t["text"], t["score"], _rank(t["text"], t["score"]))
        for k in (-1, 1):
            res = _read_line(engine, _rgb(np.rot90(crop, k=k)))
            if res:
                text, score = res[0].strip(), float(res[1])
                r = _rank(text, score)
                if text and r > best[2]:
                    best = (text, score, r)
        t["text"], t["score"] = best[0], round(best[1], 3)
        t["rot"] = 90
        if progress:
            progress(0.9 + 0.1 * (i + 1) / len(tall))
    return tokens


def _overlap(a, b):
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    if not inter:
        return 0.0
    area = lambda r: max((r[2] - r[0]) * (r[3] - r[1]), 1)
    return inter / min(area(a), area(b))


def _dedupe(tokens):
    """Remove duplicates produced by overlapping tiles; keep the longest / best text."""
    tokens = sorted(tokens, key=lambda t: (-len(t["text"]), -t["score"]))
    kept = []
    for t in tokens:
        key = t["text"].replace(" ", "")
        if any(_overlap(t["box"], k["box"]) > 0.6 and key in k["text"].replace(" ", "") for k in kept):
            continue
        kept.append(t)
    return kept


def _join_words(parts):
    """Words from one detected line, with a space only where there is a visible gap between them."""
    text, prev_end = "", None
    for word, _, box in parts:
        if not word.strip():
            continue
        xs, ys = [p[0] for p in box], [p[1] for p in box]
        if prev_end is not None and min(xs) - prev_end > 0.32 * (max(ys) - min(ys)):
            text += " "
        text += word.strip()
        prev_end = max(xs)
    return text


def read_document(rgb):
    """One pass over an upright document page (a table, not a drawing): [{text, score, box}].

    The recogniser often drops spaces in English text; its word boxes are used to put them back. The orientation
    classifier is off: it flips some lines of dense tables upside down."""
    engine = _ocr_engine()
    with _call_lock:
        res = engine(np.ascontiguousarray(rgb), use_det=True, use_cls=False, use_rec=True, return_word_box=True)
    if res.boxes is None or res.txts is None:
        return []
    words = res.word_results or [None] * len(res.txts)
    out = []
    for box, text, score, parts in zip(res.boxes.tolist(), res.txts, res.scores, words):
        if parts:
            text = _join_words(parts)
        text = unicodedata.normalize("NFKC", text)
        if float(score) < MIN_SCORE or not text.strip():
            continue
        xs, ys = [p[0] for p in box], [p[1] for p in box]
        out.append({"text": text.strip(), "score": round(float(score), 3), "box": [min(xs), min(ys), max(xs), max(ys)]})
    return out


def extract_text(page, progress=None, use_cache=True):
    """Return (tokens, method) where tokens are [{text, score, box, rot}] in image pixels."""
    words = page.pdf_words
    if len(words) >= 80:
        if progress:
            progress(1.0)
        return [{"text": w["text"], "score": 1.0, "box": w["box"], "rot": 0} for w in words], "pdf-text"

    img = page.gray
    key = hashlib.sha256(img.tobytes()).hexdigest()[:24]
    cache_file = CACHE_DIR / f"{key}.json"
    if use_cache and cache_file.exists():
        if progress:
            progress(1.0)
        return json.loads(cache_file.read_text(encoding="utf-8")), "ocr-cache"

    tokens = _dedupe(_detect(img, progress))
    tokens = _reread_vertical(img, tokens, progress)
    tokens += [{"text": w["text"], "score": 1.0, "box": w["box"], "rot": 0} for w in words]
    cache_file.write_text(json.dumps(tokens), encoding="utf-8")
    return tokens, "ocr"
