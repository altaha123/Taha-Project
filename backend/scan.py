"""
Altaha Screener — Universe Scanner  (v3: full NSE, two-phase)

Phase 1 — BREADTH: fetch the official NSE equity list (~2,000 names), bulk-download
price history in chunks, apply a liquidity floor, and compute technical scores.
Bulk download means one request per ~40 stocks instead of one per stock.

Phase 2 — DEPTH: only the strongest Phase-1 candidates (default 200) get the
expensive per-stock work — fundamentals, shareholding, archetype classification.

Why two phases: fundamentals are the slow part (3-4 requests per stock). Doing
them for 2,000 names would take hours and mostly hit companies with no published
data. Doing them for the 200 that already cleared liquidity and technical bars
covers everything that could plausibly rank, in ~15-25 minutes.

Every exclusion is deliberate and logged: illiquid names are filtered with the
threshold stated, not silently missing.
"""

import io
import json
import os
import random
import time
import datetime as dt
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import requests
import yfinance as yf

from engine import technical_score, fundamental_score, composite
import archetypes as A

OUT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "leaderboard.json")

# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------
CHUNK = 40                 # symbols per bulk price request
PHASE2_SIZE = 200          # candidates that get full fundamental analysis
PHASE2_WORKERS = 3         # polite concurrency for per-stock fundamentals
MIN_ROWS = 120             # minimum trading days of history
MIN_TURNOVER = 2e7         # liquidity floor: avg daily traded value ≥ ₹2 crore
STORE_TOP = 60             # ranked rows kept in the output file

NSE_LIST_URLS = [
    "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv",
    "https://archives.nseindia.com/content/equities/EQUITY_L.csv",
]

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0 Safari/537.36")

# Fallback if NSE blocks the server — the curated liquid core.
FALLBACK = """
RELIANCE TCS HDFCBANK ICICIBANK INFY HINDUNILVR ITC SBIN BHARTIARTL LT
KOTAKBANK AXISBANK ASIANPAINT MARUTI TITAN SUNPHARMA ULTRACEMCO NESTLEIND
WIPRO ONGC NTPC POWERGRID TATAMOTORS TATASTEEL JSWSTEEL HINDALCO COALINDIA
BAJFINANCE BAJAJFINSV HCLTECH TECHM ADANIENT ADANIPORTS GRASIM DRREDDY
CIPLA DIVISLAB APOLLOHOSP BRITANNIA EICHERMOT HEROMOTOCO INDUSINDBK
SBILIFE HDFCLIFE ICICIGI ICICIPRULI SHRIRAMFIN PIDILITIND DABUR GODREJCP
MARICO COLPAL BERGEPAINT HAVELLS VOLTAS SIEMENS ABB BOSCHLTD CUMMINSIND
BEL HAL IRCTC INDIGO TRENT DMART JUBLFOOD NAUKRI ZOMATO NYKAA
MPHASIS PERSISTENT LTIM COFORGE OFSS TATAELXSI KPITTECH SONACOMS
BALKRISIND MRF APOLLOTYRE TVSMOTOR ASHOKLEY ESCORTS BHARATFORG MOTHERSON
EXIDEIND PIIND SRF AARTIIND DEEPAKNTR NAVINFLUOR ATUL TATACHEM UPL
COROMANDEL GNFC BASF LINDEINDIA LUPIN AUROPHARMA ALKEM TORNTPHARM
ZYDUSLIFE GLENMARK IPCALAB LAURUSLABS BIOCON ABBOTINDIA PFIZER
DLF GODREJPROP OBEROIRLTY PRESTIGE PHOENIXLTD BRIGADE SOBHA
AMBUJACEM ACC SHREECEM DALBHARAT JKCEMENT RAMCOCEM
VEDL NATIONALUM NMDC SAIL JINDALSTEL APLAPOLLO RATNAMANI
IOC BPCL HINDPETRO GAIL PETRONET IGL MGL GUJGASLTD OIL
PFC RECLTD IRFC LICHSGFIN CANFINHOME CHOLAFIN MUTHOOTFIN MANAPPURAM
BANKBARODA PNB CANBK UNIONBANK IDFCFIRSTB FEDERALBNK AUBANK BANDHANBNK
RBLBANK KARURVYSYA CUB TATAPOWER ADANIGREEN TORNTPOWER JSWENERGY NHPC SJVN
CONCOR GESHIP IRB KNRCON NBCC RVNL RAILTEL
PAGEIND KPRMILL TRIDENT WELSPUNLIV VBL RADICO UBL
BATAINDIA RELAXO METROBRAND CROMPTON WHIRLPOOL BLUESTARCO DIXON AMBER
CARBORUNIV GRINDWELL THERMAX AIAENG KEI POLYCAB FINCABLES SUPREMEIND
ASTRAL PRINCEPIPE CERA KAJARIACER CDSL BSE MCX ANGELONE IEX CAMS KFINTECH
"""


