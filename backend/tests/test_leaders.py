"""
The pick lists: Swing / This month, After results, Long-term compounders,
and the setup lists.

What is pinned here is what would make the Ideas page lie if it broke: a
signal that can see tomorrow's bar, a recipe that drifts away from the one
the study measured, an exit line that follows the price down, a pick that
skipped a gate, a list that read a figure the company never filed as a zero,
and a deploy that blanks the page until the next scan.
"""
import datetime as dt
import json
import os
import re
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


_SIGNALS = {}


def cand(sym, **kw):
    """A candidate as the scan hands it to rank(). Its frame is drawn from a
    seed, so the same arguments are the same stock and its signals are
    worked out once for the whole file (rank() reads them, never changes
    them)."""
    key = tuple(sorted(kw.items()))
    if key not in _SIGNALS:
        _SIGNALS[key] = leaders.signals(frame(**kw))
    return {"symbol": sym, "leader_sig": _SIGNALS[key]}


# The lists ranked on price alone. The results list is ranked on a filing and
# is empty unless someone has reported, so it has tests of its own below.
PRICE_LISTS = tuple(k for k in leaders.ORDER if not leaders.LISTS[k].get("event"))
DAYS = [d.date().isoformat() for d in pd.bdate_range("2025-01-01", periods=320)]


def filed(sessions_ago, hhmm="18:30"):
    """A filing timestamp on the date of a session `sessions_ago` back."""
    return {"filed_at": f"{DAYS[-1 - sessions_ago]} {hhmm}:00"}


def reporters(n=12, start=2, step=0.01):
    """A universe in which S00..S(n-1) reported: each jumped a different
    amount (`step` more each) on the session after its results, filed `start`
    sessions back, on a volume that grew with the jump (as a real result
    day's does)."""
    cands, results = [], {}
    for i in range(60):
        kw = dict(drift=0.0004 + 0.00004 * i, noise=0.006 + 0.0003 * (i % 9), seed=i)
        if i < n:
            # Filed after the close `start` sessions ago: priced the session after.
            kw["jump"] = (start - 1, step * (i + 1))
            kw["volume_on"] = (start - 1, 1.5 + 0.1 * i)
            results[f"S{i:02d}"] = filed(start)
        cands.append(cand(f"S{i:02d}", **kw))
    return cands, results


def universe(n=60):
    """Sixty liquid uptrends of varying strength and calm."""
    out = []
    for i in range(n):
        out.append(cand(f"S{i:02d}", drift=0.0004 + 0.00004 * i, noise=0.006 + 0.0003 * (i % 9), seed=i))
    return out


def industries(cands, k=10):
    """Each stock in one of k NSE industries, every one with enough liquid
    members to be ranked on money flow."""
    return {c["symbol"]: f"Ind{i % k}" for i, c in enumerate(cands)}


def healthy(**over):
    """A snapshot of a company whose filings pass every test of the three
    lists: growing, profitable, cash-backed, little debt, nothing pledged."""
    s = {"basis": "consolidated", "is_financial": False, "quarter": "Q2 FY27",
         "revenue_yoy_pct": 18.0, "ebitda_yoy_pct": 20.0, "pat_yoy_pct": 22.0, "opm_pct": 18.0,
         "opm_yoy_chg": 1.0, "prev_revenue_yoy_pct": 15.0, "revenue_cr": 500.0, "pat_cr": 60.0,
         "ebitda_cr": 95.0, "core_ebitda_cr": 95.0, "exceptional_cr": 0.0, "pbt_cr": 80.0,
         "other_income_cr": 5.0, "other_income_share_pct": 6.0, "earnings_quality_ok": True,
         "eps_ttm": 24.0, "revenue_ttm_yoy_pct": 17.0, "pat_ttm_yoy_pct": 20.0, "rev_cagr_3y": 16.0,
         "pat_cagr_3y": 19.0, "opm_trend_2y": 1.5, "cfo_cr": 220.0, "fcf_cr": 150.0,
         "fcf_pos_years_3y": 3, "cfo_to_pat": 1.1, "debt_equity_x": 0.2, "roe_pct": 21.0,
         "roce_pct": 24.0, "f_score": 7, "pe": 32.0, "peg": 1.7, "ev_ebitda": 20.0,
         "pledge_pct": 0.0, "promoter_chg_4q": 0.5, "fii_dii_chg_1q": 0.3,
         "delivery_spike": False, "order_win_pct_mcap": None}
    s.update(over)
    return s


def market(n=120, k=10, **snap_over):
    """n liquid uptrends in k industries, every company with a healthy
    snapshot: (candidates, sectors, snapshots)."""
    cands = universe(n)
    return cands, industries(cands, k), {c["symbol"]: healthy(**snap_over) for c in cands}


def realistic(n=240, k=20, seed=7):
    """
    A market that looks like the real one: drifts and calm that vary, a third
    of the stocks pulling back over the last month or week, a handful that
    reported results in the last fortnight, and filings that differ the way
    companies do (growth, margins, returns, cash, debt, valuation, pledges),
    with growth and returns related as they are in practice. Returns
    (candidates, sectors, snapshots, results).
    """
    rng = np.random.default_rng(seed)
    cands, snaps, results = [], {}, {}
    for i in range(n):
        sym = f"R{i:03d}"
        kw = dict(drift=float(rng.uniform(-0.0004, 0.0022)), noise=float(rng.uniform(0.006, 0.02)), seed=1000 + i)
        roll = rng.uniform()
        if roll < 0.20:
            kw["last21"] = float(rng.uniform(-0.12, -0.02))
        elif roll < 0.33:
            kw["last5"] = float(rng.uniform(-0.07, -0.015))
        if i % 16 == 0:
            kw["jump"] = (2, float(rng.uniform(0.0, 0.12)))
            kw["volume_on"] = (2, float(rng.uniform(1.0, 4.0)))
            results[sym] = filed(3)
        cands.append(cand(sym, **kw))
        quality = float(rng.normal())                     # a company's underlying strength
        growth = 12 + 10 * quality + float(rng.normal(0, 8))
        fin = i % 11 == 0
        snaps[sym] = healthy(
            is_financial=fin, revenue_yoy_pct=round(growth, 1), prev_revenue_yoy_pct=round(growth + rng.normal(0, 5), 1),
            pat_yoy_pct=round(growth * 1.2 + float(rng.normal(0, 10)), 1), ebitda_yoy_pct=round(growth + 2, 1),
            opm_yoy_chg=round(float(rng.normal(0.3 * quality, 2)), 2),
            roce_pct=None if fin else round(16 + 8 * quality + float(rng.normal(0, 5)), 1),
            roe_pct=round(15 + 6 * quality + float(rng.normal(0, 4)), 1),
            cfo_to_pat=None if fin else round(0.9 + 0.2 * quality + float(rng.normal(0, 0.3)), 2),
            debt_equity_x=round(abs(float(rng.normal(0.5, 0.6))), 2),
            rev_cagr_3y=round(growth * 0.9 + float(rng.normal(0, 4)), 1),
            pat_cagr_3y=round(growth + float(rng.normal(0, 6)), 1),
            pe=round(float(np.exp(rng.normal(3.4, 0.5))), 1), peg=round(float(np.exp(rng.normal(0.4, 0.5))), 2),
            ev_ebitda=None if fin else round(float(np.exp(rng.normal(2.9, 0.4))), 1),
            pledge_pct=0.0 if rng.uniform() < 0.8 else round(float(rng.uniform(0.5, 20)), 1),
            f_score=None if fin else int(rng.integers(3, 10)))
    return cands, industries(cands, k), snaps, results


def top(blocks, key, n=None):
    """The symbols a list ranks in its top n (LIST_SIZE by default)."""
    n = n or leaders.LIST_SIZE
    return {s for s, b in blocks.items() if (b["lists"][key]["rank"] or 999) <= n}


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
    cands, sectors, snaps = market()
    cands.append(cand("FALLING", drift=-0.002))
    sectors["FALLING"], snaps["FALLING"] = "Ind0", healthy()
    b = leaders.rank(cands, sectors=sectors, snapshot=snaps)["FALLING"]
    assert not b["uptrend"]
    assert all(v["rank"] is None and not v["eligible"] for v in b["lists"].values())
    assert "uptrend" in b["lists"]["month"]["why_not"]
    assert b["lists"]["long"]["why_not"] == "Under its 200-day average."


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


def test_a_dip_lifts_a_stock_on_the_month_list_and_not_on_the_long_term_list():
    base = universe()
    flat = leaders.rank(base + [cand("X", drift=0.0015, noise=0.006, seed=99)])["X"]
    dipped = leaders.rank(base + [cand("X", drift=0.0015, noise=0.006, seed=99, last5=-0.04)])["X"]
    assert dipped["parts"]["dip"] > flat["parts"]["dip"]
    gain_month = dipped["lists"]["month"]["score"] - flat["lists"]["month"]["score"]
    gain_long = dipped["lists"]["long"]["score"] - flat["lists"]["long"]["score"]
    assert gain_month > 0 and gain_month > gain_long


# --- one stock, one list --------------------------------------------------------

def test_the_three_lists_overlap_little_without_giving_way():
    """
    The first version of the price lists shared 10 to 12 of their 15 names,
    and momentum was made to give way to long term to stop it. The three
    fundamental lists read different things (a pullback and a growing last
    quarter; a result the market rewarded; returns, cash and a fair price),
    so on a market that looks like the real one they share little with no
    list made to give way to another. Replayed on NSE from 2017 to 2026
    (research/fundamental-ideas-lab.json) the swing and long lists shared 2.7
    of their 15 names a date on average, results and long 1.2, swing and
    results 1.0. One synthetic market here puts 6 in common on one pair; the
    average across them is what the real record bounds.
    """
    assert not any(spec.get("gives_way_to") for spec in leaders.LISTS.values())
    shared = []
    for seed in (7, 11, 23):
        cands, sectors, snaps, results = realistic(n=400, k=25, seed=seed)
        blocks = leaders.rank(cands, results=results, sectors=sectors, snapshot=snaps)
        tops = {k: top(blocks, k) for k in leaders.ORDER}
        assert len(tops["month"]) == len(tops["long"]) == leaders.LIST_SIZE and len(tops["results"]) >= 8
        for a, b in (("month", "long"), ("month", "results"), ("results", "long")):
            n = len(tops[a] & tops[b])
            assert n <= leaders.LIST_SIZE * 2 // 5, (seed, a, b, n)
            shared.append(n)
    assert sum(shared) / len(shared) <= leaders.LIST_SIZE / 6


def test_every_eligible_stock_is_ranked_and_the_industry_cap_says_why_it_left_one_out():
    """No list gives way any more. Every eligible stock on the three lists is
    ranked; one left out by its list's cap on a single industry says so."""
    cands, sectors, snaps = market(120, 6)
    blocks = leaders.rank(cands, sectors=sectors, snapshot=snaps)
    capped = 0
    for key in leaders.ORDER:
        for b in blocks.values():
            e = b["lists"][key]
            assert (e["rank"] is not None) == e["eligible"]
            assert e["why_not"] is None or "list. Each stock" not in e["why_not"]
            capped += bool(e["why_not"] and "from its industry rank higher" in e["why_not"])
        per = {}
        for s, b in blocks.items():
            if b["lists"][key]["rank"]:
                per[sectors[s]] = per.get(sectors[s], 0) + 1
        assert not per or max(per.values()) <= leaders.recipe_of(key)["sector_cap"], key
    assert capped, "with six industries a list of fifteen has to be capped somewhere"


def test_a_month_pick_has_to_be_a_market_leader():
    cands, sectors, snaps = market()
    blocks = leaders.rank(cands, sectors=sectors, snapshot=snaps)
    floor = leaders.MONTH["leader_floor"]
    assert floor == leaders.LEADER_FLOOR == 0.70
    ranked = [b for b in blocks.values() if b["lists"]["month"]["rank"]]
    assert ranked
    assert all(b["score"] >= floor * 100 - 0.05 for b in ranked)
    followers = [b for b in blocks.values()
                 if b["uptrend"] and b["calm"] and b["score"] < floor * 100 - 0.05]
    assert followers
    assert all(b["lists"]["month"]["rank"] is None and "top 30%" in b["lists"]["month"]["why_not"]
               for b in followers)


