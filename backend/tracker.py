"""
Altaha Screener — Idea Tracker

The engine has produced ideas for months and has never once recorded whether
any of them worked. Every argument about thresholds, archetypes and weights has
therefore been a matter of taste. This file ends that.

WHAT IT DOES
  · Records EVERY idea automatically at scan time — not just the ones that get
    clicked. Selective tracking quietly becomes a highlight reel, because the
    ideas a person bothers to save are the ones they already liked.
  · Marks each one daily: return since the idea, best gain, worst drawdown, and
    the SAME-WINDOW return of the index. The last one is the only honest
    number. A 9% gain while the market did 11% is a loss of the thing this
    engine claims to provide.
  · Checks the invalidation conditions the archetypes already state, so a dead
    idea stops looking identical to a live one.

WHAT IT DELIBERATELY DOES NOT DO
  · No position sizing, no P&L, no holdings. That is the Portfolio tab. This is
    a research record — the question it answers is "does the engine work", not
    "how much did I make".
  · No re-entry logic, no averaging. One idea, one row, one outcome.

STORAGE
  DATA_DIR/tracked.json. Set DATA_DIR=/data with a Render disk attached, or the
  file is wiped on every deploy and the record never accumulates.
"""

import csv
import datetime as dt
import io
import json
import os
import threading

import pandas as pd

try:
    import dhan_source as dhan
except Exception:
    dhan = None

# Marking used to depend on Dhan alone. When the token expired — which it does,
# daily, by design — every price column silently stayed None and the whole
# table read as "0 days, no return", which is indistinguishable from "nothing
# has happened yet". The daily feed is a perfectly good second source for a
# record that only needs closes.
try:
    from data_source import resolve as _resolve
except Exception:
    _resolve = None

from engine import adx, bollinger, supertrend

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("DATA_DIR", "").strip() or HERE
try:
    os.makedirs(DATA_DIR, exist_ok=True)
except Exception:
    DATA_DIR = HERE

TRACK_FILE = os.path.join(DATA_DIR, "tracked.json")
BENCHMARK = os.environ.get("INDEX_PROXY", "NIFTYBEES").strip().upper()

# Re-adding the same setup on the same stock every 12 hours would turn one idea
# into sixty rows and make the hit rate meaningless.
DEDUPE_DAYS = 30

# Automatic recording exists so the hit rate cannot become a highlight reel of
# the ideas someone already liked. That is the right default for measuring an
# engine, and the wrong one for a personal watchlist — a scan drops sixty rows
# into a list you wanted to hold six. Set AUTOTRACK=0 in the environment and
# only the names you press Add on are recorded. The statistics then describe
# your picks rather than the engine's, which is a different question; the
# note on the Tracker tab says so.
AUTOTRACK = os.environ.get("AUTOTRACK", "1").strip().lower() not in ("0", "false", "no", "off")

# How long each archetype's premise is allowed before it is judged expired.
# Taken from the horizons the archetypes already declare, expressed in days.
HORIZON_DAYS = {
    "momentum_breakout": 56,            # 3-8 weeks
    "institutional_accumulation": 180,  # 2-6 months
    "quality_at_discount": 365,
    "turnaround": 365,
}

_lock = threading.Lock()
_cache = {"rows": None}
_bench_cache = {"day": None, "df": None}


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

def _load():
    if _cache["rows"] is not None:
        return _cache["rows"]
    rows = []
    if os.path.exists(TRACK_FILE):
        try:
            with open(TRACK_FILE) as f:
                rows = json.load(f)
        except Exception:
            rows = []
    _cache["rows"] = rows
    return rows


def _save():
    """
    Atomic write.

    BUGFIX: this used to be a plain open(TRACK_FILE, "w"). That truncates the
    file the instant it opens. If the process died mid-write — and on a 512 MB
    box it does — the ledger was left half-written and unreadable, silently
    wiping every tracked idea on the next load.

    Now the rows are written to a temporary file in the same directory and
    then moved into place with os.replace(), which is atomic on every OS we
    run on. At no point does a partially-written file exist under the real
    name: either the old ledger is intact, or the new one is complete.
    """
    rows = _cache["rows"] or []
    tmp = f"{TRACK_FILE}.{os.getpid()}.tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(rows, f)
            f.flush()
            os.fsync(f.fileno())      # force to disk before the swap
        os.replace(tmp, TRACK_FILE)   # atomic
    except Exception:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass


def _today():
    return dt.date.today().isoformat()


def _days_since(iso):
    try:
        return (dt.date.today() - dt.date.fromisoformat(iso)).days
    except Exception:
        return 0


# ---------------------------------------------------------------------------
# Adding
# ---------------------------------------------------------------------------

