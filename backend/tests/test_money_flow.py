"""
Money Flow: the store, the arithmetic, the jobs and the two places it touches
the rest of the site.

Everything runs against the invented market in moneyflow_fixture.py (three
sectors whose flows, index paths and stocks are chosen so each answer can be
worked out by hand) and a database in a temporary directory. No network: the
jobs are given fetchers that answer from memory.
"""
import datetime as dt
import math

import pytest

import money_flow as M
import money_flow_config as C
import money_flow_sources as S
import money_flow_store as store
import moneyflow_fixture as F

IT, FMCG, METAL = F.IT, F.FMCG, F.METAL


@pytest.fixture
def db(tmp_path, monkeypatch):
    """An empty Money Flow database, and the invented stocks as the universe."""
    monkeypatch.setattr(store, "DB_PATH", str(tmp_path / "mf.db"))
    monkeypatch.setitem(M._members, "map", F.members())
    monkeypatch.setitem(M._names, "map", {})
    M._cache.update(at=0.0, payload=None)
    M._cards.update(at=0.0, date=None, cards={})
    yield store
    M._cache.update(at=0.0, payload=None)
    M._cards.update(at=0.0, date=None, cards={})


@pytest.fixture
def market(db):
    F.seed(db)
    return db


def card(payload, sector):
    return next(c for c in payload["sectors"] + payload["unscored"] if c["sector"] == sector)


# ---------------------------------------------------------------------------
# The mapping table
# ---------------------------------------------------------------------------

def test_every_industry_in_our_universe_is_a_sector_in_the_table():
    """The claim the module rests on: NSDL's sectors and our stocks' industries
    are one list. Read from the shipped classification, not the fixture."""
    import csv
    with open(M.SECTORS_FILE, encoding="utf-8-sig") as fh:
        industries = {r["Industry"].strip() for r in csv.DictReader(fh)}
    assert industries == {s["name"] for s in C.SECTORS}
    assert len(C.SECTORS) == 22


def test_nsdls_spelling_and_nses_are_the_same_sector():
    assert C.canonical("Oil, Gas & Consumable Fuels") == "Oil Gas & Consumable Fuels"
    assert C.canonical("Media, Entertainment & Publication") == "Media Entertainment & Publication"
    assert C.canonical("  information   technology ") == "Information Technology"
    assert C.canonical("Sovereign") == "Sovereign" and C.sector("Sovereign") is None
    assert C.canonical("Banks") is None            # the pre-2022 list: not guessed at


def test_every_real_nsdl_sector_name_maps():
    import os
    html = open(os.path.join(os.path.dirname(__file__), "fixtures", "moneyflow",
                             "nsdl_report_2026-11-15.html"), encoding="utf-8").read()
    names = {r["sector"] for r in S.parse_nsdl_report(html)["rows"]}
    assert {n for n in names if C.canonical(n) is None} == set()


def test_the_table_says_which_mappings_are_a_judgement():
    fit = {s["name"]: s["fit"] for s in C.SECTORS}
    assert fit["Construction"] == "ambiguous" and fit["Services"] == "ambiguous"
    assert fit["Textiles"] == "none" and fit["Information Technology"] == "clean"
    for s in C.SECTORS:
        if s["fit"] != "clean":
            assert s.get("note"), s["name"] + " is a judgement with no reason written down"
        assert (s["index"] is None) == (s["fit"] == "none")
    assert len({s["index"] for s in C.SECTORS if s["index"]}) == 18      # no index used twice


def test_weights_come_from_config_and_a_bad_override_is_ignored_whole(monkeypatch):
    assert C.SCORE_WEIGHTS == {"fpi": 40.0, "rs": 35.0, "breadth": 25.0}
    default = {"fpi": 40.0, "rs": 35.0, "breadth": 25.0}
    monkeypatch.setenv("MONEYFLOW_WEIGHTS", "fpi=50,rs=30,breadth=20")
    assert C._env_weights("MONEYFLOW_WEIGHTS", default) == {"fpi": 50.0, "rs": 30.0, "breadth": 20.0}
    for bad in ("fpi=50", "fpi=50,rs=x,breadth=1", "fpi=50,rs=30,volume=20", "fpi=-1,rs=1,breadth=1"):
        monkeypatch.setenv("MONEYFLOW_WEIGHTS", bad)
        assert C._env_weights("MONEYFLOW_WEIGHTS", default) == default, bad


# ---------------------------------------------------------------------------
# The store
# ---------------------------------------------------------------------------

def test_writing_everything_twice_changes_nothing(db):
    F.seed(db)
    before = db.coverage()
    rows_before = db.fpi_rows()
    F.seed(db)
    assert db.coverage() == before
    assert [dict(r, revisions=0) for r in db.fpi_rows()] == [dict(r, revisions=0) for r in rows_before]
    assert db.upsert_deals(F.deal_rows()) == 0


def test_a_fortnight_published_twice_keeps_one_row_and_counts_a_revision(db):
    row = {"sector": IT, "period_end": "2026-11-15", "period_start": "2026-11-01",
           "equity_net_inr_cr": 3000.0, "equity_auc_inr_cr": 407600.0}
    assert db.upsert_fpi([row]) == {"written": 1, "revised": 0}
    assert db.upsert_fpi([row]) == {"written": 1, "revised": 0}           # the same again
    assert db.upsert_fpi([dict(row, equity_net_inr_cr=3040.0)]) == {"written": 1, "revised": 1}
    got = db.fpi_rows()
    assert len(got) == 1 and got[0]["equity_net_inr_cr"] == 3040.0 and got[0]["revisions"] == 1


