"""
lens_metrics.py — the numbers a lens rule is tested against

WHERE EVERY NUMBER COMES FROM
  altaha_fundamentals.db   the company's own Reg 33 filings, one accounting
                           basis per company (consolidated where filed):
                             income_statement  annual and quarterly, ~8 years
                             balance_sheet     March and September, from 2022
                             cash_flow         full year, from FY21
  altaha_lenses.db         lens_company: NSE industry, issued shares, price
                           lens_shareholding: promoter / FII / DII, pledge
  special.py panels        the latest bhavcopy close, where it is held

Nothing is estimated and nothing is filled in. A metric that cannot be
computed from what was filed returns None, and the engine treats the rule as
n/a. The one thing derived is a missing financial year: where a company's
annual row was not read but all four of that year's quarters were, the year is
their sum and says so.

TWO PASSES
Most metrics belong to one company. A few are relative to peers — revenue rank
within an industry, margin against the industry median, market-value rank,
margin stability against the market. Those are computed in a second pass over
compact per-company summaries, and only when enough of the peer group has been
read (PEER_MIN_COVERAGE). A rank computed over a tenth of an industry would be
a confident statement about a group this site has mostly not seen.

MEMORY
The instance has 512 MB. The fundamentals tables are read one company at a
time, ordered by symbol, and each company is reduced to the handful of figures
the lenses use before the next is read.
"""

import datetime as dt
import math
import os
import statistics

PEER_MIN_COVERAGE = float(os.environ.get("LENS_PEER_MIN_COVERAGE", "0.8") or 0.8)
MIN_INDUSTRY_PEERS = 3
STALE_DAYS = 800          # a latest financial year older than this is not current
LARGE_CAP_RANK = 100      # SEBI's categorisation: 1–100 large, 101–250 mid
MID_CAP_RANK = 250

INCOME_COLS = ["symbol", "company", "basis", "freq", "period_end", "months",
               "revenue_cr", "ebitda_cr", "pbt_cr", "pbt_before_exceptional_cr",
               "finance_cost_cr", "depreciation_cr", "pat_cr", "eps_basic",
               "tax_rate_pct"]
BALANCE_COLS = ["symbol", "basis", "period_end", "total_assets_cr",
                "current_assets_cr", "current_liabilities_cr", "total_equity_cr",
                "equity_to_owners_cr", "equity_capital_cr", "total_borrowings_cr",
                "borrowings_current_cr", "cash_and_equivalents_cr",
                "current_investments_cr", "other_bank_balances_cr", "debt_equity_x"]
CASHFLOW_COLS = ["symbol", "basis", "period_end", "months", "capex_cr", "fcf_cr",
                 "cfo_cr"]


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _f(v):
    if v is None or isinstance(v, bool):
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _d(s):
    try:
        return dt.date.fromisoformat(str(s)[:10])
    except (TypeError, ValueError):
        return None


def fy_label(end):
    """Indian financial-year label for a period end: 2026-03-31 -> FY26."""
    d = _d(end)
    if not d:
        return None
    return "FY%02d" % ((d.year + (1 if d.month > 3 else 0)) % 100)


def pct(v, dp=1):
    return None if v is None else ("%." + str(dp) + "f%%") % v


def cr(v):
    if v is None:
        return "—"
    return "₹{:,.0f} cr".format(v) if abs(v) >= 100 else "₹{:,.1f} cr".format(v)


def cagr(end, start, years):
    if end is None or start is None or years <= 0 or start <= 0 or end <= 0:
        return None
    return ((end / start) ** (1.0 / years) - 1.0) * 100.0


def m(value, display=None, note=None, fail=None):
    out = {"value": value, "display": display, "note": note}
    if fail:
        out["fail"] = fail
    return out


# ---------------------------------------------------------------------------
# One company, reduced to what the lenses use
# ---------------------------------------------------------------------------

