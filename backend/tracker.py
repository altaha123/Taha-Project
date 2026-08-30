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

# Below this many closed ideas an archetype's average alpha is noise and must
# not be allowed to reorder anything.
MIN_EXPECTANCY_SAMPLE = 20

# Automatic recording exists so the hit rate cannot become a highlight reel of
# the ideas someone already liked. That is the right default for measuring an
# engine, and the wrong one for a personal watchlist — a scan drops sixty rows
# into a list you wanted to hold six. Set AUTOTRACK=0 in the environment and
# only the names you press Add on are recorded. The statistics then describe
# your picks rather than the engine's, which is a different question; the
# note on the Tracker tab says so.
# Default changed to OFF on 28 Aug 2026.
#
# The original reasoning for recording every scanned idea was sound as
# statistics: a tracker containing only the ideas you chose to save is a
# highlight reel, and the hit rate it reports is meaningless. But it made the
# Tracker tab unusable as a tracker — it filled with hundreds of rows nobody
# asked for, and "Add to tracker" appeared to do nothing because the row was
# already there.
#
# Both goals are kept by separating the two lists rather than choosing one.
# What you click on is yours and is the default view. The statistical record
# still exists under source="auto" when you switch AUTOTRACK back on, and
# listing(source=...) keeps them apart.
# A blank value means "not set", not "on". Adding AUTOTRACK to Render and
# leaving the box empty should not silently switch recording back on.
_AT = os.environ.get("AUTOTRACK", "").strip().lower()
AUTOTRACK = _AT in ("1", "true", "yes", "on")

# A forced refresh (the Refresh prices button) walks the ledger in small
# batches, one HTTP request each. Rows marked inside this window count as done
# for that pass, so the loop advances instead of re-marking the same six rows
# for ever.
FORCE_FRESH_SECONDS = 600

# An idea is not dead on its third day. The invalidation rules below read the
# latest bar, and several of them (a close back inside the Bollinger mid-band,
# ADX slipping under 20) are true of perfectly ordinary pullbacks. Applying
# them the morning after an idea is recorded marked healthy setups INVALIDATED
# before they had a chance to do anything.
MIN_DAYS_BEFORE_INVALIDATION = 5

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


def _now_iso():
    return dt.datetime.now().isoformat(timespec="seconds")


def _days_since(iso):
    try:
        return (dt.date.today() - dt.date.fromisoformat(iso)).days
    except Exception:
        return 0


# ---------------------------------------------------------------------------
# Adding
# ---------------------------------------------------------------------------

def add(row: dict, source: str = "manual", force: bool = False,
        defer_save: bool = False) -> dict:
    """
    Record one idea. Returns {"added": bool, "reason": str}.

    The price is snapshotted at add time and never rewritten. An entry price
    that drifts is the single easiest way to accidentally flatter a record.

    BUGFIX: the snapshot used to be whatever price the scan payload carried,
    and a scan payload is cached for days. Pressing Add on a four-day-old idea
    anchored the record at a four-day-old price while stamping it added today,
    so the row opened showing a return the holder never had. A manual add now
    re-reads the latest close and anchors there, keeping the scan's number
    alongside it as scan_price. If the feed is down the scan price is used and
    the row says so, rather than refusing the add.
    """
    if source == "auto" and not AUTOTRACK and not force:
        return {"added": False, "reason": "automatic recording is off (AUTOTRACK=0)"}
    sym = (row.get("symbol") or "").upper().strip()
    if not sym:
        return {"added": False, "reason": "no symbol"}
    price = row.get("price")
    try:
        price = float(price) if price is not None else None
    except (TypeError, ValueError):
        price = None
    if not price or price <= 0:
        return {"added": False, "reason": "no price to anchor the record"}

    key = row.get("setup_key") or "unclassified"
    rows = _load()
    for r in rows:
        if (r["symbol"] == sym and r.get("setup_key") == key
                and _days_since(r["added_on"]) < DEDUPE_DAYS
                and r.get("status") == "LIVE"):
            # Pressing "Add to tracker" on something the scanner had already
            # recorded automatically used to hit this branch and do nothing
            # visible — the button said "already tracked" and the row never
            # appeared in your list, because your list only shows manual rows.
            # A deliberate click now promotes the existing row to yours and
            # keeps its original entry price, so the record stays honest.
            if source == "manual" and (r.get("source") or "auto") != "manual":
                with _lock:
                    r["source"] = "manual"
                    r["promoted_on"] = _today()
                    if not defer_save:
                        _save()
                return {"added": True, "reason": "added to your tracker",
                        "id": r["id"], "promoted": True}
            return {"added": False, "reason": f"already tracking this setup on {sym}",
                    "id": r["id"], "already": True}

    # Anchor a hand-picked idea on today's price, not on the cached scan's.
    scan_price, price_source = price, "scan price"
    if source == "manual":
        fresh = _last_close(sym)
        if fresh and fresh > 0:
            price, price_source = fresh, "latest close"

    rec = {
        "id": f"{sym}-{key}-{_today()}-{source[:1]}",
        "symbol": sym,
        "name": row.get("name") or sym,
        "added_on": _today(),
        "added_price": round(float(price), 2),
        "scan_price": round(float(scan_price), 2),
        "added_price_source": price_source,
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
        "days_held": 0, "invalidated_by": None,
        "updated_on": None, "updated_at": None, "mark_error": None,
    }
    with _lock:
        rows.append(rec)
        if not defer_save:
            _save()
    return {"added": True, "reason": "tracked", "id": rec["id"],
            "added_price": rec["added_price"], "price_source": price_source}


