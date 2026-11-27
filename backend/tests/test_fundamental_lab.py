"""
research/fundamental_ideas_lab.py's two honesty measures, on numbers small
enough to check by hand.

The month list could pick only companies in NSE's industry list as it stands
today, and those beat the average liquid stock on their own, so the lab also
measures the list against them (eligible_universe, window_record's
`eligible`, member_premium). The long list's checks run only where a figure
is known, so the lab counts when that was instead of asserting it
(count_known, coverage_summary). The notes the page prints are written from
those figures (month_members, long_checks, bias_text), never typed. None of
this reads research/.ideas-data; the last two tests read the lab's file and
the study file, which are in the repository.
"""
import json
import os
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

S = L.S


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


def test_the_eligible_stocks_are_the_ones_the_engine_can_place_in_an_industry():
    """rank() reads the map's keys in capitals and drops an empty industry;
    a stock the universe leaves out stays out."""
    U = pd.DataFrame([[True, True, True, False]], columns=["ABB", "TCS", "NEWCO", "ITC"])
    E = L.eligible_universe(U, {"abb": "Capital Goods", "TCS": "Information Technology", "NEWCO": "",
                                "ITC": "Fast Moving Consumer Goods"})
    assert E.iloc[0].to_dict() == {"ABB": True, "TCS": True, "NEWCO": False, "ITC": False}


def test_the_month_list_is_also_measured_against_the_stocks_it_could_pick():
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
    # A and B beat C, so the eligible average is the higher bar, and the
    # lead over every stock is the lead over them plus their premium.
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
    # vs_eligible_stock is the study's own measure, on the eligible stocks.
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


LAST = "2025-11-19"         # the last list date whose year-long hold has run, in these rows


def counts(f_score=None):
    """long_coverage()'s rows, a list date every Wednesday from November
    2022: cash against profit known throughout, debt for exactly half from
    mid-December 2022, return on capital from June 2023 and the F-score from
    June 2024; and one date with no company, which says nothing."""
    out = []
    for d in pd.date_range("2022-11-01", "2026-11-30", freq="W-WED"):
        d = str(d.date())
        out.append({"date": d, "companies": 200, "with_filings": 190, "cfo_to_pat": 160,
                    "debt_equity_x": 100 if d >= "2022-12-14" else 99,
                    "roce_pct": 120 if d >= "2023-06-07" else 2,
                    "f_score": (180 if d >= "2024-06-12" else 1) if f_score is None else f_score})
    out.append({"date": "2023-01-04", "companies": 0, "with_filings": 0, **{k: 0 for k in L.CHECKS}})
    return out


def test_the_coverage_summary_says_when_each_check_first_had_data_for_most():
    rows = counts()
    cov = L.coverage_summary(rows, L.WINDOWS["long"], LAST)
    assert cov["from"] == "2022-11-02" and cov["to"] == "2026-11-25"
    assert cov["windows"] == {"first": ["2022-11-01", "2024-04-30"], "second": ["2024-05-01", LAST]}
    assert {k: c["most_from"] for k, c in cov["checks"].items()} == {
        "cfo_to_pat": "2022-11-02", "debt_equity_x": "2022-12-14", "roce_pct": "2023-06-07", "f_score": "2024-06-12"}
    # The mean share known over each window's dates, the empty date aside.
    seen = pd.DataFrame([r for r in rows if r["companies"]])
    for name, (a, b) in cov["windows"].items():
        w = seen[(seen["date"] >= a) & (seen["date"] <= b)]
        assert cov["list_dates"][name] == len(w)
        for k in L.CHECKS:
            assert cov["checks"][k][f"{name}_pct"] == round(float((w[k] / w["companies"]).mean() * 100), 1)
    assert cov["checks"]["f_score"]["first_pct"] == 0.5
    # Never known for half: no date.
    assert L.coverage_summary(counts(f_score=99), L.WINDOWS["long"], LAST)["checks"]["f_score"]["most_from"] is None


