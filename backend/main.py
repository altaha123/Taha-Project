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

from engine import technical_score, fundamental_score, composite
from data_source import resolve, fundamentals, shareholding, NotFound
try:
    import dhan_source as dhan
except Exception:
    dhan = None
import scan as scanner
from results import quarterly_results
from portfolio import build_report, MAX_HOLDINGS, WORKERS as PF_WORKERS
from concurrent.futures import ThreadPoolExecutor, as_completed
import archetypes as A
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


def _worker():
    def progress(done, total, scored):
        _state["done"], _state["total"], _state["scored"] = done, total, scored

    try:
        payload = scanner.run_scan(progress=progress)
        _state["payload"] = payload
        _state["status"] = "done"
        _state["finished_at"] = time.time()
        _state["error"] = None
    except Exception as e:
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
def scan_start(force: bool = False):
    """Kick off a background scan. Returns immediately."""
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
    rows = [r for r in p.get("rankings", []) if r.get("setup_key") in h["keys"]]
    rows.sort(key=lambda r: (r.get("setup_fit") or 0, r.get("composite") or 0), reverse=True)
    return {"available": True, "horizon": horizon, "label": h["label"], "note": h["note"],
            "scanned_at": p.get("scanned_at"),
            "rows": rows[: max(1, min(limit, 25))],
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
        "setup": setup,
        "plain": plain,
        "verdict": verdict,
        "technical": {"score": tech["score"], "checks": tech["checks"]},
        "fundamental": {"score": fund["score"], "f_score": fund["f_score"],
                        "g_score": fund.get("g_score"), "checks": fund["checks"]},
        "disclaimer": DISCLAIMER,
    })
