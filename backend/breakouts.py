"""
Altaha Screener — Breakout alerts

WHAT THIS IS FOR
----------------
The live scanner in intraday.py answers "is something unusual trading right
now?" — sudden volume. This module answers the question most people actually
mean by an alert: "has this stock just left a long sideways range, or cleared
its 52-week high?" — and sends it to Telegram the moment it happens.

TWO PASSES, ONE SET OF LEVELS
-----------------------------
1. After the close. The 16:50 IST universe scan (scan.phase1) already holds a
   year and more of daily bars for every liquid stock, one at a time.
   read_daily() measures each frame while it is in hand, so this costs no
   extra data call. ingest() then
     - lists the CONFIRMED breakouts: a close above the top of a base (or a
       52-week high) on at least BO_VOL_EOD times the usual volume;
     - marks each of today's live alerts as held (closed above its level) or
       faded (closed back under it);
     - builds the WATCH list for the next session: stocks still inside a base,
       or under a 52-week high set 20+ sessions ago, within BO_NEAR_PCT of the
       top;
     - sends one Telegram summary.

2. During the session. intraday.scan_once() pulls one bulk quote a minute.
   The watch list rides on that same request (one Dhan call carries up to
   900 symbols), and check_live() fires when the price clears the level by
   BO_BUFFER_PCT with the day's volume running at BO_VOL_PACE times a normal
   day's pace or better. One alert per stock per day.

WHAT COUNTS AS A BASE
---------------------
The longest stretch of daily bars, 40 to 250 sessions, whose high-to-low
range fits inside
    18% when the stretch is under 120 sessions (the Breakouts list's rule), or
    25% when it is 120 sessions or longer (a long consolidation is allowed to
        be a little looser),
and whose older half already reached near the top (within 35% of the range's
height). That last test is what separates a sideways range from a slow
uptrend: a stock climbing steadily fits an 18% box too, but its older half
never got near today's high. The trigger is the high of the whole stretch.

Every threshold is an environment variable, so it can be tuned on Render
without a redeploy.
"""

import datetime as dt
import json
import os
import threading

import numpy as np

try:
    import alerts as notify
except Exception:          # pragma: no cover - the module still measures
    notify = None


def _f(name, default):
    try:
        return float(os.environ.get(name, "").strip() or default)
    except ValueError:
        return default


def _i(name, default):
    try:
        return int(float(os.environ.get(name, "").strip() or default))
    except ValueError:
        return default


def _b(name, default):
    v = os.environ.get(name, "").strip().lower()
    if not v:
        return default
    return v in ("1", "true", "yes", "on")


ENABLED = _b("BREAKOUT_ALERTS", True)
MIN_SESSIONS = _i("BO_MIN_SESSIONS", 40)        # shortest base
MAX_WIDTH = _f("BO_MAX_WIDTH", 0.18)            # its widest range, high over low less one
LONG_SESSIONS = _i("BO_LONG_SESSIONS", 120)     # from here a base is "long"
LONG_MAX_WIDTH = _f("BO_LONG_MAX_WIDTH", 0.25)  # and may be this wide
MAX_SESSIONS = _i("BO_MAX_SESSIONS", 250)       # longest base looked for
TOP_TEST = _f("BO_TOP_TEST", 0.35)              # older half must reach within this share of the range
HIGH_WINDOW = 252                               # a year of sessions
HIGH_QUIET = _i("BO_HIGH_QUIET", 20)            # the 52-week high must be at least this old
VOL_EOD = _f("BO_VOL_EOD", 2.0)                 # breakout-day volume over the 50-day median
VOL_PACE = _f("BO_VOL_PACE", 1.5)               # live: day volume over a normal day's pace
BUFFER_PCT = _f("BO_BUFFER_PCT", 0.2)           # clear the level by this much, live
NEAR_PCT = _f("BO_NEAR_PCT", 5.0)               # watch stocks this close to the top
MAX_WATCH = _i("BO_MAX_WATCH", 400)
MAX_ALERTS_DAY = _i("BO_MAX_ALERTS_DAY", 20)
START_MIN = _i("BO_START_MIN", 10)              # 09:25 — after the opening auction settles
END_MIN = _i("BO_END_MIN", 370)                 # 15:25
MIN_PRICE = _f("BO_MIN_PRICE", 20.0)
STALE_DAYS = _i("BO_STALE_DAYS", 6)             # a watch list older than this is not used
EXIT_PCT = 8.0                                  # the Breakouts list's tested exit line
MIN_SCAN = _i("BO_MIN_SCAN", 150)               # a scan smaller than this does not replace the list

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("DATA_DIR", "").strip() or HERE
try:
    os.makedirs(DATA_DIR, exist_ok=True)
