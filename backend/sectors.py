"""
Altaha Screener — Sector Intelligence

Answers the question the portfolio module could not previously ask: not just
"where is your money", but "is that where the tape is going".

Three jobs:

  1. Resolve a holding to a sector. yfinance's info["sector"] returns GICS
     names and is frequently None for NSE mid- and small-caps, so a bundled
     fallback map covers the Nifty 500 names most likely to appear in a
     retail book.

  2. Measure each sector against the index. Returns over 1M/3M/6M/12M,
     relative strength versus the Nifty 50, and the direction that relative
     strength is travelling. Sectors land in one of four states borrowed
     from relative-rotation analysis: Leading, Weakening, Lagging, Improving.

  3. Supply benchmark weights so a portfolio's sector mix can be expressed as
     active weight — the difference from the market — rather than as a raw
     percentage that means nothing on its own. Holding 30% Financials is not
     a concentration bet; the Nifty 500 already carries roughly that much.

Framing discipline, carried over from portfolio.py: every number here is an
observation with its arithmetic available. A sector being "Lagging" is a
statement about measured relative return over a stated window, not a view
about what happens next.
"""

import time

import pandas as pd

try:
    import yfinance as yf
except Exception:                                     # pragma: no cover
    yf = None


# ---------------------------------------------------------------------------
# Sector indices
# ---------------------------------------------------------------------------
#
# Yahoo carries the NSE sector indices under these symbols. Where a GICS
# sector has no clean NSE equivalent the nearest liquid proxy is used and the
# compromise is named in `proxy_note`, so the UI can disclose it rather than
# quietly implying a precision that isn't there.

BENCHMARK = "^NSEI"                                   # Nifty 50
BENCHMARK_NAME = "Nifty 50"

SECTOR_INDEX = {
    "Technology":             {"sym": "^CNXIT",      "name": "Nifty IT"},
    "Financial Services":     {"sym": "^NSEBANK",    "name": "Nifty Bank",
                               "proxy_note": "Bank index used for the whole "
                                             "financials sleeve — NBFCs and "
                                             "insurers move differently."},
    "Healthcare":             {"sym": "^CNXPHARMA",  "name": "Nifty Pharma"},
    "Consumer Defensive":     {"sym": "^CNXFMCG",    "name": "Nifty FMCG"},
    "Consumer Cyclical":      {"sym": "^CNXAUTO",    "name": "Nifty Auto",
                               "proxy_note": "Auto index used as the cyclical "
                                             "consumer proxy; retail and "
                                             "durables are not in it."},
    "Basic Materials":        {"sym": "^CNXMETAL",   "name": "Nifty Metal",
                               "proxy_note": "Metal index used for materials; "
                                             "chemicals and cement are not in it."},
    "Energy":                 {"sym": "^CNXENERGY",  "name": "Nifty Energy"},
    "Utilities":              {"sym": "^CNXENERGY",  "name": "Nifty Energy",
                               "proxy_note": "No standalone NSE utilities index "
                                             "on Yahoo — energy used as proxy."},
    "Industrials":            {"sym": "^CNXINFRA",   "name": "Nifty Infrastructure"},
    "Real Estate":            {"sym": "^CNXREALTY",  "name": "Nifty Realty"},
    "Communication Services": {"sym": "^CNXMEDIA",   "name": "Nifty Media",
                               "proxy_note": "Media index used; telecom is the "
                                             "larger part of this sector in India."},
}

# Approximate Nifty 500 sector weights, used to turn a raw sector percentage
# into an active weight. These drift with the market and are refreshed by hand
# — the date is surfaced in the payload so the UI never presents them as live.
BENCH_WEIGHTS_ASOF = "March 2026"
BENCH_WEIGHTS = {
    "Financial Services":     30.4,
    "Technology":              9.8,
    "Consumer Cyclical":      10.2,
    "Industrials":             9.1,
    "Energy":                  8.0,
    "Basic Materials":         7.9,
    "Healthcare":              7.2,
    "Consumer Defensive":      6.8,
    "Utilities":               4.1,
    "Communication Services":  3.2,
    "Real Estate":             1.9,
}

