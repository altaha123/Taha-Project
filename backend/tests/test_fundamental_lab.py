"""
research/fundamental_ideas_lab.py's two honesty measures, and the notes the
page prints from them, on numbers small enough to check by hand.

The month list could pick only companies in NSE's industry list as it stands
today, and those beat the average liquid stock on their own, so the lab also
measures the list against the liquid stocks in that map (eligible_universe,
window_record's `eligible`, member_premium). The long list's checks run only
where a figure is known, so the lab counts when that was, on every list date,
instead of asserting it (count_known, _long_pool, _count_one,
coverage_summary). The notes the page prints are written from those figures
and from the recipes the engine reads (month_members, long_checks,
bias_text, what_text), never typed. None of this reads research/.ideas-data;
the last two tests read the lab's file and the study file, which are in the
repository.
"""
import json
import os
import pickle
import re
import sys
import types
import warnings

import numpy as np
import pandas as pd
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH = os.path.join(HERE, "..", "..", "research")
sys.path.insert(0, RESEARCH)
with warnings.catch_warnings():
    # The study module silences warnings for its own long runs; that stays
    # out of the suite.
    import fundamental_ideas_lab as L

import leaders

S = L.S
MINUS = "−"            # the page's minus sign (picks.js signed)


def panel(days=30, seed=3):
    """Three stocks from December 2021 into January 2022, a close a session,
    bought at the close (entry is the close), so a one-session hold returns
    the next close over this one. A and B climb, C falls."""
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2021-12-01", periods=days)
    drift = {"A": 0.004, "B": 0.002, "C": -0.003}
    C = pd.DataFrame({k: 100 * np.exp(np.cumsum(d + rng.normal(0, 0.01, days))) for k, d in drift.items()},
                     index=idx)
    return types.SimpleNamespace(C=C, entry=C.copy())


def picks(P, names=("A",), hold=1):
    """run_list's output for a list of `names` made every session."""
    fwd = P.C.shift(-hold) / P.entry - 1
    rows = [(d, n, float(fwd.at[d, n]), 0.0, False) for d in P.C.index[:-hold] for n in names]
    return pd.DataFrame(rows, columns=["date", "name", "ret", "bench", "exited"])


def every_stock(P):
    return pd.DataFrame(True, index=P.C.index, columns=P.C.columns)


def test_the_industry_map_stocks_are_the_liquid_ones_the_engine_can_place_in_an_industry():
    """rank() reads the map's keys in capitals and drops an empty industry;
    a stock the universe leaves out stays out."""
    U = pd.DataFrame([[True, True, True, False]], columns=["ABB", "TCS", "NEWCO", "ITC"])
    E = L.eligible_universe(U, {"abb": "Capital Goods", "TCS": "Information Technology", "NEWCO": "",
                                "ITC": "Fast Moving Consumer Goods"})
    assert E.iloc[0].to_dict() == {"ABB": True, "TCS": True, "NEWCO": False, "ITC": False}


def test_the_month_list_is_also_measured_against_the_liquid_stocks_in_the_industry_map():
    P = panel()
    U = every_stock(P)
    E = L.eligible_universe(U, {"A": "Capital Goods", "B": "Healthcare"})
    df = picks(P)
    plain = L.window_record(P, U, df, 1, "1900-01-01", "2100-01-01")
    rec = L.window_record(P, U, df, 1, "1900-01-01", "2100-01-01", E)
    # Without the mask the record is what it always was; with it, that and more.
    assert not [k for k in plain if "eligible" in k or "premium" in k]
    assert {k: rec[k] for k in plain} == plain
    # By hand: each session's pick less each average.
    fwd = P.C.shift(-1) / P.entry - 1
    per = df.groupby("date")["ret"].mean()
    every, theirs = fwd.mean(axis=1).reindex(per.index), fwd[["A", "B"]].mean(axis=1).reindex(per.index)
    lead, gap = per - theirs, theirs - every
    assert rec["vs_avg_stock_pct"] == round(float((per - every).mean() * 100), 2)
    assert rec["vs_eligible_pct"] == round(float(lead.mean() * 100), 2)
    assert rec["vs_eligible_net_pct"] == pytest.approx(rec["vs_eligible_pct"] - S.ROUND_TRIP_COST_PCT, abs=0.011)
    assert rec["vs_eligible_t"] == round(S.newey_west_t(lead.values, 1), 2)
    assert rec["lists_ahead_of_eligible_pct"] == round(float((lead > 0).mean() * 100), 1)
    assert rec["member_premium_pct"] == round(float(gap.mean() * 100), 2)
    assert rec["member_premium_t"] == round(S.newey_west_t(gap.values, 1), 2)
    # A and B beat C, so the map's average is the higher bar, and the lead
    # over every stock is the lead over them plus their premium.
    assert rec["member_premium_pct"] > 0 and rec["vs_eligible_pct"] < rec["vs_avg_stock_pct"]
    assert rec["vs_eligible_pct"] + rec["member_premium_pct"] == pytest.approx(rec["vs_avg_stock_pct"], abs=0.016)


