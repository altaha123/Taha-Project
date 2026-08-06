"""
Altaha Screener — API  (v2.1 — on-demand scanning)
Start command on Render:  uvicorn main:app --host 0.0.0.0 --port $PORT
"""

import json
import os
import threading
import time

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import numpy as np

from engine import technical_score, fundamental_score, composite
from data_source import resolve, fundamentals, shareholding, NotFound
import scan as scanner
import archetypes as A

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
    currency = info.get("currency") or ("INR" if sym.endswith((".NS", ".BO")) else "USD")

    return to_native({
        "ticker": sym,
        "name": info.get("longName") or info.get("shortName") or sym.replace(".NS", "").replace(".BO", ""),
        "exchange": "NSE" if sym.endswith(".NS") else ("BSE" if sym.endswith(".BO") else info.get("exchange", "US")),
        "currency": currency,
        "price": tech["price"],
        "atr_pct": tech["atr_pct"],
        "volume_series": tech["volume_series"],
        "shareholding": holding,
        "setup": setup,
        "verdict": verdict,
        "technical": {"score": tech["score"], "checks": tech["checks"]},
        "fundamental": {"score": fund["score"], "f_score": fund["f_score"],
                        "g_score": fund.get("g_score"), "checks": fund["checks"]},
        "disclaimer": DISCLAIMER,
    })
