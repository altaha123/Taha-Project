"""
The pick lists: this week, this month, after results, momentum, long term.

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


def frame(n=320, drift=0.001, noise=0.01, turnover=5e8, price=100.0, seed=1, last5=None,
          last21=None, jump=None, volume_on=None):
    """A daily frame: steady drift, some noise, a given rupee turnover.
    `jump` is (sessions ago, log move) for one session; `volume_on` is
    (sessions ago, multiple) for one session's volume."""
    rng = np.random.default_rng(seed)
    r = drift + rng.normal(0, noise, n)
    if last21 is not None:
        r[-21:] = last21 / 21.0
    if last5 is not None:
        r[-5:] = last5 / 5.0
    if jump is not None:
        r[-1 - jump[0]] = jump[1]
    c = price * np.exp(np.cumsum(r))
    idx = pd.bdate_range("2025-01-01", periods=n)
    v = turnover / c
    if volume_on is not None:
        v[-1 - volume_on[0]] *= volume_on[1]
    return pd.DataFrame({"Open": c, "High": c * 1.005, "Low": c * 0.995, "Close": c,
                         "Volume": v}, index=idx)


def cand(sym, **kw):
    return {"symbol": sym, "leader_sig": leaders.signals(frame(**kw))}


# The lists ranked on price alone. The results list is ranked on a filing and
# is empty unless someone has reported, so it has tests of its own below.
PRICE_LISTS = tuple(k for k in leaders.ORDER if not leaders.LISTS[k].get("event"))
DAYS = [d.date().isoformat() for d in pd.bdate_range("2025-01-01", periods=320)]


def filed(sessions_ago, hhmm="18:30"):
    """A filing timestamp on the date of a session `sessions_ago` back."""
    return {"filed_at": f"{DAYS[-1 - sessions_ago]} {hhmm}:00"}


def reporters(n=12, start=2):
    """A universe in which S00..S(n-1) reported: each jumped a different
    amount on the session after its results, filed `start` sessions back."""
    cands, results = [], {}
    for i in range(60):
        kw = dict(drift=0.0004 + 0.00004 * i, noise=0.006 + 0.0003 * (i % 9), seed=i)
        if i < n:
            # Filed after the close `start` sessions ago: priced the session after.
            kw["jump"] = (start - 1, 0.01 * (i + 1))
            results[f"S{i:02d}"] = filed(start)
        cands.append(cand(f"S{i:02d}", **kw))
    return cands, results


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


def test_six_months_of_history_is_required_and_under_a_year_is_young():
    assert leaders.signals(frame(126)) is None, "no 6-month return: nothing to rank it on"
    young, full = leaders.signals(frame(127)), leaders.signals(frame(253))
    assert young["young"] is True and young["sessions"] == 127
    assert full["young"] is False
    assert leaders.signals(frame(252))["young"] is True
    assert leaders.signals(None) is None


def test_a_young_companys_six_month_return_stands_in_for_the_twelve():
    g = leaders.signals(frame(200, drift=0.003, noise=0.004, seed=8))
    assert g["ret_12m"] is None and g["ret_6m"] is not None
    assert g["va12"] == g["va6"], "the 6-month return-for-risk stands in"
    assert g["mom_6_1"] == pytest.approx(frame(200, drift=0.003, noise=0.004, seed=8)["Close"].iloc[-22]
                                         / frame(200, drift=0.003, noise=0.004, seed=8)["Close"].iloc[-127] - 1)


def test_a_young_company_halted_for_weeks_is_not_ranked():
    df = frame(180)
    gappy = df.drop(df.index[80:140])             # sixty sessions with no trade
    assert len(gappy) < leaders.MIN_YOUNG_SESSIONS or leaders.signals(gappy) is None
    spread = frame(260).drop(frame(260).index[130:230])    # 160 bars over a year
    assert leaders.signals(spread) is None


