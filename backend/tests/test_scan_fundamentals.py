"""
The scan reads each company's fundamentals for the three fundamental lists
(scan.fundamental_snapshot), and ranks with them (scan.rank_leaders).

It runs inside the universe scan, on a 512 MB box, with every candidate's
price signals still in memory, and its result feeds a ranking whose failure
empties every list on the page. So what is pinned is mostly how it behaves
when it should not be trusted: it reads a few hundred companies at a time
and never a whole table, never anything filed after the day it is asked
about, never a network or a delivery-panel build; an empty store or any
failure is no snapshot rather than a failed scan; each live-only fact is
read on its own, and one that fails leaves only itself unknown.
"""
import datetime as dt
import sys

import numpy as np
import pandas as pd
import pytest

import scan
from test_fund_snapshot import ASOF, company


@pytest.fixture
def store(tmp_path, monkeypatch):
    """A fundamentals store of its own, put back afterwards."""
    monkeypatch.setenv("ALTAHA_FUNDAMENTALS_DB", str(tmp_path / "f.db"))
    monkeypatch.delitem(sys.modules, "fundamentals_store", raising=False)
    import fundamentals_store
    return fundamentals_store


@pytest.fixture
def quiet_live(monkeypatch):
    """No live-only source answers: each fact stays unknown."""
    monkeypatch.setattr(scan, "_holding_facts", lambda syms: {})
    monkeypatch.setattr(scan, "_delivery_spikes", lambda syms, day: {})
    monkeypatch.setattr(scan, "_order_wins", lambda day: {})
    monkeypatch.setattr(scan, "_sector_money_flow", lambda: {})


def seed(store, *syms, **kw):
    for sym in syms:
        rows = company(sym, **kw)
        store.upsert("income", rows["quarterly"] + rows["annual"])
        store.upsert("cashflow", rows["cashflow"])
        store.upsert("balance", rows["balance"])


def test_an_empty_store_is_no_snapshot(store):
    assert scan.fundamental_snapshot(today=ASOF, symbols=["ACME", "TCS"]) == {}
    assert scan.fundamental_snapshot(today=ASOF) == {}


def test_each_company_is_its_filings_with_a_price_and_every_live_fact_unknown(store, quiet_live):
    seed(store, "ACME", "BETA")
    out = scan.fundamental_snapshot(today=ASOF, symbols=["acme", "BETA", "NOFILINGS"],
                                    prices={"ACME": 120.0}, sectors={"BETA": "Financial Services"})
    assert set(out) == {"ACME", "BETA"}
    a, b = out["ACME"], out["BETA"]
    assert a["revenue_yoy_pct"] == pytest.approx(15.0, abs=0.01) and a["f_score_tests"] == 9
    assert a["pe"] == pytest.approx(120.0 / a["eps_ttm"], abs=0.1) and b["pe"] is None
    assert a["is_financial"] is False and b["is_financial"] is True and b["sector"] == "Financial Services"
    for k in scan.LIVE_ONLY_FIELDS:
        assert k in a and a[k] is None, k


def test_the_tables_are_read_a_chunk_of_companies_and_a_few_columns_at_a_time(store, quiet_live, monkeypatch):
    """Never a whole table, never every column: what keeps the read small on a
    box that is holding the whole market's price signals."""
    seed(store, "S0001", "S0299", "S0599")
    real = store._connect()
    seen = []

    class Watched:
        def execute(self, sql, args=()):
            seen.append((sql, list(args)))
            return real.execute(sql, args)

    monkeypatch.setattr(store, "_connect", lambda: Watched())
    monkeypatch.setattr(store, "rows", lambda *a, **k: pytest.fail("rows() reads a whole table"))
    syms = [f"S{i:04d}" for i in range(600)]
    out = scan.fundamental_snapshot(today=ASOF, symbols=syms)
    assert set(out) == {"S0001", "S0299", "S0599"}
    reads = [(q, a) for q, a in seen if q.lstrip().upper().startswith("SELECT") and "yf_profile" not in q]
    assert len(reads) == 4 * 3, "four tables, three chunks of companies"
    # The stored sectors of companies NSE's list does not name: two columns,
    # a chunk at a time.
    profiles = [(q, a) for q, a in seen if "yf_profile" in q]
    assert 0 < len(profiles) <= 3
    for sql, args in profiles:
        assert sql.split("FROM")[0].split() == ["SELECT", "symbol,", "sector"] and len(args) <= scan.SNAPSHOT_CHUNK
    for sql, args in reads:
        assert "symbol IN (" in sql and "*" not in sql.split("FROM")[0]
        held = [a for a in args if isinstance(a, str) and a.startswith("S0")]
        assert 0 < len(held) <= scan.SNAPSHOT_CHUNK
        assert "period_end >= ?" in sql and "filed_at <= ?" in sql


