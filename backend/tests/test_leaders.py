"""
The four pick lists: this week, this month, momentum, long term.

What is pinned here is what would make the Ideas page lie if it broke: a
signal that can see tomorrow's bar, a recipe that drifts away from the one
the study measured, an exit line that follows the price down, a pick that
skipped a gate, and a deploy that blanks the page until the next scan.
"""
import datetime as dt
import json
import os
import tempfile
import time

import numpy as np
import pandas as pd
import pytest

import leaders
import ideas

HERE = os.path.dirname(os.path.abspath(__file__))


def frame(n=320, drift=0.001, noise=0.01, turnover=5e8, price=100.0, seed=1, last5=None):
    """A daily frame: steady drift, some noise, a given rupee turnover."""
    rng = np.random.default_rng(seed)
    r = drift + rng.normal(0, noise, n)
    if last5 is not None:
        r[-5:] = last5 / 5.0
    c = price * np.exp(np.cumsum(r))
    idx = pd.bdate_range("2025-01-01", periods=n)
    return pd.DataFrame({"Open": c, "High": c * 1.005, "Low": c * 0.995, "Close": c,
                         "Volume": turnover / c}, index=idx)


def cand(sym, **kw):
    return {"symbol": sym, "leader_sig": leaders.signals(frame(**kw))}


def universe(n=60):
    """Sixty liquid uptrends of varying strength and calm."""
    out = []
    for i in range(n):
        out.append(cand(f"S{i:02d}", drift=0.0004 + 0.00004 * i, noise=0.006 + 0.0003 * (i % 9), seed=i))
    return out


# --- signals ---------------------------------------------------------------

def test_a_signal_never_sees_a_later_bar():
    """Cut the frame at a date, then change everything after it: same answer."""
    df = frame(400)
    early = leaders.signals(df.iloc[:330])
    changed = df.copy()
    changed.iloc[330:, :] = changed.iloc[330:, :] * 3.0
    assert leaders.signals(changed.iloc[:330]) == early
    assert leaders.signals(changed) != early


def test_a_year_of_history_is_required():
    assert leaders.signals(frame(252)) is None
    assert leaders.signals(frame(253)) is not None
    assert leaders.signals(None) is None


def test_the_twelve_month_return_skips_the_last_month():
    df = frame(300, noise=0)
    c = df["Close"].values
    s = leaders.signals(df)
    assert s["mom_12_1"] == pytest.approx(c[-22] / c[-253] - 1)
    assert s["mom_6_1"] == pytest.approx(c[-22] / c[-127] - 1)
    assert s["ret_5d"] == pytest.approx(c[-1] / c[-6] - 1)


def test_a_straight_decline_is_not_scored_as_a_steady_climb():
    assert leaders.signals(frame(drift=-0.002, noise=0.002))["trend"] < 0
    assert leaders.signals(frame(drift=0.002, noise=0.002))["trend"] > 90


# --- the universe and the gates ---------------------------------------------

def test_thirty_names_are_needed_before_anything_is_ranked():
    assert leaders.rank(universe(29)) == {}
    assert len(leaders.rank(universe(30))) == 30


def test_an_illiquid_or_penny_stock_is_not_compared_at_all():
    cands = universe() + [cand("THIN", turnover=5e7), cand("PENNY", price=4.0)]
    blocks = leaders.rank(cands)
    assert "THIN" not in blocks and "PENNY" not in blocks


def test_a_downtrend_is_on_no_list():
    blocks = leaders.rank(universe() + [cand("FALLING", drift=-0.002)])
    b = blocks["FALLING"]
    assert not b["uptrend"]
    assert all(v["rank"] is None and not v["eligible"] for v in b["lists"].values())
    assert "uptrend" in b["lists"]["momentum"]["why_not"]


def test_the_most_volatile_fifth_is_gated_off_three_lists_and_ranked_on_the_fourth():
    blocks = leaders.rank(universe() + [cand("WILD", drift=0.004, noise=0.05, seed=3)])
    b = blocks["WILD"]
    assert b["uptrend"] and not b["calm"]
    for key in ("week", "month", "momentum"):
        assert b["lists"][key]["rank"] is None
        assert "volatile" in b["lists"][key]["why_not"]
    assert b["lists"]["long"]["eligible"], "the long-term list ranks on calm; it does not gate on it"


def test_ranks_are_one_to_n_with_no_gaps_and_no_ties():
    blocks = leaders.rank(universe())
    for key in leaders.ORDER:
        ranks = sorted(b["lists"][key]["rank"] for b in blocks.values() if b["lists"][key]["rank"])
        assert ranks == list(range(1, len(ranks) + 1))