def test_a_stock_halted_for_weeks_is_not_given_a_twelve_month_return():
    """253 bars that took fourteen months to accumulate are not a year."""
    df = frame(320)
    assert leaders.signals(df) is not None
    gappy = df.drop(df.index[200:240])            # forty sessions with no trade
    assert len(gappy) >= leaders.MIN_SESSIONS
    assert leaders.signals(gappy) is None
    assert leaders.signals(df.reset_index(drop=True)) is not None, "an undated frame is not rejected"


def test_a_cash_fund_is_not_a_company():
    """A liquid ETF climbs in a straight line at 1% volatility, which would
    rank first on every return-for-risk measure. It is not compared at all."""
    blocks = leaders.rank(universe() + [cand("LIQUIDETF", drift=0.00025, noise=0.0002, seed=5)])
    assert "LIQUIDETF" not in blocks


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


def test_the_most_volatile_fifth_is_on_no_list():
    blocks = leaders.rank(universe() + [cand("WILD", drift=0.004, noise=0.05, seed=3)])
    b = blocks["WILD"]
    assert b["uptrend"] and not b["calm"]
    for key in PRICE_LISTS:
        assert b["lists"][key]["rank"] is None
        assert "volatile" in b["lists"][key]["why_not"]


def test_ranks_are_one_to_n_with_no_gaps_and_no_ties():
    blocks = leaders.rank(universe())
    for key in leaders.ORDER:
        ranks = sorted(b["lists"][key]["rank"] for b in blocks.values() if b["lists"][key]["rank"])
        assert ranks == list(range(1, len(ranks) + 1))


def test_two_scores_that_print_the_same_are_still_ranked_by_the_real_one():
    """The page rounds to a decimal. The order must not."""
    blocks = leaders.rank(universe(200))
    for key in leaders.ORDER:
        ranked = sorted((b["lists"][key] for b in blocks.values() if b["lists"][key]["rank"]),
                        key=lambda e: e["rank"])
        scores = [e["score"] for e in ranked]
        assert scores == sorted(scores, reverse=True), key


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


# --- one stock, one list --------------------------------------------------------

def test_momentum_gives_way_to_long_term():
    """Momentum and long term shared 12 of 15 names. Now they share none."""
    blocks = leaders.rank(universe(120))
    top = lambda key: {s for s, b in blocks.items() if (b["lists"][key]["rank"] or 99) <= leaders.LIST_SIZE}
    long_top, mom_top = top("long"), top("momentum")
    assert len(long_top) == leaders.LIST_SIZE and len(mom_top) == leaders.LIST_SIZE
    assert not long_top & mom_top
    for s in long_top:
        e = blocks[s]["lists"]["momentum"]
        assert e["rank"] is None and not e["eligible"]
        assert "long term list" in e["why_not"]


def test_long_term_and_the_short_lists_are_not_changed_by_giving_way():
    """Only momentum gives way: the other three rank every eligible stock."""
    blocks = leaders.rank(universe(120))
    for key in ("week", "month", "long"):
        for b in blocks.values():
            e = b["lists"][key]
            assert (e["rank"] is not None) == e["eligible"]
            assert e["why_not"] is None or "list. Each stock" not in e["why_not"]


def test_a_month_pick_has_to_be_a_market_leader():
    blocks = leaders.rank(universe(120))
    ranked = [b for b in blocks.values() if b["lists"]["month"]["rank"]]
    assert ranked
    assert all(b["score"] >= leaders.LEADER_FLOOR * 100 - 0.05 for b in ranked)
    followers = [b for b in blocks.values()
                 if b["uptrend"] and b["calm"] and b["score"] < leaders.LEADER_FLOOR * 100 - 0.05]
    assert followers
    assert all(b["lists"]["month"]["rank"] is None and "leader" in b["lists"]["month"]["why_not"]
               for b in followers)


