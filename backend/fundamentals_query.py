"""
fundamentals_query.py — ask the whole market your own question

WHAT THIS IS
The screens (fundamentals_screens.py) and the lenses (lens_engine.py) answer
questions somebody else wrote. This answers the reader's own, typed in plain
words the way a screener's query box does:

    Market cap > 500 AND ROE > 15 AND Debt to equity < 0.5
    (Sales growth 3Y > 15 OR Profit growth 3Y > 20) AND PE < 30
    Industry contains "pharma" AND OPM > Industry OPM      <- not supported: see FIELDS

Two parts:

  snapshot()  one flat row of named figures per company — size, valuation,
              returns, growth, margins, the balance sheet, cash flow and
              ownership — built from the same stored statements and the same
              lens_metrics.Company arithmetic the lenses use, so a ROE here is
              the ROE a lens tested. Cached until the tables change.

  run(q)      parses the query with a small recursive-descent parser (never
              eval) and applies it to every row.

THE GRAMMAR
    query   := or
    or      := and ( OR and )*
    and     := not ( (AND | newline) not )*
    not     := NOT not | cmp
    cmp     := sum ( ( > | >= | < | <= | = | != | CONTAINS ) sum )?
    sum     := prod ( ( + | - ) prod )*
    prod    := unary ( ( * | / ) unary )*
    unary   := - unary | atom
    atom    := number | "text" | field name | ( query )

A field name is any run of words ("Return on equity", "roe", "ROE 3Y avg");
case, spacing and punctuation do not matter, and every field has a few
aliases. A line break between two conditions means AND, so a query can be
written one condition per line.

MISSING FIGURES ARE UNKNOWN, NOT ZERO
A company whose ROE cannot be computed does not have a ROE of 0, so it neither
passes nor fails "ROE > 15" — it is unknown, and left out of the matches. The
logic is three-valued (true / false / unknown): "unknown OR true" is true,
"unknown AND false" is false. The response counts the companies left out as
unknown, so "12 match" is never read as "everything else failed". Division by
zero or by a negative denominator is unknown for the same reason.

NOT A RECOMMENDATION
A company in the results meets the reader's stated condition on the figures
shown. Nothing is ranked as good or bad; the sort is whatever the reader asked.

NO EXTERNAL DEPENDENCIES. Standard library only (plus the project's own
lens_metrics / lens_store / fundamentals_store).
"""

import datetime as dt
import difflib
import math
import re
import threading
import time

try:
    import fundamentals_store as store
except Exception:                                   # pragma: no cover
    store = None

import lens_metrics as LM

CACHE_SECONDS = 3600
MAX_QUERY_CHARS = 2000
MAX_LIMIT = 500

NOTICE = ("Results are companies whose filed figures meet the condition you "
          "typed. They are filters, not recommendations.")

# ---------------------------------------------------------------------------
# The fields
#
# id, label, unit, group, description, aliases. Units: cr (₹ crore), inr (₹),
# pct, x (a multiple), num, text. The label is what the reader sees and can
# type; every alias is also accepted.
# ---------------------------------------------------------------------------

