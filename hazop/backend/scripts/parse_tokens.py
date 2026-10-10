"""Debug helper: parse a token dump and print extracted entities.

Usage: python scripts/parse_tokens.py <tokens.json> <width> <height>
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.pipeline import parse  # noqa: E402


def main():
    tokens = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    ext = parse.parse(tokens, (int(sys.argv[2]), int(sys.argv[3])))
    for key in ("equipment", "lines", "instruments", "valves", "connectors", "spec_breaks"):
        print(f"\n== {key} ({len(ext[key])})")
        for e in ext[key]:
            e = {k: v for k, v in e.items() if k not in ("box", "boxes")}
            print("  ", json.dumps(e, ensure_ascii=False))
    print("\nflags", ext["flags"])

    if "--rules" in sys.argv:
        from app.pipeline import rules

        result = rules.generate(ext)
        print("\n== study", result["study"])
        for n in result["nodes"]:
            print(f"\n### Node {n['id']}: {n['title']}\n  boundary: {n['boundary']}\n  intent: {n['design_intent']}"
                  f"\n  design: {n['design_conditions']}")
            for d in n["deviations"]:
                print(f"  -- {d['deviation']}")
                for r in d["rows"]:
                    print(f"     * {r['cause']}\n       C{r['c']} L{r['l']} {r['risk']['code']} sg={r['tags']} rec={r['recommendations']}")
        print("\n== recommendations")
        for k, v in result["recommendations"].items():
            print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