except Exception:
    DATA_DIR = HERE
FEED_FILE = os.path.join(DATA_DIR, "breakout_feed.json")
LOG_FILE = os.path.join(DATA_DIR, "breakout_log.json")

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))

KIND_LABEL = {"BASE": "Base breakout", "HIGH52": "52-week high"}

# A normal NSE session's cumulative share of the day's volume by minutes after
# 09:15. Volume is U-shaped — heavy at the open and into the close — so a
# straight line would make every morning look like a volume surge. This is a
# generic shape, not this stock's own; it only has to keep the live pace
# honest to within a few tenths.
_CURVE = ((0, 0.0), (15, 0.10), (30, 0.16), (60, 0.26), (120, 0.42), (180, 0.54),
          (240, 0.65), (300, 0.77), (345, 0.87), (375, 1.0))

_lock = threading.Lock()
_mem = {"feed": None, "log": None, "pending": {}}


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------

def now_ist():
    return dt.datetime.now(IST)


def _mso(t):
    return (t.hour * 60 + t.minute) - 555


def session_live(t=None):
    """True between 09:15 and 15:30 IST on a weekday: today's daily bar, if a
    feed returns one, is still forming."""
    t = t or now_ist()
    return t.weekday() < 5 and 0 <= _mso(t) < 375


def day_fraction(mso):
    """Share of a normal day's volume traded by `mso` minutes after the open."""
    if mso <= 0:
        return 0.0
    for (m0, f0), (m1, f1) in zip(_CURVE, _CURVE[1:]):
        if mso <= m1:
            return f0 + (f1 - f0) * (mso - m0) / (m1 - m0)
    return 1.0


# ---------------------------------------------------------------------------
# Measuring one stock's daily bars
# ---------------------------------------------------------------------------

def _arrays(df):
    c = np.asarray(df["Close"], dtype=float)
    h = np.asarray(df["High"], dtype=float) if "High" in df.columns else c.copy()
    low = np.asarray(df["Low"], dtype=float) if "Low" in df.columns else c.copy()
    v = np.asarray(df["Volume"], dtype=float) if "Volume" in df.columns else np.zeros(len(c))
    h = np.where(np.isfinite(h), h, c)
    low = np.where(np.isfinite(low), low, c)
    v = np.where(np.isfinite(v), v, 0.0)
    return h, low, c, v


