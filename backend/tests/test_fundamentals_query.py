"""
The query screener: a typed condition applied to every stored company.

What matters most is what a reader cannot see: a missing figure read as zero,
a loss-base growth rate printed as a percentage, a text compared as a number,
or a query that runs something other than what was typed.
"""

import datetime as dt
import sys

import pytest

import fundamentals_query as Q

TODAY = dt.date(2026, 9, 25)


# ── Parsing ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("text,fields", [
    ("ROE > 15", ["roe"]),
    ("Return on equity > 15 AND debt to equity < 0.5", ["roe", "debt_to_equity"]),
    ("Market capitalization > 1,000 crore", ["market_cap"]),
    ("ROCE > 20\nMarket cap > 500", ["roce", "market_cap"]),
    ("(Sales growth 3Y > 15 OR Profit growth 3Y > 20) AND PE < 30",
     ["sales_growth_3y", "profit_growth_3y", "pe"]),
    ("Market cap / Sales < 2", ["market_cap", "sales"]),
    ('Industry contains "bank" AND NOT ROE < 10', ["industry", "roe"]),
    ("roe>=15%", ["roe"]),
])
def test_queries_that_parse(text, fields):
    _tree, used = Q.parse(text)
    assert used == fields


@pytest.mark.parametrize("text,words", [
    ("", "Type a condition"),
    ("ROEE > 15", "Did you mean 'ROE'"),
    ("ROE >", "ends where"),
    ("ROE > 15 AND", "ends where"),
    ("(ROE > 15", "not closed"),
    ("ROE > 15)", "without a matching"),
    ("ROE", "needs a comparison"),
    ("ROE > 15 ROCE > 3", "Expected AND or OR"),
    ("Industry > 5", "Text can only be compared"),
    ('Industry contains 5', "CONTAINS works on text"),
    ("ROE > 15 AND 5", "must be a comparison"),
    ("ROE > 15 # 3", "not something"),
    ('Industry = "bank', "not closed"),
])
def test_queries_that_do_not(text, words):
    with pytest.raises(Q.QueryError) as e:
        Q.parse(text)
    assert words in e.value.message


def test_a_newline_is_and_but_or_can_continue_a_line():
    tree, _ = Q.parse("ROE > 15\nOR\nROCE > 20")
    assert tree[0] == "or"
    tree, _ = Q.parse("ROE > 15\n\nROCE > 20")
    assert tree[0] == "and"


def test_every_label_and_alias_resolves_to_its_own_field():
    for f in Q.fields():
        assert Q.resolve(f["label"]) == f["id"]
        assert Q.resolve(f["id"]) == f["id"]


# ── Three-valued logic ───────────────────────────────────────────────────────

ROWS = [
    {"symbol": "AAA", "name": "Aaa Ltd", "industry": "Banks", "roe": 20.0, "roce": 25.0,
     "market_cap": 5000.0, "sales": 1000.0, "debt_to_equity": 0.1},
    {"symbol": "BBB", "name": "Bbb Ltd", "industry": "Pharmaceuticals", "roe": 12.0,
     "roce": None, "market_cap": 800.0, "sales": 900.0, "debt_to_equity": 1.2},
    {"symbol": "CCC", "name": "Ccc Ltd", "industry": None, "roe": None, "roce": 30.0,
     "market_cap": None, "sales": 0.0, "debt_to_equity": None},
]


def _syms(out):
    return [r["symbol"] for r in out["results"]]


def test_a_missing_figure_is_unknown_not_zero():
    out = Q.run_rows(ROWS, "ROE < 15")
    assert _syms(out) == ["BBB"]           # CCC has no ROE: not "less than 15"
    assert out["unknown"] == 1
    out = Q.run_rows(ROWS, "NOT ROE > 15")
    assert _syms(out) == ["BBB"]


def test_or_rescues_an_unknown_and_and_sinks_it():
    assert set(_syms(Q.run_rows(ROWS, "ROE > 15 OR ROCE > 20"))) == {"AAA", "CCC"}
    out = Q.run_rows(ROWS, "ROE > 50 AND ROCE > 50")
    assert out["count"] == 0 and out["unknown"] == 0   # false AND unknown is false


def test_division_by_zero_is_unknown():
    out = Q.run_rows(ROWS, "Market cap / Sales > 1")
    assert _syms(out) == ["AAA"]
    assert out["unknown"] == 1


