"""End-to-end API check: run a P&ID through a running server and download both exports.

Usage: python scripts/smoke_test.py [--file pid.pdf] [--spec spec.xlsx] [--matrix matrix.xlsx]
                                    [--optional pfd.pdf ...] [--node-mode auto|user] [--base http://localhost:8000]

Without --file the first bundled sample drawing is used; without --spec / --matrix the downloadable templates are used.
"""

import argparse
import json
import sys
import time
from pathlib import Path

import httpx

BACKEND = Path(__file__).resolve().parent.parent


def _wait(c, job, until):
    t0 = time.time()
    while job["status"] not in until:
        time.sleep(2)
        job = c.get(f"/api/jobs/{job['id']}").json()
        print(f"  {time.time() - t0:5.1f}s {job['status']:8} {job['stage']:8} {job['progress']:.2f}")
    if job["status"] == "error":
        print("ERROR:", job["error"])
        sys.exit(1)
    return job


def _doc(c, path, template):
    if path:
        p = Path(path)
        return p.name, p.read_bytes()
    r = c.get(f"/api/templates/{template}")
    r.raise_for_status()
    return template, r.content


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("--file")
    ap.add_argument("--spec")
    ap.add_argument("--matrix")
    ap.add_argument("--optional", nargs="*", default=[])
    ap.add_argument("--node-mode", default="auto", choices=("auto", "user"))
    ap.add_argument("--mode", default="rules", choices=("rules", "ai"))
    ap.add_argument("--provider", default="")
    ap.add_argument("--out", default=str(BACKEND / "data" / "smoke"))
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    with httpx.Client(base_url=args.base, timeout=120) as c:
        print("health:", c.get("/api/health").json())
        pid = Path(args.file) if args.file else sorted(p for p in (BACKEND / "samples").glob("*") if p.is_file())[0]
        spec, matrix = _doc(c, args.spec, "piping-spec.xlsx"), _doc(c, args.matrix, "risk-matrix.xlsx")
        for kind, (name, data) in (("piping-spec", spec), ("risk-matrix", matrix)):
            r = c.post(f"/api/documents/{kind}", files={"file": (name, data)})
            print(f"check {kind}:", r.status_code, r.json().get("summary") or r.json())
            r.raise_for_status()

        files = [("file", (pid.name, pid.read_bytes())), ("piping_spec", spec), ("risk_matrix", matrix)]
        files += [("optional_docs", (Path(p).name, Path(p).read_bytes())) for p in args.optional]
        study = json.dumps({"project": "Smoke test", "client": "JBS Technical Solutions"})
        form = {"mode": args.mode, "provider": args.provider, "study": study, "node_mode": args.node_mode}
        r = c.post("/api/jobs", files=files, data=form)
        if r.status_code >= 400:
            print("ERROR:", r.status_code, r.text)
            sys.exit(1)
        job = r.json()
        print("job:", job["id"], "stages:", [s["id"] for s in job["stages"]])

        if args.node_mode == "user":
            job = _wait(c, job, ("review", "error"))
            proposed = job["review"]["proposed_nodes"]
            print("proposed nodes:", [(n["title"], n["tags"]) for n in proposed])
            r = c.post(f"/api/jobs/{job['id']}/nodes", json={"nodes": proposed})
            r.raise_for_status()
            job = r.json()

        job = _wait(c, job, ("done", "error"))
        res = job["result"]
        print("warnings:", job["warnings"])
        print("stats:", res["stats"])
        print("timings:", res["timings"], "method:", res["text_method"])
        print("matrix:", res["worksheet"]["risk_matrix"]["name"], "| refs:", res["worksheet"]["study"]["reference_documents"])
        img = c.get(res["image"]["url"])
        print("image:", img.status_code, len(img.content), "bytes")
        (out / f"job-{job['id']}.json").write_text(json.dumps(job, indent=2), encoding="utf-8")
        for fmt in ("docx", "xlsx"):
            r = c.post(f"/api/export/{fmt}", json={"worksheet": res["worksheet"], "extraction": res["extraction"]})
            r.raise_for_status()
            name = r.headers["content-disposition"].split('filename="')[1].rstrip('"')
            (out / name).write_bytes(r.content)
            print(f"export {fmt}: {len(r.content)} bytes -> {out / name}")


if __name__ == "__main__":
    main()
