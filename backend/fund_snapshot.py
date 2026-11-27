"""
Altaha Screener — one company's fundamentals, as the pick lists read them

WHAT THIS IS
------------
The Ideas lists used to read three numbers from a company's filings: its
latest quarter's profit growth, its revenue growth and its profit. This
reads the rest of what the site already stores — eight years of quarterly
P&L, the annual P&L, six years of cash flows and four of balance sheets —
and turns one company's rows into one dictionary of the figures the lists
are ranked and screened on.

It is written once and used twice:

  · live, by scan.fundamental_snapshot(), from the fundamentals tables, and
  · in research/fundamental_ideas_lab.py, from the same tables exported to
    CSV, with each row admitted only on the sessions after it reached the
    exchange.

The test of a recipe and the recipe the site runs therefore read the same
figures, worked out by the same code. Nothing here makes a network call.

WHAT A MISSING FIGURE MEANS
--------------------------
Not every company files everything: banks have no operating margin, balance
sheets are filed in XBRL only from September 2022, cash flows from 2020-21.
A figure that cannot be worked out is None — never 0 — and the lists treat
None as "unknown": a ranking reads it as the middle of the field, and a
safety check that needs it is skipped rather than failed.

THE BASIS
---------
A company files standalone and consolidated results for the same period, and
the two are not comparable. Every figure here comes from one basis: the
consolidated one where the company files it, as fundamentals_store does.

FINANCIAL COMPANIES
-------------------
Banks, NBFCs and insurers borrow and lend for a living. Their debt-to-equity,
operating margin, free cash flow and net cash say nothing about the quality
of the business, and a screen that reads them as it reads a manufacturer's
throws out every good bank. `is_financial` marks them, from their industry
("Financial Services") or, failing that, from their own filings: the
bank-format lines, deposits, or a balance sheet that is mostly loans. A
financial company's snapshot carries no operating margin at all, so nothing
downstream can rank or print one, and the lists judge it on return on
equity, profit growth and valuation instead.

OPERATING MARGIN
----------------
The stored EBITDA, and the margin stored beside it, are worked out from
profit after exceptional items, so a one-off gain or loss sits inside them.
Every margin here is the business's own: EBITDA without exceptional items
over revenue (_core_opm).

PER-SHARE FIGURES
-----------------
Trailing EPS is the four quarters' EPS added up as each was filed. For up to
three quarters after a split or a bonus, the older quarters are on the old
share count and the P/E reads low; a quarter whose filing put the year to
date's EPS in its row does the same. The tables hold no split dates to
restate them by, and profit over EPS is no share count to infer one from:
the profit is the whole group's, minority interests included, and the EPS
the owners' alone, so the ratio moves by a third or more with no share
issued. Restating on it was tried and moved the P/E of more companies with
no split than with one (research/IDEAS-STUDY.md, "What the review changed").

Standard library only.
"""

import datetime as dt

# A quarter's numbers stand for this long after the period ended. The scan's
# "did profit grow" read used five months; so does this.
QUARTER_FRESH_DAYS = 150
# An annual figure, a cash flow or a balance sheet older than this describes
# a company that has stopped filing, not this one.
ANNUAL_FRESH_DAYS = 550
# Four quarter-ends in a row are nine months apart, give or take the length
# of the months between them (fundamentals_store.trailing_year).
YEAR_SPAN_DAYS = (265, 285)
# Two annual periods a year apart, and four three years apart.
ONE_YEAR_DAYS = (340, 390)
THREE_YEAR_DAYS = (1060, 1130)
# Two quarter-ends one after the other (a quarter is 90 days, give or take).
QUARTER_APART_DAYS = (80, 100)
# How many quarters in a row "growing in each of the last four quarters" reads.
RUN_QUARTERS = 4

# Earnings quality: what a real profit looks like.
OTHER_INCOME_MAX_PCT = 35.0      # other income as a share of profit before tax
EXCEPTIONAL_MAX_SHARE = 0.30     # an exceptional gain larger than this share of PBT drives the profit