def test_nothing_filed_after_the_day_asked_about_is_read(store, quiet_live):
    seed(store, "ACME")
    later = dict(company("ACME")["quarterly"][0], period_end="2026-12-31", label="Q3 FY27",
                 filed_at="2027-02-01 18:00:00", revenue_cr=999.0)
    store.upsert("income", [later])
    assert scan.fundamental_snapshot(today=ASOF, symbols=["ACME"])["ACME"]["quarter_end"] == "2026-09-30"
    assert scan.fundamental_snapshot(today=dt.date(2027, 2, 2), symbols=["ACME"])["ACME"]["quarter_end"] == \
        "2026-12-31"


def test_a_failure_anywhere_in_the_read_is_no_snapshot(store, quiet_live, monkeypatch):
    seed(store, "ACME")
    import fund_snapshot

    def boom(*a, **k):
        raise RuntimeError("database is locked")
    with monkeypatch.context() as m:
        m.setattr(store, "_connect", boom)
        assert scan.fundamental_snapshot(today=ASOF, symbols=["ACME"]) == {}
    assert scan.fundamental_snapshot(today=ASOF, symbols=["ACME"]), "the same read, once the store answers"
    monkeypatch.setattr(fund_snapshot, "build", boom)
    assert scan.fundamental_snapshot(today=ASOF, symbols=["ACME"]) == {}


def test_each_live_fact_is_read_on_its_own(store, monkeypatch):
    seed(store, "ACME", "BETA")
    holdings = {"ACME": {"promoter_pct": 60.0, "pledge_pct": 0.0, "promoter_chg_4q": 1.5, "fii_dii_chg_1q": -0.4}}

    def boom(*a, **k):
        raise RuntimeError("the delivery panel will not unpickle")
    monkeypatch.setattr(scan, "_holding_facts", lambda syms: holdings)
    monkeypatch.setattr(scan, "_delivery_spikes", boom)
    monkeypatch.setattr(scan, "_order_wins", lambda day: {"BETA": 3.4, "ELSEWHERE": 9.0})
    monkeypatch.setattr(scan, "_sector_money_flow", lambda: {"Capital Goods": ("Leading", 81.5)})
    out = scan.fundamental_snapshot(today=ASOF, symbols=["ACME", "BETA"], sectors={"ACME": "Capital Goods"})
    assert out["ACME"]["pledge_pct"] == 0.0 and out["ACME"]["promoter_chg_4q"] == 1.5
    assert out["ACME"]["sector_mf_quadrant"] == "Leading" and out["ACME"]["sector_mf_score"] == 81.5
    assert out["BETA"]["order_win_pct_mcap"] == 3.4 and out["BETA"]["promoter_pct"] is None
    assert out["ACME"]["delivery_spike"] is None and out["BETA"]["delivery_spike"] is None
    assert "ELSEWHERE" not in out