def test_a_later_report_with_a_blank_keeps_the_earlier_figure(db):
    """The earlier half of a report has no closing AUC column on some pages."""
    db.upsert_fpi([{"sector": IT, "period_end": "2026-11-15", "equity_net_inr_cr": 3000.0,
                    "equity_auc_inr_cr": 407600.0}])
    db.upsert_fpi([{"sector": IT, "period_end": "2026-11-15", "equity_net_inr_cr": 3000.0,
                    "equity_auc_inr_cr": None}])
    assert db.fpi_rows()[0]["equity_auc_inr_cr"] == 407600.0


def test_a_days_flows_keep_a_side_a_later_read_did_not_carry(db):
    db.upsert_flows({"2026-11-20": {"fii": {"buy": 10.0, "sell": 4.0, "net": 6.0}}})
    db.upsert_flows({"2026-11-20": {"dii": {"buy": 3.0, "sell": 5.0, "net": -2.0}}})
    assert db.flows() == [{"date": "2026-11-20", "fii_buy": 10.0, "fii_sell": 4.0, "fii_net": 6.0,
                           "dii_buy": 3.0, "dii_sell": 5.0, "dii_net": -2.0}]


def test_the_schema_is_migrations_and_running_them_again_applies_none(db):
    conn = db._connect()
    assert [r[0] for r in conn.execute("SELECT name FROM schema_migrations")] == ["001_init.sql"]
    assert db.migrate(conn) == []
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"fpi_sector_fortnight", "inst_flow_daily", "index_close_daily", "deals_daily",
            "sector_score_daily", "stock_accumulation_daily", "snapshots", "job_runs"} <= tables


def test_old_sessions_are_pruned_and_the_records_are_not(db, monkeypatch):
    monkeypatch.setattr(db, "KEEP_SNAPSHOTS", 2)
    monkeypatch.setattr(db, "KEEP_SCORE_SESSIONS", 3)
    db.upsert_fpi(F.fpi_rows())
    card = {"sector": IT, "score": 50.0, "rank": 1, "quadrant": "Leading"}
    stock = {"sector": IT, "symbol": "IT1", "score": 80.0}
    days = ["2026-11-1%d" % n for n in range(1, 7)]
    for day in days:
        db.save_snapshot(day, {"available": True}, [card], [stock])
    conn = db._connect()
    dates = lambda t: [r[0] for r in conn.execute("SELECT DISTINCT date FROM %s ORDER BY date" % t)]
    assert dates("snapshots") == days[-2:] and dates("stock_accumulation_daily") == days[-2:]
    assert dates("sector_score_daily") == days[-3:]
    assert len(db.fpi_rows()) == 18               # what NSDL published is never pruned


def test_an_alert_key_can_be_claimed_once(db):
    assert db.alert_claim("IT|2026-11-15", "x") is True
    assert db.alert_claim("IT|2026-11-15", "x") is False


# ---------------------------------------------------------------------------
# Arithmetic
# ---------------------------------------------------------------------------

def test_percentile_ranks_share_ties_and_leave_gaps_as_gaps():
    assert M.pct_ranks([10, 30, 20]) == [0.0, 1.0, 0.5]
    assert M.pct_ranks([5, None, 5, 9]) == [0.25, None, 0.25, 1.0]
    assert M.pct_ranks([7]) == [0.5] and M.pct_ranks([None]) == [None] and M.pct_ranks([]) == []
    assert M.pct_ranks([float("nan"), 1, 2]) == [None, 0.0, 1.0]


def test_flow_is_measured_against_the_assets_the_fortnight_opened_with():
    line = M.fpi_by_sector(F.fpi_rows())[IT]
    assert [f["net_cr"] for f in line] == [200, 400, 800, 1200, 2000, 3000]
    # First fortnight: no earlier figure, so closing AUC less the flow.
    assert line[0]["pct"] == pytest.approx(200 / 400000.0 * 100)
    # After that: the previous fortnight's closing AUC.
    assert line[1]["pct"] == pytest.approx(400 / 400200.0 * 100)
    assert line[-1]["pct"] == pytest.approx(3000 / 404600.0 * 100)


def trend_of(nets):
    return M.fpi_trend([{"period_start": "s%d" % i, "period_end": "e%d" % i, "net_cr": float(n),
                         "auc_cr": 100000.0, "pct": n / 1000.0} for i, n in enumerate(nets)])


@pytest.mark.parametrize("nets, direction, trend, flip_in, flip_out, streak", [
    ([100, 300], "inflow", "accelerating", False, False, 2),
    ([300, 100], "inflow", "decelerating", False, False, 2),
    ([-100, -300], "outflow", "accelerating", False, False, 2),
    ([-300, -100], "outflow", "decelerating", False, False, 2),
    ([-300, 100], "inflow", "reversing", True, False, 1),
    ([300, -100], "outflow", "reversing", False, True, 1),
    ([500], "inflow", "steady", False, False, 1),
    ([-50, 200, 0.4], "flat", "steady", False, False, 0),
    ([-5, 10, 20, 30], "inflow", "accelerating", False, False, 3),
])
def test_the_flow_trend_is_named(nets, direction, trend, flip_in, flip_out, streak):
    t = trend_of(nets)
    assert (t["direction"], t["trend"], t["flipped_to_inflow"], t["flipped_to_outflow"], t["streak"]) == \
        (direction, trend, flip_in, flip_out, streak)


def test_the_rolling_sum_is_the_last_three_fortnights():
    t = M.fpi_trend(M.fpi_by_sector(F.fpi_rows())[IT])
    assert t["latest_cr"] == 3000 and t["prev_cr"] == 2000
    assert t["sum3_cr"] == 1200 + 2000 + 3000
    assert t["prev_sum3_cr"] == 800 + 1200 + 2000
    assert t["period_end"] == "2026-11-15" and t["fortnights_in_sum"] == 3
    assert M.fpi_trend([]) is None