def add_many(rows: list, source: str = "auto", force: bool = False) -> dict:
    """
    BUGFIX: this used to call add() once per row, and add() wrote the whole
    ledger to disk with an fsync every time. Recording a sixty-name scan meant
    sixty full rewrites, which on a small box took long enough that the request
    timed out and the caller reported a failure for work that had succeeded.
    One write at the end is enough — the rows are appended to the same cached
    list either way.
    """
    added = skipped = 0
    reasons = {}
    for r in rows:
        res = add(r, source=source, force=force, defer_save=True)
        if res["added"]:
            added += 1
        else:
            skipped += 1
            reasons[res["reason"]] = reasons.get(res["reason"], 0) + 1
    if added or skipped:
        with _lock:
            _save()
    return {"added": added, "skipped": skipped, "skipped_because": reasons,
            "total_tracked": len(_load())}


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


def _last_close(symbol):
    """Most recent close for one symbol, or None. Used to anchor manual adds."""
    df = _daily(symbol, days=15)
    if df is None or df.empty or "Close" not in df:
        return None
    try:
        c = df["Close"].dropna()
        return float(c.iloc[-1]) if len(c) else None
    except Exception:
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


def _dated_index(df):
    """
    The frame's index as tz-naive calendar days, or None when it carries no
    usable dates.

    BUGFIX — this is why every price column was blank. Yahoo returns a daily
    index localised to the exchange timezone, and comparing a tz-aware index
    with a tz-naive Timestamp raises TypeError in pandas. The exception was
    swallowed by the caller's bare except, _window() returned None, and every
    row fell into the "added today, no bar yet" branch: last price pinned to
    the entry, return 0.00%, no best, no worst, no index column — for ever,
    and identical to a tracker that had simply never been marked.

    Dhan can also answer without a timestamp array, in which case the frame
    carries a RangeIndex; pd.to_datetime turns 0,1,2 into three instants in
    1970, every bar sorts before every idea date, and the window came back
    empty with the same result. That case is now detected and reported
    instead of silently producing zeros.
    """
    if df is None or len(df) == 0:
        return None
    idx = df.index
    if not isinstance(idx, pd.DatetimeIndex):
        if getattr(idx, "dtype", None) is not None and str(idx.dtype).startswith(("int", "range")):
            return None                       # positional index — no dates to compare
        try:
            idx = pd.DatetimeIndex(pd.to_datetime(idx))
        except Exception:
            return None
    if getattr(idx, "tz", None) is not None:
        try:
            idx = idx.tz_localize(None)       # keep exchange wall time, drop the zone
        except Exception:
            try:
                idx = idx.tz_convert(None)
            except Exception:
                return None
    try:
        return idx.normalize()
    except Exception:
        return None


def _window(df, since_iso):
    """Rows on or after the idea date. Returns None when the date is missing."""
    if df is None or df.empty:
        return None
    idx = _dated_index(df)
    if idx is None:
        return None
    try:
        sub = df[idx >= pd.Timestamp(since_iso).normalize()]
        return sub if len(sub) else None
    except Exception:
        return None


