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
    out["ai"] = ai_fixture(c)
    OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print("wrote", OUT)


AI_KEY = "fixture-admin-key"


def ai_fixture(c):
    """
    Ask AI's answers, from the real routes and the real ask(), with only the
    model scripted. The counts and the "does not run" verdict on each card are
    therefore the screener's own, exactly as the page will receive them.
    """
    import os
    from types import SimpleNamespace
    import query_assistant as A

    os.environ["ADMIN_KEY"] = AI_KEY
    os.environ["ANTHROPIC_API_KEY"] = "sk-fixture-never-sent"
    A._rows = lambda: (ROWS, "2026-09-27T06:00:00+00:00")
    usage = SimpleNamespace(input_tokens=1, output_tokens=1,
                            cache_read_input_tokens=0, cache_creation_input_tokens=0)

    def turn(blocks, stop):
        return SimpleNamespace(content=blocks, stop_reason=stop, model=A.MODEL, usage=usage)

    def final(obj):
        return turn([SimpleNamespace(type="text", text=json.dumps(obj))], "end_turn")

    script = [
        turn([SimpleNamespace(type="tool_use", id="tu_1", name="check_query",
                              input={"query": "ROCE > 20"})], "tool_use"),
        final({
            "reply": ("Three companies earn more than 20% on the capital they use.\n\n"
                      "- `ROCE` is operating profit over capital employed\n"
                      "- **Debt to equity** under 0.5 keeps borrowing light\n\n"
                      "Markup stays text: <img src=x onerror=alert(1)>"),
            "queries": [
                {"title": "High return on capital", "query": "ROCE > 20",
                 "explanation": "Every company earning more than 20% on capital employed."},
                {"title": "A typo, to show the check", "query": "ROEE > 15",
                 "explanation": "Written with a misspelt field."},
            ],
            "follow_ups": ["Make it stricter on debt"],
        }),
        final({"reply": "Add `Debt to equity < 0.3` as a second line.",
               "queries": [], "follow_ups": []}),
    ]

    class Scripted:
        beta = SimpleNamespace(messages=SimpleNamespace(create=lambda **kw: script.pop(0)))

    A._client = lambda: Scripted()
    A._asked.clear()
    h = {"X-Admin-Key": AI_KEY}
    first = [{"role": "user", "content": "Companies with a high return on capital"}]
    one = c.post("/admin/query/ai", headers=h, json={"messages": first, "query": "", "error": ""})
    second = first + [{"role": "assistant", "content": "..."},
                      {"role": "user", "content": "Make it stricter on debt"}]
    two = c.post("/admin/query/ai", headers=h, json={"messages": second, "query": "", "error": ""})
    return {
        "key": AI_KEY,
        "status": c.get("/admin/query/ai", headers=h).json(),
        "answers": [one.json(), two.json()],
        "refused": c.get("/admin/query/ai", headers={"X-Admin-Key": "wrong"}).json(),
    }


if __name__ == "__main__":
    main()
