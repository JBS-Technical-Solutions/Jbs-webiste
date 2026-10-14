"""Load an uploaded P&ID (PDF or image) as a page image plus any embedded PDF text."""

import io
from dataclasses import dataclass, field
from pathlib import Path

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


class Drawing:
    """An open upload. Pages are rendered one at a time so a few hundred sheets do not sit in memory together."""

    def __init__(self, doc, dpi, image: PageImage | None, raster=None, page_count: int | None = None):
        self.doc = doc
        self.dpi = dpi
        self._image = image
        self._raster = raster
        if page_count is not None:
            self.page_count = page_count
        elif image is not None:
            self.page_count = 1
        else:
            self.page_count = doc.page_count

    def load_page(self, index: int) -> PageImage:
        if self._raster is not None:
            self._raster.seek(index)
            return _raster_page(self._raster)
        if self._image is not None:
            return self._image
        return _pdf_page(self.doc[index], self.dpi, self.page_count)

    def close(self):
        if self.doc is not None:
            self.doc.close()
            self.doc = None
        if self._raster is not None:
            self._raster.close()
            self._raster = None


def open_drawing(data: bytes, filename: str, dpi: int) -> Drawing:
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in SUPPORTED:
        raise ValueError(f"Unsupported file type '{ext}'. Upload a PDF or an image (PNG, JPG, TIFF).")
    if ext != ".pdf":
        return Drawing(None, dpi, _load_image(data))
    doc = pymupdf.open(stream=data, filetype="pdf")
    if doc.page_count == 0:
        doc.close()
        raise ValueError("The PDF has no pages.")
    return Drawing(doc, dpi, None)


def load(data: bytes, filename: str, dpi: int, page_index: int = 0) -> PageImage:
    drawing = open_drawing(data, filename, dpi)
    try:
        return drawing.load_page(min(page_index, drawing.page_count - 1))
    finally:
        drawing.close()


def _ext(filename: str) -> str:
    return "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def describe_drawing(path, filename: str) -> dict:
    """Page count only. A PDF's pages and a multi-page image's frames are each one drawing."""
    ext = _ext(filename)
    if ext not in SUPPORTED:
        raise ValueError(f"Unsupported file type '{ext}'. Upload a PDF or an image (PNG, JPG, TIFF).")
    if ext == ".pdf":
        doc = pymupdf.open(path)
        try:
            pages = doc.page_count
        finally:
            doc.close()
        if pages <= 0:
            raise ValueError(f"'{filename}' has no pages.")
        return {"kind": "pdf", "pages": pages}
    img = Image.open(path)
    try:
        pages = int(getattr(img, "n_frames", 1) or 1)
    finally:
        img.close()
    if pages <= 0:
        raise ValueError(f"'{filename}' has no pages.")
    return {"kind": "image", "pages": pages}


def open_drawing_path(path, filename: str, dpi: int) -> Drawing:
    """Open a drawing already saved on disk, so a few hundred uploads are not all held in memory."""
    ext = _ext(filename)
    if ext not in SUPPORTED:
        raise ValueError(f"Unsupported file type '{ext}'. Upload a PDF or an image (PNG, JPG, TIFF).")
    if ext == ".pdf":
        doc = pymupdf.open(path)
        if doc.page_count == 0:
            doc.close()
            raise ValueError(f"'{filename}' has no pages.")
        return Drawing(doc, dpi, None)
    raster = Image.open(path)
    pages = int(getattr(raster, "n_frames", 1) or 1)
    if pages <= 0:
        raster.close()
        raise ValueError(f"'{filename}' has no pages.")
    if pages == 1:
        page = _raster_page(raster)
        raster.close()
        return Drawing(None, dpi, page)
    return Drawing(None, dpi, None, raster=raster, page_count=pages)


def _pdf_page(page, dpi, page_count):
    words = page.get_text("words")
    # A text layer means the rule engine can read the sheet without a full-resolution bitmap.
    # Hundreds of drawings then stay small: only a preview image is rendered.
    if len(words) >= 80:
        dpi = min(dpi, 120)
    longest_pt = max(page.rect.width, page.rect.height) or 1
    dpi = min(dpi, int((1800 if len(words) >= 80 else MAX_IMAGE_SIDE) * 72 / longest_pt))
    pix = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY, alpha=False)
    gray = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width).copy()
    scale = dpi / 72
    packed = [
        {"text": w[4], "box": [w[0] * scale, w[1] * scale, w[2] * scale, w[3] * scale]}
        for w in words
    ]
    return PageImage(gray=gray, dpi=dpi, pdf_words=packed, page_count=page_count)


def blank_png() -> bytes:
    """Placeholder preview when one sheet inside a large PDF cannot be rendered."""
    buf = io.BytesIO()
    Image.new("L", (800, 520), 255).save(buf, format="PNG")
    return buf.getvalue()


def _raster_page(img: Image.Image) -> PageImage:
    frame = img.convert("L")
    scale = MAX_IMAGE_SIDE / max(frame.size)
    if scale < 1:
        frame = frame.resize((round(frame.width * scale), round(frame.height * scale)), Image.LANCZOS)
    elif max(frame.size) < 2500:
        up = 2500 / max(frame.size)
        frame = frame.resize((round(frame.width * up), round(frame.height * up)), Image.LANCZOS)
    return PageImage(gray=np.array(frame), dpi=0)


def _load_image(data):
    img = Image.open(io.BytesIO(data))
    try:
        return _raster_page(img)
    finally:
        img.close()