FIELDS = [
    # Size and valuation
    ("price", "Current price", "inr", "Valuation",
     "Latest closing price.", ["price", "cmp", "ltp", "share price"]),
    ("market_cap", "Market cap", "cr", "Valuation",
     "Price × issued shares, in ₹ crore.",
     ["market capitalization", "market capitalisation", "mcap", "m cap", "mkt cap"]),
    ("pe", "PE", "x", "Valuation",
     "Price ÷ earnings per share over the last four quarters. Unknown when "
     "earnings are not positive.",
     ["price to earning", "price to earnings", "p/e", "pe ratio", "stock pe"]),
    ("pb", "Price to book", "x", "Valuation",
     "Market cap ÷ shareholders' equity on the latest balance sheet.",
     ["pb", "p/b", "price to book value", "pbv"]),
    ("earnings_yield", "Earnings yield", "pct", "Valuation",
     "Trailing earnings per share ÷ price. The inverse of PE.", ["ey"]),
    ("ev_ebitda", "EV to EBITDA", "x", "Valuation",
     "(Market cap + debt − cash) ÷ latest full-year EBITDA.",
     ["ev/ebitda", "enterprise value to ebitda", "ev ebitda"]),
    ("enterprise_value", "Enterprise value", "cr", "Valuation",
     "Market cap + borrowings − cash and current investments.", ["ev"]),

    # Returns
    ("roe", "ROE", "pct", "Returns",
     "Return on equity, latest full year: profit after tax ÷ shareholders' equity.",
     ["return on equity"]),
    ("roce", "ROCE", "pct", "Returns",
     "Return on capital employed, latest full year: EBIT ÷ (total assets − current liabilities).",
     ["return on capital employed"]),
    ("roe_3y", "ROE 3Y avg", "pct", "Returns",
     "Average ROE over the last three full years.",
     ["average return on equity 3years", "avg roe 3y", "roe 3 year", "roe 3years"]),
    ("roce_3y", "ROCE 3Y avg", "pct", "Returns",
     "Average ROCE over the last three full years.",
     ["average return on capital employed 3years", "avg roce 3y", "roce 3 year", "roce 3years"]),
    ("roa", "ROA", "pct", "Returns",
     "Return on assets, latest full year: profit after tax ÷ total assets.",
     ["return on assets"]),

    # The P&L, full year
    ("sales", "Sales", "cr", "Profit & loss",
     "Revenue from operations, latest full year.", ["revenue", "sales annual", "turnover"]),
    ("ebitda", "EBITDA", "cr", "Profit & loss",
     "Operating profit before depreciation, latest full year.", ["operating profit"]),
    ("net_profit", "Net profit", "cr", "Profit & loss",
     "Profit after tax, latest full year.", ["pat", "profit after tax", "profit"]),
    ("eps", "EPS", "inr", "Profit & loss",
     "Basic earnings per share, latest full year.", ["earnings per share"]),
    ("opm", "OPM", "pct", "Profit & loss",
     "EBITDA ÷ sales, latest full year.",
     ["operating profit margin", "ebitda margin", "operating margin"]),
    ("npm", "Net margin", "pct", "Profit & loss",
     "Profit after tax ÷ sales, latest full year.", ["npm", "net profit margin", "pat margin"]),
    ("interest_coverage", "Interest coverage", "x", "Profit & loss",
     "EBIT ÷ finance cost, latest full year.", ["interest cover", "icr"]),

    # Trailing twelve months
    ("sales_ttm", "Sales TTM", "cr", "Trailing 12 months",
     "Revenue over the last four quarters.", ["revenue ttm", "sales 12m"]),
    ("net_profit_ttm", "Net profit TTM", "cr", "Trailing 12 months",
     "Profit after tax over the last four quarters.", ["pat ttm", "profit ttm"]),
    ("eps_ttm", "EPS TTM", "inr", "Trailing 12 months",
     "Earnings per share over the last four quarters.", ["ttm eps"]),

    # Growth
    ("sales_growth", "Sales growth", "pct", "Growth",
     "Revenue, latest full year against the one before.",
     ["revenue growth", "sales growth 1y", "sales growth 1 year"]),
    ("sales_growth_3y", "Sales growth 3Y", "pct", "Growth",
     "Revenue CAGR over three full years.",
     ["sales growth 3years", "revenue growth 3y", "sales cagr 3y", "revenue cagr 3y"]),
    ("sales_growth_5y", "Sales growth 5Y", "pct", "Growth",
     "Revenue CAGR over five full years.",
     ["sales growth 5years", "revenue growth 5y", "sales cagr 5y", "revenue cagr 5y"]),
    ("profit_growth", "Profit growth", "pct", "Growth",
     "Profit after tax, latest full year against the one before. Unknown when "
     "the earlier year was a loss.", ["pat growth", "profit growth 1y", "net profit growth"]),
    ("profit_growth_3y", "Profit growth 3Y", "pct", "Growth",
     "Profit after tax CAGR over three full years.",
     ["profit growth 3years", "pat growth 3y", "profit cagr 3y"]),
    ("profit_growth_5y", "Profit growth 5Y", "pct", "Growth",
     "Profit after tax CAGR over five full years.",
     ["profit growth 5years", "pat growth 5y", "profit cagr 5y"]),
    ("eps_growth_3y", "EPS growth 3Y", "pct", "Growth",
     "EPS CAGR over three full years.", ["eps growth 3years", "eps cagr 3y"]),

    # Latest quarter
    ("sales_qtr", "Sales latest quarter", "cr", "Latest quarter",
     "Revenue in the latest quarter.", ["sales quarter", "revenue quarter", "qtr sales"]),
    ("net_profit_qtr", "Net profit latest quarter", "cr", "Latest quarter",
     "Profit after tax in the latest quarter.", ["profit quarter", "pat quarter", "qtr profit"]),
    ("opm_qtr", "OPM latest quarter", "pct", "Latest quarter",
     "Operating margin in the latest quarter.", ["opm quarter", "qtr opm"]),
    ("sales_growth_qtr", "Sales growth YoY quarter", "pct", "Latest quarter",
     "Latest quarter's revenue against the same quarter a year earlier.",
     ["yoy quarterly sales growth", "quarterly sales growth", "qtr sales growth", "sales yoy"]),
    ("profit_growth_qtr", "Profit growth YoY quarter", "pct", "Latest quarter",
     "Latest quarter's profit against the same quarter a year earlier.",
     ["yoy quarterly profit growth", "quarterly profit growth", "qtr profit growth", "profit yoy"]),

    # Balance sheet
    ("debt", "Debt", "cr", "Balance sheet",
     "Total borrowings on the latest balance sheet.", ["borrowings", "total debt"]),
    ("cash", "Cash", "cr", "Balance sheet",
     "Cash, bank balances and current investments on the latest balance sheet.",
     ["cash and equivalents"]),
    ("net_debt", "Net debt", "cr", "Balance sheet",
     "Debt − cash. Negative means more cash than debt.", []),
    ("debt_to_equity", "Debt to equity", "x", "Balance sheet",
     "Borrowings ÷ shareholders' equity, latest balance sheet.",
     ["de", "d/e", "debt equity", "debt/equity"]),
    ("current_ratio", "Current ratio", "x", "Balance sheet",
     "Current assets ÷ current liabilities, latest balance sheet.", ["cr ratio"]),
    ("net_worth", "Net worth", "cr", "Balance sheet",
     "Shareholders' equity on the latest balance sheet.",
     ["book value", "equity", "shareholders equity"]),
    ("total_assets", "Total assets", "cr", "Balance sheet",
     "Total assets on the latest balance sheet.", ["assets"]),

    # Cash flow
    ("cfo", "Operating cash flow", "cr", "Cash flow",
     "Cash from operations, latest full year.", ["cash from operations", "ocf"]),
    ("fcf", "Free cash flow", "cr", "Cash flow",
     "Operating cash flow − capex, latest full year.", ["free cash flow 1y"]),
    ("fcf_3y", "Free cash flow 3Y", "cr", "Cash flow",
     "Free cash flow summed over the last three full years.",
     ["free cash flow 3years", "fcf 3 years"]),
    ("cfo_to_pat", "Cash conversion", "x", "Cash flow",
     "Operating cash flow ÷ profit after tax, latest full year.",
     ["cfo to pat", "ocf to pat", "cfo/pat"]),
    ("dividend_payout", "Dividend payout", "pct", "Cash flow",
     "Dividends paid ÷ profit after tax, latest full year.",
     ["dividend payout ratio", "payout"]),
    ("dividend_yield", "Dividend yield", "pct", "Cash flow",
     "Dividends paid in the latest full year ÷ market cap.", ["yield"]),

    # Ownership
    ("promoter_holding", "Promoter holding", "pct", "Ownership",
     "Promoter and promoter group stake, latest shareholding filing.",
     ["promoter", "promoters", "promoter stake"]),
    ("promoter_change", "Promoter holding change 1Y", "pct", "Ownership",
     "Change in promoter stake over a year, percentage points.",
     ["change in promoter holding", "promoter change"]),
    ("pledged", "Pledged percentage", "pct", "Ownership",
     "Promoter shares pledged, as a percentage of all shares.",
     ["pledge", "pledged", "pledge pct", "promoter pledge"]),
    ("fii_holding", "FII holding", "pct", "Ownership",
     "Foreign institutional stake, latest shareholding filing.", ["fii", "fpi", "fpi holding"]),
    ("dii_holding", "DII holding", "pct", "Ownership",
     "Domestic institutional stake, latest shareholding filing.", ["dii"]),

    # Text
    ("name", "Name", "text", "Company",
     "Company name.", ["company", "company name"]),
    ("industry", "Industry", "text", "Company",
     "NSE industry classification.", []),
    ("sector", "Sector", "text", "Company",
     "NSE sector classification.", []),
]

