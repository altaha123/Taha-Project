"""
One company's fundamentals, as the pick lists read them (fund_snapshot.py).

The live scan and the point-in-time lab both build every figure the three
fundamental lists rank on here, so a mistake here is a mistake on the page
and in its tested record at once. What is pinned: a figure a company has not
filed is None and never 0; one basis, never both; a stale quarter is not
read as this one; trailing figures are four quarters in a row; lenders are
not judged as manufacturers; a test whose inputs were not filed is not
counted as failed.

The builders at the top are also what the scan's tests seed a store with.
"""
import datetime as dt

import pytest

import fund_snapshot as FS

SHARES_CR = 10.0                     # crore shares: EPS is profit over this
QUARTER_ENDS = ["2026-09-30", "2026-06-30", "2026-03-31", "2025-12-31",
                "2025-09-30", "2025-06-30", "2025-03-31", "2024-12-31"]
YEAR_ENDS = ["2026-03-31", "2025-03-31", "2024-03-31", "2023-03-31"]
ASOF = dt.date(2026, 11, 20)


def _filed(end, days=40):
    return (dt.date.fromisoformat(end) + dt.timedelta(days=days)).isoformat() + " 18:00:00"


def quarters(sym="ACME", growth=0.15, margin=0.12, opm=18.0, opm_step=0.5, basis="consolidated",
             ends=QUARTER_ENDS, **latest):
    """Eight quarters, newest first, sales growing `growth` a year, each one's
    year-on-year growth filled in as the store's recompute_yoy does.
    `latest` overrides lines of the newest quarter."""
    n = len(ends)
    rows = []
    for k, end in enumerate(ends):
        t = n - 1 - k                                   # 0 for the oldest
        rev = 100.0 * (1 + growth) ** (t / 4)
        m = opm + opm_step * t
        pat = rev * margin
        rows.append({"symbol": sym, "company": sym.title(), "basis": basis, "freq": "quarterly",
                     "label": f"Q{k}", "period_end": end, "months": 3, "filed_at": _filed(end),
                     "revenue_cr": round(rev, 4), "pat_cr": round(pat, 4), "eps_basic": round(pat / SHARES_CR, 4),
                     "opm_pct": round(m, 4), "ebitda_cr": round(rev * m / 100, 4), "exceptional_cr": 0.0,
                     "pbt_cr": round(pat / 0.75, 4), "other_income_cr": 1.0,
                     "other_income_share_pct": round(100.0 / (pat / 0.75), 4), "finance_cost_cr": 1.0})
    for k, r in enumerate(rows):
        ago = rows[k + 4] if k + 4 < n else None
        for line in ("revenue", "pat", "ebitda"):
            r[f"{line}_yoy_pct"] = (round((r[f"{line}_cr"] / ago[f"{line}_cr"] - 1) * 100, 4)
                                    if ago else None)
    rows[0].update(latest)
    return rows


def annuals(sym="ACME", growth=0.15, basis="consolidated", ends=YEAR_ENDS):
    rows = []
    for k, end in enumerate(ends):
        rev = 400.0 / (1 + growth) ** k
        rows.append({"symbol": sym, "company": sym.title(), "basis": basis, "freq": "annual",
                     "label": f"FY{26 - k}", "period_end": end, "months": 12, "filed_at": _filed(end, 50),
                     "revenue_cr": round(rev, 4), "pat_cr": round(rev * 0.12, 4), "opm_pct": 19.0 - k,
                     "pbt_cr": round(rev * 0.16, 4), "finance_cost_cr": 4.0, "interest_cover_x": 20.0})
    return rows


def cashflows(sym="ACME", basis="consolidated", fcf=(40.0, 35.0, 30.0)):
    return [{"symbol": sym, "company": sym.title(), "basis": basis, "label": f"FY{26 - k}",
             "period_end": YEAR_ENDS[k], "months": 12, "filed_at": _filed(YEAR_ENDS[k], 50),
             "cfo_cr": 60.0 - 5 * k, "capex_cr": 60.0 - 5 * k - f, "fcf_cr": f} for k, f in enumerate(fcf)]