def test_the_member_premium_is_split_by_half_as_the_lead_over_the_average_stock_is():
    P = panel()
    U = every_stock(P)
    E = L.eligible_universe(U, {"A": "Capital Goods", "B": "Healthcare"})
    df = picks(P)
    got = L.member_premium(P, U, E, df, 1, "2017-21")
    fwd = P.C.shift(-1) / P.entry - 1
    gap = (fwd[["A", "B"]].mean(axis=1) - fwd.mean(axis=1)).reindex(pd.DatetimeIndex(sorted(df["date"].unique())))
    assert got["pct"] == round(float(gap.mean() * 100), 2)
    assert got["by_half"]["2017-21"] == round(float(gap[gap.index < S.SPLIT].mean() * 100), 2)
    assert got["by_half"]["2022-26"] == round(float(gap[gap.index >= S.SPLIT].mean() * 100), 2)
    # vs_eligible_stock is the study's own measure, on the stocks in the map.
    on_all, on_them = (S.vs_average_stock(P, M, df, 1, first="2017-21") for M in (U, E))
    assert on_them["excess_pct"] == pytest.approx(on_all["excess_pct"] - got["pct"], abs=0.016)
    assert set(on_them["by_half"]) == {"2017-21", "2022-26"}


def test_a_check_counts_only_where_the_engine_could_read_its_figure():
    """Lenders aside; a company with no filings is no lender, as the list
    reads it, and has no figure; a NaN is no figure."""
    snaps = {"BANK": {"is_financial": True, "roce_pct": 20.0, "f_score": 7},
             "MAKER": {"is_financial": False, "roce_pct": 18.0, "debt_equity_x": float("nan"),
                       "cfo_to_pat": 0.9, "f_score": None},
             "FULL": {"is_financial": False, "roce_pct": 9.0, "debt_equity_x": 0.2, "cfo_to_pat": 1.1,
                      "f_score": 6}}
    got = L.count_known(["BANK", "MAKER", "FULL", "NOFILINGS"], snaps)
    assert got == {"companies": 3, "with_filings": 2, "roce_pct": 2, "debt_equity_x": 1, "cfo_to_pat": 2,
                   "f_score": 1}


def _sig(turnover=5e8, young=False):
    """A candidate's leader_sig with every signal leaders.in_universe needs."""
    return {"turnover": turnover, "price": 100.0, "vol": 0.3, "va12": 0.1, "va6": 0.1, "near_high": 0.9,
            "trend": 50.0, "ret_5d": 0.01, "young": young}


