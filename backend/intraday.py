"""
Altaha Screener — Live Intraday Scanner  (v24)

WHAT CHANGED IN v24 AND WHY
---------------------------
1. TWO LANES, ONE QUOTE. breakouts.py runs two engines on the same 20-second
   bulk quote: Classic (the calls the owner likes, unchanged) and ★ Select
   (fewer, stricter calls spread through the day). Every alert says which
   (`engine`; an old row without one is Classic). MAX_ALERTS_DAY caps Classic
   and the legacy volume alerts only — Select keeps its own budget inside
   breakouts.py. When both lanes call one break the owner gets ONE full card
   (Select's, when they land together; a short "★ Select confirms" line when
   Select follows a Classic call) and the public channel gets one post.

2. LIVE TRACKING. Each pass, before new calls are looked for, every open call
   of the day is marked to the last traded price: profit or loss in percent
   and in risks, its best and worst point since entry, whether the half-book
   level traded, whether the stop loss or the target did. From the last price
   only — never the quote's day high or low, which can be from before the
   call. `outcome` stays the verdict mark_outcomes() takes from 5-minute
   candles after the close; the tracker only ever writes `live_*` fields.

3. THE LOG NO LONGER FORGETS. It kept the last 800 rows and was rewritten in
   place, so a crash mid-write left half a file, which the next start read as
   no history at all. It is now written whole or not at all (a temporary file,
   then a rename), keeps ALERT_HOT_DAYS of rows, and moves older rows — once —
   to an append-only archive that the record still counts.

4. THE SLOW WORK LEFT THE PASS. Per-stock volume profiles, an opening range a
   restart missed, and the sectors' money-flow quadrants need a Dhan call per
   stock (or a database read). They run in background threads started from
   the loop, never inside scan_once(), whose only Dhan call is still the one
   bulk quote.

WHAT CHANGED FROM v22 AND WHY
-----------------------------
1. THE BUG THAT KILLED EVERY ALERT.
   Quotes were pulled with mode="ohlc". Dhan's /marketfeed/ohlc response
   contains last_price and ohlc{open,high,low,close} and nothing else — there
   is no volume field on that endpoint. Every signal in this file is gated on
   volume, so detect() hit `if not vol: return []` for every symbol, on every
   pass, forever. Zero alerts was never a threshold problem. Volume only
   exists on /marketfeed/quote, so this file now asks for mode="quote".

2. ROLLING RVOL, NOT CUMULATIVE RVOL.
   The old RVOL compared the whole day's cumulative volume against the whole
   day's expected cumulative. By 14:00 a genuine spike is diluted by six hours
   of ordinary trading, so real afternoon events could not clear 2.5x. The
   trigger is now volume traded in the LAST ~5 MINUTES versus what this stock
   normally trades in that same window. Cumulative RVOL is kept as context
   (day_rvol), not as the trigger.

3. QUALITY GATES. Volume alone fires on panic dumps and dead-cat pops. Longs
   now also require price above VWAP, price high in the day's range, risk
   inside MAX_RISK_PCT and R:R above MIN_RR.

4. REGIME FILTER. Breakouts fail far more often while the index is falling.
   NIFTYBEES is used as a cheap proxy — it lives in NSE_EQ, so it rides along
   on the same bulk call at no extra request cost.

5. INCREMENTAL WARM-UP. ensure_profiles() used to build 200 volume profiles
   and 200 level sets in one blocking, unthrottled burst against an API capped
   at 5 requests/second. It got rate-limited, returned nothing, and because the
   retry guard only skipped when profiles was non-empty, it repeated the same
   failed 400-call burst every 60 seconds for the rest of the day. Warm-up is
   now batched, cached to disk, and gives up on repeatedly failing symbols.

6. NOISE CONTROL AND VISIBILITY. Cooldown instead of once-per-day-forever, a
   daily cap, a ranked digest instead of one message per alert, a heartbeat,
   and diagnose() so silence is explainable without reading logs.
"""

import datetime as dt
import functools
import inspect
import json
import os
import threading
import time
from collections import deque

import numpy as np

try:
    import dhan_source as dhan
except Exception:
    dhan = None

from levels import compute_levels

try:
    import alerts as notify
except Exception:
    notify = None

try:
    import announcements as ann
except Exception:
    ann = None

# Breakout alerts ride on this loop's quote request: the watch list built after
# the close is added to the same bulk call, so they cost no extra request.
try:
    import breakouts
except Exception:
    breakouts = None


# ---------------------------------------------------------------------------
# Configuration — every number is env-overridable, so thresholds can be tuned
# on Render without a redeploy.
# ---------------------------------------------------------------------------

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


HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("DATA_DIR", "").strip() or HERE
try:
    os.makedirs(DATA_DIR, exist_ok=True)
except Exception:
    DATA_DIR = HERE

LOG_FILE = os.path.join(DATA_DIR, "signal_log.json")
# Rows older than ALERT_HOT_DAYS, one JSON object per line, append-only.
# Empty means "next to LOG_FILE": signal_log_archive.jsonl, so the archive
# always travels with the log it came from.
ARCHIVE_FILE = ""
PROFILE_FILE = os.path.join(DATA_DIR, "vol_profiles.json")
PROFILE_VERSION = 2                         # 2: keyed by bar END (see build_profile)

RVOL_MIN = _f("RVOL_MIN", 3.0)             # rolling-window spike threshold
RVOL_CONFIRM = _f("RVOL_CONFIRM", 1.8)     # confirmation floor for breaks
LEVEL_MIN_STRENGTH = _i("LEVEL_MIN_STRENGTH", 70)
# 20 seconds, not 60: a breakout alert that arrives a minute late is an entry
# a minute worse. One bulk quote per pass is far inside Dhan's 1 request/second.
POLL_SECONDS = _i("POLL_SECONDS", 20)
MIN_PRICE = _f("MIN_PRICE", 30.0)
MAX_RISK_PCT = _f("MAX_RISK_PCT", 2.5)     # skip setups whose stop is far away
MIN_RR = _f("MIN_RR", 1.5)
MIN_RANGE_POS = _f("MIN_RANGE_POS", 0.60)  # longs must sit high in day's range
WINDOW_MIN = _i("RVOL_WINDOW_MIN", 5)      # rolling volume window, minutes
ALERT_START_MIN = _i("ALERT_START_MIN", 12)   # skip the opening-noise window
ALERT_END_MIN = _i("ALERT_END_MIN", 330)      # 14:45 — later has no room to work
MAX_ALERTS_DAY = _i("MAX_ALERTS_DAY", 15)
# The older volume-spike, opening-range and level signals on the 60-name
# watchlist. Off by default: breakouts.py is the alert now, and two engines
# sending to one chat teaches you to ignore both. VOLUME_ALERTS=1 brings
# them back alongside.
VOLUME_ALERTS = _b("VOLUME_ALERTS", False)
COOLDOWN_MIN = _i("COOLDOWN_MIN", 90)
PROFILE_BATCH = _i("PROFILE_BATCH", 20)    # symbols warmed per pass
REGIME_GUARD = _f("REGIME_GUARD", -0.80)   # suppress longs below this index %
ALERT_SHORTS = _b("ALERT_SHORTS", True)
HEARTBEAT = _b("HEARTBEAT", True)
INDEX_PROXY = os.environ.get("INDEX_PROXY", "NIFTYBEES").strip().upper()

# The log. Rows from the last ALERT_HOT_DAYS days stay in the hot file every
# pass reads; older ones (and, past ALERT_LOG_MAX rows, the oldest) move to
# the archive. Nothing is dropped any more.
ALERT_HOT_DAYS = _i("ALERT_HOT_DAYS", 60)
ALERT_LOG_MAX = _i("ALERT_LOG_MAX", 20000)
# Live tracking writes the log at once when a call reaches its half-book
# level, target or stop, or is closed at 15:15; otherwise at most this often.
LIVE_SAVE_SEC = _i("LIVE_SAVE_SEC", 120)
# Follow-ups after a call, private chat only:
#   off     nothing (default)          target  the target only
#   t1      half-book + target         all     half-book + target + stop loss
ALERT_UPDATES_TG = os.environ.get("ALERT_UPDATES_TG", "").strip().lower() or "off"
_UPDATE_EVENTS = {"off": (), "target": ("target",), "t1": ("t1", "target"),
                  "all": ("t1", "target", "stop")}


def _lanes(text, default="classic,select"):
    """'classic,select' -> ('classic', 'select'). 'none' is no lane at all."""
    raw = str(text if text is not None else "").strip().lower() or default
    want = raw.replace(" ", "").split(",")
    return tuple(n for n in ("classic", "select") if n in want)


# Which lanes the public channel hears from. One break is still posted once.
TELEGRAM_PUBLIC_LANES = _lanes(os.environ.get("TELEGRAM_PUBLIC_LANES"))
# Two calls are one break when they are the same stock, the same side, and
# their levels sit within this many percent of each other.
PAIR_PCT = _f("ALERT_PAIR_PCT", 0.15)
# A runaway guard on the Select lane, far above its own budget (8 a day by
# default, paced inside breakouts.py). It never binds unless that pacing
# breaks, and then it keeps a bug from becoming fifty messages.
SELECT_HARD_CAP = _i("SELECT_HARD_CAP", 24)
# Full sessions only, for a volume profile: 60 of the day's 75 bars.
PROFILE_MIN_BARS = _i("PROFILE_MIN_BARS", 60)
# The background jobs call Dhan once per stock; dhan_source already holds
# them to 4 a second, and this gap leaves room for every other caller.
JOB_PACE_SEC = _f("ALERT_JOB_PACE_SEC", 0.12)
PROFILE_RETRY_MIN = _i("BO_PROFILE_RETRY_MIN", 30)

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))

_state = {
    "running": False, "last_run": None, "alerts": [], "watch": [],
    "profiles": {}, "profile_day": None, "levels": {}, "error": None,
    "scanned": 0, "warm_pending": [], "warm_fail": {}, "warm_done": False,
    "regime": None, "heartbeat_day": None, "eod_day": None,
    "last_reject": {}, "top_rvol": [],
}
# Re-entrant: _save_log() takes it, and is called both from inside a pass
# that already holds it and from mark_outcomes(), which does not.
_lock = threading.RLock()
_tid = threading.get_ident

# Per-symbol rolling snapshots: symbol -> deque[(epoch_seconds, cumulative_volume)]
_tape = {}


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------

def now_ist():
    return dt.datetime.now(IST)