# GICS names vary slightly between yfinance versions and between the .NS and
# .BO listings of the same company. Normalise before anything else touches it.
SECTOR_ALIASES = {
    "information technology":  "Technology",
    "technology":              "Technology",
    "financial services":      "Financial Services",
    "financials":              "Financial Services",
    "healthcare":              "Healthcare",
    "health care":             "Healthcare",
    "consumer defensive":      "Consumer Defensive",
    "consumer staples":        "Consumer Defensive",
    "consumer cyclical":       "Consumer Cyclical",
    "consumer discretionary":  "Consumer Cyclical",
    "basic materials":         "Basic Materials",
    "materials":               "Basic Materials",
    "energy":                  "Energy",
    "utilities":               "Utilities",
    "industrials":             "Industrials",
    "real estate":             "Real Estate",
    "communication services":  "Communication Services",
    "communications":          "Communication Services",
}

# Fallback for the case yfinance returns None. Not exhaustive — it covers the
# large and mid caps that dominate retail books. Anything unmatched is
# reported as Unclassified rather than guessed at.
SYMBOL_SECTOR = {
    # Financials
    "HDFCBANK": "Financial Services", "ICICIBANK": "Financial Services",
    "SBIN": "Financial Services", "KOTAKBANK": "Financial Services",
    "AXISBANK": "Financial Services", "INDUSINDBK": "Financial Services",
    "BAJFINANCE": "Financial Services", "BAJAJFINSV": "Financial Services",
    "SBILIFE": "Financial Services", "HDFCLIFE": "Financial Services",
    "ICICIGI": "Financial Services", "ICICIPRULI": "Financial Services",
    "CHOLAFIN": "Financial Services", "SHRIRAMFIN": "Financial Services",
    "MUTHOOTFIN": "Financial Services", "LICHSGFIN": "Financial Services",
    "PNB": "Financial Services", "BANKBARODA": "Financial Services",
    "CANBK": "Financial Services", "UNIONBANK": "Financial Services",
    "IDFCFIRSTB": "Financial Services", "FEDERALBNK": "Financial Services",
    "AUBANK": "Financial Services", "BANDHANBNK": "Financial Services",
    "HDFCAMC": "Financial Services", "JIOFIN": "Financial Services",
    "PFC": "Financial Services", "RECLTD": "Financial Services",
    "IRFC": "Financial Services", "LICI": "Financial Services",
    # Technology
    "TCS": "Technology", "INFY": "Technology", "WIPRO": "Technology",
    "HCLTECH": "Technology", "TECHM": "Technology", "LTIM": "Technology",
    "MPHASIS": "Technology", "PERSISTENT": "Technology", "COFORGE": "Technology",
    "OFSS": "Technology", "TATAELXSI": "Technology", "KPITTECH": "Technology",
    # Healthcare
    "SUNPHARMA": "Healthcare", "DRREDDY": "Healthcare", "CIPLA": "Healthcare",
    "DIVISLAB": "Healthcare", "APOLLOHOSP": "Healthcare", "LUPIN": "Healthcare",
    "AUROPHARMA": "Healthcare", "TORNTPHARM": "Healthcare", "ZYDUSLIFE": "Healthcare",
    "ALKEM": "Healthcare", "MANKIND": "Healthcare", "GLENMARK": "Healthcare",
    "MAXHEALTH": "Healthcare", "FORTIS": "Healthcare", "BIOCON": "Healthcare",
    "LAURUSLABS": "Healthcare", "IPCALAB": "Healthcare",
    # Consumer defensive
    "HINDUNILVR": "Consumer Defensive", "ITC": "Consumer Defensive",
    "NESTLEIND": "Consumer Defensive", "BRITANNIA": "Consumer Defensive",
    "DABUR": "Consumer Defensive", "GODREJCP": "Consumer Defensive",
    "MARICO": "Consumer Defensive", "COLPAL": "Consumer Defensive",
    "TATACONSUM": "Consumer Defensive", "VBL": "Consumer Defensive",
    "UNITDSPR": "Consumer Defensive", "RADICO": "Consumer Defensive",
    "PATANJALI": "Consumer Defensive", "EMAMILTD": "Consumer Defensive",
    # Consumer cyclical
    "MARUTI": "Consumer Cyclical", "M&M": "Consumer Cyclical",
    "TATAMOTORS": "Consumer Cyclical", "BAJAJ-AUTO": "Consumer Cyclical",
    "HEROMOTOCO": "Consumer Cyclical", "EICHERMOT": "Consumer Cyclical",
    "TVSMOTOR": "Consumer Cyclical", "ASHOKLEY": "Consumer Cyclical",
    "TITAN": "Consumer Cyclical", "TRENT": "Consumer Cyclical",
    "DMART": "Consumer Cyclical", "ZOMATO": "Consumer Cyclical",
    "ETERNAL": "Consumer Cyclical", "NYKAA": "Consumer Cyclical",
    "JUBLFOOD": "Consumer Cyclical", "PAGEIND": "Consumer Cyclical",
    "HAVELLS": "Consumer Cyclical", "VOLTAS": "Consumer Cyclical",
    "CROMPTON": "Consumer Cyclical", "BATAINDIA": "Consumer Cyclical",
    "MOTHERSON": "Consumer Cyclical", "BOSCHLTD": "Consumer Cyclical",
    "BALKRISIND": "Consumer Cyclical", "MRF": "Consumer Cyclical",
    "APOLLOTYRE": "Consumer Cyclical", "INDHOTEL": "Consumer Cyclical",
    # Basic materials
    "TATASTEEL": "Basic Materials", "JSWSTEEL": "Basic Materials",
    "HINDALCO": "Basic Materials", "VEDL": "Basic Materials",
    "JINDALSTEL": "Basic Materials", "NATIONALUM": "Basic Materials",
    "SAIL": "Basic Materials", "APLAPOLLO": "Basic Materials",
    "ULTRACEMCO": "Basic Materials", "SHREECEM": "Basic Materials",
    "AMBUJACEM": "Basic Materials", "ACC": "Basic Materials",
    "GRASIM": "Basic Materials", "DALBHARAT": "Basic Materials",
    "PIDILITIND": "Basic Materials", "SRF": "Basic Materials",
    "UPL": "Basic Materials", "PIIND": "Basic Materials",
    "DEEPAKNTR": "Basic Materials", "TATACHEM": "Basic Materials",
    "ASIANPAINT": "Basic Materials", "BERGEPAINT": "Basic Materials",
    # Energy
    "RELIANCE": "Energy", "ONGC": "Energy", "BPCL": "Energy",
    "IOC": "Energy", "HINDPETRO": "Energy", "GAIL": "Energy",
    "OIL": "Energy", "COALINDIA": "Energy", "PETRONET": "Energy",
    "IGL": "Energy", "MGL": "Energy", "ATGL": "Energy",
    # Utilities
    "NTPC": "Utilities", "POWERGRID": "Utilities", "TATAPOWER": "Utilities",
    "ADANIGREEN": "Utilities", "ADANIPOWER": "Utilities", "JSWENERGY": "Utilities",
    "NHPC": "Utilities", "SJVN": "Utilities", "TORNTPOWER": "Utilities",
    # Industrials
    "LT": "Industrials", "SIEMENS": "Industrials", "ABB": "Industrials",
    "BEL": "Industrials", "HAL": "Industrials", "BHEL": "Industrials",
    "CUMMINSIND": "Industrials", "THERMAX": "Industrials",
    "ADANIPORTS": "Industrials", "ADANIENT": "Industrials",
    "INDIGO": "Industrials", "CONCOR": "Industrials", "GMRINFRA": "Industrials",
    "IRCTC": "Industrials", "RVNL": "Industrials", "IRB": "Industrials",
    "POLYCAB": "Industrials", "KEI": "Industrials", "SUZLON": "Industrials",
    "CGPOWER": "Industrials", "SUPREMEIND": "Industrials", "ASTRAL": "Industrials",
    # Real estate
    "DLF": "Real Estate", "GODREJPROP": "Real Estate", "OBEROIRLTY": "Real Estate",
    "PRESTIGE": "Real Estate", "PHOENIXLTD": "Real Estate", "LODHA": "Real Estate",
    "BRIGADE": "Real Estate", "SOBHA": "Real Estate",
    # Communication services
    "BHARTIARTL": "Communication Services", "IDEA": "Communication Services",
    "INDUSTOWER": "Communication Services", "SUNTV": "Communication Services",
    "ZEEL": "Communication Services", "PVRINOX": "Communication Services",
    "TATACOMM": "Communication Services", "NAUKRI": "Communication Services",
}

