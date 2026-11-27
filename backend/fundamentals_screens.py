"""
fundamentals_screens.py — three questions asked of every company at once

WHAT THIS IS
The fundamentals crawl holds every NSE company's filed statements. A question
like "whose revenue has grown more than 20% in each of the last four
quarters?" used to mean one exchange request per company per quarter; against
the tables it is one read. This module asks three such questions of the whole
market:

  · Fast growers with expanding margins  (steady_growers)
  · Operational turnarounds              (turnarounds)
  · Cash-rich FCF compounders            (fcf_compounders)

There used to be five. "Operating margin up 3 points" is now the second way
onto the growers' screen (two quarters of growth with the margin widening), and
"more cash than debt" one of the two ways through the compounders' debt test.
Their old ids still answer (ALIASES), so an address saved under one, or an old
caller, gets the screen that took it over instead of a 404.

The lenses (lens_engine.py) do the same for named investing philosophies,
built on full financial years. These are narrower and faster moving.

THE FIGURES
Every figure a screen tests or shows comes from fund_snapshot.build(), the
code the Ideas lists are ranked on. The financial carve-out, EBITDA without
exceptional items (the stored EBITDA includes them), other income as a share
of profit before tax, and the cash and balance-sheet figures are therefore the
same numbers on both pages: nothing is worked out a second way here.

The tables are read CHUNK companies at a time, and only the columns and years
the snapshot uses, so the whole market never sits in memory at once on a
512 MB box.

WHAT A MATCH IS, AND IS NOT
A company appears when its filed figures meet the stated condition, and every
match carries the figures behind it. Nothing is a recommendation, and a
company without the figures a screen needs is left out rather than guessed
at, so "not listed" never means "failed".

A MISSING FIGURE IS UNKNOWN, NEVER 0
The tests that define a screen (a profit, a year-ago loss, three years of free
cash flow) need their figure, so a company without it is left out. A safety
test (other income, an exceptional gain, return on capital, how much trades a
day) is skipped when its figure is unknown, as the Ideas lists skip theirs. In
an ordering, a company whose figure is unknown comes after the ones whose
figure is known; it is never ranked as if the figure were 0. Nothing a filing
leaves out raises.

BANKS, LENDERS AND INSURERS
fund_snapshot.is_financial() marks them, from NSE's industry or the
bank-format lines in their own filings; where NSE's bundled list does not
cover a company, its stored Yahoo sector is the industry passed in. Their
operating margin, EBITDA and other income describe lending rather than a
business's operations, so they are never tested on those, and the compounders'
screen, built on free cash flow and debt, does not list them at all.

LIQUIDITY AND PRICE
Nothing here reaches the network. How much a company trades a day is known
only for the companies the latest scan analysed: it records each one's
average traded value and close in the point-in-time store (pit_store). The
growers' turnover test runs where that figure exists and is skipped where it
does not. A market value, for the compounders' free cash flow yield, is
fund_snapshot.valuation() at the scan's close, or failing that the price in
the company's stored Yahoo profile.

Standard library only.
"""

import csv
import datetime as dt
import os
import threading
import time

try:
    import fundamentals_store as store
except Exception:                                   # pragma: no cover
    store = None
try:
    import fund_snapshot as FS
except Exception:                                   # pragma: no cover
    FS = None

_HERE = os.path.dirname(os.path.abspath(__file__))
# NSE's industry for the Nifty Total Market companies, shipped with the code
# (the file scan.sector_map() falls back to; read here without asking NSE).
SECTORS_FILE = os.path.join(_HERE, "nse_industries.csv")

CACHE_SECONDS = 3600
# Companies read per pass over the tables.
CHUNK = 250
# How far back each table is read, from the day the screens are asked: enough
# for every figure fund_snapshot works out (eight quarters and the year-ago
# quarters behind them, three-year growth on an annual P&L up to eighteen
# months old, three full years of cash flow, two year-end balance sheets),
# and the same windows the scan's snapshot reads.
QUARTERS_BACK_DAYS = 3 * 366
ANNUALS_BACK_DAYS = 5 * 366
CASHFLOWS_BACK_DAYS = 4 * 366
BALANCES_BACK_DAYS = 3 * 366
# The latest scan's traded value and close are used for this long after it
# ran; an older one describes a market that has moved on.
SCAN_FRESH_DAYS = 14