class Company:
    """
    One company's statements on one basis, arranged by financial year.

    years[0] is the latest financial year, years[k] the one k years earlier,
    and a gap in the filings leaves a None at that position rather than
    silently shifting the next year up — a "5-year" CAGR must span five years.
    """

    def __init__(self, symbol, income, balance, cashflow, today=None):
        self.symbol = symbol
        self.today = today or dt.date.today()
        self.company = next((r.get("company") for r in income if r.get("company")), None)
        self.basis = self._pick_basis(income)
        inc = [r for r in income if r.get("basis") == self.basis]
        self.balance = {r["period_end"]: r for r in balance if r.get("basis") == self.basis}
        self.cashflow = {r["period_end"]: r for r in cashflow
                         if r.get("basis") == self.basis and int(r.get("months") or 0) == 12}
        self.quarters = sorted((r for r in inc if r.get("freq") == "quarterly"),
                               key=lambda r: r["period_end"], reverse=True)
        annual = {r["period_end"]: dict(r) for r in inc if r.get("freq") == "annual"}
        self._fill_from_quarters(annual)
        self.years = self._arrange(annual)

    @staticmethod
    def _pick_basis(income):
        bases = {r.get("basis") for r in income}
        if "consolidated" in bases:
            return "consolidated"
        return "standalone" if "standalone" in bases else next(iter(bases), None)

    def _fill_from_quarters(self, annual):
        """A missing year whose four quarters were all read, as their sum."""
        if not self.quarters:
            return
        fy_month = 3
        if annual:
            fy_month = _d(max(annual)).month
        by_end = {r["period_end"]: r for r in self.quarters}
        ends = sorted(by_end)
        for e in ends:
            d = _d(e)
            if not d or d.month != fy_month or e in annual:
                continue
            four = []
            for q in ends:
                qd = _d(q)
                if qd and 0 <= (d - qd).days <= 290:
                    four.append(by_end[q])
            if len(four) != 4:
                continue
            row = {"period_end": e, "derived_from_quarters": True,
                   "company": four[0].get("company")}
            for k in ("revenue_cr", "ebitda_cr", "pbt_cr", "pbt_before_exceptional_cr",
                      "finance_cost_cr", "depreciation_cr", "pat_cr", "eps_basic"):
                vals = [_f(q.get(k)) for q in four]
                row[k] = None if any(v is None for v in vals) else round(sum(vals), 4)
            row["tax_rate_pct"] = None
            annual[e] = row

    def _arrange(self, annual):
        if not annual:
            return []
        ends = sorted(annual, reverse=True)
        latest = _d(ends[0])
        if not latest or (self.today - latest).days > STALE_DAYS:
            return []
        out = []
        for k in range(0, 12):
            want = dt.date(latest.year - k, latest.month, min(latest.day, 28))
            hit = None
            for e in ends:
                ed = _d(e)
                if ed and abs((ed - want).days) <= 45:
                    hit = annual[e]
                    break
            out.append(hit)
        while out and out[-1] is None:
            out.pop()
        return out

    # --- per-year figures --------------------------------------------------

    def year(self, k):
        return self.years[k] if 0 <= k < len(self.years) else None

    def span(self, n):
        """Years 0..n inclusive, or None if any is missing."""
        ys = [self.year(k) for k in range(n + 1)]
        return None if any(y is None for y in ys) else ys

    def bs(self, y):
        """The balance sheet at a financial year's end."""
        if not y:
            return None
        d = _d(y["period_end"])
        for e, r in self.balance.items():
            ed = _d(e)
            if ed and d and abs((ed - d).days) <= 10:
                return r
        return None

    def cf(self, y):
        if not y:
            return None
        d = _d(y["period_end"])
        for e, r in self.cashflow.items():
            ed = _d(e)
            if ed and d and abs((ed - d).days) <= 10:
                return r
        return None

    def latest_bs(self):
        if not self.balance:
            return None
        return self.balance[max(self.balance)]

    @staticmethod
    def revenue(y):
        return _f(y.get("revenue_cr")) if y else None

    @staticmethod
    def margin(y):
        if not y:
            return None
        rev, e = _f(y.get("revenue_cr")), _f(y.get("ebitda_cr"))
        if rev is None or e is None or rev <= 0:
            return None
        return e / rev * 100.0

    @staticmethod
    def ebit(y):
        if not y:
            return None
        pbt = _f(y.get("pbt_before_exceptional_cr"))
        if pbt is None:
            pbt = _f(y.get("pbt_cr"))
        fin = _f(y.get("finance_cost_cr"))
        if pbt is None or fin is None:
            return None
        return pbt + fin

    def capital_employed(self, y):
        b = self.bs(y)
        if not b:
            return None
        ta, cl = _f(b.get("total_assets_cr")), _f(b.get("current_liabilities_cr"))
        if ta is None or cl is None or ta - cl <= 0:
            return None
        return ta - cl

    def roce(self, y):
        e, ce = self.ebit(y), self.capital_employed(y)
        return None if e is None or ce is None else e / ce * 100.0

    def roe(self, y):
        b = self.bs(y)
        if not y or not b:
            return None
        pat = _f(y.get("pat_cr"))
        eq = _f(b.get("equity_to_owners_cr"))
        if eq is None:
            eq = _f(b.get("total_equity_cr"))
        if pat is None or eq is None or eq <= 0:
            return None
        return pat / eq * 100.0

    def nwc(self, b):
        if not b:
            return None
        ca, cl = _f(b.get("current_assets_cr")), _f(b.get("current_liabilities_cr"))
        if ca is None or cl is None:
            return None
        cash = sum(_f(b.get(k)) or 0.0 for k in ("cash_and_equivalents_cr",
                                                   "current_investments_cr",
                                                   "other_bank_balances_cr"))
        stb = _f(b.get("borrowings_current_cr")) or 0.0
        return (ca - cash) - (cl - stb)

    def ttm_eps(self, offset=0):
        """Sum of four consecutive quarters' EPS, `offset` quarters back."""
        qs = self.quarters[offset:offset + 4]
        if len(qs) < 4:
            return None
        ds = [_d(q["period_end"]) for q in qs]
        if any(d is None for d in ds) or (ds[0] - ds[3]).days > 290:
            return None
        vals = [_f(q.get("eps_basic")) for q in qs]
        if any(v is None for v in vals):
            return None
        return sum(vals)

    def ttm_label(self, offset=0):
        qs = self.quarters[offset:offset + 4]
        return qs[0]["period_end"] if len(qs) == 4 else None