def balances(sym="ACME", basis="consolidated", **latest):
    rows = [{"symbol": sym, "company": sym.title(), "basis": basis, "label": "Mar 2026",
             "period_end": YEAR_ENDS[0], "filed_at": _filed(YEAR_ENDS[0], 50), "total_assets_cr": 500.0,
             "total_equity_cr": 300.0, "equity_capital_cr": 10.0, "total_borrowings_cr": 40.0,
             "borrowings_non_current_cr": 30.0, "cash_and_equivalents_cr": 50.0, "current_investments_cr": 20.0,
             "other_bank_balances_cr": 5.0, "net_debt_cr": -30.0, "debt_equity_x": round(40 / 300, 4),
             "current_ratio_x": 1.8, "current_assets_cr": 270.0, "current_liabilities_cr": 150.0,
             "total_liabilities_cr": 200.0},
            {"symbol": sym, "company": sym.title(), "basis": basis, "label": "Mar 2025",
             "period_end": YEAR_ENDS[1], "filed_at": _filed(YEAR_ENDS[1], 50), "total_assets_cr": 450.0,
             "total_equity_cr": 260.0, "equity_capital_cr": 10.0, "total_borrowings_cr": 50.0,
             "borrowings_non_current_cr": 40.0, "cash_and_equivalents_cr": 40.0, "current_investments_cr": 10.0,
             "net_debt_cr": 0.0, "debt_equity_x": round(50 / 260, 4), "current_ratio_x": 1.6,
             "current_assets_cr": 240.0, "current_liabilities_cr": 150.0, "total_liabilities_cr": 190.0}]
    rows[0].update(latest)
    return rows


def company(sym="ACME", **kw):
    """Every row of one healthy company, keyed by the table it belongs to."""
    return {"quarterly": quarters(sym, **kw), "annual": annuals(sym), "cashflow": cashflows(sym),
            "balance": balances(sym)}


def build(rows=None, sector=None, asof=ASOF):
    rows = rows or company()
    return FS.build(rows["quarterly"], rows["annual"], rows["cashflow"], rows["balance"], sector=sector, asof=asof)


# --- what is read -----------------------------------------------------------------

def test_a_healthy_company_reads_as_its_filings_say():
    s = build()
    assert s["basis"] == "consolidated" and s["is_financial"] is False
    assert s["quarter"] == "Q0" and s["quarter_end"] == "2026-09-30" and s["filed_at"] == _filed("2026-09-30")
    assert s["revenue_yoy_pct"] == pytest.approx(15.0, abs=0.01)
    assert s["opm_yoy_chg"] == pytest.approx(4 * 0.5, abs=0.01)          # half a point a quarter
    assert s["prev_revenue_yoy_pct"] == pytest.approx(15.0, abs=0.01) and s["opm_expanding_2q"] is True
    assert s["earnings_quality_ok"] is True and s["core_ebitda_cr"] == s["ebitda_cr"]
    assert s["eps_ttm"] == pytest.approx(sum(r["eps_basic"] for r in quarters()[:4]), abs=0.01)
    assert s["revenue_ttm_yoy_pct"] == pytest.approx(15.0, abs=0.05)
    assert s["shares_cr"] == pytest.approx(SHARES_CR, rel=1e-3)
    assert s["rev_cagr_3y"] == pytest.approx(15.0, abs=0.01) and s["pat_cagr_3y"] == pytest.approx(15.0, abs=0.01)
    assert s["opm_trend_2y"] == pytest.approx(2.0)
    assert s["cfo_cr"] == 60.0 and s["fcf_cr"] == 40.0 and s["fcf_pos_years_3y"] == 3 and s["fcf_3y_cr"] == 105.0
    assert s["cfo_to_pat"] == pytest.approx(60.0 / 48.0, abs=0.01)
    assert s["debt_equity_x"] == pytest.approx(0.13, abs=0.01) and s["liquid_cr"] == 75.0
    assert s["roe_pct"] == pytest.approx(48.0 / 280.0 * 100, abs=0.01)    # on the average of two years' equity
    assert s["roce_pct"] == pytest.approx((64.0 + 4.0) / 340.0 * 100, abs=0.01)
    assert 0 <= s["f_score"] <= 9 and s["f_score_tests"] == 9