def _check_invalidation(key, df, entry=None):
    """
    Evaluate the machine-checkable invalidation conditions the archetypes
    already state. Conditions that depend on the next filing (institutional
    stake, promoter stake) cannot be checked here and are reported as
    manual-review rather than silently ignored.

    BUGFIX: the mid-band test used to fire on any close under the 20-day mean,
    which is an ordinary pullback, not a failed breakout — a name that was
    still up 8% on your entry could be stamped INVALIDATED for taking a
    breather. The premise has only failed if the price is back inside the band
    AND has given up the entry. Where the entry is unknown the test is skipped
    rather than guessed at.

    A NaN indicator (too few bars for a 20-period mean, a feed that returned a
    gap) used to compare False and quietly count as "healthy". Every read is
    now checked, so an unmeasurable condition leaves the row LIVE on purpose
    rather than by accident.
    """
    if df is None or len(df) < 60:
        return None

    def val(series):
        try:
            v = float(series.iloc[-1])
        except Exception:
            return None
        return None if v != v else v          # NaN is not a verdict

    try:
        close = df["Close"]
        last = val(close)
        if last is None:
            return None
        if key == "momentum_breakout":
            st = val(supertrend(df))
            if st is not None and last < st:
                return "Closed below the Supertrend band — trend regime flipped"
            a = val(adx(df))
            if a is not None and a < 20:
                return f"ADX fell to {a:.0f} — trend lost force"
            mid = val(bollinger(close)[0])
            if mid is not None and last < mid and entry and last < float(entry):
                return "Back inside the Bollinger mid-band and below the entry — the breakout failed"
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
                ma200 = val(close.rolling(200).mean())
                if ma200 is not None and last < ma200 * 0.90:
                    return "Price 10% below its 200-day average — the decline has not stopped"
    except Exception:
        return None
    return None


def update_one(rec):
    """
    Mark a single record. Mutates and returns it.

    The stamp goes on FIRST, before anything that can fail. A row whose symbol
    no longer resolves used to be left with no updated_on at all, so it stayed
    at the head of the pending queue for ever: the Refresh button re-tried the
    same handful of dead symbols on every batch and never reached the rows
    behind them.
    """
    rec["updated_on"] = _today()
    rec["updated_at"] = _now_iso()
    rec["days_held"] = _days_since(rec["added_on"])

    sym = rec["symbol"]
    df = _daily(sym, days=420)
    if df is None or df.empty:
        rec["mark_error"] = "no daily bars from either feed"
        return rec
    try:
        df = df.dropna(subset=["Close"])
    except Exception:
        rec["mark_error"] = "feed returned a frame with no Close column"
        return rec
    if df.empty:
        rec["mark_error"] = "feed returned bars but every close was blank"
        return rec

    try:
        entry = float(rec.get("added_price") or 0)
    except (TypeError, ValueError):
        entry = 0.0
    if entry <= 0:
        rec["mark_error"] = "no entry price to measure against"
        return rec

    rec["mark_error"] = None

    # The last close needs no windowing, so it is read first. Previously every
    # column here depended on the window succeeding, which meant one date
    # problem blanked the whole row rather than just the columns that genuinely
    # need a date range.
    last = float(df["Close"].iloc[-1])
    rec["last_price"] = round(last, 2)
    rec["return_pct"] = round((last - entry) / entry * 100, 2)

    win = _window(df, rec["added_on"])
    if win is None or win.empty:
        if _dated_index(df) is None:
            # No usable dates: the return above is still correct, the
            # path-dependent columns are not computable. Say so.
            rec["mark_error"] = "feed returned undated bars — best/worst unavailable"
            rec["max_gain_pct"] = None
            rec["max_drawdown_pct"] = None
        else:
            # Added today, before the session's bar exists.
            rec["max_gain_pct"] = max(rec["return_pct"], 0.0)
            rec["max_drawdown_pct"] = min(rec["return_pct"], 0.0)
    else:
        hi = float(win["High"].max()) if "High" in win else last
        lo = float(win["Low"].min()) if "Low" in win else last
        # Best can never be worse than where it stands now, and "worst dip"
        # is a dip: an idea that only ever went up has a drawdown of zero, not
        # a positive number the tab then renders in red as a loss.
        rec["max_gain_pct"] = round(max((hi - entry) / entry * 100, rec["return_pct"], 0.0), 2)
        rec["max_drawdown_pct"] = round(min((lo - entry) / entry * 100, rec["return_pct"], 0.0), 2)

    # Same-window index return. Without this the whole table is just beta.
    rec["bench_return_pct"] = None
    rec["alpha_pct"] = None
    bench = _window(_benchmark_frame(), rec["added_on"])
    if bench is not None and len(bench):
        try:
            b0 = float(bench["Close"].iloc[0])
            b1 = float(bench["Close"].iloc[-1])
            if b0:
                rec["bench_return_pct"] = round((b1 - b0) / b0 * 100, 2)
                rec["alpha_pct"] = round(rec["return_pct"] - rec["bench_return_pct"], 2)
        except Exception:
            pass

    if rec.get("status") == "LIVE":
        if rec["days_held"] > HORIZON_DAYS.get(rec.get("setup_key"), 365):
            rec["status"] = "EXPIRED"
            rec["invalidated_by"] = "Horizon elapsed without the premise playing out"
        elif rec["days_held"] >= MIN_DAYS_BEFORE_INVALIDATION:
            bad = _check_invalidation(rec.get("setup_key"), df, entry=entry)
            if bad:
                rec["status"] = "INVALIDATED"
                rec["invalidated_by"] = bad
    return rec


