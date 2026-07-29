"""
Altaha Screener — Data Layer

Wraps yfinance with an in-memory cache (30 min) so repeated lookups and the
leaderboard don't hammer the provider, plus ownership extraction from the
quarterly shareholding data where published.
"""

import time
import pandas as pd
import yfinance as yf

_CACHE = {}
_TTL = 1800  # 30 minutes


def _cget(k):
    hit = _CACHE.get(k)
    if hit and (time.time() - hit[0]) < _TTL:
        return hit[1]
    return None


def _cput(k, v):
    if len(_CACHE) > 500:
        for old in list(_CACHE)[:150]:
            _CACHE.pop(old, None)
    _CACHE[k] = (time.time(), v)


class NotFound(Exception):
    pass


def resolve(raw: str):
    """Try symbol as given, then NSE (.NS), then BSE (.BO). Returns (sym, ticker, history)."""
    raw = raw.strip().upper()
    candidates = [raw] if "." in raw else [raw, f"{raw}.NS", f"{raw}.BO"]
    for sym in candidates:
        cached = _cget(f"px::{sym}")
        if cached is not None:
            return sym, yf.Ticker(sym), cached
        try:
            t = yf.Ticker(sym)
            h = t.history(period="1y", auto_adjust=True)
            if h is not None and len(h) >= 60:
                h = h.dropna(subset=["Close"])
                _cput(f"px::{sym}", h)
                return sym, t, h
        except Exception:
            continue
    raise NotFound(raw)


def _pct(val):
    """Normalise a holding figure to a 0-1 fraction, or None."""
    try:
        f = float(val)
    except (TypeError, ValueError):
        return None
    if f != f:                       # NaN
        return None
    if f > 1.0:                      # given as a percentage, not a fraction
        f = f / 100.0
    return f if 0 <= f <= 1 else None


def ownership(t) -> dict:
    """
    Extract institutional (FII+DII) and promoter/insider holding.
    Indian coverage is patchy — returns {} rather than guessing.
    """
    out = {}

    # Preferred: major_holders breakdown
    try:
        mh = t.major_holders
        if mh is not None and not mh.empty:
            if "Value" in mh.columns:                       # newer yfinance: labelled index
                for label, val in mh["Value"].items():
                    key = str(label).lower()
                    if "institutionspercentheld" in key.replace(" ", ""):
                        out["institutions_pct"] = _pct(val)
                    elif "insiderspercentheld" in key.replace(" ", ""):
                        out["insiders_pct"] = _pct(val)
            elif mh.shape[1] >= 2:                          # older: 2 unnamed columns
                for _, row in mh.iterrows():
                    desc = str(row.iloc[1]).lower()
                    if "institution" in desc:
                        out["institutions_pct"] = _pct(str(row.iloc[0]).replace("%", ""))
                    elif "insider" in desc:
                        out["insiders_pct"] = _pct(str(row.iloc[0]).replace("%", ""))
    except Exception:
        pass

    # Fallback: info fields
    if "institutions_pct" not in out or out.get("institutions_pct") is None:
        try:
            info = t.info or {}
            out["institutions_pct"] = _pct(info.get("heldPercentInstitutions"))
            out["insiders_pct"] = out.get("insiders_pct") or _pct(info.get("heldPercentInsiders"))
        except Exception:
            pass

    return {k: v for k, v in out.items() if v is not None}


def fundamentals(sym: str, t):
    """Return (financials, balance_sheet, cashflow, info_dict). Never raises."""
    cached = _cget(f"fn::{sym}")
    if cached is not None:
        return cached

    fin = bs = cf = pd.DataFrame()
    info = {}
    for attr, target in (("financials", "fin"), ("balance_sheet", "bs"), ("cashflow", "cf")):
        try:
            val = getattr(t, attr)
            if target == "fin":
                fin = val
            elif target == "bs":
                bs = val
            else:
                cf = val
        except Exception:
            pass
    try:
        info = dict(t.info or {})
    except Exception:
        info = {}

    info.update(ownership(t))
    out = (fin, bs, cf, info)
    _cput(f"fn::{sym}", out)
    return out
