"""
Altaha Screener — API
Run locally:  uvicorn main:app --reload
Deploy free:  Render.com web service, start command:
              uvicorn main:app --host 0.0.0.0 --port $PORT
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import yfinance as yf
import pandas as pd

from engine import technical_score, fundamental_score, composite

app = FastAPI(title="Altaha Screener API", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # tighten to your frontend domain after launch
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


def resolve_ticker(raw: str):
    """Try the symbol as given, then NSE (.NS), then BSE (.BO)."""
    raw = raw.strip().upper()
    candidates = [raw] if "." in raw else [raw, f"{raw}.NS", f"{raw}.BO"]
    for sym in candidates:
        t = yf.Ticker(sym)
        hist = t.history(period="1y", auto_adjust=True)
        if hist is not None and len(hist) >= 60:
            return sym, t, hist
    return None, None, None


@app.get("/")
def root():
    return {"app": "Altaha Screener", "tagline": "Where Logic Meets Validations",
            "endpoint": "/analyze?ticker=RELIANCE  or  /analyze?ticker=NVDA"}


@app.get("/analyze")
def analyze(ticker: str):
    if not ticker or len(ticker) > 20:
        raise HTTPException(400, "Provide a valid ticker symbol.")

    sym, t, hist = resolve_ticker(ticker)
    if sym is None:
        raise HTTPException(
            404,
            f"Could not find price history for '{ticker}'. "
            "Try the exact exchange symbol (e.g. RELIANCE, TCS, NVDA, AAPL).",
        )

    hist = hist.dropna(subset=["Close"])
    tech = technical_score(hist)

    # Fundamentals — degrade gracefully if statements are sparse
    try:
        info = t.info or {}
    except Exception:
        info = {}
    try:
        fin = t.financials
        bs = t.balance_sheet
        cf = t.cashflow
    except Exception:
        fin = bs = cf = pd.DataFrame()

    fund = fundamental_score(fin, bs, cf, info)
    verdict = composite(tech, fund)

    currency = info.get("currency") or ("INR" if sym.endswith((".NS", ".BO")) else "USD")

    return {
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
    }
