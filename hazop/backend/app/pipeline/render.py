"""Load an uploaded P&ID (PDF or image) as a page image plus any embedded PDF text."""

import io
from dataclasses import dataclass, field

import numpy as np
import pymupdf
from PIL import Image

SUPPORTED = {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}
MAX_IMAGE_SIDE = 6000


@dataclass
class PageImage:
    gray: np.ndarray  # H x W uint8
    dpi: int
    pdf_words: list = field(default_factory=list)  # [{text, box:[x0,y0,x1,y1]}] in image pixels
    page_count: int = 1

    @property
    def size(self):
        h, w = self.gray.shape[:2]
        return w, h

    def png_bytes(self, max_side=2400):
        img = Image.fromarray(self.gray)
        scale = max_side / max(img.size)
        if scale < 1:
            img = img.resize((round(img.width * scale), round(img.height * scale)), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        return buf.getvalue()


def load(data: bytes, filename: str, dpi: int, page_index: int = 0) -> PageImage:
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in SUPPORTED:
        raise ValueError(f"Unsupported file type '{ext}'. Upload a PDF or an image (PNG, JPG, TIFF).")
    if ext == ".pdf":
        return _load_pdf(data, dpi, page_index)
    return _load_image(data)


def _load_pdf(data, dpi, page_index):
    doc = pymupdf.open(stream=data, filetype="pdf")
    if doc.page_count == 0:
        raise ValueError("The PDF has no pages.")
    page = doc[min(page_index, doc.page_count - 1)]
    longest_pt = max(page.rect.width, page.rect.height)
    dpi = min(dpi, int(MAX_IMAGE_SIDE * 72 / longest_pt))
    pix = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY, alpha=False)
    gray = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width).copy()
    scale = dpi / 72
    words = [
        {"text": w[4], "box": [w[0] * scale, w[1] * scale, w[2] * scale, w[3] * scale]}
        for w in page.get_text("words")
    ]
    return PageImage(gray=gray, dpi=dpi, pdf_words=words, page_count=doc.page_count)


def _load_image(data):
    img = Image.open(io.BytesIO(data))
    img = img.convert("L")
    scale = MAX_IMAGE_SIDE / max(img.size)
    if scale < 1:
        img = img.resize((round(img.width * scale), round(img.height * scale)), Image.LANCZOS)
    elif max(img.size) < 2500:
        up = 2500 / max(img.size)
        img = img.resize((round(img.width * up), round(img.height * up)), Image.LANCZOS)
    return PageImage(gray=np.array(img), dpi=0)