def test_text_is_matched_without_case():
    assert _syms(Q.run_rows(ROWS, 'Industry = "banks"')) == ["AAA"]
    assert _syms(Q.run_rows(ROWS, 'industry contains "PHARMA"')) == ["BBB"]


def test_sorting_puts_unknowns_last_and_defaults_to_the_first_number_used():
    out = Q.run_rows(ROWS, "Sales >= 0")
    assert out["sort"] == "sales" and _syms(out) == ["AAA", "BBB", "CCC"]
    out = Q.run_rows(ROWS, "Sales >= 0", sort="roe", order="asc")
    assert _syms(out) == ["BBB", "AAA", "CCC"]
    with pytest.raises(Q.QueryError):
        Q.run_rows(ROWS, "Sales >= 0", sort="nonsense field")


def test_columns_start_with_the_fields_asked_about():
    out = Q.run_rows(ROWS, "Debt to equity < 1")
    ids = [c["id"] for c in out["columns"]]
    assert ids[0] == "debt_to_equity" and "market_cap" in ids
    out = Q.run_rows(ROWS, "Debt to equity < 1", columns=["roe", "nope", "ROE"])
    assert [c["id"] for c in out["columns"]] == ["roe"]


def test_paging():
    out = Q.run_rows(ROWS, "Sales >= 0", limit=1, offset=1)
    assert out["count"] == 3 and _syms(out) == ["BBB"]


# ── The figures, from the stored statements ──────────────────────────────────

@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("ALTAHA_FUNDAMENTALS_DB", str(tmp_path / "f.db"))
    sys.modules.pop("fundamentals_store", None)
    import fundamentals_store
    return fundamentals_store


def _year(store, sym, end, rev, pat, eps, ebitda=None):
    return store.to_row("income", {
        "symbol": sym, "company": sym.title() + " Ltd", "basis": "consolidated",
        "freq": "annual", "label": "FY%s" % end[2:4], "period_end": end, "months": 12,
        "filed_at": "2026-05-01", "source_url": "https://x/%s-%s.xml" % (sym, end)},
        {"revenue": rev * 1e7, "pat": pat * 1e7, "ebitda": (ebitda or rev * .2) * 1e7,
         "pbt": pat * 1.3e7, "pbt_before_exceptional": pat * 1.3e7,
         "finance_cost": 10e7, "eps_basic": eps})


def _quarter(store, sym, end, rev, pat, eps):
    return store.to_row("income", {
        "symbol": sym, "company": sym.title() + " Ltd", "basis": "consolidated",
        "freq": "quarterly", "label": end, "period_end": end, "months": 3,
        "filed_at": "2026-08-01", "source_url": "https://x/%s-q-%s.xml" % (sym, end)},
        {"revenue": rev * 1e7, "pat": pat * 1e7, "ebitda": rev * .25e7, "eps_basic": eps})


def _sheet(store, sym, end, assets, equity, debt, cash):
    return store.to_row("balance", {
        "symbol": sym, "company": sym.title() + " Ltd", "basis": "consolidated",
        "label": end, "period_end": end, "filed_at": "2026-05-01",
        "source_url": "https://x/%s-b-%s.xml" % (sym, end)},
        {"total_assets": assets * 1e7, "total_equity": equity * 1e7,
         "current_liabilities": assets * .2e7, "current_assets": assets * .4e7,
         "total_borrowings": debt * 1e7, "cash_and_equivalents": cash * 1e7})


def _flow(store, sym, end, cfo, capex, dividends):
    return store.to_row("cashflow", {
        "symbol": sym, "company": sym.title() + " Ltd", "basis": "consolidated",
        "label": "FY%s" % end[2:4], "period_end": end, "months": 12,
        "filed_at": "2026-05-01", "source_url": "https://x/%s-c-%s.xml" % (sym, end)},
        {"cfo": cfo * 1e7, "capex": capex * 1e7, "fcf": (cfo - capex) * 1e7,
         "dividends_paid": -dividends * 1e7})