def fetch_nse_list():
    """Official NSE equity list. Returns (symbols, source_label)."""
    for url in NSE_LIST_URLS:
        try:
            r = requests.get(url, headers={"User-Agent": UA,
                                           "Accept": "text/csv,*/*",
                                           "Referer": "https://www.nseindia.com/"},
                             timeout=20)
            if r.status_code != 200 or "SYMBOL" not in r.text[:200]:
                continue
            df = pd.read_csv(io.StringIO(r.text))
            df.columns = [c.strip() for c in df.columns]
            if "SERIES" in df.columns:
                df = df[df["SERIES"].astype(str).str.strip() == "EQ"]
            syms = sorted({str(s).strip().upper() for s in df["SYMBOL"] if str(s).strip()})
            if len(syms) > 500:
                return syms, f"NSE official list ({len(syms)} EQ-series symbols)"
        except Exception:
            continue
    fb = sorted({s for s in FALLBACK.split() if s})
    return fb, f"Fallback curated list ({len(fb)} symbols) — NSE list unreachable from this server"


def universe():
    return fetch_nse_list()[0]


# ---------------------------------------------------------------------------
# Phase 1 — bulk prices, liquidity filter, technical scores
# ---------------------------------------------------------------------------

def phase1(symbols, progress, state):
    candidates, skipped_illiquid, skipped_nodata = [], 0, 0
    chunks = [symbols[i:i + CHUNK] for i in range(0, len(symbols), CHUNK)]

    for ci, chunk in enumerate(chunks):
        tickers = [f"{s}.NS" for s in chunk]
        try:
            data = yf.download(" ".join(tickers), period="1y", interval="1d",
                               group_by="ticker", auto_adjust=True,
                               threads=True, progress=False)
        except Exception:
            data = None
        time.sleep(0.6 + random.random() * 0.6)

        for s in chunk:
            state["done"] += 1
            t = f"{s}.NS"
            try:
                df = data[t].dropna(subset=["Close"]) if data is not None else None
                if df is None or len(df) < MIN_ROWS:
                    skipped_nodata += 1
                    continue
                turnover = float((df["Close"] * df["Volume"]).tail(60).mean())
                if turnover < MIN_TURNOVER:
                    skipped_illiquid += 1
                    continue
                tech = technical_score(df)
                candidates.append({"symbol": s, "tech": tech, "turnover": turnover})
            except Exception:
                skipped_nodata += 1
        if progress:
            progress(state["done"], state["total"], len(candidates))

    candidates.sort(key=lambda c: c["tech"]["score"], reverse=True)
    return candidates, skipped_illiquid, skipped_nodata


# ---------------------------------------------------------------------------
# Phase 2 — fundamentals + archetypes for the strongest candidates
# ---------------------------------------------------------------------------

