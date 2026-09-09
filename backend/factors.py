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
import os

try:
    import numpy as np
    import pandas as pd
except Exception:                                  # pragma: no cover
    np = pd = None


# Compatibility tuple view; SPEC is the canonical, auditable factor registry.
from dataclasses import dataclass

@dataclass(frozen=True)
class FactorSpec:
    family: str
    label: str
    inputs: tuple
    min_history: int
    group: str
    invalid_models: tuple = ()
    valid_models: tuple = ()
    orientation: str = "higher_is_better_at_source"
    winsorisation: str = "peer 2nd/98th percentiles, linear interpolation"
    peer_group: str = "business_model / sector / size / eligible universe; lenders isolated"
    pit: str = "filing date <= evaluation date; latest known revision; consistent basis"
    missing: str = "None; excluded from raw mean; reduces confidence"

SPEC = {
    "momentum_12_1": FactorSpec("momentum", "12-month momentum, last month skipped", ("Close",), 260, "trend"),
    "trend_quality": FactorSpec("momentum", "Signed straightness of the trend", ("Close",), 90, "trend"),
    "reversal_5d": FactorSpec("risk", "One-week reversal", ("Close",), 8, "reversal"),
    "low_volatility": FactorSpec("risk", "Realised volatility (negated)", ("Close",), 61, "volatility"),
    "volume_shock": FactorSpec("participation", "Log turnover against its history", ("Close", "Volume"), 65, "turnover"),
    "earnings_yield": FactorSpec("value", "Positive trailing earnings yield", ("eps_basic", "price"), 4, "valuation", ("lender", "cyclical", "emerging")),
    "cycle_earnings_yield": FactorSpec("value", "Three-year median annual EPS yield", ("eps_basic", "price"), 12, "valuation", (), ("cyclical",)),
    "earnings_growth": FactorSpec("growth", "PAT growth year on year", ("pat",), 5, "earnings"),
    "revenue_growth": FactorSpec("growth", "Revenue growth year on year", ("revenue",), 5, "revenue"),
    "margin_trend": FactorSpec("growth", "EBITDA margin change year on year", ("ebitda_margin_pct",), 5, "margin", ("lender",)),
    "margin_level": FactorSpec("quality", "EBITDA margin level", ("ebitda_margin_pct",), 1, "profitability", ("lender",)),
    "return_on_assets": FactorSpec("quality", "Annualised return on assets", ("roa_annualised_pct",), 1, "profitability"),
    "earnings_consistency": FactorSpec("quality", "Negative dispersion of bounded PAT growth", ("pat",), 8, "persistence"),
    "other_income_quality": FactorSpec("quality", "Negative other income / PBT", ("other_income", "pbt", "revenue"), 1, "earnings_quality", ("lender",)),
    "eps_acceleration": FactorSpec("acceleration", "EPS YoY growth acceleration (pp)", ("eps_basic",), 6, "earnings"),
    "revenue_acceleration": FactorSpec("acceleration", "Revenue YoY growth acceleration (pp)", ("revenue",), 6, "revenue"),
    "margin_acceleration": FactorSpec("acceleration", "Acceleration of YoY EBITDA margin change (pp)", ("ebitda_margin_pct",), 6, "margin", ("lender",)),
    "earnings_surprise": FactorSpec("acceleration", "Historical standardized EPS surprise", ("eps_basic",), 13, "earnings"),
    "low_leverage": FactorSpec("financial_strength", "Negative reported debt/equity", ("debt_equity", "ratio_units_validated"), 1, "leverage", ("lender", "utility")),
    "interest_coverage": FactorSpec("financial_strength", "Operating interest coverage", ("pbt_before_exceptional", "finance_cost", "other_income"), 1, "coverage", ("lender",)),
    "interest_coverage_trend": FactorSpec("financial_strength", "YoY operating interest coverage change", ("pbt_before_exceptional", "finance_cost", "other_income"), 5, "coverage", ("lender",)),
}
REGISTRY = {n: (s.family, s.label) for n, s in SPEC.items()}
FAMILIES = sorted({s.family for s in SPEC.values()})
PRICE_FACTORS = {n for n, s in SPEC.items() if "Close" in s.inputs}


def eligible(name, model):
    s = SPEC[name]
    return model not in s.invalid_models and (not s.valid_models or model in s.valid_models)


def finite(value):
    try:
        v = float(value)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError, OverflowError):
        return None


def cutoff_date(value=None):
    if value is None:
        return dt.date.today()
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    # Fail closed: an invalid historical cutoff must never default to today.
    return dt.date.fromisoformat(str(value)[:10])


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