def add(row: dict, source: str = "manual") -> dict:
    """
    Record one idea. Returns {"added": bool, "reason": str}.

    The price is snapshotted at add time and never rewritten. An entry price
    that drifts is the single easiest way to accidentally flatter a record.
    """
    if source == "auto" and not AUTOTRACK:
        return {"added": False, "reason": "automatic recording is off (AUTOTRACK=0)"}
    sym = (row.get("symbol") or "").upper().strip()
    if not sym:
        return {"added": False, "reason": "no symbol"}
    price = row.get("price")
    if not price:
        return {"added": False, "reason": "no price to anchor the record"}

    key = row.get("setup_key") or "unclassified"
    rows = _load()
    for r in rows:
        if (r["symbol"] == sym and r.get("setup_key") == key
                and _days_since(r["added_on"]) < DEDUPE_DAYS
                and r.get("status") == "LIVE"):
            return {"added": False, "reason": f"already tracking this setup on {sym}"}

    rec = {
        "id": f"{sym}-{key}-{_today()}",
        "symbol": sym,
        "name": row.get("name") or sym,
        "added_on": _today(),
        "added_price": round(float(price), 2),
        "setup_key": key,
        "setup": row.get("setup") or "Unclassified",
        "fit": row.get("setup_fit"),
        "composite": row.get("composite"),
        "technical": row.get("technical"),
        "fundamental": row.get("fundamental"),
        "sector": row.get("sector"),
        "horizon": row.get("horizon"),
        "liquidity_tier": row.get("liquidity_tier"),
        "avg_turnover_cr": row.get("avg_turnover_cr"),
        "source": source,
        "status": "LIVE",
        # filled by update_all()
        "last_price": None, "return_pct": None, "bench_return_pct": None,
        "alpha_pct": None, "max_gain_pct": None, "max_drawdown_pct": None,
        "days_held": 0, "invalidated_by": None, "updated_on": None,
    }
    with _lock:
        rows.append(rec)
        _save()
    return {"added": True, "reason": "tracked", "id": rec["id"]}


def add_many(rows: list, source: str = "auto") -> dict:
    added = skipped = 0
    for r in rows:
        res = add(r, source=source)
        added += 1 if res["added"] else 0
        skipped += 0 if res["added"] else 1
    return {"added": added, "skipped": skipped, "total_tracked": len(_load())}


def remove(idea_id: str) -> dict:
    rows = _load()
    with _lock:
        before = len(rows)
        _cache["rows"] = [r for r in rows if r["id"] != idea_id]
        _save()
    return {"removed": before - len(_cache["rows"])}


# ---------------------------------------------------------------------------
# Marking
# ---------------------------------------------------------------------------

def _daily(symbol, days=420):
    """
    Daily bars for one symbol, from whichever feed answers.

    Dhan first because it is the live one, then the daily feed. Returning None
    from both is a real outcome and the caller leaves the row unmarked, but a
    row should never go unmarked merely because one token expired overnight.
    """
    df = None
    try:
        if dhan is not None and dhan.configured():
            df = dhan.daily_ohlcv(symbol, days=days)
    except Exception:
        df = None
    if df is not None and not df.empty:
        return df
    if _resolve is None:
        return None
    try:
        _sym, _t, hist = _resolve(symbol)
        if hist is not None and not hist.empty:
            return hist.tail(days)
    except Exception:
        return None
    return None


def _benchmark_frame():
    """Daily index-proxy frame, fetched once a day."""
    if _bench_cache["day"] == _today() and _bench_cache["df"] is not None:
        return _bench_cache["df"]
    df = _daily(BENCHMARK, days=500)
    if df is None:
        df = _daily("^NSEI", days=500)      # the proxy ETF is not always mapped
    _bench_cache["day"] = _today()
    _bench_cache["df"] = df
    return df


def _window(df, since_iso):
    """Rows on or after the idea date. Returns None when the date is missing."""
    if df is None or df.empty:
        return None
    try:
        idx = pd.to_datetime(df.index)
        mask = idx >= pd.Timestamp(since_iso)
        sub = df[mask]
        return sub if len(sub) else None
    except Exception:
        return None


