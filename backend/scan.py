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
try:
    from ythreads import reap as _reap
except Exception:                       # standalone use without the API package
    def _reap():
        return 0

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
import profiles as PR
import multifactor
import xbrl

# The point-in-time ledger. Optional import: if pit_store.py isn't present
# the scan still runs exactly as before, it just records nothing.
try:
    import pit_store
    pit_store.init_db()
except Exception:
    pit_store = None

# Where the finished ranking is cached.
#
# BUGFIX: this was written next to the code. On Render that directory is
# replaced wholesale by every deploy, so each deploy silently destroyed the
# universe scan — the Ideas tab came back empty and the only clue was a
# "the engine restarted mid-scan" note that had nothing to do with it. The
# tracker had already solved this with DATA_DIR and a mounted disk; the scan
# cache simply never used it. It does now, so a deploy no longer costs a
# multi-minute scan. With DATA_DIR unset the path is unchanged.
_HERE = os.path.dirname(os.path.abspath(__file__))
_DATA_DIR = os.environ.get("DATA_DIR", "").strip() or _HERE
try:
    os.makedirs(_DATA_DIR, exist_ok=True)
except Exception:
    _DATA_DIR = _HERE

OUT_FILE = os.path.join(_DATA_DIR, "leaderboard.json")

# One-time migration: a scan cached by an older build sits in the code
# directory. Move it onto the disk rather than making the user re-run it.
_LEGACY_OUT = os.path.join(_HERE, "leaderboard.json")
if _DATA_DIR != _HERE and os.path.exists(_LEGACY_OUT) and not os.path.exists(OUT_FILE):
    try:
        os.replace(_LEGACY_OUT, OUT_FILE)
    except Exception:
        pass

# Whether the cache is actually being written. Filled by _dump() and read by
# persistence_health(), which the API surfaces so a disk problem is visible
# from outside the box instead of only as results that quietly go stale.
_persist = {
    "path": OUT_FILE,
    "data_dir_from_env": bool(os.environ.get("DATA_DIR", "").strip()),
    "last_ok": None,
    "last_error": None,
    "last_error_at": None,
    "consecutive_failures": 0,
    "bytes_written": None,
}


# A scan that dies leaves no evidence it ever ran.
#
# _state in main.py is memory only, and the checkpoint that writes results to
# disk is not reached until the depth pass. Phase 1 — the NSE list, the quote
# pre-filter and the bulk price download over ~2,300 symbols — is minutes of
# work that writes nothing. So a restart during it (a Render deploy is one)
# loses the scan AND every trace that it happened: the process comes back,
# reloads the last completed scan, and reports "done" with a date from days
# ago. There is then no way to answer the only question that matters, which is
# whether a run was even attempted.
#
# This is a breadcrumb, not results: a few bytes rewritten at each phase
# boundary so the answer survives the restart.
_ATTEMPT_FILE = os.path.join(_DATA_DIR, "scan_attempt.json")


def _note_attempt(**fields):
    """Record where the current scan has got to. Never raises."""
    try:
        rec = last_attempt() or {}
        rec.update(fields)
        tmp = f"{_ATTEMPT_FILE}.{os.getpid()}.tmp"
        with open(tmp, "w") as f:
            json.dump(rec, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, _ATTEMPT_FILE)
    except Exception:
        pass


def last_attempt():
    """The last recorded scan attempt, or None. Never raises."""
    try:
        with open(_ATTEMPT_FILE) as f:
            return json.load(f)
    except Exception:
        return None


