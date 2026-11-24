"""
Altaha Screener — the last settled sessions, kept

WHY THIS EXISTS
On the night of Monday 23 November 2026 the site went back a day at midnight.
Until 23:57 IST the Nifty's last daily bar was Monday's, 25,349.65, down
1.75%. From 00:07 it was Friday's: /market read "NIFTY 50 25800.6, +1.12%",
Friday's close and Friday's move, and went on reading that until the morning.

The index feed does this itself. After midnight in India, Yahoo's daily
history for an Indian symbol ends on the session BEFORE the one that just
closed, whatever period is asked for, and the missing bar comes back some
hours later. The price cache lasts thirty minutes, so the first refetch after
midnight replaced a frame that ended on Monday with one that ended on Friday,
and the shorter frame was served.

WHAT THIS DOES
Remembers the last few settled sessions of every history it is shown, and puts
back any of them a later frame from the feed has lost. data_source.resolve
passes every frame it fetches through keep(), so the Market page, a stock
page and the chart all read a series that never goes back a session.

  · Settled means the session has closed: a bar dated before today, or today's
    from 16:00 IST, when the closing price is in. A bar still forming is never
    kept, so a morning's price cannot be put back as that day's close.
  · The feed always wins on a session it carries. A kept bar is only ever
    added on a date the frame does not have, so a correction (same date,
    different close) replaces what was kept.
  · A kept bar is trusted for TRUST_DAYS. After that the feed is believed:
    if it still has no bar for that date, there was none.
  · A bar dated on a weekend or a trading holiday is not kept. A feed that
    shows one and then withdraws it was right to withdraw it.
  · Kept on the data disk as well as in memory, so a deploy or a restart
    during the gap does not lose the session the feed has dropped.

Only histories in exchange time (Dhan's, and Yahoo's for an Indian symbol)
are kept. "Settled by 16:00 IST" says nothing about a New York bar.
"""

import datetime as dt
import json
import math
import os
import threading

import pandas as pd

import market_calendar

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
SETTLED_MIN = 16 * 60      # the closing price is in by 16:00 (data_source)
KEEP = 3                   # settled sessions remembered per symbol
# How long a kept bar may stand in for the feed, in calendar days from its
# session. The feed was seen to lose a session at midnight and have it back
# by late the next morning. The longest it can go without a new session to
# show is a three-day weekend, and a bar from Thursday is four days old on
# the Monday morning after a Friday holiday. Past that the gap is not the
# feed running late.
TRUST_DAYS = 4
MAX_SYMBOLS = 800          # bounded for a 512 MB instance; about 200 KB on disk
COLS = ("Open", "High", "Low", "Close", "Volume")

_PATH = os.path.join(os.environ.get("DATA_DIR", "").strip()
                     or os.path.dirname(os.path.abspath(__file__)), "settled_bars.json")
_mem = {"bars": None}      # {SYMBOL: [[ISO date, open, high, low, close, volume], ...]}
_lock = threading.Lock()


def _now():
    """The clock, in IST. A function so a test can set the hour."""
    return dt.datetime.now(IST)


def _well_formed(rows) -> bool:
    try:
        return all(len(r) == 1 + len(COLS) and dt.date.fromisoformat(r[0]) for r in rows)
    except (TypeError, ValueError):
        return False


def _bars() -> dict:
    if _mem["bars"] is None:
        try:
            with open(_PATH) as fh:
                blob = json.load(fh)
            # Read strictly. A row this code cannot use is dropped here, once,
            # so it cannot fail every later fetch of its symbol.
            _mem["bars"] = {str(sym): rows for sym, rows in blob["bars"].items()
                            if isinstance(rows, list) and _well_formed(rows)}
        except Exception:
            _mem["bars"] = {}
    return _mem["bars"]


def _save(today):
    """Write the memory to the data disk. Symbols whose newest bar is past
    trusting are dropped first: they can no longer put anything back."""
    bars = _bars()
    floor = (today - dt.timedelta(days=TRUST_DAYS)).isoformat()
    for sym in [s for s, rows in bars.items() if not rows or rows[-1][0] < floor]:
        bars.pop(sym, None)
    for sym in list(bars)[: max(0, len(bars) - MAX_SYMBOLS)]:      # oldest written first
        bars.pop(sym, None)
    try:
        tmp = _PATH + ".tmp"
        with open(tmp, "w") as fh:
            json.dump({"bars": bars}, fh)
        os.replace(tmp, _PATH)
    except Exception:
        pass


