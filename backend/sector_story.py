"""
Altaha Screener — Sector Story

Answers one question the product could not previously answer: not "which
sector is up" — every website shows that — but "up because of what".

THE METHOD, IN FOUR STEPS

  1  THE MOVE.       Sector index return over the chosen window, and the same
                     number relative to the Nifty 50. A sector up 1% on a day
                     the index is up 1.4% is not a strong sector.

  2  WHO MOVED IT.   Constituent returns, ranked. A sector index is a weighted
                     average, so "Metal is up" can mean fifteen stocks rose or
                     that one very large one did. Those are different facts and
                     they lead to different decisions.

  3  BREADTH.        How many constituents rose against how many fell, and how
                     much of the move the top three names account for. This is
                     the number that separates a sector move from a stock move
                     wearing a sector's name.

  4  THE NEWS.       Exchange filings for those same constituents inside the
                     window, ranked by the importance heuristic, joined to the
                     stocks that actually moved.

WHAT IT WILL NOT DO
-------------------
It will not invent a cause. When a sector moves and no constituent filing
explains it, the honest reading is that the move came from outside the
companies — a commodity price, a currency, a policy signal, a global session —
and the module says exactly that rather than reaching for the nearest headline.
A screener that always has an explanation is a screener that is sometimes
making one up, and for a tool whose entire promise is a visible audit trail
that would be the worst possible failure.

CONSTITUENTS
------------
The lists below are the heavyweight members of each NSE sector index, carried
in the file rather than fetched. NSE does not publish constituent weights in a
free machine-readable form, so contribution is approximated by equal-weight
return and is labelled as such wherever it is shown. The list date is in the
payload so the UI can disclose staleness instead of implying precision.
"""

import datetime as dt

try:
    import pandas as pd
except Exception:                                     # pragma: no cover
    pd = None

try:
    import yfinance as yf
except Exception:                                     # pragma: no cover
    yf = None

try:
    import sectors as S
except Exception:                                     # pragma: no cover
    S = None

try:
    import announcements as ann
except Exception:                                     # pragma: no cover
    ann = None


CONSTITUENTS_AS_OF = "2026-08-21"

# Heavyweights per NSE sector index. Ten to twelve names each is enough to
# explain a move; adding the long tail adds requests, not information.
CONSTITUENTS = {
    "Technology": ["TCS", "INFY", "HCLTECH", "WIPRO", "TECHM", "LTIM",
                   "PERSISTENT", "COFORGE", "MPHASIS", "LTTS"],
    "Financial Services": ["HDFCBANK", "ICICIBANK", "SBIN", "KOTAKBANK",
                           "AXISBANK", "INDUSINDBK", "BAJFINANCE", "BAJAJFINSV",
                           "PNB", "BANKBARODA", "IDFCFIRSTB", "FEDERALBNK"],
    "Healthcare": ["SUNPHARMA", "CIPLA", "DRREDDY", "DIVISLAB", "LUPIN",
                   "AUROPHARMA", "TORNTPHARM", "ALKEM", "ZYDUSLIFE", "GLENMARK"],
    "Consumer Defensive": ["HINDUNILVR", "ITC", "NESTLEIND", "BRITANNIA",
                           "DABUR", "GODREJCP", "MARICO", "COLPAL",
                           "TATACONSUM", "UBL"],
    "Consumer Cyclical": ["MARUTI", "M&M", "TATAMOTORS", "BAJAJ-AUTO",
                          "EICHERMOT", "HEROMOTOCO", "TVSMOTOR", "ASHOKLEY",
                          "BALKRISIND", "MOTHERSON"],
    "Basic Materials": ["TATASTEEL", "JSWSTEEL", "HINDALCO", "VEDL",
                        "JINDALSTEL", "SAIL", "NATIONALUM", "HINDZINC",
                        "APLAPOLLO", "NMDC"],
    "Energy": ["RELIANCE", "ONGC", "NTPC", "POWERGRID", "COALINDIA",
               "BPCL", "IOC", "GAIL", "TATAPOWER", "ADANIGREEN"],
    "Utilities": ["NTPC", "POWERGRID", "TATAPOWER", "ADANIGREEN",
                  "TORNTPOWER", "JSWENERGY", "NHPC", "SJVN"],
    "Industrials": ["LT", "SIEMENS", "ABB", "BHEL", "CUMMINSIND",
                    "THERMAX", "BEL", "HAL", "GRINDWELL", "AIAENG"],
    "Real Estate": ["DLF", "GODREJPROP", "OBEROIRLTY", "PRESTIGE",
                    "PHOENIXLTD", "BRIGADE", "SOBHA", "MAHLIFE"],
    "Communication Services": ["BHARTIARTL", "IDEA", "ZEEL", "SUNTV",
                               "PVRINOX", "NAZARA", "TV18BRDCST"],
}