def test_a_month_long_pullback_lifts_a_leader_on_the_month_list():
    base = universe()
    flat = leaders.rank(base + [cand("X", drift=0.004, noise=0.006, seed=99)])["X"]
    dipped = leaders.rank(base + [cand("X", drift=0.004, noise=0.006, seed=99, last21=-0.03)])["X"]
    assert dipped["parts"]["dip_month"] > flat["parts"]["dip_month"]
    assert dipped["lists"]["month"]["rank"] < flat["lists"]["month"]["rank"]
    assert dipped["lists"]["month"]["score"] > flat["lists"]["month"]["score"]
    assert any("this month" in w for w in dipped["lists"]["month"]["why"])
    assert dipped["facts"]["return_1m_pct"] == pytest.approx(-3.0, abs=0.3)


def test_a_fall_deep_enough_to_lose_the_lead_takes_a_stock_off_the_month_list():
    """The month list buys a pullback in a leader, not a stock that stopped leading."""
    deep = leaders.rank(universe() + [cand("X", drift=0.004, noise=0.006, seed=99, last21=-0.10)])["X"]
    assert deep["lists"]["month"]["rank"] is None
    assert "leader" in deep["lists"]["month"]["why_not"]


def test_the_published_record_is_for_lists_that_do_not_share_names():
    with open(os.path.join(HERE, "..", "..", "research", "ideas-study.json"), encoding="utf-8") as f:
        study = json.load(f)
    now = study["overlap"]["now"]
    assert now["momentum / long"] == 0
    assert now["distinct in all four"] > study["overlap"]["first version"]["distinct in all four"]


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
        # The results list makes a list only in the weeks companies report,
        # and its filings begin in 2018: fewer picks, a later first half.
        event = bool(leaders.LISTS[key].get("event"))
        assert rec["picks"] > (3000 if event else 5000) and 0 < rec["up_pct"] < 100
        assert set(rec["by_half"]) == ({"2018-21", "2022-26"} if event else {"2017-21", "2022-26"})
        assert set(rec["market"]) == {"above_200d", "below_200d"}


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
    assert leaders.plan("long", 100.0)["stop"] == 70.0
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
    for key in PRICE_LISTS:
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


def test_momentum_never_shows_a_stock_the_long_term_list_shows(quiet):
    """The engine leaves out long term's top 15. The page can reach further
    down long term (its sector cap and its fundamentals screen), so the page
    checks what long term actually shows as well."""
    blocks = leaders.rank(universe(120))
    order = sorted((s for s in blocks if blocks[s]["lists"]["long"]["rank"]),
                   key=lambda s: blocks[s]["lists"]["long"]["rank"])
    p = scan_payload(blocks, sectors={s: "One sector" for s in order[:8]})
    long_sel = ideas.select(p, horizon="long")
    shown = {r["symbol"] for r in long_sel["rows"]}
    assert any(blocks[s]["lists"]["long"]["rank"] > leaders.LIST_SIZE for s in shown), \
        "the sector cap should have reached past long term's top 15"
    mom = ideas.select(p, horizon="momentum")
    assert len(mom["rows"]) == 15
    assert not shown & {r["symbol"] for r in mom["rows"]}
    assert mom["gives_way_to"] == "long"
    assert any("long term list" in n for n in mom["selection_notes"])


@pytest.mark.parametrize("stamp", ["an older recipe", None])
def test_a_scan_ranked_with_an_earlier_recipe_does_not_print_this_recipes_record(quiet, stamp):
    """After a deploy that changes a recipe, the scan on disk still has the old
    ranks until the next scan. It answers, but without the new record."""
    blocks = leaders.rank(universe())
    for b in blocks.values():
        if stamp is None:
            b.pop("recipe")                  # ranked before blocks carried a stamp
        else:
            b["recipe"] = stamp
    sel = ideas.select(scan_payload(blocks), horizon="month")
    assert sel["method_key"] == "tested_lists" and len(sel["rows"]) == 15
    assert sel["tested"] is None and sel["recipe_current"] is False
    assert any("earlier recipe" in n for n in sel["selection_notes"])
    fresh = ideas.select(scan_payload(leaders.rank(universe())), horizon="month")
    assert fresh["recipe_current"] is True and fresh["tested"]


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
    assert sum(1 for v in chosen.values() if v == "leader") == 18, "leaders take at most three-fifths"
    for key in PRICE_LISTS:
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


