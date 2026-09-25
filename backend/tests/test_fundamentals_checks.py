"""
The accuracy checks over the three statement tables.

Each test plants one kind of error that the first full sweep actually found —
a March filing a hundred times too small (Trent FY22), a PAT whose owners' and
minority shares disagree with it (Aarti Q4 FY21), a quarter filed in the wrong
unit (Caplin Point Q1 FY21) — and checks it is caught, graded and explained;
and plants the things that look like errors and are not (a share split,
rounding on a tiny company, Yahoo reporting in dollars, a group's share of its
joint ventures) and checks they are left alone.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("ALTAHA_FUNDAMENTALS_DB", str(tmp_path / "f.db"))
    for m in ("fundamentals_store", "fundamentals_checks"):
        sys.modules.pop(m, None)
    import fundamentals_store as store
    import fundamentals_checks as checks
    return store, checks


def _q(sym, end, rev, pat=None, eps=None, **kw):
    start = {"06-30": "04-01", "09-30": "07-01", "12-31": "10-01", "03-31": "01-01"}[end[5:]]
    return {"symbol": sym, "company": sym, "basis": "consolidated", "freq": "quarterly",
            "label": "Q " + end, "period_from": end[:5] + start, "period_end": end,
            "months": 3, "filed_at": "2026-01-01", "revenue_cr": rev, "pat_cr": pat,
            "eps_basic": eps, **kw}


def _fy(sym, end, rev, pat=None, **kw):
    return {"symbol": sym, "company": sym, "basis": "consolidated", "freq": "annual",
            "label": "FY" + end[2:4], "period_from": "%d-04-01" % (int(end[:4]) - 1),
            "period_end": end, "months": 12, "filed_at": "2026-01-01",
            "revenue_cr": rev, "pat_cr": pat, **kw}


def _year(sym, revs, fy_rev, end_year=2022, **kw):
    y = end_year
    ends = ["%d-06-30" % (y - 1), "%d-09-30" % (y - 1), "%d-12-31" % (y - 1), "%d-03-31" % y]
    return [_q(sym, e, r) for e, r in zip(ends, revs)] + [_fy(sym, ends[-1], fy_rev, **kw)]


def _by(checks, cid, **kw):
    return [f for f in checks.failures(check_id=cid, limit=0, **kw)]


def test_a_clean_company_passes_everything(env):
    store, checks = env
    store.upsert("income", _year("GOOD", [100, 110, 120, 130], 460))
    s = checks.run()
    assert s["failures"] == 0
    assert {c["id"]: c["tested"] for c in s["checks"]}["quarters_sum_revenue"] == 1


def test_a_march_filing_a_hundred_times_too_small_is_diagnosed(env):
    """Trent FY22: the fourth quarter AND the year, one document, both /100."""
    store, checks = env
    store.upsert("income", _year("TRENT", [900, 1000, 1100, 13.0], 43.0))
    (f,) = _by(checks.run() and checks, "quarters_sum_revenue")
    assert f["severity"] == "major"
    assert "fourth quarter and year together" in f["note"] and "100x too small" in f["note"]


def test_one_quarter_in_the_wrong_unit_is_named(env):
    store, checks = env
    store.upsert("income", _year("CAPLIN", [2.4, 268, 274, 290], 240 + 268 + 274 + 290))
    checks.run()
    (f,) = _by(checks, "quarters_sum_revenue")
    assert "Q 2021-06-30 looks 100x too small" in f["note"]


def test_a_year_that_disagrees_with_its_own_quarters_says_so_without_guessing(env):
    """Aarey Drugs FY23: Q4 filed as 158, the year as 62.5 — the filing itself."""
    store, checks = env
    store.upsert("income", _year("AAREY", [117, 76, 62, 158], 62.5))
    checks.run()
    (f,) = _by(checks, "quarters_sum_revenue")
    assert "annual report says which" in f["note"]


def test_small_gaps_are_minor_and_rounding_is_not_a_gap(env):
    store, checks = env
    store.upsert("income", _year("RESTATE", [100, 100, 100, 100], 408)     # 2%
                 + _year("TINY", [0.24, 0.24, 0.24, 0.24], 0.97, end_year=2023))
    checks.run()
    fails = checks.failures(limit=0)
    assert [(f["symbol"], f["severity"]) for f in fails] == [("RESTATE", "minor")]


def test_a_groups_share_of_its_joint_ventures_reconciles(env):
    """Tata Power FY23: pbt 1333.5 - tax 1647.3 + regulatory 924 + JVs 3199.5 = 3809.7."""
    store, checks = env
    store.upsert("income", [_fy("TATAPOWER", "2023-03-31", 55000, 3809.7, pbt_cr=1333.5,
                                tax_cr=1647.3, pat_continuing_cr=610.2,
                                share_of_associates_cr=3199.5, regulatory_deferral_cr=924.0,
                                discontinued_pat_cr=0.0, pat_owners_cr=3336.4,
                                pat_minority_cr=473.3)])
    s = checks.run()
    got = {c["id"]: c for c in s["checks"]}
    assert got["pat_reconciles"]["tested"] == 1 and got["pat_split"]["tested"] == 1
    assert s["failures"] == 0


def test_a_pat_its_own_split_contradicts_is_caught(env):
    """Aarti Q4 FY21: PAT filed 692.3; owners 136.1 + minority 3.2 = 139.3."""
    store, checks = env
    store.upsert("income", [_q("AARTI", "2021-03-31", 1209, 692.3, pbt_cr=726.0, tax_cr=33.7,
                               pat_continuing_cr=692.3, pat_owners_cr=136.1,
                               pat_minority_cr=3.2)])
    checks.run()
    (f,) = _by(checks, "pat_split")
    assert f["severity"] == "major" and f["expected"] == pytest.approx(139.3)


def test_unit_errors_are_told_apart_from_splits_and_from_bad_eps(env):
    store, checks = env
    rows = [_q("CO", e, 250, 50, 10) for e in
            ("2020-06-30", "2020-09-30", "2020-12-31", "2021-03-31", "2021-06-30")]
    rows[2].update(revenue_cr=2.5, pat_cr=0.5)            # money /100, EPS right
    rows[4].update(eps_basic=0.1)                         # EPS /100, money right
    split = [_q("SPLIT", e, 250, 50, eps) for e, eps in
             (("2020-06-30", 10), ("2020-09-30", 10), ("2020-12-31", 1),
              ("2021-03-31", 1), ("2021-06-30", 1))]      # a 1:10 split
    store.upsert("income", rows + split)
    checks.run()
    got = {f["period_end"]: f["note"] for f in _by(checks, "unit_scale")}
    assert set(got) == {"2020-12-31", "2021-06-30"}
    assert "money figures in this filing are in the wrong unit" in got["2020-12-31"]
    assert "EPS that was filed in the wrong unit" in got["2021-06-30"]


def test_the_balance_sheet_and_cash_flow_identities(env):
    store, checks = env
    store.upsert("balance", [
        {"symbol": "B", "company": "B", "basis": "consolidated", "label": "Mar 2026",
         "period_end": "2026-03-31", "filed_at": "x", "total_assets_cr": 100.0,
         "total_equity_and_liabilities_cr": 100.0},
        {"symbol": "B", "company": "B", "basis": "consolidated", "label": "Sep 2025",
         "period_end": "2025-09-30", "filed_at": "x", "total_assets_cr": 100.0,
         "total_equity_and_liabilities_cr": 90.0}])
    store.upsert("cashflow", [
        {"symbol": "B", "company": "B", "basis": "consolidated", "label": "FY26",
         "period_from": "2025-04-01", "period_end": "2026-03-31", "months": 12,
         "filed_at": "x", "cfo_cr": 500.0, "cfi_cr": -300.0, "cff_cr": -150.0,
         "fx_effect_on_cash_cr": 2.0, "net_change_in_cash_cr": 52.0}])
    s = checks.run()
    assert [(f["check_id"], f["period_end"]) for f in checks.failures(limit=0)] == \
        [("balance_sheet_balances", "2025-09-30")]
    assert {c["id"]: c["tested"] for c in s["checks"]}["cash_flow_sums"] == 1


def test_yahoo_in_dollars_is_skipped_and_a_disagreement_is_only_a_warning(env):
    store, checks = env
    store.upsert("income", [_fy("INFY", "2026-03-31", 178650.0, 29474.0),
                            _fy("OTHER", "2026-03-31", 1000.0, 100.0)])
    store.record_yf("INFY", "income", "annual",
                    {("2026-03-31", "Total Revenue"): 2015.8e7,
                     ("2026-03-31", "Net Income Common Stockholders"): 331.3e7})
    store.record_yf("OTHER", "income", "annual",
                    {("2026-03-31", "Total Revenue"): 1200e7})
    s = checks.run()
    assert s["yahoo_in_dollars"] == ["INFY"]
    (f,) = checks.failures(limit=0)
    assert (f["symbol"], f["check_id"], f["severity"]) == ("OTHER", "yahoo_revenue", "warning")
    assert s["identity_pass_pct"] == 100.0


def test_a_new_run_replaces_the_last_ones_failures(env):
    store, checks = env
    store.upsert("income", _year("X", [100, 100, 100, 100], 900))
    checks.run()
    assert len(checks.failures(limit=0)) == 1
    store.upsert("income", [_fy("X", "2022-03-31", 400)])
    checks.run()
    assert checks.failures(limit=0) == []