# ── Fast growers with expanding margins ──────────────────────────────────────
RUN_MIN_PCT = 20.0          # revenue growth in each of the last four quarters, more than
PAIR_MIN_PCT = 15.0         # ...or in each of the last two, at least
PAIR_MARGIN_PTS = 2.5       # ...with the operating margin up at least this on a year earlier
OPM_FLOOR_PCT = 8.0         # operating margin, at least
OPM_DROP_MAX_PTS = 1.5      # operating margin below a year earlier by no more than
MIN_TURNOVER_CR = 2.0       # ₹ crore traded a day, at least, where the scan measured it

# ── Operational turnarounds ─────────────────────────────────────────────────
OTHER_INCOME_MAX_SHARE = 0.30    # of profit before tax
EXCEPTIONAL_MAX_SHARE = 0.25     # of profit before tax
# Net margins are ordered within ±100%: a year-ago loss many times that
# quarter's revenue would otherwise decide the order on its own.
MARGIN_CLAMP_PCT = 100.0
# A business of some size: ₹25 crore of revenue in the quarter, about ₹100
# crore a year. Ordered on margin swing, the screen otherwise opens with
# companies of ₹2-90 crore a year, where a few lakh of profit swings the
# margin by tens of points.
TURNAROUND_MIN_REVENUE_CR = 25.0

# ── Cash-rich FCF compounders ───────────────────────────────────────────────
FCF_YEARS = 3               # full years of positive free cash flow, in a row
DE_MAX = 0.3                # debt to equity, at most (or net cash)
REV_CAGR_MIN_PCT = 8.0      # revenue growth a year over three years, at least
ROCE_MIN_PCT = 15.0         # return on capital employed, at least, where known

SCREENS = [
    {"id": "steady_growers",
     "name": "Fast growers with expanding margins",
     "description": ("Companies whose sales have grown fast for several quarters "
                     "running, with the operating margin holding or widening as "
                     "they grew."),
     "rule": ("Revenue up more than %g%% on the same quarter a year earlier in each "
              "of the last four quarters, or up at least %g%% in each of the last two "
              "with the operating margin at least %g points above a year earlier. A "
              "profit after tax in the latest quarter and over the last four. An "
              "operating margin of at least %g%%, and no more than %g points below a "
              "year earlier. At least ₹%g crore traded a day, where the scan has "
              "measured it. Banks, lenders and insurers have no operating margin: no "
              "margin test is applied to them, so they are listed on the four quarters "
              "above %g%% alone."
              % (RUN_MIN_PCT, PAIR_MIN_PCT, PAIR_MARGIN_PTS, OPM_FLOOR_PCT,
                 OPM_DROP_MAX_PTS, MIN_TURNOVER_CR, RUN_MIN_PCT)),
     "order": ("In order of two ranks among the companies listed, averaged: revenue "
               "growth (the middle figure of the quarters shown) and the change in "
               "operating margin on a year earlier (growth alone where there is no "
               "margin).")},
    {"id": "turnarounds",
     "name": "Operational turnarounds",
     "description": ("Back to a profit from a loss a year earlier, on higher sales, "
                     "with the business itself behind the profit rather than other "
                     "income or a one-off gain."),
     "rule": ("A profit after tax in the latest quarter against a loss in the same "
              "quarter a year earlier, on higher revenue. EBITDA excluding exceptional "
              "items positive and above the same quarter a year earlier. Other income "
              "no more than %g%% of profit before tax, and exceptional items no more "
              "than %g%% of it; a loss before tax fails both. Banks, lenders and "
              "insurers are not tested on EBITDA or other income: a lender's fees and "
              "treasury income are its business."
              % (OTHER_INCOME_MAX_SHARE * 100, EXCEPTIONAL_MAX_SHARE * 100)),
     "order": ("In order of how far the net margin (profit after tax ÷ revenue) moved "
               "from a year earlier, so no company is placed first for its size alone.")},
    {"id": "fcf_compounders",
     "name": "Cash-rich FCF compounders",
     "description": ("Businesses that have turned their profit into cash year after "
                     "year, carry little debt and have grown their sales."),
     "rule": ("Free cash flow positive in each of the last %d full years, and "
              "operating cash flow above profit after tax, itself positive, in the "
              "latest. Debt at most %g× equity, or more cash and current investments "
              "than borrowings. Revenue up at least %g%% a year over three years. "
              "Return on capital employed at least %g%%, where it can be worked out. "
              "Banks, lenders and insurers are not listed: their cash flow and debt "
              "describe the lending, not the business."
              % (FCF_YEARS, DE_MAX, REV_CAGR_MIN_PCT, ROCE_MIN_PCT)),
     "order": ("In order of free cash flow yield (the latest year's free cash flow ÷ "
               "market value) where a price is held; companies without one follow, in "
               "order of return on capital employed.")},
]
# The two screens folded into these, by their old ids.
ALIASES = {"margin_expanders": "steady_growers", "net_cash": "fcf_compounders"}
_BY_ID = {s["id"]: s for s in SCREENS}
_BY_ID.update({old: _BY_ID[new] for old, new in ALIASES.items()})