# --- the results list ---------------------------------------------------------
#
# Ranked on how a stock moved the session its quarterly results were first
# priced, against the average liquid stock that day. What is pinned: which
# session that is, how old a result may be, and that nothing here can see a
# filing or a bar from the future.

def test_companies_are_ranked_on_the_day_their_results_were_priced():
    cands, results = reporters(n=12)
    blocks = leaders.rank(cands, results=results)
    ranked = sorted((b["lists"]["results"]["rank"], s) for s, b in blocks.items()
                    if b["lists"]["results"]["rank"])
    # S11 jumped the most on the session after it reported, S00 the least.
    assert [s for _r, s in ranked] == [f"S{i:02d}" for i in range(11, -1, -1)]
    top = blocks["S11"]
    assert top["results"]["session"] == DAYS[-2] and top["results"]["sessions_ago"] == 1
    assert top["results"]["move_pct"] == pytest.approx(12.7, abs=0.2)        # exp(0.12) - 1
    assert top["results"]["reaction_pct"] == pytest.approx(
        top["results"]["move_pct"] - top["results"]["market_move_pct"], abs=0.11)
    assert top["results"]["reported"] == 12
    assert any("Results on" in w for w in top["lists"]["results"]["why"])
    # A company that did not report is on every other list it earned, and not this one.
    assert blocks["S40"]["lists"]["results"]["rank"] is None
    assert "No results" in blocks["S40"]["lists"]["results"]["why_not"]


def test_a_result_filed_before_the_close_is_priced_that_session_and_after_it_the_next():
    """Two results in three reach the exchange after the close. Read against
    the wrong session, the 'reaction' is a day the market had not seen them."""
    cands, results = reporters(n=12)
    results["S05"] = filed(3, "14:10")          # during the session three back
    results["S06"] = filed(3, "15:31")          # one minute after that close
    results["S07"] = {"filed_at": DAYS[-4]}     # a bare date: read as the evening
    blocks = leaders.rank(cands, results=results)
    assert blocks["S05"]["results"]["session"] == DAYS[-4]
    assert blocks["S06"]["results"]["session"] == DAYS[-3]
    assert blocks["S07"]["results"]["session"] == DAYS[-3]


def test_a_result_filed_over_a_weekend_is_priced_on_monday():
    cands, results = reporters(n=12)
    last = pd.Timestamp(DAYS[-1])
    saturday = last - pd.Timedelta(days=(last.weekday() + 2) % 7 or 7)
    assert saturday.weekday() == 5
    results["S03"] = {"filed_at": saturday.strftime("%Y-%m-%d 11:00:00")}
    monday = (saturday + pd.Timedelta(days=2)).date().isoformat()
    assert leaders.rank(cands, results=results)["S03"]["results"]["session"] == monday


def test_a_result_older_than_ten_sessions_is_no_longer_news():
    cands, results = reporters(n=12)
    results["S02"] = filed(10)                  # priced nine sessions ago: the edge of the window
    results["S04"] = filed(11)                  # priced ten sessions ago: outside it
    results["S08"] = filed(200)                 # last year's
    blocks = leaders.rank(cands, results=results)
    assert blocks["S02"]["results"]["sessions_ago"] == 9
    assert blocks["S04"]["results"] is None and blocks["S08"]["results"] is None
    assert blocks["S04"]["lists"]["results"]["rank"] is None


def test_a_result_that_has_not_been_priced_yet_is_not_ranked():
    """Filed tonight, after the last bar: tomorrow's move is the reaction, and
    nobody has it."""
    cands, results = reporters(n=12)
    results["S09"] = filed(0, "19:00")
    blocks = leaders.rank(cands, results=results)
    assert blocks["S09"]["results"] is None