FINANCIAL_SECTORS = {"financial services"}
# A balance sheet whose loans are more than this share of its assets is a
# lender's, whatever its industry says: an NBFC that files Ind AS results has
# no bank-format lines and takes no deposits.
LENDER_LOANS_SHARE = 0.5

QUADRANTS = ("Leading", "Improving", "Weakening", "Lagging")


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _f(v):
    """A finite float, or None. Never 0 for a missing figure."""
    if v is None or isinstance(v, bool):
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x and x not in (float("inf"), float("-inf")) else None


def _day(v):
    if not v:
        return None
    if isinstance(v, dt.datetime):
        return v.date()
    if isinstance(v, dt.date):
        return v
    s = str(v).strip()
    try:
        return dt.date.fromisoformat(s[:10])
    except ValueError:
        return None


def _apart(a, b, span):
    da, db = _day(a), _day(b)
    if not da or not db:
        return False
    return span[0] <= abs((da - db).days) <= span[1]


def _r(v, nd=2):
    return None if v is None else round(v, nd)


def _pct(now, before):
    """Percent change, only between two positive figures."""
    now, before = _f(now), _f(before)
    if now is None or before is None or before <= 0 or now <= 0:
        return None
    return (now / before - 1.0) * 100.0


def _cagr(now, before, years):
    now, before = _f(now), _f(before)
    if now is None or before is None or now <= 0 or before <= 0 or years <= 0:
        return None
    return ((now / before) ** (1.0 / years) - 1.0) * 100.0


def basis_of(rows):
    """Consolidated where the company files it, else standalone (as
    fundamentals_store._latest_basis)."""
    held = {r.get("basis") for r in rows or ()}
    return "consolidated" if "consolidated" in held else ("standalone" if "standalone" in held else None)


def _one_basis(rows, basis):
    """Rows of one basis, newest period first; one row per period (the
    latest filing for it)."""
    seen, out = set(), []
    for r in sorted((r for r in rows or () if r.get("basis") == basis),
                    key=lambda r: (str(r.get("period_end") or ""), str(r.get("filed_at") or "")),
                    reverse=True):
        key = (str(r.get("period_end") or "")[:10], int(_f(r.get("months")) or 0))
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def is_financial(sector=None, quarter=None, balance=None):
    """A bank, NBFC or insurer: by its industry, else by what a lender's own
    filing carries (pre-provision operating profit and provisions, deposits,
    or loans that are most of its assets)."""
    if sector and str(sector).strip().lower() in FINANCIAL_SECTORS:
        return True
    q = quarter or {}
    if _f(q.get("operating_profit_pre_provision_cr")) is not None and _f(q.get("provisions_cr")) is not None:
        return True
    b = balance or {}
    deposits, total = _f(b.get("deposits_cr")), _f(b.get("total_liabilities_cr"))
    if deposits is not None and total and deposits > 0.2 * total:
        return True
    loans, assets = _f(b.get("loans_cr")), _f(b.get("total_assets_cr"))
    if loans is not None and assets and assets > 0 and loans > LENDER_LOANS_SHARE * assets:
        return True
    return False


# ---------------------------------------------------------------------------
# The quarters
# ---------------------------------------------------------------------------

def _year_ago(rows, row):
    """The same quarter a year earlier, or None."""
    for r in rows:
        if _apart(row.get("period_end"), r.get("period_end"), ONE_YEAR_DAYS):
            return r
    return None


def _core_ebitda(row):
    """
    EBITDA without exceptional items. The stored EBITDA is worked out from
    profit after exceptional items (pbt + finance cost + depreciation - other
    income), so a one-off gain sits inside it; the business's own EBITDA
    leaves it out. The stored figure when no exceptional line was filed, and
    None when there is no EBITDA at all.
    """
    ebitda, exc = _f((row or {}).get("ebitda_cr")), _f((row or {}).get("exceptional_cr"))
    if ebitda is None:
        return None
    return ebitda - exc if exc is not None else ebitda