# ---------------------------------------------------------------------------
# Single-company metrics. Each takes (company, lookback, context) and returns
# a metric dict or None.
# ---------------------------------------------------------------------------

def _revenue_cagr(c, n, ctx):
    y0, yn = c.year(0), c.year(n)
    if not y0 or not yn:
        return None
    v = cagr(c.revenue(y0), c.revenue(yn), n)
    if v is None:
        return None
    return m(round(v, 2), pct(v),
             "%s %s → %s %s" % (fy_label(yn["period_end"]), cr(c.revenue(yn)),
                                 fy_label(y0["period_end"]), cr(c.revenue(y0))))


def _revenue_growth_min(c, n, ctx):
    ys = c.span(n)
    if not ys:
        return None
    gs = []
    for a, b in zip(ys, ys[1:]):
        ra, rb = c.revenue(a), c.revenue(b)
        if ra is None or rb is None or rb <= 0:
            return None
        gs.append((ra / rb - 1) * 100)
    v = min(gs)
    return m(round(v, 2), pct(v), "Lowest yearly growth in %d years" % n)


def _roce(c, n, ctx):
    y = c.year(0)
    v = c.roce(y)
    if v is None:
        return None
    return m(round(v, 2), pct(v),
             "%s: EBIT %s ÷ capital employed %s" % (fy_label(y["period_end"]),
                                                   cr(c.ebit(y)), cr(c.capital_employed(y))))


def _roce_min(c, n, ctx):
    ys = c.span(n - 1)
    if not ys:
        return None
    vals = [c.roce(y) for y in ys]
    if any(v is None for v in vals):
        return None
    v = min(vals)
    return m(round(v, 2), pct(v), "Lowest of %d years" % n)


def _roce_change(c, n, ctx):
    y0, yn = c.year(0), c.year(n)
    a, b = c.roce(y0), c.roce(yn)
    if a is None or b is None:
        return None
    v = a - b
    return m(round(v, 2), "%+.1f pp" % v,
             "%s %s vs %s %s" % (fy_label(y0["period_end"]), pct(a),
                                 fy_label(yn["period_end"]), pct(b)))


def _roe(c, n, ctx):
    y = c.year(0)
    v = c.roe(y)
    if v is None:
        return None
    return m(round(v, 2), pct(v), "%s: profit after tax ÷ shareholders' equity"
             % fy_label(y["period_end"]))