def _check_invalidation(key, df):
    """
    Evaluate the machine-checkable invalidation conditions the archetypes
    already state. Conditions that depend on the next filing (institutional
    stake, promoter stake) cannot be checked here and are reported as
    manual-review rather than silently ignored.
    """
    if df is None or len(df) < 60:
        return None
    try:
        close = df["Close"]
        if key == "momentum_breakout":
            st = supertrend(df)
            if float(close.iloc[-1]) < float(st.iloc[-1]):
                return "Closed below the Supertrend band — trend regime flipped"
            a = adx(df)
            if float(a.iloc[-1]) < 20:
                return f"ADX fell to {float(a.iloc[-1]):.0f} — trend lost force"
            mid, up, lo, _, _ = bollinger(close)
            if float(close.iloc[-1]) < float(mid.iloc[-1]):
                return "Back inside the Bollinger mid-band — the breakout failed"
        elif key == "institutional_accumulation":
            # OBV rolling over while price holds: the classic divergence.
            sign = (close.diff() > 0).astype(int) * 2 - 1
            obv = (sign * df["Volume"]).cumsum()
            if len(obv) > 25:
                obv_down = float(obv.iloc[-1]) < float(obv.iloc[-21])
                px_flat = float(close.iloc[-1]) >= float(close.iloc[-21]) * 0.97
                if obv_down and px_flat:
                    return "OBV rolling over while price holds — accumulation has stopped"
        elif key in ("quality_at_discount", "turnaround"):
            if len(close) > 200:
                ma200 = close.rolling(200).mean()
                if (float(close.iloc[-1]) < float(ma200.iloc[-1]) * 0.90):
                    return "Price 10% below its 200-day average — the decline has not stopped"
    except Exception:
        return None
    return None


def update_one(rec):
    """Mark a single record. Mutates and returns it."""
    sym = rec["symbol"]
    df = _daily(sym, days=420)
    if df is None or df.empty:
        rec["mark_error"] = "no daily bars from either feed"
        return rec
    rec["mark_error"] = None
    df = df.dropna(subset=["Close"])

    sub = _window(df, rec["added_on"])
    if sub is None or sub.empty:
        # Added today, before the day's bar exists. Anchor on the entry so the
        # row shows a price rather than a dash, and let tomorrow mark it
        # properly. A row that shows nothing looks broken.
        rec["last_price"] = rec["added_price"]
        rec["return_pct"] = 0.0
        rec["days_held"] = _days_since(rec["added_on"])
        rec["updated_on"] = _today()
        return rec

    entry = float(rec["added_price"])
    last = float(sub["Close"].iloc[-1])
    hi = float(sub["High"].max())
    lo = float(sub["Low"].min())

    rec["last_price"] = round(last, 2)
    rec["return_pct"] = round((last - entry) / entry * 100, 2)
    rec["max_gain_pct"] = round((hi - entry) / entry * 100, 2)
    rec["max_drawdown_pct"] = round((lo - entry) / entry * 100, 2)
    rec["days_held"] = _days_since(rec["added_on"])

    # Same-window index return. Without this the whole table is just beta.
    bench = _window(_benchmark_frame(), rec["added_on"])
    if bench is not None and len(bench) > 1:
        b0 = float(bench["Close"].iloc[0])
        b1 = float(bench["Close"].iloc[-1])
        if b0:
            rec["bench_return_pct"] = round((b1 - b0) / b0 * 100, 2)
            rec["alpha_pct"] = round(rec["return_pct"] - rec["bench_return_pct"], 2)

    if rec["status"] == "LIVE":
        bad = _check_invalidation(rec.get("setup_key"), df)
        if bad:
            rec["status"] = "INVALIDATED"
            rec["invalidated_by"] = bad
        elif rec["days_held"] > HORIZON_DAYS.get(rec.get("setup_key"), 365):
            rec["status"] = "EXPIRED"
            rec["invalidated_by"] = "Horizon elapsed without the premise playing out"

    rec["updated_on"] = _today()
    return rec


def update_all(limit: int = 120, force: bool = False) -> dict:
    """
    Refresh the oldest-updated records first, capped so one cron tick can never
    blow the data quota. Run it after the close.

    Never-marked rows are done first. Previously the sort put empty strings
    first only by accident of comparison, and a row that failed once could sit
    at the front of the queue for good while newer rows stayed blank. Rows that
    have never been marked are now explicitly prioritised, then the stalest.

    force=True re-marks rows already updated today, which is what the Refresh
    button on the Tracker tab needs — otherwise pressing it after a successful
    morning run appears to do nothing at all.
    """
    rows = _load()
    if not rows:
        return {"updated": 0, "tracked": 0, "marked": 0}
    today = _today()
    if force:
        pending = sorted(rows, key=lambda r: (r.get("updated_on") or ""))[:limit]
    else:
        pending = sorted(
            (r for r in rows if (r.get("updated_on") or "") != today),
            key=lambda r: (r.get("last_price") is not None, r.get("updated_on") or "")
        )[:limit]
    n = 0
    for rec in pending:
        try:
            update_one(rec)
            n += 1
        except Exception:
            continue
    with _lock:
        _save()
    return {"updated": n, "tracked": len(rows),
            "marked": sum(1 for r in rows if r.get("last_price") is not None),
            "errors": sum(1 for r in rows if r.get("mark_error"))}


