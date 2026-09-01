"""
Altaha Screener — the factor library

WHY THIS EXISTS
The technical score is twelve checks with roughly five and a half independent
ideas in it, and all five and a half are price momentum. Trend structure and
52-week position correlate at 0.86; RSI and Bollinger position at 0.70. That
is one signal wearing twelve hats, which is why it looks robust and is not.

No amount of reweighting fixes that. A score built from one idea has the
predictive ceiling of one idea. The only way past it is to add ideas that are
genuinely different — signals whose good days and bad days do not line up with
momentum's.

WHAT IS HERE, AND WHY EACH ONE
  momentum_12_1     Twelve-month return, skipping the most recent month. The
                    skip is the whole point: over one to four weeks stocks
                    REVERSE, and including the last month mixes a positive
                    signal with a negative one. This is the single most
                    likely reason the current score measures near zero at a
                    one-month horizon.
  reversal_5d       The other side of that coin, isolated and given its own
                    sign: last week's losers tend to bounce. Mechanically
                    anti-correlated with momentum, which is exactly what a
                    portfolio of signals needs.
  trend_quality     How straight the advance was, not how big. A stock that
                    climbed steadily and one that gapped once and drifted have
                    the same return and are not the same setup.
  low_volatility    Realised volatility, negated. Low-volatility stocks have
                    outperformed on a risk-adjusted basis for decades, which
                    no efficient-market account has ever explained away.
  volume_shock      Turnover against its own history. Attention, not
                    direction — read alongside a directional factor, never on
                    its own.
  earnings_yield    Trailing EPS over price. The value factor, and the one
                    family missing from this engine entirely.
  earnings_growth   Profit after tax, year on year, from the company's own
                    filing rather than a data vendor's summary.
  revenue_growth    The same for the top line, which is harder to manage.
  margin_trend      EBITDA margin, this quarter against the same quarter last
                    year. Direction of the business, not its level.
  return_on_assets  Annualised, from the filing.

POINT-IN-TIME DISCIPLINE
Every price factor is computed from a frame the caller has already truncated;
this module never reaches past the end of what it is given. Every fundamental
factor takes XBRL quarters and a cutoff date, and drops any filing the market
had not yet seen — the `filed_at` field, not the period end, decides. A number
from the December quarter was not knowable in December; it was knowable in
February when the company filed it.

SIGN CONVENTION
Every factor is oriented so that HIGHER IS BETTER. Volatility and reversal are
negated at source. Anything downstream can therefore rank without needing to
remember which way each one points, and a factor that gets its sign wrong
shows up as a negative IC rather than as a silent subtraction.
"""

import datetime as dt
import math

try:
    import numpy as np
    import pandas as pd
except Exception:                                  # pragma: no cover
    np = pd = None


# name -> (family, human label)
REGISTRY = {
    "momentum_12_1":    ("momentum",   "12-month momentum, last month skipped"),
    "trend_quality":    ("momentum",   "Straightness of the advance"),
    "reversal_5d":      ("reversal",   "One-week reversal"),
    "low_volatility":   ("volatility", "Realised volatility (negated)"),
    "volume_shock":     ("attention",  "Turnover against its own history"),
    "earnings_yield":   ("value",      "Trailing earnings yield"),
    "earnings_growth":  ("growth",     "Profit after tax, year on year"),
    "revenue_growth":   ("growth",     "Revenue, year on year"),
    "margin_trend":     ("quality",    "EBITDA margin change, year on year"),
    "return_on_assets": ("quality",    "Return on assets, annualised"),
}

FAMILIES = sorted({f for f, _ in REGISTRY.values()})


def _closes(df):
    if df is None or "Close" not in getattr(df, "columns", []):
        return None
    c = df["Close"].dropna()
    return c if len(c) else None


# --------------------------------------------------------------------------
# Price factors
# --------------------------------------------------------------------------

def momentum_12_1(df):
    """
    Return from 12 months ago to one month ago. 252 and 21 sessions.

    Skipping the last month is not a refinement, it is the difference between
    a factor that works and one that cancels itself out.
    """
    c = _closes(df)
    if c is None or len(c) < 260:
        return None
    old, recent = float(c.iloc[-252]), float(c.iloc[-21])
    if old <= 0:
        return None
    return (recent / old - 1.0) * 100.0


