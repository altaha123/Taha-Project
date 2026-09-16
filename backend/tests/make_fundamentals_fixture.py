"""
Regenerate frontend/tests/fixtures/fundamentals-reliance.json.

The browser test needs a /fundamentals payload, and hand-writing one is how a
fixture drifts from the endpoint it stands for: a key renamed in
fundamentals.py keeps passing against a JSON literal that still has the old
name, and the bug ships. So the fixture is produced by the real module, from
stubbed filings, and checked in.

    python backend/tests/make_fundamentals_fixture.py

Reliance's real figures for the last six quarters, with one deliberate
alteration: the June 2025 quarter is made a loss, so the turnaround wording —
which must never be a percentage — is exercised on screen and not only in a
unit test. Standalone rows are included at roughly the real ratio to the
consolidated ones, because the basis-mixing bug is invisible in a fixture that
only has one basis.
"""

import json
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

OUT = ROOT / "frontend" / "tests" / "fixtures" / "fundamentals-reliance.json"

ENDS = ["2026-06-30", "2026-03-31", "2025-12-31",
        "2025-09-30", "2025-06-30", "2025-03-31"]
STARTS = ["2026-04-01", "2026-01-01", "2025-10-01",
          "2025-07-01", "2025-04-01", "2025-01-01"]
REVENUE = [269496e7, 264573e7, 248160e7, 240357e7, 243832e7, 236533e7]
PAT = [22290e7, 22611e7, 21930e7, 18165e7, -4300e7, 18951e7]


def _quarter(i, consolidated):
    r = REVENUE[i] * (1.0 if consolidated else 0.45)
    p = PAT[i] * (1.0 if consolidated else 0.42)
    return {
        "to": ENDS[i], "from": STARTS[i], "consolidated": consolidated,
        "filed_at": "20-Jul-2026 19:41:02",
        "company": "Reliance Industries Limited", "audited": "Unaudited",
        "source_url": "https://nsearchives.nseindia.com/corporate/xbrl/RESULT_%s_%s.xml"
                      % (ENDS[i], "C" if consolidated else "S"),
        "revenue": r, "other_income": r * 0.0185, "total_income": r * 1.0185,
        "materials": r * 0.4058, "employee_cost": r * 0.0290,
        "finance_cost": r * 0.0233, "depreciation": r * 0.0509,
        "other_expenses": r * 0.1613, "total_expenses": r * 0.9086,
        "ebitda": r * 0.1708, "pbt_before_exceptional": p * 1.294,
        "exceptional": 0.0, "pbt": p * 1.294, "tax": p * 0.294, "pat": p,
        "eps_basic": round(p / 1.353e9, 2),
    }


def main():
    quarters = [_quarter(i, con) for i in range(len(ENDS)) for con in (True, False)]

    stub = types.ModuleType("xbrl")
    stub.available = lambda: True
    stub.filings = lambda symbol: quarters

    def statements(symbol, limit=8, consolidated=None):
        want = [q for q in quarters if consolidated is None
                or q.get("consolidated") is consolidated]
        return (want or quarters)[:limit]

    stub.statements = statements
    sys.modules["xbrl"] = stub

    import fundamentals
    payload = fundamentals.series("RELIANCE", quarters=6)
    assert payload["available"] and payload["count"] == 6, payload.get("message")
    assert payload["basis"] == "consolidated"
    assert payload["rows"][0]["yoy"]["pat"]["kind"] == "loss_to_profit"

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=1) + "\n", encoding="utf-8")
    print("wrote %s (%d quarters, %s)"
          % (OUT.relative_to(ROOT), payload["count"], payload["basis"]))


if __name__ == "__main__":
    main()