def test_the_long_note_is_written_from_the_counts():
    cov = L.coverage_summary(counts(), L.WINDOWS["long"], LAST)
    text = L.long_checks(cov)
    assert text.startswith("A check is made only where its figure is known.")
    assert ("at least half had each figure: cash from operations against profit already on 2 November 2022, the "
            "first date counted; debt to equity from 14 December 2022; return on capital from 7 June 2023; and "
            "the F-score from 12 June 2024.") in text
    # 0.5% throughout the first window; in the second (to LAST), 0.5% on six
    # dates and 90% on 76: 83.5% on average.
    assert text.endswith("In the window that chose this version, November 2022 to April 2024, the F-score was "
                         "known for 0.5% of them on average (83.5% in the second window), so that check was "
                         "effectively untested there.")
    # Return on capital was known for most of that window: not called untested.
    assert "return on capital was known" not in text and "return on capital for" not in text
    # Had the F-score been on file there, the note would not say it was untested.
    assert "untested" not in L.long_checks(L.coverage_summary(counts(f_score=150), L.WINDOWS["long"], LAST))
    # Never known for half: said, up to the last date counted.
    assert "and the F-score not by 25 November 2026, the last date counted." in L.long_checks(
        L.coverage_summary(counts(f_score=0), L.WINDOWS["long"], LAST))
    # The note around it types no figure of its own.
    assert not re.search(r"\d", L.NOTES["long"]["bias"])
    note = L.bias_text("long", "L1", {}, cov)
    assert note.startswith(text) and "{" not in note and "Pledges and holdings have no history" in note


def test_the_month_note_carries_the_premium_this_run_measured():
    said = L.month_members(0.24)
    assert "the replay could pick only companies in that list" in said
    assert "did better than the average liquid stock by 0.24 points a hold over the record" in said
    assert said.endswith("vs_eligible_stock measures the list against them.")
    assert re.findall(r"\d+(?:\.\d+)?", said) == ["0.24"]
    assert "did worse than the average liquid stock by 0.10 points a hold" in L.month_members(-0.1)
    assert "did as well as the average liquid stock over the record" in L.month_members(0.004)
    loose = L.month_members(0.3, gated=False)
    assert "could pick only" not in loose and "does not need one" in loose
    # The chosen version's own gate decides which: M3 keeps the industry
    # test, M1 is M0 without it. The year the quarterly filings start is the
    # first one the replay could see, from the results table.
    R = pd.DataFrame({"d0": pd.to_datetime(["2019-03-04", "2018-05-25"])})
    note = L.bias_text("month", "M3", {"member_premium": {"pct": 0.31}}, R=R)
    assert "{" not in note and "0.31 points a hold" in note and "could pick only" in note
    assert "Quarterly filings start in 2018 and" in note
    assert "could pick only" not in L.bias_text("month", "M1", {"member_premium": {"pct": 0.31}}, R=R)
    # The note around it types no figure of its own.
    assert not re.search(r"\d", L.NOTES["month"]["bias"])


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
    # The summary is its own counts': worked out again from the rows on file, the same.
    cols = cov["by_date"]["columns"]
    rows = [dict(zip(cols, r)) for r in cov["by_date"]["rows"]]
    again = L.coverage_summary(rows, L.WINDOWS["long"], cov["windows"]["second"][1])
    assert {k: cov[k] for k in again} == again


def test_the_published_notes_carry_the_figures_the_lab_measured():
    """The page prints these notes under "how": the month list's premium and
    the long list's dates are the lab's, and the month record is measured
    against the stocks it could pick. Fails until --publish has run on the
    lab's file as it stands."""
    lab, study = _research_json("fundamental-ideas-lab.json"), _research_json("ideas-study.json")
    month, long_ = study["lists"]["month"], study["lists"]["long"]
    hint = "run research/fundamental_ideas_lab.py --publish"
    assert set(month.get("vs_eligible_stock") or {}) >= {"excess_pct", "t", "by_half"}, hint
    # The month note, figure for figure, but for the year the filings start,
    # which only the results table in research/.ideas-data can say.
    said = L.month_members(month["member_premium"]["pct"],
                           L._recipe("month", lab["chosen"]["month"]).get("sector_gate", True))
    note = re.escape(L.NOTES["month"]["bias"].format(members=said, quarters_from="YEAR")).replace("YEAR", r"\d{4}")
    assert re.fullmatch(note, month["bias"]), hint
    assert long_["bias"] == L.bias_text("long", lab["chosen"]["long"], long_, lab["coverage"]["long"]), hint
    assert long_["lab"]["coverage"]["checks"] == lab["coverage"]["long"]["checks"], hint
