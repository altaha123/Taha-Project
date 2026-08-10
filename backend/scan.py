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
import gc

import yfinance as yf
from levels import compute_levels
from tradeplan import compact_plan

try:
    import dhan_source as dhan
except Exception:
    dhan = None

from engine import technical_score, fundamental_score, composite
import archetypes as A

OUT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "leaderboard.json")

# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------
CHUNK = 40                 # symbols per bulk price request
# Candidates that get full fundamental analysis. Overridable so a 512 MB
# Render instance can be told to go lighter: set SCAN_DEPTH=120 in the env.
PHASE2_SIZE = int(os.environ.get("SCAN_DEPTH", "200") or 200)
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

def prefilter_by_quote(symbols, state, progress):
    """
    Cheap first pass: one bulk quote call per ~900 symbols gives today's OHLC
    and volume for the whole universe. Names whose traded value is far below
    the floor are dropped before we spend a history request on them.

    Returns (survivors, dropped_count). Falls back to passing everything
    through when Dhan isn't available.
    """
    if dhan is None or not dhan.configured():
        return symbols, 0
    try:
        snap = dhan.bulk_quotes(symbols, mode="ohlc")
    except Exception:
        return symbols, 0
    if not snap:
        return symbols, 0

    keep, dropped = [], 0
    for s in symbols:
        row = snap.get(s)
        if not row:
            keep.append(s)          # unknown — let the full path decide
            continue
        px, vol = row.get("ltp") or row.get("close"), row.get("volume")
        if px and vol and (float(px) * float(vol)) < MIN_TURNOVER * 0.5:
            dropped += 1            # generous margin: one day isn't 60-day average
        else:
            keep.append(s)
    return keep, dropped


def phase1(symbols, progress, state):
    candidates, skipped_illiquid, skipped_nodata = [], 0, 0
    chunks = [symbols[i:i + CHUNK] for i in range(0, len(symbols), CHUNK)]

    for ci, chunk in enumerate(chunks):
        tickers = [f"{s}.NS" for s in chunk]
        use_dhan = dhan is not None and dhan.configured() and dhan.is_live().get("ok")
        data = None
        if not use_dhan:
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
                if use_dhan:
                    df = dhan.daily_ohlcv(s)
                    if df is not None:
                        df = df.dropna(subset=["Close"])
                else:
                    df = data[t].dropna(subset=["Close"]) if data is not None else None
                if df is None or len(df) < MIN_ROWS:
                    skipped_nodata += 1
                    continue
                turnover = float((df["Close"] * df["Volume"]).tail(60).mean())
                if turnover < MIN_TURNOVER:
                    skipped_illiquid += 1
                    continue
                # Retain only what ranking needs. The full payload (checks,
                # price_series, volume_series) is ~13 KB per stock; keeping it
                # for every candidate cost ~9 MB and is recomputed cheaply in
                # phase 2 for the few hundred that actually advance.
                tech = technical_score(df)
                candidates.append({"symbol": s, "score": tech["score"], "turnover": turnover})
                del tech
            except Exception:
                skipped_nodata += 1
            finally:
                df = None
        del data
        gc.collect()
        if progress:
            progress(state["done"], state["total"], len(candidates))

    candidates.sort(key=lambda c: c["score"], reverse=True)
    return candidates, skipped_illiquid, skipped_nodata


# ---------------------------------------------------------------------------
# Phase 2 — fundamentals + archetypes for the strongest candidates
# ---------------------------------------------------------------------------

def deep_score(cand):
    time.sleep(random.uniform(0.15, 0.5))
    s = cand["symbol"]
    t = yf.Ticker(f"{s}.NS")

    # Phase 1 deliberately discarded the technical payload to save memory;
    # recompute it here for the shortlist only.
    df = None
    if dhan is not None and dhan.configured():
        try:
            df = dhan.daily_ohlcv(s)
        except Exception:
            df = None
    if df is None:
        try:
            df = t.history(period="1y", auto_adjust=True)
        except Exception:
            return None
    if df is None or len(df) < 120:
        return None
    tech = technical_score(df.dropna(subset=["Close"]))
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
    try:
        clean = df.dropna(subset=["Close"])
        plan = compact_plan(clean, compute_levels(clean))
    except Exception:
        plan = None
    return {
        "plan": plan,
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


def _build_payload(rows, source, universe_all, prefiltered, n_candidates,
                   ill, nod, n_deep, failed, partial=False):
    rows = sorted(rows, key=lambda r: (r["composite"], r["fundamental"],
                                       r["technical"]), reverse=True)
    return {
        "scanned_at": dt.datetime.now().strftime("%d %b %Y, %H:%M")
                      + (" (partial — scan in progress)" if partial else ""),
        "partial": partial,
        "universe_source": source,
        "universe_size": universe_all,
        "prefiltered_by_quote": prefiltered,
        "liquidity_floor": "avg daily traded value ≥ ₹2 crore (60 sessions)",
        "phase1_candidates": n_candidates,
        "skipped_illiquid": ill,
        "skipped_no_data": nod,
        "phase2_analysed": n_deep,
        "scored": len(rows),
        "methodology": ("Phase 1: full universe bulk-scanned for liquidity and technicals. "
                        "Phase 2: top candidates receive full fundamental analysis "
                        "(Piotroski, adapted G-Score, ROCE, shareholding) and setup "
                        "classification. Composite = 50% technical + 50% fundamental. "
                        "Rankings reflect the scan date only."),
        "rankings": rows[:STORE_TOP],
        "skipped": failed,
    }


def _dump(payload):
    try:
        with open(OUT_FILE, "w") as f:
            json.dump(payload, f, indent=2)
    except Exception:
        pass


def run_scan(progress=None, names=None, checkpoint=None):
    """
    checkpoint: optional callable(payload) invoked with a partial payload
    every few phase-2 completions AND written to disk, so a process restart
    (free-tier memory limits are real) still leaves usable rankings behind
    instead of silently wiping the scan.
    """
    if names is not None:
        symbols, source = list(names), f"Provided list ({len(names)} symbols)"
    else:
        symbols, source = fetch_nse_list()

    n2 = min(PHASE2_SIZE, len(symbols))
    state = {"done": 0, "total": len(symbols) + n2}

    # Bulk-quote pre-filter: cuts the number of history requests substantially
    universe_all = len(symbols)
    symbols, prefiltered = prefilter_by_quote(symbols, state, progress)
    if prefiltered:
        state["done"] = prefiltered
        state["total"] = universe_all + n2

    cands, ill, nod = phase1(symbols, progress, state)
    ill += prefiltered
    deep = cands[:n2]
    state["total"] = len(symbols) + len(deep)      # exact now that we know

    n_candidates = len(cands)
    del cands
    gc.collect()

    rows, failed = [], []
    CP_EVERY = 15                       # checkpoint cadence (scored names)

    def _checkpoint(final=False):
        cp = _build_payload(list(rows), source, universe_all, prefiltered,
                            n_candidates, ill, nod, len(deep), list(failed),
                            partial=not final)
        _dump(cp)
        if checkpoint:
            try:
                checkpoint(cp)
            except Exception:
                pass
        return cp

    try:
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
                except MemoryError:
                    failed.append(sym)
                    gc.collect()
                except Exception:
                    failed.append(sym)
                state["done"] += 1
                if progress:
                    progress(state["done"], state["total"], len(rows))
                if rows and len(rows) % CP_EVERY == 0:
                    _checkpoint()
    except MemoryError:
        gc.collect()                    # salvage whatever scored so far

    return _checkpoint(final=True)


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