def test_ranking_is_the_same_whatever_order_the_scan_met_the_stocks_in():
    cands = universe()
    a = leaders.rank(cands)
    b = leaders.rank(list(reversed(cands)))
    assert a == b


def test_a_dip_lifts_a_stock_on_the_week_list_and_not_on_the_momentum_list():
    base = universe()
    flat = leaders.rank(base + [cand("X", drift=0.0015, noise=0.006, seed=99)])["X"]
    dipped = leaders.rank(base + [cand("X", drift=0.0015, noise=0.006, seed=99, last5=-0.04)])["X"]
    assert dipped["parts"]["dip"] > flat["parts"]["dip"]
    gain_week = dipped["lists"]["week"]["score"] - flat["lists"]["week"]["score"]
    gain_mom = dipped["lists"]["momentum"]["score"] - flat["lists"]["momentum"]["score"]
    assert gain_week > 0 and gain_week > gain_mom


# --- the recipes are the ones the study measured ----------------------------

def test_every_mix_sums_to_one():
    for key, spec in leaders.LISTS.items():
        assert sum(spec["mix"].values()) == pytest.approx(1.0), key


def test_hold_and_exit_are_the_ones_the_study_measured():
    """The page prints the study's record beside each list. If the hold or the
    exit line here differs from the one tested, that record is another
    recipe's."""
    with open(os.path.join(HERE, "..", "..", "research", "ideas-study.json"), encoding="utf-8") as f:
        study = json.load(f)
    for key, spec in leaders.LISTS.items():
        rec = study["lists"][key]
        assert rec["hold_sessions"] == spec["hold_sessions"], key
        assert rec["exit_pct"] == spec["exit_pct"], key
    same, total = study["engine_parity"].split("/")
    assert same == total, "the study ran against an engine that picked different stocks"


def test_the_copy_the_api_reads_is_the_study_itself():
    """The API is deployed from backend/ alone, so it carries its own copy."""
    a = open(os.path.join(HERE, "..", "ideas_study.json"), encoding="utf-8").read()
    b = open(os.path.join(HERE, "..", "..", "research", "ideas-study.json"), encoding="utf-8").read()
    assert a == b, "run research/ideas_study.py --study: the two copies have drifted"


def test_the_record_shown_is_read_from_the_study_file():
    assert leaders.TESTED.get("lists"), "the study file did not load"
    for key in leaders.ORDER:
        rec = ideas.tested_record(key)
        assert rec["picks"] > 5000 and 0 < rec["up_pct"] < 100
        assert set(rec["by_half"]) == {"2017-21", "2022-26"}


def test_every_old_horizon_name_still_resolves():
    assert leaders.resolve("short") == "momentum"
    assert leaders.resolve("medium") == "long"
    assert leaders.resolve("WEEK") == "week"
    assert leaders.resolve("nonsense") is None


# --- the plan ----------------------------------------------------------------

def test_the_plan_has_an_exit_line_a_review_date_and_no_target():
    p = leaders.plan("momentum", 200.0, dt.date(2026, 11, 10))
    assert p["stop"] == 170.0 and p["risk_pct"] == 15.0
    assert p["t1"] is None and p["rr"] is None
    assert p["review_on"] == "2027-02-09"
    assert leaders.plan("week", 100.0, dt.date(2026, 11, 10))["stop"] == 93.0
    assert leaders.plan("long", 100.0)["stop"] == 75.0
    assert leaders.plan("momentum", None) is None
    assert leaders.plan("nonsense", 100.0) is None


# --- the Ideas layer ----------------------------------------------------------

@pytest.fixture
def quiet(monkeypatch):
    monkeypatch.setattr(ideas, "sector_outlook", lambda: {})
    monkeypatch.setattr(ideas, "market_regime", lambda: None)
    monkeypatch.setattr(ideas, "_news_index", lambda hours: ({}, []))
    monkeypatch.setattr(ideas, "_filing_for", lambda sym, hours, cats: None)
    monkeypatch.setattr(ideas, "tracker", None)


def scan_payload(blocks, sectors=None, extra=None):
    rows = []
    for i, (sym, b) in enumerate(sorted(blocks.items())):
        r = {"symbol": sym, "name": f"{sym} Ltd", "sector": (sectors or {}).get(sym, f"Sector {i % 12}"),
             "setup_key": "momentum_breakout", "setup": "Momentum Breakout", "setup_fit": 80,
             "composite": 60.0, "technical": 80, "fundamental": 55, "f_score": 6,
             "trailing_eps": 12.0, "price": 100.0 + i, "avg_turnover_cr": 50.0, "leader": b}
        r.update((extra or {}).get(sym, {}))
        rows.append(r)
    return {"scanned_at": dt.datetime.now().strftime("%d %b %Y, %H:%M"), "universe_source": "test",
            "factor_universe": rows, "rankings": rows[:60]}