def test_fewer_than_eight_reporters_is_not_a_list():
    cands, results = reporters(n=7)
    blocks = leaders.rank(cands, results=results)
    assert all(b["lists"]["results"]["rank"] is None for b in blocks.values())
    assert "Fewer than 8" in blocks["S00"]["lists"]["results"]["why_not"]
    assert blocks["S00"]["results"]["reported"] == 7, "the result itself is still a fact on the stock"


def test_the_results_list_has_no_trend_or_volatility_gate():
    """It was tested without one: a falling stock that jumps on its numbers is
    exactly the kind of pick it makes."""
    cands, results = reporters(n=12)
    cands.append(cand("FALLING", drift=-0.002, jump=(1, 0.30)))
    results["FALLING"] = filed(2)
    b = leaders.rank(cands, results=results)["FALLING"]
    assert not b["uptrend"]
    assert b["lists"]["results"]["rank"] == 1
    assert all(b["lists"][k]["rank"] is None for k in PRICE_LISTS)


def test_without_filings_the_results_list_is_empty_and_the_others_are_unchanged():
    cands, results = reporters(n=12)
    with_results, without = leaders.rank(cands, results=results), leaders.rank(cands)
    for sym in without:
        assert without[sym]["results"] is None
        for key in PRICE_LISTS:
            assert with_results[sym]["lists"][key]["rank"] == without[sym]["lists"][key]["rank"]


# --- the chart and the tape ----------------------------------------------------

def test_technicals_never_see_a_later_bar():
    df = frame(n=400, seed=5)
    early = leaders.technicals(df.iloc[:330])
    df2 = df.copy()
    df2.iloc[330:, :] = df2.iloc[330:, :] * 3.0
    assert leaders.technicals(df2.iloc[:330]) == early


def test_a_first_six_month_high_in_twenty_sessions_is_a_breakout():
    # Flat for a year, then one strong close on three times the volume.
    flat = frame(n=320, drift=0.0, noise=0.002, seed=2, jump=(1, 0.08), volume_on=(1, 3.0))
    b = leaders.technicals(flat)["breakout"]
    assert b["sessions_ago"] == 1 and b["rel_volume"] == pytest.approx(3.0, rel=0.1)


def test_a_stock_making_highs_every_day_is_not_breaking_out():
    """Twenty quiet sessions are what make a new high a breakout and not one
    more day of a run."""
    climbing = frame(n=320, drift=0.004, noise=0.0005, seed=2)
    t = leaders.technicals(climbing)
    assert t["breakout"] is None and t["to_pivot"] > 0.99


def test_a_breakout_older_than_five_sessions_is_not_reported():
    old = frame(n=320, drift=0.0, noise=0.002, seed=2, jump=(8, 0.08))
    assert leaders.technicals(old)["breakout"] is None


def test_the_indicators_are_the_textbook_ones():
    up = leaders.technicals(frame(n=320, drift=0.004, noise=0.002, seed=4))
    down = leaders.technicals(frame(n=320, drift=-0.004, noise=0.002, seed=4))
    assert up["rsi"] > 70 > 30 > down["rsi"]
    assert up["above_20d_pct"] > 0 > down["above_20d_pct"]
    assert up["adx"] > 25 and down["adx"] > 25, "both are strong trends; ADX has no direction"
    assert 0 < up["up_down_volume"] and up["up_down_volume"] > down["up_down_volume"]


def test_technicals_ride_with_every_ranked_stock_and_move_no_rank():
    cands = universe()
    blocks = leaders.rank(cands)
    assert all(b["technicals"] and b["technicals"]["rsi"] is not None for b in blocks.values())
    stripped = [{"symbol": c["symbol"], "leader_sig": {k: v for k, v in c["leader_sig"].items() if k != "tech"}}
                for c in cands]
    plain = leaders.rank(stripped)
    for sym in blocks:
        for key in PRICE_LISTS:
            assert blocks[sym]["lists"][key]["rank"] == plain[sym]["lists"][key]["rank"]


# --- the Ideas layer, for what is new -------------------------------------------