def _f(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def settled_through(now):
    """The newest date whose bar is final at `now`: today from 16:00 IST,
    otherwise yesterday."""
    n = now.astimezone(IST)
    late = n.hour * 60 + n.minute >= SETTLED_MIN
    return n.date() if late else n.date() - dt.timedelta(days=1)


def _in_exchange_time(frame) -> bool:
    """A daily history dated in India: Dhan's (no zone) or Yahoo's for an
    Indian symbol (Asia/Kolkata)."""
    if not isinstance(frame, pd.DataFrame) or "Close" not in frame.columns or not len(frame):
        return False
    if not isinstance(frame.index, pd.DatetimeIndex):
        return False
    if frame.index.tz is None:
        return True
    return frame.index[-1].utcoffset() == dt.timedelta(hours=5, minutes=30)


def _settled_rows(frame, final) -> list:
    """The last KEEP settled sessions of `frame`, oldest first."""
    cols = [frame[c] if c in frame.columns else None for c in COLS]
    dates = frame.index.date
    rows = []
    for i in range(len(frame) - 1, -1, -1):
        day = dates[i]
        if day > final or not market_calendar.trading_day(day):
            continue
        vals = [None if c is None else _f(c.iloc[i]) for c in cols]
        if not vals[3] or vals[3] <= 0:
            continue
        rows.append([day.isoformat()] + vals)
        if len(rows) == KEEP:
            break
    return rows[::-1]


def _put_back(frame, rows):
    """`frame` with the kept `rows` added on their dates, in date order."""
    tz = frame.index.tz
    stamps = [pd.Timestamp(r[0]) if tz is None else pd.Timestamp(r[0], tz=tz) for r in rows]
    add = pd.DataFrame(0.0, index=pd.DatetimeIndex(stamps).astype(frame.index.dtype),
                       columns=frame.columns)
    for i, col in enumerate(COLS, start=1):
        if col in add.columns:
            add[col] = [float("nan") if r[i] is None else r[i] for r in rows]
    if "Adj Close" in add.columns:
        add["Adj Close"] = add["Close"]
    try:
        add = add.astype(frame.dtypes.to_dict())
    except (TypeError, ValueError):
        pass
    out = pd.concat([frame, add]).sort_index()
    out.index.name = frame.index.name
    out.attrs = dict(frame.attrs)
    out.attrs["kept_sessions"] = [r[0] for r in rows]
    return out


def keep(symbol: str, frame, now=None):
    """
    `frame` with any settled session the feed has dropped put back, and the
    newest settled sessions it carries remembered for next time.

    A frame with sessions put back says which in attrs["kept_sessions"]. If
    it arrived marked `today_missing` (dhan_source: today's bar was owed and
    the quote did not come) and today's bar is one of them, the mark is
    cleared: the frame is whole, and is cached as one.

    Never raises: the memory is a safeguard, and a fault in it must not cost
    the reader the price.
    """
    try:
        if not _in_exchange_time(frame):
            return frame
        now = (now or _now()).astimezone(IST)
        today = now.date()
        with _lock:
            bars = _bars()
            tail = bars.get(symbol) or []
            have = {d.isoformat() for d in frame.index.date}
            first = min(have)
            # A kept bar goes back on a date the feed does not carry, inside
            # the frame's span, while it is young enough to trust. The holiday
            # list is asked again here: it may have been read since the bar
            # was kept.
            back = [r for r in tail
                    if r[0] not in have and r[0] > first
                    and (today - dt.date.fromisoformat(r[0])).days <= TRUST_DAYS
                    and market_calendar.trading_day(dt.date.fromisoformat(r[0]))]
            if back:
                frame = _put_back(frame, back)
                if today.isoformat() in frame.attrs["kept_sessions"]:
                    frame.attrs.pop("today_missing", None)
            newest = _settled_rows(frame, settled_through(now))
            if newest and newest != tail:
                bars.pop(symbol, None)          # re-added last: the bound drops the oldest
                bars[symbol] = newest
                _save(today)
        return frame
    except Exception:
        return frame