def test_nothing_filed_is_nothing_and_a_missing_line_is_none_never_zero():
    assert FS.build() == {} and FS.build([], [], [], []) == {}
    rows = company()
    for r in rows["quarterly"]:
        r.pop("other_income_share_pct")
        r.pop("exceptional_cr")
    del rows["balance"][0]["debt_equity_x"]
    s = build(rows)
    assert s["other_income_share_pct"] is None and s["exceptional_cr"] is None and s["debt_equity_x"] is None
    # A line that was not filed is not held against the profit.
    assert s["earnings_quality_ok"] is True
    only_quarters = FS.build(quarters(), asof=ASOF)
    assert only_quarters["revenue_yoy_pct"] is not None
    for k in ("roe_pct", "roce_pct", "cfo_to_pat", "f_score", "debt_equity_x", "rev_cagr_3y"):
        assert only_quarters.get(k) is None, k


def test_one_basis_and_never_both():
    rows = company()
    standalone = company(growth=0.60)
    for table in rows:
        for r in standalone[table]:
            r["basis"] = "standalone"
        rows[table] = rows[table] + standalone[table]
    s = build(rows)
    assert s["basis"] == "consolidated" and s["revenue_yoy_pct"] == pytest.approx(15.0, abs=0.01)
    only = {t: [r for r in v if r["basis"] == "standalone"] for t, v in rows.items()}
    assert build(only)["basis"] == "standalone"


def test_a_revision_is_read_and_the_original_is_not():
    rows = company()
    revised = dict(rows["quarterly"][0], pat_cr=1.0, filed_at=_filed("2026-09-30", 70))
    rows["quarterly"].append(revised)
    assert build(rows)["pat_cr"] == 1.0


def test_a_quarter_past_five_months_is_not_this_quarter():
    s = build(asof=dt.date(2026, 9, 30) + dt.timedelta(days=FS.QUARTER_FRESH_DAYS + 1))
    assert s["quarter_stale"] is True and s.get("revenue_yoy_pct") is None and s.get("pat_cr") is None
    fresh = build(asof=dt.date(2026, 9, 30) + dt.timedelta(days=FS.QUARTER_FRESH_DAYS))
    assert "quarter_stale" not in fresh and fresh["pat_cr"] is not None


def test_the_trailing_year_is_four_quarters_in_a_row_or_nothing():
    rows = company()
    del rows["quarterly"][2]                       # the March quarter is missing
    s = build(rows)
    assert s.get("eps_ttm") is None and s.get("revenue_ttm_cr") is None
    assert FS.with_price(s, 100.0)["pe"] is None
    assert s["revenue_yoy_4q"] is None, "growth in each of four quarters is never read across a gap"


# --- earnings quality ----------------------------------------------------------------

def test_a_real_profit_and_four_that_are_not():
    q = {"pat_cr": 50.0, "core_ebitda_cr": 80.0, "other_income_share_pct": 10.0, "exceptional_cr": 0.0, "pbt_cr": 70.0}
    assert FS.earnings_quality(q) is True
    assert FS.earnings_quality(dict(q, pat_cr=-1.0)) is False
    assert FS.earnings_quality(dict(q, core_ebitda_cr=-5.0)) is False
    assert FS.earnings_quality(dict(q, other_income_share_pct=40.0)) is False
    assert FS.earnings_quality(dict(q, exceptional_cr=25.0)) is False         # 36% of PBT
    assert FS.earnings_quality(dict(q, pat_cr=None)) is None
    # A lender's fees and treasury income are its business.
    assert FS.earnings_quality(dict(q, other_income_share_pct=60.0, core_ebitda_cr=None), fin=True) is True


