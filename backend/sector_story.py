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

DATA SOURCES, IN PRIORITY ORDER
-------------------------------
  1  DHAN (paid, live).  Constituent prices come from the subscription that is
     already paid for. For a single-day window every constituent across every
     sector is one bulk quote call — not one call per stock — and that call
     also returns volume, so the screen can say whether the move had size
     behind it. Longer windows use Dhan's historical endpoint.

  2  YAHOO (free, fallback).  Used only when the Dhan token is missing or
     expired. The payload names which source served it, so a silently degraded
     screen is visible rather than assumed.

  3  EXCHANGE FILINGS (primary evidence).  announcements.py, unchanged.

  4  PRESS (secondary, labelled).  news_feed.py. Kept in a separate list from
     filings and never merged, because a journalist's rewrite of a filing is
     not the filing. Nothing in the press feed influences any score.

The benchmark rides along free. NIFTYBEES is an ETF and therefore lives in
NSE_EQ, so it can be appended to the same bulk quote call as the constituents
and costs nothing — the same trick intraday.py already uses for its regime
filter.

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

try:
    import dhan_source as dhan
except Exception:                                     # pragma: no cover
    dhan = None

try:
    import news_feed as press
except Exception:                                     # pragma: no cover
    press = None

BENCHMARK_PROXY = "NIFTYBEES"      # ETF, lives in NSE_EQ, rides the bulk call


CONSTITUENTS_AS_OF = "2026-08-21"

# Heavyweights per NSE sector index. Ten to twelve names each is enough to
# explain a move; adding the long tail adds requests, not information.
# A visual key per sector, drawn as a line icon by the frontend.
#
# Named rather than supplied as markup: the backend has no business shipping
# SVG paths, and a key lets the frontend draw them in its own stroke language
# so they sit with the rest of the site's icons instead of looking pasted on.
# An unknown sector falls back to a neutral mark rather than disappearing.
SECTOR_ICON = {
    "Technology":             "chip",
    "Financial Services":     "bank",
    "Healthcare":             "pill",
    "Consumer Defensive":     "wheat",
    "Consumer Cyclical":      "car",
    "Basic Materials":        "ingot",
    "Energy":                 "bolt",
    "Utilities":              "plug",
    "Industrials":            "factory",
    "Real Estate":            "building",
    "Communication Services": "tower",
}


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

def _returns_dhan(symbols, sessions):
    """
    Dhan first. One bulk call for a single-day window — including the
    benchmark proxy — and a throttled historical call per symbol for longer
    ones. Returns ({symbol: {...}}, benchmark_pct, note) or (None, ...) when
    Dhan cannot serve it, so the caller can fall back rather than fail.
    """
    if dhan is None or not dhan.configured():
        return None, None, "Dhan not configured on this server"

    batch = list(symbols) + [BENCHMARK_PROXY]

    if sessions <= 1:
        # mode="quote" rather than "ohlc": volume and average price exist only
        # on the quote endpoint. The old scanner bug was exactly this.
        try:
            snap = dhan.bulk_quotes(batch, mode="quote")
        except Exception as e:
            return None, None, f"Dhan bulk quote failed ({str(e)[:60]})"
        if not snap:
            return None, None, "Dhan returned no quotes"

        def pct(row):
            ltp, prev = row.get("ltp"), row.get("prev_close")
            try:
                if ltp and prev:
                    return round(100 * (float(ltp) - float(prev)) / float(prev), 2)
            except (TypeError, ValueError, ZeroDivisionError):
                pass
            return None

        out = {}
        for sym in symbols:
            row = snap.get(sym)
            if not row:
                continue
            p = pct(row)
            if p is None:
                continue
            out[sym] = {"change_pct": p, "volume": row.get("volume"),
                        "ltp": row.get("ltp"), "vwap": row.get("vwap")}
        bench = pct(snap.get(BENCHMARK_PROXY) or {})
        return out, bench, None

    # Multi-session: one historical call per symbol, throttled at 0.25s inside
    # dhan_source. Ten constituents costs about two and a half seconds.
    out = {}
    for sym in batch:
        try:
            df = dhan.daily_ohlcv(sym, days=max(90, sessions * 3))
        except Exception:
            continue
        if df is None or getattr(df, "empty", True) or len(df) < sessions + 1:
            continue
        try:
            c = df["Close"] if "Close" in df else df["close"]
            now, then = float(c.iloc[-1]), float(c.iloc[-1 - sessions])
            if not then:
                continue
            vol = None
            for k in ("Volume", "volume"):
                if k in df:
                    vol = float(df[k].iloc[-sessions:].sum())
                    break
            out[sym] = {"change_pct": round(100 * (now - then) / then, 2),
                        "volume": vol, "ltp": now, "vwap": None}
        except Exception:
            continue

    bench = (out.pop(BENCHMARK_PROXY, {}) or {}).get("change_pct")
    if not out:
        return None, None, "Dhan historical returned nothing usable"
    return out, bench, None


