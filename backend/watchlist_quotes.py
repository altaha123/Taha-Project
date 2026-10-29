"""
Altaha Screener — Watchlist quotes

WHAT THIS IS FOR
A watchlist is a list of names somebody wants to glance at, so the one request
it makes has to answer for the whole list at once: the last price, today's
move, the week and the month, and enough closes to draw a sparkline. Before
this file the only quotes the site handed a watchlist were the dozen sector
heavyweights the Today page already had, so most names on most lists showed
a blank.

WHERE THE NUMBERS COME FROM
  1. Yahoo, one batched daily download per chunk of names — the closes, the
     day's move and the sparkline. Cached per symbol, so a list of forty that
     shares thirty names with somebody else's costs ten.
  2. Dhan, when it is configured — one bulk quote for the whole list lays the
     live last price and the exchange's previous close over the daily bars.
  3. The universe scan — the Altaha Score, its label, the name and the sector,
     read from the payload already in memory. No request at all.

WHAT IT REFUSES TO DO
  · More than CHUNK uncached names per request. The rest come back as
    `pending` and the page asks again; a 100-name list must not turn one
    request into a two-minute download on a 512 MB instance.
  · Two downloads at once. A second caller while one is running gets the cache
    and a `pending` list, not a second batch of threads.
"""

import datetime as dt
import math
import re
import threading
import time

try:
    import pandas as pd
except Exception:                                   # pragma: no cover
    pd = None

try:
    import yfinance as yf
except Exception:                                   # pragma: no cover
    yf = None

try:
    import dhan_source as dhan
except Exception:                                   # pragma: no cover
    dhan = None

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
MAX_SYMBOLS = 100
CHUNK = 25                 # uncached names fetched per request
SPARK = 30                 # closes kept for the sparkline
TTL_OPEN = 180             # seconds, while the market is open
TTL_SHUT = 1800            # seconds, otherwise
MAX_CACHE = 800

_cache = {}                # SYMBOL -> (fetched_at, row)
_fetch_lock = threading.Lock()
# Dhan's quote endpoint is rate limited to about one call a second across the
# whole app, and a list polled by twenty readers must not spend all of it.
LIVE_TTL = 20
_live = {}                 # SYMBOL -> (fetched_at, {"ltp", "prev_close"})


def clean(symbols) -> list:
    out, seen = [], set()
    for raw in symbols or []:
        s = str(raw or "").strip().upper().replace(".NS", "").replace(".BO", "")
        if not re.match(r"^[A-Z0-9&.\-]{1,20}$", s) or s in seen:
            continue
        seen.add(s)
        out.append(s)
        if len(out) >= MAX_SYMBOLS:
            break
    return out


def market_open(now=None) -> bool:
    n = (now or dt.datetime.now(dt.timezone.utc)).astimezone(IST)
    m = n.hour * 60 + n.minute
    return n.weekday() < 5 and 555 <= m < 930


def _ttl(now=None):
    return TTL_OPEN if market_open(now) else TTL_SHUT


def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _pct(a, b):
    a, b = _num(a), _num(b)
    if a is None or not b:
        return None
    return round(100 * (a / b - 1), 2)


def _row_from_closes(sym, closes):
    """closes: a pandas Series of daily closes, oldest first, dated."""
    c = closes.dropna()
    if len(c) < 2:
        return None
    vals = [float(v) for v in c.tolist()]
    last, prev = vals[-1], vals[-2]
    try:
        dates = [d.date().isoformat() for d in c.index[-SPARK:]]
    except Exception:
        dates = []
    last_date = dates[-1] if dates else None
    return {
        "symbol": sym, "ltp": round(last, 2), "prev_close": round(prev, 2),
        "change_pct": _pct(last, prev),
        "week_pct": _pct(last, vals[-6]) if len(vals) >= 6 else None,
        "month_pct": _pct(last, vals[-22]) if len(vals) >= 22 else _pct(last, vals[0]),
        "spark": [round(v, 2) for v in vals[-SPARK:]],
        # The session each close belongs to, so a day's move can be read back
        # later — the watchlist game scores yesterday's pick this morning.
        "spark_dates": dates,
        "last_date": last_date, "source": "Yahoo Finance (daily, delayed)",
    }


def _yahoo(symbols) -> dict:
    if yf is None or pd is None or not symbols:
        return {}
    tickers = [f"{s}.NS" for s in symbols]
    try:
        raw = yf.download(tickers, period="3mo", interval="1d", progress=False,
                          auto_adjust=True, threads=False)      # see ythreads.py
    except Exception:
        return {}
    if raw is None or getattr(raw, "empty", True):
        return {}
    try:
        closes = raw["Close"] if "Close" in raw else raw
    except Exception:
        return {}
    out = {}
    for sym, tk in zip(symbols, tickers):
        try:
            if hasattr(closes, "columns"):
                col = closes[tk] if tk in closes.columns else None
            else:
                col = closes if len(tickers) == 1 else None
            if col is None:
                continue
            row = _row_from_closes(sym, col)
            if row:
                out[sym] = row
        except Exception:
            continue
    return out