def _roe_min(c, n, ctx):
    ys = c.span(n - 1)
    if not ys:
        return None
    vals = [c.roe(y) for y in ys]
    if any(v is None for v in vals):
        return None
    v = min(vals)
    return m(round(v, 2), pct(v), "Lowest of %d years" % n)


def _debt_equity(c, n, ctx):
    b = c.latest_bs()
    if not b:
        return None
    v = _f(b.get("debt_equity_x"))
    if v is None:
        debt, eq = _f(b.get("total_borrowings_cr")), _f(b.get("total_equity_cr"))
        if debt is None or eq is None or eq <= 0:
            return None
        v = debt / eq
    return m(round(v, 3), "%.2fx" % v, "Balance sheet at %s" % b["period_end"])


def _fcf_positive_years(c, n, ctx):
    ys = c.span(n - 1)
    if not ys:
        return None
    fcfs = [_f((c.cf(y) or {}).get("fcf_cr")) for y in ys]
    if any(v is None for v in fcfs):
        return None
    v = sum(1 for x in fcfs if x > 0)
    return m(v, "%d of %d years" % (v, n))


def _margin_change(c, n, ctx):
    y0, yn = c.year(0), c.year(n)
    a, b = c.margin(y0), c.margin(yn)
    if a is None or b is None:
        return None
    v = a - b
    return m(round(v, 2), "%+.1f pp" % v,
             "EBITDA margin %s %s vs %s %s" % (fy_label(y0["period_end"]), pct(a),
                                               fy_label(yn["period_end"]), pct(b)))


def _margin_stdev(c, n):
    ys = c.span(n - 1)
    if not ys:
        return None
    ms = [c.margin(y) for y in ys]
    if any(v is None for v in ms):
        return None
    return statistics.pstdev(ms)


def _eps_growth(c, n, ctx):
    a, b = c.ttm_eps(0), c.ttm_eps(4)
    if a is not None and b is not None:
        if b <= 0:
            return None
        v = (a / b - 1) * 100
        return m(round(v, 2), pct(v), "Trailing four quarters to %s: ₹%.2f vs ₹%.2f"
                 % (c.ttm_label(0), a, b))
    y0, y1 = c.year(0), c.year(1)
    if not y0 or not y1:
        return None
    a, b = _f(y0.get("eps_basic")), _f(y1.get("eps_basic"))
    if a is None or b is None or b <= 0:
        return None
    v = (a / b - 1) * 100
    return m(round(v, 2), pct(v), "%s EPS ₹%.2f vs %s ₹%.2f"
             % (fy_label(y0["period_end"]), a, fy_label(y1["period_end"]), b))


def _eps_cagr(c, n, ctx):
    y0, yn = c.year(0), c.year(n)
    if not y0 or not yn:
        return None
    a, b = _f(y0.get("eps_basic")), _f(yn.get("eps_basic"))
    if a is None or b is None or b <= 0:
        return None
    if a <= 0:
        return m(None, None, None, fail="EPS moved from a profit to a loss")
    v = cagr(a, b, n)
    return m(round(v, 2), pct(v), "%s EPS ₹%.2f → %s ₹%.2f"
             % (fy_label(yn["period_end"]), b, fy_label(y0["period_end"]), a))


def _eps_rising_years(c, n, ctx):
    ys = c.span(n)
    if not ys:
        return None
    eps = [_f(y.get("eps_basic")) for y in ys]
    if any(v is None for v in eps):
        return None
    v = sum(1 for a, b in zip(eps, eps[1:]) if a > b)
    return m(v, "%d of %d years" % (v, n))


def _price(c, ctx):
    p = (ctx.get("prices") or {}).get(c.symbol)
    if p is None:
        p = _f((ctx.get("company") or {}).get("last_price"))
    return p


def _peg(c, n, ctx):
    price = _price(c, ctx)
    if price is None or price <= 0:
        return None
    eps = c.ttm_eps(0)
    if eps is None and c.year(0):
        eps = _f(c.year(0).get("eps_basic"))
    if eps is None:
        return None
    if eps <= 0:
        return m(None, None, None, fail="No P/E: trailing EPS is not positive")
    growth = (_eps_growth if n <= 1 else _eps_cagr)(c, n, ctx)
    if growth is None:
        return None
    if growth.get("fail"):
        return m(None, None, None, fail=growth["fail"])
    g = growth["value"]
    if g is None:
        return None
    if g <= 0:
        return m(None, None, None, fail="EPS did not grow, so PEG is not defined")
    pe = price / eps
    v = pe / g
    return m(round(v, 3), "%.2f" % v, "P/E %.1f ÷ EPS growth %s" % (pe, pct(g)))