FIELD_BY_ID = {f[0]: {"id": f[0], "label": f[1], "unit": f[2], "group": f[3],
                      "description": f[4]} for f in FIELDS}

DEFAULT_COLUMNS = ["price", "market_cap", "pe", "roce", "roe", "sales_growth_3y"]


def _norm(s):
    return re.sub(r"[^a-z0-9%]", "", str(s).lower())


def _alias_map():
    out = {}
    for fid, label, _u, _g, _d, aliases in FIELDS:
        for name in [fid, label] + list(aliases):
            out.setdefault(_norm(name), fid)
    return out


ALIASES = _alias_map()


def fields():
    """The catalogue the page shows: every field with its group and aliases."""
    return [{"id": f[0], "label": f[1], "unit": f[2], "group": f[3],
             "description": f[4], "aliases": f[5]} for f in FIELDS]


def resolve(name):
    """A typed name to a field id, or None."""
    return ALIASES.get(_norm(name))


def suggest(name, n=3):
    keys = difflib.get_close_matches(_norm(name), list(ALIASES), n=n * 3, cutoff=0.6)
    seen, out = set(), []
    for k in keys:
        fid = ALIASES[k]
        if fid not in seen:
            seen.add(fid)
            out.append(FIELD_BY_ID[fid]["label"])
    return out[:n]


# ---------------------------------------------------------------------------
# One row of figures per company
# ---------------------------------------------------------------------------

_f = LM._f


def _div(a, b, scale=1.0):
    if a is None or b is None or b <= 0:
        return None
    return a / b * scale


def _growth(a, b):
    if a is None or b is None or b <= 0:
        return None
    return (a / b - 1.0) * 100.0


def _r(v, dp=2):
    return None if v is None or not math.isfinite(v) else round(v, dp)