def test_holdings_are_the_latest_filing_against_a_year_back_and_a_quarter_back(tmp_path, monkeypatch):
    import lens_store
    monkeypatch.setattr(lens_store, "DB_PATH", str(tmp_path / "lens.db"))
    lens_store.upsert_shareholding([
        {"symbol": "ACME", "period_end": "2026-09-30", "promoter_pct": 61.0, "fii_pct": 12.0, "dii_pct": 9.0,
         "pledged": 0, "pledge_pct": None},
        {"symbol": "ACME", "period_end": "2026-06-30", "promoter_pct": 60.5, "fii_pct": 11.0, "dii_pct": 9.5},
        {"symbol": "ACME", "period_end": "2025-09-30", "promoter_pct": 59.0, "fii_pct": 10.0, "dii_pct": 9.0},
        {"symbol": "BETA", "period_end": "2026-09-30", "promoter_pct": 40.0, "fii_pct": 5.0, "dii_pct": 5.0,
         "pledged": 1, "pledge_pct": 22.5},
    ])
    got = scan._holding_facts(["ACME", "BETA", "GAMMA"])
    assert got["ACME"] == {"promoter_pct": 61.0, "pledge_pct": 0.0, "promoter_chg_4q": 2.0, "fii_dii_chg_1q": 0.5}
    assert got["BETA"] == {"promoter_pct": 40.0, "pledge_pct": 22.5, "promoter_chg_4q": None,
                           "fii_dii_chg_1q": None}
    assert "GAMMA" not in got


def _panel(days=30):
    idx = pd.bdate_range(end=pd.Timestamp(ASOF), periods=days)
    flat = np.full(days, 100.0)
    surge = np.r_[np.full(days - 5, 1e5), np.full(5, 2.2e5)]
    usual = np.full(days, 1e5)
    falling = np.r_[flat[:-5], [99.0, 98.0, 97.0, 96.0, 95.0]]
    rising = np.r_[flat[:-5], [101.0, 102.0, 103.0, 104.0, 105.0]]
    close = pd.DataFrame({"DIP": falling, "RISE": rising, "CALM": falling}, index=idx)
    qty = pd.DataFrame({"DIP": surge, "RISE": surge, "CALM": usual}, index=idx)
    deliv = pd.DataFrame(50.0, index=idx, columns=close.columns)
    return {"close": close, "qty": qty, "deliv": deliv}


def test_a_delivery_surge_on_a_falling_week_is_the_catalyst_and_the_panel_is_never_built(monkeypatch):
    import special
    monkeypatch.setattr(special, "ensure_building", lambda *a, **k: pytest.fail("a delivery build was started"))
    monkeypatch.setitem(special._state, "panel", _panel())
    got = scan._delivery_spikes(["DIP", "RISE", "CALM", "ABSENT"], ASOF)
    assert got == {"DIP": True, "RISE": False, "CALM": False}
    # A panel a fortnight old says nothing about this week.
    assert scan._delivery_spikes(["DIP"], ASOF + dt.timedelta(days=14)) == {}
    # Not in memory and no file: nothing is read, nothing is built.
    monkeypatch.setitem(special._state, "panel", None)
    monkeypatch.setattr(special, "CACHE", "/nonexistent/delivery.pkl")
    monkeypatch.setattr(special, "_load_cache", lambda: pytest.fail("there was no file to load"))
    assert scan._delivery_spikes(["DIP"], ASOF) == {}


def test_an_order_counts_only_as_the_ledgers_public_cards_count_one(monkeypatch):
    import wow_orders
    rows = [{"symbol": "ACME", "value_cr": 400.0, "value_confident": 1, "stage": "order", "reader": 2,
             "pct_of_market_cap": 3.1},
            {"symbol": "ACME", "value_cr": 90.0, "value_confident": 1, "stage": "order", "reader": 2,
             "pct_of_market_cap": 0.7},
            {"symbol": "BETA", "value_cr": 900.0, "value_confident": 1, "stage": "bid", "reader": 2,
             "pct_of_market_cap": 30.0},
            {"symbol": "GAMMA", "value_cr": 900.0, "value_confident": 0, "stage": "order", "reader": 2,
             "pct_of_market_cap": 30.0}]
    asked = []
    monkeypatch.setattr(wow_orders, "history", lambda start, end: asked.append((start, end)) or rows)
    assert scan._order_wins(ASOF) == {"ACME": 3.1}
    assert asked == [(ASOF - dt.timedelta(days=scan.ORDER_DAYS), ASOF)]