def test_fmcg_is_flagged_as_having_flipped_from_outflow_to_inflow():
    t = M.fpi_trend(M.fpi_by_sector(F.fpi_rows())[FMCG])
    assert t["flipped_to_inflow"] is True and t["trend"] == "reversing" and t["direction"] == "inflow"
    assert t["sum3_cr"] == -500 - 400 + 600


def _line(values, end=F.TODAY):
    days = F.sessions(len(values), end)
    return [(d.isoformat(), float(v)) for d, v in zip(days, values)]


def test_relative_strength_is_the_sectors_return_less_the_benchmarks():
    n = 64
    bench = _line([100.0] * n)
    sector = _line([100.0] * (n - 21) + [100.0 + i for i in range(1, 22)])
    rs = M.relative_strength(sector, bench)
    assert rs["rs_1m"] == pytest.approx(21.0) and rs["rs_3m"] == pytest.approx(21.0)
    assert rs["bench_1m"] == 0.0 and rs["ret_1m"] == pytest.approx(21.0)
    # The month before was flat against the benchmark, so all of it is new.
    assert rs["momentum"] == pytest.approx(21.0)


def test_relative_strength_needs_the_history_it_claims():
    rs = M.relative_strength(_line([100.0 + i for i in range(30)]), _line([100.0] * 30))
    assert rs["rs_1m"] is not None and rs["rs_3m"] is None and rs["momentum"] is None
    assert M.relative_strength([], _line([100.0] * 30)) is None


def test_only_sessions_both_series_have_are_compared():
    bench = _line([100.0] * 40)
    sector = _line([100.0] * 39 + [110.0])[5:]             # the sector starts later
    assert M.relative_strength(sector, bench)["sessions"] == 35


@pytest.mark.parametrize("ratio, momentum, want", [
    (101, 101, "Leading"), (101, 99, "Weakening"), (99, 99, "Lagging"), (99, 101, "Improving"),
    (100, 100, "Leading"), (None, 101, None),
])
def test_the_four_quadrants(ratio, momentum, want):
    assert M.quadrant(ratio, momentum) == want


def test_the_rotation_trail_is_weekly_and_at_most_eight_points():
    closes = F.index_closes()
    line = lambda name: [(d, v[name]) for d, v in sorted(closes.items())]
    pts = M.rrg_points(line("NIFTY IT"), line("NIFTY 50"))
    assert len(pts) == 8 and pts[-1]["week"] == F.TODAY.isoformat()
    weeks = [dt.date.fromisoformat(p["week"]) for p in pts]
    assert all((b - a).days == 7 for a, b in zip(weeks, weeks[1:]))
    assert all(p["ratio"] > 100 for p in pts)
    assert pts[-1]["date"] == F.TODAY.isoformat()
    # 70 sessions are needed for one point: 50 for the slow average, 20 more
    # for momentum's.
    assert M.rrg_points(line("NIFTY IT")[-60:], line("NIFTY 50")[-60:]) == []
    assert len(M.rrg_points(line("NIFTY IT")[-70:], line("NIFTY 50")[-70:])) == 1


def test_an_unfinished_week_is_named_by_its_friday_and_dated_by_its_last_session():
    """So a series that stops on Tuesday and one that stops on Monday are in
    the same week on the chart."""
    closes = F.index_closes()
    line = lambda name, cut: [(d, v[name]) for d, v in sorted(closes.items())][:cut]
    tue = M.rrg_points(line("NIFTY IT", -3), line("NIFTY 50", -3))[-1]       # stops Tue 17 Nov
    mon = M.rrg_points(line("NIFTY IT", -4), line("NIFTY 50", -4))[-1]       # stops Mon 16 Nov
    assert (tue["week"], tue["date"]) == ("2026-11-20", "2026-11-17")
    assert (mon["week"], mon["date"]) == ("2026-11-20", "2026-11-16")


def test_a_series_in_line_with_the_benchmark_sits_at_100():
    bench = _line([100.0 * 1.001 ** i for i in range(200)])
    pts = M.rrg_points(bench, bench)
    assert pts and all(p["ratio"] == 100.0 and p["momentum"] == 100.0 for p in pts)


# ---------------------------------------------------------------------------
# Stocks
# ---------------------------------------------------------------------------

def test_breadth_counts_stocks_above_their_50_day_average():
    table = M.stock_table(F.panel(), F.members(), {})
    assert M.sector_breadth(table, FMCG) == {"pct": 50.0, "above": 4, "of": 8}
    assert M.sector_breadth(table, METAL) == {"pct": 12.5, "above": 1, "of": 8}


def test_a_split_is_not_counted_as_a_stock_falling_below_its_average():
    """IT2 halves in one session. It is rising; unadjusted, it reads as far
    below its 50-day average. It is left out of the count, not counted wrong."""
    table = M.stock_table(F.panel(), F.members(), {})
    assert table["IT2"]["corporate_action"] is True and table["IT2"]["above_50dma"] is None
    assert M.sector_breadth(table, IT) == {"pct": 85.7, "above": 6, "of": 7}
    assert M.accumulation_score(table["IT2"]) == (None, [])


def test_breadth_needs_five_stocks():
    table = {k: v for k, v in M.stock_table(F.panel(), F.members(), {}).items()
             if k in ("FM1", "FM2", "FM3", "FM4")}
    assert M.sector_breadth(table, FMCG) is None