UNCLASSIFIED = "Unclassified"

# Trading sessions per window. Approximate by design — the exact count varies
# with holidays, and a two-session drift does not change a momentum reading.
WINDOWS = {"1M": 21, "3M": 63, "6M": 126, "12M": 252}

_CACHE = {"at": 0.0, "data": None}
_TTL = 6 * 3600          # sector momentum does not need intraday refresh


# ---------------------------------------------------------------------------
# Sector resolution
# ---------------------------------------------------------------------------

def normalise(raw) -> str | None:
    """Map any GICS spelling onto the canonical set. None stays None."""
    if not raw:
        return None
    return SECTOR_ALIASES.get(str(raw).strip().lower())


def resolve_sector(symbol: str, info: dict | None) -> tuple[str, str]:
    """
    Best available sector for a holding, with the source named.

    Returns (sector, source) where source is one of "provider", "bundled map"
    or "unresolved". The source travels with the value so the UI can mark a
    sector that was inferred rather than reported.
    """
    hit = normalise((info or {}).get("sector"))
    if hit:
        return hit, "provider"

    base = (symbol or "").upper().replace(".NS", "").replace(".BO", "")
    if base in SYMBOL_SECTOR:
        return SYMBOL_SECTOR[base], "bundled map"

    return UNCLASSIFIED, "unresolved"