def test_the_scan_builds_the_snapshot_before_it_ranks_and_ranks_without_it_if_it_fails(monkeypatch):
    import leaders
    sig = {"price": 250.0, "turnover": 5e8, "vol": 0.3, "va12": 1.0, "va6": 1.0, "near_high": 0.9,
           "trend": 50.0, "ret_5d": 0.0}
    cands = [{"symbol": "LIQUID", "leader_sig": dict(sig)}, {"symbol": "THIN", "leader_sig": dict(sig, turnover=1e6)},
             {"symbol": "NOSIG", "leader_sig": None}]
    for name, value in (("sector_map", {"LIQUID": "Capital Goods"}), ("recent_results", {}),
                        ("latest_growth", {"LIQUID": {"pat_yoy_pct": 5.0}}), ("benchmark_returns", None),
                        ("institutional_map", {})):
        monkeypatch.setattr(scan, name, lambda value=value: value)
    order, got = [], {}

    def snapshot(symbols=None, prices=None, sectors=None, today=None):
        order.append("snapshot")
        got.update(symbols=symbols, prices=prices, sectors=sectors)
        return {"LIQUID": {"pe": 20.0}}

    def rank(cands, **kw):
        order.append("rank")
        got["rank"] = kw
        return {"LIQUID": {"lists": {}}}
    monkeypatch.setattr(scan, "fundamental_snapshot", snapshot)
    monkeypatch.setattr(leaders, "rank", rank)
    assert scan.rank_leaders(cands) == {"LIQUID": {"lists": {}}}
    assert order == ["snapshot", "rank"]
    assert got["symbols"] == ["LIQUID"] and got["prices"] == {"LIQUID": 250.0}
    assert got["sectors"] == {"LIQUID": "Capital Goods"}
    assert got["rank"]["snapshot"] == {"LIQUID": {"pe": 20.0}}
    assert got["rank"]["fundamentals"] == {"LIQUID": {"pat_yoy_pct": 5.0}}, "the setup lists' read is unchanged"

    def broken(**kw):
        raise MemoryError("the read did not fit")
    monkeypatch.setattr(scan, "fundamental_snapshot", broken)
    assert scan.rank_leaders(cands) == {"LIQUID": {"lists": {}}}
    assert got["rank"]["snapshot"] == {}
    monkeypatch.setattr(leaders, "rank", broken)
    assert scan.rank_leaders(cands) == {}


def test_results_are_asked_for_over_five_weeks(monkeypatch):
    """The month list asks whether the market sold a result in the last 21
    sessions; the scan asks for five weeks of filings to cover them."""
    import types
    asked = {}
    cal = types.SimpleNamespace(filings=lambda start, end: asked.update(cal=(start, end)) or [])
    tables = types.SimpleNamespace(recent_quarterly=lambda since: asked.update(store=since) or [])
    monkeypatch.setitem(sys.modules, "results_calendar", cal)
    monkeypatch.setitem(sys.modules, "fundamentals_store", tables)
    assert scan.RESULTS_LOOKBACK_DAYS == 35
    scan.recent_results(ASOF)
    assert asked["cal"] == (ASOF - dt.timedelta(days=35), ASOF)
    assert asked["store"] == (ASOF - dt.timedelta(days=35)).isoformat()


def test_a_lender_outside_nses_list_is_known_by_its_stored_sector(store, quiet_live):
    """NSE's industry list names about 750 companies. A liquid NBFC outside it
    is read as a lender from the sector Yahoo's profile stored for it, as the
    quarterly screens read it, so it is never held to a manufacturer's debt."""
    seed(store, "NBFC1", "MAKER")
    conn = store._connect()
    for sym, sector in (("NBFC1", "Financial Services"), ("MAKER", "Industrials")):
        conn.execute("INSERT OR REPLACE INTO yf_profile (symbol, company, sector, industry, shares, price,"
                     " market_cap, currency, updated_utc) VALUES (?,?,?,?,?,?,?,?,?)",
                     (sym, sym, sector, None, None, None, None, "INR", "2026-11-01T00:00:00"))
    conn.commit()
    out = scan.fundamental_snapshot(today=ASOF, symbols=["NBFC1", "MAKER"], sectors={"MAKER": "Capital Goods"})
    assert out["NBFC1"]["is_financial"] is True and out["NBFC1"]["opm_yoy_chg"] is None
    # NSE's own industry wins where it names the company.
    assert out["MAKER"]["is_financial"] is False and out["MAKER"]["sector"] == "Capital Goods"