def market_open(t=None):
    t = t or now_ist()
    if t.weekday() >= 5:
        return False
    mins = t.hour * 60 + t.minute
    return 555 <= mins <= 930          # 09:15 – 15:30


def minutes_since_open(t=None):
    t = t or now_ist()
    return max(1, (t.hour * 60 + t.minute) - 555)


def _today():
    return now_ist().date().isoformat()


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _engine(a):
    """Which lane made an alert. Rows logged before there were two lanes
    carry no engine: they are Classic."""
    return (a.get("engine") or "classic") if isinstance(a, dict) else "classic"


def _is_bo(a):
    return str(a.get("kind", "")).startswith("BO_")


def _flt(v):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return v if v == v else None


def _accepts(fn, name):
    """Whether `fn` takes the keyword `name`. A test, or an older module,
    may stand in with a narrower function than the one this file was
    written against; a new argument is passed only to a function that takes
    it, so the loop never breaks on a TypeError it caused itself."""
    try:
        params = inspect.signature(fn).parameters.values()
    except (TypeError, ValueError):
        return False
    return any(p.kind == p.VAR_KEYWORD
               or (p.name == name and p.kind in (p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY))
               for p in params)


def _call(fn, *args, **kw):
    """fn(*args, **kw) with only the keywords fn takes."""
    return fn(*args, **{k: v for k, v in kw.items() if _accepts(fn, k)})


def _jsonable(o):
    """What json.dump cannot write on its own. The engine works in numpy, and
    one numpy number in one row used to make the whole save raise — inside a
    bare except, so the day's log silently never reached the disk. Anything
    else unknown is written as its text: an odd value in one row must never
    stop the day's log from being kept."""
    if isinstance(o, np.generic):
        return o.item()
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, (set, frozenset, tuple)):
        return list(o)
    return str(o)


def _fsync(f):
    """Flush to the disk where the filesystem allows it. Some do not; the
    rename is still atomic for the process, so that is no reason to fail."""
    try:
        f.flush()
        os.fsync(f.fileno())
    except OSError:
        pass


def _native(o):
    """A copy the HTTP layer can always encode: numpy numbers as Python
    numbers, tuples and sets as lists, NaN and infinity as None. Copying
    also means a response is never read while the scanner writes to it."""
    if isinstance(o, dict):
        return {(k if isinstance(k, str) else str(k)): _native(v) for k, v in dict(o).items()}
    if isinstance(o, (list, tuple, set, frozenset)):
        return [_native(v) for v in list(o)]
    if isinstance(o, np.generic):
        o = o.item()
    if isinstance(o, float) and (o != o or o in (float("inf"), float("-inf"))):
        return None
    return o


def _write_atomic(path, text):
    """
    Write a whole file or nothing. The text goes to a temporary file beside
    the target, is flushed to the disk, and is renamed over it — a rename is
    atomic, so a reader (or a crash) sees the old file or the new one, never
    half of one. The temporary name ends in .tmp, which the nightly backup
    skips.
    """
    tmp = f"{path}.{os.getpid()}.{_tid()}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text)
            _fsync(f)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


# ---------------------------------------------------------------------------
# Volume profile — what does this stock normally trade BY this minute?
# ---------------------------------------------------------------------------

def build_profile(symbol):
    """
    Cumulative volume by minute-of-day, across recent sessions.
    Returns {minutes_since_open: expected_cumulative_volume} or None.

    Keyed by the END of each five-minute bar. Dhan stamps a bar with its
    start, but the 09:15 bar's volume has all traded by 09:20 — minute 5,
    not minute 0. Keyed by the start, as it was, the whole curve ran five
    minutes early: a stock's ordinary pace looked like more than it is, and
    a real burst looked smaller. Only whole sessions count (PROFILE_MIN_BARS
    of the 75 bars); a half-formed today would drag every median down.
    """
    df = dhan.intraday_ohlcv(symbol, interval="5", days=7)
    if df is None or len(df) < 20:
        return None
    df = df.copy()
    try:
        idx = df.index.tz_convert(IST) if df.index.tz is not None else df.index
    except Exception:
        idx = df.index
    try:
        df["day"] = [d.date() for d in idx]
        df["mso"] = [max(0, (d.hour * 60 + d.minute) - 555 + 5) for d in idx]
    except (AttributeError, TypeError):
        return None                       # no timestamps: no clock to key by

    counts = df["day"].value_counts()
    days = sorted(d for d, n in counts.items() if n >= PROFILE_MIN_BARS)[-5:]
    curves = []
    for d in days:
        sub = df[df["day"] == d].sort_values("mso")
        curves.append(dict(zip(sub["mso"].tolist(),
                               [float(v) for v in np.cumsum(sub["Volume"].values)])))
    if len(curves) < 2:
        return None

    prof = {}
    for m in range(0, 380, 5):
        vals = [c[m] for c in curves if m in c]
        if vals:
            # Median, not mean. One results-day volume explosion in the sample
            # would otherwise lift the baseline so far that nothing looks
            # unusual again for the next five sessions.
            prof[m] = float(np.median(vals))
    return prof or None


def build_bo_profile(symbol):
    """
    This stock's own volume curve in the shape breakouts.save_profiles()
    keeps: 75 median cumulative volumes, one at the END of each five-minute
    bar from 09:20 (minute 5) to 15:30 (minute 375); None where no session
    in the sample traded that bar. None when there is no profile at all.
    """
    prof = build_profile(symbol)
    if not prof:
        return None
    return [prof.get(m) for m in range(5, 380, 5)]


def expected_volume(prof, mso):
    """Interpolated expected CUMULATIVE volume at `mso` minutes after open."""
    if not prof:
        return None
    keys = sorted(prof)
    if mso <= keys[0]:
        return prof[keys[0]] * (max(mso, 1) / max(keys[0], 1))
    if mso >= keys[-1]:
        return prof[keys[-1]]
    lo = max(k for k in keys if k <= mso)
    hi = min(k for k in keys if k >= mso)
    if hi == lo:
        return prof[lo]
    # Linear interpolation. The old step function overstated RVOL by up to a
    # full bucket right after every 5-minute boundary — which is exactly where
    # a 60-second poll tends to land.
    frac = (mso - lo) / (hi - lo)
    return prof[lo] + (prof[hi] - prof[lo]) * frac


def expected_window(prof, mso, window):
    """Expected volume traded BETWEEN mso-window and mso."""
    a = expected_volume(prof, max(1, mso - window))
    b = expected_volume(prof, mso)
    if a is None or b is None:
        return None
    return max(b - a, 0.0)


# ---------------------------------------------------------------------------
# Warm-up — batched, cached, forgiving
# ---------------------------------------------------------------------------

def _load_profiles():
    if not os.path.exists(PROFILE_FILE):
        return
    try:
        with open(PROFILE_FILE) as f:
            blob = json.load(f)
        # A file from before the bar-end clock describes the wrong minutes:
        # it is rebuilt rather than read.
        if blob.get("day") == _today() and blob.get("v") == PROFILE_VERSION:
            _state["profiles"] = {k: {int(m): v for m, v in p.items()}
                                  for k, p in (blob.get("profiles") or {}).items()}
            _state["levels"] = blob.get("levels") or {}
            _state["profile_day"] = blob["day"]
    except Exception:
        pass


def _save_profiles():
    try:
        _write_atomic(PROFILE_FILE, json.dumps(
            {"day": _state["profile_day"], "v": PROFILE_VERSION,
             "profiles": {k: {str(m): v for m, v in p.items()}
                          for k, p in _state["profiles"].items()},
             "levels": _state["levels"]}, default=_jsonable))
    except Exception:
        pass


def warm_step(symbols):
    """
    Warm a small batch per pass instead of all 200 at once.

    The old code built every profile and every level set in one blocking burst
    with no throttle, against an API that allows 5 requests/second. It was
    rate-limited into returning nothing, and because the retry guard only
    skipped when profiles was non-empty, it repeated the whole failed burst
    every single minute for the rest of the day.
    """
    day = _today()
    if _state["profile_day"] != day:
        with _lock:
            _state["profiles"] = {}
            _state["levels"] = {}
            _state["warm_fail"] = {}
            _state["profile_day"] = day
            _state["warm_done"] = False
        _load_profiles()

    pending = [s for s in symbols
               if s not in _state["profiles"]
               and _state["warm_fail"].get(s, 0) < 2]
    _state["warm_pending"] = pending
    if not pending:
        _state["warm_done"] = True
        return

    for s in pending[:PROFILE_BATCH]:
        try:
            p = build_profile(s)
            if not p:
                _state["warm_fail"][s] = _state["warm_fail"].get(s, 0) + 1
                continue
            _state["profiles"][s] = p
            d = dhan.daily_ohlcv(s, days=400)
            if d is not None and len(d) > 60:
                lv = compute_levels(d.dropna(subset=["Close"]))
                if lv:
                    _state["levels"][s] = lv
        except Exception:
            _state["warm_fail"][s] = _state["warm_fail"].get(s, 0) + 1
    _save_profiles()


# ---------------------------------------------------------------------------
# Rolling volume tape
# ---------------------------------------------------------------------------

def _push_tape(sym, cum_vol):
    dq = _tape.setdefault(sym, deque(maxlen=20))
    dq.append((time.time(), float(cum_vol)))


def _window_volume(sym, window_min):
    """Volume traded in roughly the last `window_min` minutes, or (None, None)."""
    dq = _tape.get(sym)
    if not dq or len(dq) < 2:
        return None, None
    now_t, now_v = dq[-1]
    target = now_t - window_min * 60
    ref = None
    for t, v in dq:
        if t <= target:
            ref = (t, v)
    if ref is None:
        ref = dq[0]
    elapsed_min = (now_t - ref[0]) / 60.0
    if elapsed_min < 0.75:
        return None, None
    delta = now_v - ref[1]
    if delta < 0:          # counter reset (new day / feed glitch)
        return None, None
    return delta, elapsed_min


# ---------------------------------------------------------------------------
# Signal detection
# ---------------------------------------------------------------------------

def _recent_alert(sym, kind):
    """True if this symbol+signal fired inside the cooldown window."""
    now = now_ist()
    for a in reversed(_state["alerts"][-300:]):
        if a["symbol"] != sym or a["kind"] != kind or a["date"] != _today():
            continue
        try:
            fired = dt.datetime.strptime(a["time"], "%H:%M").replace(
                year=now.year, month=now.month, day=now.day, tzinfo=IST)
        except Exception:
            return True
        if (now - fired).total_seconds() < COOLDOWN_MIN * 60:
            return True
    return False


def _alerts_today():
    today = _today()
    return [a for a in _state["alerts"] if a.get("date") == today]


