"""
Everything else that now reads altaha_fundamentals.db instead of a provider:
the Piotroski statements, the scan's factor history, the balance sheet and
cash flow pane, the industry comparison and the quarterly screens.

The failures that matter are quiet ones: a US ticker scored on an Indian
company's statements, an overdue series scored as current, a median over two
peers, a half-year's cash flow set beside a year's, a stale company listed by
a screen.
"""

import datetime as dt
import sys

import pytest

TODAY = dt.date(2026, 9, 25)


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("ALTAHA_FUNDAMENTALS_DB", str(tmp_path / "f.db"))
    for m in ("fundamentals_store", "fundamentals_screens"):
        sys.modules.pop(m, None)
    import fundamentals_store
    return fundamentals_store


def _q(store, sym, end, rev, pat, opm=20.0, basis="consolidated", eps=10.0):
    import fundamentals as F
    e = dt.date.fromisoformat(end)
    row = store.to_row("income", {
        "symbol": sym, "company": sym.title() + " Ltd", "basis": basis,
        "freq": "quarterly", "label": F.quarter_label(e),
        "period_from": (e - dt.timedelta(days=90)).isoformat(), "period_end": end,
        "months": 3, "filed_at": "10-%s 18:00:00" % (e + dt.timedelta(days=40)).strftime("%b-%Y"),
        "audited": "Unaudited", "source_url": "https://x/%s-%s.xml" % (sym, end)},
        {"revenue": rev * 1e7, "pat": pat * 1e7, "ebitda": rev * opm / 100 * 1e7,
         "pbt": pat * 1.3e7, "pbt_before_exceptional": pat * 1.3e7,
         "finance_cost": 5e7, "other_income": 2e7, "eps_basic": eps})
    row["opm_pct"] = opm
    return row


def _year(store, sym, end, rev, pat, basis="consolidated"):
    return store.to_row("income", {
        "symbol": sym, "company": sym.title() + " Ltd", "basis": basis, "freq": "annual",
        "label": "FY%s" % end[2:4], "period_end": end, "months": 12,
        "filed_at": "2026-05-01", "source_url": "https://x/%s-y.xml" % sym},
        {"revenue": rev * 1e7, "pat": pat * 1e7})


def _sheet(store, sym, end, assets, equity, debt, cash, basis="consolidated", ci=0):
    return store.to_row("balance", {
        "symbol": sym, "company": sym.title() + " Ltd", "basis": basis,
        "label": end, "period_end": end, "filed_at": "2026-05-01",
        "source_url": "https://x/%s-b.xml" % sym},
        {"total_assets": assets * 1e7, "total_equity": equity * 1e7,
         "total_borrowings": debt * 1e7, "cash_and_equivalents": cash * 1e7,
         "current_investments": ci * 1e7, "net_debt": (debt - cash - ci) * 1e7,
         "debt_equity_x": round(debt / equity, 2), "current_ratio_x": 1.5})


def _flow(store, sym, end, cfo, capex, months=12, basis="consolidated"):
    return store.to_row("cashflow", {
        "symbol": sym, "company": sym.title() + " Ltd", "basis": basis,
        "label": ("FY%s" % end[2:4]) if months == 12 else "H1", "period_end": end,
        "months": months, "filed_at": "2026-05-01", "source_url": "https://x/%s-c.xml" % sym},
        {"cfo": cfo * 1e7, "capex": capex * 1e7, "fcf": (cfo - capex) * 1e7})


QS = ["2026-06-30", "2026-03-31", "2025-12-31", "2025-09-30", "2025-06-30",
      "2025-03-31", "2024-12-31", "2024-09-30"]


# ── 2. The scan's factor history ───────────────────────────────────────────

