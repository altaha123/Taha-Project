"""
Altaha Screener — Data Layer

Wraps yfinance with an in-memory cache (30 min) so repeated lookups and the
leaderboard don't hammer the provider, plus ownership extraction from the
quarterly shareholding data where published.
"""

import time
import pandas as pd
import yfinance as yf

try:
    import dhan_source as dhan
except Exception:      # module optional
    dhan = None

_CACHE = {}
_TTL = 1800  # 30 minutes
MAX_CACHE = 120        # bounded for a 512 MB instance


def _cget(k):
    hit = _CACHE.get(k)
    if hit and (time.time() - hit[0]) < _TTL:
        return hit[1]
    return None


def _cput(k, v):
    if len(_CACHE) >= MAX_CACHE:
        # drop the oldest third rather than growing without bound
        for old in sorted(_CACHE, key=lambda x: _CACHE[x][0])[: MAX_CACHE // 3]:
            _CACHE.pop(old, None)
    _CACHE[k] = (time.time(), v)


class NotFound(Exception):
    pass


def resolve(raw: str):
    """
    Resolve a symbol to (sym, yfinance_ticker, price_history).

    Price history comes from Dhan when a valid token is configured (faster,
    live, no datacenter throttling); otherwise from Yahoo. The yfinance
    Ticker object is always returned because fundamentals, shareholding and
    quarterly results still come from Yahoo — Dhan does not publish them.
    """
    raw = raw.strip().upper()
    candidates = [raw] if "." in raw else [raw, f"{raw}.NS", f"{raw}.BO"]

    # Dhan first, for Indian equities only
    if dhan is not None and dhan.configured():
        base = raw.replace(".NS", "").replace(".BO", "")
        if not raw.startswith("^"):
            key = f"px::{base}.NS"
            cached = _cget(key)
            if cached is not None:
                return f"{base}.NS", yf.Ticker(f"{base}.NS"), cached
            try:
                df = dhan.daily_ohlcv(base)
            except Exception:
                df = None
            if df is not None and len(df) >= 60:
                _cput(key, df)
                return f"{base}.NS", yf.Ticker(f"{base}.NS"), df

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


def shareholding(t) -> dict:
    """
    Build the fullest shareholding picture the provider publishes.

    Indian shareholding patterns are quarterly filings under LODR Reg 31.
    Coverage via this provider is partial — anything missing is reported as
    unpublished rather than estimated.
    """
    own = ownership(t)
    out = {
        "promoter_pct": own.get("insiders_pct"),
        "institutions_pct": own.get("institutions_pct"),
        "public_pct": None,
        "institutions_float_pct": None,
        "institutions_count": None,
        "as_of": None,
        "top_holders": [],
        "mf_holders": [],
    }

    # Extra figures from major_holders
    try:
        mh = t.major_holders
        if mh is not None and not mh.empty and "Value" in mh.columns:
            for label, val in mh["Value"].items():
                key = str(label).lower().replace(" ", "")
                if "institutionsfloatpercentheld" in key:
                    out["institutions_float_pct"] = _pct(val)
                elif "institutionscount" in key:
                    try:
                        out["institutions_count"] = int(float(val))
                    except (TypeError, ValueError):
                        pass
    except Exception:
        pass

    # Derived residual — only when both known and arithmetic is sane
    p, i = out["promoter_pct"], out["institutions_pct"]
    if p is not None and i is not None:
        rest = 1.0 - p - i
        out["public_pct"] = round(rest, 4) if -0.005 <= rest <= 1.0 else None
        if out["public_pct"] is not None and out["public_pct"] < 0:
            out["public_pct"] = 0.0

    def _holders(frame, cap=6):
        rows = []
        if frame is None or getattr(frame, "empty", True):
            return rows
        cols = {str(c).lower().strip(): c for c in frame.columns}

        def pick(*names):
            for n in names:
                if n in cols:
                    return cols[n]
            return None

        c_name = pick("holder", "name")
        c_pct = pick("pctheld", "% out", "pctout", "percentheld")
        c_sh = pick("shares")
        c_val = pick("value")
        c_dt = pick("date reported", "datereported", "date")

        for _, r in frame.head(cap).iterrows():
            item = {"name": str(r[c_name]) if c_name else None,
                    "pct": _pct(r[c_pct]) if c_pct else None,
                    "shares": None, "value": None, "date": None}
            if c_sh:
                try:
                    item["shares"] = int(float(r[c_sh]))
                except (TypeError, ValueError):
                    pass
            if c_val:
                try:
                    item["value"] = float(r[c_val])
                except (TypeError, ValueError):
                    pass
            if c_dt:
                try:
                    item["date"] = str(r[c_dt])[:10]
                except Exception:
                    pass
            if item["name"]:
                rows.append(item)
        return rows

    try:
        out["top_holders"] = _holders(t.institutional_holders)
    except Exception:
        pass
    try:
        out["mf_holders"] = _holders(t.mutualfund_holders, cap=5)
    except Exception:
        pass

    dates = [h["date"] for h in out["top_holders"] + out["mf_holders"] if h.get("date")]
    if dates:
        out["as_of"] = max(dates)

    out["published"] = any(out[k] is not None for k in
                           ("promoter_pct", "institutions_pct")) or bool(out["top_holders"])
    return out


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
