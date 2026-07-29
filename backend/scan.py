"""
Altaha Screener — Universe Scanner

Scores every stock in the universe below and writes leaderboard.json,
which the API then serves instantly. Run it on your own machine:

    cd backend
    python scan.py

Takes roughly 5-12 minutes for ~180 stocks (deliberately throttled so the
data provider doesn't rate-limit you). When it finishes, commit the new
leaderboard.json to GitHub — Render picks it up on the next deploy.

Re-run it whenever you want fresh rankings. Daily after market close is ideal.
"""

import json
import os
import time
import datetime as dt

import yfinance as yf

from engine import technical_score, fundamental_score, composite

# ---------------------------------------------------------------------------
# The universe. Edit freely — one NSE symbol per entry, no .NS suffix.
# Index constituents change; treat this as a seed and prune what's stale.
# A smaller, liquid universe scans faster and ranks more meaningfully.
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
TOP_N = 25          # how many to store (frontend shows the top 5)
PAUSE = 1.1         # seconds between stocks — keeps the provider happy
MIN_FUND_ROWS = 1   # require at least some fundamental data to rank


def universe():
    seen, out = set(), []
    for tok in UNIVERSE.split():
        s = tok.strip().upper()
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


def score_one(base: str):
    """Score a single symbol. Returns a dict, or None if it can't be scored."""
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
        return None                      # rank only fully-evidenced names

    v = composite(tech, fund)
    return {
        "symbol": base,
        "ticker": sym,
        "name": info.get("longName") or info.get("shortName") or base,
        "price": tech["price"],
        "composite": v["score"],
        "label": v["label"],
        "tone": v["tone"],
        "technical": tech["score"],
        "fundamental": fund["score"],
        "f_score": fund["f_score"],
    }


def main():
    names = universe()
    print(f"Altaha Screener — scanning {len(names)} stocks")
    print("This is deliberately paced so the data provider doesn't block you.\n")

    rows, failed = [], []
    started = time.time()

    for i, base in enumerate(names, 1):
        try:
            r = score_one(base)
            if r:
                rows.append(r)
                print(f"[{i:>3}/{len(names)}] {base:<14} {r['composite']:>3}  "
                      f"(T {r['technical']:>3} / F {r['fundamental']:>3})")
            else:
                failed.append(base)
                print(f"[{i:>3}/{len(names)}] {base:<14}  — skipped (insufficient data)")
        except Exception as e:
            failed.append(base)
            print(f"[{i:>3}/{len(names)}] {base:<14}  — error: {str(e)[:60]}")
        time.sleep(PAUSE)

    rows.sort(key=lambda r: (r["composite"], r["fundamental"], r["technical"]), reverse=True)

    payload = {
        "scanned_at": dt.datetime.now().strftime("%d %b %Y, %H:%M"),
        "universe_size": len(names),
        "scored": len(rows),
        "methodology": ("Composite = 50% technical (trend structure, Hull MA, RSI, MACD, ADX, "
                        "Supertrend, volume trend, accumulation, OBV, 52-week position) + "
                        "50% fundamental (Piotroski F-Score, ROCE, leverage, growth, valuation, "
                        "shareholding). Ranked on the scan date only."),
        "rankings": rows[:TOP_N],
    }

    with open(OUT_FILE, "w") as f:
        json.dump(payload, f, indent=2)

    mins = (time.time() - started) / 60
    print(f"\nDone in {mins:.1f} min — {len(rows)} scored, {len(failed)} skipped.")
    print(f"Written to {OUT_FILE}")
    if rows:
        print("\nTop 5 by composite score:")
        for r in rows[:5]:
            print(f"  {r['composite']:>3}  {r['symbol']:<14} {r['label']}")
    if failed:
        print(f"\nSkipped symbols (likely renamed or delisted — prune them from UNIVERSE):")
        print("  " + " ".join(failed))
    print("\nNow commit leaderboard.json to GitHub so your live site serves it.")


if __name__ == "__main__":
    main()