def _dhan_overlay(symbols) -> dict:
    """{SYMBOL: {"ltp", "prev_close"}} from one bulk quote, or {}."""
    if dhan is None:
        return {}
    try:
        if not dhan.configured():
            return {}
    except Exception:
        return {}
    t = time.time()
    out = {s: _live[s][1] for s in symbols if s in _live and t - _live[s][0] < LIVE_TTL}
    need = [s for s in symbols if s not in out]
    if not need:
        return out
    try:
        snap = dhan.bulk_quotes(need, mode="ohlc") or {}
    except Exception:
        return out
    for sym, q in snap.items():
        ltp, prev = _num((q or {}).get("ltp")), _num((q or {}).get("prev_close"))
        if ltp:
            row = {"ltp": ltp, "prev_close": prev}
            _live[str(sym).upper()] = (t, row)
            out[str(sym).upper()] = row
    if len(_live) > MAX_CACHE:
        for sym in sorted(_live, key=lambda k: _live[k][0])[: len(_live) - MAX_CACHE]:
            _live.pop(sym, None)
    return out


def _trim_cache():
    if len(_cache) <= MAX_CACHE:
        return
    for sym in sorted(_cache, key=lambda k: _cache[k][0])[: len(_cache) - MAX_CACHE]:
        _cache.pop(sym, None)


def quotes(symbols, scan_rows=None, now=None, fetch=None) -> dict:
    """
    Quotes for one list. Returns {"rows", "pending", "market_open", "as_of"}.

    scan_rows  the universe scan's rows, for score, label, name and sector
    fetch      replaces the Yahoo download (tests)
    """
    now = now or dt.datetime.now(dt.timezone.utc)
    syms = clean(symbols)
    ttl, t = _ttl(now), time.time()
    fresh = {s: _cache[s][1] for s in syms if s in _cache and t - _cache[s][0] < ttl}
    need = [s for s in syms if s not in fresh]
    pending = []
    if need:
        batch, pending = need[:CHUNK], need[CHUNK:]
        if _fetch_lock.acquire(blocking=False):
            try:
                got = (fetch or _yahoo)(batch)
                for s, row in got.items():
                    _cache[s] = (time.time(), row)
                    fresh[s] = row
                _trim_cache()
            finally:
                _fetch_lock.release()
        else:
            pending = need
        # A name Yahoo had nothing for is not pending — asking again will not
        # change the answer. Its stale copy, if any, is better than a blank.
        for s in batch:
            if s not in fresh and s in _cache:
                fresh[s] = _cache[s][1]

    live = _dhan_overlay(syms) if syms else {}
    scan = {}
    for r in scan_rows or []:
        sym = str(r.get("symbol") or "").upper()
        if sym:
            scan[sym] = r

    rows = []
    for s in syms:
        base = dict(fresh.get(s) or {"symbol": s, "ltp": None, "change_pct": None, "spark": []})
        lv = live.get(s)
        if lv:
            base["ltp"] = round(lv["ltp"], 2)
            if lv.get("prev_close"):
                base["prev_close"] = round(lv["prev_close"], 2)
                base["change_pct"] = _pct(lv["ltp"], lv["prev_close"])
            base["source"] = "Dhan (live)"
        sr = scan.get(s) or {}
        if base.get("ltp") is None and _num(sr.get("price")):
            base["ltp"] = round(_num(sr.get("price")), 2)
            base["source"] = "Universe scan price"
        base.update({"name": sr.get("name") or base.get("name"), "sector": sr.get("sector"),
                     "score": _num(sr.get("composite")), "label": sr.get("label"),
                     "tone": sr.get("tone")})
        rows.append(base)
    return {"rows": rows, "pending": [s for s in pending if s not in fresh],
            "market_open": market_open(now), "as_of": now.isoformat(timespec="seconds"),
            "note": ("Daily closes from Yahoo Finance, delayed; the live last price comes from "
                     "Dhan when it is connected. Scores are from the latest universe scan.")}


# Large, liquid and familiar: the names a new reader recognises, so the
# featured list is something to play with on the first visit, not homework.
GIANTS = ["RELIANCE", "HDFCBANK", "ICICIBANK", "BHARTIARTL", "TCS", "INFY",
          "SBIN", "LT", "ITC", "HINDUNILVR", "KOTAKBANK", "AXISBANK"]


def featured(scan_payload=None, open_calls=None) -> dict:
    """Lists everyone can see and copy. Built from what the site already holds."""
    lists = []
    calls = []
    for c in open_calls or []:
        if c.get("symbol") and c["symbol"] not in calls:
            calls.append(c["symbol"])
    if calls:
        lists.append({"id": "f-calls", "name": "Altaha open calls", "emoji": "📣", "color": "gold",
                      "blurb": "Every name the Ideas list is calling right now. Changes with each scan.",
                      "symbols": calls[:15]})
    ranked = [r for r in (scan_payload or {}).get("rankings") or [] if r.get("symbol")]
    if ranked:
        top = sorted(ranked, key=lambda r: -(_num(r.get("composite")) or 0))[:12]
        lists.append({"id": "f-top", "name": "Top of the scan", "emoji": "🏆", "color": "green",
                      "blurb": "The twelve highest Altaha Scores in the latest universe scan.",
                      "symbols": [r["symbol"].upper() for r in top]})
    lists.append({"id": "f-giants", "name": "Nifty giants", "emoji": "🐘", "color": "blue",
                  "blurb": "The market's heaviest names. A good list to race on a busy day.",
                  "symbols": list(GIANTS)})
    return {"lists": lists}