def _score(rvol, rpos, rr, strength=0):
    """0-100 conviction score so the digest can rank rather than dump."""
    s = 0.0
    s += min(rvol / 6.0, 1.0) * 40          # participation
    s += max(min(rpos, 1.0), 0.0) * 20      # sitting strong in the range
    s += min(max(rr, 0) / 3.0, 1.0) * 25    # payoff geometry
    s += min(strength / 100.0, 1.0) * 15    # level quality
    return round(s)


def detect(sym, q, prof, lv, opening, regime_pct):
    """Return a list of alert dicts for one symbol from one quote snapshot."""
    out = []

    px = q.get("ltp") or q.get("close")
    cum_vol = q.get("volume")
    if not px or not cum_vol:
        _state["last_reject"][sym] = "no ltp/volume in quote"
        return out
    px, cum_vol = float(px), float(cum_vol)
    if px < MIN_PRICE:
        _state["last_reject"][sym] = "below MIN_PRICE"
        return out

    _push_tape(sym, cum_vol)

    mso = minutes_since_open()
    if mso < ALERT_START_MIN or mso > ALERT_END_MIN:
        _state["last_reject"][sym] = "outside alert window"
        return out

    win_vol, win_min = _window_volume(sym, WINDOW_MIN)
    exp_win = expected_window(prof, mso, int(round(win_min))) if win_min else None
    if not win_vol or not exp_win or exp_win <= 0:
        _state["last_reject"][sym] = "no volume profile / not enough tape yet"
        return out

    rvol = win_vol / exp_win                                   # THE trigger
    exp_cum = expected_volume(prof, mso)
    day_rvol = (cum_vol / exp_cum) if exp_cum and exp_cum > 0 else None

    day_high = float(q.get("high") or px)
    day_low = float(q.get("low") or px)
    prev_close = float(q.get("prev_close") or q.get("close") or px)
    vwap = float(q.get("vwap") or 0) or None
    rng = max(day_high - day_low, px * 0.002)
    rpos = (px - day_low) / rng                                # 1.0 = at highs

    _state["last_reject"][sym] = None

    def mk(kind, direction, headline, entry, stop, target, why, strength=0):
        if direction == "UP":
            risk, reward = entry - stop, target - entry
        else:
            risk, reward = stop - entry, entry - target
        if risk <= 0 or reward <= 0:
            return None
        risk_pct = risk / entry * 100
        rr = reward / risk
        if risk_pct > MAX_RISK_PCT or rr < MIN_RR:
            return None
        return {
            "date": _today(), "time": now_ist().strftime("%H:%M"),
            "symbol": sym, "kind": kind, "direction": direction,
            "headline": headline,
            "price": round(px, 2), "rvol": round(rvol, 1),
            "day_rvol": round(day_rvol, 1) if day_rvol else None,
            "range_pos": round(rpos, 2),
            "vwap": round(vwap, 2) if vwap else None,
            "entry": round(entry, 2), "stop": round(stop, 2),
            "target": round(target, 2), "rr": round(rr, 1),
            "risk_pct": round(risk_pct, 1),
            "score": _score(rvol, rpos if direction == "UP" else 1 - rpos,
                            rr, strength),
            "regime": regime_pct, "why": why,
            "outcome": None, "closed_at": None,
        }

    long_ok = (px > prev_close and rpos >= MIN_RANGE_POS
               and (vwap is None or px >= vwap)
               and (regime_pct is None or regime_pct > REGIME_GUARD))
    short_ok = (ALERT_SHORTS and px < prev_close and rpos <= (1 - MIN_RANGE_POS)
                and (vwap is None or px <= vwap))

    # ---- 1. Rolling volume spike ---------------------------------------
    if rvol >= RVOL_MIN:
        atr_stop = max(rng * 0.5, px * 0.006)
        if long_ok and not _recent_alert(sym, "RVOL"):
            stop = max(day_low, px - atr_stop)
            a = mk("RVOL", "UP",
                   f"{rvol:.1f}x normal volume in the last {int(win_min)} min, holding above VWAP",
                   px, stop, px + 2 * (px - stop),
                   f"Traded {rvol:.1f}x its usual volume for this {int(win_min)}-minute window "
                   f"(day so far {day_rvol:.1f}x), price in the top {int(rpos * 100)}% of the "
                   "day's range and above VWAP. Unusual participation is an event, not a "
                   "lagging pattern.")
            if a:
                out.append(a)
        elif short_ok and not _recent_alert(sym, "RVOL_DOWN"):
            stop = min(day_high, px + atr_stop)
            a = mk("RVOL_DOWN", "DOWN",
                   f"{rvol:.1f}x normal volume on a break DOWN, below VWAP",
                   px, stop, px - 2 * (stop - px),
                   f"Heavy volume ({rvol:.1f}x normal for this window) with price in the bottom "
                   f"{int((1 - rpos) * 100)}% of the day's range and under VWAP. Flagged as "
                   "distribution, relevant mainly if you already hold this.")
            if a:
                out.append(a)

    # ---- 2. Opening range break ----------------------------------------
    if opening and rvol >= RVOL_CONFIRM:
        orh, orl = opening.get("high") or 0, opening.get("low") or 0
        if long_ok and px > orh > 0 and not _recent_alert(sym, "ORB"):
            stop = max(orl, px * (1 - MAX_RISK_PCT / 100))
            a = mk("ORB", "UP", f"cleared the opening-range high {orh:,.1f}",
                   px, stop, px + 2 * (px - stop),
                   f"Broke the first 15 minutes' high ({orh:,.1f}) on {rvol:.1f}x volume. "
                   "ORB without a volume filter is close to a coin flip; the filter is the edge.")
            if a:
                out.append(a)
        if short_ok and 0 < orl and px < orl and not _recent_alert(sym, "ORB_DOWN"):
            stop = min(orh, px * (1 + MAX_RISK_PCT / 100))
            a = mk("ORB_DOWN", "DOWN", f"lost the opening-range low {orl:,.1f}",
                   px, stop, px - 2 * (stop - px),
                   f"Lost the first 15 minutes' low ({orl:,.1f}) on {rvol:.1f}x volume.")
            if a:
                out.append(a)

    # ---- 3. Strong level break ------------------------------------------
    if lv and rvol >= RVOL_CONFIRM and long_ok and not _recent_alert(sym, "LEVEL"):
        for r in (lv.get("resistances") or []):
            if r["strength"] >= LEVEL_MIN_STRENGTH and prev_close < r["level"] <= px:
                sup = (lv.get("supports") or [{}])[0]
                stop = max(sup.get("level") or 0, px * (1 - MAX_RISK_PCT / 100), day_low)
                nxt = [x["level"] for x in (lv.get("resistances") or []) if x["level"] > px]
                target = nxt[0] if nxt else px + 2 * (px - stop)
                a = mk("LEVEL", "UP",
                       f"broke resistance {r['level']:,.1f} (strength {r['strength']}/100)",
                       px, stop, target,
                       f"Cleared a zone price reversed at {r['touches']}x (last {r['last_touch']}) "
                       f"on {rvol:.1f}x volume. {str(r.get('why') or '')[:110]}",
                       strength=r["strength"])
                if a:
                    out.append(a)
                break
    return out


# ---------------------------------------------------------------------------
# Scan loop
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# The alert log: a hot file the passes read, and an archive behind it
#
# The hot file is a JSON list, rewritten whole on each save (atomically).
# Rows older than ALERT_HOT_DAYS move to the archive: one JSON object per
# line, only ever appended to. Each row is archived once — a crash between
# the append and the hot file's rewrite leaves the row in both, and the next
# save sees it is already archived and only trims it. A crash mid-append
# leaves a torn last line, which the reader skips and the next append starts
# a fresh line after; the row it belonged to is still in the hot file, so
# it is appended again whole.
# ---------------------------------------------------------------------------

def _archive_path():
    return ARCHIVE_FILE or (os.path.splitext(LOG_FILE)[0] + "_archive.jsonl")


def _row_key(a):
    """What makes a logged row itself. Two rows with one key are one call
    written twice, never two calls: Classic calls a stock once a side a day,
    Select records its own lane, and the volume alerts have a 90-minute
    cooldown per kind."""
    return (str(a.get("date") or ""), str(a.get("time") or ""), str(a.get("symbol") or ""),
            str(a.get("kind") or ""), str(a.get("direction") or "UP"), _engine(a))


_arch = {"sig": None, "rows": [], "keys": frozenset()}


def _archive_index():
    """(rows, keys) of the archive, read again only when its size or
    modification time changes. Lines that do not parse are skipped."""
    path = _archive_path()
    try:
        st = os.stat(path)
    except OSError:
        return [], frozenset()
    sig = (path, st.st_size, st.st_mtime_ns)
    if _arch["sig"] != sig:
        rows = []
        with open(path, "rb") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    a = json.loads(line)
                except ValueError:          # a torn write, or junk: not a row
                    continue
                if isinstance(a, dict):
                    rows.append(a)
        _arch.update(sig=sig, rows=rows, keys=frozenset(_row_key(a) for a in rows))
    return _arch["rows"], _arch["keys"]


def _archive_append(rows):
    """Append rows the archive does not hold yet. Returns how many. Raises
    when the write fails, so the caller trims nothing it could not keep."""
    _rows, have = _archive_index()
    fresh, seen = [], set()
    for a in rows:
        k = _row_key(a)
        if k in have or k in seen:
            continue
        seen.add(k)
        fresh.append(a)
    if not fresh:
        return 0
    path = _archive_path()
    lead = b""
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            if f.tell() > 0:
                f.seek(-1, os.SEEK_END)
                if f.read(1) != b"\n":
                    lead = b"\n"            # after a torn line, start a clean one
    except OSError:
        pass
    blob = "".join(json.dumps(a, default=_jsonable, separators=(",", ":")) + "\n"
                   for a in fresh).encode("utf-8")
    with open(path, "ab") as f:
        f.write(lead + blob)
        _fsync(f)
    return len(fresh)


def _split_hot(rows):
    """(hot, old): what the hot file keeps, and what goes to the archive —
    every row dated before the last ALERT_HOT_DAYS days, then, past
    ALERT_LOG_MAX rows, the oldest. Today's rows always stay: the day's caps,
    pairing and live tracking read them."""
    today = _today()
    cutoff = (now_ist().date() - dt.timedelta(days=max(ALERT_HOT_DAYS, 0))).isoformat()
    old = [a for a in rows if str(a.get("date") or "") < cutoff]
    gone = {id(a) for a in old}
    hot = [a for a in rows if id(a) not in gone]
    if ALERT_LOG_MAX > 0 and len(hot) > ALERT_LOG_MAX:
        spare = sorted((a for a in hot if a.get("date") != today),
                       key=lambda a: (str(a.get("date") or ""), str(a.get("time") or "")))
        extra = spare[:len(hot) - ALERT_LOG_MAX]
        gone = {id(a) for a in extra}
        hot = [a for a in hot if id(a) not in gone]
        old += extra
    return hot, old