def test_the_results_list_is_served_with_its_record_and_its_ledger(quiet):
    cands, results = reporters(n=12)
    sel = ideas.select(scan_payload(leaders.rank(cands, results=results)), horizon="results", limit=15)
    assert sel["list"] == "results" and sel["event"] == "results" and sel["count"] == 12
    assert [r["symbol"] for r in sel["rows"]][:2] == ["S11", "S10"]
    assert sel["tested"]["hold_sessions"] == 21 and sel["tested"]["exit_pct"] == 12.0
    assert "2018-21" in sel["tested"]["by_half"]
    for r in sel["rows"]:
        assert r["setup_key"] == "pick_results" and r["plan"]["risk_pct"] == 12.0
        assert sum(e["points"] for e in r["evidence"]) == pytest.approx(r["conviction"], abs=1.5)
        assert "results reached the exchange" in r["evidence"][0]["detail"]
        assert r["results"]["session"] == DAYS[-2]


def test_an_empty_results_list_says_why(quiet):
    cands, results = reporters(n=5)
    sel = ideas.select(scan_payload(leaders.rank(cands, results=results)), horizon="results")
    assert sel["count"] == 0 and "5 liquid companies" in sel["empty_text"] and "needs 8" in sel["empty_text"]
    none = ideas.select(scan_payload(leaders.rank(universe())), horizon="results")
    assert none["count"] == 0 and "No liquid company" in none["empty_text"]


def test_every_pick_carries_the_chart_facts_and_a_note_that_they_rank_nothing(quiet):
    sel = ideas.select(scan_payload(leaders.rank(universe())), horizon="momentum")
    assert "none of them changes a rank" in sel["chart_note"]
    for r in sel["rows"]:
        kinds = [c["k"] for c in r["chart"]]
        assert "Indicators" in kinds and "Averages" in kinds
        assert all(c["v"].endswith(".") for c in r["chart"])


def test_chart_facts_read_like_sentences():
    tech = {"breakout": {"sessions_ago": 2, "rel_volume": 2.4, "level": 100.0}, "above_20d_pct": 3.0,
            "rsi": 64.0, "macd_hist_pct": 0.2, "macd_rising": True, "adx": 31.0, "rel_volume": 1.6,
            "up_down_volume": 1.8, "squeeze": 0.6, "below_60d_high_pct": 0.0}
    rows = {c["k"]: c["v"] for c in ideas.chart_facts(
        tech, {"sma50": 90.0, "sma200": 120.0},
        {"name": "Cup and handle", "status": "forming", "trigger": 131.5, "distance_to_trigger_pct": 4.2},
        price=110.0)}
    assert rows["Breakout"].startswith("Closed at a six-month high 2 sessions ago, on 2.4 times")
    assert rows["Averages"] == "Above its 20 and 50-day averages, under its 200-day."
    assert rows["Indicators"] == "RSI 64 · MACD above its signal line and rising · ADX 31."
    assert rows["Range"].startswith("Tightening")
    assert "confirms on a close through" in rows["Pattern"] and "4.2% away" in rows["Pattern"]
    assert ideas.chart_facts(None) == []


def test_the_page_is_told_what_the_test_found_in_a_market_like_todays(quiet, monkeypatch):
    """The old page warned that trend setups fail under a weak index. Measured
    on these lists they did not, so the page says what was measured."""
    monkeypatch.setattr(ideas, "market_regime", lambda: {"ok": False, "pct_vs_200dma": -4.0, "label": "x"})
    sel = ideas.select(scan_payload(leaders.rank(universe())), horizon="momentum")
    rec = ideas.tested_record("momentum")["market"]
    assert sel["market_test"]["state"] == "below_200d"
    assert f"{rec['below_200d']['avg_pct']:+.1f}%" in sel["market_test"]["text"]
    assert "not held back" in sel["market_test"]["text"]
    monkeypatch.setattr(ideas, "market_regime", lambda: {"ok": True, "pct_vs_200dma": 6.0, "label": "x"})
    assert ideas.select(scan_payload(leaders.rank(universe())), horizon="momentum")["market_test"]["state"] == "above_200d"


