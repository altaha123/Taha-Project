"""
Regenerate frontend/tests/fixtures/delivery-reliance.json.

The browser test needs a /delivery payload, and hand-writing one is how a
fixture drifts from the endpoint it stands for: a key renamed in special.py
keeps passing against a JSON literal that still carries the old name, and the
bug ships. So the fixture is produced by the real `daily_delivery`, from a
synthetic panel in the shape `_to_panels` builds, and checked in.

    python backend/tests/make_delivery_fixture.py

The panel is deterministic (fixed seed) so the fixture does not churn on every
regeneration. Two sessions are deliberately damaged, because both are things
the page has to survive and neither shows up in clean data:

  · one session has a published delivery share but NO traded quantity, so the
    page must print an em dash rather than a delivered zero;
  · one session's delivered share sits far above the stock's own average, so
    the "ran above its 20-session average" shading has something to shade.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

import numpy as np
import pandas as pd

import special

SYMS = ["RELIANCE", "TCS", "INFY"]
OUT = ROOT / "frontend" / "tests" / "fixtures" / "delivery-reliance.json"


def build_panel():
    days = pd.bdate_range(end="2026-09-18", periods=300)
    rng = np.random.default_rng(1729)

    def frame(lo, hi):
        return pd.DataFrame(rng.uniform(lo, hi, (len(days), len(SYMS))),
                            index=days, columns=SYMS).astype("float32")

    P = {"deliv": frame(38, 58), "qty": frame(2e6, 9e6), "vwap": frame(1350, 1450),
         "close": frame(1350, 1450), "high": frame(1450, 1500), "low": frame(1300, 1350)}

    # A clear, checkable latest session: 2,000,000 traded at 66.00% delivered
    # is exactly 1,320,000 delivered, which the browser test asserts on screen.
    P["deliv"].iloc[-1, 0] = 66.00
    P["qty"].iloc[-1, 0] = 2_000_000
    # A session with a share but no traded quantity.
    P["qty"].iloc[-3, 0] = np.nan
    return P


def main():
    P = build_panel()
    special._state["panel"] = P
    payload = special.daily_delivery("RELIANCE", days=60)
    assert payload["available"] is True, payload
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"{OUT.relative_to(ROOT)}: {payload['sessions_returned']} sessions, "
          f"as of {payload['as_of']}")


if __name__ == "__main__":
    main()