def test_each_list_is_served_in_the_order_the_recipe_ranked_it(quiet):
    blocks = leaders.rank(universe())
    p = scan_payload(blocks)
    for key in leaders.ORDER:
        sel = ideas.select(p, horizon=key, limit=15)
        assert sel["list"] == key and sel["method_key"] == "tested_lists"
        ranks = [r["pick_rank"] for r in sel["rows"]]
        assert ranks == sorted(ranks) and len(ranks) == 15
        assert all(r["setup_key"] == leaders.LISTS[key]["setup_key"] for r in sel["rows"])
        assert all(r["plan"]["t1"] is None and r["plan"]["stop"] < r["price"] for r in sel["rows"])
        assert sel["tested"]["hold_sessions"] == leaders.LISTS[key]["hold_sessions"]


def test_the_ledger_adds_up_to_the_score_beside_it(quiet):
    sel = ideas.select(scan_payload(leaders.rank(universe())), horizon="month")
    for r in sel["rows"]:
        assert sum(e["of"] for e in r["evidence"]) == pytest.approx(100, abs=0.5)
        assert sum(e["points"] for e in r["evidence"]) == pytest.approx(r["conviction"], abs=1.5)


def test_a_serious_adverse_filing_removes_a_pick_and_says_so(quiet, monkeypatch):
    blocks = leaders.rank(universe())
    top = min(blocks, key=lambda s: blocks[s]["lists"]["momentum"]["rank"] or 999)
    monkeypatch.setattr(ideas, "_filing_for", lambda sym, hours, cats: (
        {"category": "Regulatory action", "importance": "critical", "headline": "SEBI order",
         "line": "filed", "direction": "adverse"} if sym == top else None))
    sel = ideas.select(scan_payload(blocks), horizon="momentum")
    assert top not in [r["symbol"] for r in sel["rows"]]
    assert sel["excluded_adverse"][0]["symbol"] == top
    assert any("adverse filing" in n for n in sel["selection_notes"])


def test_one_sector_cannot_fill_the_list(quiet):
    blocks = leaders.rank(universe())
    sel = ideas.select(scan_payload(blocks, sectors={s: "Industrials" for s in blocks}), horizon="momentum")
    assert len(sel["rows"]) == ideas.PICK_SECTOR_CAP
    assert any("one sector" in n for n in sel["selection_notes"])


def test_the_long_term_list_leaves_out_a_loss_maker_and_the_others_do_not(quiet):
    blocks = leaders.rank(universe())
    top = min(blocks, key=lambda s: blocks[s]["lists"]["long"]["rank"] or 999)
    p = scan_payload(blocks, extra={top: {"trailing_eps": -3.0}})
    assert top not in [r["symbol"] for r in ideas.select(p, horizon="long")["rows"]]
    assert any(top in n for n in ideas.select(p, horizon="long")["selection_notes"])
    if blocks[top]["lists"]["momentum"]["rank"] and blocks[top]["lists"]["momentum"]["rank"] <= 15:
        assert top in [r["symbol"] for r in ideas.select(p, horizon="momentum")["rows"]]


def test_a_scan_from_before_the_lists_still_answers(quiet):
    """A deploy must not blank the Ideas page until the next scan runs."""
    old = {"scanned_at": dt.datetime.now().strftime("%d %b %Y, %H:%M"), "universe_source": "test",
           "rankings": [{"symbol": "OLD", "name": "Old Ltd", "sector": "Energy",
                         "setup_key": "momentum_breakout", "setup": "Momentum Breakout",
                         "setup_fit": 90, "composite": 80, "technical": 80, "fundamental": 70,
                         "price": 100.0, "avg_turnover_cr": 40.0, "horizon": "3-8 weeks"}]}
    assert not ideas.has_picks(old)
    for h in ("week", "month", "momentum", "short"):
        sel = ideas.select(old, horizon=h)
        assert sel["available"] and sel.get("method_key") != "tested_lists"
        assert [r["symbol"] for r in sel["rows"]] == ["OLD"]
    assert ideas.select(old, horizon="long")["available"]
    with pytest.raises(ValueError):
        ideas.select(old, horizon="nonsense")


def test_the_old_switch_positions_reach_the_new_lists(quiet):
    p = scan_payload(leaders.rank(universe()))
    assert ideas.select(p, horizon="short")["list"] == "momentum"
    assert ideas.select(p, horizon="medium")["list"] == "long"


# --- the scan gives leaders a place ------------------------------------------