def test_stored_quarters_score_like_filings(store):
    import factors
    store.upsert("income", [_q(store, "ACME", e, 1000 - i * 40, 100 - i * 5, eps=10 - i * .5)
                            for i, e in enumerate(QS)])
    store.upsert("balance", [_sheet(store, "ACME", "2026-03-31", 4000, 2000, 500, 100)])
    store.recompute_yoy("ACME")
    qs = store.scoring_quarters("ACME")
    assert len(qs) == 8 and qs[0]["period"]["to"] == "2026-06-30"
    assert qs[0]["revenue"] == 1000 * 1e7 and qs[0]["consolidated"] is True
    assert qs[0]["ebitda_margin_pct"] == 20.0
    # ROA against the March balance sheet, annualised, as normalise() does it.
    assert qs[0]["roa_annualised_pct"] == pytest.approx(100 * 4 / 4000 * 100, abs=.01)
    # The exchange's own timestamp format, so the PIT store dedupes versions.
    assert qs[0]["filed_at"] == "10-Aug-2026 18:00:00"
    known = factors.known_quarters(qs, TODAY)
    assert [q["period"]["to"] for q in known] == QS
    out = factors.fundamental_factors(qs, price=500, as_of=TODAY)
    assert out["revenue_growth"] == pytest.approx((1000 / 840 - 1) * 100)
    assert out["earnings_yield"] is not None and not out.get("stale")


def test_the_scan_reads_the_store_and_falls_back_when_overdue(store, monkeypatch):
    import xbrl
    store.upsert("income", [_q(store, "ACME", e, 1000, 100) for e in QS])
    monkeypatch.setattr(xbrl, "_age_days", lambda d, today=None: (TODAY - dt.date.fromisoformat(d)).days)
    assert len(xbrl._stored_scoring("ACME", 16)) == 8
    store.upsert("income", [_q(store, "OLD", "2025-12-31", 1000, 100)])
    assert xbrl._stored_scoring("OLD", 16) is None
    assert xbrl._stored_scoring("NOBODY", 16) is None


# ── 1. The Piotroski statements ───────────────────────────────────────────

def test_the_score_reads_stored_yahoo_statements(store):
    import data_source, engine
    for statement, items in (
            ("income", {"Net Income": (900, 800), "Total Revenue": (9000, 8000),
                        "Gross Profit": (4000, 3400)}),
            ("balance", {"Total Assets": (10000, 9500), "Current Assets": (5000, 4500),
                         "Current Liabilities": (2500, 2500), "Long Term Debt": (1000, 1200),
                         "Ordinary Shares Number": (100, 100)}),
            ("cashflow", {"Operating Cash Flow": (1200, 1000),
                          "Capital Expenditure": (-300, -250)})):
        store.record_yf("ACME", statement, "annual",
                        {(p, k): v[i] * 1e7 for k, v in items.items()
                         for i, p in enumerate(("2026-03-31", "2025-03-31"))})
    held = data_source.stored_statements("ACME.NS", today=TODAY)
    assert held is not None
    fin, bs, cf = held
    assert list(fin.columns.date) == [dt.date(2026, 3, 31), dt.date(2025, 3, 31)]
    assert engine._get(fin, ["Net Income"], 0) == 900 * 1e7
    score = engine.fundamental_score(fin, bs, cf, {})
    assert score["score"] is not None
    passed = {c["name"] for c in score["checks"] if c["points"] and c["name"].startswith("F-Score")}
    assert "F-Score · Positive operating cash flow" in passed
    assert "F-Score · Leverage falling" in passed
    # A bare ticker is a US listing: never an NSE company's statements.
    assert data_source.stored_statements("ACME", today=TODAY) is None
    # Overdue annual statements are read live instead.
    assert data_source.stored_statements("ACME.NS", today=dt.date(2027, 9, 1)) is None


# ── 3. Balance sheet and cash flow ────────────────────────────────────────

def test_position_shows_full_years_only_on_one_basis(store):
    import fundamentals as F
    store.upsert("balance", [_sheet(store, "ACME", "2026-03-31", 4000, 2000, 500, 100),
                             _sheet(store, "ACME", "2025-09-30", 3800, 1900, 600, 90)])
    store.upsert("cashflow", [_flow(store, "ACME", "2026-03-31", 600, 200),
                              _flow(store, "ACME", "2025-09-30", 250, 90, months=6),
                              _flow(store, "ACME", "2025-03-31", 500, 150)])
    store.upsert("income", [_year(store, "ACME", "2026-03-31", 4000, 400),
                            _year(store, "ACME", "2025-03-31", 3600, -50)])
    out = F.position_from_store("ACME")
    assert out["available"] and out["basis"] == "consolidated"
    assert [r["period_end"] for r in out["balance"]["rows"]] == ["2026-03-31", "2025-09-30"]
    assert out["balance"]["rows"][0]["ratios"]["debt_equity_x"] == 0.25
    # The half-year is not in the table beside the years.
    assert [r["period_end"] for r in out["cashflow"]["rows"]] == ["2026-03-31", "2025-03-31"]
    top, loss = out["cashflow"]["rows"]
    assert top["values"]["fcf"] == 400 and top["ratios"]["cash_conversion_pct"] == 150.0
    assert top["ratios"]["fcf_margin_pct"] == 10.0
    assert loss["ratios"]["cash_conversion_pct"] is None      # against a loss
    keys = [l["key"] for l in out["balance"]["lines"]]
    assert "total_assets" in keys and "deposits" not in keys  # never filed, not drawn