NOTICE = ("Screens are filters applied to the companies' filed statements. A "
          "company listed meets the stated condition on the figures shown; it "
          "is not a recommendation.")

_cache = {"at": 0.0, "key": None, "result": None}
_lock = threading.Lock()
# One pass over the market at a time: a second request waits for the first
# and reads what it cached, rather than holding a second copy of the work.
_compute_lock = threading.Lock()
_sectors = {"value": None}


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _day(v):
    if isinstance(v, dt.datetime):
        return v.date()
    if isinstance(v, dt.date):
        return v
    try:
        return dt.date.fromisoformat(str(v)[:10])
    except (TypeError, ValueError):
        return None


def _num(v):
    """A finite float, or None: never 0 for a missing figure."""
    if v is None or isinstance(v, bool):
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x and x not in (float("inf"), float("-inf")) else None


def _known(*vals):
    return all(v is not None for v in vals)


def _mean(vals):
    vals = [v for v in vals if v is not None]
    return sum(vals) / len(vals) if vals else None


def _median(vals):
    vals = sorted(v for v in vals if v is not None)
    n = len(vals)
    if not n:
        return None
    return vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / 2


def _round(v, nd=2):
    return None if v is None else round(v, nd)


def _pct_ranks(values):
    """{key: percentile in (0, 1]} by average rank among the values that are
    known; ties share the mean of their ranks. A key whose value is None gets
    no percentile, so it can never be ranked as the bottom of the field."""
    known = sorted((v, k) for k, v in values.items() if v is not None)
    n, out, i = len(known), {}, 0
    while i < n:
        j = i
        while j + 1 < n and known[j + 1][0] == known[i][0]:
            j += 1
        for t in range(i, j + 1):
            out[known[t][1]] = ((i + j) / 2 + 1) / n
        i = j + 1
    return out


def _quarter_parts(label):
    """(quarter, two-digit fiscal year) of a 'Q2 FY27' label, or None."""
    s = str(label or "").strip().upper()
    if len(s) == 7 and s[0] == "Q" and s[1] in "1234" and s[2:5] == " FY" and s[5:].isdigit():
        return int(s[1]), int(s[5:])
    return None


def _quarters_back(label, n):
    """The labels of the latest quarter and the n-1 before it, newest first,
    read off the latest one's label. A label in another form names the
    others by their distance from it."""
    parts = _quarter_parts(label)
    out = []
    for k in range(n):
        if parts is None:
            out.append(label if k == 0 else "%d quarter%s before" % (k, "s" if k > 1 else ""))
            continue
        q, fy = parts[0] - k, parts[1]
        while q < 1:
            q, fy = q + 4, fy - 1
        out.append("Q%d FY%02d" % (q, fy % 100))
    return out


def _year_ago_label(label):
    parts = _quarter_parts(label)
    return "Q%d FY%02d" % (parts[0], (parts[1] - 1) % 100) if parts else "a year earlier"


def _fy_label(end):
    """'FY26' for the Indian financial year a year-end date closes."""
    d = _day(end)
    if d is None:
        return None
    return "FY%02d" % ((d.year + 1 if d.month >= 4 else d.year) % 100)


def _margin(pat, revenue):
    """Net margin in percent, on a positive revenue only."""
    if not _known(pat, revenue) or revenue <= 0:
        return None
    return pat / revenue * 100.0


def _clamp(v, limit):
    return max(-limit, min(limit, v))


def _share_ok(part, pbt, max_share):
    """Is `part` at most `max_share` of profit before tax? None (not tested)
    when profit before tax is unknown, or when it is positive but the part
    was not filed. False on a loss before tax: no share of it can be small."""
    if pbt is None:
        return None
    if pbt <= 0:
        return False
    if part is None:
        return None
    return part <= max_share * pbt


