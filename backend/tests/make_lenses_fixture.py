"""
Regenerate frontend/tests/fixtures/lenses.json from the real modules.

Three made-up companies are written into throwaway fundamentals and lens
databases, the real nightly compute runs over them, and the real endpoints'
responses are saved. The browser test reads those responses, so a key renamed
in main.py or lens_engine.py fails the browser test instead of passing against
a stale JSON literal.

    python backend/tests/make_lenses_fixture.py
"""

import datetime as dt
import json
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
OUT = HERE.parents[1] / "frontend" / "tests" / "fixtures" / "lenses.json"


def main():
    tmp = tempfile.mkdtemp()
    os.environ["ALTAHA_FUNDAMENTALS_DB"] = os.path.join(tmp, "f.db")
    os.environ["ALTAHA_LENS_DB"] = os.path.join(tmp, "l.db")
    import conftest  # noqa: F401  (offline stubs for the modules main imports)
    import fundamentals_store as fs
    import lens_store as ls
    import lens_job
    import main as api
    from fastapi.testclient import TestClient
    from test_lens_metrics import grower, balance, cashflow, _load

    rows = {"income_statement": [], "balance_sheet": [], "cash_flow": []}
    # GROW: fast growth, shrinking share count, owner-run.
    rows["income_statement"] += grower("GROW")
    rows["balance_sheet"] += [balance("GROW", y, 200 + 20 * i, 80, 40, 150, capital=c)
                              for i, (y, c) in enumerate(((2023, 10.0), (2024, 9.6),
                                                          (2025, 9.2), (2026, 8.8)))]
    rows["cash_flow"] += [cashflow("GROW", y, 20.0, 5.0) for y in range(2021, 2027)]
    # STEADY: slower, flat capital, promoter below half.
    rows["income_statement"] += grower("STEADY", g=0.08)
    rows["balance_sheet"] += [balance("STEADY", y, 300, 90, 50, 200, capital=20.0)
                              for y in range(2023, 2027)]
    # NEWCO: two years of filings only.
    rows["income_statement"] += grower("NEWCO", start=2025, n=2)
    _load(fs, rows)
    ls.upsert_company({"symbol": "GROW", "company": "Grow Industries Ltd",
                       "industry": "Specialty Chemicals", "issued_shares": 1e8, "last_price": 250.0})
    ls.upsert_company({"symbol": "STEADY", "company": "Steady Foods Ltd",
                       "industry": "Packaged Foods", "issued_shares": 5e7, "last_price": 90.0})
    ls.upsert_shareholding([
        {"symbol": "GROW", "period_end": "2026-06-30", "promoter_pct": 61.2, "fii_pct": 6.1,
         "dii_pct": 5.4, "pledged": 0},
        {"symbol": "GROW", "period_end": "2025-06-30", "promoter_pct": 59.8, "fii_pct": 6.0,
         "dii_pct": 5.0, "pledged": 0},
        {"symbol": "STEADY", "period_end": "2026-06-30", "promoter_pct": 44.0, "fii_pct": 18.0,
         "dii_pct": 12.0, "pledged": 1},
        {"symbol": "STEADY", "period_end": "2025-06-30", "promoter_pct": 45.0, "fii_pct": 17.0,
         "dii_pct": 12.0, "pledged": 1}])
    lens_job.compute(today=dt.date(2026, 9, 1), prices={}, universe_size=3)

    client = TestClient(api.app)
    got = {"index": client.get("/api/lenses").json(),
           "convergence": {str(n): client.get("/api/lenses/convergence?min_lenses=%d" % n).json()
                           for n in (2, 3, 4)},
           "stock": {s: client.get("/api/lenses/stock/" + s).json()
                     for s in ("GROW", "STEADY", "NOPE")},
           "lens": {}}
    for lens in got["index"]["lenses"]:
        got["lens"][lens["id"]] = client.get("/api/lenses/" + lens["id"]).json()
    OUT.write_text(json.dumps(got, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print("wrote", OUT)


if __name__ == "__main__":
    main()