def _core_opm(row):
    """The operating margin without exceptional items, in percent: core
    EBITDA over revenue. The stored margin where there is no EBITDA line to
    strip, and None where neither can be read."""
    core, rev = _core_ebitda(row), _f((row or {}).get("revenue_cr"))
    if core is not None and rev is not None and rev > 0:
        return core / rev * 100.0
    return _f((row or {}).get("opm_pct"))


def _margin_change(now, before):
    """Points the core margin moved between two periods, or None."""
    a, b = _core_opm(now), _core_opm(before)
    return None if a is None or b is None else a - b


def _in_a_row(rows):
    """True when each row's quarter ended one quarter after the next one's."""
    return all(_apart(a.get("period_end"), b.get("period_end"), QUARTER_APART_DAYS)
               for a, b in zip(rows, rows[1:]))


def _ttm(rows, start):
    """Sum of four consecutive quarters from rows[start], or None per line."""
    four = rows[start:start + 4]
    if len(four) < 4 or not _apart(four[0].get("period_end"), four[3].get("period_end"), YEAR_SPAN_DAYS):
        return None

    def total(key):
        vals = [_f(r.get(key)) for r in four]
        return None if any(v is None for v in vals) else sum(vals)
    cores = [_core_ebitda(r) for r in four]
    return {"revenue": total("revenue_cr"), "pat": total("pat_cr"),
            "ebitda": total("ebitda_cr"),
            "core_ebitda": None if any(v is None for v in cores) else sum(cores),
            "eps": total("eps_basic"), "through": four[0].get("period_end")}


