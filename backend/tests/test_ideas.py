"""
Idea selection.

The properties worth pinning are the ones that make the list a judgement
rather than a ranking: a serious adverse filing removes a name however well
it scores, sector outlook separates two identical fits, and the evidence
ledger adds up to the number printed beside it.
"""
import datetime as dt

import pytest

import ideas


SECTORS = {
    "Energy": {"sector": "Energy", "index_name": "Nifty Energy", "state": "Leading",
               "state_why": "Ahead and widening.",
               "relative": {"1M": 2.1, "3M": 8.4, "6M": 5.0}, "above_200dma_pct": 9.1},
    "Utilities": {"sector": "Utilities", "index_name": "Nifty Utilities", "state": "Lagging",
                  "state_why": "Behind and widening.",
                  "relative": {"1M": -3.0, "3M": -9.2, "6M": -4.0}, "above_200dma_pct": -6.4},
}

ADVERSE = {"category": "Regulatory action", "importance": "critical",
           "headline": "USFDA import alert", "line": "Regulatory action filed 30 min ago",
           "minutes_ago": 30, "pdf": None, "count": 1}


@pytest.fixture(autouse=True)
def wiring(monkeypatch):
    """Deterministic sector, news and filing layers."""
    monkeypatch.setattr(ideas, "sector_outlook", lambda: SECTORS)
    monkeypatch.setattr(ideas, "market_regime", lambda: {
        "ok": True, "stance": "Mixed", "pct_vs_50dma": 0.5, "pct_vs_200dma": -1.0,
        "change_5d_pct": 0.2, "label": "Mixed.", "benchmark": "NIFTYBEES", "source": "test"})
    monkeypatch.setattr(ideas, "_news_index", lambda hours: ({}, []))
    monkeypatch.setattr(ideas, "_filing_for",
                        lambda sym, hours, cats: dict(ADVERSE, direction="adverse")
                        if sym == "BADCO" else None)
    monkeypatch.setattr(ideas, "tracker", None)


def row(sym, sector, fit, comp, turnover=12.0, key="momentum_breakout"):
    return {"symbol": sym, "name": f"{sym} Ltd", "sector": sector, "setup_key": key,
            "setup": "Momentum Breakout", "setup_fit": fit, "composite": comp,
            "technical": comp, "fundamental": comp - 5, "f_score": 6, "price": 100.0,
            "avg_turnover_cr": turnover, "horizon": "3-8 weeks"}


def payload(rows):
    return {"scanned_at": dt.datetime.now().strftime("%d %b %Y, %H:%M"),
            "universe_source": "test", "rankings": rows}


def test_a_critical_adverse_filing_removes_the_name():
    """Highest fit on the board, and a live USFDA import alert."""
    p = payload([row("BADCO", "Energy", 95, 90), row("GOODCO", "Energy", 80, 74)])
    sel = ideas.select(p, horizon="short", limit=15)
    assert "BADCO" not in [r["symbol"] for r in sel["rows"]]
    assert any(e["symbol"] == "BADCO" for e in sel["excluded_adverse"])


def test_sector_outlook_separates_two_similar_fits():
    p = payload([row("LEAD", "Energy", 80, 74), row("LAG", "Utilities", 80, 74)])
    by = {r["symbol"]: r for r in ideas.select(p, horizon="short", limit=15)["rows"]}
    assert by["LEAD"]["conviction"] > by["LAG"]["conviction"]


def test_evidence_ledger_sums_to_the_conviction_shown():
    p = payload([row(f"S{i}", "Energy", 70 + i, 70) for i in range(3)])
    for r in ideas.select(p, horizon="short", limit=15)["rows"]:
        total = round(sum(e["points"] for e in r["evidence"]), 1)
        assert abs(total - r["conviction"]) < 0.25, (r["symbol"], total, r["conviction"])


def test_thin_liquidity_is_excluded_by_default_and_optional():
    p = payload([row("THIN", "Energy", 88, 80, turnover=0.3)])
    assert ideas.select(p, horizon="short", limit=15)["rows"] == []
    wide = ideas.select(p, horizon="short", limit=15, include_thin=True)
    assert [r["symbol"] for r in wide["rows"]] == ["THIN"]


def test_sector_cap_is_honoured():
    p = payload([row(f"E{i}", "Energy", 85 - i, 80) for i in range(6)])
    sel = ideas.select(p, horizon="short", limit=15)
    assert all(n <= ideas.SECTOR_CAP for _, n in sel["sector_mix"])


def test_horizons_use_different_setups_and_weights():
    p = payload([row("MOM", "Energy", 80, 74),
                 row("QUAL", "Energy", 80, 74, key="quality_at_discount")])
    assert [r["symbol"] for r in ideas.select(p, "short", 15)["rows"]] == ["MOM"]
    assert [r["symbol"] for r in ideas.select(p, "medium", 15)["rows"]] == ["QUAL"]
    assert ideas.HORIZONS["short"]["weights"] != ideas.HORIZONS["medium"]["weights"]


