"""
Altaha Screener — forward-return labelling

WHAT THIS IS FOR
The point-in-time store banks what the engine believed on a given day. On its
own that is a diary, not evidence. This module attaches the other half: what
each of those stocks then actually did, measured against the index over the
identical window.

Once both halves exist, every question about whether the engine works stops
being an argument and becomes a query. That is the entire purpose — the
project's claim is that it shows its working, and a scoring engine that has
never been scored is the one place that claim did not hold.

WHY EXCESS RETURN AND NOT RETURN
A stock that rose 6% in a month when the index rose 6% told you nothing about
the engine. Only the difference does. Every label carries the raw return, the
benchmark's return over the same two dates, and the excess.

WHY IT IS A SEPARATE, IDEMPOTENT JOB
Labels can only be written once the horizon has elapsed, which is days or
months after the snapshot. So this runs on a schedule, finds what is missing,
fills what it can, and leaves the rest. Running it twice changes nothing.
"""

import datetime as dt
import threading

try:
    import pandas as pd
except Exception:                                  # pragma: no cover
    pd = None

import pit_store

# Four horizons, chosen to bracket how the product is actually used: a week,
# a fortnight, a month, a quarter. The engine's own signal was measured to
# decay somewhere between the fortnight and the month, so both sides of that
# boundary have to be observable.
HORIZONS = (5, 10, 21, 63)

BENCHMARK = "NIFTYBEES"

# A horizon is only labelled once enough calendar time has passed for that many
# trading sessions to exist. 1.55 covers weekends and the Indian holiday
# calendar with room to spare; being late by a few days costs nothing, being
# early writes a wrong number that is never revisited.
CALENDAR_SLACK = 1.55

_lock = threading.Lock()
_running = {"at": None, "done": 0, "written": 0}


def _history(symbol):
    """Daily closes for one symbol, or None. Never raises."""
    try:
        from data_source import resolve
        _sym, _t, hist = resolve(symbol)
    except Exception:
        return None
    if hist is None or "Close" not in getattr(hist, "columns", []):
        return None
    if len(hist) < 5:
        return None
    close = hist["Close"].dropna()
    if not len(close):
        return None
    try:
        idx = pd.to_datetime(close.index)
        if getattr(idx, "tz", None) is not None:
            idx = idx.tz_localize(None)
        close.index = idx.normalize()
    except Exception:
        return None
    return close


def _at_or_before(series, when):
    """
    The last close on or before a date, and the date it came from.

    The index is normalised Timestamps, so `when` is coerced to one: pandas 4
    deprecates slicing a DatetimeIndex with a bare datetime.date, and the
    dates arriving here are a mix of ISO strings from the store and date
    objects from the caller.
    """
    try:
        when = pd.Timestamp(when).normalize()
    except Exception:
        return None, None
    try:
        sub = series.loc[:when]
    except Exception:
        return None, None
    if not len(sub):
        return None, None
    return float(sub.iloc[-1]), sub.index[-1]


def _forward(series, start, horizon):
    """
    Return over `horizon` TRADING sessions from the bar on or before `start`.

    Sessions, not calendar days: a 21-day horizon means twenty-one bars, so a
    long holiday does not quietly shorten the window being measured.
    """
    px0, d0 = _at_or_before(series, start)
    if px0 is None or px0 <= 0:
        return None, None
    try:
        i = series.index.get_loc(d0)
    except Exception:
        return None, None
    j = i + horizon
    if j >= len(series):
        return None, None
    px1 = float(series.iloc[j])
    if px1 <= 0:
        return None, None
    return (px1 / px0 - 1.0) * 100.0, series.index[j]


def _elapsed(as_of, horizon, today=None):
    """Has this horizon finished, with slack for weekends and holidays?"""
    today = today or dt.date.today()
    try:
        d = dt.date.fromisoformat(str(as_of)[:10])
    except Exception:
        return False
    return (today - d).days >= int(horizon * CALENDAR_SLACK) + 2


def run(horizons=HORIZONS, limit_symbols=None, today=None):
    """
    Fill every forward return that can now be computed.

    Returns a summary rather than logging into the void, because this runs
    unattended and the only evidence it worked is what it hands back.
    """
    if pd is None:
        return {"ok": False, "error": "pandas unavailable"}

    if not _lock.acquire(blocking=False):
        return {"ok": False, "error": "a labelling run is already in progress"}

    try:
        pit_store.init_db()
        today = today or dt.date.today()

        # One work list across all horizons, so each symbol's history is
        # fetched once no matter how many dates and horizons need it.
        wanted = {}
        for h in horizons:
            for as_of, sym in pit_store.unlabelled(h):
                if not _elapsed(as_of, h, today):
                    continue
                wanted.setdefault(sym, []).append((as_of, h))

        if not wanted:
            return {"ok": True, "symbols": 0, "written": 0,
                    "message": "Nothing is ready to label yet."}

        bench = _history(BENCHMARK)
        if bench is None:
            return {"ok": False, "error": f"benchmark {BENCHMARK} unavailable — "
                                          "labels without it would be returns, not alpha"}

        symbols = sorted(wanted)
        if limit_symbols:
            symbols = symbols[:int(limit_symbols)]

        written, skipped, missing = 0, 0, 0
        for sym in symbols:
            series = _history(sym)
            if series is None:
                missing += 1
                continue
            for as_of, h in wanted[sym]:
                ret, end = _forward(series, as_of, h)
                if ret is None:
                    skipped += 1
                    continue
                # The benchmark is measured between the SAME two dates the
                # stock was measured between, not over its own bar count —
                # otherwise a symbol that did not trade on some days is
                # compared against a longer window than it actually had.
                b0, _ = _at_or_before(bench, as_of)
                b1, _ = _at_or_before(bench, end)
                bret = ((b1 / b0 - 1.0) * 100.0) if (b0 and b1 and b0 > 0) else None
                pit_store.record_forward_return(as_of, sym, h, round(ret, 4),
                                                round(bret, 4) if bret is not None else None)
                written += 1

        return {"ok": True, "symbols": len(symbols), "written": written,
                "skipped_not_ready": skipped, "no_history": missing,
                "horizons": list(horizons), "benchmark": BENCHMARK,
                "counts": pit_store.label_counts()}
    finally:
        _lock.release()


def status():
    try:
        pit_store.init_db()
        return {"ok": True, "counts": pit_store.label_counts(),
                "horizons": list(HORIZONS), "benchmark": BENCHMARK}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {str(e)[:120]}"}