def test_a_date_is_counted_on_the_long_lists_pool_and_the_filings_visible_that_session(tmp_path, monkeypatch):
    """_long_pool keeps what rank() ranks for the long list: liquid, every
    signal measurable, listed a year. _count_one reads each company's
    snapshot from the filings that had reached the exchange by that
    session's close, as the replay does: one filed after 15:30 is seen from
    the next session. A lender (here by its industry) is left out, a
    company with no filing counted as one without figures."""
    idx = pd.bdate_range("2024-05-13", periods=6)       # Monday 13 to Monday 20 May 2024
    C = pd.DataFrame(100.0, index=idx, columns=["MAKER", "LATE", "BANK", "NOFILE", "YOUNG", "THIN"])
    P = types.SimpleNamespace(C=C, RAW=C)

    def sheet(sym, filed):
        return {"symbol": sym, "basis": "standalone", "period_end": "2024-03-31", "filed_at": filed, "months": 12,
                "debt_equity_x": 0.4, "total_equity_cr": 500.0}
    balance = pd.DataFrame([sheet("MAKER", "2024-05-14 15:00:00"), sheet("LATE", "2024-05-14 17:45:00"),
                            sheet("BANK", "2024-05-13 10:00:00"), sheet("YOUNG", "2024-05-13 10:00:00"),
                            # Filed before its year ended: a data error, never seen.
                            sheet("NOFILE", "2024-03-01 10:00:00")])
    for table, name in L.TABLE_FILES.items():
        df = balance if table == "balance" else pd.DataFrame(columns=["symbol", "basis", "period_end", "filed_at"])
        df.to_csv(tmp_path / name, index=False)
    monkeypatch.setattr(L, "DATA", str(tmp_path))
    cands = [{"symbol": s, "leader_sig": _sig()} for s in ("MAKER", "LATE", "BANK", "NOFILE")]
    cands += [{"symbol": "YOUNG", "leader_sig": _sig(young=True)}, {"symbol": "THIN", "leader_sig": _sig(1e6)}]
    assert L._long_pool(cands) == ["MAKER", "LATE", "BANK", "NOFILE"]
    folder = tmp_path / "cands"
    folder.mkdir()
    for i in range(len(idx)):
        with open(folder / f"{i}.pkl", "wb") as f:
            pickle.dump(cands, f)
    monkeypatch.setattr(L, "_G", {"P": P, "dir": str(folder), "pit": L.load_pit(P),
                                  "sectors": {"BANK": "Financial Services"}})
    zero = {"roce_pct": 0, "cfo_to_pat": 0, "f_score": 0}
    # Monday: the lender's sheet is in, so it is known as one and left out.
    assert L._count_one(0) == {"date": "2024-05-13", "companies": 3, "with_filings": 0, "debt_equity_x": 0, **zero}
    # Tuesday: MAKER's sheet, filed at 15:00, is in that close; LATE's, at 17:45, is not.
    assert L._count_one(1) == {"date": "2024-05-14", "companies": 3, "with_filings": 1, "debt_equity_x": 1, **zero}
    assert L._count_one(2) == {"date": "2024-05-15", "companies": 3, "with_filings": 2, "debt_equity_x": 2, **zero}


def test_the_coverage_cache_is_keyed_on_the_code_that_counts(tmp_path, monkeypatch):
    """A changed rule in this lab (the 15:30 cut, the pool, the counting)
    must count again, not read the counts its old rule wrote."""
    for name in L.TABLE_FILES.values():
        (tmp_path / name).write_text("symbol,filed_at,period_end\n")
    monkeypatch.setattr(L, "DATA", str(tmp_path))
    P = types.SimpleNamespace(C=pd.DataFrame(index=pd.bdate_range("2024-01-01", periods=5)))
    key = L._coverage_key(P, "stamp", {"ABB": "Capital Goods"}, [1, 2])
    assert key == L._coverage_key(P, "stamp", {"ABB": "Capital Goods"}, [1, 2])
    lab = tmp_path / "lab.py"
    with open(L.__file__, encoding="utf-8") as f:
        lab.write_text(f.read() + "\n# one line more\n")
    monkeypatch.setattr(L, "__file__", str(lab))
    assert L._coverage_key(P, "stamp", {"ABB": "Capital Goods"}, [1, 2]) != key


LAST = "2025-11-19"         # the last list date whose year-long hold has run, in these rows


def counts(f_score=None, cash=None):
    """long_coverage()'s rows, a list date every Wednesday from January 2017
    to November 2026, 200 companies each: cash against profit known for one
    in twenty until October 2021 and four in five after; debt for none until
    mid-December 2022 and for half after, but for one date in March 2023
    when it fell just short; return on capital for one in a hundred until
    June 2023; the F-score for one in two hundred until June 2024; and one
    date with no company, which says nothing."""
    out = []
    for d in pd.date_range("2017-01-04", "2026-11-30", freq="W-WED"):
        d = str(d.date())
        out.append({"date": d, "companies": 200, "with_filings": 190,
                    "cfo_to_pat": (160 if d >= "2021-10-06" else 10) if cash is None else cash,
                    "debt_equity_x": 0 if d < "2022-12-14" else 99 if d == "2023-03-01" else 100,
                    "roce_pct": 120 if d >= "2023-06-07" else 2,
                    "f_score": (180 if d >= "2024-06-12" else 1) if f_score is None else f_score})
    out.append({"date": "2023-01-04", "companies": 0, "with_filings": 0, **{k: 0 for k in L.CHECKS}})
    return out


