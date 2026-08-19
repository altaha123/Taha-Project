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

# The point-in-time ledger. Optional import: if pit_store.py isn't present
# the scan still runs exactly as before, it just records nothing.
try:
    import pit_store
    pit_store.init_db()
except Exception:
    pit_store = None

OUT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "leaderboard.json")

# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------
CHUNK = 40                 # symbols per bulk price request
# Candidates that get full fundamental analysis. Overridable so a 512 MB
# Render instance can be told to go lighter: set SCAN_DEPTH=120 in the env.
PHASE2_SIZE = int(os.environ.get("SCAN_DEPTH", "200") or 200)

# CONTROL COHORT — the most important line in this file for research purposes.
#
# Phase 2 used to analyse only the top names by technical score. That meant
# fundamentals were ONLY ever observed for stocks that already had strong
# price momentum. The recorded data was therefore conditioned on momentum,
# and no honest question like "does high ROCE predict returns?" could ever
# be answered from it — there was no comparison group.
#
# This reserves a slice of Phase 2 for names drawn at RANDOM from everything
# that cleared the liquidity floor, stratified so no sector or size band is
# systematically unobserved. Those names are the control group. They cost
# about 25% more scan time and they are what makes every future factor
# statistic meaningful rather than decorative.
CONTROL_PCT = float(os.environ.get("SCAN_CONTROL_PCT", "0.25") or 0.25)
PHASE2_WORKERS = 3         # polite concurrency for per-stock fundamentals
MIN_ROWS = 120             # minimum trading days of history
MIN_TURNOVER = 2e7         # legacy constant, retained for the payload label
# Only genuinely untradeable names are removed. Everything above this floor is
# scored and shown with a liquidity tier attached (see ideas.liquidity_tier).
HARD_FLOOR = float(os.environ.get("SCAN_HARD_FLOOR", "5e6") or 5e6)   # ₹50 lakh
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
        # mode="quote", not "ohlc". /marketfeed/ohlc returns no volume field,
        # so the traded-value test below was always false and this prefilter
        # silently dropped nothing while still costing a full round trip.
        snap = dhan.bulk_quotes(symbols, mode="quote")
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
        if px and vol and (float(px) * float(vol)) < HARD_FLOOR * 0.5:
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
                # Previously anything under 2 crore was deleted here, which hid
                # roughly half the real companies on the exchange. Now only
                # genuinely untradeable names are dropped; everything else is
                # carried through and LABELLED by tier in ideas.py, so the
                # reader sees the name and the warning together.
                if turnover < HARD_FLOOR:
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

def deep_score(cand, selection="ranked"):
    """
    Full analysis of one candidate.

    `selection` records WHY this stock reached Phase 2 — "ranked" (it scored
    highly on technicals) or "control" (it was drawn at random). Research done
    later must be able to tell these apart, or it will mistake the sampling
    design for a finding.
    """
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
        fin = bs = cf = None
        info = {}
    try:
        fund = fundamental_score(fin, bs, cf, info)
    except Exception:
        fund = {"score": None, "f_score": None}

    # BUGFIX (silent deletion): this used to be
    #     if fund["score"] is None: return None
    # A stock whose statements failed to download simply vanished — no row, no
    # reason, no record. That quietly biased the whole system toward large,
    # well-covered companies, because those are the ones Yahoo has data for.
    #
    # Now the row survives with fundamental = None and an explicit quality
    # status. It is excluded from RANKING (you cannot rank on a score that
    # doesn't exist) but it IS recorded, so the gap is visible and countable
    # instead of invisible.
    fund_missing = fund.get("score") is None
    quality = "MISSING" if fund_missing else "VALID"

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
        "technical": tech["score"], "fundamental": fund.get("score"),
        "f_score": fund.get("f_score"),
        "sector": info.get("sector"),
        "setup": (setup or {}).get("name"), "setup_key": (setup or {}).get("key"),
        "setup_fit": (setup or {}).get("fit"), "horizon": (setup or {}).get("horizon"),
        "avg_turnover_cr": round(cand["turnover"] / 1e7, 1),
        # --- research metadata: never shown in the UI, essential for analysis
        "selection": selection,              # "ranked" or "control"
        "fundamental_quality": quality,      # "VALID" or "MISSING"
        "rankable": not fund_missing,        # excluded from the leaderboard if False
    }


