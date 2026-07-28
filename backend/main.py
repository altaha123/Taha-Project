"""
Altaha Screener — API  (v1.2 — numpy-safe responses)
Start command on Render:  uvicorn main:app --host 0.0.0.0 --port $PORT
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import numpy as np
import yfinance as yf
import pandas as pd

from engine import technical_score, fundamental_score, composite

app = FastAPI(title="Altaha Screener API", version="1.2")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

DISCLAIMER = (
    "Altaha Screener is an educational analysis tool. Scores are objective "
    "computations from public data using disclosed formulas. Nothing here is "
    "investment advice or a recommendation to buy or sell any security. "
    "Markets carry risk of loss. Do your own research or consult a "
    "SEBI-registered adviser."
)

BUSY_MSG = (
    "The data provider is temporarily rate-limiting requests. "
    "Wait about a minute and try again."
)


def to_native(obj):
    """Recursively convert numpy types to plain Python so JSON encoding never fails."""
    if isinstance(obj, dict):
        return {k: to_native(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_native(v) for v in obj]
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.floating):
        v = float(obj)
        return None if (v != v or v in (float("inf"), float("-inf"))) else v
    if isinstance(obj, float):
        return None if (obj != obj or obj in (float("inf"), float("-inf"))) else obj
    return obj


def fetch_history(sym: str):
    try:
        t = yf.Ticker(sym)
        hist = t.history(period="1y", auto_adjust=True)
        if hist is not None and len(hist) >= 60:
            return t, hist, False
        return None, None, False
    except Exception as e:
        msg = str(e).lower()
        blocked = any(k in msg for k in ("429", "rate", "limit", "denied", "blocked", "crumb", "unauthorized"))
        return None, None, blocked


def resolve_ticker(raw: str):
    raw = raw.strip().upper()
    candidates = [raw] if "." in raw else [raw, f"{raw}.NS", f"{raw}.BO"]
    any_blocked = False
    for sym in candidates:
        t, hist, blocked = fetch_history(sym)
        any_blocked = any_blocked or blocked
        if hist is not None:
            return sym, t, hist, False
    return None, None, None, any_blocked


@app.get("/")
def root():
    return {"app": "Altaha Screener", "tagline": "Where Logic Meets Validations",
            "endpoint": "/analyze?ticker=RELIANCE  or  /analyze?ticker=NVDA"}


@app.get("/analyze")
def analyze(ticker: str):
    if not ticker or len(ticker) > 20:
        raise HTTPException(400, "Provide a valid ticker symbol.")

    try:
        sym, t, hist, blocked = resolve_ticker(ticker)
    except Exception:
        raise HTTPException(503, BUSY_MSG)

    if sym is None:
        if blocked:
            raise HTTPException(503, BUSY_MSG)
        raise HTTPException(
            404,
            f"Could not find price history for '{ticker}'. "
            "Try the exact exchange symbol (e.g. RELIANCE, TCS, NVDA, AAPL).",
        )

    try:
        hist = hist.dropna(subset=["Close"])
        tech = technical_score(hist)
    except Exception:
        raise HTTPException(500, "Scoring failed for this ticker's price data. Try another symbol.")

    info, fin, bs, cf = {}, pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
    try:
        info = t.info or {}
    except Exception:
        pass
    try:
        fin = t.financials
    except Exception:
        pass
    try:
        bs = t.balance_sheet
    except Exception:
        pass
    try:
        cf = t.cashflow
    except Exception:
        pass

    try:
        fund = fundamental_score(fin, bs, cf, info)
    except Exception:
        fund = {"score": None, "f_score": None, "checks": []}

    verdict = composite(tech, fund)
    currency = info.get("currency") or ("INR" if sym.endswith((".NS", ".BO")) else "USD")

    return to_native({
        "ticker": sym,
        "name": info.get("longName") or info.get("shortName") or sym,
        "exchange": "NSE" if sym.endswith(".NS") else ("BSE" if sym.endswith(".BO") else info.get("exchange", "—")),
        "currency": currency,
        "price": tech["price"],
        "atr_pct": tech["atr_pct"],
        "verdict": verdict,
        "technical": {"score": tech["score"], "checks": tech["checks"]},
        "fundamental": {"score": fund["score"], "f_score": fund["f_score"], "checks": fund["checks"]},
        "disclaimer": DISCLAIMER,
    })