def test_the_coverage_summary_says_from_when_each_check_had_data_for_most():
    rows = counts()
    cov = L.coverage_summary(rows, L.WINDOWS["long"], LAST)
    assert cov["from"] == "2017-01-04" and cov["to"] == "2026-11-25"
    assert cov["windows"] == {"first": ["2022-11-01", "2024-04-30"], "second": ["2024-05-01", LAST]}
    assert cov["first_half"] == {"label": "2017-21", "before": S.SPLIT, "list_dates": 261}
    # From a date on means on every list date after it: debt first reached
    # half in December 2022, fell short on 1 March 2023 and held from the
    # next date, 8 March.
    assert {k: c["most_from"] for k, c in cov["checks"].items()} == {
        "cfo_to_pat": "2021-10-06", "debt_equity_x": "2023-03-08", "roce_pct": "2023-06-07", "f_score": "2024-06-12"}
    # The mean share known over each window's dates and over the first half,
    # the empty date aside.
    seen = pd.DataFrame([r for r in rows if r["companies"]])
    spans = dict(cov["windows"], first_half=["1900-01-01", "2021-12-31"])
    dates = dict(cov["list_dates"], first_half=cov["first_half"]["list_dates"])
    for name, (a, b) in spans.items():
        w = seen[(seen["date"] >= a) & (seen["date"] <= b)]
        assert dates[name] == len(w)
        for k in L.CHECKS:
            assert cov["checks"][k][f"{name}_pct"] == round(float((w[k] / w["companies"]).mean() * 100), 1)
    assert cov["checks"]["f_score"]["first_pct"] == 0.5 and cov["checks"]["cfo_to_pat"]["first_half_pct"] == 8.7
    # Not known for half on the last date: no date.
    assert L.coverage_summary(counts(f_score=99), L.WINDOWS["long"], LAST)["checks"]["f_score"]["most_from"] is None
    end = counts()
    end[-2] = dict(end[-2], f_score=99)          # the last list date, 25 November 2026
    assert L.coverage_summary(end, L.WINDOWS["long"], LAST)["checks"]["f_score"]["most_from"] is None


def test_the_long_note_is_written_from_the_counts():
    cov = L.coverage_summary(counts(), L.WINDOWS["long"], LAST)
    text = L.long_checks(cov)
    assert text == (
        "A check is made only where its figure is known. "
        # Every check under one company in ten over 2017-21: the list ranked on its trend there.
        "In 2017-21, of the liquid companies the list ranks, lenders aside, cash from operations against profit "
        "was known for 8.7% on average, debt to equity for 0%, return on capital for 1% and the F-score for 0.5%, "
        "so there the list was ranked mostly on its trend. "
        "At least half of them had cash from operations against profit from 6 October 2021 on, debt to equity "
        "from 8 March 2023, return on capital from 7 June 2023 and the F-score from 12 June 2024. "
        # 0.5% throughout the first window; in the second (to LAST), 0.5% on
        # six dates and 90% on 76: 83.5% on average.
        "From November 2022 to April 2024, the period this version was chosen on, the F-score was known for 0.5% "
        "of them on average (83.5% from May 2024 to November 2025), so that check was effectively untested there.")
    # No lab words on the page.
    assert "counted" not in text and "window" not in text
    # Cash known for one in five over 2017-21 tested the list there: the
    # other three were not, and the trend is not said to have ranked it.
    some = L.long_checks(L.coverage_summary(counts(cash=40), L.WINDOWS["long"], LAST))
    assert ("In 2017-21, of the liquid companies the list ranks, lenders aside, debt to equity was known for 0% "
            "on average, return on capital for 1% and the F-score for 0.5%, so those checks were effectively "
            "untested there.") in some
    assert "trend" not in some
    # Had the F-score been on file throughout, the window that chose the
    # version tested it; debt and return on capital still were not in 2017-21.
    full = L.long_checks(L.coverage_summary(counts(f_score=150, cash=150), L.WINDOWS["long"], LAST))
    assert "chosen on" not in full and "trend" not in full
    assert ("debt to equity was known for 0% on average and return on capital for 1%, so those checks were "
            "effectively untested there.") in full
    # Not known for half on the last date: said, with that date.
    assert L.long_checks(L.coverage_summary(counts(f_score=0), L.WINDOWS["long"], LAST)).endswith(
        "Fewer than half of them had the F-score on the last list date, 25 November 2026. From November 2022 to "
        "April 2024, the period this version was chosen on, the F-score was known for 0% of them on average (0% "
        "from May 2024 to November 2025), so that check was effectively untested there.")
    # The note around it types no figure of its own.
    assert not re.search(r"\d", L.BIAS["long"])
    note = L.bias_text("long", "L1", {}, cov)
    assert note.startswith(text) and "{" not in note and "Pledges and holdings have no history" in note