def test_a_month_long_pullback_lifts_a_leader_on_the_month_list(monkeypatch):
    # The pullback is what is measured here, so the industry screen is off:
    # with it on, the stock's industry would decide the case.
    monkeypatch.setitem(leaders.MONTH, "sector_gate", False)
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
    # Reads today's study file, whose lists are the November ones; the lab
    # regenerates it for the three fundamental lists (research/IDEAS-STUDY.md).
    with open(os.path.join(HERE, "..", "..", "research", "ideas-study.json"), encoding="utf-8") as f:
        study = json.load(f)
    if "overlap" not in study:
        pytest.skip("the study file carries no overlap table; the lab's own file does")
    now = study["overlap"]["now"]
    if "momentum / long" in now:
        assert now["momentum / long"] == 0
        assert now["distinct in all four"] > study["overlap"]["first version"]["distinct in all four"]
    else:
        pairs = [v for k, v in now.items() if " / " in k and isinstance(v, (int, float))]
        assert pairs and all(v <= leaders.LIST_SIZE // 3 for v in pairs)


# --- the recipes are the ones the study measured ----------------------------

def test_every_mix_sums_to_one():
    for key, spec in leaders.LISTS.items():
        assert sum(spec["mix"].values()) == pytest.approx(1.0), key
        assert sum(leaders.mix_of(key).values()) == pytest.approx(1.0), key
    assert sum(leaders.MONTH["pull_mix"].values()) == pytest.approx(1.0)
    # The three lists' weights are their recipe dictionaries' own.
    for key, cfg in (("month", leaders.MONTH), ("results", leaders.RESULTS), ("long", leaders.LONG)):
        assert leaders.recipe_of(key) is cfg and leaders.LISTS[key]["mix"] is cfg["mix"]


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
    assert leaders.resolve("short") == "short"        # its own list now, not a name for momentum
    assert leaders.resolve("medium") == "long" and leaders.resolve("invest") == "long"
    # This week and momentum were folded into the fundamental lists: their
    # names, and the old switch's, open the list that replaced each.
    assert leaders.resolve("WEEK") == "month" and leaders.resolve("trade") == "month"
    assert leaders.resolve("momentum") == "long" and leaders.resolve(" Position ") == "long"
    assert leaders.resolve("nonsense") is None and leaders.resolve(None) is None


def test_the_lists_are_the_three_fundamental_ones_and_the_setups():
    assert leaders.ORDER == ("month", "results", "long")
    assert "week" not in leaders.LISTS and "momentum" not in leaders.LISTS
    assert leaders.YOUNG_LISTS == ()
    assert leaders.RECIPE == "2026-12 fundamental lists v3"
    assert leaders.DAYS_KEPT == 23
    assert set(leaders.ALL) == set(leaders.LISTS)
    for key, spec in leaders.LISTS.items():
        assert len(key) <= 10 and spec["setup_key"] == f"pick_{key}", key
    # What each was called, and how long each is held: what the call log,
    # the tracker and the study key on.
    assert [leaders.LISTS[k]["label"] for k in leaders.ORDER] == \
        ["Swing / This month", "After results", "Long-term compounders"]
    assert [(leaders.LISTS[k]["hold_sessions"], leaders.LISTS[k]["exit_pct"]) for k in leaders.ORDER] == \
        [(21, 12.0), (21, 12.0), (252, 30.0)]


# --- the plan ----------------------------------------------------------------

def test_the_plan_has_an_exit_line_a_review_date_and_no_target():
    p = leaders.plan("month", 200.0, dt.date(2026, 11, 10))
    assert p["stop"] == 176.0 and p["risk_pct"] == 12.0
    assert p["t1"] is None and p["rr"] is None
    assert p["review_on"] == "2026-12-10"
    assert leaders.plan("results", 100.0, dt.date(2026, 11, 10))["stop"] == 88.0
    assert leaders.plan("long", 100.0)["stop"] == 70.0
    assert leaders.plan("long", 100.0, dt.date(2026, 11, 10))["review_on"] == "2027-11-10"
    assert leaders.plan("month", None) is None
    assert leaders.plan("nonsense", 100.0) is None


def test_the_mark_above_the_price_is_for_the_page_and_closes_nothing():
    """
    A reader asked where a good result would be. The plan marks it as far
    above the call price as the exit line is below it, and still carries no
    target to sell at: the call log closes a call on `t1`, and that stays
    None, so a pick is judged exactly as it was before the mark existed.
    """
    p = leaders.plan("month", 200.0, dt.date(2026, 11, 10))
    assert p["aim"] == 224.0 and p["aim_pct"] == 12.0
    assert p["aim"] - p["entry"] == p["entry"] - p["stop"]
    assert p["t1"] is None and p["rr"] is None and "targets" not in p
    import call_log
    assert call_log._levels({"plan": p})["target"] is None, "the mark would close a logged call"
    # A list that already says when to sell carries no mark.
    q = leaders.plan("emerging", 100.0)
    assert q["sell_rule"] == "sma50" and q["aim"] is None and q["aim_pct"] is None


def test_what_selling_at_the_mark_did_is_the_studys_own_figures():
    """Read from the study file's exits table, whatever lists it holds: a list
    with both runs there gets the study's own two records, any other none."""
    exits = leaders.TESTED["exits"]
    for key in leaders.ORDER:
        pct = leaders.LISTS[key]["exit_pct"]
        runs = exits.get(key) or {}
        sold = runs.get(f"close {pct:g}% under, target {pct:g}% over")
        held = runs.get(f"close {pct:g}% under")
        t = leaders.target_tested(key)
        if not (sold and held):
            assert t is None, key
            continue
        assert t["target_pct"] == pct
        assert t["sold"]["up_pct"] == sold["up_pct"] and t["sold"]["avg_pct"] == sold["avg_pct"]
        assert t["held"]["up_pct"] == held["up_pct"] and t["held"]["avg_pct"] == held["avg_pct"]
        # Held to the end is the list's own record, the one the page already prints.
        assert t["held"]["avg_pct"] == leaders.TESTED["lists"][key]["avg_pct"]
    assert leaders.target_tested("month") and leaders.target_tested("long")
    # Not tested that way: nothing is said, and nothing is made up.
    for key in ("technical", "breakout", "quick", "nonsense"):
        assert leaders.target_tested(key) is None


# --- the Ideas layer ----------------------------------------------------------

@pytest.fixture
def quiet(monkeypatch):
    monkeypatch.setattr(ideas, "sector_outlook", lambda: {})
    monkeypatch.setattr(ideas, "market_regime", lambda: None)
    monkeypatch.setattr(ideas, "_news_index", lambda hours: ({}, []))
    monkeypatch.setattr(ideas, "_filing_for", lambda sym, hours, cats: None)
    monkeypatch.setattr(ideas, "tracker", None)


@pytest.fixture
def stamped(monkeypatch):
    """The study file as the lab writes it once it has replayed this recipe:
    stamped with leaders.RECIPE. Today's file holds the November lists'
    records, which the page must not print beside the new ones."""
    monkeypatch.setitem(leaders.TESTED, "recipe", leaders.RECIPE)


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


def big_market():
    """Two hundred stocks in twenty industries, every company healthy: enough
    for the month list to fill fifteen places under its industry cap."""
    return market(200, 20)


def test_each_list_is_served_in_the_order_the_recipe_ranked_it(quiet, stamped):
    cands, sectors, snaps = big_market()
    p = scan_payload(leaders.rank(cands, sectors=sectors, snapshot=snaps))
    for key in PRICE_LISTS:
        sel = ideas.select(p, horizon=key, limit=15)
        assert sel["list"] == key and sel["method_key"] == "tested_lists"
        ranks = [r["pick_rank"] for r in sel["rows"]]
        assert ranks == sorted(ranks) and len(ranks) == 15, key
        assert all(r["setup_key"] == leaders.LISTS[key]["setup_key"] for r in sel["rows"])
        assert all(r["plan"]["t1"] is None and r["plan"]["stop"] < r["price"] for r in sel["rows"])
        assert sel["tested"]["hold_sessions"] == leaders.LISTS[key]["hold_sessions"]
        assert sel["weights"] == leaders.mix_of(key) and sel["study_current"] is True
        assert sel["method"] == ideas._tab_method(key)


def test_the_ledger_adds_up_to_the_score_beside_it(quiet):
    """Every part of each fundamental list's mix has a row, in plain words,
    and the rows add up to the conviction printed beside them."""
    cands, sectors, snaps, results = realistic(n=240, seed=7)
    p = scan_payload(leaders.rank(cands, results=results, sectors=sectors, snapshot=snaps))
    for key in leaders.ORDER:
        sel = ideas.select(p, horizon=key)
        assert sel["rows"], key
        weighted = {k for k, w in leaders.mix_of(key).items() if w > 0}
        for r in sel["rows"]:
            assert {e["key"] for e in r["evidence"]} == weighted, key
            assert sum(e["of"] for e in r["evidence"]) == pytest.approx(100, abs=0.5)
            assert sum(e["points"] for e in r["evidence"]) == pytest.approx(r["conviction"], abs=0.3)
            assert all(e["factor"] and e["detail"].endswith(".") for e in r["evidence"])


def test_a_ledger_from_before_the_breakdown_still_adds_up(quiet):
    """A scan ranked before December 2026 has no breakdown on its blocks. Until
    the next scan its ledger is rebuilt from the mix it was ranked on."""
    blocks = leaders.rank(universe())
    for b in blocks.values():
        b["recipe"] = "2026-12 setup lists v2"
        for key in leaders.ORDER:
            b["lists"][key].pop("breakdown", None)
        old = b["parts"]
        b["lists"]["long"]["score"] = round((old["momentum_12m"] + old["near_high"] + old["steady_trend"]) / 3, 1)
    sel = ideas.select(scan_payload(blocks), horizon="long")
    assert sel["rows"] and sel["recipe_current"] is False
    for r in sel["rows"]:
        assert [e["factor"] for e in r["evidence"]] == ["12-month return for its risk", "Closeness to the 52-week high",
                                                        "How steady the climb was"]
        assert sum(e["points"] for e in r["evidence"]) == pytest.approx(r["conviction"], abs=1.5)


def test_a_serious_adverse_filing_removes_a_pick_and_says_so(quiet, monkeypatch):
    blocks = leaders.rank(universe())
    first = min(blocks, key=lambda s: blocks[s]["lists"]["long"]["rank"] or 999)
    monkeypatch.setattr(ideas, "_filing_for", lambda sym, hours, cats: (
        {"category": "Regulatory action", "importance": "critical", "headline": "SEBI order",
         "line": "filed", "direction": "adverse"} if sym == first else None))
    sel = ideas.select(scan_payload(blocks), horizon="long")
    assert first not in [r["symbol"] for r in sel["rows"]]
    assert sel["excluded_adverse"][0]["symbol"] == first
    assert any("adverse filing" in n for n in sel["selection_notes"])


def test_one_sector_cannot_fill_the_list(quiet):
    blocks = leaders.rank(universe())
    sel = ideas.select(scan_payload(blocks, sectors={s: "Industrials" for s in blocks}), horizon="long")
    assert len(sel["rows"]) == ideas.PICK_SECTOR_CAP
    assert any("one sector" in n for n in sel["selection_notes"])


def test_the_long_term_list_is_screened_on_the_filings_by_the_engine_not_on_yahoo_by_the_page(quiet):
    """
    The page used to drop a long-term pick with a Piotroski score under 4 or
    a trailing loss read from Yahoo, a screen nobody had tested. The engine's
    own gates now read the company's filings and were replayed: a loss over
    the last four quarters, or an F-score under 5, takes a stock off the list
    in words, and the page drops nothing for Yahoo's figures.
    """
    assert not hasattr(ideas, "LONG_MIN_PIOTROSKI")
    cands, sectors, snaps = market(60, 5)
    blocks = leaders.rank(cands, sectors=sectors, snapshot=snaps)
    first = min(blocks, key=lambda s: blocks[s]["lists"]["long"]["rank"] or 999)
    p = scan_payload(blocks, extra={first: {"trailing_eps": -3.0, "f_score": 2}})
    assert first in [r["symbol"] for r in ideas.select(p, horizon="long")["rows"]]
    for over, text in (({"eps_ttm": -3.0}, "Lost money over the last four quarters."),
                       ({"f_score": 4}, "F-score 4 of 9: the list needs 5.")):
        again = leaders.rank(cands, sectors=sectors, snapshot=dict(snaps, **{first: healthy(**over)}))
        e = again[first]["lists"]["long"]
        assert e["rank"] is None and e["why_not"] == text


def test_an_old_momentum_or_week_link_opens_the_list_that_replaced_it(quiet):
    cands, sectors, snaps = big_market()
    p = scan_payload(leaders.rank(cands, sectors=sectors, snapshot=snaps))
    for old, new in (("momentum", "long"), ("position", "long"), ("week", "month"), ("trade", "month")):
        sel = ideas.select(p, horizon=old)
        assert sel["list"] == new and sel["gives_way_to"] is None, old
        assert [r["symbol"] for r in sel["rows"]] == [r["symbol"] for r in ideas.select(p, horizon=new)["rows"]]


@pytest.mark.parametrize("stamp", ["an older recipe", None])
def test_a_scan_ranked_with_an_earlier_recipe_does_not_print_this_recipes_record(quiet, stamped, stamp):
    """After a deploy that changes a recipe, the scan on disk still has the old
    ranks until the next scan. It answers, but without the new record."""
    blocks = leaders.rank(universe())
    for b in blocks.values():
        if stamp is None:
            b.pop("recipe")                  # ranked before blocks carried a stamp
        else:
            b["recipe"] = stamp
    sel = ideas.select(scan_payload(blocks), horizon="long")
    assert sel["method_key"] == "tested_lists" and len(sel["rows"]) == 15
    assert sel["tested"] is None and sel["recipe_current"] is False
    assert any("earlier recipe" in n for n in sel["selection_notes"])
    fresh = ideas.select(scan_payload(leaders.rank(universe())), horizon="long")
    assert fresh["recipe_current"] is True and fresh["tested"]


def test_a_study_of_the_lists_that_were_replaced_is_not_printed_beside_the_new_ones(quiet):
    """
    The study file is the record of a recipe. Until the lab has replayed the
    three fundamental lists and stamped the file with their recipe, a
    current scan's lists show no record rather than the November lists',
    and say why; the setup lists' records are the engine's own replay and
    stay.
    """
    if leaders.TESTED.get("recipe") == leaders.RECIPE:
        pytest.skip("the study file already carries this recipe's replay")
    p = scan_payload(leaders.rank(universe()))
    sel = ideas.select(p, horizon="long")
    assert sel["recipe_current"] is True and sel["study_current"] is False
    assert sel["tested"] is None and sel["target_test"] is None and sel["market_test"] is None
    assert any("not in the study file yet" in n for n in sel["selection_notes"])
    assert ideas.select(p, horizon="breakout")["tested"]


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
    assert ideas.select(p, horizon="short")["list"] == "short"
    assert ideas.select(p, horizon="medium")["list"] == "long"
    assert ideas.select(p, horizon="invest")["list"] == "long"


# --- the scan gives leaders a place ------------------------------------------

def test_the_scan_gives_the_top_of_every_list_a_place_in_phase_two():
    import scan
    cands = universe(80)
    blocks = leaders.rank(cands, sectors=industries(cands, 8),
                          snapshot={c["symbol"]: healthy() for c in cands})
    for i, c in enumerate(cands):
        c.update(score=float(i), turnover=5e8, leader=blocks.get(c["symbol"]))
        c.pop("leader_sig")
    cands.sort(key=lambda c: -c["score"])
    cohort, n_ranked, n_control = scan.pick_phase2_cohort(cands, 40, control_pct=0.25)
    chosen = {c["symbol"]: label for c, label in cohort}
    assert len(chosen) == 40 and n_ranked == 30
    assert sum(1 for v in chosen.values() if v == "leader") == 20, "leaders take at most two-thirds"
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


def pick(sym, price, key="month"):
    spec = leaders.LISTS[key]
    return {"symbol": sym, "name": sym, "sector": "Energy", "setup_key": spec["setup_key"],
            "setup": spec["setup"], "horizon": spec["hold_text"], "price": price, "conviction": 90.0,
            "conviction_band": "High", "plan": leaders.plan(key, price, dt.date(2026, 11, 2))}


S1, S2, S3 = "02 Nov 2026, 10:30", "03 Nov 2026, 10:30", "04 Nov 2026, 10:30"


def test_the_exit_line_stays_where_the_call_put_it(log):
    log.record("month", [pick("ABC", 100.0)], S1, {"ABC": 100.0})
    # The price fell 10%. A plan redrawn from today's price would put the line
    # at 79.2; the call's own line is 88 and must not move.
    log.record("month", [pick("ABC", 90.0)], S2, {"ABC": 90.0})
    call = log.listing()["rows"][0]
    assert call["status"] == "open" and call["stop"] == 88.0
    assert not [e for e in call["events"] if e["kind"] == "levels"]
    # Under the line at the next scan, and gone from the list.
    log.record("month", [], S3, {"ABC": 87.0})
    call = log.listing()["rows"][0]
    assert call["status"] == "closed" and call["outcome"] == "stop"
    assert call["price_now"] == 87.0


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


def test_the_week_and_momentum_calls_close_once_with_the_list_that_replaced_them(log):
    """This week and momentum left the page in December 2026. Their open
    calls would otherwise stay open for ever: nothing lists or drops them."""
    week = dict(pick("WK", 100.0), setup_key="pick_week", setup="Week pick")
    mom = dict(pick("MO", 200.0, "long"), setup_key="pick_momentum", setup="Momentum pick")
    log.record("week", [week], S1, {"WK": 100.0})
    log.record("momentum", [mom], S1, {"MO": 200.0})
    assert log.retire_replaced(S2, {"WK": 104.0, "MO": 210.0}) == 2
    assert log.retire_replaced(S3, {"WK": 90.0, "MO": 150.0}) == 0
    by = {r["horizon"]: r for r in log.listing()["rows"]}
    assert by["week"]["status"] == by["momentum"]["status"] == "closed"
    assert by["week"]["outcome"] == by["momentum"]["outcome"] == "dropped"
    assert by["week"]["price_now"] == 104.0 and by["momentum"]["price_now"] == 210.0
    notes = {h: [e["note"] for e in by[h]["events"] if e["kind"] == "dropped"] for h in by}
    assert notes["week"] == ["List replaced by Swing / This month."]
    assert notes["momentum"] == ["List replaced by Long-term compounders."]
    # They keep their own labels on the record.
    assert by["week"]["horizon_label"] == "This week" and by["momentum"]["horizon_label"] == "Momentum"


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
    # Every list's ideas expire on their own clock, the replaced lists' too.
    assert tracker.HORIZON_DAYS["pick_week"] < tracker.HORIZON_DAYS["pick_month"] \
        < tracker.HORIZON_DAYS["pick_momentum"] < tracker.HORIZON_DAYS["pick_long"]
    assert all(spec["setup_key"] in tracker.HORIZON_DAYS for spec in leaders.LISTS.values())


# --- the results list ---------------------------------------------------------
#
# Ranked on how a stock moved the session its quarterly results were first
# priced, against the average liquid stock that day. What is pinned: which
# session that is, how old a result may be, and that nothing here can see a
# filing or a bar from the future.

def reported(results, **over):
    """A healthy snapshot for every company in `results`: what each reported
    was real growth unless a test says otherwise."""
    return {s: healthy(**over) for s in results}


def test_companies_are_ranked_on_the_day_their_results_were_priced():
    cands, results = reporters(n=12)
    blocks = leaders.rank(cands, results=results, snapshot=reported(results))
    ranked = sorted((b["lists"]["results"]["rank"], s) for s, b in blocks.items()
                    if b["lists"]["results"]["rank"])
    # S11 jumped the most on the session after it reported, on the heaviest
    # volume; S00 the least. Their quarters were the same.
    assert [s for _r, s in ranked] == [f"S{i:02d}" for i in range(11, -1, -1)]
    top = blocks["S11"]
    assert top["results"]["session"] == DAYS[-2] and top["results"]["sessions_ago"] == 1
    assert top["results"]["move_pct"] == pytest.approx(12.7, abs=0.2)        # exp(0.12) - 1
    assert top["results"]["reaction_pct"] == pytest.approx(
        top["results"]["move_pct"] - top["results"]["market_move_pct"], abs=0.11)
    assert top["results"]["reported"] == 12 and top["results"]["qualified"] == 12
    assert top["results"]["vol_x"] == pytest.approx(2.6 / 1.12, rel=0.05)    # 2.6x the shares on a 12% higher price
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
    """A falling stock that jumps on real numbers is exactly the kind of pick
    it makes: no uptrend or calm gate, only a floor under a stock still far
    below its 200-day average."""
    cands, results = reporters(n=12)
    cands.append(cand("FALLING", drift=-0.001, jump=(1, 0.10), volume_on=(1, 3.0)))
    results["FALLING"] = filed(2)
    b = leaders.rank(cands, results=results, snapshot=reported(results))["FALLING"]
    assert not b["uptrend"]
    assert b["lists"]["results"]["eligible"] and b["lists"]["results"]["rank"] <= 5
    assert all(b["lists"][k]["rank"] is None for k in PRICE_LISTS)


def test_the_results_list_does_not_chase_and_leaves_a_stock_still_far_under_its_average():
    cands, results = reporters(n=12)
    cands += [cand("CHASED", jump=(1, 0.22), volume_on=(1, 4.0), seed=41),
              cand("SLUMP", drift=-0.004, jump=(1, 0.03), seed=42)]
    results.update(CHASED=filed(2), SLUMP=filed(2))
    blocks = leaders.rank(cands, results=results, snapshot=reported(results))
    assert blocks["CHASED"]["lists"]["results"]["why_not"] == \
        "Already rose 25% the day results were priced: the list does not chase."
    assert blocks["SLUMP"]["lists"]["results"]["why_not"] == "More than 15% under its 200-day average."


def test_the_results_floor_is_the_recipes_own(monkeypatch):
    """RESULTS["floor"] picks the floor the lab replays: none, within 15% of
    the 200-day average, or above the 50-day."""
    cands, results = reporters(n=12)
    cands.append(cand("SLUMP", drift=-0.004, jump=(1, 0.03), seed=42))
    results["SLUMP"] = filed(2)
    snaps = reported(results)
    monkeypatch.setitem(leaders.RESULTS, "floor", None)
    assert leaders.rank(cands, results=results, snapshot=snaps)["SLUMP"]["lists"]["results"]["eligible"]
    monkeypatch.setitem(leaders.RESULTS, "floor", "sma50")
    assert leaders.rank(cands, results=results, snapshot=snaps)["SLUMP"]["lists"]["results"]["why_not"] == \
        "Under its 50-day average."


def test_without_filings_the_results_list_is_empty_and_the_others_are_unchanged():
    # No reporter here was sold on its results, so the month list's result
    # guard has nothing to say and the price lists are exactly as they were.
    cands, results = reporters(n=12)
    snaps = reported(results)
    with_results = leaders.rank(cands, results=results, snapshot=snaps)
    without = leaders.rank(cands, snapshot=snaps)
    for sym in without:
        assert without[sym]["results"] is None
        assert without[sym]["lists"]["results"]["rank"] is None
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
    """RSI, MACD, ADX, the breakout and volume measures are facts beside a
    pick. Taken away, the month and long-term lists are exactly the same.
    (The industry's money flow is part of the month recipe: it is built from
    each stock's turnover and its 50-day average, which stay.)"""
    cands, sectors, snaps = market()
    blocks = leaders.rank(cands, sectors=sectors, snapshot=snaps)
    assert all(b["technicals"] and b["technicals"]["rsi"] is not None for b in blocks.values())
    flow = ("turnover_5", "turnover_60", "above_50d")
    stripped = [{"symbol": c["symbol"],
                 "leader_sig": dict(c["leader_sig"], tech={k: c["leader_sig"]["tech"][k] for k in flow})}
                for c in cands]
    plain = leaders.rank(stripped, sectors=sectors, snapshot=snaps)
    assert any(b["lists"]["month"]["rank"] for b in plain.values())
    for sym in blocks:
        for key in PRICE_LISTS:
            assert blocks[sym]["lists"][key]["rank"] == plain[sym]["lists"][key]["rank"]


# --- the Ideas layer, for what is new -------------------------------------------

def test_the_results_list_is_served_with_its_record_and_its_ledger(quiet, stamped):
    cands, results = reporters(n=12)
    blocks = leaders.rank(cands, results=results, snapshot=reported(results))
    sel = ideas.select(scan_payload(blocks), horizon="results", limit=15)
    assert sel["list"] == "results" and sel["event"] == "results" and sel["count"] == 12
    assert [r["symbol"] for r in sel["rows"]][:2] == ["S11", "S10"]
    assert sel["tested"]["hold_sessions"] == 21 and sel["tested"]["exit_pct"] == 12.0
    for r in sel["rows"]:
        assert r["setup_key"] == "pick_results" and r["plan"]["risk_pct"] == 12.0
        assert sum(e["points"] for e in r["evidence"]) == pytest.approx(r["conviction"], abs=0.3)
        assert "results reached the exchange" in r["evidence"][0]["detail"]
        assert [e["key"] for e in r["evidence"]] == ["reaction", "volume", "growth"]
        assert r["results"]["session"] == DAYS[-2]
    assert any("12 passed every test" in n for n in sel["selection_notes"])


def test_an_empty_results_list_says_why_and_when_it_fills_in(quiet):
    cands, results = reporters(n=5)
    sel = ideas.select(scan_payload(leaders.rank(cands, results=results, snapshot=reported(results))),
                       horizon="results")
    assert sel["count"] == 0 and "5 liquid companies" in sel["empty_text"] and "needs 8" in sel["empty_text"]
    none = ideas.select(scan_payload(leaders.rank(universe())), horizon="results")
    assert none["count"] == 0 and "No liquid company" in none["empty_text"]
    # Twelve reported and five passed every test: no list this season, and
    # the page says when companies report again.
    cands, results = reporters(n=12)
    snaps = reported(results)
    for s in list(results)[:7]:
        snaps[s] = healthy(revenue_yoy_pct=3.0)
    p = scan_payload(leaders.rank(cands, results=results, snapshot=snaps))
    p["scanned_at"] = "05 Dec 2026, 10:30"            # between seasons
    sel = ideas.select(p, horizon="results")
    assert sel["count"] == 0
    assert sel["empty_text"].startswith("12 liquid companies had results priced in the last 10 sessions and 5 "
                                        "passed every test; the list needs 8.")
    assert sel["empty_text"].endswith("Companies report again from about 10 January; this list fills in then.")
    p["scanned_at"] = "28 Oct 2026, 10:30"            # in the middle of a season
    assert "Companies are reporting now" in ideas.select(p, horizon="results")["empty_text"]


def test_the_next_results_season_is_named_from_the_calendar():
    season = leaders.next_results_season
    assert season(dt.date(2026, 12, 5)) == (dt.date(2027, 1, 10), False)
    assert season(dt.date(2027, 1, 9)) == (dt.date(2027, 1, 10), False)
    assert season(dt.date(2027, 1, 10)) == (dt.date(2027, 1, 10), True)
    assert season(dt.date(2026, 5, 29)) == (dt.date(2026, 4, 10), True)       # the March quarter runs late
    assert season(dt.date(2026, 6, 20)) == (dt.date(2026, 7, 10), False)
    assert season(dt.date(2026, 11, 20)) == (dt.date(2026, 10, 10), True)


def test_every_pick_carries_the_chart_facts_and_a_note_that_they_rank_nothing(quiet):
    sel = ideas.select(scan_payload(leaders.rank(universe())), horizon="long")
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


def test_the_page_is_told_what_the_test_found_in_a_market_like_todays(quiet, stamped, monkeypatch):
    """The old page warned that trend setups fail under a weak index. Measured
    on these lists they did not, so the page says what was measured."""
    monkeypatch.setattr(ideas, "market_regime", lambda: {"ok": False, "pct_vs_200dma": -4.0, "label": "x"})
    sel = ideas.select(scan_payload(leaders.rank(universe())), horizon="long")
    rec = ideas.tested_record("long")["market"]
    assert sel["market_test"]["state"] == "below_200d"
    assert f"{rec['below_200d']['avg_pct']:+.1f}%" in sel["market_test"]["text"]
    assert "not held back" in sel["market_test"]["text"]
    monkeypatch.setattr(ideas, "market_regime", lambda: {"ok": True, "pct_vs_200dma": 6.0, "label": "x"})
    assert ideas.select(scan_payload(leaders.rank(universe())), horizon="long")["market_test"]["state"] == "above_200d"


def test_an_order_is_shown_with_its_size_against_the_company(quiet, monkeypatch):
    payload = scan_payload(leaders.rank(universe()))
    winner = ideas.select(payload, horizon="long")["rows"][0]["symbol"]

    class Ledger:
        @staticmethod
        def history(start, end):
            return [{"symbol": winner, "date": "2025-03-01", "value_cr": 450.0, "market_cap_cr": 3700.0,
                     "pct_of_market_cap": 12.2, "headline": "Order win", "value_confident": 1},
                    {"symbol": winner, "date": "2025-03-03", "value_cr": 40.0, "pct_of_market_cap": 1.1}]
    monkeypatch.setattr(ideas, "wow_orders", Ledger)
    monkeypatch.setitem(ideas._orders_cache, "at", 0.0)
    sel = ideas.select(payload, horizon="long")
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
# decade; on the month, long-term and results lists they did not. Since week
# and momentum were folded into the fundamental lists (December 2026), such a
# company is on the emerging list only.

def newcomer(sym="NEWCO", **kw):
    kw.setdefault("drift", 0.004)
    kw.setdefault("noise", 0.006)
    return {"symbol": sym, "leader_sig": leaders.signals(frame(n=200, **kw))}


def test_a_young_company_is_on_none_of_the_three_lists_and_is_told_where_it_is():
    cands, sectors, snaps = market()
    cands.append(newcomer())
    sectors["NEWCO"], snaps["NEWCO"] = "Ind0", healthy()
    b = leaders.rank(cands, sectors=sectors, snapshot=snaps)["NEWCO"]
    assert b["young"] is True and b["listed_sessions"] == 200
    for key in leaders.ORDER:
        assert b["lists"][key]["rank"] is None
        assert b["lists"][key]["why_not"] == ("Listed under a year. This list needs twelve months of prices; "
                                              "younger companies are on emerging.")
        assert b["lists"][key]["breakdown"] == []
    assert b["facts"]["return_12m_pct"] is None and b["facts"]["return_6m_pct"] is not None
    assert any(w.startswith("Listed ") for w in b["lists"]["month"]["why"])


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
    thin = leaders.rank(universe() + [newcomer("THIN", turnover=5e7)])
    assert "THIN" not in thin


def test_a_young_company_is_not_on_the_results_list_even_if_it_reported():
    cands, results = reporters(n=12)
    cands.append(newcomer("NEWCO", jump=(1, 0.40)))
    results["NEWCO"] = filed(2)
    b = leaders.rank(cands, results=results)["NEWCO"]
    assert b["results"] is None and b["lists"]["results"]["rank"] is None


def test_a_young_company_is_never_served_on_the_three_lists(quiet):
    """The Ideas layer serves the engine's ranks, so a company listed under a
    year cannot reach the month, results or long-term list however strong."""
    cands, results = reporters(n=12)
    cands.append(newcomer("NEWCO", jump=(1, 0.08)))
    results["NEWCO"] = filed(2)
    sectors = industries(cands, 5)
    p = scan_payload(leaders.rank(cands, results=results, sectors=sectors,
                                  snapshot={c["symbol"]: healthy() for c in cands}))
    for key in leaders.ORDER:
        sel = ideas.select(p, horizon=key)
        assert "NEWCO" not in [r["symbol"] for r in sel["rows"]], key
        assert not any(r["young"] for r in sel["rows"])


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


# --- the setup lists: breakouts, technicals, quick trades, money flow, emerging ---

def _frame(closes, volumes=None):
    import pandas as pd
    c = np.asarray(closes, dtype=float)
    v = np.full(len(c), 1e6) if volumes is None else np.asarray(volumes, dtype=float)
    idx = pd.bdate_range("2024-01-01", periods=len(c))
    return pd.DataFrame({"High": c * 1.005, "Low": c * 0.995, "Close": c, "Volume": v}, index=idx)


def _base_then_break(broke=True):
    """260 sessions of climb, 40 flat inside a 4% range, then one session."""
    rng = np.random.default_rng(3)
    climb = np.linspace(60, 100, 259)
    flat = 100 + rng.uniform(-1.5, 1.5, 40)
    last = 106.0 if broke else 100.5
    vol = np.full(300, 1e6)
    vol[-1] = 3.5e6 if broke else 1e6
    return _frame(np.concatenate([climb, flat, [last]]), vol)


def test_a_close_above_a_tight_base_on_heavy_volume_is_a_breakout():
    t = leaders.technicals(_base_then_break(True))
    assert t["box"] and t["box"]["sessions_ago"] == 0 and t["box"]["holding"]
    assert t["box"]["width"] <= leaders.BOX_MAX_WIDTH and t["box"]["rel_volume"] >= leaders.BOX_MIN_VOLUME


def test_a_stock_still_inside_its_base_is_watched_not_picked():
    t = leaders.technicals(_base_then_break(False))
    assert not t["box"]
    assert t["base"] and t["base"]["width"] <= leaders.BOX_MAX_WIDTH and 0 <= t["base"]["to_top"] <= 0.04


def test_the_scorecard_counts_the_nine_conditions_it_names():
    t = leaders.technicals(_base_then_break(True))
    assert 0 <= t["scorecard"] <= 9 and len(t["scorecard_met"]) == t["scorecard"]
    assert set(t["scorecard_met"]) <= set(leaders.SCORECARD_LABELS) and len(leaders.SCORECARD_LABELS) == 9


# --- the setup lists as rebuilt in December 2026 (research/setups_lab.py --v2) ---

def _bars(closes, vols=None, last=None):
    """Daily bars with an open; `last` is (high, low, open) for the final bar."""
    c = np.asarray(closes, dtype=float)
    h, low, o = c * 1.005, c * 0.995, c.copy()
    v = np.full(len(c), 1e6) if vols is None else np.asarray(vols, dtype=float)
    if last:
        h[-1], low[-1], o[-1] = last
    idx = pd.bdate_range("2024-01-01", periods=len(c))
    return pd.DataFrame({"Open": o, "High": h, "Low": low, "Close": c, "Volume": v}, index=idx)


def _ratnaveer_like():
    """A climb, then a 50-session base about 23% wide whose last fortnight
    tightened on lighter volume, then a close above it on 2.5 times the
    volume near the day's high: the RATNAVEER launch of July 2026 in shape."""
    rng = np.random.default_rng(7)
    climb = np.linspace(60, 100, 230)
    wide = 90 + 9 * np.sin(np.linspace(0, 6 * np.pi, 35))
    tight = 96 + rng.uniform(-1.5, 1.5, 15)
    v = np.full(281, 1e6)
    v[-16:-1], v[-1] = 6e5, 2.5e6
    return _bars(np.concatenate([climb, wide, tight, [104.0]]), v, last=(104.4, 99.0, 99.5))


def _hfcl_like():
    """A fall, a recovery and a long sideways base with a quiet last month
    near its top, then a first 60-session high on 2.6 times the volume: the
    shape of HFCL's April 2026 turn."""
    rng = np.random.default_rng(11)
    base1 = 82 + 7 * np.sin(np.linspace(0, 4 * np.pi, 70))
    base1[-5] = 90.0
    c = np.concatenate([np.linspace(100, 60, 100), np.linspace(60, 80, 60), base1,
                        86 + rng.uniform(-2, 2, 50), [94.0]])
    v = np.full(len(c), 1e6)
    v[-1] = 2.6e6
    return _bars(c, v, last=(94.3, 88.0, 88.5))


def _setup_ctx(**over):
    ctx = {"sectors": {"AAA": "Alpha"},
           "flow_by": {"Alpha": {"sector": "Alpha", "rank": 2, "of": 10, "score": 80.0}},
           "flow_top": [], "flow_pick": {}, "flow_why": {}, "bench": {"ret_1m": 0.0, "ret_3m": 0.0},
           "fund": {}, "events": {}, "updown": {"AAA": 0.6}, "institutional": {}}
    ctx.update(over)
    return ctx


def _sig(df):
    g = leaders.signals(df)
    g["ret_1m"] = 0.05                    # ahead of the market in these cases unless a test says not
    return g


def test_a_tightening_base_broken_on_volume_is_a_vcp_launchpad():
    t = leaders.technicals(_ratnaveer_like())
    L = t["launch"][-1]
    assert L["sessions_ago"] == 0 and L["a"] and L["rel_volume"] >= leaders.LAUNCH_A_VOLUME
    # Wider than the old 18% box, which would never have counted it, but tightened at the end.
    assert leaders.BOX_MAX_WIDTH < L["a"]["width"] <= leaders.LAUNCH_A_WIDTH
    assert L["range_15_60"] <= leaders.LAUNCH_A_RANGE and L["clv"] >= leaders.LAUNCH_CLV
    g = _sig(_ratnaveer_like())
    score, why, order = leaders._setup("breakout", "AAA", g, {"leader": 0.6}, True, _setup_ctx())
    assert why is None and score > 0 and order > 0
    assert leaders._launch(g, g["tech"], {"leader": 0.6}, None, None)[1] == "VCP launchpad"


def test_a_breakout_already_stretched_is_not_bought():
    g = _sig(_ratnaveer_like())
    g["tech"] = dict(g["tech"], ext_50d_pct=21.0)
    _s, why, _o = leaders._setup("breakout", "AAA", g, {"leader": 0.6}, True, _setup_ctx())
    assert why and "above its 50-day average" in why
    g = _sig(_ratnaveer_like())
    g["ret_3m"] = 0.70
    _s, why, _o = leaders._setup("breakout", "AAA", g, {"leader": 0.6}, True, _setup_ctx())
    assert why and "three months" in why


def test_each_breakout_screen_refuses_in_words():
    base = _sig(_ratnaveer_like())
    cases = {
        "leader score": ({}, {"leader": 0.3}, {}),
        "outside the top": ({}, {"leader": 0.6},
                            {"flow_by": {"Alpha": {"sector": "Alpha", "rank": 9, "of": 10, "score": 20.0}}}),
        "did not beat": ({"ret_1m": -0.05}, {"leader": 0.6}, {}),
        "Profit fell": ({}, {"leader": 0.6}, {"fund": {"AAA": {"pat_yoy_pct": -30.0}}}),
        "results were sold": ({}, {"leader": 0.6},
                              {"events": {"AAA": {"reaction": -0.05, "move": -0.06, "market_move": -0.01}}}),
    }
    for text, (g_over, part, ctx_over) in cases.items():
        g = dict(base, **g_over)
        _s, why, _o = leaders._setup("breakout", "AAA", g, part, True, _setup_ctx(**ctx_over))
        assert why and text in why, (text, why)
    # A company with no quarter on file is never refused for it.
    assert leaders._setup("breakout", "AAA", base, {"leader": 0.6}, True, _setup_ctx(fund={}))[1] is None


def test_a_first_sixty_session_high_out_of_a_long_base_is_a_turnaround_even_for_a_laggard(monkeypatch):
    t = leaders.technicals(_hfcl_like())
    L = t["launch"][-1]
    assert L["b"] and L["b"]["base"] == 60 and L["b"]["width"] <= leaders.LAUNCH_B_WIDTH
    assert L["rel_volume"] >= leaders.LAUNCH_B_VOLUME and L["clv"] >= leaders.LAUNCH_B_CLV
    g = _sig(_hfcl_like())
    laggard = {"leader": 0.30}          # not yet in the top half of 12-month leaders
    # With pattern B switched on it is picked as a turnaround; A alone needs a leader.
    monkeypatch.setattr(leaders, "LAUNCH_PATTERNS", ("A", "B"))
    launch, pattern, why = leaders._launch(g, g["tech"], laggard, None, {"pat_yoy_pct": 25.0})
    assert launch and pattern == "Base turnaround" and why is None
    # A turnaround needs sales or profit growing where a quarter is on file.
    assert leaders._launch(g, g["tech"], laggard, None, {"pat_yoy_pct": -5.0, "revenue_yoy_pct": -2.0})[0] is None
    monkeypatch.setattr(leaders, "LAUNCH_PATTERNS", ("A",))
    launch, _p, why = leaders._launch(g, g["tech"], laggard, None, {"pat_yoy_pct": 25.0})
    assert launch is None and "leader score" in why


def test_the_shipped_breakout_list_is_the_pattern_the_lab_chose():
    with open(os.path.join(HERE, "..", "..", "research", "setups-lab-v2.json"), encoding="utf-8") as f:
        lab = json.load(f)
    taken = lab["taken"]["breakout"]
    assert taken["version"].startswith("new: A ") and leaders.LAUNCH_PATTERNS == ("A",)
    spec = leaders.LISTS["breakout"]
    assert (spec["hold_sessions"], spec["exit_pct"]) == (taken["hold"], taken["stop"])


def _pullback(**over):
    g = {"price": 102.0, "sma50": 98.0, "sma200": 90.0, "uptrend": True, "ret_1m": 0.02, "ret_3m": 0.08,
         "tech": {"ema20": 100.0, "rsi": 58.0, "ext_20d_pct": 2.0, "low3_vs_ema20": 1.005,
                  "closed_up": True, "sma200_rising": True}}
    for k, v in over.items():
        if k in g["tech"]:
            g["tech"][k] = v
        else:
            g[k] = v
    return leaders._setup("technical", "AAA", g, {"leader": over.pop("leader", 0.7)}, True, _setup_ctx())


def test_a_calm_pullback_to_the_20_day_in_a_rising_trend_is_a_technical_pick():
    score, why, order = _pullback()
    assert why is None and 0 < score <= 100 and order > 0


def test_the_technical_list_refuses_a_stretched_or_overbought_stock():
    cases = {"6% or less": dict(ext_20d_pct=9.0), "RSI is 74": dict(rsi=74.0),
             "not rising": dict(sma200_rising=False), "pulled back": dict(low3_vs_ema20=1.06),
             "close up": dict(closed_up=False), "Not in an uptrend": dict(uptrend=False),
             "under its 20-day": dict(ext_20d_pct=-0.5)}
    for text, over in cases.items():
        _s, why, _o = _pullback(**over)
        assert why and text in why, (text, why)


def _dip(**over):
    g = {"price": 97.0, "sma50": 98.0, "sma200": 85.0, "uptrend": True, "ret_5d": -0.05,
         "tech": {"rsi2": 6.0}}
    leader = over.pop("leader", 0.8)
    ev = over.pop("ev", None)
    for k, v in over.items():
        if k in g["tech"]:
            g["tech"][k] = v
        else:
            g[k] = v
    return leaders._setup("quick", "AAA", g, {"leader": leader}, True,
                          _setup_ctx(events={"AAA": ev} if ev else {}))


def test_a_swing_dip_is_a_leader_sold_hard_that_still_holds_its_50_day():
    assert _dip()[1] is None
    assert _dip(rsi2=40.0)[1] is None                       # a 5% week is enough on its own
    assert "Not sold off" in _dip(rsi2=40.0, ret_5d=-0.01)[1]
    assert "market leader" in _dip(leader=0.5)[1]
    assert "50-day average" in _dip(price=90.0)[1]
    assert "its results" in _dip(ev={"reaction": -0.06})[1]


def test_the_swing_dip_is_held_a_month_and_keeps_a_profit_after_costs():
    p = leaders.plan("quick", 200.0, dt.date(2026, 11, 9))
    assert p["sell_rule"] is None and p["hold_sessions"] == 21 and p["stop"] == 180.0
    with open(os.path.join(HERE, "..", "..", "research", "setups-lab-v2.json"), encoding="utf-8") as f:
        lab = json.load(f)
    old = lab["quick"]["old: rsi2 under 10, leader top 30% (shipped until now)"]["exits"]
    old = old["first close above the 5-day average, 7 sessions, close 7% under (old)"]
    new = lab["quick"]["new: leader swing dip"]["exits"]["21 sessions, close 10% under"]
    assert old["after_costs_pct"] < 0 < new["after_costs_pct"]
    assert new["by_half"]["2017-21"]["after_costs_pct"] > 0 and new["by_half"]["2022-26"]["after_costs_pct"] > 0


def _ranked_with_sectors():
    cands = universe(80)
    names = ["Alpha", "Beta", "Gamma", "Delta", "Epsilon"]
    sectors = {c["symbol"]: names[i % 5] for i, c in enumerate(cands)}
    return cands, sectors, leaders.rank(cands, sectors=sectors)


def test_every_block_carries_every_setup_list():
    _c, _s, blocks = _ranked_with_sectors()
    for b in blocks.values():
        assert set(leaders.ALL) <= set(b["lists"])
        for key in leaders.SETUPS:
            e = b["lists"][key]
            assert e["eligible"] or e["why_not"], key
            assert (e["rank"] is None) or e["eligible"]


def test_money_flow_picks_only_from_the_top_three_sectors():
    _c, sectors, blocks = _ranked_with_sectors()
    table = {b["sector_flow"]["sector"]: b["sector_flow"] for b in blocks.values() if b.get("sector_flow")}
    assert len(table) == 5 and sorted(r["rank"] for r in table.values()) == [1, 2, 3, 4, 5]
    assert leaders.FLOW_SECTORS == 3 and leaders.FLOW_PER_SECTOR == 5
    top = {s for s, r in table.items() if r["rank"] <= leaders.FLOW_SECTORS}
    picked = [s for s, b in blocks.items() if b["lists"]["flow"]["rank"]]
    assert picked, "no money-flow pick from a ranked universe"
    assert all(sectors[s] in top for s in picked)
    per = {}
    for s in picked:
        per[sectors[s]] = per.get(sectors[s], 0) + 1
    assert max(per.values()) <= leaders.FLOW_PER_SECTOR
    # Each pick beat the market (here the median stock: no index was given) over one month and three.
    med1 = float(np.median([b["facts"]["return_1m_pct"] for b in blocks.values() if not b["young"]]))
    assert all(blocks[s]["facts"]["return_1m_pct"] > med1 - 0.1 for s in picked)


def test_sectors_are_ordered_on_rotation_and_the_short_list_keeps_its_own_score():
    _c, _s, blocks = _ranked_with_sectors()
    rows = sorted({b["sector_flow"]["sector"]: b["sector_flow"] for b in blocks.values()
                   if b.get("sector_flow")}.values(), key=lambda r: r["rank"])
    assert [r["rank"] for r in rows] == list(range(1, 6))
    assert all(rows[i]["score"] >= rows[i + 1]["score"] for i in range(4))
    assert sorted(r["classic_rank"] for r in rows) == [1, 2, 3, 4, 5]
    assert all("month3_pct" in r and "classic_score" in r for r in rows)
    assert sum(leaders.ROTATION_WEIGHTS.values()) == pytest.approx(1.0)


def test_money_flow_anti_chasing_is_measured_and_off(monkeypatch):
    """The lab ran money flow with and without the anti-chasing screen and the
    rule took the version without it. Switched on, it refuses a stretched name."""
    assert leaders.FLOW_ANTI_CHASE is False
    cands, sectors, before = _ranked_with_sectors()
    monkeypatch.setattr(leaders, "FLOW_EXT50", -100.0)       # every stock is "stretched"
    monkeypatch.setattr(leaders, "FLOW_ANTI_CHASE", True)
    after = leaders.rank(cands, sectors=sectors)
    assert not any(b["lists"]["flow"]["rank"] for b in after.values())
    assert any("50-day average" in (b["lists"]["flow"]["why_not"] or "") for b in after.values())


def test_institutional_buying_reorders_the_money_flow_names_and_chooses_none():
    cands, sectors, plain = _ranked_with_sectors()
    picked = {s for s, b in plain.items() if b["lists"]["flow"]["rank"]}
    last = max(picked, key=lambda s: plain[s]["lists"]["flow"]["rank"])
    inst = {last: {"accumulation": 100.0}}
    boosted = leaders.rank(cands, sectors=sectors, institutional=inst)
    assert {s for s, b in boosted.items() if b["lists"]["flow"]["rank"]} == picked
    assert boosted[last]["lists"]["flow"]["rank"] <= plain[last]["lists"]["flow"]["rank"]


def test_money_flow_is_empty_without_a_sector_list_and_says_why():
    blocks = leaders.rank(universe(60))
    assert not any(b["lists"]["flow"]["rank"] for b in blocks.values())
    assert all("sector" in b["lists"]["flow"]["why_not"].lower() for b in blocks.values())


def test_the_benchmark_given_is_the_one_measured_against():
    cands, sectors, _b = _ranked_with_sectors()
    high = leaders.rank(cands, sectors=sectors, benchmark={"ret_1m": 0.5, "ret_3m": 0.5})
    assert not any(b["lists"]["flow"]["rank"] for b in high.values())
    assert any("beaten the market" in (b["lists"]["flow"]["why_not"] or "") for b in high.values())


def test_emerging_is_for_companies_listed_six_to_eighteen_months():
    cands = universe(60)
    for i, c in enumerate(cands):
        c["listed_sessions"] = 300 if i % 2 else 1e4      # half listed ~14 months, half long ago
    blocks = leaders.rank(cands)
    for i, c in enumerate(cands):
        e = blocks[c["symbol"]]["lists"]["emerging"]
        if not i % 2:
            assert not e["eligible"] and "Listed more than 18 months" in e["why_not"]
        elif e["eligible"]:
            b = blocks[c["symbol"]]
            assert b["technicals"]["sma50_rising"] and b["parts"]["leader"] >= leaders.EMERGING_LEADER * 100 - 1
    # Without a listing age the frame's own length is read (a 320-session frame: about fifteen months).
    assert leaders.EMERGING_MIN_SESSIONS <= 320 <= leaders.EMERGING_MAX_SESSIONS


def test_emerging_refuses_a_loss_maker_and_falling_sales():
    g = _sig(_ratnaveer_like())
    g["near_high"] = 0.97
    g["tech"] = dict(g["tech"], sma50_rising=True)
    ctx = _setup_ctx(bench={"ret_1m": -0.1, "ret_3m": -0.1})
    assert "not rising" in leaders._emerging("AAA", dict(g, tech=dict(g["tech"], sma50_rising=False)),
                                             {"leader": 0.8}, ctx, 300)[1]
    assert leaders._emerging("AAA", g, {"leader": 0.8}, ctx, 300)[1] is None
    assert "loss" in leaders._emerging("AAA", g, {"leader": 0.8},
                                       _setup_ctx(bench=ctx["bench"], fund={"AAA": {"pat_cr": -3.0}}), 300)[1]
    assert "Sales fell" in leaders._emerging("AAA", g, {"leader": 0.8},
                                             _setup_ctx(bench=ctx["bench"],
                                                        fund={"AAA": {"revenue_yoy_pct": -4.0}}), 300)[1]
    assert "Listed more than" in leaders._emerging("AAA", g, {"leader": 0.8}, ctx, 500)[1]


def test_the_rebuilt_plans_hold_for_the_move_and_carry_no_target():
    for key, (hold, stop) in {"breakout": (63, 12.0), "technical": (63, 12.0), "quick": (21, 10.0),
                              "flow": (63, 15.0), "emerging": (90, 15.0)}.items():
        p = leaders.plan(key, 100.0, dt.date(2026, 12, 1))
        assert (p["hold_sessions"], p["risk_pct"]) == (hold, stop), key
        assert p["aim"] is None and p["t1"] is None, key
    e = leaders.plan("emerging", 100.0)
    assert e["sell_rule"] == "sma50" and "50-day average" in e["note"] and e["stop"] == 85.0
    assert leaders.plan("breakout", 100.0)["stop"] == 88.0
    # The short-term list is not one of them, and is unchanged.
    assert leaders.plan("short", 100.0)["aim"] == 108.0


def test_each_setup_list_has_a_replayed_record_with_its_big_winners():
    with open(os.path.join(HERE, "..", "..", "research", "ideas-study.json"), encoding="utf-8") as f:
        study = json.load(f)
    for key in leaders.SETUPS:
        rec = study["lists"][key]
        assert rec["kind"] == "setup" and rec["picks"] > 500 and rec["what"]
        assert rec["by_half"]["2017-21"] and rec["by_half"]["2022-26"]
        assert rec["avg_after_costs_pct"] == round(rec["avg_pct"] - study["round_trip_cost_pct"], 2)
        assert "big_winner_pct" in rec and "big_winner_pct" in rec["by_half"]["2022-26"], key
    for key in ("breakout", "technical", "quick", "flow", "emerging"):
        assert study["lists"][key]["version"] == "2026-12", key
    assert study["lists"]["emerging"]["avg_sessions_held"] < leaders.LISTS["emerging"]["hold_sessions"]


def test_the_breakout_watch_lists_unbroken_bases_of_either_pattern():
    def block(score, watch, sector_flow=None, **t):
        return {"young": False, "score": score, "sector": "Alpha", "facts": {"turnover_cr": 50, "return_3m_pct": 10},
                "sector_flow": sector_flow, "technicals": dict({"launch": [], "ext_50d_pct": 8.0, "watch": watch}, **t)}
    vcp = {"pattern": "VCP launchpad", "base": 40, "top": 100, "low": 80, "width_pct": 25.0, "to_top_pct": 1.2}
    turn = {"pattern": "Base turnaround", "base": 60, "top": 100, "low": 76, "width_pct": 31.0, "to_top_pct": 2.0}
    blocks = {"AAA": block(60.0, vcp),
              "BBB": block(20.0, turn),                       # a laggard: a turnaround needs no leader score
              "CCC": block(20.0, vcp),                        # a launchpad does
              "DDD": block(80.0, vcp, ext_50d_pct=25.0),      # stretched
              "EEE": block(80.0, vcp, launch=[{"a": {}}]),    # already broke out
              "FFF": block(80.0, None)}
    got = leaders.breakout_watch(blocks)
    assert [r["symbol"] for r in got] == ["AAA", "BBB"]
    assert [r["pattern"] for r in got] == ["VCP launchpad", "Base turnaround"]


def test_the_short_lists_watch_is_its_own_tight_forty_session_base():
    blocks = {"AAA": {"young": False, "score": 80.0, "sector": "Alpha", "facts": {"turnover_cr": 50},
                      "technicals": {"box": None, "above_200d": True, "rel_volume_5": 1.1,
                                     "base": {"top": 100, "low": 92, "width_pct": 8.7, "to_top_pct": 1.2}}},
              "BBB": {"young": False, "score": 80.0, "facts": {},
                      "technicals": {"box": None, "above_200d": True,
                                     "base": {"top": 100, "low": 70, "width_pct": 42.0, "to_top_pct": 1.0}}},
              "CCC": {"young": False, "score": 30.0, "facts": {},
                      "technicals": {"box": None, "above_200d": True,
                                     "base": {"top": 100, "low": 95, "width_pct": 5.0, "to_top_pct": 1.0}}}}
    assert [r["symbol"] for r in leaders.short_watch(blocks)] == ["AAA"]


def test_an_industry_index_at_a_fresh_high_is_a_sector_breakout():
    up = [[0.002] * leaders.SECTOR_PATH] * leaders.FLOW_MIN_MEMBERS
    assert leaders._sector_breakout(up) == {"breakout": True, "near_high": True, "from_high_pct": 0.0}
    fell = [[0.002] * 60 + [-0.008] * 10] * leaders.FLOW_MIN_MEMBERS
    got = leaders._sector_breakout(fell)
    assert got["breakout"] is False and got["near_high"] is False and got["from_high_pct"] > 3
    # Too few stocks to make an index is unknown, not a no.
    assert leaders._sector_breakout(up[:3])["near_high"] is None


def test_every_sector_row_says_whether_its_industry_is_breaking_out():
    _c, _s, blocks = _ranked_with_sectors()
    rows = [b["sector_flow"] for b in blocks.values() if b.get("sector_flow")]
    assert rows and all({"breakout", "near_high", "from_high_pct"} <= set(r) for r in rows)
    assert all(isinstance(r["near_high"], bool) for r in rows)


def test_a_breakout_in_an_industry_far_from_its_high_is_refused():
    g = _sig(_ratnaveer_like())
    far = {"Alpha": {"sector": "Alpha", "rank": 2, "of": 10, "score": 80.0,
                     "breakout": False, "near_high": False, "from_high_pct": 8.2}}
    _s, why, _o = leaders._setup("breakout", "AAA", g, {"leader": 0.6}, True, _setup_ctx(flow_by=far))
    assert leaders.BREAKOUT_SECTOR_NEAR_HIGH and why and "8.2% under its 60-session high" in why
    near = {"Alpha": dict(far["Alpha"], near_high=True, from_high_pct=1.0)}
    assert leaders._setup("breakout", "AAA", g, {"leader": 0.6}, True, _setup_ctx(flow_by=near))[1] is None
    # No industry, or one too small to index: passes, as every sector screen does.
    unknown = {"Alpha": dict(far["Alpha"], near_high=None)}
    assert leaders._setup("breakout", "AAA", g, {"leader": 0.6}, True, _setup_ctx(flow_by=unknown))[1] is None


def test_the_sector_screen_is_the_one_the_lab_adopted():
    with open(os.path.join(HERE, "..", "..", "research", "setups-lab-sector.json"), encoding="utf-8") as f:
        lab = json.load(f)["lists"]
    assert lab["breakout A"]["adopted"] == "gate: near_high"
    assert lab["technical (pullback)"]["adopted"] is None


def test_technicals_still_read_only_three_hundred_bars():
    long = _bars(np.linspace(50, 150, 900))
    assert leaders.technicals(long) == leaders.technicals(long.iloc[-300:])


# --- the short-term list: a breakout, passed through five screens -----------------

def _short_case(**over):
    g = {"price": 110.0, "sma200": 90.0,
         "tech": {"scorecard": 8, "box": {"sessions_ago": 1, "top": 105.0, "low": 95.0, "width": 0.105,
                                           "rel_volume": 3.0, "close": 108.0, "holding": True}}}
    part = {"leader": 0.8}
    flow = {"Alpha": {"sector": "Alpha", "score": 80.0, "rank": 2, "of": 18}}
    kw = dict(pat_yoy=20.0, growth=0.7, ev=None)
    for k, v in over.items():
        if k in kw:
            kw[k] = v
        elif k == "leader":
            part["leader"] = v
        elif k == "sector_score":
            flow["Alpha"]["score"] = v
        elif k in ("scorecard",):
            g["tech"][k] = v
        elif k in ("holding", "rel_volume", "width"):
            g["tech"]["box"][k] = v
        elif k == "box":
            g["tech"]["box"] = v
        elif k == "base":
            g["tech"]["base"] = v
        else:
            g[k] = v
    return leaders._short("AAA", g, part, {"AAA": "Alpha"}, flow, kw["pat_yoy"], kw["growth"], kw["ev"])


def test_a_breakout_that_passes_every_screen_is_a_short_term_pick():
    score, why, order = _short_case()
    assert why is None and 0 < score <= 100 and order == score


def test_each_screen_of_the_short_term_list_refuses_in_words():
    cases = {
        "200-day": dict(sma200=120.0),
        "bottom half of liquid": dict(leader=0.3),
        "chart conditions": dict(scorecard=4),
        "bottom half": dict(sector_score=30.0),
        "Profit fell": dict(pat_yoy=-12.0),
        "closed back under": dict(holding=False),
        "usual volume": dict(rel_volume=1.2),
        "wide": dict(width=0.30),
        "results were sold": dict(ev={"reaction": -0.05, "move": -0.06, "market_move": -0.01}),
    }
    for text, over in cases.items():
        _s, why, _o = _short_case(**over)
        assert why and text in why, (text, why)


def test_a_company_with_no_quarter_on_file_is_not_refused_for_it():
    assert _short_case(pat_yoy=None, growth=None)[1] is None


def test_a_stock_on_the_verge_is_named_as_such_and_not_picked():
    _s, why, _o = _short_case(box=None, base={"top": 105.0, "low": 95.0, "width": 0.105, "to_top": 0.012})
    assert why.startswith("On the verge") and "waits for the breakout" in why
    assert "No breakout" in _short_case(box=None, base=None)[1]


def test_stronger_industry_and_faster_growth_rank_a_pick_higher():
    assert _short_case(sector_score=95.0)[0] > _short_case(sector_score=55.0)[0]
    assert _short_case(growth=0.9)[0] > _short_case(growth=0.2)[0]


def test_the_page_shows_two_lists_and_short_is_its_own():
    assert leaders.PRIMARY == ("short", "long")
    assert leaders.resolve("short") == "short" and leaders.resolve("medium") == "long"
    assert leaders.plan("short", 100.0)["stop"] == 92.0


def test_the_short_term_record_is_the_engines_and_is_read_from_the_study():
    with open(os.path.join(HERE, "..", "..", "research", "ideas-study.json"), encoding="utf-8") as f:
        rec = json.load(f)["lists"]["short"]
    assert rec["kind"] == "setup" and rec["picks"] > 500 and rec["bias"]
    assert rec["hold_sessions"] == 21 and rec["exit_pct"] == 8.0
    # Led the average stock in both halves: the reason it is the list the page leads with.
    assert all(h["excess_pct"] > 0 for h in rec["vs_average_stock"]["by_half"].values())


# --- the three fundamental lists (December 2026) ----------------------------------
#
# Swing / This month, After results and Long-term compounders read each
# company's filings (fund_snapshot.py) beside its chart. What is pinned: they
# read the snapshot and nothing the setup lists read; a figure a company has
# not filed is the middle of the field and never a failed test; each refusal
# is said in words, in the order the page explains; every threshold and
# weight is the recipe dictionary's, as the lab replays it.

WORDS_NEVER_USED = re.compile(r"\b(buy|buys|buying|sell|sells|selling|should|recommend\w*)\b", re.I)


def member(i, **kw):
    """Stock S{i} of universe(), drawn again with something changed."""
    base = dict(drift=0.0004 + 0.00004 * i, noise=0.006 + 0.0003 * (i % 9), seed=i)
    base.update(kw)
    return cand(f"S{i:02d}", **base)


def ranked(blocks, key):
    """A list's symbols in the order it ranked them."""
    return [s for _r, s in sorted((b["lists"][key]["rank"], s) for s, b in blocks.items()
                                  if b["lists"][key]["rank"])]


def first_on(blocks, key):
    return ranked(blocks, key)[0]


def test_the_setup_lists_never_read_the_snapshot():
    """The six setup lists keep reading `fundamentals` exactly as before: a
    snapshot passed or not, good or dreadful, moves none of their ranks."""
    cands, sectors, snaps = market(80, 5)
    fundamentals = {c["symbol"]: {"pat_yoy_pct": 12.0 - i % 30, "revenue_yoy_pct": 5.0, "pat_cr": 10.0}
                    for i, c in enumerate(cands)}
    dreadful = {s: healthy(pat_cr=-50.0, pat_yoy_pct=-90.0, revenue_yoy_pct=-40.0, pledge_pct=80.0,
                           eps_ttm=-5.0, roce_pct=1.0) for s in snaps}
    runs = [leaders.rank(cands, sectors=sectors, fundamentals=fundamentals, snapshot=snap)
            for snap in (None, snaps, dreadful, {s: {} for s in snaps})]
    for key in leaders.SETUPS:
        for sym in runs[0]:
            want = (runs[0][sym]["lists"][key]["rank"], runs[0][sym]["lists"][key]["score"])
            assert all((r[sym]["lists"][key]["rank"], r[sym]["lists"][key]["score"]) == want for r in runs[1:]), \
                (key, sym)
    # And the other way round: the three lists never read `fundamentals`.
    a = leaders.rank(cands, sectors=sectors, snapshot=snaps)
    b = leaders.rank(cands, sectors=sectors, fundamentals=fundamentals, snapshot=snaps)
    for key in leaders.ORDER:
        assert ranked(a, key) == ranked(b, key), key


def test_a_company_with_nothing_on_file_is_the_middle_of_the_field_and_nothing_raises():
    cands, sectors, snaps = market(60, 5)
    syms = [c["symbol"] for c in cands]
    odd = {syms[0]: {}, syms[1]: {"pat_cr": None}, syms[2]: None,
           syms[3]: {"revenue_yoy_pct": "n/a", "pe": float("nan"), "pledge_pct": "x", "is_financial": None,
                     "roce_pct": float("inf"), "f_score": "seven", "delivery_spike": "yes"},
           syms[4]: {k: None for k in healthy()}}
    blocks = leaders.rank(cands, sectors=sectors, snapshot=odd)
    assert set(blocks) == set(syms)
    for s in syms[:5]:
        for key, part in (("month", "fundmom"), ("month", "catalyst"), ("long", "quality"),
                          ("long", "compounding"), ("long", "governance"), ("long", "valuation")):
            row = next(r for r in blocks[s]["lists"][key]["breakdown"] if r["factor"] == part)
            assert row["value"] == 50.0, (s, key, part)
        # A missing figure skips its own check and fails nothing.
        for key in ("month", "long"):
            why = blocks[s]["lists"][key]["why_not"] or ""
            assert not any(t in why for t in ("loss", "Profit fell", "pledged", "F-score", "Return on",
                                              "Debt", "Cash from", "P/E", "Lost money")), (s, why)
    assert blocks[syms[0]]["fundamentals"] is None and blocks[syms[2]]["fundamentals"] is None
    # With no snapshot at all, the same.
    bare = leaders.rank(cands, sectors=sectors)
    assert ranked(bare, "long") and all(b["fundamentals"] is None for b in bare.values())


def test_month_refuses_a_falling_or_loss_making_quarter_and_a_heavy_pledge_in_words():
    cands, sectors, snaps = market()
    base = leaders.rank(cands, sectors=sectors, snapshot=snaps)
    x = first_on(base, "month")
    cases = {"Made a loss in its last quarter.": dict(pat_cr=-4.0, pat_yoy_pct=None),
             "Profit fell 31% on a year ago in its last quarter.": dict(pat_yoy_pct=-31.0),
             "Profit fell 0.4% on a year ago in its last quarter.": dict(pat_yoy_pct=-0.4),
             "Promoters have pledged 25% of the company.": dict(pledge_pct=25.0),
             "Promoters have pledged 10.5% of the company.": dict(pledge_pct=10.5)}
    for text, over in cases.items():
        e = leaders.rank(cands, sectors=sectors, snapshot=dict(snaps, **{x: healthy(**over)}))[x]["lists"]["month"]
        assert e["rank"] is None and e["why_not"] == text, (text, e["why_not"])
    # A pledge at the limit is not over it.
    e = leaders.rank(cands, sectors=sectors, snapshot=dict(snaps, **{x: healthy(pledge_pct=10.0)}))[x]
    assert e["lists"]["month"]["eligible"]


def test_month_refuses_an_industry_money_is_leaving_or_that_cannot_be_ranked():
    cands, sectors, snaps = market()
    blocks = leaders.rank(cands, sectors=sectors, snapshot=snaps)
    leaders_ = [s for s, b in blocks.items()
                if b["uptrend"] and b["calm"] and b["parts"]["leader"] >= leaders.MONTH["leader_floor"] * 100 + 1]
    weak = [s for s in leaders_ if blocks[s]["sector_flow"]["score"] < leaders.MONTH["sector_floor"]]
    strong = [s for s in leaders_ if blocks[s]["sector_flow"]["score"] >= leaders.MONTH["sector_floor"]]
    assert weak and strong
    for s in weak:
        row = blocks[s]["sector_flow"]
        assert blocks[s]["lists"]["month"]["why_not"] == \
            f"Its industry, {row['sector']}, ranks {row['rank']} of {row['of']} on money flow: the bottom half."
    assert all("money flow" not in (blocks[s]["lists"]["month"]["why_not"] or "") for s in strong)
    x = strong[0]
    unknown = {k: v for k, v in sectors.items() if k != x}
    e = leaders.rank(cands, sectors=unknown, snapshot=snaps)[x]["lists"]["month"]
    assert e["why_not"] == "Its industry could not be ranked on money flow."


def test_month_refuses_a_company_whose_results_the_market_sold_this_month():
    """A result priced in the last 21 sessions that fell 2% or more against
    the average stock: the month list waits, though the results list (ten
    sessions) has long forgotten it."""
    cands, sectors, snaps = market()
    # A calm leader, so one bad day does not make it volatile.
    x = next(s for s in ranked(leaders.rank(cands, sectors=sectors, snapshot=snaps), "month")
             if int(s[1:]) % 9 <= 2)
    i = int(x[1:])
    cands = [c for c in cands if c["symbol"] != x] + [member(i, jump=(15, -0.03))]
    clean = leaders.rank(cands, sectors=sectors, snapshot=snaps)[x]
    assert clean["lists"]["month"]["eligible"], "the fall alone is a pullback, not a refusal"
    sold = leaders.rank(cands, sectors=sectors, snapshot=snaps, results={x: filed(16)})[x]
    assert sold["results"] is None, "fifteen sessions ago is outside the results list's ten"
    assert sold["lists"]["month"]["why_not"].startswith("Its results were sold: -")


def test_month_checks_its_gates_in_the_order_the_page_explains():
    cands, sectors, snaps = market()
    blocks = leaders.rank(cands, sectors=sectors, snapshot=snaps)
    x = first_on(blocks, "month")
    bad = healthy(pat_cr=-1.0, pledge_pct=40.0)
    got = leaders.rank(cands, sectors=sectors, snapshot=dict(snaps, **{x: bad}))[x]["lists"]["month"]
    assert got["why_not"] == "Made a loss in its last quarter.", "the profit guard comes before the pledge"
    follower = next(s for s, b in blocks.items() if b["uptrend"] and b["calm"]
                    and b["parts"]["leader"] < 60 and b["sector_flow"]["score"] < 50)
    got = leaders.rank(cands, sectors=sectors, snapshot=dict(snaps, **{follower: bad}))[follower]
    assert got["lists"]["month"]["why_not"].startswith("Not a market leader"), \
        "the leader floor comes before the industry and the filings"


def test_a_catalyst_and_a_growing_quarter_lift_a_month_pick():
    cands, sectors, snaps = market()
    x = first_on(leaders.rank(cands, sectors=sectors, snapshot=snaps), "month")
    def score(**over):
        return leaders.rank(cands, sectors=sectors, snapshot=dict(snaps, **{x: healthy(**over)}))[x]["lists"]["month"]
    plain = score()
    for over in (dict(delivery_spike=True), dict(order_win_pct_mcap=3.0)):
        lifted = score(**over)
        assert lifted["score"] == pytest.approx(plain["score"] + 5.0, abs=0.05)   # 10% weight, 0.5 to 1.0
        assert any(("deliveries" in w.lower()) or ("order worth" in w) for w in lifted["why"])
    assert score(order_win_pct_mcap=1.5)["score"] == plain["score"], "an order under 2% is not a catalyst"
    assert score(revenue_yoy_pct=60.0, opm_yoy_chg=6.0)["score"] > plain["score"] > \
        score(revenue_yoy_pct=-5.0, opm_yoy_chg=-4.0)["score"]


def test_results_refuses_results_that_were_not_real_growth_in_words():
    cands, results = reporters(n=20, step=0.007)
    snaps = reported(results)
    cases = {
        "S00": (dict(other_income_share_pct=60.0),
                "Other income was 60% of profit before tax: not the business's own earnings."),
        "S01": (dict(exceptional_cr=40.0, pbt_cr=80.0), "An exceptional gain made up 50% of profit before tax."),
        "S02": (dict(revenue_yoy_pct=5.0), "Sales grew 5% on a year ago; the list needs 8%."),
        "S03": (dict(revenue_yoy_pct=-6.0), "Sales fell 6% on a year ago; the list needs 8% growth."),
        "S04": (dict(pat_cr=-3.0, pat_yoy_pct=None), "Made a loss in the quarter it reported."),
        "S05": (dict(pat_yoy_pct=-4.0), "Profit did not grow on a year ago."),
        "S06": (dict(ebitda_yoy_pct=-2.0), "Operating profit did not grow."),
        "S07": (dict(core_ebitda_cr=-5.0), "Operating profit did not grow."),
        "S08": (dict(cfo_cr=-10.0), "Its last full year's operations used cash."),
        "S09": (dict(pat_cr=None), "The figures it reported are not in the fundamentals tables yet."),
    }
    for s, (over, _text) in cases.items():
        snaps[s] = healthy(**over)
    # A lender's other income and cash flow are its business: no refusal.
    snaps["S10"] = healthy(is_financial=True, other_income_share_pct=60.0, cfo_cr=-500.0, core_ebitda_cr=None)
    blocks = leaders.rank(cands, results=results, snapshot=snaps)
    for s, (_over, text) in cases.items():
        assert blocks[s]["lists"]["results"]["why_not"] == text, (s, blocks[s]["lists"]["results"]["why_not"])
    assert blocks["S10"]["lists"]["results"]["eligible"]
    assert len(ranked(blocks, "results")) == 10


def test_results_ranks_a_move_on_heavy_volume_and_faster_growth_above_a_bigger_move_on_neither():
    cands, results = reporters(n=12, step=0.008)
    cands += [cand("LOUD", jump=(1, 0.06), volume_on=(1, 4.0), seed=51),
              cand("QUIET", jump=(1, 0.06), volume_on=(1, 1.0), seed=52),
              cand("SPIKE", jump=(1, 0.08), volume_on=(1, 1.0), seed=53)]
    results.update(LOUD=filed(2), QUIET=filed(2), SPIKE=filed(2))
    snaps = reported(results)
    snaps["LOUD"] = healthy(revenue_yoy_pct=35.0, prev_revenue_yoy_pct=22.0, opm_yoy_chg=4.0)
    snaps["QUIET"] = snaps["SPIKE"] = healthy(revenue_yoy_pct=9.0, prev_revenue_yoy_pct=14.0, opm_yoy_chg=-0.5)
    blocks = leaders.rank(cands, results=results, snapshot=snaps)
    rank = {s: blocks[s]["lists"]["results"]["rank"] for s in ("LOUD", "QUIET", "SPIKE")}
    assert rank["LOUD"] < rank["QUIET"] and rank["LOUD"] < rank["SPIKE"]
    parts = {r["factor"]: r for r in blocks["LOUD"]["lists"]["results"]["breakdown"]}
    assert parts["volume"]["value"] == 100.0 and parts["growth"]["value"] == 100.0
    assert "sales growing faster than the quarter before" in parts["growth"]["detail"]
    assert any(w.startswith("Volume ") and w.endswith("usual") for w in blocks["LOUD"]["lists"]["results"]["why"])


def test_a_fresh_result_is_not_judged_on_the_quarter_before_it():
    """The fundamentals tables read a filing a few hours to a day after the
    exchange does. A result whose quarter is not in them yet is not judged on
    the previous quarter's numbers."""
    cands, results = reporters(n=12)
    snaps = reported(results)
    results["S11"] = {"filed_at": f"{DAYS[-3]} 18:30:00", "quarter": "Q2 FY27"}
    snaps["S11"] = healthy(filed_at="2026-08-10 17:00:00", quarter="Q1 FY27")
    snaps["S10"] = healthy(filed_at=f"{DAYS[-3]} 18:35:00", quarter="Q2 FY27", revenue_yoy_pct=3.0)
    blocks = leaders.rank(cands, results=results, snapshot=snaps)
    assert blocks["S11"]["lists"]["results"]["why_not"] == \
        "The figures it reported are not in the fundamentals tables yet."
    assert blocks["S10"]["lists"]["results"]["why_not"].startswith("Sales grew 3%"), \
        "a table row filed with the result is the result"


def test_fewer_than_eight_companies_passing_every_test_is_no_list():
    cands, results = reporters(n=12)
    snaps = reported(results)
    for s in list(results)[:5]:
        snaps[s] = healthy(other_income_share_pct=70.0)
    blocks = leaders.rank(cands, results=results, snapshot=snaps)
    assert not ranked(blocks, "results")
    passed = [s for s in results if s not in list(results)[:5]]
    assert all(blocks[s]["lists"]["results"]["why_not"] ==
               "Fewer than 8 companies passed every test this results season." for s in passed)
    assert blocks["S00"]["results"]["qualified"] == 7 and blocks["S00"]["results"]["reported"] == 12


def _long_market():
    """A market where the strongest climbers carry the worst balance sheets,
    middling climbers are compounders, and five lenders file no ROCE."""
    cands, sectors, snaps = market(120, 10)
    compounders = [f"S{i:02d}" for i in range(60, 70)]
    mediocre = [f"S{i:02d}" for i in range(100, 110)]
    for s in compounders:
        snaps[s] = healthy(roce_pct=40.0, cfo_to_pat=1.3, fcf_pos_years_3y=3, debt_equity_x=0.0, pledge_pct=0.0,
                           promoter_chg_4q=1.0, fii_dii_chg_1q=1.0, rev_cagr_3y=25.0, pat_cagr_3y=28.0,
                           revenue_ttm_yoy_pct=24.0, pat_ttm_yoy_pct=27.0, opm_trend_2y=2.0, peg=0.9,
                           ev_ebitda=12.0, pe=25.0)
    for s in mediocre:
        snaps[s] = healthy(roce_pct=15.0, cfo_to_pat=0.75, fcf_pos_years_3y=1, debt_equity_x=0.9, pledge_pct=4.5,
                           promoter_chg_4q=-1.0, fii_dii_chg_1q=-1.0, rev_cagr_3y=6.0, pat_cagr_3y=5.0,
                           revenue_ttm_yoy_pct=5.0, pat_ttm_yoy_pct=4.0, opm_trend_2y=-1.0, peg=3.5,
                           ev_ebitda=35.0, pe=60.0)
    snaps["S119"] = healthy(debt_equity_x=2.5)
    snaps["S118"] = healthy(cfo_cr=-40.0, cfo_to_pat=-0.6)
    snaps["S117"] = healthy(pe=150.0, peg=5.0, pat_cagr_3y=30.0)
    snaps["S116"] = healthy(pe=120.0, peg=1.2, pat_cagr_3y=45.0)
    # Five calm lenders, in NSE's own industry for them.
    for s, roe in zip(LENDERS, (20.0, 9.0, 14.0, 16.0, 18.0)):
        sectors[s] = "Financial Services"
        snaps[s] = healthy(is_financial=True, roce_pct=None, roe_pct=roe, debt_equity_x=9.0,
                           cfo_cr=-800.0, cfo_to_pat=-3.0, fcf_pos_years_3y=0, f_score=None, ev_ebitda=None)
    return cands, sectors, snaps, compounders, mediocre


LENDERS = ("S45", "S46", "S47", "S54", "S55")


def test_long_ranks_cash_backed_compounders_above_debt_cash_burn_and_bubbles():
    cands, sectors, snaps, compounders, mediocre = _long_market()
    blocks = leaders.rank(cands, sectors=sectors, snapshot=snaps)
    why = {s: blocks[s]["lists"]["long"]["why_not"] for s in ("S119", "S118", "S117", "S116")}
    assert why["S119"] == "Debt is 2.5× equity: the list allows 1×."
    assert why["S118"] == "Operations used cash last year."
    assert why["S117"] == "P/E of 150: priced past the list's ceiling of 90."
    assert why["S116"] is None, "a P/E over 90 on a PEG of 1.2 and 45% growth a year is not priced out"
    # The mediocre ten climbed harder (their drift is higher), and every one
    # of them scores under every compounder; none reaches the list's top 15.
    good = [blocks[s]["lists"]["long"]["score"] for s in compounders if blocks[s]["lists"]["long"]["eligible"]]
    middling = [blocks[s]["lists"]["long"]["score"] for s in mediocre]
    assert len(good) >= 6 and min(good) > max(middling)
    first = set(ranked(blocks, "long")[:leaders.LIST_SIZE])
    assert not first & set(mediocre) and len(first & set(compounders)) >= 6
    year = lambda group: np.median([blocks[s]["facts"]["return_12m_pct"] for s in group])
    assert year(mediocre) > year(compounders)
    best = min(compounders, key=lambda s: blocks[s]["lists"]["long"]["rank"] or 999)
    assert blocks[best]["lists"]["long"]["why"][:3] == ["ROCE 40%, cash flow 1.3× profit",
                                                        "Sales +25% a year for 3 years", "No shares pledged"]


def test_long_judges_a_bank_on_its_return_on_equity():
    """A lender's debt is its stock in trade and its cash flow follows its
    lending: debt nine times equity and cash used by operations do not
    count against it. Its return on equity does."""
    cands, sectors, snaps, _c, _m = _long_market()
    blocks = leaders.rank(cands, sectors=sectors, snapshot=snaps)
    best, weak, *others = LENDERS
    assert blocks[weak]["lists"]["long"]["why_not"] == "Return on equity 9%: a lender needs 13%."
    for s in [best] + others:
        assert blocks[s]["lists"]["long"]["eligible"], (s, blocks[s]["lists"]["long"]["why_not"])
    quality = {s: next(r for r in blocks[s]["lists"]["long"]["breakdown"] if r["factor"] == "quality")
               for s in LENDERS}
    # Ranked on return on equity among the five lenders: 20% is the best of them.
    assert quality[best]["value"] == 100.0 and quality[weak]["value"] == 20.0
    assert quality[best]["detail"] == "Return on equity 20%"
    assert blocks[best]["lists"]["long"]["why"][0] == "ROE 20%"
    assert blocks[best]["fundamentals"]["is_financial"] is True


def test_long_checks_its_gates_in_the_order_the_page_explains():
    cands, sectors, snaps, _c, _m = _long_market()
    x = first_on(leaders.rank(cands, sectors=sectors, snapshot=snaps), "long")
    def why(**over):
        snap = dict(snaps, **{x: healthy(**over)})
        return leaders.rank(cands, sectors=sectors, snapshot=snap)[x]["lists"]["long"]["why_not"]
    assert why(eps_ttm=-1.0, f_score=3, pledge_pct=30.0, roce_pct=5.0, pe=200.0) == \
        "Lost money over the last four quarters."
    assert why(f_score=3, pledge_pct=30.0, roce_pct=5.0, pe=200.0) == "F-score 3 of 9: the list needs 5."
    assert why(pledge_pct=30.0, roce_pct=5.0, pe=200.0) == "Promoters have pledged 30% of the company."
    assert why(roce_pct=13.6, pe=200.0) == "Return on capital 13.6%: the list needs 14%."
    assert why(cfo_to_pat=0.69, pe=200.0) == "Cash from operations was 0.69× profit: the list needs 0.7×."
    assert why(debt_equity_x=1.04) == "Debt is 1.04× equity: the list allows 1×."
    assert why(pe=95.0, peg=1.4, pat_cagr_3y=30.0) == "P/E of 95: priced past the list's ceiling of 90."
    assert why() is None


def test_the_recipe_dictionaries_drive_every_threshold_and_weight(monkeypatch):
    """The lab swaps the whole dictionary, as it does for each declared
    version; the engine reads the one in place when it ranks."""
    cands, sectors, snaps, _c, _m = _long_market()
    x = first_on(leaders.rank(cands, sectors=sectors, snapshot=snaps), "month")
    snaps[x] = healthy(pledge_pct=25.0)
    assert leaders.rank(cands, sectors=sectors, snapshot=snaps)[x]["lists"]["month"]["why_not"].startswith(
        "Promoters have pledged")
    monkeypatch.setattr(leaders, "MONTH", dict(leaders.MONTH, pledge_max=50.0, sector_cap=2,
                                               pull_mix={"dip21": 1.0}))
    blocks = leaders.rank(cands, sectors=sectors, snapshot=snaps)
    assert blocks[x]["lists"]["month"]["eligible"]
    per = {}
    for s in ranked(blocks, "month"):
        per[sectors[s]] = per.get(sectors[s], 0) + 1
    assert max(per.values()) == 2
    pull = next(r for r in blocks[x]["lists"]["month"]["breakdown"] if r["factor"] == "pull")
    assert pull["value"] == blocks[x]["parts"]["dip_month"] or abs(pull["value"] - blocks[x]["parts"]["dip_month"]) <= 0.5
    # Long term without its valuation ceiling takes the bubble back.
    assert blocks["S117"]["lists"]["long"]["why_not"].startswith("P/E of 150")
    monkeypatch.setattr(leaders, "LONG", dict(leaders.LONG, valuation_ceiling=False,
                                              mix={"trendq": 1.0, "quality": 0.0}))
    blocks = leaders.rank(cands, sectors=sectors, snapshot=snaps)
    assert blocks["S117"]["lists"]["long"]["eligible"]
    e = blocks["S117"]["lists"]["long"]
    assert [r["factor"] for r in e["breakdown"]] == ["trendq"] and e["score"] == e["breakdown"][0]["value"]
    # The results list on its reaction alone ranks in the order of the move.
    cands, results = reporters(n=12)
    monkeypatch.setattr(leaders, "RESULTS", dict(leaders.RESULTS, mix={"reaction": 1.0, "volume": 0.0,
                                                                        "growth": 0.0}))
    blocks = leaders.rank(cands, results=results, snapshot=reported(results))
    assert ranked(blocks, "results") == [f"S{i:02d}" for i in range(11, -1, -1)]
    assert [r["factor"] for r in blocks["S11"]["lists"]["results"]["breakdown"]] == ["reaction"]


def test_every_score_is_its_breakdown_and_every_fact_is_an_observation():
    cands, sectors, snaps, results = realistic(n=240, seed=7)
    blocks = leaders.rank(cands, results=results, sectors=sectors, snapshot=snaps)
    seen = 0
    for b in blocks.values():
        for key in leaders.ORDER:
            e = b["lists"][key]
            if e["breakdown"]:
                seen += 1
                # The score prints to a decimal and each part to two: at most 0.05 + 5 x 0.005 apart.
                assert sum(r["points"] for r in e["breakdown"]) == pytest.approx(e["score"], abs=0.08)
                assert sum(r["weight"] for r in e["breakdown"]) == pytest.approx(1.0)
                for r in e["breakdown"]:
                    assert set(r) == {"factor", "label", "weight", "value", "points", "detail"}
                    assert 0 <= r["value"] <= 100 and r["label"] == leaders.FACTOR_LABELS[r["factor"]]
                    # `value` is printed to a decimal; the points are worked on the exact figure.
                    assert r["points"] == pytest.approx(r["weight"] * r["value"], abs=0.03)
                    assert r["detail"] and not WORDS_NEVER_USED.search(r["detail"])
            assert len(e["why"]) <= 4
            for text in e["why"] + [e["why_not"] or ""]:
                assert not WORDS_NEVER_USED.search(text), (key, text)
    assert seen > 400


def test_each_block_carries_the_figures_the_page_shows_from_its_filings():
    cands, sectors, snaps = market(60, 5)
    snaps["S00"] = healthy(sector_mf_quadrant="Leading", f_score=8)
    blocks = leaders.rank(cands, sectors=sectors, snapshot=snaps)
    f = blocks["S00"]["fundamentals"]
    assert tuple(f) == leaders.FUNDAMENTALS_SHOWN
    assert f["sector_mf_quadrant"] == "Leading" and f["f_score"] == 8 and f["roce_pct"] == 24.0
    assert f["pledge_pct"] == 0.0 and f["is_financial"] is False and f["quarter"] == "Q2 FY27"


def test_signals_carry_a_month_of_sessions_and_each_sessions_volume():
    df = frame(320, seed=3, volume_on=(4, 3.0))
    g = leaders.signals(df)
    assert len(g["days"]) == len(g["day_vols"]) == leaders.DAYS_KEPT == 23
    assert [d for d, _m in g["days"]] == [d for d, _v, _u in g["day_vols"]]
    v = df["Volume"].values
    for k, (d, vol, usual) in enumerate(g["day_vols"]):
        t = len(v) - leaders.DAYS_KEPT + k
        assert vol == pytest.approx(v[t]) and usual == pytest.approx(np.median(v[t - 20:t]))
    heavy = g["day_vols"][-5]
    assert heavy[1] / heavy[2] == pytest.approx(3.0, rel=0.05)
    assert all(vol is None and usual is None for _d, vol, usual in
               leaders.signals(df.drop(columns=["Volume"]))["day_vols"])


def test_a_result_is_read_over_the_window_asked_for_with_its_volume():
    cands, results = reporters(n=12)
    results["S40"] = filed(16)                        # priced fifteen sessions ago
    pool = [(c["symbol"], c["leader_sig"]) for c in cands]
    ten = leaders.result_reactions(pool, results)
    month = leaders.result_reactions(pool, results, window=21)
    assert "S40" not in ten and month["S40"]["sessions_ago"] == 15
    assert set(ten) < set(month)
    ev = ten["S05"]
    assert ev["vol_x"] == pytest.approx(2.0 / np.exp(0.06), rel=0.05)
    assert ev["above_sma50"] is True and ev["sma200_ratio"] > 1.0