def test_delivery_and_volume_are_each_stocks_own_usual():
    r = M.stock_table(F.panel(), F.members(), {})["IT1"]
    assert r["deliv_pct"] == 64.0 and r["deliv_5d"] == 64.0 and r["deliv_base"] == 40.0
    assert r["deliv_ratio"] == pytest.approx(1.6)
    # Today against the 20 sessions before it: 4 of those were already doubled.
    assert r["vol_ratio"] == pytest.approx(2_000_000 / (1_000_000 * 16 / 20 + 2_000_000 * 4 / 20), abs=0.01)
    assert r["vol_ratio_5d"] == 2.0 and r["up_vol_days"] == 5
    quiet = M.stock_table(F.panel(), F.members(), {})["IT3"]
    assert quiet["deliv_ratio"] == 1.0 and quiet["up_vol_days"] == 0 and quiet["vol_ratio"] == 1.0


def test_the_accumulation_score_is_its_three_parts_added():
    table = M.stock_table(F.panel(), F.members(), {})
    score, why = M.accumulation_score(table["IT1"])
    assert score == 45.0 + 40.0                 # delivery at the ceiling, 5 of 5 sessions
    assert len(why) == 2 and "64%" in why[0] and "5 of the last 5" in why[1]
    assert M.accumulation_score(table["IT3"]) == (round(45.0 * (1.0 - 0.9) / 0.6, 1), [])


def test_net_buying_in_deals_adds_fifteen_and_net_selling_takes_it_off(market):
    nets = M.deal_nets("2026-01-01")
    assert nets["IT1"]["net_cr"] == 7.0 and nets["IT3"]["net_cr"] == -5.6
    table = M.stock_table(F.panel(), F.members(), nets)
    bought, why = M.accumulation_score(table["IT1"])
    assert bought == 100.0 and "Long Horizon Mutual Fund" in why[-1]
    sold, _ = M.accumulation_score(table["IT3"])
    assert sold == 0.0                          # 7.5 from delivery, less 15, floored


def test_a_market_maker_on_both_sides_is_not_buying(market):
    net = M.deal_nets("2026-01-01")["IT4"]
    assert net["net_cr"] == 0.0 and net["prop_cr"] > 0
    table = M.stock_table(F.panel(), F.members(), M.deal_nets("2026-01-01"))
    assert M.accumulation_score(table["IT4"])[0] == M.accumulation_score(
        M.stock_table(F.panel(), F.members(), {})["IT4"])[0]


def test_a_stock_that_barely_trades_is_not_ranked():
    assert M.accumulation_score(M.stock_table(F.panel(), F.members(), {})["MT8"]) == (None, [])


def test_the_basket_is_weighted_by_rupees_traded_and_capped():
    """Five stocks. BIG trades ten times what each of the others does and
    rises 1% a session; the others do not move. Equal weight would say +0.2% a
    session and raw turnover +0.71%. Capped at a quarter of the basket before
    the weights are shared out, BIG is 0.25 of 0.25 + 4/14 and the basket
    rises 0.467% a session."""
    import numpy as np
    import pandas as pd
    idx = pd.to_datetime(F.sessions(30))
    cols = ["BIG", "S1", "S2", "S3", "S4"]
    close = pd.DataFrame(100.0, index=idx, columns=cols)
    close["BIG"] = 100.0 * 1.01 ** np.arange(30)
    qty = pd.DataFrame(1000.0, index=idx, columns=cols)
    qty["BIG"] = 10000.0 / 1.01 ** np.arange(30)        # so its rupees traded stay 10x
    P = {"close": close, "qty": qty, "vwap": close}
    line = M.basket_series(P, cols)
    assert len(line) == 29
    share = 0.25 / (0.25 + 4 / 14.0)
    assert line.iloc[0] == pytest.approx(100.0 * (1 + 0.01 * share), rel=1e-6)
    assert M.basket_series(P, ["BIG", "S1"]) is None             # under five stocks
    assert M.basket_series(None, cols) is None


def test_a_falling_sectors_basket_falls():
    line = M.basket_series(F.panel(), [s for s, sec in F.members().items() if sec == METAL])
    assert line.iloc[0] < 100.0 and line.iloc[-1] < 90.0


def test_a_split_does_not_drop_the_basket():
    P = F.panel()
    members = [s for s, sec in F.members().items() if sec == IT]
    step = M.basket_series(P, members).pct_change().dropna()
    assert step.min() > -0.01, "the session IT2 split shows as a fall in the basket"


# ---------------------------------------------------------------------------
# FII and DII
# ---------------------------------------------------------------------------

def test_the_hero_carries_daily_bars_a_running_total_and_two_sums(market):
    rows = market.flows()
    out = M.market_flow(rows)
    assert out["available"] and out["sessions"] == 30 and len(out["days"]) == 30
    assert out["fii_5d"] == sum(r["fii_net"] for r in rows[-5:])
    assert out["dii_20d"] == sum(r["dii_net"] for r in rows[-20:])
    assert out["days"][-1]["fii_cum"] == sum(r["fii_net"] for r in rows)
    assert out["days"][0]["fii_cum"] == out["days"][0]["fii"]
    assert out["latest"]["date"] == F.TODAY.isoformat() and "provisional" in out["note"]


def test_a_short_record_says_how_short_and_does_not_pad():
    rows = [{"date": "2026-11-20", "fii_net": 100.0, "dii_net": -40.0}]
    out = M.market_flow(rows)
    assert out["sessions"] == 1 and out["sessions_in_20d"] == 1 and out["fii_20d"] == 100.0
    assert "1 session recorded" in out["note"]
    assert M.market_flow([])["available"] is False


# ---------------------------------------------------------------------------
# One computed session
# ---------------------------------------------------------------------------

def test_the_sector_with_flows_price_and_breadth_behind_it_ranks_first(market):
    payload, _cards, _stocks = M.build_snapshot(today=F.TODAY, panel=F.panel())
    assert [c["sector"] for c in payload["sectors"]] == [IT, FMCG, METAL]
    assert [c["rank"] for c in payload["sectors"]] == [1, 2, 3]
    assert all(c["of"] == 3 for c in payload["sectors"])
    assert payload["as_of"] == F.TODAY.isoformat()