def pick_phase2_cohort(candidates, n_total, control_pct=CONTROL_PCT):
    """
    Choose which names get expensive Phase-2 analysis.

    Returns (cohort, n_ranked, n_control) where cohort is a list of
    (candidate, selection_label) pairs.

    Two groups:
      RANKED  — the strongest names by technical score. These are the ideas.
      CONTROL — drawn at random from everyone else that cleared liquidity,
                stratified across turnover deciles so small, mid and large
                names are all represented. These are the comparison group.

    Without the control group, every "this factor predicts returns" claim the
    system ever makes is measured only on stocks that already had momentum,
    and there is no way to detect that from inside the numbers.
    """
    if not candidates:
        return [], 0, 0

    n_total = min(n_total, len(candidates))
    n_control = int(n_total * control_pct)
    n_ranked = n_total - n_control

    ranked = candidates[:n_ranked]
    ranked_syms = {c["symbol"] for c in ranked}
    pool = [c for c in candidates if c["symbol"] not in ranked_syms]

    control = []
    if n_control and pool:
        # Stratify by turnover so the control group isn't accidentally all
        # micro-caps (which is what an unstratified random draw would give,
        # because most of the universe is small).
        by_turnover = sorted(pool, key=lambda c: c["turnover"])
        n_strata = min(10, len(by_turnover))
        stratum_size = max(1, len(by_turnover) // n_strata)
        per_stratum = max(1, n_control // n_strata)

        rng = random.Random()          # unseeded: a fresh draw every scan
        for i in range(n_strata):
            lo = i * stratum_size
            hi = len(by_turnover) if i == n_strata - 1 else (i + 1) * stratum_size
            stratum = by_turnover[lo:hi]
            if not stratum:
                continue
            take = min(per_stratum, len(stratum), n_control - len(control))
            if take <= 0:
                break
            control.extend(rng.sample(stratum, take))

        # Top up from anything left if rounding left us short.
        if len(control) < n_control:
            chosen = {c["symbol"] for c in control}
            rest = [c for c in pool if c["symbol"] not in chosen]
            if rest:
                rng.shuffle(rest)
                control.extend(rest[:n_control - len(control)])

    cohort = ([(c, "ranked") for c in ranked] +
              [(c, "control") for c in control])
    return cohort, len(ranked), len(control)


def _record_to_pit(rows, universe_all, n_candidates, ill, nod, regime=None):
    """
    Write an immutable dated snapshot of this scan to the point-in-time store.

    This is the scan's real long-term output. The leaderboard is what you look
    at today; this is what lets you ask, in eighteen months, "what did Altaha
    actually know on 19 August 2026, and was it right?"

    Deliberately wrapped in a broad try/except: recording must never be able
    to break a scan that otherwise succeeded.
    """
    if pit_store is None or not rows:
        return
    try:
        run_id = pit_store.start_run(
            universe_size=universe_all,
            regime=regime,
            notes=(f"candidates={n_candidates} illiquid={ill} nodata={nod} "
                   f"scored={len(rows)}"),
        )
        records = {}
        for r in rows:
            records[r["symbol"]] = {
                "composite": r.get("composite"),
                "technical": r.get("technical"),
                "fundamental": r.get("fundamental"),
                "f_score": r.get("f_score"),
                "price": r.get("price"),
                "avg_turnover_cr": r.get("avg_turnover_cr"),
                "sector": r.get("sector"),
                "setup_key": r.get("setup_key"),
                "setup_fit": r.get("setup_fit"),
                "horizon": r.get("horizon"),
                "selection": r.get("selection"),
                "fundamental_quality": r.get("fundamental_quality"),
                "label": r.get("label"),
            }
        pit_store.snapshot_many(records, run_id=run_id)
    except Exception:
        pass


def _build_payload(rows, source, universe_all, prefiltered, n_candidates,
                   ill, nod, n_deep, failed, partial=False):
    # Rows whose fundamentals failed to load are recorded but must not be
    # ranked — a composite built from technicals alone is not comparable with
    # one built from both. They stay visible in the counts below.
    all_rows = list(rows)
    rankable = [r for r in all_rows if r.get("rankable", True)]
    n_missing_fund = len(all_rows) - len(rankable)
    n_control = sum(1 for r in all_rows if r.get("selection") == "control")

    rows = sorted(rankable, key=lambda r: (r["composite"] or 0,
                                           r["fundamental"] or 0,
                                           r["technical"] or 0), reverse=True)
    return {
        "scanned_at": dt.datetime.now().strftime("%d %b %Y, %H:%M")
                      + (" (partial — scan in progress)" if partial else ""),
        "partial": partial,
        "universe_source": source,
        "universe_size": universe_all,
        "prefiltered_by_quote": prefiltered,
        "liquidity_floor": f"avg daily traded value ≥ ₹{HARD_FLOOR/1e7:.2f} crore (60 sessions); everything above is scored and tiered, not deleted",
        "phase1_candidates": n_candidates,
        "skipped_illiquid": ill,
        "skipped_no_data": nod,
        "phase2_analysed": n_deep,
        "scored": len(rows),
        "control_cohort": n_control,
        "missing_fundamentals": n_missing_fund,
        "methodology": ("Phase 1: full universe bulk-scanned for liquidity and technicals. "
                        "Phase 2: top candidates receive full fundamental analysis "
                        "(Piotroski, adapted G-Score, ROCE, shareholding) and setup "
                        "classification. Composite = 50% technical + 50% fundamental. "
                        "Rankings reflect the scan date only."),
        "rankings": rows[:STORE_TOP],
        "skipped": failed,
    }


def _dump(payload):
    """
    Atomic write — same reasoning as tracker._save().

    A scan checkpoints roughly every 15 stocks. With a plain open(..., "w")
    every one of those was a window in which a crash left leaderboard.json
    truncated and unparseable, destroying a scan that had otherwise finished.
    """
    tmp = f"{OUT_FILE}.{os.getpid()}.tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(payload, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, OUT_FILE)
    except Exception:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
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

    # Was: deep = cands[:n2] — top N by technical score only.
    # Now: ranked names PLUS a stratified random control group, so the data
    # this scan records can actually be analysed later. See pick_phase2_cohort.
    cohort, n_ranked, n_control_planned = pick_phase2_cohort(cands, n2)
    deep = cohort
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
        if final:
            # Immutable record of what this scan knew, written once at the end.
            _record_to_pit(list(rows), universe_all, n_candidates, ill, nod)
        if checkpoint:
            try:
                checkpoint(cp)
            except Exception:
                pass
        return cp

    try:
        with ThreadPoolExecutor(max_workers=PHASE2_WORKERS) as pool:
            futures = {pool.submit(deep_score, c, sel): c["symbol"]
                       for c, sel in deep}
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
    print(f"Research: {p.get('control_cohort', 0)} control-cohort names recorded, "
          f"{p.get('missing_fundamentals', 0)} recorded with fundamentals missing.")
    print("\nTop 10 by composite:")
    for r in p["rankings"][:10]:
        print(f"  {r['composite']:>3}  {r['symbol']:<14} {r['setup'] or '—'}")


if __name__ == "__main__":
    main()


# ---------------------------------------------------------------------------
# Company names — for the search typeahead
# ---------------------------------------------------------------------------

_names_cache = {"at": 0.0, "rows": []}


def universe_with_names():
    """
    [{"s": "RELIANCE", "n": "Reliance Industries Limited"}, ...]

    fetch_nse_list() already downloads this CSV and throws the company-name
    column away. Keeping it is what lets someone search "Bajaj Finance"
    instead of having to already know the symbol is BAJFINANCE.

    Same source as the scan, deliberately: the typeahead must never be able to
    offer a symbol the engine cannot then score. Cached for a day, because the
    equity list changes on listings and delistings, not on ticks.
    """
    if _names_cache["rows"] and (time.time() - _names_cache["at"]) < 86400:
        return _names_cache["rows"]

    rows = []
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
            name_col = next((c for c in df.columns if "NAME" in c.upper()), None)

            seen = set()
            for _, row in df.iterrows():
                sym = str(row["SYMBOL"]).strip().upper()
                if not sym or sym in seen:
                    continue
                seen.add(sym)
                nm = str(row[name_col]).strip() if name_col else sym
                if nm.lower() in ("nan", "none", ""):
                    nm = sym
                rows.append({"s": sym, "n": nm})

            if len(rows) > 500:
                break
        except Exception:
            continue

    if not rows:
        # Same fallback the scan uses, so the two never disagree about what
        # the universe is — just without company names.
        rows = [{"s": x, "n": x} for x in sorted({y for y in FALLBACK.split() if y})]

    rows.sort(key=lambda r: r["s"])
    _names_cache["at"] = time.time()
    _names_cache["rows"] = rows
    return rows