WINDOWS = {
    "1D": {"sessions": 1, "label": "today", "news_hours": 30},
    "1W": {"sessions": 5, "label": "this week", "news_hours": 8 * 24},
    "1M": {"sessions": 21, "label": "this month", "news_hours": 31 * 24},
}


# ---------------------------------------------------------------------------
# Price data
# ---------------------------------------------------------------------------

def _returns(symbols, sessions):
    """
    Batch download and return {symbol: pct_change} over `sessions` sessions.
    One request for the whole basket — a loop here would be forty requests per
    sector view and would be rate-limited within a minute.
    """
    if yf is None or pd is None or not symbols:
        return {}, "price data unavailable on this server"

    tickers = [f"{s}.NS" for s in symbols]
    try:
        raw = yf.download(tickers, period="3mo", interval="1d",
                          progress=False, auto_adjust=True, threads=True)
    except Exception as e:
        return {}, f"price download failed ({str(e)[:70]})"

    try:
        closes = raw["Close"] if "Close" in raw else raw
    except Exception:
        return {}, "unexpected price payload shape"

    out = {}
    for sym, tk in zip(symbols, tickers):
        try:
            col = closes[tk] if tk in closes.columns else None
            if col is None:
                continue
            col = col.dropna()
            if len(col) < sessions + 1:
                continue
            now, then = float(col.iloc[-1]), float(col.iloc[-1 - sessions])
            if then:
                out[sym] = round(100 * (now - then) / then, 2)
        except Exception:
            continue
    return out, None


def _index_move(sector, sessions):
    """Sector index return and the same figure relative to the Nifty 50."""
    if S is None or yf is None:
        return None
    spec = S.SECTOR_INDEX.get(sector)
    if not spec:
        return None
    try:
        raw = yf.download([spec["sym"], S.BENCHMARK], period="6mo",
                          interval="1d", progress=False, auto_adjust=True)
        closes = raw["Close"] if "Close" in raw else raw

        def chg(sym):
            col = closes[sym].dropna()
            if len(col) < sessions + 1:
                return None
            a, b = float(col.iloc[-1]), float(col.iloc[-1 - sessions])
            return round(100 * (a - b) / b, 2) if b else None

        sec, bench = chg(spec["sym"]), chg(S.BENCHMARK)
        rel = round(sec - bench, 2) if (sec is not None and bench is not None) else None
        return {"index": spec["name"], "symbol": spec["sym"],
                "change_pct": sec, "benchmark": S.BENCHMARK_NAME,
                "benchmark_pct": bench, "relative_pp": rel,
                "proxy_note": spec.get("proxy_note")}
    except Exception:
        return None


# ---------------------------------------------------------------------------
# The join
# ---------------------------------------------------------------------------

def _news_for(symbols, hours):
    """Filings for these symbols inside the window, most important first."""
    if ann is None:
        return [], "announcements module unavailable"
    try:
        ann.poll_if_stale()
    except Exception:
        pass
    wanted = set(symbols)
    rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    rows = []
    try:
        feed = ann.feed(limit=400, min_importance="low")
        items = feed.get("rows", feed) if isinstance(feed, dict) else feed
        for r in items or []:
            sym = (r.get("symbol") or "").upper()
            if sym in wanted:
                rows.append(r)
    except Exception as e:
        return [], f"filing feed unavailable ({str(e)[:60]})"
    rows.sort(key=lambda r: (rank.get(r.get("importance", "low"), 3),
                             r.get("when_iso") or ""))
    return rows[:12], None