def test_a_score_is_its_three_parts_at_the_configured_weights(market):
    payload, _c, _s = M.build_snapshot(today=F.TODAY, panel=F.panel())
    for c in payload["sectors"]:
        parts = c["components"]
        assert [parts[k]["weight"] for k in ("fpi", "rs", "breadth")] == [40.0, 35.0, 25.0]
        want = sum(parts[k]["score"] * parts[k]["weight"] for k in parts) / 100.0
        assert c["score"] == pytest.approx(want, abs=0.06)
        assert sum(p["points"] for p in parts.values()) == pytest.approx(c["score"], abs=0.11)
        assert c["partial"] is False and c["missing"] == []
    it = card(payload, IT)
    # Flow: top of three on the three-fortnight sum (0.5) and on the latest
    # fortnight (0.3), second on the change from the fortnight before (0.2),
    # because FMCG's swing from selling to buying was the larger move.
    assert it["components"]["fpi"]["score"] == pytest.approx(100 * (0.5 + 0.3 + 0.2 * 0.5))
    # Strength: Leading, and top on both returns against the Nifty 50.
    assert it["components"]["rs"]["score"] == 100.0
    assert it["components"]["breadth"]["score"] == 85.7
    assert it["score"] == pytest.approx(0.40 * 90 + 0.35 * 100 + 0.25 * 85.7, abs=0.06)


def test_each_card_carries_what_the_page_prints(market):
    payload, _c, _s = M.build_snapshot(today=F.TODAY, panel=F.panel())
    it, fm, mt = (card(payload, s) for s in (IT, FMCG, METAL))
    assert (it["quadrant"], fm["quadrant"], mt["quadrant"]) == ("Leading", "Improving", "Lagging")
    assert it["fpi"]["trend"] == "accelerating" and it["fpi"]["direction"] == "inflow"
    assert mt["fpi"]["trend"] == "accelerating" and mt["fpi"]["direction"] == "outflow"
    assert fm["fpi"]["flipped_to_inflow"] is True
    assert it["fpi_spark"] == [200, 400, 800, 1200, 2000, 3000]
    assert it["index"]["source"] == "index" and it["index"]["label"] == "Nifty IT"
    assert it["rs"]["rs_1m"] > 0 > mt["rs"]["rs_1m"]
    assert it["top_stocks"][0]["symbol"] == "IT1"
    assert payload["fpi"]["flipped_to_inflow"] == ["FMCG"]
    assert payload["fpi"]["latest_period"] == {"start": "2026-11-01", "end": "2026-11-15"}


def test_the_heatmap_is_sector_by_fortnight_oldest_fortnight_first(market):
    payload, _c, _s = M.build_snapshot(today=F.TODAY, panel=F.panel())
    h = payload["heatmap"]
    assert [p["end"] for p in h["periods"]] == [end for _s, end in F.FORTNIGHTS]
    row = next(r for r in h["rows"] if r["sector"] == METAL)
    assert [c["net_cr"] for c in row["cells"]] == [300, -100, -400, -800, -1200, -2000]
    assert h["totals"][-1] == 3000 + 600 - 2000
    assert all(c["pct"] is not None for r in h["rows"] for c in r["cells"])


def test_the_rotation_chart_has_a_trail_per_sector(market):
    payload, _c, _s = M.build_snapshot(today=F.TODAY, panel=F.panel())
    series = {s["full"]: s for s in payload["rrg"]["series"]}
    assert set(series) == {IT, FMCG, METAL}
    assert all(len(s["points"]) == 8 and s["kind"] == "sector" for s in series.values())
    assert len(payload["rrg"]["weeks"]) == 8 and payload["rrg"]["benchmark"] == "Nifty 50"
    assert payload["rrg"]["week_dates"][-1] == F.TODAY.isoformat()


def test_accumulation_rows_are_ranked_inside_each_sector(market):
    _p, _c, stocks = M.build_snapshot(today=F.TODAY, panel=F.panel())
    it = [r for r in stocks if r["sector"] == IT]
    assert it[0]["symbol"] == "IT1" and it[0]["score"] == 100.0 and it[0]["rank"] == 1
    assert [r["score"] for r in it] == sorted((r["score"] for r in it), reverse=True)
    assert "IT2" not in {r["symbol"] for r in it}                 # the split
    assert it[0]["deals"]["net_cr"] == 7.0
    assert "MT8" not in {r["symbol"] for r in stocks}             # barely trades


def test_without_the_delivery_panels_a_sector_is_still_scored_and_says_what_is_missing(market):
    payload, _c, stocks = M.build_snapshot(today=F.TODAY, panel=None)
    assert stocks == []
    it = card(payload, IT)
    assert it["partial"] is True and it["missing"] == ["breadth"]
    assert it["components"]["breadth"]["score"] is None
    # FPI (90) and rotation (100) re-weighted to the whole: 40 and 35 of 75.
    assert it["score"] == pytest.approx((90 * 40 + 100 * 35) / 75.0, abs=0.06)
    assert it["components"]["fpi"]["points"] == pytest.approx(90 * 40 / 75, abs=0.06)
    assert any("delivery record" in g for g in payload["gaps"])


def test_one_measurement_alone_is_not_a_score(db):
    """Only NSDL data: every sector has FPI flow and nothing else."""
    db.upsert_fpi(F.fpi_rows())
    payload, _c, _s = M.build_snapshot(today=F.TODAY, panel=None)
    assert payload["sectors"] == []
    assert card(payload, IT)["score"] is None and card(payload, IT)["fpi"]["latest_cr"] == 3000
    assert len(payload["heatmap"]["rows"]) == 3            # the flows are still shown
    assert any("Nifty 50" in g for g in payload["gaps"])