def _ttm(c, key):
    qs = c.quarters[:4]
    if len(qs) < 4:
        return None
    ds = [LM._d(q["period_end"]) for q in qs]
    if any(d is None for d in ds) or (ds[0] - ds[3]).days > 290:
        return None
    vals = [_f(q.get(key)) for q in qs]
    return None if any(v is None for v in vals) else sum(vals)


def _year_quarter_ago(c, top):
    end = LM._d(top["period_end"])
    for q in c.quarters[1:]:
        e = LM._d(q["period_end"])
        if end and e and 350 <= (end - e).days <= 380:
            return q
    return None


def company_row(c, ctx, today=None):
    """Every field for one company. Unknowns are None."""
    today = today or dt.date.today()
    prof = ctx.get("company") or {}
    holdings = ctx.get("shareholding") or []
    y0, y1 = c.year(0), c.year(1)
    y3, y5 = c.year(3), c.year(5)
    b = c.latest_bs()
    b0 = c.bs(y0)
    cf0 = c.cf(y0)
    row = {"symbol": c.symbol, "name": prof.get("company") or c.company,
           "industry": prof.get("industry") or None, "sector": prof.get("sector") or None,
           "basis": c.basis}

    price = LM._price(c, ctx)
    shares = _f(prof.get("issued_shares"))
    mcap = price * shares / 1e7 if price and shares else None
    row["price"] = _r(price)
    row["market_cap"] = _r(mcap)

    # --- The P&L ---
    sales, sales1 = c.revenue(y0), c.revenue(y1)
    pat = _f(y0.get("pat_cr")) if y0 else None
    pat1 = _f(y1.get("pat_cr")) if y1 else None
    ebitda = _f(y0.get("ebitda_cr")) if y0 else None
    ebit = c.ebit(y0)
    fin = _f(y0.get("finance_cost_cr")) if y0 else None
    row.update(sales=_r(sales), ebitda=_r(ebitda), net_profit=_r(pat),
               eps=_r(_f(y0.get("eps_basic")) if y0 else None),
               opm=_r(c.margin(y0)), npm=_r(_div(pat, sales, 100.0)),
               interest_coverage=_r(_div(ebit, fin)))
    row["fy"] = LM.fy_label(y0["period_end"]) if y0 else None

    # --- Returns ---
    row["roe"] = _r(c.roe(y0))
    row["roce"] = _r(c.roce(y0))
    three = c.span(2)
    if three:
        roes = [c.roe(y) for y in three]
        roces = [c.roce(y) for y in three]
        row["roe_3y"] = _r(sum(roes) / 3) if None not in roes else None
        row["roce_3y"] = _r(sum(roces) / 3) if None not in roces else None
    else:
        row["roe_3y"] = row["roce_3y"] = None
    row["roa"] = _r(_div(pat, _f((b0 or {}).get("total_assets_cr")), 100.0))

    # --- Growth ---
    row["sales_growth"] = _r(_growth(sales, sales1))
    row["profit_growth"] = _r(_growth(pat, pat1))
    row["sales_growth_3y"] = _r(LM.cagr(sales, c.revenue(y3), 3)) if y3 else None
    row["sales_growth_5y"] = _r(LM.cagr(sales, c.revenue(y5), 5)) if y5 else None
    row["profit_growth_3y"] = _r(LM.cagr(pat, _f(y3.get("pat_cr")), 3)) if y3 else None
    row["profit_growth_5y"] = _r(LM.cagr(pat, _f(y5.get("pat_cr")), 5)) if y5 else None
    row["eps_growth_3y"] = (_r(LM.cagr(_f(y0.get("eps_basic")), _f(y3.get("eps_basic")), 3))
                            if y0 and y3 else None)

    # --- Trailing twelve months, and valuation off it ---
    eps_ttm = c.ttm_eps(0)
    row["sales_ttm"] = _r(_ttm(c, "revenue_cr"))
    row["net_profit_ttm"] = _r(_ttm(c, "pat_cr"))
    row["eps_ttm"] = _r(eps_ttm)
    eps_for_pe = eps_ttm if eps_ttm is not None else row["eps"]
    row["pe"] = _r(_div(price, eps_for_pe))
    row["earnings_yield"] = _r(_div(eps_for_pe, price, 100.0)) if eps_for_pe is not None else None

    # --- Latest quarter ---
    top = c.quarters[0] if c.quarters else None
    if top and (today - (LM._d(top["period_end"]) or today)).days <= 92 + 62:
        prior = _year_quarter_ago(c, top)
        qs, qp = _f(top.get("revenue_cr")), _f(top.get("pat_cr"))
        row["sales_qtr"], row["net_profit_qtr"] = _r(qs), _r(qp)
        row["opm_qtr"] = _r(c.margin(top))
        row["sales_growth_qtr"] = _r(_growth(qs, _f((prior or {}).get("revenue_cr"))))
        row["profit_growth_qtr"] = _r(_growth(qp, _f((prior or {}).get("pat_cr"))))
        row["quarter"] = top.get("period_end")
    else:
        for k in ("sales_qtr", "net_profit_qtr", "opm_qtr", "sales_growth_qtr",
                  "profit_growth_qtr", "quarter"):
            row[k] = None

    # --- Balance sheet ---
    bs = b or {}
    debt = _f(bs.get("total_borrowings_cr"))
    cash = None
    if bs.get("cash_and_equivalents_cr") is not None:
        cash = sum(_f(bs.get(k)) or 0.0 for k in ("cash_and_equivalents_cr",
                                                   "current_investments_cr",
                                                   "other_bank_balances_cr"))
    equity = _f(bs.get("equity_to_owners_cr"))
    if equity is None:
        equity = _f(bs.get("total_equity_cr"))
    row["debt"], row["cash"] = _r(debt), _r(cash)
    row["net_debt"] = _r(debt - cash) if debt is not None and cash is not None else None
    de = _f(bs.get("debt_equity_x"))
    if de is None:
        de = _div(debt, equity)
    row["debt_to_equity"] = _r(de, 3)
    row["current_ratio"] = _r(_div(_f(bs.get("current_assets_cr")),
                                   _f(bs.get("current_liabilities_cr"))))
    row["net_worth"] = _r(equity)
    row["total_assets"] = _r(_f(bs.get("total_assets_cr")))
    row["pb"] = _r(_div(mcap, equity))
    ev = mcap + debt - cash if None not in (mcap, debt, cash) else None
    row["enterprise_value"] = _r(ev)
    row["ev_ebitda"] = _r(_div(ev, ebitda)) if ev is not None and ev > 0 else None

    # --- Cash flow ---
    cfo = _f((cf0 or {}).get("cfo_cr"))
    row["cfo"] = _r(cfo)
    row["fcf"] = _r(_f((cf0 or {}).get("fcf_cr")))
    if three:
        fcfs = [_f((c.cf(y) or {}).get("fcf_cr")) for y in three]
        row["fcf_3y"] = _r(sum(fcfs)) if None not in fcfs else None
    else:
        row["fcf_3y"] = None
    row["cfo_to_pat"] = _r(_div(cfo, pat))
    div = _f((cf0 or {}).get("dividends_paid_cr"))
    div = abs(div) if div is not None else None
    row["dividend_payout"] = _r(_div(div, pat, 100.0))
    row["dividend_yield"] = _r(_div(div, mcap, 100.0))

    # --- Ownership ---
    q = holdings[0] if holdings else {}
    row["promoter_holding"] = _r(_f(q.get("promoter_pct")))
    row["fii_holding"] = _r(_f(q.get("fii_pct")))
    row["dii_holding"] = _r(_f(q.get("dii_pct")))
    pl = LM._pledge(c, 1, ctx)
    row["pledged"] = _r((pl or {}).get("value"), 4)
    pc = LM._promoter_change(c, 1, ctx)
    row["promoter_change"] = _r((pc or {}).get("value"), 3)
    return row


