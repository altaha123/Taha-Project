"""
Altaha Screener — API  (v2.1 — on-demand scanning)
Start command on Render:  uvicorn main:app --host 0.0.0.0 --port $PORT
"""

import json
import os
import threading
import time

from fastapi import FastAPI, HTTPException, Body
from fastapi.middleware.cors import CORSMiddleware
import numpy as np
import pandas as pd

from engine import technical_score, fundamental_score, composite
from data_source import resolve, fundamentals, shareholding, NotFound
try:
    import dhan_source as dhan
except Exception:
    dhan = None
import scan as scanner
from results import quarterly_results
from levels import compute_levels
from tradeplan import build_plan
from portfolio import build_report, MAX_HOLDINGS, WORKERS as PF_WORKERS
from concurrent.futures import ThreadPoolExecutor, as_completed
import archetypes as A
import intraday
import alerts as notify
from plain import highlights, plain_verdict

app = FastAPI(title="Altaha Screener API", version="2.1")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

DISCLAIMER = (
    "Altaha Screener is an educational analysis tool. Scores are objective "
    "computations from public data using disclosed formulas. Nothing here is "
    "investment advice or a recommendation to buy or sell any security. "
    "Rankings reflect scores on the stated date and change as prices and "
    "filings change. Markets carry risk of loss. Do your own research or "
    "consult a SEBI-registered adviser."
)

LEADERBOARD_FILE = scanner.OUT_FILE
RESULT_TTL = 12 * 3600          # a ranking older than this is stale

# ---------------------------------------------------------------------------
# Scan job state — one scan at a time, shared by everyone
# ---------------------------------------------------------------------------

_lock = threading.Lock()
_state = {
    "status": "idle",           # idle | running | done | error
    "done": 0, "total": 0, "scored": 0,
    "started_at": None, "finished_at": None,
    "error": None,
    "payload": None,
}



# ---------------------------------------------------------------------------
# Admin guard
#
# Every control endpoint below was previously open to anyone who found the
# Render URL: they could stop the scanner, spam the Telegram alerts, or kick
# off a universe scan that burns the Dhan rate limit. Set ADMIN_KEY in the
# environment and pass ?key=... to use them. If ADMIN_KEY is unset the guard
# stays open, so nothing breaks for a local run — but it should be set in
# production.
# ---------------------------------------------------------------------------

ADMIN_KEY = os.environ.get("ADMIN_KEY", "").strip()


def _require_admin(key: str = ""):
    if ADMIN_KEY and key != ADMIN_KEY:
        raise HTTPException(401, "This control endpoint needs the admin key (?key=...).")


def _load_from_disk():
    if os.path.exists(LEADERBOARD_FILE):
        try:
            with open(LEADERBOARD_FILE) as f:
                _state["payload"] = json.load(f)
                _state["status"] = "done"
                _state["finished_at"] = os.path.getmtime(LEADERBOARD_FILE)
        except Exception:
            pass


_load_from_disk()


def _autostart_intraday():
    """
    Render restarts the process on deploy, on idle wake-up, and sometimes for
    no visible reason. A scanner that only starts when a human presses a button
    silently stops alerting after the first restart, which is the worst kind of
    failure: quiet. So it re-arms itself on boot.
    """
    if os.environ.get("INTRADAY_AUTOSTART", "").strip().lower() not in ("1", "true", "yes"):
        return
    try:
        limit = int(os.environ.get("INTRADAY_WATCHLIST", "200"))
    except ValueError:
        limit = 200
    try:
        if dhan is not None and dhan.configured():
            intraday.start(_default_watchlist(limit))
    except Exception:
        pass


def _worker():
    def progress(done, total, scored):
        _state["done"], _state["total"], _state["scored"] = done, total, scored

    def checkpoint(partial_payload):
        # Partial rankings become visible immediately and survive a process
        # restart (they're also written to disk by the scanner), so the Ideas
        # tab is never left empty after minutes of scanning.
        _state["payload"] = partial_payload

    try:
        payload = scanner.run_scan(progress=progress, checkpoint=checkpoint)
        _state["payload"] = payload
        _state["status"] = "done"
        _state["finished_at"] = time.time()
        _state["error"] = None
    except MemoryError:
        _state["status"] = "done" if _state["payload"] else "error"
        _state["finished_at"] = time.time()
        _state["error"] = "ran out of memory — partial results kept" \
            if _state["payload"] else "out of memory before any results"
    except Exception as e:
        if _state["payload"]:
            _state["status"] = "done"
            _state["finished_at"] = time.time()
            _state["error"] = "scan interrupted — partial results kept: " + str(e)[:120]
        else:
            _state["status"] = "error"
            _state["error"] = str(e)[:200]