def _fill(store):
    ends = ["2026-03-31", "2025-03-31", "2024-03-31", "2023-03-31"]
    store.upsert("income", [_year(store, "ACME", e, 1331 / 1.1 ** i, 133.1 / 1.1 ** i,
                                  13.31 / 1.1 ** i) for i, e in enumerate(ends)])
    store.upsert("income", [_quarter(store, "ACME", e, 400, 40, 4.0) for e in
                            ["2026-06-30", "2026-03-31", "2025-12-31", "2025-09-30"]]
                 + [_quarter(store, "ACME", "2025-06-30", 320, 50, 5.0)])
    store.upsert("balance", [_sheet(store, "ACME", e, 2000, 1000, 200, 300) for e in ends[:3]])
    store.upsert("cashflow", [_flow(store, "ACME", e, 200, 50, 40) for e in ends[:3]])
    # A company that lost money last year: its growth is not a percentage.
    store.upsert("income", [_year(store, "LOSS", "2026-03-31", 500, 20, 2.0),
                            _year(store, "LOSS", "2025-03-31", 450, -30, -3.0)])


def test_one_company_row(store):
    _fill(store)
    rows = Q.build(store._connect(), today=TODAY, prices={"ACME": 320.0},
                   profiles={"ACME": {"company": "Acme Ltd", "industry": "Chemicals",
                                      "issued_shares": 1e8}},
                   holdings={"ACME": [{"period_end": "2026-06-30", "promoter_pct": 55.0,
                                       "fii_pct": 10.0, "dii_pct": 5.0, "pledge_pct": 0.0}]})
    by = {r["symbol"]: r for r in rows}
    a = by["ACME"]
    assert a["name"] == "Acme Ltd" and a["industry"] == "Chemicals"
    assert a["market_cap"] == 3200.0                   # 320 × 10 crore shares
    assert a["sales"] == 1331.0 and a["net_profit"] == 133.1
    assert a["sales_growth"] == pytest.approx(10.0)
    assert a["sales_growth_3y"] == pytest.approx(10.0)
    assert a["sales_growth_5y"] is None                # four years held, not six
    assert a["roe"] == pytest.approx(13.31)
    assert a["roe_3y"] is not None
    assert a["eps_ttm"] == 16.0 and a["pe"] == 20.0     # four quarters of ₹4
    assert a["sales_ttm"] == 1600.0
    assert a["sales_growth_qtr"] == pytest.approx(25.0)
    assert a["profit_growth_qtr"] == pytest.approx(-20.0)
    assert a["debt_to_equity"] == 0.2 and a["net_debt"] == -100.0
    assert a["pb"] == 3.2
    assert a["fcf"] == 150.0 and a["fcf_3y"] == 450.0
    assert a["dividend_payout"] == pytest.approx(40 / 133.1 * 100, abs=.01)
    assert a["dividend_yield"] == pytest.approx(1.25)
    assert a["promoter_holding"] == 55.0 and a["pledged"] == 0.0

    loss = by["LOSS"]
    assert loss["profit_growth"] is None               # from a loss: not a rate
    assert loss["sales_growth"] == pytest.approx(11.11, abs=.01)
    assert loss["market_cap"] is None and loss["pe"] is None


def test_run_end_to_end(store, monkeypatch):
    _fill(store)
    monkeypatch.setattr(Q, "store", store)
    monkeypatch.setattr(Q.LM, "latest_prices", lambda: {"ACME": 320.0})
    monkeypatch.setattr(Q, "_profiles", lambda: ({"ACME": {"issued_shares": 1e8}}, {}))
    Q._cache.update(rows=None, key=None)
    out = Q.run("Sales growth > 5\nMarket cap > 1000")
    assert out["available"] and _syms(out) == ["ACME"]
    assert out["unknown"] == 1                          # LOSS has no market cap
    with pytest.raises(Q.QueryError):
        Q.run("Sales growth >")


def test_the_endpoint_reports_a_bad_query_as_400(monkeypatch):
    from fastapi.testclient import TestClient
    import main
    monkeypatch.setattr(Q, "snapshot", lambda: (ROWS, "2026-09-25T00:00:00+00:00"))
    c = TestClient(main.app)
    r = c.get("/fundamentals/query", params={"q": "ROEE > 5"})
    assert r.status_code == 400
    assert "ROE" in r.json()["error"]["suggestions"]
    r = c.get("/fundamentals/query", params={"q": "ROE > 15"})
    assert r.status_code == 200 and _syms(r.json()) == ["AAA"]
    r = c.get("/fundamentals/query/fields")
    assert any(f["id"] == "roce" for f in r.json()["fields"])