def _returns_yahoo(symbols, sessions):
    """Fallback only. One batched download for the whole basket."""
    if yf is None or pd is None or not symbols:
        return None, None, "Yahoo unavailable on this server"

    tickers = [f"{s}.NS" for s in symbols]
    try:
        raw = yf.download(tickers, period="3mo", interval="1d",
                          progress=False, auto_adjust=True, threads=True)
        closes = raw["Close"] if "Close" in raw else raw
    except Exception as e:
        return None, None, f"Yahoo download failed ({str(e)[:60]})"

    out = {}
    for sym, tk in zip(symbols, tickers):
        try:
            col = closes[tk].dropna() if tk in closes.columns else None
            if col is None or len(col) < sessions + 1:
                continue
            now, then = float(col.iloc[-1]), float(col.iloc[-1 - sessions])
            if then:
                out[sym] = {"change_pct": round(100 * (now - then) / then, 2),
                            "volume": None, "ltp": now, "vwap": None}
        except Exception:
            continue
    return (out or None), None, (None if out else "Yahoo returned nothing usable")


def _returns(symbols, sessions):
    """Dhan, then Yahoo. Reports which one actually served the request."""
    rows, bench, err = _returns_dhan(symbols, sessions)
    if rows:
        return rows, bench, "dhan", None
    rows2, bench2, err2 = _returns_yahoo(symbols, sessions)
    if rows2:
        note = f"Dhan unavailable ({err}) — figures from Yahoo Finance instead."
        return rows2, bench2, "yahoo", note
    return {}, None, "none", f"No price source available. Dhan: {err}. Yahoo: {err2}."


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