def test_the_scan_gives_the_top_of_every_list_a_place_in_phase_two():
    import scan
    cands = universe(80)
    blocks = leaders.rank(cands)
    for i, c in enumerate(cands):
        c.update(score=float(i), turnover=5e8, leader=blocks.get(c["symbol"]))
        c.pop("leader_sig")
    cands.sort(key=lambda c: -c["score"])
    cohort, n_ranked, n_control = scan.pick_phase2_cohort(cands, 40, control_pct=0.25)
    chosen = {c["symbol"]: label for c, label in cohort}
    assert len(chosen) == 40 and n_ranked == 30
    assert sum(1 for v in chosen.values() if v == "leader") == 15, "leaders take at most half"
    for key in leaders.ORDER:
        best = min(blocks, key=lambda s: blocks[s]["lists"][key]["rank"] or 999)
        assert chosen.get(best) == "leader", f"the top {key} pick was not analysed"
    assert set(chosen.values()) == {"leader", "ranked", "control"}


def test_without_leader_ranks_the_cohort_is_the_old_one():
    import scan
    cands = [{"symbol": f"T{i:02d}", "score": float(100 - i), "turnover": 1e8} for i in range(50)]
    cohort, n_ranked, _ = scan.pick_phase2_cohort(cands, 20, control_pct=0.25)
    ranked = [c["symbol"] for c, label in cohort if label == "ranked"]
    assert ranked == [f"T{i:02d}" for i in range(15)]
    assert "leader" not in {label for _, label in cohort}


# --- the call log keeps the exit line where it was called ---------------------

@pytest.fixture
def log(monkeypatch):
    import call_log
    monkeypatch.setenv("TZ", "UTC")
    time.tzset()
    path = os.path.join(tempfile.mkdtemp(prefix="altaha-picks-"), "call_log.db")
    monkeypatch.setattr(call_log, "DB_PATH", path)
    return call_log


def pick(sym, price, key="momentum"):
    spec = leaders.LISTS[key]
    return {"symbol": sym, "name": sym, "sector": "Energy", "setup_key": spec["setup_key"],
            "setup": spec["setup"], "horizon": spec["hold_text"], "price": price, "conviction": 90.0,
            "conviction_band": "High", "plan": leaders.plan(key, price, dt.date(2026, 11, 2))}


S1, S2, S3 = "02 Nov 2026, 10:30", "03 Nov 2026, 10:30", "04 Nov 2026, 10:30"


def test_the_exit_line_stays_where_the_call_put_it(log):
    log.record("momentum", [pick("ABC", 100.0)], S1, {"ABC": 100.0})
    # The price fell 10%. A plan redrawn from today's price would put the line
    # at 76.5; the call's own line is 85 and must not move.
    log.record("momentum", [pick("ABC", 90.0)], S2, {"ABC": 90.0})
    call = log.listing()["rows"][0]
    assert call["status"] == "open" and call["stop"] == 85.0
    assert not [e for e in call["events"] if e["kind"] == "levels"]
    # Under the line at the next scan, and gone from the list.
    log.record("momentum", [], S3, {"ABC": 84.0})
    call = log.listing()["rows"][0]
    assert call["status"] == "closed" and call["outcome"] == "stop"
    assert call["price_now"] == 84.0


def test_the_lists_they_replaced_are_closed_once_and_only_once(log):
    old = {"symbol": "OLD", "name": "Old", "setup_key": "momentum_breakout", "setup": "Momentum",
           "horizon": "3-8 weeks", "price": 50.0, "conviction": 60.0,
           "plan": {"stance": "WAIT", "entry": None, "stop": None}}
    log.record("short", [old], S1, {"OLD": 50.0})
    assert log.retire(log.LEGACY_HORIZONS, S2, {"OLD": 55.0}) == 1
    assert log.retire(log.LEGACY_HORIZONS, S3, {"OLD": 60.0}) == 0
    call = log.listing()["rows"][0]
    assert call["status"] == "closed" and call["outcome"] == "dropped"
    assert call["price_now"] == 55.0
    assert call["horizon_label"] == "Short term"
    assert log.HORIZON_LABEL["week"] == "This week"


# --- the tracker reads a pick's exit line on the close ------------------------

def test_an_intraday_dip_through_the_line_is_not_an_exit():
    import tracker
    idx = pd.bdate_range("2026-11-02", periods=4)
    win = pd.DataFrame({"High": [101, 100, 99, 98], "Low": [99, 84, 95, 83],
                        "Close": [100, 92, 96, 84.5]}, index=idx)
    _t, on_low = tracker._first_touch(win, None, 85.0)
    assert on_low["on"] == "2026-11-03"
    _t, on_close = tracker._first_touch(win, None, 85.0, on_close=True)
    assert on_close["on"] == "2026-11-05"
    assert tracker.HORIZON_DAYS["pick_week"] < tracker.HORIZON_DAYS["pick_month"] \
        < tracker.HORIZON_DAYS["pick_momentum"] < tracker.HORIZON_DAYS["pick_long"]