def _profiles():
    try:
        import lens_store
        return lens_store.companies(), lens_store.shareholding()
    except Exception:
        return {}, {}


def build(conn, today=None, prices=None, profiles=None, holdings=None):
    """[row, ...] for every company in the tables."""
    if profiles is None or holdings is None:
        p, h = _profiles()
        profiles = p if profiles is None else profiles
        holdings = h if holdings is None else holdings
    prices = LM.latest_prices() if prices is None else prices
    rows = []
    # The dividend line is not in lens_metrics' column list; read it apart.
    divs = {}
    try:
        for r in conn.execute("SELECT symbol, basis, period_end, dividends_paid_cr"
                              " FROM cash_flow WHERE months=12"):
            divs[(r[0], r[1], r[2])] = r[3]
    except Exception:
        pass
    for sym, inc, bal, cfs in LM.iter_companies(conn):
        for r in cfs:
            r["dividends_paid_cr"] = divs.get((sym, r.get("basis"), r.get("period_end")))
        c = LM.Company(sym, inc, bal, cfs, today=today)
        if not c.years and not c.quarters:
            continue
        ctx = {"company": profiles.get(sym), "shareholding": holdings.get(sym),
               "prices": prices}
        try:
            rows.append(company_row(c, ctx, today))
        except (ArithmeticError, TypeError, ValueError):
            continue
    return rows


_cache = {"at": 0.0, "key": None, "rows": None, "built_utc": None}
_lock = threading.Lock()