def to_native(obj):
    if isinstance(obj, dict):
        return {k: to_native(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_native(v) for v in obj]
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        v = float(obj)
        return None if (v != v or v in (float("inf"), float("-inf"))) else v
    return obj


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/")
def root():
    return {"app": "Altaha Screener", "tagline": "Where Logic Meets Validations",
            "endpoints": ["/analyze?ticker=RELIANCE", "/leaderboard",
                          "/scan/start", "/scan/status", "/health"]}


INDICES = [("^NSEI", "NIFTY 50"), ("^BSESN", "SENSEX"),
            ("^NSEBANK", "BANK NIFTY"), ("^INDIAVIX", "INDIA VIX")]


@app.get("/market")
def market():
    """Index levels for the ticker strip. Cached by the data layer."""
    import datetime as _dt
    out = []
    for sym, label in INDICES:
        try:
            _, t, hist = resolve(sym)
            c = hist["Close"].dropna()
            if len(c) < 2:
                continue
            last, prev = float(c.iloc[-1]), float(c.iloc[-2])
            out.append({"label": label, "level": round(last, 2),
                        "change": round(last - prev, 2),
                        "change_pct": round(100 * (last - prev) / prev, 2)})
        except Exception:
            continue

    # Market session status, IST
    dhan_status = None
    if dhan is not None and dhan.configured():
        try:
            dhan_status = dhan.market_status()
        except Exception:
            dhan_status = None

    now = _dt.datetime.utcnow() + _dt.timedelta(hours=5, minutes=30)
    mins = now.hour * 60 + now.minute
    weekday = now.weekday() < 5
    if not weekday:
        status = "closed"
    elif 555 <= mins < 915:          # 09:15 - 15:30
        status = "open"
    elif mins < 555:
        status = "pre"
    else:
        status = "closed"
    if dhan_status:
        if "open" in dhan_status:
            status = "open"
        elif "pre" in dhan_status:
            status = "pre"
        elif "close" in dhan_status:
            status = "closed"

    return to_native({"indices": out, "status": status,
                      "ist": now.strftime("%d %b %Y, %H:%M IST")})


@app.get("/datasource")
def datasource():
    """Which price feed is live right now, and why."""
    if dhan is None or not dhan.configured():
        return {"price_source": "yahoo", "dhan_configured": False,
                "detail": "Set DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN in Render to enable Dhan."}
    st = dhan.is_live()
    scrip = dhan.load_scrip()
    return {"price_source": "dhan" if st["ok"] else "yahoo (dhan unavailable)",
            "dhan_configured": True, "dhan_ok": st["ok"], "detail": st["detail"],
            "instruments_mapped": len(scrip or {}),
            "scrip_error": getattr(dhan, "_scrip", {}).get("error"),
            "token": dhan.token_info()}


@app.get("/health")
def health():
    try:
        sym, t, h = resolve("AAPL")
        return {"data_layer": "ok", "rows": len(h), "last_close": round(float(h["Close"].iloc[-1]), 2)}
    except Exception as e:
        return {"data_layer": "unreachable", "detail": str(e)[:200]}


@app.post("/scan/start")
@app.get("/scan/start")
def scan_start(force: bool = False, key: str = ""):
    """Kick off a background scan. Returns immediately."""
    _require_admin(key)
    with _lock:
        if _state["status"] == "running":
            return {"started": False, "reason": "already_running", **scan_status()}

        fresh = (_state["payload"] is not None
                 and _state["finished_at"]
                 and (time.time() - _state["finished_at"]) < RESULT_TTL)
        if fresh and not force:
            return {"started": False, "reason": "cached", **scan_status()}

        _state.update({"status": "running", "done": 0, "scored": 0,
                       "total": len(scanner.universe()),
                       "started_at": time.time(), "error": None})
        threading.Thread(target=_worker, daemon=True).start()
        return {"started": True, **scan_status()}


@app.get("/scan/status")
def scan_status():
    elapsed = int(time.time() - _state["started_at"]) if _state["started_at"] else 0
    out = {
        "status": _state["status"],
        "done": _state["done"], "total": _state["total"], "scored": _state["scored"],
        "elapsed_seconds": elapsed if _state["status"] == "running" else None,
        "error": _state["error"],
    }
    if _state["payload"]:
        out["scanned_at"] = _state["payload"].get("scanned_at")
    return out


HORIZONS = {
    "short": {"keys": ["momentum_breakout", "institutional_accumulation"],
              "label": "Short-term setups",
              "note": ("Setups whose premise plays out in weeks to a few months: strong trends with "
                       "volume behind them, and accumulation footprints that haven't fully moved yet. "
                       "These decay fastest — re-scan often.")},
    "medium": {"keys": ["quality_at_discount", "turnaround"],
               "label": "Medium-term setups",
               "note": ("Setups whose premise needs quarters, not weeks: quality businesses in a "
                        "drawdown, and companies whose fundamentals are inflecting. Judged mainly on "
                        "filings, so re-check after each results season.")},
}


@app.get("/ideas")
def ideas(horizon: str = "short", limit: int = 15):
    h = HORIZONS.get(horizon)
    if not h:
        raise HTTPException(400, "horizon must be 'short' or 'medium'")
    p = _state["payload"]
    if not p:
        return {"available": False, "status": _state["status"],
                "message": "No scan yet — generate the ranking first."}
    limit = max(1, min(limit, 25))
    rows = [r for r in p.get("rankings", []) if r.get("setup_key") in h["keys"]]
    rows.sort(key=lambda r: (r.get("setup_fit") or 0, r.get("composite") or 0), reverse=True)
    rows = rows[:limit]

    # Never hand the UI an empty list when a scan exists. If few names fit
    # this horizon's archetypes cleanly, top up with the highest-composite
    # names overall, clearly flagged so the frontend can label them.
    fallback_used = False
    if len(rows) < min(8, limit):
        seen = {r.get("symbol") for r in rows}
        extras = [dict(r, fallback=True) for r in p.get("rankings", [])
                  if r.get("symbol") not in seen]
        extras.sort(key=lambda r: r.get("composite") or 0, reverse=True)
        extras = extras[: limit - len(rows)]
        fallback_used = bool(extras)
        rows += extras

    return {"available": True, "horizon": horizon, "label": h["label"], "note": h["note"],
            "scanned_at": p.get("scanned_at"),
            "partial": bool(p.get("partial")),
            "scored": p.get("scored"),
            "fallback_used": fallback_used,
            "rows": rows,
            "universe_source": p.get("universe_source"),
            "disclaimer": DISCLAIMER}


@app.get("/leaderboard")
def leaderboard(limit: int = 5):
    p = _state["payload"]
    if not p:
        return {"available": False, "status": _state["status"],
                "message": "No ranking generated yet."}
    return {
        "available": True,
        "status": _state["status"],
        "scanned_at": p.get("scanned_at"),
        "universe_size": p.get("universe_size"),
        "scored": p.get("scored"),
        "methodology": p.get("methodology"),
        "rankings": p.get("rankings", [])[: max(1, min(limit, 25))],
        "disclaimer": DISCLAIMER,
    }


def _analyse_holding(item):
    sym_in = str(item.get("symbol", "")).strip().upper()
    qty = float(item.get("qty") or 0)
    buy = item.get("buy_price")
    buy = float(buy) if buy not in (None, "",) else None
    if not sym_in or qty <= 0:
        return {"symbol": sym_in or "?", "error": "missing symbol or quantity",
                "value": 0.0, "cost": None}
    try:
        sym, t, hist = resolve(sym_in)
    except NotFound:
        return {"symbol": sym_in, "error": "symbol not found", "value": 0.0, "cost": None}
    except Exception:
        return {"symbol": sym_in, "error": "data provider busy", "value": 0.0, "cost": None}
    try:
        tech = technical_score(hist)
    except Exception:
        return {"symbol": sym_in, "error": "scoring failed", "value": 0.0, "cost": None}
    try:
        fin, bs, cf, info = fundamentals(sym, t)
        fund = fundamental_score(fin, bs, cf, info)
    except Exception:
        info, fund = {}, {"score": None, "f_score": None, "g_score": None, "checks": [], "extras": {}}
    v = composite(tech, fund)
    try:
        setup = A.evaluate(tech, fund)
    except Exception:
        setup = None
    price = float(tech["price"])
    return {
        "symbol": sym.replace(".NS", "").replace(".BO", ""),
        "name": info.get("longName") or info.get("shortName") or sym_in,
        "sector": info.get("sector"),
        "qty": qty, "buy_price": buy, "price": price,
        "value": round(qty * price, 2),
        "cost": round(qty * buy, 2) if buy is not None else None,
        "pnl_pct": round(100 * (price - buy) / buy, 2) if buy else None,
        "composite": v["score"], "tone": v["tone"],
        "technical": tech["score"], "fundamental": fund["score"],
        "setup": (setup or {}).get("name"), "setup_fit": (setup or {}).get("fit"),
        "horizon": (setup or {}).get("horizon"),
        "error": None,
    }


@app.post("/portfolio")
def portfolio(payload: dict = Body(...)):
    holdings = payload.get("holdings") or []
    if not isinstance(holdings, list) or not holdings:
        raise HTTPException(400, "Provide a holdings list.")
    if len(holdings) > MAX_HOLDINGS:
        raise HTTPException(400, f"Maximum {MAX_HOLDINGS} holdings per analysis — "
                                 "split larger portfolios into batches.")
    rows = [None] * len(holdings)
    with ThreadPoolExecutor(max_workers=PF_WORKERS) as pool:
        futures = {pool.submit(_analyse_holding, h): i for i, h in enumerate(holdings)}
        for fut in as_completed(futures):
            i = futures[fut]
            try:
                rows[i] = fut.result()
            except Exception:
                rows[i] = {"symbol": str(holdings[i].get("symbol", "?")),
                           "error": "analysis failed", "value": 0.0, "cost": None}
    report = build_report(rows, _state.get("payload"))
    report["disclaimer"] = DISCLAIMER
    return to_native(report)


@app.get("/results")
def results(ticker: str):
    if not ticker or len(ticker) > 20:
        raise HTTPException(400, "Provide a valid ticker symbol.")
    try:
        sym, t, hist = resolve(ticker)
    except NotFound:
        raise HTTPException(404, f"Couldn't find '{ticker.upper()}'. Check the spelling.")
    except Exception:
        raise HTTPException(503, "The data provider is busy. Try again in a minute.")
    try:
        qfin = t.quarterly_financials
        info = {}
        try:
            info = t.info or {}
        except Exception:
            pass
        name = info.get("longName") or info.get("shortName") or sym.replace(".NS","").replace(".BO","")
        out = quarterly_results(qfin, name, sym)
    except Exception:
        out = {"available": False,
               "message": "Quarterly statements could not be retrieved for this stock."}
    out["disclaimer"] = DISCLAIMER
    return to_native(out)


RANGES = {
    "1m":  {"mode": "intraday", "interval": "1",  "days": 4,   "label": "1 minute"},
    "5m":  {"mode": "intraday", "interval": "5",  "days": 10,  "label": "5 minute"},
    "15m": {"mode": "intraday", "interval": "15", "days": 25,  "label": "15 minute"},
    "1H":  {"mode": "intraday", "interval": "60", "days": 90,  "label": "1 hour"},
    "4H":  {"mode": "intraday", "interval": "60", "days": 240, "label": "4 hour",
            "resample": 4},
    "1D":  {"mode": "daily",    "sessions": 400,              "label": "1 day"},
    "1W":  {"mode": "daily",    "sessions": 1200, "resample_w": True, "label": "1 week"},
}


def _resample_hours(df, factor: int):
    """Combine N consecutive candles into one (for 4H from 60m)."""
    out = df.resample(f"{factor}h", origin="start", label="left", closed="left").agg(
        {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"})
    return out.dropna(subset=["Close"])


def _resample_weeks(df):
    out = df.resample("W-FRI", label="left", closed="left").agg(
        {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"})
    return out.dropna(subset=["Close"])


@app.get("/chart")
def chart(ticker: str, range: str = "1D"):
    """Candles for one symbol at a chosen timeframe, with overlays."""
    from engine import ema, bollinger
    raw = (range or "1D").strip()
    key = next((k for k in RANGES if k.lower() == raw.lower()), None)
    cfg = RANGES.get(key) if key else None
    if not cfg:
        raise HTTPException(400, f"range must be one of {', '.join(RANGES)}")

    base = ticker.strip().upper().replace(".NS", "").replace(".BO", "")
    df, live = None, False

    if cfg["mode"] == "intraday":
        if dhan is None or not dhan.configured():
            raise HTTPException(503, "Intraday charts need the Dhan data feed. "
                                     "Longer timeframes are available without it.")
        try:
            df = dhan.intraday_ohlcv(base, interval=cfg["interval"], days=cfg["days"])
        except Exception:
            df = None
        if df is None or len(df) < 5:
            raise HTTPException(404, f"No intraday data available for {base}. "
                                     "It may be a holiday, or the symbol may be unlisted.")
        live = True
        if cfg.get("resample") and isinstance(df.index, pd.DatetimeIndex):
            df = _resample_hours(df, cfg["resample"])
    else:
        try:
            sym, t, hist = resolve(base)
        except NotFound:
            raise HTTPException(404, f"Couldn't find '{base}'.")
        except Exception:
            raise HTTPException(503, "The data provider is busy. Try again in a minute.")
        df = hist.tail(cfg["sessions"])
        if cfg.get("resample_w") and isinstance(df.index, pd.DatetimeIndex):
            df = _resample_weeks(df)

    close = df["Close"]
    e20, e50 = ema(close, 20), ema(close, 50)
    _, bup, blo, _, _ = bollinger(close)

    rows = []
    for i in df.index:
        try:
            ts = int(pd.Timestamp(i).timestamp()) if isinstance(df.index, pd.DatetimeIndex) else None
            rows.append([
                ts,
                round(float(df.at[i, "Open"]), 2), round(float(df.at[i, "High"]), 2),
                round(float(df.at[i, "Low"]), 2), round(float(df.at[i, "Close"]), 2),
                None if pd.isna(e20.get(i)) else round(float(e20.get(i)), 2),
                None if pd.isna(e50.get(i)) else round(float(e50.get(i)), 2),
                None if pd.isna(bup.get(i)) else round(float(bup.get(i)), 2),
                None if pd.isna(blo.get(i)) else round(float(blo.get(i)), 2),
                int(df.at[i, "Volume"]) if "Volume" in df.columns and not pd.isna(df.at[i, "Volume"]) else 0,
            ])
        except Exception:
            continue

    if not rows:
        raise HTTPException(500, "Chart data could not be assembled for this symbol.")

    first, last = float(close.iloc[0]), float(close.iloc[-1])
    return to_native({
        "ticker": base, "range": key, "label": cfg["label"],
        "live": live, "source": "dhan" if live else "daily feed",
        "candles": rows,
        "last": round(last, 2),
        "change": round(last - first, 2),
        "change_pct": round(100 * (last - first) / first, 2) if first else None,
        "as_of": str(df.index[-1])[:19] if len(df) else None,
    })


@app.get("/quote")
def quote(ticker: str):
    """Single live quote — used by the chart's live tick mode."""
    if dhan is None or not dhan.configured():
        raise HTTPException(503, "Live quotes need the Dhan feed.")
    base = ticker.strip().upper().replace(".NS", "").replace(".BO", "")
    try:
        q = dhan.bulk_quotes([base], mode="ltp")
    except Exception:
        raise HTTPException(503, "Quote feed busy.")
    row = q.get(base)
    if not row or not row.get("ltp"):
        raise HTTPException(404, f"No live quote for {base}.")
    return to_native({"ticker": base, "ltp": row["ltp"], "ts": int(time.time())})


@app.get("/options/expiries")
def options_expiries(ticker: str):
    if dhan is None or not dhan.configured():
        raise HTTPException(503, "Options data needs the Dhan feed.")
    ex = dhan.expiry_list(ticker)
    if not ex:
        raise HTTPException(404, f"No option expiries found for {ticker.upper()}. "
                                 "Indices (NIFTY, BANKNIFTY, FINNIFTY, SENSEX) and "
                                 "F&O-listed stocks are supported — non-F&O stocks "
                                 "have no options to show.")
    return {"ticker": ticker.upper(), "expiries": ex[:12]}


@app.get("/options/chain")
def options_chain(ticker: str, expiry: str):
    if dhan is None or not dhan.configured():
        raise HTTPException(503, "Options data needs the Dhan feed.")
    raw = dhan.option_chain(ticker, expiry)
    data = (raw or {}).get("data") or {}
    oc = data.get("oc") or {}
    if not oc:
        raise HTTPException(404, "No option chain returned for that expiry. Dhan "
                                 "allows one chain request every 3 seconds — wait a "
                                 "moment and pick the expiry again.")

    spot = data.get("last_price")
    rows, ce_oi, pe_oi, ce_vol, pe_vol = [], 0, 0, 0, 0
    for strike, legs in sorted(oc.items(), key=lambda kv: float(kv[0])):
        ce = (legs or {}).get("ce") or {}
        pe = (legs or {}).get("pe") or {}
        g_ce = ce.get("greeks") or {}
        g_pe = pe.get("greeks") or {}
        ce_oi += ce.get("oi") or 0
        pe_oi += pe.get("oi") or 0
        ce_vol += ce.get("volume") or 0
        pe_vol += pe.get("volume") or 0
        rows.append({
            "strike": round(float(strike), 2),
            "ce_ltp": ce.get("last_price"), "pe_ltp": pe.get("last_price"),
            "ce_oi": ce.get("oi"), "pe_oi": pe.get("oi"),
            "ce_vol": ce.get("volume"), "pe_vol": pe.get("volume"),
            "ce_iv": ce.get("implied_volatility"), "pe_iv": pe.get("implied_volatility"),
            "ce_delta": g_ce.get("delta"), "pe_delta": g_pe.get("delta"),
        })

    # Max pain: strike where combined option-writer loss is smallest
    max_pain, best = None, None
    for r in rows:
        k = r["strike"]
        pain = sum(max(0, k - x["strike"]) * (x["ce_oi"] or 0) +
                   max(0, x["strike"] - k) * (x["pe_oi"] or 0) for x in rows)
        if best is None or pain < best:
            best, max_pain = pain, k

    if spot:
        rows = sorted(rows, key=lambda r: abs(r["strike"] - float(spot)))[:21]
        rows.sort(key=lambda r: r["strike"])

    return to_native({
        "ticker": ticker.upper(), "expiry": expiry, "spot": spot,
        "pcr_oi": round(pe_oi / ce_oi, 3) if ce_oi else None,
        "pcr_volume": round(pe_vol / ce_vol, 3) if ce_vol else None,
        "total_ce_oi": ce_oi, "total_pe_oi": pe_oi,
        "max_pain": max_pain,
        "rows": rows,
        "note": ("Put-call ratio above ~1 means more puts are open than calls, often read as "
                 "hedging or bearish positioning; below ~0.7 leans bullish. Max pain is the "
                 "strike where option writers lose least. Both are sentiment gauges, not "
                 "forecasts."),
        "disclaimer": DISCLAIMER,
    })


@app.get("/analyze")
def analyze(ticker: str):
    if not ticker or len(ticker) > 20:
        raise HTTPException(400, "Provide a valid ticker symbol.")

    try:
        sym, t, hist = resolve(ticker)
    except NotFound:
        raise HTTPException(
            404,
            f"Couldn't find '{ticker.upper()}'. Check the spelling — "
            "try RELIANCE, TCS, INFY, NVDA or AAPL.",
        )
    except Exception:
        raise HTTPException(503, "The data provider is busy. Try again in a minute.")

    try:
        tech = technical_score(hist)
    except Exception:
        raise HTTPException(500, "Scoring failed for this ticker's price data.")

    try:
        fin, bs, cf, info = fundamentals(sym, t)
        fund = fundamental_score(fin, bs, cf, info)
    except Exception:
        info, fund = {}, {"score": None, "f_score": None, "checks": []}

    try:
        holding = shareholding(t)
    except Exception:
        holding = {"published": False}

    try:
        lv = compute_levels(hist)
    except Exception:
        lv = None
    try:
        plan = build_plan(hist, lv, tech)
    except Exception:
        plan = None
    # Percentile vs the scanned universe — makes the score mean something.
    pct = None
    try:
        rows = (_state.get("payload") or {}).get("rankings") or []
        base = sym.replace(".NS", "").replace(".BO", "")
        mine = next((r for r in rows if r.get("symbol") == base), None)
        if mine and mine.get("composite") is not None and len(rows) >= 50:
            comps = [r["composite"] for r in rows if r.get("composite") is not None]
            pct = round(sum(1 for c in comps if c < mine["composite"]) / len(comps) * 100)
    except Exception:
        pct = None

    verdict = composite(tech, fund)
    try:
        setup = A.evaluate(tech, fund)
    except Exception:
        setup = None
    try:
        plain = {"verdict": plain_verdict(tech, fund, verdict, setup),
                 **highlights(tech, fund)}
    except Exception:
        plain = None
    currency = info.get("currency") or ("INR" if sym.endswith((".NS", ".BO")) else "USD")

    return to_native({
        "ticker": sym,
        "name": info.get("longName") or info.get("shortName") or sym.replace(".NS", "").replace(".BO", ""),
        "exchange": "NSE" if sym.endswith(".NS") else ("BSE" if sym.endswith(".BO") else info.get("exchange", "US")),
        "currency": currency,
        "price": tech["price"],
        "atr_pct": tech["atr_pct"],
        "volume_series": tech["volume_series"],
        "price_series": tech.get("price_series"),
        "shareholding": holding,
        "levels": lv,
        "plan": plan,
        "percentile": pct,
        "setup": setup,
        "plain": plain,
        "verdict": verdict,
        "technical": {"score": tech["score"], "checks": tech["checks"]},
        "fundamental": {"score": fund["score"], "f_score": fund["f_score"],
                        "g_score": fund.get("g_score"), "checks": fund["checks"]},
        "disclaimer": DISCLAIMER,
    })


# ---------------------------------------------------------------------------
# Live intraday scanner
# ---------------------------------------------------------------------------

def _default_watchlist(limit=200):
    """Liquid names: prefer the scanned leaderboard, else the curated core."""
    rows = (_state.get("payload") or {}).get("rankings") or []
    syms = [r["symbol"] for r in rows if r.get("symbol")][:limit]
    if len(syms) < 40:
        syms = sorted({s for s in scanner.FALLBACK.split() if s})[:limit]
    return syms


@app.post("/intraday/start")
def intraday_start(limit: int = 200, key: str = ""):
    _require_admin(key)
    if dhan is None or not dhan.configured():
        raise HTTPException(503, "Dhan is not configured — the live scanner needs it for quotes.")
    wl = _default_watchlist(limit)
    intraday.start(wl)
    return {"started": True, "watchlist_size": len(wl),
            "alerts_configured": notify.configured(),
            "note": ("Scans every 60s while the market is open. Alerts go to Telegram when "
                     "TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are set.")}


@app.post("/intraday/stop")
def intraday_stop(key: str = ""):
    _require_admin(key)
    intraday.stop()
    return {"stopped": True}


@app.get("/intraday/status")
def intraday_status():
    return intraday.status()


@app.post("/intraday/scan")
def intraday_scan_now(key: str = ""):
    _require_admin(key)
    """Force one pass — useful for testing outside market hours."""
    if not intraday._state["watch"]:
        intraday.start(_default_watchlist())
    fired = intraday.scan_once()
    return {"fired": fired, "count": len(fired), "status": intraday.status()}


@app.get("/intraday/stats")
def intraday_stats():
    return intraday.stats()


@app.post("/intraday/mark")
def intraday_mark(key: str = ""):
    _require_admin(key)
    return {"marked": intraday.mark_outcomes(), "stats": intraday.stats()}


@app.get("/alerts/test")
def alerts_test(key: str = ""):
    _require_admin(key)
    return notify.test()


@app.get("/cron/tick")
def cron_tick():
    """
    Keep-alive + self-heal endpoint. Point an external cron (cron-job.org,
    UptimeRobot) at this every 5 minutes: it stops Render's free tier from
    sleeping AND restarts the scanner thread if a restart killed it.
    """
    revived = False
    if not intraday._state["running"]:
        _autostart_intraday()
        revived = intraday._state["running"]
    fired, marked = [], 0
    if intraday.market_open() and intraday._state["running"]:
        try:
            fired = intraday.scan_once()
        except Exception:
            pass
    else:
        # Outcome marking previously ran ONLY inside the scanner loop. If the
        # process restarted after the close, or the scanner was stopped, that
        # day's alerts stayed permanently unmarked and never reached the hit
        # rate. The cron tick now closes that gap; mark_outcomes is idempotent.
        try:
            if intraday.now_ist().hour >= 16:
                marked = intraday.mark_outcomes()
        except Exception:
            pass
    return {"awake": True, "scanner_running": intraday._state["running"],
            "revived": revived, "market_open": intraday.market_open(),
            "fired_now": len(fired), "outcomes_marked": marked}


_autostart_intraday()
