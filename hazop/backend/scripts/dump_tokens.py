"""Debug helper: run text extraction on a P&ID and dump tokens to JSON.

Usage: python -m scripts.dump_tokens <file> [out.json]
"""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import RENDER_DPI  # noqa: E402
from app.pipeline import ocr, render  # noqa: E402


def main():
    src = Path(sys.argv[1])
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else src.with_suffix(".tokens.json")
    page = render.load(src.read_bytes(), src.name, RENDER_DPI)
    t0 = time.time()
    tokens, method = ocr.extract_text(page, progress=None)
    print(f"{method}: {len(tokens)} tokens in {time.time() - t0:.1f}s, image {page.size}")
    out.write_text(json.dumps(tokens, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"written {out}")


if __name__ == "__main__":
    main()