def test_an_exceptional_gain_is_taken_out_of_the_business_ebitda():
    s = FS.build(quarters(exceptional_cr=10.0), asof=ASOF)
    assert s["core_ebitda_cr"] == pytest.approx(s["ebitda_cr"] - 10.0)


# --- lenders ---------------------------------------------------------------------------

def test_a_lender_is_known_by_its_industry_or_its_own_lines():
    assert FS.is_financial("Financial Services") is True
    assert FS.is_financial("Information Technology") is False
    assert FS.is_financial(None, {"operating_profit_pre_provision_cr": 10.0, "provisions_cr": 2.0}) is True
    assert FS.is_financial(None, None, {"deposits_cr": 300.0, "total_liabilities_cr": 1000.0}) is True
    s = build(sector="Financial Services")
    assert s["is_financial"] is True
    assert s.get("roce_pct") is None and s["f_score"] is None and s["f_score_tests"] is None
    assert s["roe_pct"] is not None
    assert FS.with_price(s, 100.0)["ev_ebitda"] is None


# --- valuation ---------------------------------------------------------------------------

def test_valuation_is_worked_out_at_the_price_and_changes_nothing_else():
    s = build()
    v = FS.with_price(s, 120.0)
    assert v["market_cap_cr"] == pytest.approx(120.0 * SHARES_CR, abs=0.2)
    assert v["pe"] == pytest.approx(120.0 / s["eps_ttm"], abs=0.1)
    assert v["peg"] == pytest.approx(v["pe"] / s["pat_cagr_3y"], abs=0.01)
    assert v["ev_ebitda"] == pytest.approx((v["market_cap_cr"] + s["net_debt_cr"]) / s["ebitda_ttm_cr"], abs=0.1)
    assert "pe" not in s, "with_price returns a new dict"
    assert FS.valuation(s, None) == {"market_cap_cr": None, "pe": None, "peg": None, "ev_ebitda": None}
    loss = FS.build(quarters(margin=-0.05), asof=ASOF)
    assert FS.with_price(loss, 120.0)["pe"] is None, "a P/E on a loss means nothing"


# --- the F-score -------------------------------------------------------------------------

def test_a_test_whose_lines_were_not_filed_is_not_counted_as_failed():
    """
    About one balance sheet in ten files no non-current borrowings line, and
    about as many no current ratio. Scoring those tests as failed took a
    point off a debt-free company for a line it never had to file, which is
    enough to put it under the long-term list's floor of five. The leverage
    test reads total borrowings when the split is not filed, the liquidity
    test current assets over current liabilities, and a test whose figures
    are all missing is not made.
    """
    a0, a1 = annuals()[0], annuals()[1]
    b0, b1 = balances()
    cfs = cashflows()
    full = FS.piotroski_tests(a0, a1, b0, b1, cfs)
    assert full[1] == 9
    # No non-current split, but total borrowings on both sheets: still made.
    nosplit = [dict(b, borrowings_non_current_cr=None) for b in (b0, b1)]
    assert FS.piotroski_tests(a0, a1, *nosplit, cfs)[1] == 9
    # Debt-free and saying so only in the total: the leverage point is earned.
    free = [dict(b, borrowings_non_current_cr=None, total_borrowings_cr=0.0) for b in (b0, b1)]
    score, tests = FS.piotroski_tests(a0, a1, *free, cfs)
    worse = [dict(b, borrowings_non_current_cr=None, total_borrowings_cr=None) for b in (b0, b1)]
    assert tests == 9 and FS.piotroski_tests(a0, a1, *worse, cfs) == (score - 1, 8)
    # No current ratio, but the two lines it is made of.
    nocr = [dict(b, current_ratio_x=None) for b in (b0, b1)]
    assert FS.piotroski_tests(a0, a1, *nocr, cfs) == full
    # Half a score is no score.
    assert FS.piotroski_tests(a0, None, b0, b1, cfs) is None and FS.piotroski(a0, a1, b0, None, cfs) is None
    assert FS.piotroski(a0, a1, b0, b1, cfs) == full[0]