def persistence_health():
    """
    Can a finished scan survive a restart? Never raises.

    A scan is minutes of work that exists in one process's memory until it
    reaches this file, so "the write is failing" and "the disk is nearly
    full" are the two facts worth having before the results disappear.
    """
    out = dict(_persist)
    d = os.path.dirname(OUT_FILE) or "."
    out["dir_exists"] = os.path.isdir(d)
    try:
        out["file_exists"] = os.path.exists(OUT_FILE)
        out["file_mtime"] = os.path.getmtime(OUT_FILE) if out["file_exists"] else None
        out["file_age_hours"] = round((time.time() - out["file_mtime"]) / 3600, 1) \
            if out["file_mtime"] else None
    except Exception:
        out["file_exists"] = None
    try:
        st = os.statvfs(d)
        out["disk_free_mb"] = round(st.f_bavail * st.f_frsize / 1e6, 1)
        out["disk_total_mb"] = round(st.f_blocks * st.f_frsize / 1e6, 1)
    except Exception:
        out["disk_free_mb"] = out["disk_total_mb"] = None
    att = last_attempt()
    if att:
        out["last_attempt"] = att
        # Started but never finished means the process died mid-scan. That is
        # a different fault from a write that failed, and it is the one a
        # deploy causes.
        if att.get("started_at") and not att.get("finished_at"):
            out["interrupted_scan"] = (
                "A scan reached the '" + str(att.get("phase")) + "' phase at " +
                str(att.get("started_at")) + " and never finished — the process "
                "restarted while it was running. Nothing was written, so the "
                "cached scan below is older than that attempt.")
    out["healthy"] = bool(out.get("dir_exists")) and _persist["consecutive_failures"] == 0
    if not out["healthy"]:
        out["warning"] = (
            "The universe scan is not reaching disk. Results will look correct "
            "until this process restarts, then revert to the last write that "
            "succeeded. Check free space on the mounted disk and the "
            "permissions on " + str(d) + "."
        )
    return out


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

# ---------------------------------------------------------------------------
# Memory watchdog
#
# The scan is the only thing in this process that needs hundreds of MB, and on
# a 512 MB instance it is what turns a healthy process into a killed one. Being
# killed is the worst possible ending: the instance goes down, every other tab
# on the site starts returning nothing, and the browser can only report that
# the engine is unreachable — which reads as "the server is asleep" rather than
# "the scan you just started took the site with it". The user then presses the
# button again, and it happens again.
#
# So the scan now watches its own resident size and stops itself while it can
# still write a checkpoint. A scan that ends early with 140 names scored and
# says so is worth more than one that is 80% done and dies.
#
# Two settings, both overridable on Render:
#   MEM_LIMIT_MB             what the instance is allowed to hold (Render plan)
#   SCAN_ABORT_HEADROOM_MB   stop when less than this much is left
MEM_LIMIT_MB = int(os.environ.get("MEM_LIMIT_MB", "512") or 512)
SCAN_ABORT_HEADROOM_MB = int(os.environ.get("SCAN_ABORT_HEADROOM_MB", "45") or 45)


def rss_mb():
    """Resident memory in MB, or None where /proc is not available."""
    try:
        with open("/proc/self/status") as fh:
            for line in fh:
                if line.startswith("VmRSS:"):
                    return round(int(line.split()[1]) / 1024, 1)
    except Exception:
        pass
    return None


def trim():
    """
    Collect, then hand the freed arenas back to the OS.

    gc.collect() on its own frees Python objects but can leave the memory in
    glibc's arenas, so RSS — the number Render actually kills on — need not
    move at all. malloc_trim is the half that was missing here.

    Measured at idle it returns very little (the /health/memory notes in
    main.py record 0.2 MB, honestly), which is why it is not sold as the fix.
    Its moment is this one: immediately after a chunk's price frames are
    dropped, when there is something large and recently freed to hand back.
    It costs microseconds either way.
    """
    gc.collect()
    try:
        import ctypes
        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except Exception:
        pass
    return rss_mb()


def headroom_mb():
    """MB left before the instance limit, or None when RSS is unreadable."""
    rss = rss_mb()
    return None if rss is None else round(MEM_LIMIT_MB - rss, 1)


def _should_stop():
    """
    True when the process is close enough to the limit that continuing means
    being killed. Trims first: the point is to stop on memory genuinely in
    use, not on arenas nobody has handed back yet.
    """
    head = headroom_mb()
    if head is None or head >= SCAN_ABORT_HEADROOM_MB:
        return False
    trim()
    head = headroom_mb()
    return head is not None and head < SCAN_ABORT_HEADROOM_MB