def benchmark_weight(sector: str) -> float | None:
    """Approximate Nifty 500 weight for a sector, or None if not benchmarked."""
    return BENCH_WEIGHTS.get(sector)


# ---------------------------------------------------------------------------
# Sector momentum
# ---------------------------------------------------------------------------

def _pct_change(closes: pd.Series, sessions: int) -> float | None:
    """Simple return over the last N sessions, or None if history is short."""
    if closes is None or len(closes) <= sessions:
        return None
    now, then = float(closes.iloc[-1]), float(closes.iloc[-1 - sessions])
    if then <= 0:
        return None
    return round(100.0 * (now - then) / then, 2)


def _quadrant(rs_3m: float | None, rs_6m: float | None) -> tuple[str, str]:
    """
    Place a sector in one of four relative-rotation states.

    The x-axis is relative strength: has this sector beaten the index over
    three months. The y-axis is where that relative strength is heading —
    three-month relative strength measured against the six-month figure. A
    sector can be behind the index and still improving, which is a different
    fact from being behind and getting worse, and the four-way split is the
    cheapest honest way to say so.
    """
    if rs_3m is None:
        return "Unrated", "Not enough index history to measure."

    improving = rs_6m is None or rs_3m > rs_6m
    ahead = rs_3m > 0

    if ahead and improving:
        return "Leading", "Ahead of the index over 3 months, and the gap is widening."
    if ahead and not improving:
        return "Weakening", "Still ahead of the index over 3 months, but the gap is closing."
    if not ahead and improving:
        return "Improving", "Behind the index over 3 months, but the gap is narrowing."
    return "Lagging", "Behind the index over 3 months, and the gap is widening."