def _quarters(rows, asof, fin):
    out = {}
    if not rows:
        return out
    top = rows[0]
    end = _day(top.get("period_end"))
    if asof and end and (asof - end).days > QUARTER_FRESH_DAYS:
        out["quarter_stale"] = True
        return out
    out["quarter"] = top.get("label") or str(top.get("period_end") or "")[:10]
    out["quarter_end"] = str(top.get("period_end") or "")[:10] or None
    out["filed_at"] = top.get("filed_at")
    for k in ("revenue_yoy_pct", "ebitda_yoy_pct", "pat_yoy_pct", "opm_pct",
              "other_income_share_pct", "interest_cover_x"):
        out[k] = _r(_f(top.get(k)))
    for k in ("revenue_cr", "pat_cr", "ebitda_cr", "exceptional_cr", "pbt_cr", "other_income_cr"):
        out[k] = _r(_f(top.get(k)))
    # The stored EBITDA includes exceptional items; the business's own leaves
    # them out (_core_ebitda), and so does every margin here (_core_opm).
    out["core_ebitda_cr"] = _r(_core_ebitda(top))
    out["opm_pct"] = _r(_core_opm(top))
    ago = _year_ago(rows[1:], top)
    out["opm_yoy_chg"] = _r(_margin_change(top, ago)) if ago is not None else None
    out["pat_yoy_cr_prev"] = _r(_f((ago or {}).get("pat_cr")))
    # The year-ago quarter's revenue and EBITDA without exceptional items, as
    # figures: a growth rate is only worked out between two positive numbers,
    # so an EBITDA that rose from a loss has none, yet it did rise.
    out["revenue_yoy_cr_prev"] = _r(_f((ago or {}).get("revenue_cr")))
    out["core_ebitda_yoy_cr_prev"] = _r(_core_ebitda(ago)) if ago is not None else None
    # Revenue growth in each of the latest four quarters, newest first, and
    # only where the four are quarters in a row: "up in each of the last four
    # quarters" is never read across a gap. An entry is None where that
    # quarter's growth is unknown.
    run = rows[:RUN_QUARTERS]
    out["revenue_yoy_4q"] = ([_r(_f(r.get("revenue_yoy_pct"))) for r in run]
                             if len(run) == RUN_QUARTERS and _in_a_row(run) else None)
    # The quarter before, for acceleration: is growth speeding up?
    prev = rows[1] if len(rows) > 1 and _in_a_row(rows[:2]) else None
    out["prev_revenue_yoy_pct"] = _r(_f((prev or {}).get("revenue_yoy_pct")))
    out["prev_pat_yoy_pct"] = _r(_f((prev or {}).get("pat_yoy_pct")))
    prev_chg = None
    if prev is not None:
        prev_ago = _year_ago(rows[2:], prev)
        if prev_ago is not None:
            prev_chg = _margin_change(prev, prev_ago)
    out["prev_opm_yoy_chg"] = _r(prev_chg)
    out["opm_expanding_2q"] = (None if out["opm_yoy_chg"] is None or prev_chg is None
                               else bool(out["opm_yoy_chg"] > 0 and prev_chg > 0))
    if fin:
        # A lender has no operating margin to read (FINANCIAL COMPANIES).
        for k in ("opm_pct", "opm_yoy_chg", "prev_opm_yoy_chg", "opm_expanding_2q"):
            out[k] = None
    out["earnings_quality_ok"] = earnings_quality(out, fin)
    # The last four quarters, and the four before them.
    t0, t1 = _ttm(rows, 0), _ttm(rows, 4)
    if t0:
        out["revenue_ttm_cr"] = _r(t0["revenue"])
        out["pat_ttm_cr"] = _r(t0["pat"])
        out["ebitda_ttm_cr"] = _r(t0["ebitda"])
        out["core_ebitda_ttm_cr"] = _r(t0["core_ebitda"])
        out["eps_ttm"] = _r(t0["eps"])
        if t1 and _apart(t0["through"], t1["through"], ONE_YEAR_DAYS):
            out["revenue_ttm_yoy_pct"] = _r(_pct(t0["revenue"], t1["revenue"]))
            out["pat_ttm_yoy_pct"] = _r(_pct(t0["pat"], t1["pat"]))
    # Shares outstanding, from the latest quarter's profit and its EPS: what
    # turns a price into a market value without a feed that may not exist.
    for r in rows[:4]:
        pat, eps = _f(r.get("pat_cr")), _f(r.get("eps_basic"))
        if pat and eps and (pat > 0) == (eps > 0) and abs(eps) >= 0.01:
            out["shares_cr"] = abs(pat) / abs(eps)          # crore shares
            break
    return out


def earnings_quality(q, fin=False):
    """
    True when the latest quarter's profit is a real one: positive, made by
    the business (positive EBITDA, for a company that has one), not mostly
    other income and not carried by an exceptional gain. None when the profit
    itself is unknown; a missing other-income or exceptional figure is not
    held against it.
    """
    pat = _f(q.get("pat_cr"))
    if pat is None:
        return None
    if pat <= 0:
        return False
    if not fin:
        ebitda = _f(q.get("core_ebitda_cr")) if q.get("core_ebitda_cr") is not None else _f(q.get("ebitda_cr"))
        if ebitda is not None and ebitda <= 0:
            return False
        # A lender's fees and treasury income are its business, not a one-off,
        # so this test is for everyone else.
        oi = _f(q.get("other_income_share_pct"))
        if oi is not None and oi > OTHER_INCOME_MAX_PCT:
            return False
    exc, pbt = _f(q.get("exceptional_cr")), _f(q.get("pbt_cr"))
    if exc is not None and pbt and pbt > 0 and exc > EXCEPTIONAL_MAX_SHARE * pbt:
        return False
    return True


# ---------------------------------------------------------------------------
# The year: growth, cash, the balance sheet
# ---------------------------------------------------------------------------

def _years(rows):
    """Full-year rows (months 12 where known), newest first."""
    return [r for r in rows if int(_f(r.get("months")) or 12) == 12]


def _balance_at(sheets, end):
    """The balance sheet at a year's end (same date, within a fortnight)."""
    d = _day(end)
    for b in sheets:
        e = _day(b.get("period_end"))
        if d and e and abs((d - e).days) <= 15:
            return b
    return None