def _fii_dii(c, n, ctx):
    q = (ctx.get("shareholding") or [None])[0]
    if not q:
        return None
    f, d = _f(q.get("fii_pct")), _f(q.get("dii_pct"))
    if f is None or d is None:
        return None
    v = f + d
    return m(round(v, 2), pct(v), "FII %s + DII %s, quarter to %s"
             % (pct(f), pct(d), q["period_end"]))


def _promoter(c, n, ctx):
    q = (ctx.get("shareholding") or [None])[0]
    if not q or _f(q.get("promoter_pct")) is None:
        return None
    v = _f(q["promoter_pct"])
    return m(round(v, 2), pct(v), "Quarter to %s" % q["period_end"])


def _pledge(c, n, ctx):
    q = (ctx.get("shareholding") or [None])[0]
    if not q:
        return None
    p, flag = _f(q.get("pledge_pct")), q.get("pledged")
    if p is not None:
        return m(round(p, 4), pct(p, 2), "Promoter shares pledged, quarter to %s" % q["period_end"])
    if flag == 0:
        return m(0.0, "None", "The filing states no promoter shares are pledged (%s)" % q["period_end"])
    if flag == 1:
        return m(None, "Yes", None, fail="The filing states promoter shares are pledged")
    return None


def _promoter_change(c, n, ctx):
    rows = ctx.get("shareholding") or []
    if not rows:
        return None
    q0 = rows[0]
    d0 = _d(q0["period_end"])
    lo, hi = 330 * max(1, n), 400 * max(1, n)
    prev = next((r for r in rows[1:] if d0 and _d(r["period_end"])
                 and lo <= (d0 - _d(r["period_end"])).days <= hi), None)
    a = _f(q0.get("promoter_pct"))
    b = _f(prev.get("promoter_pct")) if prev else None
    if a is None or b is None:
        return None
    v = a - b
    return m(round(v, 3), "%+.2f pp" % v, "%s %s vs %s %s"
             % (q0["period_end"], pct(a, 2), prev["period_end"], pct(b, 2)))


def _reinvestment_rate(c, n, ctx):
    ys = c.span(n)
    if not ys:
        return None
    reinvest = nopat = 0.0
    for i in range(n):
        y, prev = ys[i], ys[i + 1]
        cfy, b, bp = c.cf(y), c.bs(y), c.bs(prev)
        capex = _f((cfy or {}).get("capex_cr"))
        dep = _f(y.get("depreciation_cr"))
        w0, w1 = c.nwc(b), c.nwc(bp)
        e = c.ebit(y)
        if None in (capex, dep, w0, w1, e):
            return None
        t = _f(y.get("tax_rate_pct"))
        t = 0.25 if t is None else min(max(t / 100.0, 0.0), 0.4)
        reinvest += capex - dep + (w0 - w1)
        nopat += e * (1 - t)
    if nopat <= 0:
        return None
    v = reinvest / nopat * 100
    return m(round(v, 2), pct(v),
             "(capex − depreciation + change in working capital) ÷ operating profit after tax, %d years" % n)


def _asset_turnover_change(c, n, ctx):
    y0, yn = c.year(0), c.year(n)

    def at(y):
        b = c.bs(y)
        ta = _f((b or {}).get("total_assets_cr"))
        rev = c.revenue(y)
        return None if not ta or ta <= 0 or rev is None else rev / ta

    a, b = at(y0), at(yn)
    if a is None or b is None:
        return None
    v = a - b
    return m(round(v, 4), "%+.2fx" % v, "Revenue ÷ total assets %s %.2fx vs %s %.2fx"
             % (fy_label(y0["period_end"]), a, fy_label(yn["period_end"]), b))


def _share_count_cagr(c, n, ctx):
    y0, yn = c.year(0), c.year(n)
    b0, bn = c.bs(y0), c.bs(yn)
    a = _f((b0 or {}).get("equity_capital_cr"))
    b = _f((bn or {}).get("equity_capital_cr"))
    v = cagr(a, b, n)
    if v is None:
        return None
    return m(round(v, 2), "%+.1f%% a year" % v,
             "Paid-up equity capital %s %s → %s %s. A bonus issue raises this without dilution."
             % (fy_label(yn["period_end"]), cr(b), fy_label(y0["period_end"]), cr(a)))