def _fig(label, value, unit):
    return {"label": label, "value": _round(value), "unit": unit}


# ---------------------------------------------------------------------------
# What is read: the four tables, an industry, a price, a traded value
# ---------------------------------------------------------------------------

# Only the columns fund_snapshot.build() reads for the figures below, plus a
# name to show. The F-score's inputs are not read: no screen uses it.
_COLUMNS = {
    "quarters": ("symbol", "company", "basis", "period_end", "label", "filed_at",
                 "revenue_cr", "pat_cr", "ebitda_cr", "exceptional_cr", "pbt_cr",
                 "other_income_cr", "eps_basic", "opm_pct", "other_income_share_pct",
                 "interest_cover_x", "revenue_yoy_pct", "ebitda_yoy_pct", "pat_yoy_pct",
                 "operating_profit_pre_provision_cr", "provisions_cr"),
    "annuals": ("symbol", "company", "basis", "period_end", "label", "months", "filed_at",
                "revenue_cr", "pat_cr", "opm_pct", "pbt_cr", "finance_cost_cr",
                "interest_cover_x"),
    "cashflows": ("symbol", "basis", "period_end", "months", "cfo_cr", "fcf_cr"),
    "balances": ("symbol", "basis", "period_end", "total_borrowings_cr", "net_debt_cr",
                 "debt_equity_x", "cash_and_equivalents_cr", "other_bank_balances_cr",
                 "current_investments_cr", "total_equity_cr", "deposits_cr",
                 "total_liabilities_cr"),
}
_SOURCES = {
    "quarters": ("income_statement", "freq = 'quarterly'", QUARTERS_BACK_DAYS),
    "annuals": ("income_statement", "freq = 'annual'", ANNUALS_BACK_DAYS),
    "cashflows": ("cash_flow", "months = 12", CASHFLOWS_BACK_DAYS),
    "balances": ("balance_sheet", None, BALANCES_BACK_DAYS),
}