def plan_footprint():
    """
    (chunk, workers) sized to the room actually available right now.

    A scan is not one fixed weight. Phase 1 holds one bulk price frame of
    `chunk` tickers at a time and phase 2 holds one yfinance session per
    worker, so both are dials, and on a cramped instance turning them down is
    the difference between a scan that gets somewhere before the watchdog
    stops it and one that does not. A roomy instance keeps the fast settings.
    """
    head = headroom_mb()
    if head is None or head >= 150:
        return CHUNK, PHASE2_WORKERS
    if head >= 90:
        return max(20, CHUNK // 2), PHASE2_WORKERS
    return max(10, CHUNK // 4), 1

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


def phase1(symbols, progress, state, chunk_size=None):
    """
    Returns (candidates, skipped_illiquid, skipped_nodata, stopped).

    `stopped` is None on a full pass, or a sentence explaining why the breadth
    pass ended early. It ends early only to avoid being killed — see the
    memory watchdog above — and everything scored up to that point is kept.
    """
    candidates, skipped_illiquid, skipped_nodata = [], 0, 0
    stopped = None
    size = int(chunk_size or CHUNK)
    chunks = [symbols[i:i + size] for i in range(0, len(symbols), size)]

    for ci, chunk in enumerate(chunks):
        if _should_stop():
            done_syms = ci * size
            # The unreached symbols advance the progress bar — a scan that ends
            # is not a scan that hangs — but they are NOT counted as skipped for
            # missing data. They were never looked at, and recording them as
            # "insufficient price data" would put a false reason in the payload
            # for names that may be perfectly fine. The counts under-run the
            # universe size instead, and stopped_reason says why.
            state["done"] += max(0, len(symbols) - done_syms)
            stopped = (f"Breadth pass stopped after {done_syms} of {len(symbols)} "
                       f"symbols: the instance was within {SCAN_ABORT_HEADROOM_MB} MB "
                       f"of its {MEM_LIMIT_MB} MB limit. Depth analysis continues on "
                       "what cleared so far.")
            break
        tickers = [f"{s}.NS" for s in chunk]
        use_dhan = dhan is not None and dhan.configured() and dhan.is_live().get("ok")
        data = None
        if not use_dhan:
            try:
                # threads=False deliberately. threads=True does not use a
                # pool: yfinance starts one OS thread per ticker (see
                # ythreads.py), so this line alone created CHUNK threads per
                # chunk and ~1,200 over a universe pass. On a 512 MB box with
                # ~45 MB of headroom that is what was killing the scan
                # part-way through. Sequential is slower per chunk and is the
                # difference between a scan that finishes and one that does not.
                data = yf.download(" ".join(tickers), period="1y", interval="1d",
                                   group_by="ticker", auto_adjust=True,
                                   threads=False, progress=False)
            except Exception:
                data = None
        time.sleep(0.6 + random.random() * 0.6)
        _reap()          # multitasking never drops finished tasks; see ythreads

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
        # Trim, not just collect: the chunk's price frames are the largest
        # thing this loop allocates and gc alone leaves them resident.
        trim()
        if progress:
            progress(state["done"], state["total"], len(candidates))

    candidates.sort(key=lambda c: c["score"], reverse=True)
    return candidates, skipped_illiquid, skipped_nodata, stopped


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
            df = t.history(period="2y", auto_adjust=True)
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
    # The orthogonal factor block, and the technical score's own checks broken
    # out individually. Neither is shown in the UI; both are banked, because
    # the Factor Lab cannot measure what was never recorded and every day this
    # is missing is a day of evidence that cannot be recovered later.
    extra, quality_meta = {}, {}
    try:
        quarters = xbrl.scoring_statements(s)
    except Exception:
        quarters = []
    try:
        import factors as _factors
        extra = _factors.compute(df, quarters=quarters, price=tech.get("price")) or {}
        quality_meta = _factors.data_quality(quarters)
    except Exception:
        extra = {}
    checks = {}
    try:
        for c in (tech.get("checks") or []):
            if c.get("max"):
                checks["chk_" + str(c["name"]).lower().replace(" ", "_")[:40]] = c.get("points")
    except Exception:
        checks = {}

    return {
        "plan": plan,
        "factors": extra,
        "data_quality": quality_meta,
        "industry": info.get("industry"),
        "market_cap": info.get("marketCap"),
        "trailing_eps": info.get("trailingEps"),
        "tech_checks": checks,
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
                "legacy_composite": r.get("legacy_composite"),
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
            # Orthogonal factors and the individual technical checks. Recorded
            # flat alongside everything else — factor_snapshots is long-format
            # precisely so new factors never need a migration.
            v4 = r.get("altaha_score_v4")
            if v4:
                records[r["symbol"]]["v4_audit"] = v4
                records[r["symbol"]]["methodology_version"] = "v4"
                for hz in PR.V4_WEIGHTS:
                    for metric in ("raw_score", "final_score", "confidence"):
                        records[r["symbol"]][f"v4_{hz}_{metric}"] = v4[hz][metric]
                    for family, value in v4[hz]["pillars"].items():
                        records[r["symbol"]][f"v4_{hz}_family_{family}"] = value
                for entry in v4["factor_ledger"]:
                    if entry["value"] is not None and entry["applicable"]:
                        records[r["symbol"]]["v4_raw_" + entry["factor"]] = entry["value"]
            for src in (r.get("factors") or {}, r.get("tech_checks") or {}):
                for k, v in src.items():
                    if v is not None:
                        records[r["symbol"]][k] = v
        pit_store.snapshot_many(records, run_id=run_id)
    except Exception:
        pass


def _build_payload(rows, source, universe_all, prefiltered, n_candidates,
                   ill, nod, n_deep, failed, partial=False, stopped=None):
    all_rows = list(rows)
    n_missing_fund = sum(r.get("fundamental") is None for r in all_rows)
    n_control = sum(r.get("selection") == "control" for r in all_rows)
    ranked = multifactor.rank(all_rows, "position")
    scored = ranked.get("rows", [])
    for r in scored:
        r.setdefault("legacy_composite", r.get("composite"))
        r["composite"] = r["position_score"]
        p = multifactor.presentation(r["altaha_score_v4"])
        r["label"], r["tone"] = p["label"], p["tone"]
        r["rankable"] = True
    rows = sorted(scored, key=lambda r: (-r["position_score"], r["symbol"]))
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
        "methodology": ("Altaha Score v4: peer percentiles, eight pillars, business-model priors, "
                        "confidence shrinkage. Analysed cohort includes technical candidates and random controls; "
                        "it is not the complete NSE universe."),
        "methodology_version": "v4",
        "factor_universe": rows,
        "rankings": rows[:STORE_TOP],
        "skipped": failed,
        # Set when the scan ended itself rather than finishing. A short list
        # then means the scan stopped early, not that the market had nothing
        # to offer, and the reader is told which.
        "stopped_early": bool(stopped),
        "stopped_reason": stopped,
    }


def _jsonable(obj):
    """
    Last resort for a value json cannot encode. Passed as json.dump(default=).

    Every HTTP endpoint in this project runs its response through
    main.to_native() first, because a single numpy scalar anywhere in a
    payload — one sector figure, one corroboration count — fails encoding.
    _dump() never had that protection: it called json.dump() directly, inside
    a bare `except Exception: pass`. So a payload holding one numpy value was
    served to the browser perfectly well (the endpoint converts on the way
    out) while every attempt to write it to disk raised TypeError and was
    swallowed. The scan looked like it worked and vanished on the next
    restart, which is exactly the reported symptom.

    Using default= rather than converting the whole payload keeps the common
    path untouched: json only calls this for values it has already failed on.
    """
    # Arrays and sets first: .item() raises on anything holding more than one
    # value, and str() would then "succeed" by writing the repr of an array
    # into the file — a silent corruption worse than the failure it replaces.
    if isinstance(obj, (set, frozenset)):
        return sorted(obj, key=str)
    tolist = getattr(obj, "tolist", None)
    if callable(tolist):
        try:
            return tolist()
        except Exception:
            pass
    for cast in (float, int, str):
        try:
            v = cast(obj)
        except Exception:
            continue
        if isinstance(v, float) and (v != v or v in (float("inf"), float("-inf"))):
            return None
        return v
    return None


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
            json.dump(payload, f, indent=2, default=_jsonable)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, OUT_FILE)
        _persist.update(last_ok=time.time(), last_error=None, consecutive_failures=0,
                        bytes_written=os.path.getsize(OUT_FILE))
    except Exception as e:
        # This used to be `except Exception: pass`, and that silence is the
        # whole reason a scan could appear to work and then vanish.
        #
        # The failure mode: the in-memory payload and the disk copy are
        # written by the same call, so a scan whose checkpoints all failed
        # still served fresh ideas for as long as the process lived. When
        # Render restarted it, _load_from_disk() restored the last write that
        # HAD succeeded — a scan from days earlier — and reported it as
        # "done". Nothing anywhere said a write had ever failed. Observed in
        # production on 9 Sep 2026: the site served a 31 Aug payload with no
        # record of the nine days of scans in between.
        #
        # pit_store.py already learned this lesson and states it plainly: a
        # store that silently records nothing is worse than one that is
        # absent, because the absence is at least visible.
        _persist.update(last_error=f"{type(e).__name__}: {e}"[:300],
                        last_error_at=time.time(),
                        consecutive_failures=_persist["consecutive_failures"] + 1)
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
    _note_attempt(started_at=dt.datetime.now().isoformat(timespec="seconds"),
                  finished_at=None, phase="fetching the NSE universe list",
                  pid=os.getpid(), scored=0)
    if names is not None:
        symbols, source = list(names), f"Provided list ({len(names)} symbols)"
    else:
        symbols, source = fetch_nse_list()
    _note_attempt(phase="phase 1 — bulk prices and technical scores",
                  universe=len(symbols))

    n2 = min(PHASE2_SIZE, len(symbols))
    state = {"done": 0, "total": len(symbols) + n2}

    # Bulk-quote pre-filter: cuts the number of history requests substantially
    universe_all = len(symbols)
    symbols, prefiltered = prefilter_by_quote(symbols, state, progress)
    if prefiltered:
        state["done"] = prefiltered
        state["total"] = universe_all + n2

    # Size the scan to the room there is, once, up front. Reading it here
    # rather than at import time matters: the process is a different size at
    # 09:00 with the intraday scanner armed than it is at boot.
    chunk_size, workers = plan_footprint()

    cands, ill, nod, stopped = phase1(symbols, progress, state, chunk_size)
    ill += prefiltered
    _note_attempt(phase="phase 2 — fundamentals and archetypes",
                  candidates=len(cands))

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
                            partial=not final, stopped=stopped)
        _dump(cp)
        _note_attempt(scored=len(rows),
                      **({"finished_at": dt.datetime.now().isoformat(timespec="seconds"),
                          "phase": "complete"} if final else {}))
        if final and not stopped:
            # Immutable record of what this scan knew, written once at the end.
            _record_to_pit(cp.get("factor_universe") or [], universe_all, n_candidates, ill, nod)
        if checkpoint:
            try:
                checkpoint(cp)
            except Exception:
                pass
        return cp

    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(deep_score, c, sel): c["symbol"]
                       for c, sel in deep}
            pending = set(futures)
            for fut in as_completed(futures):
                pending.discard(fut)
                sym = futures[fut]
                try:
                    r = fut.result()
                    if r:
                        rows.append(r)
                    else:
                        failed.append(sym)
                except MemoryError:
                    failed.append(sym)
                    trim()
                except Exception:
                    failed.append(sym)
                state["done"] += 1
                if progress:
                    progress(state["done"], state["total"], len(rows))
                if rows and len(rows) % CP_EVERY == 0:
                    _checkpoint()
                # Stop while a checkpoint can still be written. Being killed
                # here loses nothing scored (checkpoints are on disk) but it
                # does take the whole instance down, and the site is then
                # unreachable for as long as Render takes to restart it.
                if _should_stop():
                    for f in pending:
                        f.cancel()
                    for f in pending:
                        failed.append(futures[f])
                    # The names that will never be attempted still count as
                    # processed, or the progress bar freezes part-way and the
                    # scan looks hung rather than finished early.
                    state["done"] += len(pending)
                    if progress:
                        progress(state["done"], state["total"], len(rows))
                    stopped = (
                        (stopped + " ") if stopped else "") + (
                        f"Depth pass stopped after {len(rows)} names scored: the "
                        f"instance was within {SCAN_ABORT_HEADROOM_MB} MB of its "
                        f"{MEM_LIMIT_MB} MB limit. Rankings below are from what "
                        "was scored before it stopped.")
                    break
    except MemoryError:
        trim()                          # salvage whatever scored so far
        stopped = ((stopped + " ") if stopped else "") + (
            "The scan ran out of memory part-way through; what had been scored "
            "was kept.")

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
    [{"s": "RELIANCE", "n": "Reliance Industries Limited", "x": "NSE"}, ...]

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
                # The exchange travels with the row so the typeahead can label
                # a suggestion with the listing it actually is, rather than the
                # client assuming one. Everything here is NSE EQ series; a BSE
                # source would append rows carrying "x": "BSE".
                rows.append({"s": sym, "n": nm, "x": "NSE"})

            if len(rows) > 500:
                break
        except Exception:
            continue

    if not rows:
        # Same fallback the scan uses, so the two never disagree about what
        # the universe is — just without company names.
        rows = [{"s": x, "n": x, "x": "NSE"}
                for x in sorted({y for y in FALLBACK.split() if y})]

    rows.sort(key=lambda r: r["s"])
    _names_cache["at"] = time.time()
    _names_cache["rows"] = rows
    return rows