def test_position_for_an_unread_company(store):
    import fundamentals as F
    out = F.position_from_store("NOBODY")
    assert not out["available"] and "not been read" in out["message"]


# ── 4. Against its industry ───────────────────────────────────────────────

def test_peers_median_rank_and_the_minimum(store):
    import fundamentals as F
    peers = ["P%d" % i for i in range(6)]
    rows, sheets, years = [], [], []
    for i, s in enumerate(peers + ["ACME"]):
        opm = 10 + i * 2 if s != "ACME" else 30
        rows.append(_q(store, s, "2026-06-30", 1000, 100, opm=opm))
        sheets.append(_sheet(store, s, "2026-03-31", 4000, 2000, 200 * (i + 1), 100))
        years.append(_year(store, s, "2026-03-31", 4000, 300))
    rows.append(_q(store, "STALE", "2025-06-30", 1000, 100, opm=90))
    store.upsert("income", rows + years)
    store.upsert("balance", sheets)
    out = F.peers_from_store("ACME", "Widgets", peers + ["ACME", "STALE"], today=TODAY)
    assert out["available"] and out["peers_read"] == 6 and out["industry_members"] == 7
    opm = next(m for m in out["measures"] if m["key"] == "opm_pct")
    assert opm["median"] == 15.0 and opm["above"] == 6 and opm["peers"] == 6
    roe = next(m for m in out["measures"] if m["key"] == "roe_pct")
    assert roe["value"] == 15.0
    few = F.peers_from_store("ACME", "Widgets", peers[:3] + ["ACME"], today=TODAY)
    assert not few["available"] and "Too few" in few["message"]
    assert not F.peers_from_store("ACME", None, [], today=TODAY)["available"]


# ── 5. The quarterly screens ──────────────────────────────────────────────

def test_the_screens(store):
    import fundamentals_screens as S
    # Grower: 25% YoY in each of four quarters.
    rows = [_q(store, "GROW", e, 1250 if i < 4 else 1000, 100) for i, e in enumerate(QS)]
    # Turnaround, and a margin expander.
    rows += [_q(store, "TURN", QS[0], 500, 40), _q(store, "TURN", QS[4], 480, -30)]
    rows += [_q(store, "WIDE", QS[0], 1100, 90, opm=25), _q(store, "WIDE", QS[4], 1000, 80, opm=20)]
    # Stale: a turnaround a year ago, nothing since.
    rows += [_q(store, "OLD", "2025-06-30", 500, 40), _q(store, "OLD", "2024-06-30", 480, -30)]
    store.upsert("income", rows + [_year(store, "CASHY", "2026-03-31", 4000, 300),
                                   _year(store, "FLOW", "2026-03-31", 4000, 300)])
    for s in ("GROW", "TURN", "WIDE", "OLD"):
        store.recompute_yoy(s)
    store.upsert("balance", [_sheet(store, "CASHY", "2026-03-31", 4000, 2000, 100, 300)])
    store.upsert("cashflow", [_flow(store, "FLOW", e, 500, 100) for e in
                              ("2026-03-31", "2025-03-31", "2024-03-31")])
    res = S.evaluate(store._connect(), today=TODAY)
    names = {k: [m["symbol"] for m in v] for k, v in res.items()}
    assert names["steady_growers"] == ["GROW"]
    assert names["turnarounds"] == ["TURN"]
    assert names["margin_expanders"] == ["WIDE"]
    assert names["net_cash"] == ["CASHY"]
    assert names["fcf_compounders"] == ["FLOW"]
    idx = S.index(today=TODAY)
    assert {s["id"]: s["count"] for s in idx["screens"]}["turnarounds"] == 1
    d = S.detail("turnarounds", today=TODAY)
    assert d["matches"][0]["figures"][1]["value"] == -30 and "sort" not in d["matches"][0]
    assert S.detail("nope", today=TODAY) is None
