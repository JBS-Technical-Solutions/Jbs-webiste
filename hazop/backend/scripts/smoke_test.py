"""End-to-end API check: run the sample P&ID through a running server and download all exports.

Usage: python scripts/smoke_test.py [--file path/to/pid.pdf] [--base http://localhost:8000]
"""

import argparse
import json
import sys
import time
from pathlib import Path

import httpx


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("--file")
    ap.add_argument("--mode", default="rules", choices=("rules", "ai"))
    ap.add_argument("--provider", default="")
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent.parent / "data" / "smoke"))
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    with httpx.Client(base_url=args.base, timeout=60) as c:
        print("health:", c.get("/api/health").json())
        study = json.dumps({"project": "Smoke test", "client": "Chevron"})
        form = {"mode": args.mode, "provider": args.provider, "study": study}
        if args.file:
            p = Path(args.file)
            r = c.post("/api/jobs", files={"file": (p.name, p.read_bytes())}, data=form)
        else:
            r = c.post("/api/jobs/sample", data=form)
        r.raise_for_status()
        job = r.json()
        print("job:", job["id"])
        t0 = time.time()
        while job["status"] not in ("done", "error"):
            time.sleep(2)
            job = c.get(f"/api/jobs/{job['id']}").json()
            print(f"  {time.time() - t0:5.1f}s {job['status']:8} {job['stage']:8} {job['progress']:.2f}")
        if job["status"] == "error":
            print("ERROR:", job["error"])
            sys.exit(1)
        res = job["result"]
        print("warnings:", job["warnings"])
        print("stats:", res["stats"])
        print("timings:", res["timings"], "method:", res["text_method"])
        img = c.get(res["image"]["url"])
        print("image:", img.status_code, len(img.content), "bytes")
        for fmt in ("docx", "xlsx", "json"):
            r = c.post(f"/api/export/{fmt}", json={"worksheet": res["worksheet"], "extraction": res["extraction"]})
            r.raise_for_status()
            name = r.headers["content-disposition"].split('filename="')[1].rstrip('"')
            (out / name).write_bytes(r.content)
            print(f"export {fmt}: {len(r.content)} bytes -> {out / name}")


if __name__ == "__main__":
    main()