SINGLE = {
    "revenue_cagr": _revenue_cagr,
    "revenue_growth_min": _revenue_growth_min,
    "roce": _roce,
    "roce_min": _roce_min,
    "roce_change": _roce_change,
    "roe": _roe,
    "roe_min": _roe_min,
    "debt_equity": _debt_equity,
    "fcf_positive_years": _fcf_positive_years,
    "margin_change": _margin_change,
    "eps_growth": _eps_growth,
    "eps_cagr": _eps_cagr,
    "eps_rising_years": _eps_rising_years,
    "peg": _peg,
    "fii_dii_pct": _fii_dii,
    "promoter_pct": _promoter,
    "pledge_pct": _pledge,
    "promoter_change": _promoter_change,
    "reinvestment_rate": _reinvestment_rate,
    "asset_turnover_change": _asset_turnover_change,
    "share_count_cagr": _share_count_cagr,
}
PEER = {"industry_revenue_rank", "margin_vs_industry_min", "size_band",
        "margin_stdev_pctile"}
UNBUILT = {"industry_capex_dep_change", "industry_peer_count_change"}


def fields_known():
    return set(SINGLE) | PEER | UNBUILT


# ---------------------------------------------------------------------------
# Per company: own metrics plus the summary the peer pass needs
# ---------------------------------------------------------------------------

def company_metrics(c, required, ctx):
    """({metric_key: metric}, peer_summary) for one company."""
    from lens_engine import metric_key
    out = {}
    for field, lb in required:
        fn = SINGLE.get(field)
        if fn is None:
            continue
        try:
            out[metric_key(field, lb)] = fn(c, lb, ctx)
        except (ArithmeticError, TypeError, ValueError):
            out[metric_key(field, lb)] = None
    prof = ctx.get("company") or {}
    y0 = c.year(0)
    price = _price(c, ctx)
    shares = _f(prof.get("issued_shares"))
    summary = {
        "symbol": c.symbol,
        "company": prof.get("company") or c.company,
        "industry": prof.get("industry") or None,
        "revenue": c.revenue(y0),
        "revenue_fy": fy_label(y0["period_end"]) if y0 else None,
        "margins": {fy_label(y["period_end"]): c.margin(y)
                    for y in c.years[:6] if y and c.margin(y) is not None},
        "mcap_cr": (price * shares / 1e7) if price and shares else None,
        "stdev": {lb: _margin_stdev(c, lb) for f, lb in required if f == "margin_stdev_pctile"},
    }
    return out, summary