def reversal_5d(df):
    """Last week's return, negated. Losers bounce."""
    c = _closes(df)
    if c is None or len(c) < 8:
        return None
    old = float(c.iloc[-6])
    if old <= 0:
        return None
    return -((float(c.iloc[-1]) / old - 1.0) * 100.0)


def trend_quality(df, window=90):
    """
    R² of log price against time. Zero to one hundred.

    Deliberately NOT the slope. Two stocks up 30% over a quarter, one in a
    straight line and one on a single gap and three months of drift, score the
    same on momentum and should not score the same here.
    """
    c = _closes(df)
    if c is None or len(c) < window:
        return None
    px = np.asarray(c.iloc[-window:], dtype=float)
    if not np.all(px > 0):
        return None
    y = np.log(px)
    if not np.all(np.isfinite(y)):
        return None
    x = np.arange(len(y), dtype=float)
    vx = x.var()
    if vx <= 0 or y.var() <= 0:
        return None
    r = float(((x - x.mean()) * (y - y.mean())).mean() / math.sqrt(vx * y.var()))
    # Signed: a straight line DOWN is a high-quality downtrend, and rewarding
    # it as though it were an uptrend is the obvious way to get this wrong.
    return (r ** 2) * 100.0 * (1.0 if r > 0 else -1.0)


def low_volatility(df, window=60):
    """Annualised realised volatility, negated so higher is calmer."""
    c = _closes(df)
    if c is None or len(c) < window + 1:
        return None
    px = np.asarray(c.iloc[-(window + 1):], dtype=float)
    if not np.all(px > 0):
        return None
    r = np.diff(np.log(px))
    if not np.all(np.isfinite(r)) or r.std() <= 0:
        return None
    return -float(r.std() * math.sqrt(252) * 100.0)


def volume_shock(df, recent=5, base=60):
    """
    Recent turnover against its own median. Log-scaled, because turnover is
    lognormal and a raw ratio makes one frantic day dominate a whole universe.

    Attention only. It says people are looking, not that they are right.
    """
    if df is None or "Volume" not in getattr(df, "columns", []):
        return None
    c = _closes(df)
    if c is None or len(c) < base + recent:
        return None
    turn = (df["Close"] * df["Volume"]).dropna()
    if len(turn) < base + recent:
        return None
    r = float(turn.iloc[-recent:].mean())
    b = float(turn.iloc[-(base + recent):-recent].median())
    if b <= 0 or r <= 0:
        return None
    return math.log(r / b) * 100.0


# --------------------------------------------------------------------------
# Fundamental factors, from the company's own filing
# --------------------------------------------------------------------------