def _load_log():
    """The hot log. A file that does not parse is set aside beside it (as
    signal_log.json.bad), not left to be overwritten: the next save would
    otherwise replace the whole history with today's few rows."""
    if not os.path.exists(LOG_FILE):
        return []
    try:
        with open(LOG_FILE) as f:
            rows = json.load(f)
        if not isinstance(rows, list):
            raise ValueError("the log is not a list")
        return [a for a in rows if isinstance(a, dict)]
    except Exception:
        try:
            os.replace(LOG_FILE, LOG_FILE + ".bad")
        except OSError:
            pass
        return []


def _save_log():
    """Archive what has aged out, then write the hot log whole. Archive
    first, trim after: a row is never out of both files. An archive that
    cannot be written (a full disk) keeps its rows hot and trims nothing —
    and still does not stop today's log being saved."""
    with _lock:
        try:
            rows = _state["alerts"]
            _hot, old = _split_hot(rows)
            if old:
                try:
                    _archive_append(old)
                except Exception:
                    old = []
                if old:
                    gone = {id(a) for a in old}
                    rows[:] = [a for a in rows if id(a) not in gone]
            _write_atomic(LOG_FILE, json.dumps(rows, default=_jsonable,
                                               separators=(",", ":")))
        except Exception:
            pass


def _all_alerts():
    """Every logged alert: the archive, then the hot log. A row in both (a
    crash between the archive's append and the hot file's rewrite) counts
    once, from the hot log."""
    hot = list(_state["alerts"])
    try:
        arch, _keys = _archive_index()
    except Exception:
        arch = []
    if not arch:
        return hot
    mine = {_row_key(a) for a in hot}
    return [a for a in arch if _row_key(a) not in mine] + hot


# ---------------------------------------------------------------------------
# Live tracking — every open call of the day, marked to the last price
# ---------------------------------------------------------------------------

_LIVE_DONE = ("TARGET", "STOP", "OPEN_AT_CLOSE")
_live = {"saved": 0.0}


def _updates_mode():
    m = str(ALERT_UPDATES_TG or "off").strip().lower()
    return m if m in _UPDATE_EVENTS else "off"


def _ltp(q):
    """The last traded price, or None. Only ever the last price: the quote's
    high and low are the whole day's, much of it from before the call."""
    if not q:
        return None
    try:
        px = float(q.get("ltp") or 0)
    except (TypeError, ValueError):
        return None
    return px if px > 0 else None


def _open_symbols():
    """Today's calls still being tracked, so their stocks ride on the bulk
    quote even if they have left the watch list. Same one request."""
    today = _today()
    return [a["symbol"] for a in _state["alerts"]
            if a.get("date") == today and a.get("live_outcome") is None
            and a.get("entry") is not None and a.get("symbol")]


def _track_live(snap, now=None):
    """
    Mark every open call of the day to this pass's quote. Returns the
    follow-ups due, as (alert, event) pairs, for the caller to send.

    A call is open while it has an entry, a stop and a target, fired at or
    before `now`, and has no live result yet. For each, from the last traded
    price alone:
      live_price, live_pnl_pct, live_r   where it stands now
      mfe_* / mae_*                      its best and worst point since entry
      t1_hit, t1_time                    the half-book level (one risk) traded
      live_outcome                       STOP, else TARGET, else at the first
                                         pass from 15:15, OPEN_AT_CLOSE
    live_exit is the stop or target level itself (the order that would have
    filled), or the 15:15 price. The stop is checked first, as the candle
    reconciliation does. `outcome` is never touched: that is the verdict
    mark_outcomes() writes from the 5-minute candles after the close.

    The log is saved at once on any of those events, else at most every
    LIVE_SAVE_SEC. A follow-up is flagged (tg_t1 / tg_target / tg_stop) and
    saved BEFORE it is sent, so a restart can never send it twice — a crash
    in between loses one message rather than repeating it.
    """
    now = now or now_ist()
    today = now.date().isoformat()
    hhmm = now.strftime("%H:%M")
    closing = now.time() >= SQUARE_OFF
    want = _UPDATE_EVENTS[_updates_mode()]
    follow, moved, tracked = [], False, 0
    with _lock:
        for a in _state["alerts"]:
            if a.get("date") != today or a.get("live_outcome") is not None:
                continue
            if str(a.get("time") or "99:99") > hhmm:
                continue                    # fired after this quote was taken
            entry, stop, target = _flt(a.get("entry")), _flt(a.get("stop")), _flt(a.get("target"))
            if not entry or stop is None or target is None or entry <= 0:
                continue
            risk = abs(entry - stop)
            if risk <= 0:
                continue
            px = _ltp(snap.get(a.get("symbol")))
            if px is None:
                # No quote on the closing pass: the last price seen stands in
                # for the close, rather than leaving the call open all night.
                if not (closing and _flt(a.get("live_price"))):
                    continue
                px = _flt(a["live_price"])
            tracked += 1
            sign = 1 if a.get("direction", "UP") == "UP" else -1
            pnl = sign * (px - entry) / entry * 100
            r = sign * (px - entry) / risk
            for k in ("live_outcome", "live_time", "live_exit"):
                a.setdefault(k, None)               # open: present, and None
            a["live_price"] = round(px, 2)
            a["live_pnl_pct"] = round(pnl, 2)
            a["live_r"] = round(r, 2)
            a["mfe_pct"] = round(max(_flt(a.get("mfe_pct")) or 0.0, pnl, 0.0), 2)
            a["mae_pct"] = round(min(_flt(a.get("mae_pct")) or 0.0, pnl, 0.0), 2)
            a["mfe_r"] = round(max(_flt(a.get("mfe_r")) or 0.0, r, 0.0), 2)
            a["mae_r"] = round(min(_flt(a.get("mae_r")) or 0.0, r, 0.0), 2)
            a["live_at"] = now.strftime("%H:%M:%S")

            events = []
            t1 = _flt(a.get("t1"))
            if t1 is not None:
                if a.get("t1_hit") is None:
                    a["t1_hit"] = False
                if not a["t1_hit"] and sign * (px - t1) >= 0:
                    a["t1_hit"], a["t1_time"] = True, hhmm
                    events.append("t1")
            out = exit_ = None
            if sign * (px - stop) <= 0:
                out, exit_ = "STOP", stop
            elif sign * (px - target) >= 0:
                out, exit_ = "TARGET", target
            elif closing:
                out, exit_ = "OPEN_AT_CLOSE", px
            if out:
                a["live_outcome"], a["live_time"], a["live_exit"] = out, hhmm, round(exit_, 2)
                a["live_pnl_pct"] = round(sign * (exit_ - entry) / entry * 100, 2)
                a["live_r"] = round(sign * (exit_ - entry) / risk, 2)
                events.append({"STOP": "stop", "TARGET": "target", "OPEN_AT_CLOSE": "close"}[out])
            if not events:
                continue
            moved = True
            if "target" in events and "t1" in events:
                events.remove("t1")         # the target says it, and more
            # One follow-up stream per break: the record whose full card
            # the owner saw (a paired record carried by the other's card
            # is marked tg_card False).
            if a.get("tg_card") is False:
                continue
            for ev in events:
                if ev in want and not a.get("tg_" + ev):
                    a["tg_" + ev] = True
                    follow.append((a, ev))
        if moved or (tracked and time.time() - _live["saved"] >= LIVE_SAVE_SEC):
            _save_log()
            _live["saved"] = time.time()
    return follow


def _send_update(a, event):
    """One follow-up line to the private chat. Never raises."""
    fmt = getattr(notify, "format_update", None) if notify else None
    send = getattr(notify, "send_plain", None) if notify else None
    if not (fmt and send):
        return False
    try:
        text = fmt(a, event)
        if text:
            send(text)
            return True
    except Exception:
        pass
    return False


def _live_count(rows, now=None):
    """How many of `rows` (today's) the tracker is following right now."""
    hhmm = (now or now_ist()).strftime("%H:%M")
    return sum(1 for a in rows
               if a.get("live_outcome") is None and a.get("entry") is not None
               and a.get("stop") is not None and a.get("target") is not None
               and str(a.get("time") or "99:99") <= hhmm)


def _regime(snap):
    """Index proxy day change %, or None."""
    q = snap.get(INDEX_PROXY)
    if not q:
        return None
    try:
        px = float(q.get("ltp") or 0)
        pc = float(q.get("prev_close") or 0)
        if px and pc:
            return round((px - pc) / pc * 100, 2)
    except Exception:
        pass
    return None


_pass_lock = threading.Lock()


def scan_once():
    """One pass. Returns newly fired alerts. The scanner loop and the cron
    tick both call this; when they collide the second one stands down, so a
    breakout is never detected — and sent — twice."""
    if not _pass_lock.acquire(blocking=False):
        return []
    try:
        return _scan_pass()
    finally:
        _pass_lock.release()