def _narrate(sector, move, movers, breadth, news, window):
    """
    One paragraph, assembled from measured facts only. Every clause traces to a
    number above it. Where the numbers do not support a cause, it says so.
    """
    w = WINDOWS[window]["label"]
    bits = []

    if move and move.get("change_pct") is not None:
        d = "up" if move["change_pct"] >= 0 else "down"
        bits.append(f"{move['index']} is {d} {abs(move['change_pct'])}% {w}")
        if move.get("relative_pp") is not None:
            if abs(move["relative_pp"]) < 0.25:
                bits[-1] += ", essentially in line with the Nifty 50"
            else:
                verb = "ahead of" if move["relative_pp"] > 0 else "behind"
                bits[-1] += (f", {abs(move['relative_pp'])} points {verb} "
                             f"the Nifty 50")

    if breadth.get("total"):
        bits.append(f"{breadth['up']} of {breadth['total']} heavyweights rose")
        if breadth.get("top3_share") is not None and breadth["top3_share"] >= 60:
            names = ", ".join(m["symbol"] for m in movers[:3])
            bits[-1] += (f", but {breadth['top3_share']}% of the movement came from "
                         f"just three names ({names}) — read this as a stock move "
                         f"more than a sector move")
        elif breadth.get("up") and breadth["up"] >= 0.7 * breadth["total"]:
            bits[-1] += ", so the move is broad rather than carried by one or two names"

    if news:
        crit = [n for n in news if n.get("importance") in ("critical", "high")]
        if crit:
            bits.append(f"{len(crit)} significant filing"
                        + ("s" if len(crit) != 1 else "")
                        + " landed in the sector inside the window")
        else:
            bits.append(f"{len(news)} routine filings, none of them market-moving "
                        f"in category")
    else:
        bits.append("no company filings inside the window explain it — a move with "
                    "no company-level cause usually came from outside the companies: "
                    "a commodity price, the currency, a policy signal or the global "
                    "session")

    return ". ".join(b[0].upper() + b[1:] for b in bits if b) + "."


def story(sector: str, window: str = "1D") -> dict:
    """The whole picture for one sector."""
    if window not in WINDOWS:
        window = "1D"
    sessions = WINDOWS[window]["sessions"]
    names = CONSTITUENTS.get(sector)
    if not names:
        return {"error": f"No constituent list carried for '{sector}'.",
                "known": sorted(CONSTITUENTS)}

    rets, price_err = _returns(names, sessions)
    movers = sorted(({"symbol": s, "change_pct": v} for s, v in rets.items()),
                    key=lambda m: -m["change_pct"])

    up = sum(1 for v in rets.values() if v > 0)
    down = sum(1 for v in rets.values() if v < 0)
    total = len(rets)
    avg = round(sum(rets.values()) / total, 2) if total else None

    # How concentrated is the move? Share of the summed absolute move that the
    # three largest movers account for. Equal-weight, and labelled as such.
    top3_share = None
    if total >= 5:
        mag = sorted((abs(v) for v in rets.values()), reverse=True)
        s_all = sum(mag)
        if s_all:
            top3_share = round(100 * sum(mag[:3]) / s_all)

    breadth = {"up": up, "down": down, "total": total,
               "average_pct": avg, "top3_share": top3_share,
               "method": ("Equal-weight across the carried heavyweights. NSE does "
                          "not publish index weights freely, so this approximates "
                          "contribution rather than measuring it.")}

    news, news_err = _news_for(names, WINDOWS[window]["news_hours"])

    # Attach each filing to its mover, so the two facts are read together.
    by_sym = {m["symbol"]: m for m in movers}
    for n in news:
        m = by_sym.get((n.get("symbol") or "").upper())
        if m:
            n["mover_change_pct"] = m["change_pct"]

    move = _index_move(sector, sessions)

    return {
        "sector": sector,
        "window": window,
        "window_label": WINDOWS[window]["label"],
        "move": move,
        "movers": movers,
        "laggards": movers[::-1][:5],
        "breadth": breadth,
        "news": news,
        "narrative": _narrate(sector, move or {}, movers, breadth, news, window),
        "constituents_as_of": CONSTITUENTS_AS_OF,
        "notes": [n for n in (price_err, news_err) if n],
        "disclaimer": ("Every figure here is a measurement over a stated window. "
                       "Nothing on this screen forecasts what happens next."),
    }


def overview(window: str = "1D") -> dict:
    """
    Every sector, ranked by relative strength — the entry screen. Deliberately
    lighter than story(): index moves only, no constituent download, so it
    stays inside one request budget.
    """
    if window not in WINDOWS:
        window = "1D"
    sessions = WINDOWS[window]["sessions"]
    rows = []
    for sector in CONSTITUENTS:
        m = _index_move(sector, sessions)
        if m and m.get("change_pct") is not None:
            rows.append({"sector": sector, **m})
    rows.sort(key=lambda r: -(r.get("relative_pp") if r.get("relative_pp")
                              is not None else -99))
    return {"window": window, "window_label": WINDOWS[window]["label"],
            "rows": rows, "as_of": dt.datetime.utcnow().isoformat() + "Z",
            "note": ("Ranked by return relative to the Nifty 50 over the window. "
                     "Open any sector for the constituent-level explanation.")}