def _parse_filed(q):
    """The date the market learned this. Not the period end."""
    raw = q.get("filed_at") or q.get("filing_date")
    if not raw:
        return None
    txt = str(raw)[:11].strip()
    for fmt in ("%d-%b-%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return dt.datetime.strptime(txt[:len(dt.datetime.now().strftime(fmt))], fmt).date()
        except Exception:
            continue
    try:
        return dt.date.fromisoformat(txt[:10])
    except Exception:
        return None


def known_quarters(quarters, as_of=None, consolidated=None):
    """
    The filings the market had actually seen on `as_of`, newest first.

    This function is the point-in-time guarantee for everything fundamental.
    Using the period end instead of the filing date would credit the engine
    with knowing December's profit in December, six weeks before the company
    published it — the single most common way a backtest flatters itself.
    """
    if not quarters:
        return []
    cutoff = as_of or dt.date.today()
    if isinstance(cutoff, str):
        try:
            cutoff = dt.date.fromisoformat(cutoff[:10])
        except Exception:
            cutoff = dt.date.today()
    out = []
    for q in quarters:
        filed = _parse_filed(q)
        if filed is None or filed > cutoff:
            continue
        if consolidated is not None and bool(q.get("consolidated")) != bool(consolidated):
            continue
        out.append((filed, q))
    out.sort(key=lambda t: (t[0], str((t[1].get("period") or {}).get("to") or "")), reverse=True)
    return [q for _f, q in out]


def _period_to(q):
    p = q.get("period") or {}
    return str(p.get("to") or "")[:10]


def _same_quarter_last_year(known, latest):
    """
    The matching quarter twelve months earlier.

    Matched on the period label rather than by counting back four filings:
    a company that missed or restated a quarter would otherwise be compared
    against the wrong one, silently.
    """
    want = latest.get("quarter")
    end = _period_to(latest)
    if not end:
        return None
    try:
        target = dt.date.fromisoformat(end) - dt.timedelta(days=365)
    except Exception:
        return None
    best, gap = None, 75
    for q in known:
        if q is latest:
            continue
        if want and q.get("quarter") and q["quarter"] != want:
            continue
        e = _period_to(q)
        if not e:
            continue
        try:
            d = abs((dt.date.fromisoformat(e) - target).days)
        except Exception:
            continue
        if d < gap:
            best, gap = q, d
    return best


def _growth(now, then):
    if now is None or then is None:
        return None
    try:
        now, then = float(now), float(then)
    except (TypeError, ValueError):
        return None
    if then == 0:
        return None
    # A swing through zero has no meaningful percentage. Reporting one turns a
    # loss-making company that lost slightly less into a 300% grower.
    if then < 0 or now < 0:
        return None
    return (now / then - 1.0) * 100.0


def fundamental_factors(quarters, price=None, as_of=None, consolidated=None):
    """
    Growth, margin direction, return on assets and earnings yield, all from
    filings the market had already seen on `as_of`.
    """
    known = known_quarters(quarters, as_of, consolidated)
    out = {"earnings_growth": None, "revenue_growth": None,
           "margin_trend": None, "return_on_assets": None, "earnings_yield": None}
    if not known:
        return out

    latest = known[0]
    prior = _same_quarter_last_year(known, latest)

    if prior:
        out["earnings_growth"] = _growth(latest.get("pat"), prior.get("pat"))
        out["revenue_growth"] = _growth(latest.get("revenue"), prior.get("revenue"))
        a, b = latest.get("ebitda_margin_pct"), prior.get("ebitda_margin_pct")
        if a is not None and b is not None:
            out["margin_trend"] = float(a) - float(b)

    roa = latest.get("roa_annualised_pct")
    if roa is not None:
        try:
            out["return_on_assets"] = float(roa)
        except (TypeError, ValueError):
            pass

    # Trailing twelve months of EPS over price. Four consecutive quarters or
    # nothing — annualising one quarter would rank a seasonal business on
    # whichever quarter it last reported.
    if price:
        eps = []
        seen = set()
        for q in known:
            e = q.get("eps_basic")
            key = _period_to(q)
            if e is None or not key or key in seen:
                continue
            seen.add(key)
            try:
                eps.append(float(e))
            except (TypeError, ValueError):
                continue
            if len(eps) == 4:
                break
        if len(eps) == 4:
            try:
                p = float(price)
                if p > 0:
                    out["earnings_yield"] = sum(eps) / p * 100.0
            except (TypeError, ValueError):
                pass
    return out


# --------------------------------------------------------------------------
# One call
# --------------------------------------------------------------------------

def compute(df, quarters=None, price=None, as_of=None, consolidated=None):
    """
    Every factor for one stock, as a flat {name: value_or_None} dict.

    None is a first-class answer and means "not knowable here", never zero.
    A missing factor scored as zero ranks the stock at the bottom of that
    factor, which is a claim the data does not support.
    """
    if np is None:
        return {k: None for k in REGISTRY}

    if price is None:
        c = _closes(df)
        price = float(c.iloc[-1]) if c is not None else None

    def safe(fn, *a):
        try:
            v = fn(*a)
        except Exception:
            return None
        if v is None:
            return None
        try:
            v = float(v)
        except (TypeError, ValueError):
            return None
        return v if math.isfinite(v) else None

    out = {
        "momentum_12_1": safe(momentum_12_1, df),
        "trend_quality": safe(trend_quality, df),
        "reversal_5d": safe(reversal_5d, df),
        "low_volatility": safe(low_volatility, df),
        "volume_shock": safe(volume_shock, df),
    }
    try:
        out.update(fundamental_factors(quarters or [], price, as_of, consolidated))
    except Exception:
        for k in ("earnings_yield", "earnings_growth", "revenue_growth",
                  "margin_trend", "return_on_assets"):
            out.setdefault(k, None)
    return {k: out.get(k) for k in REGISTRY}