def test_an_empty_store_is_not_available(db):
    payload, cards, stocks = M.build_snapshot(today=F.TODAY, panel=None)
    assert payload["available"] is False and stocks == []
    assert M.recompute(today=F.TODAY, panel=None)["stored"] is False
    out = M.overview()
    assert out["available"] is False and "backfill" in out["message"]


def test_a_new_index_with_too_little_history_falls_back_to_the_basket(market, monkeypatch):
    monkeypatch.setattr(C, "MIN_INDEX_SESSIONS", 1000)
    payload, _c, _s = M.build_snapshot(today=F.TODAY, panel=F.panel())
    it = card(payload, IT)
    assert it["index"]["source"] == "basket" and "Basket of 8 IT stocks" == it["index"]["label"]
    assert it["rs"] is not None


def test_the_payload_serialises(market):
    import json
    payload, cards, stocks = M.build_snapshot(today=F.TODAY, panel=F.panel())
    text = json.dumps([payload, cards, stocks], allow_nan=False)
    assert "NaN" not in text and len(text) > 2000


# ---------------------------------------------------------------------------
# What the endpoints read
# ---------------------------------------------------------------------------

def test_recompute_stores_a_session_and_the_page_reads_it_back(market):
    out = M.recompute(today=F.TODAY, panel=F.panel())
    assert out == {"ok": True, "stored": True, "as_of": F.TODAY.isoformat(),
                   "sectors_scored": 3, "stocks": out["stocks"]}
    page = M.overview()
    assert page["available"] and page["built_utc"] and len(page["sectors"]) == 3
    assert M.recompute(today=F.TODAY, panel=F.panel())["stored"]     # again: replaces, no error
    assert market.coverage()["snapshots"] == {"count": 1, "latest": F.TODAY.isoformat()}


def test_a_sector_opens_into_its_fortnights_and_its_stocks(market):
    M.recompute(today=F.TODAY, panel=F.panel())
    d = M.sector_detail("information-technology")
    assert d["available"] and d["sector"] == IT and d["card"]["rank"] == 1
    assert [f["net_cr"] for f in d["fortnights"]] == [200, 400, 800, 1200, 2000, 3000]
    assert d["stocks"][0]["symbol"] == "IT1" and d["stocks"][0]["reasons"]
    assert d["history"] == [{"date": F.TODAY.isoformat(), "score": d["card"]["score"],
                             "rank": 1, "quadrant": "Leading"}]
    assert M.sector_detail(IT)["sector"] == IT                       # by name as well as slug
    assert M.sector_detail("no-such-sector") is None


def test_a_stocks_tailwind_is_its_sectors_card_in_one_line(market):
    M.recompute(today=F.TODAY, panel=F.panel())
    t = M.tailwind("it3.NS")
    assert t["sector"] == IT and t["rank"] == 1 and t["of"] == 3 and t["tier"] == "top"
    assert t["quadrant"] == "Leading" and t["fpi_latest_cr"] == 3000
    assert "IT ranks 1 of 3 on money flow (a tailwind)" in t["line"]
    assert "does not change the Altaha Score" in t["note"]
    assert M.tailwind("MT1")["tier"] == "bottom"
    assert M.tailwind("NOTLISTED") is None


def test_sector_caps_are_off_unless_switched_on(market, monkeypatch):
    M.recompute(today=F.TODAY, panel=F.panel())
    assert C.CAPS_ON is False
    assert [M.sector_cap(s, 4) for s in ("IT1", "FM1", "MT1", "NOTLISTED")] == [4, 4, 4, 4]
    monkeypatch.setattr(C, "CAPS_ON", True)
    assert [M.sector_cap(s, 4) for s in ("IT1", "FM1", "MT1", "NOTLISTED")] == [5, 4, 2, 4]
    assert M.caps_note()["on"] is True


# ---------------------------------------------------------------------------
# Alerts
# ---------------------------------------------------------------------------

def _cards(quadrant, latest=600.0, prev=-400.0, flipped=True):
    return {FMCG: {"sector": FMCG, "short": "FMCG", "quadrant": quadrant, "score": 61.2,
                   "rank": 2, "of": 3,
                   "fpi": {"latest_cr": latest, "prev_cr": prev, "flipped_to_inflow": flipped,
                           "period_start": "2026-11-01", "period_end": "2026-11-15"}}}


def test_a_sector_entering_improving_on_fpi_buying_is_announced():
    found = M.find_alerts(_cards("Improving"), _cards("Lagging"))
    assert [a["key"] for a in found] == [FMCG + "|2026-11-15"]
    text = found[0]["text"]
    assert "FMCG moved to Improving (was Lagging)" in text
    assert "FPIs turned net buyers" in text and "+600 cr after Rs -400 cr" in text
    assert "Score 61 of 100, rank 2 of 3" in text


@pytest.mark.parametrize("now, before, why", [
    (_cards("Improving"), _cards("Improving"), "it has not moved"),
    (_cards("Lagging"), _cards("Improving"), "it moved the wrong way"),
    (_cards("Improving"), _cards("Leading"), "leading to improving is a step down"),
    (_cards("Leading", latest=-50.0, flipped=False), _cards("Weakening"), "FPIs are selling"),
    (_cards("Improving"), {}, "there is nothing to compare with on the first day"),
])
def test_nothing_is_announced_when(now, before, why):
    assert M.find_alerts(now, before) == [], why


def test_requiring_a_flip_drops_a_sector_fpis_were_already_buying(monkeypatch):
    now = _cards("Leading", latest=600.0, prev=200.0, flipped=False)
    assert len(M.find_alerts(now, _cards("Weakening"))) == 1
    monkeypatch.setattr(C, "ALERT_REQUIRE_FLIP", True)
    assert M.find_alerts(now, _cards("Weakening")) == []