def _pending(rows, force: bool):
    """
    The rows still owed a mark, stalest first.

    Ordinary run: anything not marked today.
    Forced run:   anything not marked in the last FORCE_FRESH_SECONDS. This is
                  what makes the Refresh button work in batches. A plain
                  "re-mark everything" force re-sorted the whole ledger by a
                  date that was identical for every row, so each six-row batch
                  picked the same six rows and the loop never advanced.
    """
    if force:
        cutoff = (dt.datetime.now()
                  - dt.timedelta(seconds=FORCE_FRESH_SECONDS)).isoformat(timespec="seconds")
        pend = [r for r in rows if (r.get("updated_at") or "") < cutoff]
    else:
        today = _today()
        pend = [r for r in rows if (r.get("updated_on") or "") != today]
    # Never-marked rows first, then the stalest.
    pend.sort(key=lambda r: (r.get("last_price") is not None,
                             r.get("updated_at") or "",
                             r.get("updated_on") or ""))
    return pend


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

    BUGFIX: the return value had no "remaining" field. The Refresh button
    marks in small batches and loops until remaining hits zero; with the field
    absent it treated the server as an out-of-date build, stopped after a
    single batch of six, and reported "old backend". Any tracker holding more
    than six rows therefore never finished marking no matter how often the
    button was pressed. It is now reported, and it is recomputed after the
    batch so the caller sees real progress rather than the count it started
    with.
    """
    rows = _load()
    if not rows:
        return {"updated": 0, "priced": 0, "tracked": 0, "marked": 0,
                "errors": 0, "remaining": 0, "forced": bool(force)}
    batch = _pending(rows, force)[:max(1, int(limit))]
    n = 0
    for rec in batch:
        try:
            update_one(rec)
        except Exception as e:
            # Stamp it anyway — see update_one. An unstamped failure blocks
            # every row behind it.
            rec["updated_on"] = _today()
            rec["updated_at"] = _now_iso()
            rec["mark_error"] = f"marking failed: {str(e)[:100]}"
        n += 1
    with _lock:
        _save()
    return {"updated": n,
            "priced": sum(1 for r in batch if not r.get("mark_error")),
            "tracked": len(rows),
            "marked": sum(1 for r in rows if r.get("last_price") is not None),
            "errors": sum(1 for r in rows if r.get("mark_error")),
            "remaining": len(_pending(rows, force)),
            "forced": bool(force),
            "last_marked_at": _now_iso()}


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

def _median(values):
    v = sorted(values)
    if not v:
        return None
    mid = len(v) // 2
    return v[mid] if len(v) % 2 else round((v[mid - 1] + v[mid]) / 2, 2)


def _bucket(rows):
    """
    Summary statistics for one group of ideas.

    Only marked rows count. A row that has never been priced is not a zero-
    return idea — it is an unmeasured one, and averaging it in as a zero is
    how a tracker quietly reports a hit rate it has not earned.
    """
    marked = [r for r in rows if r.get("return_pct") is not None]
    if not marked:
        return None
    n = len(marked)
    wins = sum(1 for r in marked if r["return_pct"] > 0)
    alpha_rows = [r for r in marked if r.get("alpha_pct") is not None]
    beat = sum(1 for r in alpha_rows if r["alpha_pct"] > 0)
    dd_rows = [r["max_drawdown_pct"] for r in marked if r.get("max_drawdown_pct") is not None]
    return {
        "ideas": n,
        "win_rate": round(wins / n * 100),
        "avg_return_pct": round(sum(r["return_pct"] for r in marked) / n, 2),
        "median_return_pct": _median([r["return_pct"] for r in marked]),
        "avg_alpha_pct": (round(sum(r["alpha_pct"] for r in alpha_rows) / len(alpha_rows), 2)
                          if alpha_rows else None),
        "alpha_ideas": len(alpha_rows),
        "beat_index_pct": round(beat / len(alpha_rows) * 100) if alpha_rows else None,
        # Averaged over the rows that actually have a drawdown, not over every
        # marked row — dividing a partial sum by the full count understated the
        # worst dip whenever some rows were missing the column.
        "avg_max_drawdown_pct": round(sum(dd_rows) / len(dd_rows), 2) if dd_rows else None,
        "median_days_held": _median([r.get("days_held") or 0 for r in marked]),
        # Under about 30 closed ideas any of this is noise, and the tab should
        # say so rather than printing a confident percentage.
        "reliable": n >= 30,
    }


def stats(source: str = "") -> dict:
    """
    BUGFIX: stats always described the whole ledger while the Tracker tab
    listed one source. With automatic recording on you saw six of your own
    picks above a headline counting ninety-two ideas, and a "23 rows have no
    prices" warning about rows the tab was not showing. The source filter now
    runs through both, so the numbers describe the list underneath them.
    """
    rows = _load()
    if source:
        rows = [r for r in rows if (r.get("source") or "auto") == source]
    by_arch, by_sector, by_month = {}, {}, {}
    for r in rows:
        by_arch.setdefault(r.get("setup") or "Unclassified", []).append(r)
        by_sector.setdefault(r.get("sector") or "Unknown", []).append(r)
        by_month.setdefault((r.get("added_on") or "")[:7], []).append(r)

    marked = sum(1 for r in rows if r.get("return_pct") is not None)
    stamps = [r.get("updated_at") for r in rows if r.get("updated_at")]
    return {
        "source": source or "all",
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
        "last_marked_at": max(stamps) if stamps else None,
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
        key = r.get("setup_key")
        if key:
            grouped.setdefault(key, []).append(r["alpha_pct"])
    for k, vals in grouped.items():
        if len(vals) >= MIN_EXPECTANCY_SAMPLE:   # below this it is noise
            out[k] = round(sum(vals) / len(vals), 2)
    return out


def expectancy_detail() -> dict:
    """
    The same numbers with their sample sizes, so the Ideas tab can say
    "averaged +2.1% alpha across 34 closed ideas" instead of asserting a
    figure with no idea how much evidence sits behind it.
    """
    rows = [r for r in _load() if r.get("alpha_pct") is not None]
    grouped = {}
    for r in rows:
        key = r.get("setup_key")
        if key:
            grouped.setdefault(key, []).append(r["alpha_pct"])
    return {k: {"avg_alpha_pct": round(sum(v) / len(v), 2), "ideas": len(v),
                "reliable": len(v) >= MIN_EXPECTANCY_SAMPLE}
            for k, v in grouped.items()}


def tracked_symbols(source: str = "") -> set:
    """Symbols with a LIVE row, so the Ideas tab can show what is already
    tracked instead of offering an Add button that answers "already tracked"."""
    out = set()
    for r in _load():
        if r.get("status") != "LIVE":
            continue
        if source and (r.get("source") or "auto") != source:
            continue
        out.add(r.get("symbol"))
    return out


def listing(status: str = "", limit: int = 400, source: str = "manual") -> dict:
    """source defaults to "manual" — the Tracker tab is your list, not the
    scanner's. Pass source="" for everything, or source="auto" for the
    statistical record."""
    rows = _load()
    if status:
        rows = [r for r in rows if r.get("status") == status.upper()]
    if source:
        rows = [r for r in rows if (r.get("source") or "auto") == source]
    total = len(rows)
    # BUGFIX: these counts were taken after the slice, so a ledger of 600 rows
    # reported the marked count of the 400 that fitted on the page and the
    # tab's "still unmarked" line was wrong by whatever fell off the end.
    marked = sum(1 for r in rows if r.get("last_price") is not None)
    errors = sum(1 for r in rows if r.get("mark_error"))
    stamps = [r.get("updated_at") for r in rows if r.get("updated_at")]
    rows = sorted(rows, key=lambda r: (r.get("added_on") or "", r.get("id") or ""),
                  reverse=True)[:limit]
    return {"rows": rows, "count": total, "shown": len(rows),
            "benchmark": BENCHMARK, "autotrack": AUTOTRACK,
            "source": source or "all",
            "marked": marked, "unmarked": total - marked, "mark_errors": errors,
            "last_marked_at": max(stamps) if stamps else None,
            "storage_is_ephemeral": DATA_DIR == HERE}


def export_csv() -> str:
    rows = sorted(_load(), key=lambda r: r.get("added_on") or "", reverse=True)
    cols = ["added_on", "symbol", "name", "setup", "sector", "horizon",
            "added_price", "added_price_source", "scan_price",
            "last_price", "updated_on", "return_pct", "bench_return_pct",
            "alpha_pct", "max_gain_pct", "max_drawdown_pct", "days_held",
            "status", "invalidated_by", "fit", "composite", "technical",
            "fundamental", "liquidity_tier", "avg_turnover_cr", "source",
            "mark_error"]
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        w.writerow(r)
    return buf.getvalue()