def peer_metrics(summaries, required, profiles, universe_size):
    """{symbol: {metric_key: metric}} for the peer-relative fields."""
    from lens_engine import metric_key
    need = {(f, lb) for f, lb in required if f in PEER}
    out = {s["symbol"]: {} for s in summaries}
    if not need:
        return out

    members = {}
    for sym, p in profiles.items():
        if p.get("industry"):
            members.setdefault(p["industry"], set()).add(sym)
    by_ind = {}
    for s in summaries:
        if s["industry"]:
            by_ind.setdefault(s["industry"], []).append(s)

    def industry_ok(ind, have):
        total = len(members.get(ind) or ())
        if total < MIN_INDUSTRY_PEERS:
            return False, "Fewer than %d listed companies in %s" % (MIN_INDUSTRY_PEERS, ind)
        if have / float(total) < PEER_MIN_COVERAGE:
            return False, ("Statements read for %d of %d companies in %s so far"
                           % (have, total, ind))
        return True, None

    for field, lb in need:
        key = metric_key(field, lb)
        if field == "industry_revenue_rank":
            for ind, group in by_ind.items():
                latest = [g for g in group if g["revenue"] is not None]
                ok, why = industry_ok(ind, len(latest))
                ranked = sorted(latest, key=lambda g: -g["revenue"])
                for g in group:
                    if not ok or g["revenue"] is None:
                        out[g["symbol"]][key] = m(None, None, why)
                        continue
                    r = ranked.index(g) + 1
                    out[g["symbol"]][key] = m(r, "#%d of %d" % (r, len(ranked)),
                                              "By %s revenue in %s" % (g["revenue_fy"], ind))
        elif field == "margin_vs_industry_min":
            for ind, group in by_ind.items():
                have = sum(1 for g in group if g["margins"])
                ok, why = industry_ok(ind, have)
                med = {}
                for g in group:
                    for fy, mg in g["margins"].items():
                        med.setdefault(fy, []).append(mg)
                med = {fy: statistics.median(v) for fy, v in med.items()
                       if len(v) >= MIN_INDUSTRY_PEERS}
                for g in group:
                    fys = sorted(g["margins"], reverse=True)[:lb]
                    if not ok or len(fys) < lb or any(fy not in med for fy in fys):
                        out[g["symbol"]][key] = m(None, None, why)
                        continue
                    diffs = [(g["margins"][fy] - med[fy], fy) for fy in fys]
                    v, fy = min(diffs)
                    out[g["symbol"]][key] = m(round(v, 2), "%+.1f pp" % v,
                                              "Smallest gap to the %s median was in %s" % (ind, fy))
        elif field == "size_band":
            have = [s for s in summaries if s["mcap_cr"]]
            enough = universe_size and len(have) / float(universe_size) >= PEER_MIN_COVERAGE
            ranked = sorted(have, key=lambda s: -s["mcap_cr"])
            rank = {s["symbol"]: i + 1 for i, s in enumerate(ranked)}
            for s in summaries:
                if not enough or s["symbol"] not in rank:
                    out[s["symbol"]][key] = m(None, None, (
                        "Market-value ranks need a price and share count for most listed "
                        "companies; %d of %d so far" % (len(have), universe_size or 0)))
                    continue
                r = rank[s["symbol"]]
                band = "large" if r <= LARGE_CAP_RANK else ("mid" if r <= MID_CAP_RANK else "small")
                out[s["symbol"]][key] = m(band, "%s cap (#%d, %s)" % (band.capitalize(), r,
                                                                       cr(s["mcap_cr"])),
                                          "Rank by market value: 1–100 large, 101–250 mid, 251+ small")
        elif field == "margin_stdev_pctile":
            vals = sorted((s["stdev"].get(lb), s["symbol"]) for s in summaries
                          if s["stdev"].get(lb) is not None)
            enough = universe_size and len(vals) / float(universe_size) >= PEER_MIN_COVERAGE
            n = len(vals)
            pos = {sym: i for i, (_v, sym) in enumerate(vals)}
            for s in summaries:
                if not enough or s["symbol"] not in pos:
                    out[s["symbol"]][key] = m(None, None, "Too few companies with %d years of margins" % lb)
                    continue
                v = 100.0 * pos[s["symbol"]] / max(1, n - 1)
                out[s["symbol"]][key] = m(round(v, 1), "Percentile %.0f" % v,
                                          "Lower is steadier: standard deviation %.1f pp"
                                          % s["stdev"][lb])
    return out


# ---------------------------------------------------------------------------
# Reading the stores, one company at a time
# ---------------------------------------------------------------------------

def _grouped(conn, table, cols, where=""):
    sql = "SELECT %s FROM %s %s ORDER BY symbol" % (", ".join(cols), table, where)
    cur = conn.execute(sql)
    group, sym = [], None
    for r in cur:
        d = dict(zip(cols, r))
        if d["symbol"] != sym and group:
            yield sym, group
            group = []
        sym = d["symbol"]
        group.append(d)
    if group:
        yield sym, group


def iter_companies(conn):
    """(symbol, income_rows, balance_rows, cashflow_rows), merged by symbol."""
    inc = _grouped(conn, "income_statement", INCOME_COLS)
    bal = dict(_grouped(conn, "balance_sheet", BALANCE_COLS))
    cfs = dict(_grouped(conn, "cash_flow", CASHFLOW_COLS, "WHERE months = 12"))
    for sym, rows in inc:
        yield sym, rows, bal.pop(sym, []), cfs.pop(sym, [])


def latest_prices():
    """{symbol: close} from the delivery panels, where they are held."""
    try:
        import special
        P = special._load_cache()
        if not P or P.get("close") is None:
            return {}
        close = P["close"].ffill().iloc[-1]
        return {str(k): float(v) for k, v in close.items() if v == v and v > 0}
    except Exception:
        return {}