LEAD = {"excess_pct": 0.55, "t": 1.91, "lists_ahead_pct": 56.6,
        "by_half": {"2017-21": {"excess_pct": 1.05, "t": 2.3}, "2022-26": {"excess_pct": -0.04, "t": -0.13}}}


def test_the_month_note_prints_the_lead_over_the_liquid_stocks_in_the_map_and_their_premium():
    said = L.month_members(0.23, LEAD)
    assert said == ("Industries are NSE's list as it stands today, and a stock without one fails the industry "
                    "test, so the replay could pick only companies in that list. On the same days the liquid stocks "
                    "in that list did better than the average liquid stock by 0.23%, and the list's lead over them "
                    f"was +0.55% a pick (2017-21 +1.05%, 2022-26 {MINUS}0.04%).")
    # Every figure is one it was given, in the page's unit; no field names.
    assert re.findall(r"\d+\.\d+", said) == ["0.23", "0.55", "1.05", "0.04"]
    assert "_" not in said
    assert "did worse than the average liquid stock by 0.10%" in L.month_members(-0.1, LEAD)
    assert "did as well as the average liquid stock, and" in L.month_members(0.004, LEAD)
    assert L.month_members(None, LEAD).endswith("On the same days the list's lead over the liquid stocks in that "
                                                f"list was +0.55% a pick (2017-21 +1.05%, 2022-26 {MINUS}0.04%).")
    loose = L.month_members(0.3, LEAD, gated=False)
    assert "could pick only" not in loose and "does not need one" in loose and "+0.55% a pick" in loose
    # The chosen version's own gate decides which: M3 keeps the industry
    # test, M1 is M0 without it. The year the quarterly filings start is the
    # first one the replay could see, from the results table.
    R = pd.DataFrame({"d0": pd.to_datetime(["2019-03-04", "2018-05-25"])})
    rec = {"member_premium": {"pct": 0.31}, "vs_eligible_stock": LEAD}
    note = L.bias_text("month", "M3", rec, R=R)
    assert "{" not in note and "by 0.31%" in note and "could pick only" in note and "+0.55% a pick" in note
    assert "Quarterly filings start in 2018 and" in note
    assert "could pick only" not in L.bias_text("month", "M1", rec, R=R)
    # The notes around them type no figure of their own.
    assert not re.search(r"\d", L.BIAS["month"]) and not re.search(r"\d", L.BIAS["results"])


def test_the_results_note_prints_the_lead_over_the_companies_that_reported():
    note = L.bias_text("results", "R4", {"vs_reporters": LEAD})
    assert note.endswith(f"Against every liquid company whose results were priced in the same "
                         f"{leaders.RESULTS_WINDOW} sessions, which shares that bias, the list's lead was +0.55% a "
                         f"pick (2017-21 +1.05%, 2022-26 {MINUS}0.04%).")
    assert "vs_reporters" not in note
    assert L.bias_text("results", "R4", {}).endswith("with the revised figures.")


def test_what_each_list_is_is_written_from_the_recipe_the_engine_reads():
    month = L.what_text("month", L._recipe("month", "M3"))
    assert f"leader score in the top {100 - leaders.MONTH['leader_floor'] * 100:.0f}%" in month
    # The gate compares an industry's rank with how many are ranked.
    assert "in an industry ranked in the top half on money flow" in month
    assert f"no more than {leaders.MONTH['pledge_max']:g}% of the company pledged" in month
    assert "(a lender's sales alone)" in month
    assert "industry ranked" not in L.what_text("month", L._recipe("month", "M1"))
    results = L.what_text("results", L._recipe("results", "R4"))
    assert "a profit and an operating profit, both up on a year ago (one-off items left out of the operating " \
           "profit)" in results
    assert "A lender is tested on its sales, profit and exceptional gain only." in results
    assert f"in the last {leaders.RESULTS_WINDOW} sessions" in results
    assert "Ranked half on that session's move less the average liquid stock's, a quarter on the volume behind " \
           "it and a quarter on the growth" in results
    long_ = L.what_text("long", L._recipe("long", "L1"))
    assert "and positive shareholders' equity" in long_
    assert f"a return on equity of {leaders.LONG['roe_min_fin']:g}% or more" in long_
    # Each threshold is read from the recipe, not typed: move one and the
    # words move with it.
    for tab, key, field, value, want in (
            ("month", "M3", "sector_top", 0.4, "ranked in the top 40% on money flow"),
            ("month", "M3", "leader_floor", 0.8, "leader score in the top 20%"),
            ("results", "R4", "rev_min", 11.0, "sales up 11% or more"),
            ("results", "R4", "exceptional_max", 0.2, "no more than 20% of profit before tax"),
            ("results", "R4", "min_qualified", 6, "only when 6 or more pass"),
            ("long", "L1", "roce_min", 17.0, "a return on capital of 17% or more"),
            ("long", "L1", "de_max", 0.5, "debt no more than 0.5 times equity"),
            ("long", "L1", "sector_cap", 3, "at most 3 from one industry")):
        assert want in L.what_text(tab, dict(L._recipe(tab, key), **{field: value})), (tab, field)