# How old a filing may be before it stops describing the present.
#
# THIS IS THE CONSEQUENTIAL ONE. NSE's XBRL index is frozen at the December
# 2024 quarter, and without this cutoff every growth, margin and yield factor
# below would be computed from filings twenty months old and fed into the
# ranking as though they were current. That is not a weak signal, it is a
# wrong one, and it would have been completely silent: the numbers are
# well-formed, the arithmetic is correct, and the answer describes a company
# that has since reported six more times.
#
# A quarterly filer owes a result within 45 days of the quarter end. Two
# quarters plus that allowance is generous and still refuses a dead source.
STALE_AFTER_DAYS = int(os.environ.get("FUNDAMENTAL_STALE_DAYS", "225") or 225)


def _too_old(quarter, as_of):
    """Is this the newest thing available, and is the newest thing ancient?"""
    end = (quarter.get("period") or {}).get("to")
    if not end:
        return False
    try:
        d = dt.date.fromisoformat(str(end)[:10])
    except Exception:
        return False
    return (as_of - d).days > STALE_AFTER_DAYS


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
    cutoff = cutoff_date(as_of)
    out = []
    for q in quarters:
        filed = _parse_filed(q)
        try:
            end = dt.date.fromisoformat(_period_to(q))
        except (ValueError, TypeError):
            continue
        if filed is None or filed > cutoff or end > filed or end > cutoff:
            continue
        # Reject annual/YTD statements when an actual duration is supplied.
        begin = (q.get("period") or {}).get("from")
        if begin and begin != end.isoformat():
            try:
                if not 60 <= (end - dt.date.fromisoformat(str(begin)[:10])).days <= 110:
                    continue
            except ValueError:
                continue
        out.append(q)
    if consolidated is None and out:
        newest = max(_period_to(q) for q in out)
        consolidated = any(q.get("consolidated") for q in out if _period_to(q) == newest)
    out = [q for q in out if consolidated is None or bool(q.get("consolidated")) == bool(consolidated)]
    # Sort by period first: a late revision of an old quarter isn't the latest quarter.
    out.sort(key=lambda q: (_period_to(q), _parse_filed(q),
                           str(q.get("filed_at") or ""), q.get("regime") == "integrated",
                           str(q.get("source_url") or "")), reverse=True)
    unique = {}
    for q in out:
        unique.setdefault(_period_to(q), q)
    return list(unique.values())


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
    try:
        end = dt.date.fromisoformat(_period_to(latest))
    except ValueError:
        return None
    return next((q for q in known if _period_to(q)[:7] == f"{end.year-1:04d}-{end.month:02d}"), None)


def _growth(now, then):
    if now is None or then is None:
        return None
    try:
        now, then = float(now), float(then)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(now) or not math.isfinite(then) or then <= 1e-8:
        return None
    # A swing through zero has no meaningful percentage. Reporting one turns a
    # loss-making company that lost slightly less into a 300% grower.
    if then < 0 or now < 0:
        return None
    # Reject tiny bases relative to the current scale (over 100x); never cap into a buy.
    if then < abs(now) * 0.01:
        return None
    return (now / then - 1.0) * 100.0


def _previous(known, latest):
    end = dt.date.fromisoformat(_period_to(latest))
    month = end.year * 12 + end.month - 1 - 3
    key = f"{month // 12:04d}-{month % 12 + 1:02d}"
    return next((q for q in known if _period_to(q).startswith(key)), None)


def _chain(known, latest, n):
    result, q = [], latest
    while q is not None and len(result) < n:
        result.append(q)
        q = _previous(known, q)
    return result