def test_an_order_is_shown_with_its_size_against_the_company(quiet, monkeypatch):
    payload = scan_payload(leaders.rank(universe()))
    winner = ideas.select(payload, horizon="momentum")["rows"][0]["symbol"]

    class Ledger:
        @staticmethod
        def history(start, end):
            return [{"symbol": winner, "date": "2025-03-01", "value_cr": 450.0, "market_cap_cr": 3700.0,
                     "pct_of_market_cap": 12.2, "headline": "Order win", "value_confident": 1},
                    {"symbol": winner, "date": "2025-03-03", "value_cr": 40.0, "pct_of_market_cap": 1.1}]
    monkeypatch.setattr(ideas, "wow_orders", Ledger)
    monkeypatch.setitem(ideas._orders_cache, "at", 0.0)
    sel = ideas.select(payload, horizon="momentum")
    row = sel["rows"][0]
    assert row["symbol"] == winner, "an order is a fact beside the pick; it moves no rank"
    assert row["order"]["value_cr"] == 450.0 and row["order"]["pct_of_market_cap"] == 12.2
    assert all(r["order"] is None for r in sel["rows"][1:])
    monkeypatch.setitem(ideas._orders_cache, "at", 0.0)


# --- the scan asks who reported -------------------------------------------------

def test_the_scan_takes_the_first_filing_of_the_newest_quarter_and_skips_revisions(monkeypatch):
    import scan
    import sys
    import types
    day = dt.date(2026, 11, 11)
    cal = types.SimpleNamespace(filings=lambda start, end: [
        {"symbol": "AAA", "at": dt.datetime(2026, 11, 5, 18, 0), "quarter_end": dt.date(2026, 9, 30), "revised": False},
        {"symbol": "AAA", "at": dt.datetime(2026, 11, 4, 17, 0), "quarter_end": dt.date(2026, 9, 30), "revised": False},
        {"symbol": "AAA", "at": dt.datetime(2026, 11, 9, 12, 0), "quarter_end": dt.date(2026, 9, 30), "revised": True},
        {"symbol": "BBB", "at": dt.datetime(2026, 11, 6, 9, 0), "quarter_end": dt.date(2026, 9, 30), "revised": True},
    ])
    store = types.SimpleNamespace(recent_quarterly=lambda since: [
        {"symbol": "AAA", "label": "Q2 FY27", "filed_at": "2026-11-05 18:00:00", "pat_yoy_pct": 41.0,
         "revenue_yoy_pct": 12.0},
        {"symbol": "CCC", "label": "Q2 FY27", "filed_at": "2026-11-03 16:45:10", "pat_yoy_pct": -8.0,
         "revenue_yoy_pct": 2.0}])
    monkeypatch.setitem(sys.modules, "results_calendar", cal)
    monkeypatch.setitem(sys.modules, "fundamentals_store", store)
    out = scan.recent_results(day)
    assert out["AAA"] == {"filed_at": "2026-11-04 17:00:00", "quarter": "Q2 FY27",
                          "pat_yoy_pct": 41.0, "revenue_yoy_pct": 12.0}
    assert "BBB" not in out, "a revision is not the day the market learned the numbers"
    assert out["CCC"]["filed_at"] == "2026-11-03 16:45:10", "a filing only the tables know of still counts"


def test_the_scan_survives_both_results_sources_failing(monkeypatch):
    import scan
    import sys
    import types

    def boom(*a, **k):
        raise RuntimeError("NSE refused")
    monkeypatch.setitem(sys.modules, "results_calendar", types.SimpleNamespace(filings=boom))
    monkeypatch.setitem(sys.modules, "fundamentals_store", types.SimpleNamespace(recent_quarterly=boom))
    assert scan.recent_results(dt.date(2026, 11, 11)) == {}