def _annual(ann, cfs, sheets, asof, fin):
    out = {}
    a = _years(ann)
    if a and asof and _day(a[0].get("period_end")) and \
            (asof - _day(a[0].get("period_end"))).days > ANNUAL_FRESH_DAYS:
        a = []
    if a:
        a0 = a[0]
        out["fy_end"] = str(a0.get("period_end") or "")[:10] or None
        out["pat_annual_cr"] = _r(_f(a0.get("pat_cr")))
        out["revenue_annual_cr"] = _r(_f(a0.get("revenue_cr")))
        out["opm_annual_pct"] = None if fin else _r(_core_opm(a0))
        a3 = next((r for r in a[1:] if _apart(a0.get("period_end"), r.get("period_end"), THREE_YEAR_DAYS)), None)
        if a3 is not None:
            out["rev_cagr_3y"] = _r(_cagr(a0.get("revenue_cr"), a3.get("revenue_cr"), 3))
            out["pat_cagr_3y"] = _r(_cagr(a0.get("pat_cr"), a3.get("pat_cr"), 3))
        a1 = next((r for r in a[1:] if _apart(a0.get("period_end"), r.get("period_end"), ONE_YEAR_DAYS)), None)
        a2 = next((r for r in a[1:] if _apart(a0.get("period_end"), r.get("period_end"), (705, 760))), None)
        if a2 is not None and not fin:
            out["opm_trend_2y"] = _r(_margin_change(a0, a2))
        if _f(a0.get("interest_cover_x")) is not None:
            out["interest_cover_x"] = _r(_f(a0.get("interest_cover_x")))
    else:
        a0 = a1 = None

    # Cash flow: full years only.
    c = [r for r in _years(cfs)]
    if c and asof and _day(c[0].get("period_end")) and \
            (asof - _day(c[0].get("period_end"))).days > ANNUAL_FRESH_DAYS:
        c = []
    if c:
        c0 = c[0]
        out["cfo_cr"] = _r(_f(c0.get("cfo_cr")))
        out["fcf_cr"] = _r(_f(c0.get("fcf_cr")))
        # Three consecutive years, each a year apart.
        run = [c0]
        for r in c[1:]:
            if len(run) == 3:
                break
            if _apart(run[-1].get("period_end"), r.get("period_end"), ONE_YEAR_DAYS):
                run.append(r)
        fcfs = [_f(r.get("fcf_cr")) for r in run]
        out["fcf_years_known"] = sum(1 for v in fcfs if v is not None)
        out["fcf_pos_years_3y"] = (sum(1 for v in fcfs if v is not None and v > 0)
                                   if len(run) == 3 and all(v is not None for v in fcfs) else None)
        out["fcf_3y_cr"] = (_r(sum(fcfs)) if len(run) == 3 and all(v is not None for v in fcfs) else None)
        # Cash from operations against the same year's profit.
        same = a0 if (a0 is not None and _day(a0.get("period_end")) == _day(c0.get("period_end"))) else \
            next((r for r in _years(ann) if _day(r.get("period_end")) == _day(c0.get("period_end"))), None)
        pat = _f((same or {}).get("pat_cr"))
        cfo = _f(c0.get("cfo_cr"))
        out["cfo_to_pat"] = _r(cfo / pat) if (cfo is not None and pat and pat > 0) else None

    # The balance sheet.
    s = list(sheets)
    if s and asof and _day(s[0].get("period_end")) and \
            (asof - _day(s[0].get("period_end"))).days > ANNUAL_FRESH_DAYS:
        s = []
    if s:
        b0 = s[0]
        out["debt_equity_x"] = _r(_f(b0.get("debt_equity_x")))
        out["net_debt_cr"] = _r(_f(b0.get("net_debt_cr")))
        out["total_borrowings_cr"] = _r(_f(b0.get("total_borrowings_cr")))
        liquid = [_f(b0.get(k)) for k in ("cash_and_equivalents_cr", "other_bank_balances_cr",
                                          "current_investments_cr")]
        known = [v for v in liquid if v is not None]
        out["liquid_cr"] = _r(sum(known)) if known else None
        out["total_equity_cr"] = _r(_f(b0.get("total_equity_cr")))
    # Returns on capital, at the latest year's end.
    if a0 is not None and s:
        bs = _balance_at(s, a0.get("period_end"))
        if bs is not None:
            equity = _f(bs.get("total_equity_cr"))
            debt = _f(bs.get("total_borrowings_cr"))
            pat = _f(a0.get("pat_cr"))
            prior = _balance_at(s, (a1 or {}).get("period_end")) if a1 is not None else None
            eq_prior = _f((prior or {}).get("total_equity_cr"))
            avg_eq = (equity + eq_prior) / 2 if (equity and eq_prior and eq_prior > 0) else equity
            if pat is not None and avg_eq and avg_eq > 0:
                out["roe_pct"] = _r(pat / avg_eq * 100)
            if not fin:
                pbt, fin_cost = _f(a0.get("pbt_cr")), _f(a0.get("finance_cost_cr"))
                if pbt is not None and equity and equity > 0:
                    ebit = pbt + (fin_cost or 0.0) if fin_cost is not None else pbt
                    ce = equity + (debt if debt is not None else 0.0)
                    if ce > 0:
                        out["roce_pct"] = _r(ebit / ce * 100)
            # Piotroski's liquidity and leverage tests describe a manufacturer;
            # a lender's balance sheet is its borrowing, so it has no F-score.
            # `f_score_tests` says how many of the nine could be made.
            got = None if fin else piotroski_tests(a0, a1, bs, prior, cfs)
            out["f_score"], out["f_score_tests"] = (None, None) if got is None else got
    return out