# --- figures the review found wrong (December 2026) ---------------------------

def test_trailing_eps_is_on_the_latest_share_count_across_a_split():
    """A 1:10 split between quarters: the quarter before it was filed on a
    tenth of the shares. Its EPS is restated, so the P/E is the true one."""
    q = quarters()
    q[3]["eps_basic"] = round(q[3]["pat_cr"] / (SHARES_CR / 10), 4)      # filed before the split
    s = FS.build(q, annuals(), cashflows(), balances(), asof=ASOF)
    pat_ttm = sum(r["pat_cr"] for r in q[:4])
    assert s["eps_ttm"] == pytest.approx(pat_ttm / SHARES_CR, rel=1e-3)
    assert FS.valuation(s, 120.0)["pe"] == pytest.approx(120.0 / (pat_ttm / SHARES_CR), abs=0.1)
    # Ordinary quarters are summed as filed.
    plain = FS.build(quarters(), annuals(), cashflows(), balances(), asof=ASOF)
    assert plain["eps_ttm"] == pytest.approx(sum(r["eps_basic"] for r in quarters()[:4]), abs=0.01)


def test_margins_leave_one_off_items_out():
    """A one-off gain in the year-ago quarter made its stored margin huge:
    the change is read on the business's own EBITDA."""
    q = quarters()
    ago = q[4]
    ago["exceptional_cr"] = 200.0
    ago["ebitda_cr"] = round(ago["ebitda_cr"] + 200.0, 4)
    ago["opm_pct"] = round(ago["ebitda_cr"] / ago["revenue_cr"] * 100, 4)
    s = FS.build(q, annuals(), cashflows(), balances(), asof=ASOF)
    core_now = q[0]["ebitda_cr"] / q[0]["revenue_cr"] * 100
    core_ago = (ago["ebitda_cr"] - 200.0) / ago["revenue_cr"] * 100
    assert s["opm_yoy_chg"] == pytest.approx(core_now - core_ago, abs=0.01)
    assert s["opm_yoy_chg"] > 0, "a one-off a year ago read as a margin collapse"
    # A one-off gain now does not lift the margin either.
    q2 = quarters(exceptional_cr=50.0)
    q2[0]["ebitda_cr"] = round(q2[0]["ebitda_cr"] + 50.0, 4)
    s2 = FS.build(q2, annuals(), cashflows(), balances(), asof=ASOF)
    assert s2["opm_pct"] == pytest.approx(core_now, abs=0.01)


def test_a_lender_has_no_operating_margin():
    s = FS.build(quarters(), annuals(), cashflows(), balances(), sector="Financial Services", asof=ASOF)
    for k in ("opm_pct", "opm_yoy_chg", "prev_opm_yoy_chg", "opm_expanding_2q", "opm_annual_pct", "opm_trend_2y"):
        assert s.get(k) is None, k
    assert s["revenue_yoy_pct"] is not None and s["roe_pct"] is not None


def test_a_balance_sheet_mostly_loans_is_a_lenders():
    """An NBFC filing Ind AS results has no bank-format lines and no deposits;
    its loans are most of what it owns."""
    nbfc = balances(loans_cr=420.0)
    assert FS.build(quarters(), annuals(), cashflows(), nbfc, asof=ASOF)["is_financial"] is True
    maker = balances(loans_cr=20.0)
    assert FS.build(quarters(), annuals(), cashflows(), maker, asof=ASOF)["is_financial"] is False


def test_an_enterprise_value_needs_the_net_debt():
    s = FS.build(quarters(), annuals(), cashflows(), balances(net_debt_cr=None), asof=ASOF)
    assert FS.valuation(s, 120.0)["ev_ebitda"] is None, "an unknown debt was read as none"
    known = FS.build(quarters(), annuals(), cashflows(), balances(), asof=ASOF)
    assert FS.valuation(known, 120.0)["ev_ebitda"] is not None