def _nse_industries():
    """{SYMBOL: NSE industry} from the list shipped with the code, read once."""
    if _sectors["value"] is None:
        out = {}
        try:
            with open(SECTORS_FILE, encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    row = {(k or "").strip(): (v or "").strip() for k, v in row.items()}
                    if row.get("Symbol") and row.get("Industry"):
                        out[row["Symbol"].upper()] = row["Industry"]
        except Exception:
            out = {}
        _sectors["value"] = out
    return _sectors["value"]


def _scan_market(today):
    """
    {SYMBOL: {"turnover_cr", "price"}} for the companies the latest scan on
    or before `today` analysed: the average traded value a day (₹ crore, 60
    sessions) and the close it scored on, as it recorded them in the
    point-in-time store. Empty when that scan is more than SCAN_FRESH_DAYS
    old, or none could be read. Never raises.
    """
    try:
        import pit_store
        conn = pit_store._connect()
        top = conn.execute("SELECT as_of_date FROM factor_snapshots WHERE as_of_date <= ?"
                           " ORDER BY as_of_date DESC LIMIT 1", (today.isoformat(),)).fetchone()
        day = _day(top[0]) if top else None
        if day is None or (today - day).days > SCAN_FRESH_DAYS:
            return {}
        out = {}
        for sym, factor, value in conn.execute(
                "SELECT symbol, factor, value FROM factor_snapshots WHERE as_of_date = ?"
                " AND factor IN ('avg_turnover_cr', 'price')", (top[0],)):
            key = "turnover_cr" if factor == "avg_turnover_cr" else "price"
            out.setdefault(str(sym).upper(), {})[key] = _num(value)
        return out
    except Exception:
        return {}


def _symbols(conn, today):
    """Every company with an income statement inside the longest window."""
    since = (today - dt.timedelta(days=ANNUALS_BACK_DAYS)).isoformat()
    return [r[0] for r in conn.execute(
        "SELECT DISTINCT symbol FROM income_statement WHERE period_end >= ?"
        " ORDER BY symbol", (since,))]


def _read(conn, syms, today):
    """{SYMBOL: {"quarters", "annuals", "cashflows", "balances": [rows],
    "profile": {sector, price, currency} or None}} for a chunk of companies."""
    marks = ",".join("?" * len(syms))
    out = {s: {"quarters": [], "annuals": [], "cashflows": [], "balances": [], "profile": None}
           for s in syms}
    for part, (table, only, back) in _SOURCES.items():
        since = (today - dt.timedelta(days=back)).isoformat()
        sql = "SELECT %s FROM %s WHERE symbol IN (%s) AND period_end >= ?%s" % (
            ", ".join(_COLUMNS[part]), table, marks, (" AND " + only) if only else "")
        for r in conn.execute(sql, list(syms) + [since]):
            got = out.get(r["symbol"])
            if got is not None:
                got[part].append(dict(r))
    for r in conn.execute("SELECT symbol, sector, price, currency FROM yf_profile"
                          " WHERE symbol IN (%s)" % marks, list(syms)):
        if r["symbol"] in out:
            out[r["symbol"]]["profile"] = dict(r)
    return out


def _company(rows):
    named = [r for r in rows if r.get("company")]
    return max(named, key=lambda r: str(r.get("period_end") or ""))["company"] if named else None


def _price(scan, profile):
    """The scan's close where it has one, else the stored Yahoo price (in
    rupees only)."""
    p = _num((scan or {}).get("price"))
    if p is not None and p > 0:
        return p
    profile = profile or {}
    if str(profile.get("currency") or "INR").upper() != "INR":
        return None
    p = _num(profile.get("price"))
    return p if p is not None and p > 0 else None


# ---------------------------------------------------------------------------
# The three screens. Each takes one company's snapshot and returns its match
# (with "keys": what it is ordered by) or None.
# ---------------------------------------------------------------------------

def _steady_grower(snap, ctx):
    if not snap.get("quarter"):
        return None                          # no quarter recent enough to judge
    fin = bool(snap.get("is_financial"))
    run = snap.get("revenue_yoy_4q")
    four = bool(run) and all(v is not None and v > RUN_MIN_PCT for v in run)
    pair = [snap.get("revenue_yoy_pct"), snap.get("prev_revenue_yoy_pct")]
    chg = None if fin else snap.get("opm_yoy_chg")
    # The widening margin is what admits the slower growth of the second
    # route, so it is a figure the route needs, not a safety test to skip: a
    # lender, with no operating margin, is listed on the first route alone.
    two = all(v is not None and v >= PAIR_MIN_PCT for v in pair) and \
        chg is not None and chg >= PAIR_MARGIN_PTS
    if not (four or two):
        return None
    pat, ttm = snap.get("pat_cr"), snap.get("pat_ttm_cr")
    if not _known(pat, ttm) or pat <= 0 or ttm <= 0:
        return None
    if not fin:
        opm = snap.get("opm_pct")
        if opm is not None and opm < OPM_FLOOR_PCT:
            return None
        if chg is not None and chg < -OPM_DROP_MAX_PTS:
            return None
    turnover = ctx.get("turnover_cr")
    if turnover is not None and turnover < MIN_TURNOVER_CR:
        return None
    shown = run if run else pair
    q = snap["quarter"]
    figures = [_fig("Revenue YoY, " + label, v, "pct")
               for label, v in zip(_quarters_back(q, len(shown)), shown)]
    if not fin:
        figures += [_fig("Operating margin, " + q, snap.get("opm_pct"), "pct"),
                     _fig("Operating margin vs a year earlier", chg, "pts")]
    figures.append(_fig("PAT YoY, " + q, snap.get("pat_yoy_pct"), "pct"))
    # The growth it is ordered on is the median of the quarters shown, so one
    # quarter against a near-empty year-ago base cannot carry the order.
    return {"as_of": q, "figures": figures,
            "keys": {"growth": _median(shown), "margin": chg}}


def _turnaround(snap, ctx):
    if not snap.get("quarter"):
        return None
    fin = bool(snap.get("is_financial"))
    pat, pat_before = snap.get("pat_cr"), snap.get("pat_yoy_cr_prev")
    if not _known(pat, pat_before) or not (pat > 0 and pat_before < 0):
        return None
    rev, rev_before = snap.get("revenue_cr"), snap.get("revenue_yoy_cr_prev")
    if not _known(rev, rev_before) or rev <= rev_before:
        return None
    if rev < TURNAROUND_MIN_REVENUE_CR:
        return None
    core, core_before = snap.get("core_ebitda_cr"), snap.get("core_ebitda_yoy_cr_prev")
    if not fin and (not _known(core, core_before) or core <= 0 or core <= core_before):
        return None
    pbt = snap.get("pbt_cr")
    if not fin and _share_ok(snap.get("other_income_cr"), pbt, OTHER_INCOME_MAX_SHARE) is False:
        return None
    if _share_ok(snap.get("exceptional_cr"), pbt, EXCEPTIONAL_MAX_SHARE) is False:
        return None
    now, then = _margin(pat, rev), _margin(pat_before, rev_before)
    swing = now - then if _known(now, then) else None
    q = snap["quarter"]
    figures = [_fig("PAT, " + q, pat, "cr"),
               _fig("PAT, " + _year_ago_label(q), pat_before, "cr"),
               _fig("Revenue YoY", snap.get("revenue_yoy_pct"), "pct"),
               _fig("Net margin vs a year earlier", swing, "pts")]
    if not fin:
        figures.append(_fig("EBITDA excluding exceptional items, " + q, core, "cr"))
    order = (_clamp(now, MARGIN_CLAMP_PCT) - _clamp(then, MARGIN_CLAMP_PCT)
             if swing is not None else None)
    return {"as_of": q, "figures": figures, "keys": {"swing": order}}


def _fcf_compounder(snap, ctx):
    if snap.get("is_financial"):
        return None
    if snap.get("fcf_pos_years_3y") != FCF_YEARS:
        return None
    # Worked out only against a positive profit of the same year, so a known
    # figure above 1 is "operating cash flow above a positive profit".
    cfo_pat = snap.get("cfo_to_pat")
    if cfo_pat is None or cfo_pat <= 1.0:
        return None
    de = snap.get("debt_equity_x")
    liquid, debt = snap.get("liquid_cr"), snap.get("total_borrowings_cr")
    net_cash = liquid - debt if _known(liquid, debt) else None
    if not ((de is not None and de <= DE_MAX) or (net_cash is not None and net_cash > 0)):
        return None
    cagr = snap.get("rev_cagr_3y")
    if cagr is None or cagr < REV_CAGR_MIN_PCT:
        return None
    roce = snap.get("roce_pct")
    if roce is not None and roce < ROCE_MIN_PCT:
        return None
    mcap = FS.valuation(snap, ctx.get("price")).get("market_cap_cr")
    fcf = snap.get("fcf_cr")
    fcf_yield = fcf / mcap * 100.0 if (_known(fcf, mcap) and mcap > 0) else None
    fy = _fy_label(snap.get("fy_end"))
    figures = [_fig("Free cash flow, last %d years" % FCF_YEARS, snap.get("fcf_3y_cr"), "cr"),
               _fig("Operating cash flow ÷ PAT" + (", " + fy if fy else ""), cfo_pat, "x"),
               (_fig("Net cash", net_cash, "cr") if net_cash is not None and net_cash > 0
                else _fig("Debt ÷ equity", de, "x")),
               _fig("ROCE", roce, "pct"),
               _fig("Revenue CAGR, 3 years", cagr, "pct")]
    if fcf_yield is not None:
        figures.append(_fig("FCF yield", fcf_yield, "pct"))
    return {"as_of": fy, "figures": figures, "keys": {"fcf_yield": fcf_yield, "roce": roce}}


_TESTS = {"steady_growers": _steady_grower, "turnarounds": _turnaround,
          "fcf_compounders": _fcf_compounder}


def _order(screen_id, rows):
    """Each match's "sort", (tier, value), and the list in that order: tier
    first, the higher value first within it, then by symbol. A company whose
    ordering figure is unknown is in a later tier, never ranked as a 0."""
    if screen_id == "steady_growers":
        growth = _pct_ranks({m["symbol"]: m["keys"]["growth"] for m in rows})
        margin = _pct_ranks({m["symbol"]: m["keys"]["margin"] for m in rows})
        for m in rows:
            blend = _mean([growth.get(m["symbol"]), margin.get(m["symbol"])])
            m["sort"] = (0, blend) if blend is not None else (1, 0.0)
    elif screen_id == "turnarounds":
        for m in rows:
            swing = m["keys"]["swing"]
            m["sort"] = (0, swing) if swing is not None else (1, 0.0)
    else:
        for m in rows:
            k = m["keys"]
            m["sort"] = ((0, k["fcf_yield"]) if k["fcf_yield"] is not None else
                         (1, k["roce"]) if k["roce"] is not None else (2, 0.0))
    for m in rows:
        m.pop("keys", None)
    rows.sort(key=lambda m: (m["sort"][0], -m["sort"][1], m["symbol"]))
    return rows


# ---------------------------------------------------------------------------
# The whole market
# ---------------------------------------------------------------------------

def evaluate(conn=None, today=None, market=None):
    """
    Every screen over the whole store: {screen_id: [match, ...]}, each list
    in its screen's order. A match is {"symbol", "company", "as_of",
    "figures": [{"label", "value", "unit"}], "sort"}; unit is "pct", "pts"
    (percentage points), "x" (a multiple) or "cr" (₹ crore).

    `market` is {SYMBOL: {"turnover_cr", "price"}}; left out, it is the
    latest scan's (_scan_market).
    """
    conn = conn or store._connect()
    today = _day(today) or dt.date.today()
    market = _scan_market(today) if market is None else (market or {})
    sectors = _nse_industries()
    out = {s["id"]: [] for s in SCREENS}
    syms = _symbols(conn, today)
    for i in range(0, len(syms), CHUNK):
        chunk = syms[i:i + CHUNK]
        for sym, got in _read(conn, chunk, today).items():
            try:
                profile = got["profile"] or {}
                snap = FS.build(got["quarters"], got["annuals"], got["cashflows"], got["balances"],
                                sector=sectors.get(sym) or profile.get("sector"), asof=today)
                if not snap:
                    continue
                scan = market.get(sym) or {}
                ctx = {"turnover_cr": _num(scan.get("turnover_cr")), "price": _price(scan, profile)}
                company = _company(got["quarters"]) or _company(got["annuals"])
                for screen_id, test in _TESTS.items():
                    m = test(snap, ctx)
                    if m is not None:
                        out[screen_id].append({"symbol": sym, "company": company, **m})
            except Exception:
                # One company's unreadable filing costs that company its
                # place, never the whole market its screens.
                continue
    return {k: _order(k, v) for k, v in out.items()}


def _key(conn):
    return tuple(conn.execute("SELECT MAX(updated_utc) FROM %s" % t).fetchone()[0]
                 for t in ("income_statement", "cash_flow", "balance_sheet"))


def _run(today=None):
    """Every screen, cached for an hour and until the tables change."""
    conn = store._connect()
    key = _key(conn)

    def cached():
        with _lock:
            fresh = time.time() - _cache["at"] < CACHE_SECONDS
            if _cache["result"] is not None and fresh and _cache["key"] == key and today is None:
                return _cache["result"]
        return None

    hit = cached()
    if hit is not None:
        return hit
    with _compute_lock:
        hit = cached()
        if hit is not None:
            return hit
        res = evaluate(conn, today)
        held = conn.execute("SELECT COUNT(DISTINCT symbol) FROM income_statement").fetchone()[0]
        result = {"results": res, "companies_held": held,
                  "computed_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}
        if today is None:
            with _lock:
                _cache.update(at=time.time(), key=key, result=result)
    return result


def resolve(screen_id):
    """The screen an id names, an old id included; None for an unknown one."""
    return _BY_ID.get(str(screen_id or "").strip().lower())


def index(today=None):
    """Every screen with how many companies meet it."""
    if store is None or FS is None:
        return {"available": False, "message": "The fundamentals tables are not available."}
    r = _run(today)
    return {"available": True, "companies_held": r["companies_held"],
            "computed_utc": r["computed_utc"], "notice": NOTICE,
            "screens": [{**s, "count": len(r["results"][s["id"]])} for s in SCREENS]}


def detail(screen_id, limit=200, today=None):
    """One screen: its rule and every company that meets it, with the figures.
    An old id answers with the screen that took it over."""
    if store is None or FS is None:
        return {"available": False, "message": "The fundamentals tables are not available."}
    s = resolve(screen_id)
    if s is None:
        return None
    r = _run(today)
    rows = r["results"][s["id"]]
    cap = max(1, min(int(limit or 200), 2000))
    return {"available": True, "screen": s, "count": len(rows),
            "companies_held": r["companies_held"], "computed_utc": r["computed_utc"],
            "notice": NOTICE,
            "matches": [{k: v for k, v in m.items() if k != "sort"} for m in rows[:cap]]}