def test_a_sector_is_announced_once_per_fortnight(market):
    M.recompute(today=F.TODAY, panel=F.panel())
    as_of = F.TODAY.isoformat()
    _d, cards = market.sector_cards(date=as_of)
    before = {k: dict(v, quadrant="Lagging") for k, v in cards.items()}
    market.save_snapshot("2026-11-19", {"available": True}, list(before.values()), [])
    sent = []
    out = M.send_alerts(as_of, send=lambda text: sent.append(text) or True)
    assert out["found"] == 2 and out["sent"] == 2 and sorted(out["sectors"]) == sorted([IT, FMCG])
    again = M.send_alerts(as_of, send=lambda text: sent.append(text) or True)
    assert again["sent"] == 0 and len(sent) == 2
    assert all(a["delivered"] == 1 for a in market.alerts())


def test_with_no_telegram_the_alert_is_recorded_and_not_delivered(market):
    M.recompute(today=F.TODAY, panel=F.panel())
    _d, cards = market.sector_cards(date=F.TODAY.isoformat())
    market.save_snapshot("2026-11-19", {"available": True},
                         [dict(v, quadrant="Lagging") for v in cards.values()], [])
    out = M.send_alerts(F.TODAY.isoformat(), send=lambda text: False)
    assert out["found"] == 2 and out["sent"] == 0
    assert [a["delivered"] for a in market.alerts()] == [0, 0]


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------

LISTED = [{"url": "https://nsdl/a.html", "label": "NOV 15, 2026", "report_date": "2026-11-15"},
          {"url": "https://nsdl/b.html", "label": "OCT 31, 2026", "report_date": "2026-10-31"}]


def _report(url):
    periods = {"https://nsdl/a.html": ("2026-11-01", "2026-11-15", 3000.0),
               "https://nsdl/b.html": ("2026-10-16", "2026-10-31", 2000.0)}[url]
    return {"periods": [], "warnings": [], "grand_total": {}, "rows": [
        {"sector": "Information Technology", "period_start": periods[0], "period_end": periods[1],
         "equity_net_inr_cr": periods[2], "equity_auc_inr_cr": 400000.0},
        {"sector": "Oil, Gas & Consumable Fuels", "period_start": periods[0], "period_end": periods[1],
         "equity_net_inr_cr": -100.0, "equity_auc_inr_cr": 90000.0}]}


def test_the_nsdl_step_reads_each_report_once(db):
    calls = []
    fetch = lambda url: calls.append(url) or _report(url)
    first = M.step_nsdl(limit=5, fetch_index=lambda: LISTED, fetch_report=fetch)
    assert first["ok"] and first["read"] == 2 and first["rows"] == 4 and first["remaining"] == 0
    second = M.step_nsdl(limit=5, fetch_index=lambda: LISTED, fetch_report=fetch)
    assert second["read"] == 0 and len(calls) == 2
    # NSDL's spelling with commas is stored under the one name.
    assert {r["sector"] for r in db.fpi_rows()} == {"Information Technology", "Oil Gas & Consumable Fuels"}


def test_a_report_that_fails_to_parse_is_logged_and_asked_for_again(db):
    def broken(url):
        if url.endswith("a.html"):
            raise S.ParseError("no Equity column under 'Net Investment November 01-15, 2026' in INR")
        return _report(url)
    out = M.step_nsdl(limit=5, fetch_index=lambda: LISTED, fetch_report=broken)
    assert out["ok"] is False and out["read"] == 1
    assert "2026-11-15: ParseError: no Equity column" in out["errors"][0]
    assert db.reports_done() == {"https://nsdl/a.html": "error", "https://nsdl/b.html": "ok"}
    fixed = M.step_nsdl(limit=5, fetch_index=lambda: LISTED, fetch_report=_report)
    assert fixed["ok"] and fixed["read"] == 1 and db.reports_done()["https://nsdl/a.html"] == "ok"


def test_a_sector_name_nobody_knows_is_reported_not_guessed(db):
    def odd(url):
        r = _report(url)
        r["rows"].append({"sector": "Quantum Computing", "period_start": "2026-11-01",
                          "period_end": "2026-11-15", "equity_net_inr_cr": 5.0})
        return r
    out = M.step_nsdl(limit=1, fetch_index=lambda: LISTED, fetch_report=odd)
    assert out["ok"] and "unknown sectors: Quantum Computing" in out["warnings"][0]
    assert "Quantum Computing" not in {r["sector"] for r in db.fpi_rows()}


def test_only_reports_inside_the_window_are_asked_for(db):
    out = M.step_nsdl(limit=5, since="2026-11-01", fetch_index=lambda: LISTED, fetch_report=_report)
    assert out["read"] == 1 and out["remaining"] == 0


def _index_fetch(answers):
    def fetch(day):
        return answers.get(day.isoformat(), (S.ABSENT, {}))
    return fetch


def test_index_days_are_stored_once_and_holidays_are_not_asked_for_again(db):
    today = dt.date(2026, 11, 20)
    start = dt.date(2026, 11, 10)
    ok = {d.isoformat(): (S.OK, {"NIFTY 50": 25000.0}) for d in F.sessions(9, today)}
    first = M.step_indices(start, today, limit=30, today=today, fetch=_index_fetch(ok))
    assert first["ok"] and first["stored"] == 9 and first["absent"] == 2 and first["remaining"] == 0
    asked = []

    def again(day):
        asked.append(day)
        return S.ABSENT, {}
    second = M.step_indices(start, today, limit=30, today=today, fetch=again)
    assert second["stored"] == 0 and asked == []
    assert db.coverage()["index_sessions"]["count"] == 9