def _download(symbols: list[str]) -> dict:
    """One batched request for every index. Individual failures are tolerated."""
    if yf is None:
        return {}
    out = {}
    try:
        raw = yf.download(symbols, period="2y", interval="1d",
                          group_by="ticker", auto_adjust=True,
                          progress=False, threads=True)
    except Exception:
        return {}

    for s in symbols:
        try:
            frame = raw[s] if isinstance(raw.columns, pd.MultiIndex) else raw
            closes = frame["Close"].dropna()
            if len(closes) >= 70:
                out[s] = closes
        except Exception:
            continue
    return out


def momentum(force: bool = False) -> dict:
    """
    Returns and relative strength for every sector index, versus the Nifty 50.

    Cached for six hours. A failed fetch returns an available=False payload
    rather than raising, because a portfolio report is still worth producing
    without the sector overlay — it just says so.
    """
    if not force and _CACHE["data"] is not None and (time.time() - _CACHE["at"]) < _TTL:
        return _CACHE["data"]

    wanted = sorted({v["sym"] for v in SECTOR_INDEX.values()} | {BENCHMARK})
    series = _download(wanted)

    bench = series.get(BENCHMARK)
    if bench is None:
        payload = {
            "available": False,
            "message": "Sector indices could not be retrieved. Portfolio weights "
                       "and risk are unaffected; only the sector momentum "
                       "overlay is missing.",
            "sectors": [], "benchmark": None,
            "benchmark_weights_asof": BENCH_WEIGHTS_ASOF,
        }
        _CACHE.update(at=time.time(), data=payload)
        return payload

    bench_ret = {k: _pct_change(bench, n) for k, n in WINDOWS.items()}

    rows = []
    seen = set()
    for sector, meta in SECTOR_INDEX.items():
        closes = series.get(meta["sym"])
        if closes is None:
            continue

        rets = {k: _pct_change(closes, n) for k, n in WINDOWS.items()}
        rel = {}
        for k in WINDOWS:
            if rets[k] is None or bench_ret.get(k) is None:
                rel[k] = None
            else:
                rel[k] = round(rets[k] - bench_ret[k], 2)

        state, why = _quadrant(rel.get("3M"), rel.get("6M"))

        # Distance above the 200-day average is a slower, structural read on
        # the same index — it disagrees with three-month momentum often
        # enough to be worth showing beside it rather than folded in.
        above_200 = None
        if len(closes) >= 200:
            ma = float(closes.tail(200).mean())
            if ma > 0:
                above_200 = round(100.0 * (float(closes.iloc[-1]) - ma) / ma, 2)

        rows.append({
            "sector": sector,
            "index_symbol": meta["sym"],
            "index_name": meta["name"],
            "proxy_note": meta.get("proxy_note"),
            "returns": rets,
            "relative": rel,
            "state": state,
            "state_why": why,
            "above_200dma_pct": above_200,
            "benchmark_weight_pct": BENCH_WEIGHTS.get(sector),
            "duplicate_index": meta["sym"] in seen,
        })
        seen.add(meta["sym"])

    rows.sort(key=lambda r: (r["relative"].get("3M") is None,
                             -(r["relative"].get("3M") or 0)))
    for i, r in enumerate(rows, 1):
        r["rank_3m"] = i

    payload = {
        "available": True,
        "benchmark": {"symbol": BENCHMARK, "name": BENCHMARK_NAME,
                      "returns": bench_ret},
        "sectors": rows,
        "total_sectors": len(rows),
        "benchmark_weights_asof": BENCH_WEIGHTS_ASOF,
        "measured_at": time.strftime("%Y-%m-%d %H:%M", time.localtime()),
        "method": ("Returns are simple price changes over approximate session "
                   "counts (21/63/126/252). Relative strength is the sector "
                   "return minus the Nifty 50 return over the identical window. "
                   "State compares 3-month relative strength against 6-month."),
    }
    _CACHE.update(at=time.time(), data=payload)
    return payload


def by_sector(force: bool = False) -> dict:
    """Momentum rows keyed by sector name, for cheap lookup during a report."""
    m = momentum(force)
    return {r["sector"]: r for r in m.get("sectors", [])}