def _scan_pass():
    if dhan is None or not dhan.configured():
        _state["error"] = "Dhan not configured"
        return []
    syms = _state["watch"] if VOLUME_ALERTS else []
    bo_syms = []
    if breakouts is not None:
        try:
            bo_syms = breakouts.watch_symbols()
        except Exception:
            bo_syms = []
    if not syms and not bo_syms:
        _state["error"] = ("no breakout levels yet: they are built after each close, "
                           "or within minutes of the first start")
        return []

    if syms:
        warm_step(syms)

    try:
        # mode="quote" — NOT "ohlc". /marketfeed/ohlc carries no volume field,
        # and every signal here is volume-gated. This one word is the whole
        # difference between a scanner and a silent scanner.
        # Today's open calls ride along, so a call is still marked to market
        # if its stock left the watch list: still the same one request.
        req = list(dict.fromkeys(list(syms) + list(bo_syms) + _open_symbols() + [INDEX_PROXY]))
        snap = dhan.bulk_quotes(req, mode="quote")
    except Exception as e:
        _state["error"] = str(e)[:160]
        return []
    if not snap:
        _state["error"] = ("Dhan returned no quotes: the Data API subscription or the "
                           "access token is the usual cause")
        return []
    _state["error"] = None

    regime_pct = _regime(snap)
    _state["regime"] = regime_pct

    # The calls already made are marked to this quote before new ones are
    # looked for, so a call never marks itself on the pass that made it.
    try:
        follow = _track_live(snap)
    except Exception:
        follow = []
    for a_, event in follow:
        _send_update(a_, event)

    # Opening range: capture live between 09:30-09:40, else backfill once.
    mso = minutes_since_open()
    today_str = _today()
    if syms and mso >= 15 and _state.get("opening_day") != today_str:
        if mso <= 25:
            _state["opening"] = {s: {"high": float(q.get("high") or 0),
                                     "low": float(q.get("low") or 0)}
                                 for s, q in snap.items() if q.get("high")}
            _state["opening_day"] = today_str
        else:
            _backfill_opening(syms[:120], today_str)

    fired = []
    for s in syms:
        q = snap.get(s)
        if not q:
            continue
        try:
            fired.extend(detect(s, q, _state["profiles"].get(s),
                                _state["levels"].get(s),
                                (_state.get("opening") or {}).get(s),
                                regime_pct))
        except Exception:
            continue

    # Visibility: what came closest today, so silence is explainable.
    try:
        ranked = []
        for s in syms:
            wv, wm = _window_volume(s, WINDOW_MIN)
            ew = expected_window(_state["profiles"].get(s), mso,
                                 int(round(wm))) if wm else None
            if wv and ew and ew > 0:
                ranked.append({"symbol": s, "rvol": round(wv / ew, 2)})
        _state["top_rvol"] = sorted(ranked, key=lambda x: -x["rvol"])[:15]
    except Exception:
        pass

    # Breakouts, up and down, both lanes (breakouts.py). They join the same
    # list, so they share the filing join, the log and the outcome marking.
    # `fired` tells Classic what it already called today (its own rows only:
    # a Select call does not use up Classic's one call a stock a side);
    # `log` hands every lane today's rows, from which Select reads its own.
    if breakouts is not None:
        try:
            bo_today = [a for a in _alerts_today() if _is_bo(a)]
            done = {(a["symbol"], a.get("direction", "UP")) for a in bo_today
                    if _engine(a) != "select"}
            fired.extend(_check_breakouts(snap, regime_pct, done, bo_today))
        except Exception as e:
            _state["error"] = "breakouts: " + str(e)[:140]

    fired = _cap(fired)

    # THE JOIN. Volume on its own says something happened. Volume with a filing
    # eleven minutes old says what. No retail tool in India puts these two facts
    # in the same message, and it costs one dictionary lookup.
    if fired and ann is not None:
        try:
            ann.poll_if_stale()
            for a_ in fired:
                t = ann.tag(a_["symbol"], minutes=120)
                if t:
                    a_["filing"] = t
                    a_["score"] = min(100, a_["score"] + (8 if t["importance"] in
                                                          ("critical", "high") else 3))
        except Exception:
            pass

    if fired:
        fired = sorted(fired, key=lambda a: -(a.get("score") or 0))
        with _lock:
            cards, confirms, public = _route(fired, _alerts_today())
            _state["alerts"].extend(fired)
            _save_log()
        _deliver(cards, confirms, public)

    _state["scanned"] = len(snap)
    _state["last_run"] = now_ist().isoformat()
    _heartbeat()
    return fired


def _check_breakouts(snap, index_pct, done, log):
    """One engine pass. `log` goes only to an engine that takes it."""
    fn = breakouts.check_live
    if _accepts(fn, "log"):
        return list(fn(snap, index_pct=index_pct, fired=done, log=log) or [])
    return list(fn(snap, index_pct=index_pct, fired=done) or [])


def _cap(fired):
    """
    The daily cap, best first — on Classic and the legacy volume alerts
    only. Better to miss the 16th idea than to train yourself to ignore the
    notification. ★ Select is paced inside breakouts.py (slots per part of
    the session, per pass, per sector), so its calls pass straight through,
    under nothing but SELECT_HARD_CAP, a guard against that pacing breaking.
    """
    today = _alerts_today()
    rest = [a for a in fired if _engine(a) != "select"]
    sel = [a for a in fired if _engine(a) == "select"]
    room = MAX_ALERTS_DAY - sum(1 for a in today if _engine(a) != "select")
    if room <= 0:
        rest = []
    elif len(rest) > room:
        rest = sorted(rest, key=lambda a: -(a.get("score") or 0))[:room]
    if SELECT_HARD_CAP > 0:
        left = SELECT_HARD_CAP - sum(1 for a in today if _engine(a) == "select")
        sel = sorted(sel, key=lambda a: -(a.get("score") or 0))[:max(left, 0)]
    return rest + sel


# ---------------------------------------------------------------------------
# One break, one card: pairing the lanes and routing the messages
# ---------------------------------------------------------------------------

def _public_lanes():
    v = TELEGRAM_PUBLIC_LANES
    return _lanes(v) if isinstance(v, str) else tuple(v or ())


def _same_break(a, b):
    """Two calls of one break: same stock, same side, and levels within
    PAIR_PCT percent of each other."""
    if a.get("symbol") != b.get("symbol") or a.get("direction", "UP") != b.get("direction", "UP"):
        return False
    la, lb = _flt(a.get("level")), _flt(b.get("level"))
    if la is None or lb is None:
        return False
    return abs(la - lb) <= PAIR_PCT / 100.0 * max(abs(la), abs(lb))


def _partner(a, pool):
    """The first call in `pool` of the same break, or None."""
    return next((b for b in pool if b is not a and _same_break(a, b)), None)


def _link(classic, select):
    classic["select_time"] = select.get("time")
    classic["select_score"] = select.get("score")
    select["pair_time"] = classic.get("time")


def _route(fired, earlier):
    """
    Who hears about this pass's new calls, and how. Returns (cards,
    confirms, public): the rows for full private cards, the ★ Select rows
    that get the short "Select confirms" line instead, and the rows for the
    public channel. Marks each row with the decision (tg_card, tg_public)
    and links the two records of one break (select_time and select_score on
    the Classic row, pair_time on the Select row).

    One break, one full card, one public post:
      * Classic and Select call it in the same pass: Select's card only,
        and one public post (Select's, if its lane is public).
      * Select follows an earlier Classic call: the short confirm line, no
        second card; posted publicly only if the Classic call was not.
      * Classic follows an earlier Select call: no second card either.
    Everything else is a full card, as before.
    """
    lanes = _public_lanes()
    classic_new = [a for a in fired if _is_bo(a) and _engine(a) != "select"]
    select_new = [a for a in fired if _is_bo(a) and _engine(a) == "select"]
    classic_old = [a for a in earlier if _is_bo(a) and _engine(a) != "select"]
    select_old = [a for a in earlier if _is_bo(a) and _engine(a) == "select"]

    carried = {}        # id(classic row) -> the select row whose card carries it
    batch_pair = {}     # id(select row) -> the classic row it carries
    later = {}          # id(row) -> the earlier record of the same break
    confirms = []
    for s in select_new:                    # best first: fired is sorted
        c = _partner(s, [c for c in classic_new
                         if id(c) not in carried and not c.get("select_time")])
        if c is not None:
            _link(c, s)
            carried[id(c)], batch_pair[id(s)] = s, c
            continue
        c = _partner(s, [c for c in classic_old if not c.get("select_time")])
        if c is not None:
            _link(c, s)
            later[id(s)] = c
            confirms.append(s)
    for c in classic_new:
        if id(c) in carried:
            continue
        s = _partner(c, [s for s in select_old if not s.get("pair_time")])
        if s is not None:
            _link(c, s)
            later[id(c)] = s

    def public_ok(a):
        return _engine(a) in lanes

    def was_posted(b):
        # Rows logged before this routing existed went to every channel.
        v = b.get("tg_public")
        return public_ok(b) if v is None else bool(v)

    cards, public = [], []
    for a in fired:
        a["tg_card"] = id(a) not in carried and id(a) not in later
        a["tg_public"] = False
        if a["tg_card"]:
            cards.append(a)
    for a in fired:
        if id(a) in carried:
            continue                        # its Select pair decides for both
        c = batch_pair.get(id(a))
        if c is not None:
            pick = a if public_ok(a) else (c if public_ok(c) else None)
        elif id(a) in later:
            pick = a if (public_ok(a) and not was_posted(later[id(a)])) else None
        else:
            pick = a if public_ok(a) else None
        if pick is not None:
            pick["tg_public"] = True
            public.append(pick)
    return cards, confirms, public


def _deliver(cards, confirms, public):
    """Send what _route() decided. Never raises: a Telegram outage must not
    stop the scanner."""
    if not notify:
        return
    send_batch = getattr(notify, "send_batch", None)
    if send_batch and (cards or public):
        kw = {"index_pct": _state.get("regime"), "total_today": len(_alerts_today()),
              "clock": now_ist().strftime("%H:%M")}
        try:
            if _accepts(send_batch, "public_rows"):
                send_batch(cards, public_rows=public, **kw)
            elif cards:
                send_batch(cards, **kw)
        except Exception:
            pass
    fmt = getattr(notify, "format_confirm", None)
    send = getattr(notify, "send_plain", None)
    if confirms and fmt and send:
        try:
            text = "\n\n".join(t for t in (fmt(a) for a in confirms) if t)
            if text:
                send(text)
        except Exception:
            pass


def _heartbeat():
    """One 'I am alive' message a day. Without it, a broken scanner and a
    quiet market look identical. The day's result is sent by day_result()."""
    if not (HEARTBEAT and notify):
        return
    day = _today()
    # Sent BEFORE the alert window opens (09:18), not after it.
    if _state["heartbeat_day"] != day and market_open() and minutes_since_open() >= 3:
        _state["heartbeat_day"] = day
        try:
            st = breakouts.status() if breakouts is not None else {}
            kw = dict(stocks=st.get("stocks", 0) if st.get("usable") else 0,
                      levels_asof=st.get("asof"),
                      index_pct=_state["regime"],
                      poll_seconds=POLL_SECONDS)
            sel = _select_brief(st)
            if sel and _accepts(notify.format_day_open, "select"):
                kw["select"] = sel
            notify.send_plain(notify.format_day_open(**kw))
        except Exception:
            pass


def _select_brief(st):
    """The ★ Select lane's day, for the morning message: its cap and its
    window, from breakouts.status(); None when the lane is off."""
    lane = ((st or {}).get("lanes") or {}).get("select") or {}
    if not lane.get("enabled"):
        return None
    frm, _sep, to = str(lane.get("window") or "").replace("-", "–").partition("–")
    return {"cap_day": lane.get("cap_day") or 8,
            "from": frm.strip() or "09:25", "to": to.strip() or "14:45"}