def _leverage(b):
    """Long-term borrowings, or all borrowings where the sheet does not split
    them: about one sheet in ten files no non-current line, most of those
    with their total (often nil) on record."""
    v = _f(b.get("borrowings_non_current_cr"))
    return v if v is not None else _f(b.get("total_borrowings_cr"))


def _current_ratio(b):
    """The current ratio as filed, else current assets over current
    liabilities where both are on the sheet."""
    v = _f(b.get("current_ratio_x"))
    if v is not None:
        return v
    ca, cl = _f(b.get("current_assets_cr")), _f(b.get("current_liabilities_cr"))
    return ca / cl if (ca is not None and cl and cl > 0) else None


def piotroski_tests(a0, a1, b0, b1, cfs):
    """
    Piotroski's nine tests, from the company's own filings, as
    (points scored, tests that could be made): profit, cash flow, the change
    in returns, accruals, leverage, liquidity, share issuance, margin and
    asset turnover. A test whose figures are not filed is not made, rather
    than counted as failed. None unless both year-end balance sheets and both
    years' P&L are held, since half a score is no score.
    """
    if not (a0 and a1 and b0 and b1):
        return None
    ta0, ta1 = _f(b0.get("total_assets_cr")), _f(b1.get("total_assets_cr"))
    pat0, pat1 = _f(a0.get("pat_cr")), _f(a1.get("pat_cr"))
    if not ta0 or not ta1 or ta0 <= 0 or ta1 <= 0 or pat0 is None or pat1 is None:
        return None
    c0 = next((r for r in _years(cfs) if _day(r.get("period_end")) == _day(a0.get("period_end"))), None)
    cfo = _f((c0 or {}).get("cfo_cr"))
    roa0, roa1 = pat0 / ta0, pat1 / ta1
    tests = [roa0 > 0, roa0 > roa1]
    if cfo is not None:
        tests += [cfo > 0, cfo / ta0 > roa0]
    lev0, lev1 = _leverage(b0), _leverage(b1)
    if lev0 is not None and lev1 is not None:
        tests.append((lev0 / ta0) <= (lev1 / ta1))
    cr0, cr1 = _current_ratio(b0), _current_ratio(b1)
    if cr0 is not None and cr1 is not None:
        tests.append(cr0 > cr1)
    eq0, eq1 = _f(b0.get("equity_capital_cr")), _f(b1.get("equity_capital_cr"))
    if eq0 is not None and eq1 is not None:
        tests.append(eq0 <= eq1 * 1.001)
    m0, m1 = _core_opm(a0), _core_opm(a1)
    if m0 is not None and m1 is not None:
        tests.append(m0 > m1)
    r0, r1 = _f(a0.get("revenue_cr")), _f(a1.get("revenue_cr"))
    if r0 is not None and r1 is not None:
        tests.append((r0 / ta0) > (r1 / ta1))
    return int(sum(bool(t) for t in tests)), len(tests)