def snapshot():
    """Every company's row, rebuilt hourly or when the tables change."""
    conn = store._connect()
    key = conn.execute("SELECT MAX(updated_utc), COUNT(*) FROM income_statement").fetchone()
    key = tuple(key) + (dt.date.today().isoformat(),)
    with _lock:
        fresh = time.time() - _cache["at"] < CACHE_SECONDS
        if _cache["rows"] is not None and fresh and _cache["key"] == key:
            return _cache["rows"], _cache["built_utc"]
        rows = build(conn)
        _cache.update(at=time.time(), key=key, rows=rows,
                      built_utc=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"))
        return rows, _cache["built_utc"]


# ---------------------------------------------------------------------------
# The query language
# ---------------------------------------------------------------------------

class QueryError(ValueError):
    """A query the reader typed that cannot be run, with a readable reason."""

    def __init__(self, message, position=None, suggestions=None):
        super().__init__(message)
        self.message = message
        self.position = position
        self.suggestions = suggestions or []

    def as_dict(self):
        return {"message": self.message, "position": self.position,
                "suggestions": self.suggestions}


_KEYWORDS = {"and": "AND", "or": "OR", "not": "NOT", "contains": "CONTAINS"}
_OPS = [">=", "<=", "!=", "<>", "==", ">", "<", "=", "+", "-", "*", "/", "(", ")"]
_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_%'.&]*|[0-9]+[A-Za-z][A-Za-z0-9_%]*")
_NUM = re.compile(r"(\d{1,3}(?:,\d{2,3})+|\d+)(\.\d+)?|\.\d+")


def tokenize(text):
    """[(kind, value, position)] with kinds NUM, STR, NAME, OP, KW, NL."""
    out, i, n = [], 0, len(text)
    words = []            # the current run of name words: [(word, pos)]

    def flush():
        if words:
            out.append(("NAME", " ".join(w for w, _p in words), words[0][1]))
            del words[:]

    while i < n:
        ch = text[i]
        if ch == "\n" or ch == ";":
            flush()
            out.append(("NL", ch, i))
            i += 1
            continue
        if ch.isspace():
            i += 1
            continue
        if ch in "\"'" and not words:
            j = text.find(ch, i + 1)
            if j < 0:
                raise QueryError("A quoted text is not closed.", i)
            flush()
            out.append(("STR", text[i + 1:j], i))
            i = j + 1
            continue
        m = _WORD.match(text, i)
        if m and not (ch.isdigit() and not words):
            w = m.group(0)
            kw = _KEYWORDS.get(w.lower())
            if kw:
                flush()
                out.append(("KW", kw, i))
            else:
                words.append((w, i))
            i = m.end()
            continue
        if ch.isdigit() or (ch == "." and i + 1 < n and text[i + 1].isdigit()):
            if words:
                # A number inside a name ("ROE 3 years") belongs to the name.
                m = re.compile(r"[0-9]+").match(text, i)
                words.append((m.group(0), i))
                i = m.end()
                continue
            m = _NUM.match(text, i)
            num = m.group(0).replace(",", "")
            i = m.end()
            # Trailing units that change nothing: "15%", "500 cr", "1,000 crore".
            um = re.compile(r"\s*(%|cr\b|crore\b|crores\b|x\b)", re.I).match(text, i)
            if um:
                i = um.end()
            out.append(("NUM", float(num), m.start()))
            continue
        op = next((o for o in _OPS if text.startswith(o, i)), None)
        if op:
            flush()
            out.append(("OP", {"==": "=", "<>": "!="}.get(op, op), i))
            i += len(op)
            continue
        raise QueryError("'%s' is not something a query can contain." % ch, i)
    flush()
    return out


class _Parser:
    def __init__(self, text):
        self.text = text
        self.toks = tokenize(text)
        self.i = 0
        self.fields = []          # field ids referenced, in order

    def peek(self, skip_nl=False):
        j = self.i
        while skip_nl and j < len(self.toks) and self.toks[j][0] == "NL":
            j += 1
        return self.toks[j] if j < len(self.toks) else None

    def skip_nl(self):
        while self.i < len(self.toks) and self.toks[self.i][0] == "NL":
            self.i += 1

    def take(self):
        t = self.toks[self.i]
        self.i += 1
        return t

    def is_(self, tok, kind, value=None):
        return tok is not None and tok[0] == kind and (value is None or tok[1] == value)

    def parse(self):
        self.skip_nl()
        if self.peek() is None:
            raise QueryError("Type a condition, for example: ROE > 15 AND Debt to equity < 0.5")
        node = self.or_()
        self.skip_nl()
        t = self.peek()
        if t is not None:
            if self.is_(t, "OP", ")"):
                raise QueryError("There is a ')' without a matching '('.", t[2])
            raise QueryError("Expected AND or OR before '%s'." % str(t[1]), t[2])
        return node

    def or_(self):
        node = self.and_()
        while self.is_(self.peek(skip_nl=True), "KW", "OR"):
            self.skip_nl()
            self.take()
            self.skip_nl()
            node = ("or", node, self.and_())
        return node

    def and_(self):
        node = self.not_()
        while True:
            t = self.peek()
            if self.is_(self.peek(skip_nl=True), "KW", "AND"):
                self.skip_nl()
                self.take()
                self.skip_nl()
            elif self.is_(t, "NL"):
                nxt = self.peek(skip_nl=True)
                if nxt is None or self.is_(nxt, "OP", ")") or self.is_(nxt, "KW", "OR"):
                    return node
                self.skip_nl()
            else:
                return node
            node = ("and", node, self.not_())

    def not_(self):
        if self.is_(self.peek(), "KW", "NOT"):
            self.take()
            return ("not", self.not_())
        return self.cmp()

    def cmp(self):
        left = self.sum_()
        t = self.peek()
        if self.is_(t, "OP") and t[1] in (">", ">=", "<", "<=", "=", "!="):
            self.take()
            return ("cmp", t[1], left, self.sum_())
        if self.is_(t, "KW", "CONTAINS"):
            self.take()
            return ("cmp", "contains", left, self.sum_())
        return left

    def sum_(self):
        node = self.prod()
        while self.is_(self.peek(), "OP") and self.peek()[1] in "+-":
            op = self.take()[1]
            node = ("bin", op, node, self.prod())
        return node

    def prod(self):
        node = self.unary()
        while self.is_(self.peek(), "OP") and self.peek()[1] in "*/":
            op = self.take()[1]
            node = ("bin", op, node, self.unary())
        return node

    def unary(self):
        if self.is_(self.peek(), "OP", "-"):
            self.take()
            return ("neg", self.unary())
        return self.atom()

    def atom(self):
        t = self.peek()
        if t is None:
            raise QueryError("The query ends where a value or field was expected.", len(self.text))
        kind, val, pos = t
        if kind == "NUM":
            self.take()
            return ("num", val)
        if kind == "STR":
            self.take()
            return ("str", val)
        if kind == "NAME":
            self.take()
            fid = resolve(val)
            if fid is None:
                sug = suggest(val)
                msg = "'%s' is not a field." % val
                if sug:
                    msg += " Did you mean %s?" % " or ".join("'%s'" % s for s in sug)
                raise QueryError(msg, pos, sug)
            if fid not in self.fields:
                self.fields.append(fid)
            return ("field", fid)
        if self.is_(t, "OP", "("):
            self.take()
            self.skip_nl()
            node = self.or_()
            self.skip_nl()
            if not self.is_(self.peek(), "OP", ")"):
                raise QueryError("A '(' is not closed.", pos)
            self.take()
            return node
        if kind == "NL":
            raise QueryError("A condition is incomplete at the end of a line.", pos)
        raise QueryError("Expected a field or a number before '%s'." % val, pos)


def parse(text):
    """(tree, [field ids]) or QueryError."""
    text = (text or "").strip()
    if len(text) > MAX_QUERY_CHARS:
        raise QueryError("The query is longer than %d characters." % MAX_QUERY_CHARS)
    p = _Parser(text)
    tree = p.parse()
    _check_root(tree)
    return tree, p.fields


def _kind(node):
    k = node[0]
    if k in ("num", "neg", "bin"):
        return "num"
    if k == "str":
        return "text"
    if k == "field":
        return "text" if FIELD_BY_ID[node[1]]["unit"] == "text" else "num"
    return "bool"


def _check_types(node):
    k = node[0]
    if k in ("and", "or"):
        for sub in node[1:]:
            if _kind(sub) != "bool":
                raise QueryError("Each part joined by AND or OR must be a comparison, "
                                 "like ROE > 15.")
            _check_types(sub)
    elif k == "not":
        if _kind(node[1]) != "bool":
            raise QueryError("NOT must be followed by a comparison.")
        _check_types(node[1])
    elif k == "cmp":
        op, a, b = node[1], node[2], node[3]
        ka, kb = _kind(a), _kind(b)
        if "bool" in (ka, kb):
            raise QueryError("A comparison cannot compare another comparison.")
        if op == "contains":
            if ka != "text" or kb != "text":
                raise QueryError("CONTAINS works on text, like Industry contains \"bank\".")
        elif ka != kb:
            raise QueryError("Text can only be compared with text in quotes, "
                             "like Industry = \"Pharmaceuticals\".")
        elif ka == "text" and op not in ("=", "!="):
            raise QueryError("Text can only be compared with = or != or CONTAINS.")
    elif k == "bin":
        if _kind(node[2]) != "num" or _kind(node[3]) != "num":
            raise QueryError("Arithmetic works on numbers only.")


def _check_root(tree):
    if _kind(tree) != "bool":
        raise QueryError("A query needs a comparison, like ROE > 15.")
    _check_types(tree)


def _value(node, row):
    k = node[0]
    if k == "num":
        return node[1]
    if k == "str":
        return node[1]
    if k == "field":
        return row.get(node[1])
    if k == "neg":
        v = _value(node[1], row)
        return None if v is None else -v
    if k == "bin":
        a, b = _value(node[2], row), _value(node[3], row)
        if a is None or b is None:
            return None
        op = node[1]
        if op == "+":
            return a + b
        if op == "-":
            return a - b
        if op == "*":
            return a * b
        return None if b == 0 else a / b
    raise ValueError(k)


def evaluate(node, row):
    """True, False or None (unknown) for one company."""
    k = node[0]
    if k == "and":
        a = evaluate(node[1], row)
        if a is False:
            return False
        b = evaluate(node[2], row)
        if b is False:
            return False
        return None if a is None or b is None else True
    if k == "or":
        a = evaluate(node[1], row)
        if a is True:
            return True
        b = evaluate(node[2], row)
        if b is True:
            return True
        return None if a is None or b is None else False
    if k == "not":
        v = evaluate(node[1], row)
        return None if v is None else not v
    if k == "cmp":
        op = node[1]
        a, b = _value(node[2], row), _value(node[3], row)
        if a is None or b is None:
            return None
        if isinstance(a, str):
            a, b = a.strip().lower(), str(b).strip().lower()
            if op == "contains":
                return b in a
            return (a == b) if op == "=" else (a != b)
        if op == ">":
            return a > b
        if op == ">=":
            return a >= b
        if op == "<":
            return a < b
        if op == "<=":
            return a <= b
        if op == "=":
            return abs(a - b) < 1e-9
        return abs(a - b) >= 1e-9
    raise ValueError(k)


# ---------------------------------------------------------------------------
# Running a query
# ---------------------------------------------------------------------------

def run_rows(rows, q, sort=None, order="desc", limit=50, offset=0, columns=None):
    """Apply a query to rows already built. Raises QueryError."""
    tree, used = parse(q)
    matched, unknown = [], 0
    for r in rows:
        v = evaluate(tree, r)
        if v is True:
            matched.append(r)
        elif v is None:
            unknown += 1

    sort_id = resolve(sort) if sort else None
    if sort and sort_id is None:
        raise QueryError("'%s' is not a field to sort by." % sort, None, suggest(sort))
    if sort_id is None:
        sort_id = next((f for f in used if FIELD_BY_ID[f]["unit"] != "text"), "market_cap")
    desc = str(order).lower() != "asc"

    is_text = FIELD_BY_ID[sort_id]["unit"] == "text"
    have = [r for r in matched if r.get(sort_id) is not None]
    have.sort(key=lambda r: (str(r[sort_id]).lower() if is_text else r[sort_id], r["symbol"]),
              reverse=desc)
    matched = have + [r for r in matched if r.get(sort_id) is None]

    cols = []
    for c in list(columns or []):
        fid = resolve(c)
        if fid and fid not in cols and fid != "name":
            cols.append(fid)
    if not columns:
        for fid in used + DEFAULT_COLUMNS:
            if fid not in cols and fid not in ("name",):
                cols.append(fid)
    limit = max(1, min(int(limit or 50), MAX_LIMIT))
    offset = max(0, int(offset or 0))
    page = matched[offset:offset + limit]
    keep = ["symbol", "name", "industry", "fy", "quarter"] + cols
    return {
        "query": q,
        "fields_used": used,
        "columns": [FIELD_BY_ID[c] for c in cols],
        "sort": sort_id, "order": "desc" if desc else "asc",
        "count": len(matched), "unknown": unknown, "screened": len(rows),
        "offset": offset, "limit": limit,
        "results": [{k: r.get(k) for k in keep} for r in page],
    }


def run(q, sort=None, order="desc", limit=50, offset=0, columns=None):
    """The endpoint: parse, apply to every company, sort, page."""
    if store is None:
        return {"available": False, "message": "The fundamentals tables are not available."}
    parse(q)                    # a bad query fails before the snapshot is built
    rows, built = snapshot()
    out = run_rows(rows, q, sort, order, limit, offset, columns)
    out.update(available=True, computed_utc=built, notice=NOTICE)
    return out


EXAMPLES = [
    {"name": "Profitable and lightly borrowed",
     "query": "ROCE > 20\nDebt to equity < 0.5\nMarket cap > 1000"},
    {"name": "Growing sales and profits",
     "query": "Sales growth 3Y > 15\nProfit growth 3Y > 15\nROE > 15"},
    {"name": "Low PE with a return on capital",
     "query": "PE < 15\nPE > 0\nROCE > 15\nMarket cap > 500"},
    {"name": "Latest quarter: sales and profit up 25%",
     "query": "Sales growth YoY quarter > 25\nProfit growth YoY quarter > 25"},
    {"name": "Cash generative",
     "query": "Free cash flow 3Y > 0\nCash conversion > 1\nNet debt < 0"},
    {"name": "High promoter stake, nothing pledged",
     "query": "Promoter holding > 60\nPledged percentage = 0\nROE > 12"},
    {"name": "Paying dividends out of earnings",
     "query": "Dividend yield > 2\nDividend payout < 70\nProfit growth 3Y > 5"},
]


def meta():
    """The field catalogue and examples, for the page to build its helpers."""
    return {"available": store is not None, "fields": fields(), "examples": EXAMPLES,
            "default_columns": DEFAULT_COLUMNS, "notice": NOTICE}