def fundamental_factors(quarters, price=None, as_of=None, consolidated=None):
    known = known_quarters(quarters, as_of, consolidated)
    out = {n: None for n in SPEC if n not in PRICE_FACTORS}
    if not known:
        return out
    latest = known[0]
    if _too_old(latest, cutoff_date(as_of)):
        out.update(stale=True, stale_reason="Newest filing period is superseded; fundamental factors withheld after "
                   f"{STALE_AFTER_DAYS} days.")
        return out
    prior = _same_quarter_last_year(known, latest)
    prev = _previous(known, latest)
    prev_prior = _same_quarter_last_year(known, prev) if prev else None
    def change(q, p, key, growth=False):
        a, b = finite((q or {}).get(key)), finite((p or {}).get(key))
        if a is None or b is None:
            return None
        return _growth(a, b) if growth else a - b
    for name, key, growth in (("earnings_growth", "pat", True), ("revenue_growth", "revenue", True),
                              ("margin_trend", "ebitda_margin_pct", False)):
        out[name] = change(latest, prior, key, growth)
    for name, key, growth in (("eps_acceleration", "eps_basic", True),
                              ("revenue_acceleration", "revenue", True),
                              ("margin_acceleration", "ebitda_margin_pct", False)):
        a, b = change(latest, prior, key, growth), change(prev, prev_prior, key, growth)
        if a is not None and b is not None:
            out[name] = a - b
    out["margin_level"] = finite(latest.get("ebitda_margin_pct"))
    out["return_on_assets"] = finite(latest.get("roa_annualised_pct"))
    de = finite(latest.get("debt_equity"))
    if de is not None and de >= 0 and latest.get("ratio_units_validated") is True:
        out["low_leverage"] = -de
    def coverage(q):
        # Ratio tags have inconsistent scaling/sentinel zeros across real filings.
        # Rebuild operating EBIT from explicit statement lines in the same unit.
        q = q or {}
        p, cost, other = [finite(q.get(k)) for k in
                          ("pbt_before_exceptional", "finance_cost", "other_income")]
        if all(v is not None for v in (p,cost,other)) and cost > 1e-8:
            return (p + cost - other) / cost
        return None
    out["interest_coverage"] = coverage(latest)
    prior_coverage = coverage(prior)
    if out["interest_coverage"] is not None and prior_coverage is not None:
        out["interest_coverage_trend"] = out["interest_coverage"] - prior_coverage
    oi, pbt, rev = [finite(latest.get(k)) for k in ("other_income", "pbt", "revenue")]
    if all(v is not None for v in (oi, pbt, rev)) and rev > 0 and pbt > max(1e-8, rev * .01) and oi >= 0:
        out["other_income_quality"] = -oi / pbt
    chain = _chain(known, latest, 16)
    # Symmetric percentage change in [-200,200], valid through losses/zero.
    # Consistency measures dispersion, not profitability; level is a separate group.
    changes = []
    deltas = []
    for q in chain:
        py = _same_quarter_last_year(known, q)
        a, b = finite(q.get("pat")), finite((py or {}).get("pat"))
        if a is not None and b is not None and abs(a) + abs(b) > 1e-8:
            changes.append(200 * (a - b) / (abs(a) + abs(b)))
        else:
            changes.append(None)
        deltas.append(change(q, py, "eps_basic"))
    cs = []
    for v in changes[:8]:
        if v is None: break
        cs.append(v)
    if len(cs) >= 4:
        out["earnings_consistency"] = -float(np.std(cs, ddof=1))
    # Current innovation excluded from the eight preceding seasonal differences.
    # MAD denominator; a zero historical scale withholds SUE rather than exploding.
    if len(deltas) >= 9 and all(v is not None for v in deltas[:9]):
        history = np.asarray(deltas[1:9], float)
        median = float(np.median(history))
        scale = float(1.4826 * np.median(np.abs(history - median)))
        if scale > max(1e-8, float(np.max(np.abs(history))) * 1e-6):
            out["earnings_surprise"] = (deltas[0] - median) / scale
    p = finite(price)
    eps = [finite(q.get("eps_basic")) for q in chain]
    if p is not None and p > 0:
        if len(eps) >= 4 and all(v is not None for v in eps[:4]) and sum(eps[:4]) > 0:
            out["earnings_yield"] = sum(eps[:4]) / p * 100
        if len(eps) >= 12 and all(v is not None for v in eps[:12]):
            normal = float(np.median([sum(eps[j:j+4]) for j in (0, 4, 8)]))
            if normal > 0:
                out["cycle_earnings_yield"] = normal / p * 100
    return {k: finite(v) if k in SPEC else v for k, v in out.items()}


def data_quality(quarters, as_of=None, consolidated=None):
    known = known_quarters(quarters, as_of, consolidated)
    q = known[0] if known else {}
    age = (cutoff_date(as_of) - dt.date.fromisoformat(_period_to(q))).days if q else None
    return {"as_of": cutoff_date(as_of).isoformat(), "period_age_days": age,
            "latest_period_end": _period_to(q) or None,
            "latest_filed_at": q.get("filed_at"),
            "stale": age is not None and age > STALE_AFTER_DAYS,
            "history_quarters": len(_chain(known, q, 16)) if q else 0,
            "source_valid": bool(known) and all(bool(x.get("source_url")) for x in known),
            "consolidated": q.get("consolidated"),
            "source_urls": list(dict.fromkeys(x.get("source_url") for x in known if x.get("source_url")))}


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

    if as_of is not None and df is not None:
        cutoff = cutoff_date(as_of)
        df = df.loc[pd.to_datetime(df.index).date <= cutoff]
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
        fund = fundamental_factors(quarters or [], price, as_of, consolidated)
        out["_fundamentals_stale"] = bool(fund.pop("stale", False))
        out["_fundamentals_note"] = fund.pop("stale_reason", None)
        out.update(fund)
    except Exception:
        for k in ("earnings_yield", "earnings_growth", "revenue_growth",
                  "margin_trend", "return_on_assets"):
            out.setdefault(k, None)
    # The registry keys, in registry order, plus the two diagnostics. The
    # underscore prefix keeps them out of anything that iterates factors —
    # the ranker walks REGISTRY, so a diagnostic leaking in would be ranked as
    # though it were a signal.
    result = {k: out.get(k) for k in REGISTRY}
    result["_fundamentals_stale"] = bool(out.get("_fundamentals_stale"))
    result["_fundamentals_note"] = out.get("_fundamentals_note")
    return result