def piotroski(a0, a1, b0, b1, cfs):
    """Piotroski's nine-point F-score: the tests passed (piotroski_tests), or
    None when the two years' sheets and P&L are not both held."""
    got = piotroski_tests(a0, a1, b0, b1, cfs)
    return None if got is None else got[0]


# ---------------------------------------------------------------------------
# One company
# ---------------------------------------------------------------------------

def build(quarters=(), annuals=(), cashflows=(), balances=(), sector=None, asof=None):
    """
    One company's snapshot from its rows of the four tables (dicts in the
    fundamentals_store column names, any order, either basis). `asof` (a
    date) is the session the snapshot is read on: older figures than it
    allows are left out. Returns {} when there is nothing to read.
    """
    asof = _day(asof) or dt.date.today()
    every = list(quarters or ()) + list(annuals or ())
    basis = basis_of(every) or basis_of(list(cashflows or ()) + list(balances or ()))
    if not basis:
        return {}
    q = _one_basis(quarters, basis)
    a = _one_basis(annuals, basis)
    c = _one_basis(cashflows, basis)
    b = _one_basis(balances, basis)
    if not (q or a or c or b):
        return {}
    fin = is_financial(sector, q[0] if q else None, b[0] if b else None)
    out = {"basis": basis, "is_financial": fin, "sector": sector}
    out.update(_quarters(q, asof, fin))
    out.update(_annual(a, c, b, asof, fin))
    return out


def valuation(snap, price):
    """
    Price-dependent figures, worked out from the filings and today's price:
    market value, trailing P/E, PEG on three-year profit growth, and EV over
    trailing EBITDA (not for lenders, for whom it means nothing). A new dict;
    `snap` is not changed.
    """
    snap = dict(snap or {})
    p = _f(price)
    shares = _f(snap.get("shares_cr"))
    out = {"market_cap_cr": None, "pe": None, "peg": None, "ev_ebitda": None}
    if p is None or p <= 0:
        return out
    if shares and shares > 0:
        out["market_cap_cr"] = _r(p * shares, 1)
    eps = _f(snap.get("eps_ttm"))
    if eps and eps > 0:
        out["pe"] = _r(p / eps, 1)
        g = _f(snap.get("pat_cagr_3y"))
        if g and g > 0:
            out["peg"] = _r(out["pe"] / g, 2)
    if not snap.get("is_financial"):
        # The business's own EBITDA, and an enterprise value only where the
        # net debt is known: an unknown debt is not no debt.
        ebitda = _f(snap.get("core_ebitda_ttm_cr"))
        if ebitda is None:
            ebitda = _f(snap.get("ebitda_ttm_cr"))
        mcap, nd = out["market_cap_cr"], _f(snap.get("net_debt_cr"))
        if ebitda and ebitda > 0 and mcap and nd is not None:
            out["ev_ebitda"] = _r((mcap + nd) / ebitda, 1)
    return out


def with_price(snap, price):
    """The snapshot with its valuation at `price` added."""
    out = dict(snap or {})
    out.update(valuation(snap, price))
    return out