def test_a_stale_scan_is_penalised_and_says_so():
    fresh = payload([row("A", "Energy", 80, 74)])
    stale = dict(fresh, scanned_at=(dt.datetime.now() - dt.timedelta(days=9))
                 .strftime("%d %b %Y, %H:%M"))
    f = ideas.select(fresh, "short", 15)["rows"][0]["conviction"]
    s_sel = ideas.select(stale, "short", 15)
    s = s_sel["rows"][0]
    assert s["conviction"] < f
    assert any(e["factor"] == "Scan freshness" for e in s["evidence"])
    assert s_sel["staleness"]["warn"] is True


def test_an_unknown_horizon_is_rejected():
    with pytest.raises(ValueError):
        ideas.select(payload([]), horizon="yearly")


# --- live catalysts on the setup lists (December 2026) -----------------------

class _Calls:
    """concalls, as ideas reads it: the newest transcript and its brief."""
    def __init__(self, epoch, weight="high"):
        self.epoch, self.weight = epoch, weight

    def filed_since(self, symbol="", limit=1, epoch=0):
        return [{"pdf": "x.pdf", "symbol": symbol, "headline": "Transcript", "at": "2026-11-12T10:00:00",
                 "epoch": self.epoch, "digest": {"quarter": "Q2 FY27", "guidance_count": 4,
                                                 "guidance": [{"said": "We expect order inflow to double."}]}}]

    def briefs_for(self, pdfs):
        return {"x.pdf": {"headline": "Order book at a record; margin guidance raised", "weight": self.weight,
                          "commitments": [{"said": "Margins of 14% this year."}]}}


def test_a_catalyst_is_an_order_a_call_or_a_weeks_news(monkeypatch):
    import time as _t
    monkeypatch.setattr(ideas, "concalls", _Calls(_t.time() - 5 * 86400))
    now = dt.datetime.now(dt.timezone.utc)
    stories = [{"title": "Wins export order", "when": now.isoformat(), "speculative": False},
               {"title": "Rumour", "when": now.isoformat(), "speculative": True},
               {"title": "Old story", "when": (now - dt.timedelta(days=30)).isoformat(), "speculative": False}]
    order = {"value_cr": 420.0, "pct_of_market_cap": 6.1, "date": "2026-11-20"}
    c = ideas.catalysts("AAA", stories, order)
    assert len(c["lines"]) == 3
    assert c["lines"][0].startswith("Order worth ₹420 crore, 6.1%")
    assert "Q2 FY27" in c["lines"][1] and "record" in c["lines"][1]
    assert c["lines"][2] == "In the news: Wins export order"           # rumour and old story left out
    assert c["concall"]["said"] == "Margins of 14% this year."
    assert c["score"] == pytest.approx(min(3.0, 1 + 6.1 / 5) + 1.0 + 0.3)


def test_no_catalyst_is_none_and_an_old_call_is_not_news(monkeypatch):
    import time as _t
    monkeypatch.setattr(ideas, "concalls", _Calls(_t.time() - (ideas.CONCALL_DAYS + 5) * 86400))
    assert ideas.catalysts("AAA", [], {}) is None
    monkeypatch.setattr(ideas, "concalls", None)
    small = ideas.catalysts("AAA", [], {"value_cr": 5.0, "pct_of_market_cap": 0.2})
    assert small["lines"] and small["score"] == 0.0                     # shown, but too small to move a pick


def test_catalysts_reorder_a_setup_list_and_never_change_who_is_on_it(monkeypatch):
    """Served through ideas.select: the members of a setup list are the
    engine's; a catalyst only moves one up, and the page is told why."""
    import leaders
    from test_leaders import _ranked_with_sectors, scan_payload
    monkeypatch.setattr(ideas, "sector_outlook", lambda: {})
    monkeypatch.setattr(ideas, "market_regime", lambda: None)
    monkeypatch.setattr(ideas, "_news_index", lambda hours: ({}, []))
    monkeypatch.setattr(ideas, "_filing_for", lambda sym, hours, cats: None)
    monkeypatch.setattr(ideas, "tracker", None)
    _c, sectors, blocks = _ranked_with_sectors()
    payload = scan_payload(blocks, sectors)
    monkeypatch.setattr(ideas, "catalysts", lambda sym, stories=None, order=None: None)
    plain = ideas.select(payload, horizon="flow", limit=15)
    assert len(plain["rows"]) >= 3
    last = plain["rows"][-1]["symbol"]
    monkeypatch.setattr(ideas, "catalysts", lambda sym, stories=None, order=None:
                        {"lines": ["Order worth \u20b9420 crore"], "score": 2.0} if sym == last else None)
    lifted = ideas.select(payload, horizon="flow", limit=15)
    assert [r["symbol"] for r in lifted["rows"]][0] == last
    assert {r["symbol"] for r in lifted["rows"]} == {r["symbol"] for r in plain["rows"]}
    assert any("never choose it" in n for n in lifted["selection_notes"])
    assert set(ideas.CATALYST_LISTS) == {"breakout", "technical", "quick", "flow", "emerging"}


def test_every_list_served_has_a_staleness_limit_and_an_unknown_one_says_what_there_is():
    import leaders
    assert set(leaders.LISTS) <= set(ideas.PICK_STALE_DAYS)
    assert [ideas.PICK_STALE_DAYS[k] for k in leaders.ORDER] == [5, 3, 14]
    with pytest.raises(ValueError, match="month, results, long"):
        ideas.select(payload([]), horizon="fortnight")