MARKS_FILE = os.path.join(DATA_DIR, "intraday_marks.json")


def _marks():
    try:
        with open(MARKS_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def day_result():
    """
    After the close: mark every open alert target / stop / flat, then send
    the day's result to Telegram once. Sent on a day with no alerts too —
    silence that is confirmed is information — but not on a day the scanner
    never ran (a holiday). Returns how many alerts were marked.
    """
    t = now_ist()
    if t.weekday() >= 5 or t.hour < 16:
        return 0
    marked = mark_outcomes()
    day = _today()
    rows = _alerts_today()
    ran_today = str(_state.get("last_run") or "")[:10] == day
    if notify and HEARTBEAT and (rows or ran_today) and _marks().get("result_day") != day:
        try:
            _write_atomic(MARKS_FILE, json.dumps({"result_day": day}))
        except Exception:
            pass
        try:
            notify.send_plain(notify.format_day_result(day, rows))
        except Exception:
            pass
    return marked


def _ensure_levels():
    """
    The breakout levels normally come from the after-close scan. If they are
    missing or stale on a trading morning — first day after a deploy, a scan
    that failed — build them straight from Dhan's daily bars, once, in the
    background. About two minutes for 400 stocks at Dhan's 5 requests/second.
    """
    if breakouts is None or dhan is None or not dhan.configured():
        return
    t = now_ist()
    mins = t.hour * 60 + t.minute
    if t.weekday() >= 5 or not (510 <= mins <= 900):       # 08:30 to 15:00
        return
    day = _today()
    # Rebuild when there are no usable levels, or when they are a session
    # behind (the after-close scan did not run, or ran short).
    if _state.get("levels_day") == day or (breakouts.usable() and not breakouts.behind()):
        return
    _state["levels_day"] = day
    syms = breakouts.universe() or list(_state["watch"])
    if not syms:
        return
    threading.Thread(target=breakouts.rebuild,
                     args=(syms, lambda s: dhan.daily_ohlcv(s, with_today=False)),
                     daemon=True, name="altaha-levels").start()


def _backfill_opening(symbols, today_str):
    """Rebuild the 09:15-09:30 range from 5-minute candles when the live
    capture window was missed (deploy, restart, cold start)."""
    out = {}
    for s in symbols:
        try:
            df = dhan.intraday_ohlcv(s, interval="5", days=1)
            if df is None or not len(df):
                continue
            idx = df.index.tz_convert(IST) if df.index.tz is not None else df.index
            mask = [i for i, ts in enumerate(idx)
                    if ts.date().isoformat() == today_str
                    and 555 <= (ts.hour * 60 + ts.minute) < 570]
            if not mask:
                continue
            sub = df.iloc[mask]
            out[s] = {"high": float(sub["High"].max()), "low": float(sub["Low"].min())}
        except Exception:
            continue
    if out:
        with _lock:
            _state["opening"] = out
            _state["opening_day"] = today_str


# ---------------------------------------------------------------------------
# Background jobs — started from the loop, never from a pass
#
# Each needs one Dhan call per stock (or a database read), which a pass
# cannot afford: a pass is one bulk quote every 20 seconds. Each runs in its
# own daemon thread, is skipped while its previous thread is still alive,
# runs at most once a day (the profiles get one retry), paces its calls, and
# never raises into the loop. What each one did is kept in _jobs, which
# diagnose() shows.
# ---------------------------------------------------------------------------

_jobs = {}


def _job(name):
    return _jobs.setdefault(name, {"thread": None, "day": None, "tries": 0, "last_try": 0.0,
                                   "built": None, "of": None, "map": {},
                                   "result": None, "error": None})


def _quiet(name):
    """A background job's guard: whatever goes wrong is noted in _jobs, for
    diagnose() to show, and never raised into the loop."""
    def wrap(fn):
        @functools.wraps(fn)
        def run(*a, **k):
            try:
                return fn(*a, **k)
            except Exception as e:
                _job(name)["error"] = str(e)[:160]
                return False
        return run
    return wrap


def _spawn(name, fn, *args, sync=False):
    """Run fn(*args) in its own daemon thread, unless the last one is still
    at it. sync=True runs it here, for a test or a one-off call."""
    j = _job(name)
    t = j.get("thread")
    if t is not None and t.is_alive():
        return False

    def run():
        try:
            j["result"] = fn(*args)
            j["error"] = None
        except Exception as e:
            j["error"] = str(e)[:160]

    if sync:
        run()
        return True
    th = threading.Thread(target=run, daemon=True, name="altaha-" + name)
    j["thread"] = th
    th.start()
    return True


def _pace():
    if JOB_PACE_SEC > 0:
        time.sleep(JOB_PACE_SEC)


def _prev_weekday(day):
    day -= dt.timedelta(days=1)
    while day.weekday() >= 5:
        day -= dt.timedelta(days=1)
    return day


@_quiet("profiles")
def _ensure_bo_profiles(now=None, sync=False):
    """
    Each Select stock's own 5-minute volume profile, built once a trading
    morning (07:30 to 15:00) from the last five whole sessions, when the
    stored ones are not for the last close. One retry, PROFILE_RETRY_MIN
    later, when the first try built fewer than half (Dhan having a bad
    morning); the retry only fetches what is missing. Returns whether a
    build was started.
    """
    if breakouts is None or dhan is None or not dhan.configured():
        return False
    fresh = getattr(breakouts, "profiles_fresh", None)
    wanted = getattr(breakouts, "profile_symbols", None)
    save = getattr(breakouts, "save_profiles", None)
    if not (fresh and wanted and save):
        return False
    now = now or now_ist()
    mins = now.hour * 60 + now.minute
    if now.weekday() >= 5 or not (450 <= mins <= 900):
        return False
    day = now.date().isoformat()
    j = _job("profiles")
    if j["day"] != day:
        j.update(day=day, tries=0, last_try=0.0, built=None, of=None, map={})
    if j["tries"] == 0:
        if _call(fresh, now=now):
            return False
    elif j["tries"] == 1:
        if (time.time() - j["last_try"] < PROFILE_RETRY_MIN * 60 or not j["of"]
                or (j["built"] or 0) >= 0.5 * j["of"]):
            return False
    else:
        return False
    t = j.get("thread")
    if t is not None and t.is_alive():
        return False
    syms = [s for s in (wanted() or []) if s]
    if not syms:
        return False                        # no levels yet: not an attempt
    lc = getattr(breakouts, "last_close", None)
    try:
        built_for = (_call(lc, now=now) if lc else _prev_weekday(now.date())).isoformat()
    except Exception:
        built_for = _prev_weekday(now.date()).isoformat()
    j["tries"] += 1
    j["last_try"] = time.time()
    return _spawn("profiles", _profiles_job, syms, built_for, save, sync=sync)


def _profiles_job(syms, built_for, save):
    j = _job("profiles")
    have = dict(j.get("map") or {})
    j["of"], j["built"] = len(syms), sum(1 for s in syms if s in have)
    for s in syms:
        if s in have:
            continue
        try:
            p = build_bo_profile(s)
        except Exception:
            p = None
        if p and any(v is not None for v in p):
            have[s] = p
            j["built"] += 1
        _pace()
    j["map"] = have
    if have:
        save(have, built_for)
    return len(have)


def _opening_range(df, day):
    """(high, low) of the first 15 minutes of `day`: the 09:15, 09:20 and
    09:25 five-minute bars. None when none of them is there."""
    if df is None or not len(df):
        return None
    idx = df.index
    try:
        if getattr(idx, "tz", None) is not None:
            idx = idx.tz_convert(IST)
    except Exception:
        pass
    rows = []
    for i, ts in enumerate(idx):
        try:
            if ts.date().isoformat() == day and (ts.hour, ts.minute) in ((9, 15), (9, 20), (9, 25)):
                rows.append(i)
        except AttributeError:
            return None                     # no timestamps on this frame
    if not rows:
        return None
    sub = df.iloc[rows]
    hi, lo = float(sub["High"].max()), float(sub["Low"].min())
    return (hi, lo) if hi > lo > 0 else None


@_quiet("orb")
def _ensure_orb(now=None, sync=False):
    """
    The opening range, when the live capture at 09:30 was missed (a deploy,
    a restart, a cold start): rebuilt from today's 5-minute candles for the
    watch list and handed to breakouts.set_orb(). breakouts.orb_missing()
    says when it is still worth it. Once a day.
    """
    if breakouts is None or dhan is None or not dhan.configured():
        return False
    missing = getattr(breakouts, "orb_missing", None)
    set_orb = getattr(breakouts, "set_orb", None)
    if not (missing and set_orb):
        return False
    now = now or now_ist()
    day = now.date().isoformat()
    j = _job("orb")
    if j["day"] == day:
        return False
    if not _call(missing, now=now):
        return False
    syms = [s for s in (_call(breakouts.watch_symbols, now=now) or []) if s]
    if not syms:
        return False
    j["day"] = day
    return _spawn("orb", _orb_job, syms, day, set_orb, sync=sync)


def _orb_job(syms, day, set_orb):
    out = {}
    for s in syms:
        try:
            rng = _opening_range(dhan.intraday_ohlcv(s, interval="5", days=1), day)
            if rng:
                out[s] = rng
        except Exception:
            pass
        _pace()
    return set_orb(day, out) if out else 0


@_quiet("money_flow")
def _ensure_money_flow(now=None, sync=False):
    """
    The sectors' money-flow quadrants (Leading / Improving / Weakening /
    Lagging) for the Select lane, read from money_flow.overview() once a
    trading day, 08:00 to 15:30. No Dhan call: a read of the stored page.
    """
    if breakouts is None:
        return False
    setter = getattr(breakouts, "set_money_flow", None)
    if not setter:
        return False
    now = now or now_ist()
    mins = now.hour * 60 + now.minute
    if now.weekday() >= 5 or not (480 <= mins <= 930):
        return False
    day = now.date().isoformat()
    j = _job("money_flow")
    if j["day"] == day:
        return False
    t = j.get("thread")
    if t is not None and t.is_alive():
        return False
    j["day"] = day
    return _spawn("money_flow", _money_flow_job, setter, day, sync=sync)


def _money_flow_job(setter, day):
    # Imported here, in the thread: a heavy module the loop needs once a day.
    import money_flow
    page = money_flow.overview() or {}
    m = {}
    # Scored sectors first; an unscored one still has a quadrant (it is read
    # from prices, not from the members a score needs).
    for c in list(page.get("sectors") or []) + list(page.get("unscored") or []):
        q = c.get("quadrant") if isinstance(c, dict) else None
        if not q:
            continue
        for name in (c.get("sector"), c.get("short")):
            if name:
                m.setdefault(str(name).strip().lower(), q)
    if m:
        setter(m, day)
    return len(m)


def _ensure_background(now=None):
    """Start whichever background job is due. Never raises."""
    for name, fn in (("profiles", _ensure_bo_profiles), ("orb", _ensure_orb),
                     ("money_flow", _ensure_money_flow)):
        try:
            fn(now)
        except Exception as e:
            _job(name)["error"] = str(e)[:160]


def _jobs_view():
    out = {}
    for name, j in _jobs.items():
        t = j.get("thread")
        out[name] = {"day": j.get("day"), "tries": j.get("tries"), "built": j.get("built"),
                     "of": j.get("of"), "result": j.get("result"), "error": j.get("error"),
                     "running": bool(t is not None and t.is_alive())}
    return out


SQUARE_OFF = dt.time(15, 15)


def _r_multiple(a, last=None):
    """The trade's result in risks: +rr at the target, -1 at the stop, and
    for one still open at the square-off, wherever it stood. Counting only
    targets and stops would leave out every trade that drifted — which is
    most of the losing days of a breakout system."""
    try:
        risk = abs(float(a["entry"]) - float(a["stop"]))
        if risk <= 0:
            return None
        if a["outcome"] == "TARGET":
            return round(abs(float(a["target"]) - float(a["entry"])) / risk, 2)
        if a["outcome"] == "STOP":
            return -1.0
        last = a.get("closed_at") if last is None else last
        sign = 1 if a.get("direction", "UP") == "UP" else -1
        return round(sign * (float(last) - float(a["entry"])) / risk, 2)
    except (TypeError, ValueError, KeyError):
        return None


def _pnl_pct(a, last=None):
    """The call's profit or loss as a percent of the entry price: out at the
    target, out at the stop loss, or out at the 3:15 pm price."""
    try:
        entry = float(a["entry"])
        if a["outcome"] == "TARGET":
            out = float(a["target"])
        elif a["outcome"] == "STOP":
            out = float(a["stop"])
        else:
            out = float(a.get("closed_at") if last is None else last)
        sign = 1 if a.get("direction", "UP") == "UP" else -1
        return round(sign * (out - entry) / entry * 100, 2)
    except (TypeError, ValueError, KeyError, ZeroDivisionError):
        return None


def call_record(rows=None):
    """
    The breakout calls' record in plain terms, for the Alerts page: for each
    of the two kinds of call, how many were made, how many hit the target,
    how many hit the stop loss, and the average profit or loss per call in
    percent. Alerts from the older volume scanner are not counted — they
    were a different system.

    `rows` defaults to every logged Classic call, archive included — the
    record it always was. Pass one lane's rows for that lane's record.
    """
    if rows is None:
        rows = [a for a in _all_alerts() if _engine(a) != "select"]
    groups = {"INTRADAY": [], "CONSOLIDATION": []}
    for a in rows:
        if not str(a.get("kind", "")).startswith("BO_"):
            continue
        if a.get("outcome") not in ("STOP", "TARGET", "OPEN_AT_CLOSE"):
            continue
        pct = a.get("pnl_pct")
        if pct is None:
            pct = _pnl_pct(a)
        if pct is not None:
            groups.setdefault(a.get("call") or "INTRADAY", []).append((a, pct))

    def summary(rows):
        n = len(rows)
        if not n:
            return {"calls": 0}
        return {"calls": n,
                "target": sum(1 for a, _p in rows if a["outcome"] == "TARGET"),
                "stop": sum(1 for a, _p in rows if a["outcome"] == "STOP"),
                "closed": sum(1 for a, _p in rows if a["outcome"] == "OPEN_AT_CLOSE"),
                "profitable": sum(1 for _a, p in rows if p > 0),
                "avg_pct": round(sum(p for _a, p in rows) / n, 2)}
    return {"intraday": summary(groups["INTRADAY"]),
            "consolidation": summary(groups["CONSOLIDATION"])}


def mark_outcomes():
    """
    Mark open alerts target-hit, stopped-out, or open-at-close.

    Uses only bars AFTER the alert fired, so a dip at 09:20 cannot stop out an
    11:00 entry. Now also sweeps alerts from earlier days left unmarked by a
    restart — those used to sit at outcome=None forever and quietly never
    reached the hit rate.

    With no 5-minute candles for the call, a result the live tracker saw is
    used (approx, source "live") before the daily bar: the daily bar's high
    and low include the hours before the call, the tracker's do not. Each
    marked row says where its result came from: "candles", "live", "daily".
    """
    open_alerts = [a for a in _state["alerts"] if a.get("outcome") is None]
    if not open_alerts:
        return 0
    today = _today()
    cutoff = (now_ist().date() - dt.timedelta(days=10)).isoformat()
    done = 0

    by_day = {}
    for a in open_alerts:
        if str(a.get("date") or "") >= cutoff:
            by_day.setdefault(a["date"], []).append(a)

    for day, group in by_day.items():
        for s in sorted({a["symbol"] for a in group}):
            mine = [x for x in group if x["symbol"] == s]
            intra = None
            if day == today:
                try:
                    intra = dhan.intraday_ohlcv(s, interval="5", days=1)
                except Exception:
                    intra = None
            try:
                for a in mine:
                    hi = lo = last = None
                    approx = False
                    if intra is not None and len(intra):
                        try:
                            idx = (intra.index.tz_convert(IST)
                                   if intra.index.tz is not None else intra.index)
                            fired = dt.datetime.strptime(a["time"], "%H:%M").time()
                            # A day trade is flat by 15:15: bars after that
                            # are not part of it.
                            after = [i for i, ts in enumerate(idx)
                                     if ts.date().isoformat() == day
                                     and fired <= ts.time() < SQUARE_OFF]
                            if after:
                                sub = intra.iloc[after[0]:after[-1] + 1]
                                hi = float(sub["High"].max())
                                lo = float(sub["Low"].min())
                                last = float(sub["Close"].iloc[-1])
                        except Exception:
                            hi = lo = last = None
                    source = "candles"
                    if hi is None and a.get("live_outcome") in _LIVE_DONE:
                        live = _flt(a.get("live_exit"))
                        live = live if live is not None else _flt(a.get("live_price"))
                        if live is not None:
                            with _lock:
                                a["outcome"] = a["live_outcome"]
                                a["closed_at"] = round(live, 2)
                                a["approx"] = True
                                a["source"] = "live"
                                a["r"] = _r_multiple(a, live)
                                a["pnl_pct"] = _pnl_pct(a, live)
                            done += 1
                            continue
                    if hi is None:
                        df = dhan.daily_ohlcv(s, days=15)
                        if df is None or df.empty:
                            continue
                        row = df.iloc[-1]
                        hi, lo, last = (float(row["High"]), float(row["Low"]),
                                        float(row["Close"]))
                        approx = True
                        source = "daily"

                    up = a.get("direction", "UP") == "UP"
                    with _lock:
                        # Stop first: when both levels trade inside the same bar we
                        # cannot know the order, so assume the loss.
                        if up:
                            a["outcome"] = ("STOP" if lo <= a["stop"]
                                            else "TARGET" if hi >= a["target"]
                                            else "OPEN_AT_CLOSE")
                        else:
                            a["outcome"] = ("STOP" if hi >= a["stop"]
                                            else "TARGET" if lo <= a["target"]
                                            else "OPEN_AT_CLOSE")
                        a["closed_at"] = round(last, 2)
                        a["approx"] = approx
                        a["source"] = source
                        a["r"] = _r_multiple(a, last)
                        a["pnl_pct"] = _pnl_pct(a, last)
                    done += 1
            except Exception:
                continue
    _save_log()
    return done


def _closed(rows):
    """(alert, R) for every marked trade among `rows`."""
    done = []
    for a in rows:
        if a.get("outcome") not in ("STOP", "TARGET", "OPEN_AT_CLOSE"):
            continue
        r = a.get("r")
        if r is None:
            r = _r_multiple(a)
        if r is not None:
            done.append((a, r))
    return done


def _bucket(rows):
    n = len(rows)
    if not n:
        return None
    return {"trades": n,
            "win_rate": round(sum(1 for _a, r in rows if r > 0) / n * 100),
            "targets": sum(1 for a, _r in rows if a["outcome"] == "TARGET"),
            "stops": sum(1 for a, _r in rows if a["outcome"] == "STOP"),
            "expectancy_R": round(sum(r for _a, r in rows) / n, 2),
            "total_R": round(sum(r for _a, r in rows), 1)}


def _xbucket(rows):
    """A bucket plus what the live tracker saw of the same trades: their
    average best and worst point (percent and R) and how often the half-book
    level traded. None where no trade in it was tracked live."""
    b = _bucket(rows)
    if b is None:
        return None

    def avg(key):
        vals = [_flt(a.get(key)) for a, _r in rows]
        vals = [v for v in vals if v is not None]
        return round(sum(vals) / len(vals), 2) if vals else None

    hits = [bool(a["t1_hit"]) for a, _r in rows if a.get("t1_hit") is not None]
    b.update(avg_mfe_pct=avg("mfe_pct"), avg_mae_pct=avg("mae_pct"),
             avg_mfe_r=avg("mfe_r"), avg_mae_r=avg("mae_r"),
             t1_rate=round(sum(hits) / len(hits) * 100) if hits else None)
    return b


_WINDOWS = ("early", "open", "mid", "pm", "late")
# The setup tag of an old row, which predates the tag: from its kind.
_SETUP_OF = {"BASE": "Base breakout", "BASE_DN": "Base breakdown",
             "HIGH52": "52-week high", "LOW52": "52-week low",
             "HIGH20": "20-day high", "LOW20": "20-day low",
             "PDH": "Yesterday's high", "PDL": "Yesterday's low",
             "ORB": "Opening range", "ORB_DN": "Opening range",
             "RANGE": "Tight range", "RANGE_DN": "Tight range",
             "HOD": "Fresh day high", "LOD": "Fresh day low",
             "VWAP": "VWAP reclaim", "VWAP_DN": "VWAP rejection"}
SHADOW_CODES = ("rpos", "extended", "book", "sector", "pdh")


def _window_key(a):
    """The part of the session a call fired in; an old row's from its time."""
    if a.get("window"):
        return a["window"]
    try:
        h, m = (int(x) for x in str(a.get("time"))[:5].split(":"))
    except (TypeError, ValueError):
        return None
    mso = h * 60 + m - 555
    fn = getattr(breakouts, "window_of", None) if breakouts is not None else None
    if fn:
        try:
            return fn(mso)
        except Exception:
            pass
    return ("early" if mso < 10 else "open" if mso < 60 else "mid" if mso < 195
            else "pm" if mso < 330 else "late")


def _setup_key(a):
    return a.get("setup") or _SETUP_OF.get(str(a.get("kind", ""))[3:])


def _score_key(a):
    sc = a.get("score") or 0
    return "<50" if sc < 50 else "50-64" if sc < 65 else "65-79" if sc < 80 else "80+"


def _grouped(done, keyfn, order=None):
    """{key: extended bucket} over `done`, rows whose key is None left out;
    in `order` when given, else busiest first."""
    groups = {}
    for a, r in done:
        k = keyfn(a)
        if k is not None:
            groups.setdefault(k, []).append((a, r))
    if order:
        keys = [k for k in order if k in groups] + sorted(k for k in groups if k not in order)
    else:
        keys = sorted(groups, key=lambda k: (-len(groups[k]), str(k)))
    return {k: _xbucket(groups[k]) for k in keys}


def _lane_stats(rows):
    """One lane's own record, from its own trade records."""
    done = _closed(rows)
    return {"overall": _xbucket(done),
            "by_setup": _grouped(done, _setup_key),
            "by_window": _grouped(done, _window_key, order=_WINDOWS),
            "by_direction": _grouped(done, lambda a: a.get("direction", "UP")),
            "by_score_bucket": _grouped(done, _score_key),
            "calls": call_record(rows)}


def _by_shadow(done):
    """For each Select quality filter, Classic's trades that would have
    failed it and those that would have passed: whether the filter would
    have helped Classic. Rows from before the filters were measured (no
    `shadow`) are in neither."""
    measured = [(a, r) for a, r in done if isinstance(a.get("shadow"), (list, tuple))]
    return {code: {"failed": _xbucket([(a, r) for a, r in measured if code in a["shadow"]]),
                   "passed": _xbucket([(a, r) for a, r in measured if code not in a["shadow"]])}
            for code in SHADOW_CODES}


def stats():
    """Honest expectancy over logged alerts — the whole point of the log.
    Every marked trade counts, including the ones flat at the square-off.

    The keys it always had are Classic's (with the legacy volume alerts),
    worked out exactly as before, over the archive as well as the hot log.
    ★ Select keeps its own record beside it, never mixed in: `engines` has
    each lane's, `calls_by_engine` each lane's plain counts, and `by_shadow`
    asks of Classic's trades whether Select's filters would have helped."""
    rows = _all_alerts()
    mine = [a for a in rows if _engine(a) != "select"]
    done = _closed(mine)

    by_signal, by_hour, by_rvol, by_score, by_dir = {}, {}, {}, {}, {}
    for a, r in done:
        by_signal.setdefault(a["kind"], []).append((a, r))
        by_dir.setdefault(a.get("direction", "UP"), []).append((a, r))
        try:
            by_hour.setdefault(a["time"][:2] + ":00", []).append((a, r))
        except Exception:
            pass
        rv = a.get("rvol") or 0
        key = "<3x" if rv < 3 else "3-5x" if rv < 5 else "5-8x" if rv < 8 else "8x+"
        by_rvol.setdefault(key, []).append((a, r))
        by_score.setdefault(_score_key(a), []).append((a, r))

    classic = [a for a in mine if _is_bo(a)]
    select = [a for a in rows if _engine(a) == "select"]
    cdone = _closed(classic)
    return {
        "by_signal": {k: _bucket(v) for k, v in by_signal.items()},
        "by_direction": {k: _bucket(v) for k, v in by_dir.items()},
        "by_hour": {k: _bucket(v) for k, v in sorted(by_hour.items())},
        "by_rvol_bucket": {k: _bucket(v) for k, v in by_rvol.items()},
        "by_score_bucket": {k: _bucket(v) for k, v in by_score.items()},
        "overall": _bucket(done),
        "calls": call_record(mine),
        "total_closed": len(done),
        "note": ("Results are in R: one R is the distance from entry to stop. A target is +2R, "
                 "a stop is -1R, and a trade still open at 15:15 counts for wherever it stood. "
                 "Positive expectancy makes money even under a 50% win rate. Under about 30 "
                 "trades a row is noise; after that, switch off the kinds that lose."),
        "engines": {"classic": _lane_stats(classic), "select": _lane_stats(select)},
        "by_window": _grouped(cdone, _window_key, order=_WINDOWS),
        "by_setup": _grouped(cdone, _setup_key),
        "by_shadow": _by_shadow(cdone),
        "calls_by_engine": {"classic": call_record(classic), "select": call_record(select)},
    }


def diagnose():
    """Why did nothing fire? Answers it without reading logs."""
    reasons = {}
    for s, r in (_state["last_reject"] or {}).items():
        if r:
            reasons[r] = reasons.get(r, 0) + 1
    bst = None
    if breakouts is not None:
        try:
            bst = breakouts.status()
        except Exception as e:
            bst = {"error": str(e)[:160]}
    bsd = bst if isinstance(bst, dict) else {}
    try:
        archived = len(_archive_index()[0])
    except Exception:
        archived = None
    return _native({
        "running": _state["running"],
        "market_open": market_open(),
        "minutes_since_open": minutes_since_open() if market_open() else None,
        "in_alert_window": (market_open()
                            and ALERT_START_MIN <= minutes_since_open() <= ALERT_END_MIN),
        "watchlist_size": len(_state["watch"]),
        "quotes_received_last_pass": _state["scanned"],
        "volume_profiles_built": len(_state["profiles"]),
        "profiles_still_pending": len(_state["warm_pending"]),
        "profiles_given_up_on": len(_state["warm_fail"]),
        "tape_depth_sample": {s: len(_tape.get(s, [])) for s in _state["watch"][:5]},
        "index_change_pct": _state["regime"],
        "longs_suppressed_by_regime": (_state["regime"] is not None
                                       and _state["regime"] <= REGIME_GUARD),
        "closest_names_by_rolling_rvol": _state["top_rvol"],
        "rejection_reasons": reasons,
        "alerts_today": len(_alerts_today()),
        "daily_cap": MAX_ALERTS_DAY,
        "thresholds": {"RVOL_MIN": RVOL_MIN, "RVOL_CONFIRM": RVOL_CONFIRM,
                       "MIN_RANGE_POS": MIN_RANGE_POS, "MAX_RISK_PCT": MAX_RISK_PCT,
                       "MIN_RR": MIN_RR, "WINDOW_MIN": WINDOW_MIN,
                       "ALERT_START_MIN": ALERT_START_MIN,
                       "ALERT_END_MIN": ALERT_END_MIN},
        "alerts_configured": bool(notify and notify.configured()),
        "breakouts": bst,
        "volume_alerts_on": VOLUME_ALERTS,
        "poll_seconds": POLL_SECONDS,
        "error": _state["error"],
        "log_path": LOG_FILE,
        "log_is_ephemeral": DATA_DIR == HERE,
        # The two lanes, from the engine.
        "lanes": bsd.get("lanes"),
        "profiles": bsd.get("profiles"),
        "checkpoint": bsd.get("checkpoint"),
        "gates": bsd.get("gates"),
        # This loop's own side of it.
        "updates_tg": _updates_mode(),
        "public_lanes": list(_public_lanes()),
        "log_rows": len(_state["alerts"]),
        "archive_rows": archived,
        "archive_path": _archive_path(),
        "background_jobs": _jobs_view(),
    })


def _loop():
    marked_day = None
    while _state["running"]:
        try:
            _ensure_levels()
        except Exception as e:
            _state["error"] = str(e)[:160]
        # Profiles, a missed opening range, money flow: each in its own
        # thread, so the pass below is never kept waiting on them.
        _ensure_background()
        try:
            if market_open():
                scan_once()
            else:
                today = _today()
                if marked_day != today and now_ist().hour >= 16:
                    day_result()
                    marked_day = today
        except Exception as e:
            _state["error"] = str(e)[:160]
        time.sleep(POLL_SECONDS)


_thread = {"t": None}


def start(watchlist):
    """Race-safe start: two callers (boot autostart and the cron tick) can
    arrive at the same instant, and two loops means every alert fires twice
    and the rate limit is consumed twice."""
    with _lock:
        _state["watch"] = list(watchlist)
        if not _state["alerts"]:
            _state["alerts"] = _load_log()
        _load_profiles()
        alive = _thread["t"] is not None and _thread["t"].is_alive()
        if alive and _state["running"]:
            return True
        _state["running"] = True          # set BEFORE spawning, closing the race
        t = threading.Thread(target=_loop, daemon=True, name="altaha-scanner")
        _thread["t"] = t
        t.start()
    return True


def stop():
    _state["running"] = False
    _thread["t"] = None


def _pacing(rows, now):
    """The Select lane's slots for the page, counted from the log."""
    fn = getattr(breakouts, "pacing", None) if breakouts is not None else None
    if not fn:
        return None
    try:
        return _call(fn, log=rows, now=now)
    except Exception:
        return None


def status():
    now = now_ist()
    today = _alerts_today()
    return _native({
        "running": _state["running"],
        "market_open": market_open(),
        "watchlist_size": len(_state["watch"]),
        "quotes_last_pass": _state["scanned"],
        "last_run": _state["last_run"],
        "profiles_built": len(_state["profiles"]),
        "profiles_pending": len(_state["warm_pending"]),
        "index_change_pct": _state["regime"],
        # Newest first, both lanes, with the live fields.
        "alerts_today": today[::-1],
        "top_rvol_now": _state["top_rvol"][:8],
        "profiles_given_up": sum(1 for n in _state["warm_fail"].values() if n >= 2),
        "in_alert_window": (market_open()
                            and ALERT_START_MIN <= minutes_since_open() <= ALERT_END_MIN),
        "alerts_configured": bool(notify and notify.configured()),
        "volume_alerts_on": VOLUME_ALERTS,
        "poll_seconds": POLL_SECONDS,
        "daily_cap": MAX_ALERTS_DAY,
        "error": _state["error"],
        "pacing": _pacing(today, now),
        "clock": now.strftime("%H:%M"),
        "lanes": {"classic": sum(1 for a in today if _engine(a) != "select"),
                  "select": sum(1 for a in today if _engine(a) == "select")},
        "updates_tg": _updates_mode(),
        "live_tracked": _live_count(today, now),
    })