def _research_json(name):
    with open(os.path.join(RESEARCH, name), encoding="utf-8") as f:
        return json.load(f)


def test_the_labs_file_reports_both_measures_beside_the_declared_rule():
    """--report writes both; the rule reads neither."""
    lab = _research_json("fundamental-ideas-lab.json")
    for group in ("records", "before"):
        for key, rec in lab[group]["month"].items():
            for w in ("first", "second", "all"):
                r = rec[w]
                assert r["vs_eligible_t"] is not None and r["member_premium_t"] is not None, (group, key, w)
                assert r["vs_eligible_pct"] + r["member_premium_pct"] == pytest.approx(r["vs_avg_stock_pct"],
                                                                                       abs=0.016), (group, key, w)
    assert not [k for tab in ("results", "long") for rec in lab["records"][tab].values()
                for k in rec["first"] if "eligible" in k or "premium" in k]
    assert L.choose(lab["records"]) == lab["chosen"]
    cov = lab["coverage"]["long"]
    assert set(cov["checks"]) == set(L.CHECKS) and cov["windows"]["first"] == list(L.WINDOWS["long"][0])
    # Counted on every list date, the record's first half among them.
    cols = cov["by_date"]["columns"]
    rows = [dict(zip(cols, r)) for r in cov["by_date"]["rows"]]
    assert rows[0]["date"] < "2018-01-01" and cov["first_half"]["list_dates"] > 200
    assert len(rows) >= lab["records"]["long"][lab["chosen"]["long"]]["all"]["list_dates"]
    # The summary is its own counts': worked out again from the rows on file, the same.
    again = L.coverage_summary(rows, L.WINDOWS["long"], cov["windows"]["second"][1])
    assert {k: cov[k] for k in again} == again


def test_the_published_notes_carry_the_figures_the_lab_measured():
    """The page prints these notes under "how". The month record's lead over
    the liquid stocks in the industry map and their premium are the lab's
    own, every figure in the notes is the record's, and what each list is
    reads as the recipe it was replayed on. Fails until --publish has run on
    the lab's file as it stands."""
    lab, study = _research_json("fundamental-ideas-lab.json"), _research_json("ideas-study.json")
    chosen = lab["chosen"]
    month, results, long_ = (study["lists"][k] for k in ("month", "results", "long"))
    hint = "run research/fundamental_ideas_lab.py --publish"
    measured = lab["records"]["month"][chosen["month"]]["all"]
    lead = month.get("vs_eligible_stock") or {}
    assert (lead.get("excess_pct"), lead.get("t"), lead.get("lists_ahead_pct")) == (
        measured["vs_eligible_pct"], measured["vs_eligible_t"], measured["lists_ahead_of_eligible_pct"]), hint
    assert month["member_premium"]["pct"] == measured["member_premium_pct"], hint
    # The month note, figure for figure, but for the year the filings start,
    # which only the results table in research/.ideas-data can say.
    said = L.month_members(month["member_premium"]["pct"], lead,
                           L._recipe("month", chosen["month"]).get("sector_gate", True))
    note = re.escape(L.BIAS["month"].format(members=said, quarters_from="YEAR")).replace("YEAR", r"\d{4}")
    assert re.fullmatch(note, month["bias"]), hint
    assert results["bias"] == L.bias_text("results", chosen["results"], results), hint
    assert long_["bias"] == L.bias_text("long", chosen["long"], long_, lab["coverage"]["long"]), hint
    assert long_["lab"]["coverage"]["checks"] == lab["coverage"]["long"]["checks"], hint
    for tab in L.TABS:
        assert study["lists"][tab]["what"] == L.what_text(tab, L._recipe(tab, chosen[tab])), (tab, hint)