def _narrate(sector, move, movers, breadth, news, window, vol_note=None):
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
            bench = move.get("benchmark") or "the Nifty 50"
            if abs(move["relative_pp"]) < 0.25:
                bits[-1] += f", essentially in line with {bench}"
            else:
                verb = "ahead of" if move["relative_pp"] > 0 else "behind"
                bits[-1] += f", {abs(move['relative_pp'])} points {verb} {bench}"

    if breadth.get("total"):
        bits.append(f"{breadth['up']} of {breadth['total']} heavyweights rose")
        if breadth.get("top3_share") is not None and breadth["top3_share"] >= 60:
            names = ", ".join(m["symbol"] for m in movers[:3])
            bits[-1] += (f", but {breadth['top3_share']}% of the movement came from "
                         f"just three names ({names}) — read this as a stock move "
                         f"more than a sector move")
        elif breadth.get("up") and breadth["up"] >= 0.7 * breadth["total"]:
            bits[-1] += ", so the move is broad rather than carried by one or two names"

    if vol_note:
        bits.append(vol_note.rstrip("."))

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

    rows, bench_pct, source, price_note = _returns(names, sessions)

    movers = sorted(
        ({"symbol": s_, "change_pct": d["change_pct"], "volume": d.get("volume"),
          "ltp": d.get("ltp")} for s_, d in rows.items()),
        key=lambda m: -m["change_pct"])

    vals = [d["change_pct"] for d in rows.values()]
    up = sum(1 for v in vals if v > 0)
    down = sum(1 for v in vals if v < 0)
    total = len(vals)
    avg = round(sum(vals) / total, 2) if total else None

    top3_share = None
    if total >= 5:
        mag = sorted((abs(v) for v in vals), reverse=True)
        s_all = sum(mag)
        if s_all:
            top3_share = round(100 * sum(mag[:3]) / s_all)

    breadth = {"up": up, "down": down, "total": total,
               "average_pct": avg, "top3_share": top3_share,
               "method": ("Equal-weight across the carried heavyweights. NSE does "
                          "not publish index weights freely, so this approximates "
                          "contribution rather than measuring it.")}

    # Volume confirmation — only available on the Dhan path, and only worth
    # stating when it exists. A sector move on thin volume is a different
    # object from the same move on heavy volume, and no free screener says so.
    vol_note = None
    with_vol = [m for m in movers if m.get("volume")]
    if len(with_vol) >= max(3, total // 2):
        risers = [m for m in with_vol if m["change_pct"] > 0]
        fallers = [m for m in with_vol if m["change_pct"] < 0]
        # Only worth saying when both sides exist. "0% of volume was in the
        # ones that rose" on a day nothing rose is not a finding, it is the
        # breadth line repeated in a more confusing form.
        if risers and fallers:
            rv = sum(m["volume"] for m in risers)
            fv = sum(m["volume"] for m in fallers)
            if rv + fv:
                share = round(100 * rv / (rv + fv))
                vol_note = (f"{share}% of the traded volume across these names was "
                            f"in the ones that rose")
                if share >= 75:
                    vol_note += " — the buying had size behind it"
                elif share <= 35:
                    vol_note += " — the selling carried the volume"

    filings, news_err = _news_for(names, WINDOWS[window]["news_hours"])

    by_sym = {m["symbol"]: m for m in movers}
    for n in filings:
        m = by_sym.get((n.get("symbol") or "").upper())
        if m:
            n["mover_change_pct"] = m["change_pct"]

    # Press is fetched and returned SEPARATELY. It is never merged into the
    # filing list and it never reaches a score — see news_feed.py.
    coverage, press_err = [], None
    if press is not None:
        try:
            coverage = press.feed(limit=8, symbols=names, sector=sector,
                                  max_age_hours=max(24, WINDOWS[window]["news_hours"]))
        except Exception as e:
            press_err = f"press feed unavailable ({str(e)[:60]})"

    # When Dhan served the constituents, the benchmark that rode along on the
    # same bulk call is the better comparison: it is the same snapshot, taken
    # at the same instant. Fetching a published index level separately would
    # cost a request and compare two different moments. The published index is
    # only pulled when Dhan could not serve the data at all.
    move = None
    if source != "dhan":
        m = _index_move(sector, sessions)
        if m and m.get("change_pct") is not None:
            move = m
            if move.get("benchmark_pct") is None and bench_pct is not None:
                move["benchmark_pct"] = bench_pct
                move["relative_pp"] = round(move["change_pct"] - bench_pct, 2)

    if move is None and avg is not None:
        move = {"index": sector,
                "change_pct": avg,
                "benchmark": "Nifty (NIFTYBEES proxy)",
                "benchmark_pct": bench_pct,
                "relative_pp": (round(avg - bench_pct, 2)
                                if bench_pct is not None else None),
                "proxy_note": ("Equal-weight average of the carried heavyweights "
                               "measured against NIFTYBEES in the same snapshot — "
                               "not the published index level.")}

    return {
        "sector": sector,
        "window": window,
        "window_label": WINDOWS[window]["label"],
        "source": source,
        "move": move,
        "movers": movers,
        "laggards": movers[::-1][:5],
        "breadth": breadth,
        "volume_note": vol_note,
        "filings": filings,
        "news": filings,                 # kept so existing callers do not break
        "press": coverage,
        "press_disclaimer": ("Press coverage is reporting about events, not the "
                             "events themselves. It is listed separately from "
                             "exchange filings and does not affect any score."),
        "narrative": _narrate(sector, move or {}, movers, breadth, filings,
                              window, vol_note),
        "constituents_as_of": CONSTITUENTS_AS_OF,
        "notes": [n for n in (price_note, news_err, press_err) if n],
        "disclaimer": ("Every figure here is a measurement over a stated window. "
                       "Nothing on this screen forecasts what happens next."),
    }


def overview(window: str = "1D", with_stocks: bool = False) -> dict:
    """
    Every sector ranked by strength relative to the benchmark.

    On the Dhan path this is ONE request for the whole market — every
    constituent of every sector plus the benchmark proxy in a single bulk
    quote — rather than eleven separate index downloads. That is the whole
    reason for paying for the feed.
    """
    if window not in WINDOWS:
        window = "1D"
    sessions = WINDOWS[window]["sessions"]

    every = sorted({s_ for names in CONSTITUENTS.values() for s_ in names})

    rows_all, bench_pct, source, note = (
        _returns(every, sessions) if sessions <= 1
        else ({}, None, "none", "Multi-session overview falls back to index downloads.")
    )

    out = []
    if rows_all:
        for sector, names in CONSTITUENTS.items():
            vals = [rows_all[n]["change_pct"] for n in names if n in rows_all]
            if not vals:
                continue
            avg = round(sum(vals) / len(vals), 2)
            row = {
                "sector": sector,
                "icon": SECTOR_ICON.get(sector),
                "index": f"{sector} (equal-weight)",
                "change_pct": avg,
                "benchmark": "Nifty (NIFTYBEES proxy)",
                "benchmark_pct": bench_pct,
                "relative_pp": (round(avg - bench_pct, 2)
                                if bench_pct is not None else None),
                "up": sum(1 for v in vals if v > 0),
                "down": sum(1 for v in vals if v < 0),
                "flat": sum(1 for v in vals if v == 0),
                "total": len(vals),
            }
            if with_stocks:
                # The bulk quote already fetched every one of these. Returning
                # them costs nothing and saves the client a second round trip
                # for the one thing a reader always wants next: which names
                # inside the sector are actually doing the moving.
                stocks = [{"symbol": n,
                           "change_pct": rows_all[n]["change_pct"],
                           "ltp": rows_all[n].get("ltp"),
                           "volume": rows_all[n].get("volume")}
                          for n in names if n in rows_all]
                stocks.sort(key=lambda r: -(r["change_pct"] or 0))
                row["stocks"] = stocks
                row["leader"] = stocks[0] if stocks else None
                row["laggard"] = stocks[-1] if len(stocks) > 1 else None
            out.append(row)
    else:
        # Fallback: published index levels, one download each.
        for sector in CONSTITUENTS:
            m = _index_move(sector, sessions)
            if m and m.get("change_pct") is not None:
                out.append({"sector": sector, "icon": SECTOR_ICON.get(sector), **m})
        source = "yahoo"

    out.sort(key=lambda r: -(r["relative_pp"] if r.get("relative_pp") is not None
                             else r.get("change_pct") or -99))
    return {"window": window, "window_label": WINDOWS[window]["label"],
            "source": source, "rows": out,
            "as_of": dt.datetime.now(dt.timezone.utc).isoformat(),
            "constituents_as_of": CONSTITUENTS_AS_OF,
            "notes": [n for n in (note,) if n],
            "note": ("Ranked by return relative to the Nifty over the window. "
                     "Sector returns are equal-weight across the carried "
                     "heavyweights, not published index levels. Open any sector "
                     "for the constituent-level explanation.")}
