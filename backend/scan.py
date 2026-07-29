"""
Altaha Screener — Universe Scanner

Can be run two ways:
  1. From the website's "Generate ranking" button (the API imports run_scan)
  2. On your own machine:  python scan.py

Scans concurrently but politely — a small worker pool with jitter, so the
data provider doesn't rate-limit us.
"""

import json
import os
import random
import time
import datetime as dt
from concurrent.futures import ThreadPoolExecutor, as_completed

import yfinance as yf

from engine import technical_score, fundamental_score, composite

# ---------------------------------------------------------------------------
# The universe. Edit freely — one NSE symbol per entry, no .NS suffix.
# Fewer, more liquid names = faster scans and more meaningful rankings.
# ---------------------------------------------------------------------------

UNIVERSE = """
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
RBLBANK KARURVYSYA CUB
TATAPOWER ADANIGREEN TORNTPOWER JSWENERGY NHPC SJVN
CONCOR GESHIP IRB KNRCON NBCC RVNL RAILTEL
PAGEIND KPRMILL TRIDENT WELSPUNLIV VBL RADICO UBL
BATAINDIA RELAXO METROBRAND CROMPTON WHIRLPOOL BLUESTARCO DIXON AMBER
CARBORUNIV GRINDWELL THERMAX AIAENG KEI POLYCAB FINCABLES SUPREMEIND
ASTRAL PRINCEPIPE CERA KAJARIACER
CDSL BSE MCX ANGELONE IEX CAMS KFINTECH
"""

OUT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "leaderboard.json")
TOP_N = 25
WORKERS = 3        # polite concurrency — raising this risks rate-limiting

METHODOLOGY = (
    "Composite = 50% technical (trend structure, Hull MA, RSI, MACD, ADX, Supertrend, "
    "volume trend, accumulation, OBV, 52-week position) + 50% fundamental (Piotroski "
    "F-Score, ROCE, leverage, growth, valuation, shareholding). Ranked on scan date only."
)


def universe():
    seen, out = set(), []
    for tok in UNIVERSE.split():
        s = tok.strip().upper()
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


def score_one(base: str):
    """Score one symbol. Returns dict, or None if it can't be scored."""
    time.sleep(random.uniform(0.15, 0.5))          # jitter, spreads the load
    sym = f"{base}.NS"
    t = yf.Ticker(sym)

    hist = t.history(period="1y", auto_adjust=True)
    if hist is None or len(hist) < 120:
        return None
    hist = hist.dropna(subset=["Close"])
    tech = technical_score(hist)

    try:
        fin, bs, cf = t.financials, t.balance_sheet, t.cashflow
        info = dict(t.info or {})
    except Exception:
        return None

    fund = fundamental_score(fin, bs, cf, info)
    if fund["score"] is None:
        return None                                # rank only evidenced names

    v = composite(tech, fund)
    return {
        "symbol": base, "ticker": sym,
        "name": info.get("longName") or info.get("shortName") or base,
        "price": tech["price"],
        "composite": v["score"], "label": v["label"], "tone": v["tone"],
        "technical": tech["score"], "fundamental": fund["score"],
        "f_score": fund["f_score"],
    }


def run_scan(progress=None, names=None):
    """
    Scan the universe. `progress(done, total, scored)` is called as work completes.
    Returns the payload dict (also written to leaderboard.json).
    """
    names = names or universe()
    total = len(names)
    rows, failed = [], []
    done = 0

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(score_one, n): n for n in names}
        for fut in as_completed(futures):
            base = futures[fut]
            try:
                r = fut.result()
                if r:
                    rows.append(r)
                else:
                    failed.append(base)
            except Exception:
                failed.append(base)
            done += 1
            if progress:
                try:
                    progress(done, total, len(rows))
                except Exception:
                    pass

    rows.sort(key=lambda r: (r["composite"], r["fundamental"], r["technical"]), reverse=True)

    payload = {
        "scanned_at": dt.datetime.now().strftime("%d %b %Y, %H:%M"),
        "universe_size": total,
        "scored": len(rows),
        "methodology": METHODOLOGY,
        "rankings": rows[:TOP_N],
        "skipped": failed,
    }
    try:
        with open(OUT_FILE, "w") as f:
            json.dump(payload, f, indent=2)
    except Exception:
        pass                                        # read-only disk is fine
    return payload


def main():
    names = universe()
    print(f"Altaha Screener — scanning {len(names)} stocks\n")
    started = time.time()

    def show(done, total, scored):
        print(f"\r  {done}/{total} processed · {scored} scored", end="", flush=True)

    payload = run_scan(progress=show)
    print(f"\n\nDone in {(time.time()-started)/60:.1f} min — "
          f"{payload['scored']} scored, {len(payload['skipped'])} skipped.")
    print("\nTop 5 by composite score:")
    for r in payload["rankings"][:5]:
        print(f"  {r['composite']:>3}  {r['symbol']:<14} {r['label']}")
    if payload["skipped"]:
        print("\nSkipped (likely renamed or delisted — prune from UNIVERSE):")
        print("  " + " ".join(payload["skipped"]))


if __name__ == "__main__":
    main()