def deep_score(cand):
    time.sleep(random.uniform(0.15, 0.5))
    s = cand["symbol"]
    tech = cand["tech"]
    t = yf.Ticker(f"{s}.NS")
    try:
        fin, bs, cf = t.financials, t.balance_sheet, t.cashflow
        info = dict(t.info or {})
    except Exception:
        return None
    fund = fundamental_score(fin, bs, cf, info)
    if fund["score"] is None:
        return None
    v = composite(tech, fund)
    try:
        setup = A.evaluate(tech, fund)
    except Exception:
        setup = None
    return {
        "symbol": s, "ticker": f"{s}.NS",
        "name": info.get("longName") or info.get("shortName") or s,
        "price": tech["price"],
        "composite": v["score"], "label": v["label"], "tone": v["tone"],
        "technical": tech["score"], "fundamental": fund["score"],
        "f_score": fund["f_score"],
        "sector": info.get("sector"),
        "setup": (setup or {}).get("name"), "setup_key": (setup or {}).get("key"),
        "setup_fit": (setup or {}).get("fit"), "horizon": (setup or {}).get("horizon"),
        "avg_turnover_cr": round(cand["turnover"] / 1e7, 1),
    }


def run_scan(progress=None, names=None):
    if names is not None:
        symbols, source = list(names), f"Provided list ({len(names)} symbols)"
    else:
        symbols, source = fetch_nse_list()

    n2 = min(PHASE2_SIZE, len(symbols))
    state = {"done": 0, "total": len(symbols) + n2}

    cands, ill, nod = phase1(symbols, progress, state)
    deep = cands[:n2]
    state["total"] = len(symbols) + len(deep)      # exact now that we know

    rows, failed = [], []
    with ThreadPoolExecutor(max_workers=PHASE2_WORKERS) as pool:
        futures = {pool.submit(deep_score, c): c["symbol"] for c in deep}
        for fut in as_completed(futures):
            sym = futures[fut]
            try:
                r = fut.result()
                if r:
                    rows.append(r)
                else:
                    failed.append(sym)
            except Exception:
                failed.append(sym)
            state["done"] += 1
            if progress:
                progress(state["done"], state["total"], len(rows))

    rows.sort(key=lambda r: (r["composite"], r["fundamental"], r["technical"]), reverse=True)

    payload = {
        "scanned_at": dt.datetime.now().strftime("%d %b %Y, %H:%M"),
        "universe_source": source,
        "universe_size": len(symbols),
        "liquidity_floor": "avg daily traded value ≥ ₹2 crore (60 sessions)",
        "phase1_candidates": len(cands),
        "skipped_illiquid": ill,
        "skipped_no_data": nod,
        "phase2_analysed": len(deep),
        "scored": len(rows),
        "methodology": ("Phase 1: full universe bulk-scanned for liquidity and technicals. "
                        "Phase 2: top candidates receive full fundamental analysis "
                        "(Piotroski, adapted G-Score, ROCE, shareholding) and setup "
                        "classification. Composite = 50% technical + 50% fundamental. "
                        "Rankings reflect the scan date only."),
        "rankings": rows[:STORE_TOP],
        "skipped": failed,
    }
    try:
        with open(OUT_FILE, "w") as f:
            json.dump(payload, f, indent=2)
    except Exception:
        pass
    return payload


def main():
    started = time.time()
    def show(done, total, scored):
        print(f"\r  {done}/{total} processed · {scored} fully scored", end="", flush=True)
    p = run_scan(progress=show)
    print(f"\n\nSource: {p['universe_source']}")
    print(f"Done in {(time.time()-started)/60:.1f} min — universe {p['universe_size']}, "
          f"liquid candidates {p['phase1_candidates']}, deep-analysed {p['phase2_analysed']}, "
          f"fully scored {p['scored']}.")
    print(f"Excluded: {p['skipped_illiquid']} below the liquidity floor, "
          f"{p['skipped_no_data']} with insufficient price data.")
    print("\nTop 10 by composite:")
    for r in p["rankings"][:10]:
        print(f"  {r['composite']:>3}  {r['symbol']:<14} {r['setup'] or '—'}")


if __name__ == "__main__":
    main()