# --- companies listed under a year ----------------------------------------------
#
# Tested before they were let in: on the week and momentum lists the picks that
# were six to twelve months old led the average stock in both halves of the
# decade; on the month, long-term and results lists they did not.

def newcomer(sym="NEWCO", **kw):
    kw.setdefault("drift", 0.004)
    kw.setdefault("noise", 0.006)
    return {"symbol": sym, "leader_sig": leaders.signals(frame(n=200, **kw))}


def test_a_young_company_is_ranked_on_the_two_lists_it_earned_and_no_other():
    blocks = leaders.rank(universe() + [newcomer()])
    b = blocks["NEWCO"]
    assert b["young"] is True and b["listed_sessions"] == 200
    assert b["lists"]["momentum"]["rank"] and b["lists"]["week"]["eligible"]
    for key in ("month", "long", "results"):
        assert b["lists"][key]["rank"] is None
        assert "Listed under a year" in b["lists"][key]["why_not"]
    assert b["facts"]["return_12m_pct"] is None and b["facts"]["return_6m_pct"] is not None
    assert any(w.startswith("Listed ") for w in b["lists"]["momentum"]["why"])


def test_letting_young_companies_in_changes_no_established_stocks_score():
    """They are placed against the established universe, not added to it, so
    the month, long-term and results lists are exactly what they were."""
    before = leaders.rank(universe())
    after = leaders.rank(universe() + [newcomer("NEW1"), newcomer("NEW2", seed=9, drift=0.002)])
    for sym, b in before.items():
        assert after[sym]["parts"] == b["parts"] and after[sym]["universe"] == b["universe"]
        for key in leaders.ORDER:
            assert after[sym]["lists"][key]["score"] == b["lists"][key]["score"]
        for key in ("month", "long"):
            assert after[sym]["lists"][key]["rank"] == b["lists"][key]["rank"]


def test_a_young_company_passes_the_same_gates_as_everyone():
    falling = leaders.rank(universe() + [newcomer("DOWN", drift=-0.003)])["DOWN"]
    assert not falling["uptrend"] and all(v["rank"] is None for v in falling["lists"].values())
    wild = leaders.rank(universe() + [newcomer("WILD", drift=0.006, noise=0.06, seed=3)])["WILD"]
    assert "volatile" in wild["lists"]["momentum"]["why_not"]
    thin = leaders.rank(universe() + [newcomer("THIN", turnover=5e7)])
    assert "THIN" not in thin


def test_a_young_company_is_not_on_the_results_list_even_if_it_reported():
    cands, results = reporters(n=12)
    cands.append(newcomer("NEWCO", jump=(1, 0.40)))
    results["NEWCO"] = filed(2)
    b = leaders.rank(cands, results=results)["NEWCO"]
    assert b["results"] is None and b["lists"]["results"]["rank"] is None


def test_a_young_pick_says_it_is_young_and_how_it_was_ranked(quiet):
    sel = ideas.select(scan_payload(leaders.rank(universe() + [newcomer()])), horizon="momentum")
    row = next(r for r in sel["rows"] if r["symbol"] == "NEWCO")
    assert row["young"] is True
    assert "6-month return" in row["evidence"][0]["detail"] and "stands in" in row["evidence"][0]["detail"]
    assert any("Listed under a year" in n and "NEWCO" in n for n in sel["selection_notes"])
    assert sum(e["points"] for e in row["evidence"]) == pytest.approx(row["conviction"], abs=1.5)


def test_the_study_measured_the_young_picks_before_they_were_admitted():
    with open(os.path.join(HERE, "..", "..", "research", "ideas-study.json"), encoding="utf-8") as f:
        study = json.load(f)
    for key in leaders.YOUNG_LISTS:
        young = study["lists"][key]["young"]
        assert young["picks"] > 100
        halves = young["vs_average_stock"]["by_half"]
        assert all(h["excess_pct"] > 0 for h in halves.values()), f"young picks trailed on {key}"
    for key in set(leaders.LISTS) - set(leaders.YOUNG_LISTS):
        assert "young" not in study["lists"][key]
