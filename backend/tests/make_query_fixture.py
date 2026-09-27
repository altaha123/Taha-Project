"""
Regenerate frontend/tests/fixtures/query.json from the real endpoints.

A handful of made-up companies are put through fundamentals_query's real
arithmetic-free path (run_rows over fixed rows), and the responses the page
will ask for are saved — field list, a few queries, a sort and a bad query's
400 — so a key renamed in fundamentals_query.py or main.py fails the browser
test instead of passing against a stale JSON literal.

    python backend/tests/make_query_fixture.py
"""

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
OUT = HERE.parents[1] / "frontend" / "tests" / "fixtures" / "query.json"

ROWS = [
    {"symbol": "ACME", "name": "Acme Chemicals Ltd", "industry": "Chemicals", "fy": "FY26",
     "price": 812.5, "market_cap": 12500.0, "pe": 24.1, "roce": 28.4, "roe": 21.2,
     "sales_growth_3y": 18.5, "debt_to_equity": 0.12, "sales": 4200.0},
    {"symbol": "BETA", "name": "Beta Pharma Ltd", "industry": "Pharmaceuticals", "fy": "FY26",
     "price": 1420.0, "market_cap": 38000.0, "pe": 31.0, "roce": 22.0, "roe": 17.5,
     "sales_growth_3y": 12.2, "debt_to_equity": 0.3, "sales": 9100.0},
    {"symbol": "GAMMA", "name": "Gamma & Sons Ltd", "industry": "Textiles", "fy": "FY26",
     "price": 95.2, "market_cap": 640.0, "pe": None, "roce": 9.0, "roe": -3.0,
     "sales_growth_3y": -2.0, "debt_to_equity": 1.4, "sales": 800.0},
    {"symbol": "DELTA", "name": "Delta Infra Ltd", "industry": "Construction", "fy": "FY26",
     "price": None, "market_cap": None, "pe": None, "roce": 26.0, "roe": None,
     "sales_growth_3y": 30.0, "debt_to_equity": None, "sales": 1500.0},
]


def main():
    import conftest  # noqa: F401  (offline stubs for the modules main imports)
    from fastapi.testclient import TestClient
    import fundamentals_query as Q
    import main as app_main

    Q.snapshot = lambda: (ROWS, "2026-09-27T06:00:00+00:00")
    c = TestClient(app_main.app)
    out = {"fields": c.get("/fundamentals/query/fields").json(), "queries": {}}
    asks = [
        {"q": "ROCE > 20\nDebt to equity < 0.5\nMarket cap > 1000"},
        {"q": "ROCE > 20"},
        {"q": "ROCE > 20", "sort": "roe", "order": "desc"},
        {"q": "ROCE > 20", "sort": "roe", "order": "asc"},
        {"q": "ROEE > 15"},
        {"q": "ROE > 100"},
    ]
    for a in asks:
        params = {"q": a["q"], "limit": "50", "offset": "0"}
        if a.get("sort"):
            params.update(sort=a["sort"], order=a["order"])
        r = c.get("/fundamentals/query", params=params)
        key = "%s|%s|%s" % (a["q"], a.get("sort", ""), a.get("order", ""))
        out["queries"][key] = {"status": r.status_code, "body": r.json()}
    OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print("wrote", OUT)


if __name__ == "__main__":
    main()
