"""
Writes the Strategy lab fixture the browser test serves for /strategies.

The report is the real one, from strategy_lab.run(), on a seeded synthetic
price walk, so the page is tested against exactly the shape the server
sends. Rebuild it after changing that shape:

    python backend/tests/make_strategy_lab_fixture.py
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

import strategy_lab                      # noqa: E402
from test_strategy_lab import walk       # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.dirname(HERE)), "frontend", "tests", "fixtures",
                   "strategy-lab-demo.json")


def build():
    report = strategy_lab.run(walk(n=3200, seed=11, drift=0.0005), "DEMO.NS", years=10, ticker="DEMO")
    report["computed_at"] = "2026-10-31T00:00:00Z"
    return report


if __name__ == "__main__":
    import math

    def clean(o):
        if isinstance(o, dict):
            return {k: clean(v) for k, v in o.items()}
        if isinstance(o, list):
            return [clean(v) for v in o]
        if isinstance(o, float) and (math.isnan(o) or math.isinf(o)):
            return None
        if hasattr(o, "item"):
            return clean(o.item())
        return o

    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(clean(build()), fh, separators=(",", ":"))
    print(OUT, os.path.getsize(OUT), "bytes")