def find_base(h, low, end):
    """
    The longest consolidation in bars [end - N, end), or None.

    Returns {"sessions", "top", "low", "width", "top_age"}: `top` is the
    highest high of the stretch — the level a breakout has to clear — and
    `top_age` how many sessions ago it was last touched.
    """
    hi_n = min(MAX_SESSIONS, end)
    if hi_n < MIN_SESSIONS:
        return None
    hh = h[end - hi_n:end][::-1]               # most recent first
    ll = low[end - hi_n:end][::-1]
    rmax = np.maximum.accumulate(hh)           # rmax[k]: high of the last k+1 bars
    rmin = np.minimum.accumulate(ll)
    with np.errstate(divide="ignore", invalid="ignore"):
        width = np.where(rmin > 0, rmax / rmin - 1.0, np.inf)
    lengths = np.arange(1, hi_n + 1)
    cap = np.where(lengths >= LONG_SESSIONS, LONG_MAX_WIDTH, MAX_WIDTH)
    ok = (lengths >= MIN_SESSIONS) & (width <= cap)
    # Longest first; the first one whose older half reached the top is the
    # base. A stretch that only fits because the stock climbed steadily
    # through it is a trend, and is skipped.
    for k in np.nonzero(ok)[0][::-1]:
        n = int(k) + 1
        top, bot = float(rmax[k]), float(rmin[k])
        older = hh[n // 2:n]
        if older.size and float(older.max()) < top - TOP_TEST * (top - bot):
            continue
        return {"sessions": n, "top": top, "low": bot, "width": float(width[k]),
                "top_age": int(np.argmax(hh[:n] >= top))}
    return None


def find_high(h, end):
    """The 52-week high over bars before `end`, and how many sessions ago it
    was last touched. None for a stock with under six months of history."""
    start = max(0, end - HIGH_WINDOW)
    win = h[start:end]
    if win.size < 120:
        return None
    level = float(win.max())
    age = int(np.argmax(win[::-1] >= level))
    return {"level": level, "age": age}


def _date(idx):
    try:
        return idx.date().isoformat() if hasattr(idx, "date") else str(idx)[:10]
    except Exception:
        return str(idx)[:10]


def read_daily(df, drop_partial=None, today=None):
    """
    Everything the breakout alerts need from one stock's daily bars, or None.

    Small on purpose — it is kept for every liquid stock while the scan runs:
      asof, close, prev_close, rel_volume (last bar over the 50 before it),
      vol_med50 (for tomorrow's live pace), fresh (a breakout ON the last
      bar), watch (a setup for the NEXT session).

    `drop_partial` drops a last bar dated today while the session is still
    open, so a mid-day scan never measures a half-formed candle.
    """
    try:
        frame = df.dropna(subset=["Close"])
    except Exception:
        return None
    if frame is None or len(frame) < MIN_SESSIONS + 11:
        return None
    if drop_partial is None:
        drop_partial = session_live()
    today = today or now_ist().date().isoformat()
    if drop_partial and _date(frame.index[-1]) == today:
        frame = frame.iloc[:-1]
    frame = frame.iloc[-(max(MAX_SESSIONS, HIGH_WINDOW) + 2):]
    n = len(frame)
    if n < MIN_SESSIONS + 11:
        return None
    h, low, c, v = _arrays(frame)
    price, prev = float(c[-1]), float(c[-2])
    if not (np.isfinite(price) and price >= MIN_PRICE and prev > 0):
        return None

    before = v[max(0, n - 51):n - 1]
    med_before = float(np.median(before)) if before.size >= 20 else 0.0
    rel = float(v[-1] / med_before) if med_before > 0 else None
    med_now = float(np.median(v[-50:])) if n >= 30 else 0.0

    out = {"asof": _date(frame.index[-1]), "close": round(price, 2), "prev_close": round(prev, 2),
           "move_pct": round((price / prev - 1) * 100, 2),
           "rel_volume": round(rel, 2) if rel is not None else None,
           "vol_med50": round(med_now), "fresh": None, "watch": None}

    # 1. Did the last bar break out? The base is measured on the bars before it.
    base = find_base(h, low, n - 1)
    high = find_high(h, n - 1)
    fresh = None
    if base and price > base["top"]:
        fresh = {"kind": "BASE", "level": round(base["top"], 2), "base_low": round(base["low"], 2),
                 "sessions": base["sessions"], "width_pct": round(base["width"] * 100, 1)}
        if high:
            fresh["high52"] = round(high["level"], 2)
    elif high and price > high["level"] and high["age"] >= HIGH_QUIET:
        fresh = {"kind": "HIGH52", "level": round(high["level"], 2), "high_age": high["age"]}
    if fresh:
        fresh["above_pct"] = round((price / fresh["level"] - 1) * 100, 2)
        out["fresh"] = fresh
        return out          # broke out today: tomorrow is follow-through, not a breakout

    # 2. The setup for the next session, measured through the last bar.
    base = find_base(h, low, n)
    high = find_high(h, n)
    watch = None
    if base:
        watch = {"kind": "BASE", "level": round(base["top"], 2), "base_low": round(base["low"], 2),
                 "sessions": base["sessions"], "width_pct": round(base["width"] * 100, 1)}
        if high:
            # Equal to the level: clearing the base is also a 52-week high.
            # Above it: the overhead the breakout still has to get through.
            watch["high52"] = round(high["level"], 2)
    elif high and high["age"] >= HIGH_QUIET:
        watch = {"kind": "HIGH52", "level": round(high["level"], 2), "high_age": high["age"]}
    if watch:
        to_top = (watch["level"] / price - 1) * 100
        if 0 <= to_top <= NEAR_PCT:
            watch["to_top_pct"] = round(to_top, 2)
            out["watch"] = watch
    return out


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

def _read_json(path, default):
    try:
        with open(path) as fh:
            return json.load(fh)
    except Exception:
        return default


def _write_json(path, blob):
    tmp = path + ".tmp"
    try:
        with open(tmp, "w") as fh:
            json.dump(blob, fh)
        os.replace(tmp, path)
    except Exception:
        pass


def _feed():
    if _mem["feed"] is None:
        _mem["feed"] = _read_json(FEED_FILE, {}) or {}
    return _mem["feed"]


def _log():
    if _mem["log"] is None:
        rows = _read_json(LOG_FILE, [])
        _mem["log"] = rows if isinstance(rows, list) else []
    return _mem["log"]


def _save_log():
    _write_json(LOG_FILE, _log()[-600:])


def _feed_usable(feed, today):
    asof = feed.get("asof")
    if not asof or not feed.get("watch"):
        return False
    try:
        age = (dt.date.fromisoformat(today) - dt.date.fromisoformat(asof)).days
    except Exception:
        return False
    # The list describes the session after `asof`. Built today from today's
    # close, it is for tomorrow; built a week ago, its levels are stale.
    return 0 < age <= STALE_DAYS


# ---------------------------------------------------------------------------
# After the close
# ---------------------------------------------------------------------------

def _order_fresh(r):
    return (0 if r["kind"] == "BASE" else 1, -(r.get("sessions") or 0), -(r.get("rel_volume") or 0))


def ingest(reads, meta=None, now=None, send=True):
    """
    Turn one scan's reads into the confirmed list, tomorrow's watch list and
    the outcome of today's live alerts. `reads` is {SYMBOL: read_daily()}.
    Returns the feed. A scan too small to be the whole market leaves the
    stored list alone and returns None.
    """
    reads = {s: r for s, r in (reads or {}).items() if r}
    if len(reads) < MIN_SCAN:
        return None
    meta = meta or {}
    now = now or now_ist()
    dates = {}
    for r in reads.values():
        dates[r["asof"]] = dates.get(r["asof"], 0) + 1
    asof = max(dates, key=lambda d: (dates[d], d))

    def card(sym, r, part):
        m = meta.get(sym) or {}
        row = dict(r[part], symbol=sym, close=r["close"], move_pct=r["move_pct"],
                   rel_volume=r["rel_volume"], vol_med50=r["vol_med50"])
        if m.get("sector"):
            row["sector"] = m["sector"]
        if m.get("leader") is not None:
            row["leader"] = m["leader"]
        return row

    fresh, light, watch = [], [], []
    for sym, r in reads.items():
        if r["asof"] != asof:
            continue
        if r.get("fresh"):
            row = card(sym, r, "fresh")
            (fresh if (r.get("rel_volume") or 0) >= VOL_EOD else light).append(row)
        elif r.get("watch"):
            watch.append(card(sym, r, "watch"))
    fresh.sort(key=_order_fresh)
    light.sort(key=_order_fresh)
    watch.sort(key=lambda w: (w["to_top_pct"], 0 if w["kind"] == "BASE" else 1, w["symbol"]))
    watch = watch[:MAX_WATCH]

    with _lock:
        old = _feed()
        feed = {"asof": asof, "built_at": now.isoformat(timespec="minutes"),
                "universe": len(reads), "fresh": fresh, "light": light, "watch": watch,
                "eod_sent": old.get("eod_sent") if old.get("asof") == asof else None}
        # Live alerts from the session this scan closed: did they hold?
        held, faded = [], []
        for a in _log():
            if a.get("date") != asof or a.get("eod"):
                continue
            r = reads.get(a["symbol"])
            if not r:
                continue
            a["eod_close"] = r["close"]
            a["eod_rel_volume"] = r.get("rel_volume")
            a["eod"] = "held" if r["close"] >= a["level"] else "faded"
            (held if a["eod"] == "held" else faded).append(a)
        _save_log()
        complete = asof == now.date().isoformat() and not session_live(now) and _mso(now) >= 375
        due = send and complete and feed["eod_sent"] != asof
        if due:
            feed["eod_sent"] = asof
        _mem["feed"] = feed
        _write_json(FEED_FILE, feed)

    if due and notify is not None:
        try:
            notify.send_plain(notify.format_breakout_close(
                asof, fresh, light, held, faded, watch, vol_eod=VOL_EOD, near_pct=NEAR_PCT))
        except Exception:
            pass
    return feed


# ---------------------------------------------------------------------------
# During the session
# ---------------------------------------------------------------------------

def watch_symbols(now=None):
    """Symbols the live loop should add to its quote request."""
    if not ENABLED:
        return []
    now = now or now_ist()
    feed = _feed()
    if not _feed_usable(feed, now.date().isoformat()):
        return []
    return [w["symbol"] for w in feed["watch"]]


def check_live(snap, now=None, index_pct=None, send=True):
    """
    One pass over the watch list against a bulk quote snapshot. Returns the
    alerts that fired. Safe to call from two threads at once (the scanner
    loop and the cron tick both run passes): the fired set is checked and
    written under one lock, so a stock can only alert once a day.
    """
    if not ENABLED or not snap:
        return []
    now = now or now_ist()
    today = now.date().isoformat()
    feed = _feed()
    if not _feed_usable(feed, today):
        return []
    mso = _mso(now)
    if mso < START_MIN or mso > END_MIN or now.weekday() >= 5:
        return []
    expected_share = max(day_fraction(mso), 0.06)

    fired = []
    with _lock:
        log = _log()
        todays = [a for a in log if a.get("date") == today]
        done = {a["symbol"] for a in todays}
        room = MAX_ALERTS_DAY - len(todays)
        pending = {}
        for w in feed["watch"]:
            sym = w["symbol"]
            q = snap.get(sym)
            if not q or sym in done:
                continue
            try:
                px = float(q.get("ltp") or 0)
                cum = float(q.get("volume") or 0)
                pc = float(q.get("prev_close") or 0)
            except (TypeError, ValueError):
                continue
            level = float(w["level"])
            if px <= 0:
                continue
            # Already above the level before today opened: the list is a day
            # behind (a missed scan) and this is not a fresh breakout.
            if pc and pc > level:
                continue
            if px < level * (1 + BUFFER_PCT / 100.0):
                continue
            med = float(w.get("vol_med50") or 0)
            pace = cum / (med * expected_share) if med > 0 and cum > 0 else None
            if pace is None or pace < VOL_PACE:
                pending[sym] = {"symbol": sym, "kind": w["kind"], "level": level, "price": round(px, 2),
                                "pace": round(pace, 2) if pace is not None else None}
                continue
            a = {
                "date": today, "time": now.strftime("%H:%M"), "symbol": sym, "kind": w["kind"],
                "level": round(level, 2), "price": round(px, 2),
                "above_pct": round((px / level - 1) * 100, 2),
                "move_pct": round((px / pc - 1) * 100, 2) if pc else None,
                "pace": round(pace, 1), "volume": int(cum),
                "sessions": w.get("sessions"), "width_pct": w.get("width_pct"),
                "base_low": w.get("base_low"), "high_age": w.get("high_age"),
                "high52": w.get("high52"), "sector": w.get("sector"), "leader": w.get("leader"),
                "exit": round(px * (1 - EXIT_PCT / 100.0), 2),
                "measured_move": (round(level + (level - w["base_low"]), 2)
                                  if w.get("base_low") else None),
                "index_pct": index_pct, "eod": None,
            }
            fired.append(a)
        fired.sort(key=lambda a: (0 if a["kind"] == "BASE" else 1, -(a.get("sessions") or 0), -a["pace"]))
        fired = fired[:max(room, 0)]
        if fired:
            log.extend(fired)
            _save_log()
        _mem["pending"] = pending

    if fired and send and notify is not None:
        try:
            notify.send_breakouts(fired, clock=now.strftime("%H:%M"), index_pct=index_pct,
                                  total_today=len(todays) + len(fired))
        except Exception:
            pass
    return fired


# ---------------------------------------------------------------------------
# What the page reads
# ---------------------------------------------------------------------------

def rules():
    return {
        "base": (f"{MIN_SESSIONS}+ sessions inside a {MAX_WIDTH * 100:.0f}% range, or "
                 f"{LONG_SESSIONS}+ sessions inside {LONG_MAX_WIDTH * 100:.0f}%"),
        "high52": f"a 52-week high set at least {HIGH_QUIET} sessions ago",
        "live": (f"price {BUFFER_PCT:g}% over the level with volume at {VOL_PACE:g}x "
                 "a normal day's pace, 09:25 to 15:25"),
        "close": f"a close over the level on {VOL_EOD:g}x the usual volume",
        "watch": f"stocks within {NEAR_PCT:g}% of the level",
        "cap": f"{MAX_ALERTS_DAY} live alerts a day, one per stock",
    }


def status(now=None):
    now = now or now_ist()
    today = now.date().isoformat()
    feed = _feed()
    log = _log()
    todays = [a for a in log if a.get("date") == today][::-1]
    judged = [a for a in log if a.get("eod") in ("held", "faded")]
    recent = judged[-60:]
    return {
        "enabled": ENABLED,
        "asof": feed.get("asof"),
        "built_at": feed.get("built_at"),
        "universe": feed.get("universe"),
        "watch_usable": _feed_usable(feed, today),
        "watch_count": len(feed.get("watch") or []),
        "near": (feed.get("watch") or [])[:15],
        "fresh": (feed.get("fresh") or [])[:25],
        "light": (feed.get("light") or [])[:8],
        "today": todays,
        "pending": sorted(_mem["pending"].values(), key=lambda p: -(p.get("pace") or 0))[:10],
        "record": {"held": sum(1 for a in recent if a["eod"] == "held"),
                   "faded": sum(1 for a in recent if a["eod"] == "faded"),
                   "of_last": len(recent)},
        "rules": rules(),
        "session_live": session_live(now),
        "telegram": notify.health() if notify is not None else {"configured": False},
    }


def sample():
    """A made-up live alert, for the Telegram test."""
    return {"date": "", "time": "10:42", "symbol": "TESTMSG", "kind": "BASE", "level": 412.50,
            "price": 418.20, "above_pct": 1.38, "move_pct": 2.31, "pace": 2.1, "volume": 0,
            "sessions": 64, "width_pct": 14.0, "base_low": 362.00, "high52": 430.00,
            "sector": "Power", "leader": 72.0, "exit": 384.74, "measured_move": 463.00,
            "index_pct": 0.35, "eod": None}