def test_a_file_not_out_yet_is_not_written_off_as_a_holiday(db):
    today = dt.date(2026, 11, 20)
    out = M.step_indices(today - dt.timedelta(days=1), today, today=today, fetch=_index_fetch({}))
    assert out["absent"] == 2 and db.index_days() == {}
    # Four days later the same answer IS believed.
    later = today + dt.timedelta(days=4)
    M.step_indices(today - dt.timedelta(days=1), today, today=later, fetch=_index_fetch({}))
    assert set(db.index_days().values()) == {"absent"}


def test_a_refused_day_is_an_error_and_stays_to_be_fetched(db):
    today = dt.date(2026, 11, 20)
    refused = {d.isoformat(): (S.BLOCKED, {}) for d in F.sessions(3, dt.date(2026, 11, 13))}
    out = M.step_indices(dt.date(2026, 11, 9), dt.date(2026, 11, 13), today=today,
                         fetch=_index_fetch(refused))
    assert out["ok"] is False and out["blocked"] == 3 and out["remaining"] == 3
    assert "refused 3 index files" in out["errors"][0]
    assert not any(d in db.index_days() for d in refused)


def test_five_refusals_in_a_row_end_the_slice(db):
    asked = []

    def refuse(day):
        asked.append(day)
        return S.BLOCKED, {}
    M.step_indices(dt.date(2026, 10, 1), dt.date(2026, 10, 31), limit=30,
                   today=dt.date(2026, 11, 20), fetch=refuse)
    assert len(asked) == 5


def test_the_flows_step_stores_the_session_it_was_given(db):
    out = M.step_flows(fetch=lambda: ("2026-11-20", {"fii": {"buy": 9.0, "sell": 4.0, "net": 5.0},
                                                     "dii": {"buy": 2.0, "sell": 3.0, "net": -1.0}}))
    assert out["ok"] and out["latest"] == "2026-11-20"
    assert M.step_flows(fetch=lambda: None)["ok"] is False


def test_deal_history_is_read_in_windows_and_a_refusal_is_noted_not_failed(db):
    read = []

    def fetch(kind, lo, hi):
        read.append((kind, lo, hi))
        return F.deal_rows()[:1] if kind == "bulk" else []
    out = M.step_deals_history(dt.date(2026, 9, 1), dt.date(2026, 11, 20), limit=4, fetch=fetch)
    assert out["windows_read"] == 4 and out["remaining"] == 2 and out["new"] == 1
    assert all((hi - lo).days <= 29 for _k, lo, hi in read)
    M.step_deals_history(dt.date(2026, 9, 1), dt.date(2026, 11, 20), limit=4, fetch=fetch)
    assert len(read) == 6                                       # the two that were left
    refused = M.step_deals_history(dt.date(2026, 6, 1), dt.date(2026, 11, 20), limit=4,
                                   fetch=lambda *a: None)
    assert refused["ok"] is True and refused["refused"] and refused["remaining"] == 0
    assert "refused" in refused["notes"][0]


def test_one_step_failing_does_not_stop_the_others_and_the_run_is_logged(db):
    def boom():
        raise ConnectionError("NSDL's report list did not answer (blocked)")
    out = M._run("daily", [("nsdl", boom), ("flows", lambda: {"ok": True, "written": 1}),
                           ("indices", lambda: {"ok": True, "remaining": 3})])
    assert out["ok"] is False and out["remaining"] == 3
    assert out["steps"]["flows"]["written"] == 1
    assert out["errors"] == ["nsdl: ConnectionError: NSDL's report list did not answer (blocked)"]
    run = db.job_runs(limit=1)[0]
    assert run["job"] == "daily" and run["ok"] is False and run["finished_utc"]
    assert run["summary"]["errors"] == out["errors"]
    assert M.status()["last"]["daily"]["ok"] is False


def test_a_second_job_does_not_start_while_one_is_running(db):
    inner = {}

    def step():
        inner["second"] = M._run("daily", [("x", lambda: {"ok": True})])
        return {"ok": True}
    out = M._run("backfill", [("x", step)])
    assert out["ok"] is True and inner["second"]["busy"] is True


def test_the_whole_daily_job_end_to_end_and_again(market, monkeypatch):
    """Every source faked; the second run of the same evening writes nothing."""
    today = F.TODAY
    monkeypatch.setattr(S, "fetch_index_day", lambda day: (S.ABSENT, {}))
    monkeypatch.setattr(S, "fetch_nsdl_index", lambda: [])
    monkeypatch.setattr(S, "fetch_deals_latest", lambda: (F.deal_rows(), []))
    monkeypatch.setattr(M, "step_flows", lambda: {"ok": True, "written": 0})
    monkeypatch.setattr(M, "step_delivery", lambda: {"ok": True})
    monkeypatch.setattr(M, "_panel", lambda: F.panel())
    first = M.run_daily(today=today)
    assert first["ok"], first["errors"]
    assert first["steps"]["compute"]["sectors_scored"] == 3 and first["steps"]["deals"]["new"] == 0
    before = market.coverage()
    second = M.run_daily(today=today)
    assert second["ok"] and market.coverage() == before
    assert [r["job"] for r in market.job_runs(limit=5)] == ["daily", "daily"]


def test_nothing_in_a_stored_payload_is_nan(market):
    M.recompute(today=F.TODAY, panel=F.panel())

    def walk(v):
        if isinstance(v, dict):
            return all(walk(x) for x in v.values())
        if isinstance(v, list):
            return all(walk(x) for x in v)
        return not (isinstance(v, float) and not math.isfinite(v))
    assert walk(M.overview()) and walk(M.sector_detail(IT))