def purge(source: str = "auto") -> dict:
    """
    Drop every row recorded by one route. Turning AUTOTRACK off stops new
    automatic rows but leaves the sixty already sitting there, and deleting
    them one at a time is not a reasonable ask.
    """
    rows = _load()
    with _lock:
        before = len(rows)
        _cache["rows"] = [r for r in rows if (r.get("source") or "auto") != source]
        _save()
    return {"removed": before - len(_cache["rows"]), "remaining": len(_cache["rows"])}


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------

def _bucket(rows):
    marked = [r for r in rows if r.get("return_pct") is not None]
    if not marked:
        return None
    n = len(marked)
    wins = sum(1 for r in marked if r["return_pct"] > 0)
    alpha_rows = [r for r in marked if r.get("alpha_pct") is not None]
    beat = sum(1 for r in alpha_rows if r["alpha_pct"] > 0)
    return {
        "ideas": n,
        "win_rate": round(wins / n * 100),
        "avg_return_pct": round(sum(r["return_pct"] for r in marked) / n, 2),
        "avg_alpha_pct": (round(sum(r["alpha_pct"] for r in alpha_rows) / len(alpha_rows), 2)
                          if alpha_rows else None),
        "beat_index_pct": round(beat / len(alpha_rows) * 100) if alpha_rows else None,
        "avg_max_drawdown_pct": round(sum(r.get("max_drawdown_pct") or 0
                                          for r in marked) / n, 2),
        "median_days_held": sorted(r.get("days_held", 0) for r in marked)[n // 2],
    }


def stats() -> dict:
    rows = _load()
    by_arch, by_sector, by_month = {}, {}, {}
    for r in rows:
        by_arch.setdefault(r.get("setup") or "Unclassified", []).append(r)
        by_sector.setdefault(r.get("sector") or "Unknown", []).append(r)
        by_month.setdefault((r.get("added_on") or "")[:7], []).append(r)

    marked = sum(1 for r in rows if r.get("return_pct") is not None)
    return {
        "overall": _bucket(rows),
        "by_archetype": {k: _bucket(v) for k, v in sorted(by_arch.items())},
        "by_sector": {k: _bucket(v) for k, v in sorted(by_sector.items())},
        "by_month": {k: _bucket(v) for k, v in sorted(by_month.items())},
        "status_counts": {
            "LIVE": sum(1 for r in rows if r.get("status") == "LIVE"),
            "INVALIDATED": sum(1 for r in rows if r.get("status") == "INVALIDATED"),
            "EXPIRED": sum(1 for r in rows if r.get("status") == "EXPIRED"),
        },
        "total_tracked": len(rows),
        "marked": marked,
        "benchmark": BENCHMARK,
        "storage_is_ephemeral": DATA_DIR == HERE,
        "autotrack": AUTOTRACK,
        "unmarked": sum(1 for r in rows if r.get("last_price") is None),
        "mark_errors": sum(1 for r in rows if r.get("mark_error")),
        "note": ("Alpha is return minus the index over the identical window — it is the only "
                 "column that says anything about the engine. Return alone mostly measures the "
                 "market. Under about 30 marked ideas a bucket is noise, and archetypes with "
                 "long horizons will look empty for months before they mean anything."),
    }


def expectancy_by_archetype() -> dict:
    """
    {setup_key: avg_alpha_pct} for archetypes with enough history to matter.
    Used by the Ideas ranker so ordering is driven by what has actually worked
    rather than by how neatly a stock matches a template.
    """
    rows = [r for r in _load() if r.get("alpha_pct") is not None]
    out = {}
    grouped = {}
    for r in rows:
        grouped.setdefault(r.get("setup_key"), []).append(r["alpha_pct"])
    for k, vals in grouped.items():
        if len(vals) >= 20:                      # below this it is noise
            out[k] = round(sum(vals) / len(vals), 2)
    return out


def listing(status: str = "", limit: int = 400, source: str = "") -> dict:
    rows = _load()
    if status:
        rows = [r for r in rows if r.get("status") == status.upper()]
    if source:
        rows = [r for r in rows if (r.get("source") or "auto") == source]
    total = len(rows)
    rows = sorted(rows, key=lambda r: r.get("added_on") or "", reverse=True)[:limit]
    return {"rows": rows, "count": total, "benchmark": BENCHMARK,
            "autotrack": AUTOTRACK,
            "marked": sum(1 for r in rows if r.get("last_price") is not None),
            "storage_is_ephemeral": DATA_DIR == HERE}


def export_csv() -> str:
    rows = sorted(_load(), key=lambda r: r.get("added_on") or "", reverse=True)
    cols = ["added_on", "symbol", "name", "setup", "sector", "horizon",
            "added_price", "last_price", "return_pct", "bench_return_pct",
            "alpha_pct", "max_gain_pct", "max_drawdown_pct", "days_held",
            "status", "invalidated_by", "fit", "composite", "technical",
            "fundamental", "liquidity_tier", "avg_turnover_cr", "source"]
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        w.writerow(r)
    return buf.getvalue()
