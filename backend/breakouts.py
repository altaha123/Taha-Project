"""
Altaha Screener — Intraday breakout alerts

WHAT THIS IS FOR
----------------
One job: tell Telegram, the moment it happens, that a liquid stock is
breaking out of a level — up or down — in a way that makes a day trade:
a clear entry, a stop a short distance away, and room to the target.

HOW IT WORKS
------------
1. After the close, the universe scan (scan.phase1) reads every liquid
   stock's daily bars. read_daily() takes the levels that matter tomorrow
   from each frame while it is in hand — no extra data call:

       UP    yesterday's high · 20-day high · top of a base · 52-week high
       DOWN  yesterday's low  · 20-day low  · bottom of a base · 52-week low

   ingest() keeps them for the BO_UNIVERSE most-traded stocks.

2. During the session, intraday.scan_once() pulls one bulk quote every
   POLL_SECONDS for all of them (one Dhan request carries 900 symbols).
   check_live() keeps a short tape of those quotes and adds two levels the
   day itself makes:

       the opening range (first 15 minutes), and
       a tight intraday range — 40 minutes inside a third of the stock's
       daily ATR — which is the "long consolidation" of a day trade.

3. A break alerts only if every one of these holds:
     - FRESH   the price was on the other side of the level minutes ago.
               A stock that gapped through at the open, or was already
               through yesterday, is not breaking out now.
     - VOLUME  the last five minutes traded BO_SURGE times what this stock
               normally trades in five minutes at this time of day.
     - SIDE    above VWAP for a long, below it for a short.
     - RISK    the stop — just back inside the level, or the far side of
               the tight range — is between BO_MIN_RISK and BO_MAX_RISK
               percent away. Further than that and the entry is late.
     - ROOM    the next level in the way is at least one risk away.
     - MARKET  no longs with the index down hard, no shorts with it up hard.
     - NOT SPENT  the day's move so far is inside 2.5 daily ATRs.

   One alert per stock per direction per day. The target is two risks from
   the entry; the alert goes into the scanner's log, where it is marked
   target / stop / flat-at-close after the session, so every kind of
   breakout carries its own measured record.

A BASE
------
The longest stretch of 40 to 250 daily bars whose high-to-low range fits in
18% (25% from 120 sessions) and whose older half already reached near the
top. That last test separates a sideways range from a slow uptrend.

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

# Which stocks. A day trade needs to get in and out without moving the price.
UNIVERSE = _i("BO_UNIVERSE", 400)                 # most-traded stocks watched live
MIN_TURNOVER_CR = _f("BO_MIN_TURNOVER_CR", 15.0)  # 60-day average, rupees crore a day
MIN_PRICE = _f("BO_MIN_PRICE", 50.0)

# What a base is (daily bars).
MIN_SESSIONS = _i("BO_MIN_SESSIONS", 40)
MAX_WIDTH = _f("BO_MAX_WIDTH", 0.18)
LONG_SESSIONS = _i("BO_LONG_SESSIONS", 120)
LONG_MAX_WIDTH = _f("BO_LONG_MAX_WIDTH", 0.25)
MAX_SESSIONS = _i("BO_MAX_SESSIONS", 250)
TOP_TEST = _f("BO_TOP_TEST", 0.35)
HIGH_WINDOW = 252
HIGH_QUIET = _i("BO_HIGH_QUIET", 20)              # a 52-week extreme this old is a real level
NEAR_PCT = _f("BO_NEAR_PCT", 3.0)                 # "close to a level", for the page's list

# The live trigger.
BUFFER_PCT = _f("BO_BUFFER_PCT", 0.1)             # through the level by this much
SURGE = _f("BO_SURGE", 2.0)                       # last-5-minute volume over its usual
PACE_FLOOR = _f("BO_PACE_FLOOR", 0.7)             # and the day not running dead quiet
CHASE_MIN = _f("BO_CHASE_MIN", 12.0)              # minutes a break may wait for its volume
CHASE_PCT = _f("BO_CHASE_PCT", 1.0)               # and how far past the level it may run
MIN_RISK = _f("BO_MIN_RISK", 0.4)                 # percent; tighter stops are noise
MAX_RISK = _f("BO_MAX_RISK", 1.5)                 # percent; wider and the entry is late
RR = _f("BO_RR", 2.0)                             # target, in risks
ROOM_R = _f("BO_ROOM_R", 1.0)                     # the next level must be this many risks away
REGIME = _f("BO_REGIME", 0.8)                     # index move, percent, that blocks the other side
MIN_SCORE = _i("BO_MIN_SCORE", 50)
SHORTS = _b("BO_SHORTS", True)
START_MIN = _i("BO_START_MIN", 5)                 # 09:20
END_MIN = _i("BO_END_MIN", 345)                   # 15:00 — the last call still has 15 minutes
                                                  # before the 15:15 exit; asked for by the owner
ORB_MIN = 15                                      # the opening range is the first 15 minutes
ORB_END = _i("BO_ORB_END", 165)                   # and is traded until 12:00
RANGE_MIN = _i("BO_RANGE_MIN", 40)                # the intraday consolidation, minutes
RANGE_COVER = _i("BO_RANGE_COVER", 28)            # tape needed before it is judged
RANGE_ATR = _f("BO_RANGE_ATR", 0.35)              # its width, as a share of the daily ATR
STALE_DAYS = _i("BO_STALE_DAYS", 6)
MIN_SCAN = _i("BO_MIN_SCAN", 150)                 # a smaller scan does not replace the levels
TAPE = 240                                        # passes kept: 80 minutes at 20 seconds

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("DATA_DIR", "").strip() or HERE
try:
    os.makedirs(DATA_DIR, exist_ok=True)
except Exception:
    DATA_DIR = HERE
FEED_FILE = os.path.join(DATA_DIR, "breakout_feed.json")

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))

# How much a level matters, and what it is called in a sentence.
SIG = {"BASE_LONG": 5, "BASE": 4, "HIGH52": 4, "LOW52": 4, "HIGH20": 3, "LOW20": 3,
       "RANGE": 3, "ORB": 2, "PDH": 2, "PDL": 2}
WORDS = {"BASE": "the top of its consolidation", "HIGH52": "its 52-week high",
         "HIGH20": "its 20-day high", "PDH": "yesterday's high",
         "ORB": "the high of the first 15 minutes", "RANGE": "a tight intraday range",
         "BASE_DN": "the bottom of its consolidation", "LOW52": "its 52-week low",
         "LOW20": "its 20-day low", "PDL": "yesterday's low",
         "ORB_DN": "the low of the first 15 minutes", "RANGE_DN": "a tight intraday range"}

# A normal NSE session's cumulative share of the day's volume by minutes after
# 09:15. Volume is U-shaped — heavy at the open and into the close — so a
# straight line would make every morning look like a surge. A generic shape,
# not this stock's own: it only has to keep the comparison honest.
_CURVE = ((0, 0.0), (15, 0.10), (30, 0.16), (60, 0.26), (120, 0.42), (180, 0.54),
          (240, 0.65), (300, 0.77), (345, 0.87), (375, 1.0))

_lock = threading.Lock()
_mem = {"feed": None, "day": None}


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------

def now_ist():
    return dt.datetime.now(IST)


def _mso(t):
    return (t.hour * 60 + t.minute) - 555 + t.second / 60.0


def session_live(t=None):
    """09:15 to 15:30 IST on a weekday: today's daily bar is still forming."""
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
# Daily bars -> tomorrow's levels
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
    Returns {"sessions", "top", "low", "width"}.
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
    # Longest first; the first whose older half reached the top is the base.
    # A stretch that only fits because the stock climbed steadily through it
    # is a trend, and is skipped.
    for k in np.nonzero(ok)[0][::-1]:
        n = int(k) + 1
        top, bot = float(rmax[k]), float(rmin[k])
        older = hh[n // 2:n]
        if older.size and float(older.max()) < top - TOP_TEST * (top - bot):
            continue
        return {"sessions": n, "top": top, "low": bot, "width": float(width[k])}
    return None


def _extreme(arr, end, high=True):
    """The 52-week high (or low) over bars before `end` and how many sessions
    ago it was last touched. None under six months of history."""
    win = arr[max(0, end - HIGH_WINDOW):end]
    if win.size < 120:
        return None
    level = float(win.max() if high else win.min())
    hit = (win[::-1] >= level) if high else (win[::-1] <= level)
    return level, int(np.argmax(hit))


def _date(idx):
    try:
        return idx.date().isoformat() if hasattr(idx, "date") else str(idx)[:10]
    except Exception:
        return str(idx)[:10]


def read_daily(df, drop_partial=None, today=None):
    """
    The levels one stock carries into its next session, or None.

    `drop_partial` drops a last bar dated today while the session is still
    open, so a mid-day read never treats a half-formed candle as yesterday.
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
    price = float(c[-1])
    if not (np.isfinite(price) and price > 0):
        return None

    tr = np.maximum(h[1:] - low[1:], np.maximum(np.abs(h[1:] - c[:-1]), np.abs(low[1:] - c[:-1])))
    atr_pct = float(tr[-14:].mean() / price * 100)
    out = {
        "asof": _date(frame.index[-1]), "close": round(price, 2),
        "pdh": round(float(h[-1]), 2), "pdl": round(float(low[-1]), 2),
        "hi20": round(float(h[-20:].max()), 2), "lo20": round(float(low[-20:].min()), 2),
        "atr_pct": round(atr_pct, 2),
        "vol_med50": round(float(np.median(v[-50:]))),
        "turnover_cr": round(float((c[-60:] * v[-60:]).mean() / 1e7), 1),
        "base": None, "high52": None, "low52": None,
    }
    base = find_base(h, low, n)
    if base:
        out["base"] = {"top": round(base["top"], 2), "low": round(base["low"], 2),
                       "sessions": base["sessions"], "width_pct": round(base["width"] * 100, 1)}
    hi, lo = _extreme(h, n, True), _extreme(low, n, False)
    if hi:
        out["high52"], out["high52_age"] = round(hi[0], 2), hi[1]
    if lo:
        out["low52"], out["low52_age"] = round(lo[0], 2), lo[1]
    return out


def _ladder(r, up=True):
    """
    The levels in one direction, nearest first, levels within 0.15% of each
    other merged into one. Each: {"l": level, "k": kind, "s": weight,
    "also": [other kinds at the same price]}.
    """
    b = r.get("base")
    rows = []
    if up:
        rows.append((r["pdh"], "PDH"))
        rows.append((r["hi20"], "HIGH20"))
        if b:
            rows.append((b["top"], "BASE"))
        if r.get("high52"):
            rows.append((r["high52"], "HIGH52"))
    else:
        rows.append((r["pdl"], "PDL"))
        rows.append((r["lo20"], "LOW20"))
        if b:
            rows.append((b["low"], "BASE_DN"))
        if r.get("low52"):
            rows.append((r["low52"], "LOW52"))

    def weight(kind):
        if kind in ("BASE", "BASE_DN"):
            return SIG["BASE_LONG"] if b["sessions"] >= LONG_SESSIONS else SIG["BASE"]
        if kind == "HIGH52":
            return SIG["HIGH52"] if r.get("high52_age", 0) >= HIGH_QUIET else SIG["HIGH20"]
        if kind == "LOW52":
            return SIG["LOW52"] if r.get("low52_age", 0) >= HIGH_QUIET else SIG["LOW20"]
        return SIG[kind]

    rows = sorted(((float(l), k, weight(k)) for l, k in rows if l and l > 0),
                  key=lambda x: x[0] if up else -x[0])
    out = []
    for level, kind, s in rows:
        if out and abs(level / out[-1]["l"] - 1) <= 0.0015:
            m = out[-1]
            m["l"] = max(m["l"], level) if up else min(m["l"], level)
            if s > m["s"]:
                m["also"].append(m["k"])
                m["k"], m["s"] = kind, s
            else:
                m["also"].append(kind)
            continue
        out.append({"l": round(level, 2), "k": kind, "s": s, "also": []})
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


def _usable(feed, today):
    asof = feed.get("asof")
    if not asof or not feed.get("levels"):
        return False
    try:
        age = (dt.date.fromisoformat(today) - dt.date.fromisoformat(asof)).days
    except Exception:
        return False
    # The levels describe the session AFTER `asof`. Built from today's close
    # they are for tomorrow; a week old, they are stale.
    return 0 < age <= STALE_DAYS


def _weekday_before(day):
    day -= dt.timedelta(days=1)
    while day.weekday() >= 5:
        day -= dt.timedelta(days=1)
    return day


def last_close(now=None):
    """The last session that has closed: today after 15:30 on a weekday,
    otherwise the weekday before. Holidays are not known here, so on the day
    after one this names the holiday; callers only ever use it to ask
    "could the levels be newer?", where one wasted check is harmless."""
    now = now or now_ist()
    if now.weekday() < 5 and _mso(now) >= 375:
        return now.date()
    return _weekday_before(now.date())


def behind(now=None):
    """True when the stored levels are older than the last close, so the
    session about to trade would use a stale yesterday's high and low."""
    asof = _feed().get("asof")
    if not asof:
        return True
    try:
        return dt.date.fromisoformat(asof) < last_close(now)
    except ValueError:
        return True


def usable(now=None):
    now = now or now_ist()
    return _usable(_feed(), now.date().isoformat())


def universe():
    """Symbols in the stored levels, most traded first."""
    return list((_feed().get("levels") or {}).keys())


# ---------------------------------------------------------------------------
# After the close: build tomorrow's levels
# ---------------------------------------------------------------------------

def _near(sym, r):
    """Levels (other than yesterday's high and low, which are always close)
    this stock closed within NEAR_PCT of."""
    rows, px, b = [], r["close"], r.get("base")

    def add(level, kind, up):
        if not level:
            return
        away = (level / px - 1) * 100 * (1 if up else -1)
        if 0 <= away <= NEAR_PCT:
            row = {"symbol": sym, "dir": "UP" if up else "DOWN", "kind": kind,
                   "level": level, "away_pct": round(away, 2)}
            if b and kind in ("BASE", "BASE_DN"):
                row["sessions"], row["width_pct"] = b["sessions"], b["width_pct"]
            rows.append(row)
    if b:
        add(b["top"], "BASE", True)
        add(b["low"], "BASE_DN", False)
    if r.get("high52") and r.get("high52_age", 0) >= HIGH_QUIET:
        add(r["high52"], "HIGH52", True)
    if r.get("low52") and r.get("low52_age", 0) >= HIGH_QUIET:
        add(r["low52"], "LOW52", False)
    # One row per direction: the base and the 52-week high are often one price.
    best = {}
    for row in rows:
        cur = best.get(row["dir"])
        if cur is None or row["away_pct"] < cur["away_pct"]:
            best[row["dir"]] = row
    return list(best.values())


def ingest(reads, meta=None, now=None, send=True, force=False):
    """
    Turn one pass over the market's daily bars into the levels the live loop
    trades against. `reads` is {SYMBOL: read_daily()}. Returns the feed, or
    None when the pass is too small to stand for the market (unless `force`).
    """
    reads = {s: r for s, r in (reads or {}).items() if r}
    if not reads or (len(reads) < MIN_SCAN and not force):
        return None
    meta = meta or {}
    now = now or now_ist()
    dates = {}
    for r in reads.values():
        dates[r["asof"]] = dates.get(r["asof"], 0) + 1
    asof = max(dates, key=lambda d: (dates[d], d))

    pool = [(s, r) for s, r in reads.items()
            if r["asof"] == asof and r["close"] >= MIN_PRICE
            and r["turnover_cr"] >= MIN_TURNOVER_CR and r["vol_med50"] > 0]
    pool.sort(key=lambda x: -x[1]["turnover_cr"])
    pool = pool[:UNIVERSE]

    levels, near = {}, []
    for sym, r in pool:
        b = r.get("base")
        levels[sym] = {"c": r["close"], "atr": r["atr_pct"], "v": r["vol_med50"],
                       "up": _ladder(r, True), "dn": _ladder(r, False),
                       "base": ({"n": b["sessions"], "w": b["width_pct"]} if b else None),
                       "sector": (meta.get(sym) or {}).get("sector")}
        near.extend(_near(sym, r))
    near.sort(key=lambda x: (x["away_pct"], x["symbol"]))

    with _lock:
        old = _feed()
        feed = {"asof": asof, "built_at": now.isoformat(timespec="minutes"),
                "scanned": len(reads), "levels": levels, "near": near[:60],
                "sent": old.get("sent") if old.get("asof") == asof else None}
        # The levels are complete once they describe the last close — after
        # 15:30 the same day, or overnight: GitHub's scheduled scan has been
        # starting hours late, around 01:30 IST.
        complete = not session_live(now) and asof == last_close(now).isoformat()
        due = bool(send and complete and levels and feed["sent"] != asof)
        if due:
            feed["sent"] = asof
        _mem["feed"] = feed
        _mem["day"] = None
        _write_json(FEED_FILE, feed)

    if due and notify is not None:
        try:
            notify.send_plain(notify.format_levels_ready(asof, len(levels), feed["near"]))
        except Exception:
            pass
    return feed


def rebuild(symbols, fetch, now=None):
    """Build the levels straight from daily bars, without waiting for the
    scan — the first morning after a deploy, or after a scan that failed.
    `fetch(symbol)` returns a daily frame or None."""
    reads = {}
    for s in symbols or []:
        try:
            reads[str(s).upper()] = read_daily(fetch(s))
        except Exception:
            continue
    return ingest(reads, now=now, send=False, force=True)


# ---------------------------------------------------------------------------
# During the session
# ---------------------------------------------------------------------------

def watch_symbols(now=None):
    """Symbols the live loop must quote on every pass."""
    if not ENABLED or not usable(now):
        return []
    return universe()


def _day(today, feed):
    """The session's working memory: a tape of every pass, the opening
    ranges, and which breaks have been seen. Rebuilt each morning."""
    d = _mem["day"]
    if d is not None and d["day"] == today and d["asof"] == feed.get("asof"):
        return d
    syms = list(feed["levels"].keys())
    d = {"day": today, "asof": feed.get("asof"), "syms": syms,
         "row": {s: i for i, s in enumerate(syms)},
         "t": np.zeros(TAPE), "n": 0,
         "px": np.full((len(syms), TAPE), np.nan, dtype=np.float32),
         "vol": np.full((len(syms), TAPE), np.nan, dtype=np.float32),
         "orb": {}, "orb_done": False,
         "armed": {}, "dead": set(), "late": {}, "seen": set(),
         "waiting": {}, "passes": 0, "last": None}
    _mem["day"] = d
    return d


def _push(d, snap, stamp):
    if d["n"] == TAPE:                       # full: drop the oldest quarter
        k = TAPE // 4
        d["t"][:-k] = d["t"][k:]
        d["px"][:, :-k] = d["px"][:, k:]
        d["vol"][:, :-k] = d["vol"][:, k:]
        d["px"][:, -k:] = np.nan
        d["vol"][:, -k:] = np.nan
        d["n"] -= k
    i = d["n"]
    d["t"][i] = stamp
    for sym, q in snap.items():
        r = d["row"].get(sym)
        if r is None or not q:
            continue
        try:
            px = float(q.get("ltp") or 0)
            if px > 0:
                d["px"][r, i] = px
                d["vol"][r, i] = float(q.get("volume") or np.nan)
        except (TypeError, ValueError):
            continue
    d["n"] = i + 1
    d["passes"] += 1
    return i


def _num(q, key):
    try:
        return float(q.get(key) or 0)
    except (TypeError, ValueError):
        return 0.0


def _span(vals):
    vals = vals[np.isfinite(vals)]
    return (float(vals.min()), float(vals.max())) if vals.size else (None, None)


def check_live(snap, now=None, index_pct=None, fired=None):
    """
    One pass. `snap` is {SYMBOL: quote}; `fired` is the set of
    (symbol, direction) already alerted today. Returns the alerts this pass
    produced, best first, in the scanner's alert shape — the caller logs and
    sends them. Never sends anything itself.
    """
    if not ENABLED or not snap:
        return []
    now = now or now_ist()
    today = now.date().isoformat()
    feed = _feed()
    if not _usable(feed, today) or not session_live(now):
        return []
    fired = fired or set()
    mso = _mso(now)
    out = []

    with _lock:
        d = _day(today, feed)
        i = _push(d, snap, now.timestamp())
        d["last"] = now.strftime("%H:%M:%S")
        t = d["t"][:i + 1]
        t_now = t[i]

        # The opening range, taken once from the day's high and low at 09:30.
        # A process that started after 09:35 has missed it and trades without.
        if not d["orb_done"] and mso >= ORB_MIN:
            d["orb_done"] = True
            if mso <= ORB_MIN + 5:
                for sym, q in snap.items():
                    hi, lo = _num(q, "high"), _num(q, "low")
                    if sym in d["row"] and hi > lo > 0:
                        d["orb"][sym] = (hi, lo)

        if mso < START_MIN or mso > END_MIN:
            d["seen"].update(s for s in snap if s in d["row"])
            return []

        j5 = int(np.searchsorted(t, t_now - 300))
        j15 = int(np.searchsorted(t, t_now - 900))
        jw = int(np.searchsorted(t, t_now - RANGE_MIN * 60))
        je = int(np.searchsorted(t, t_now - 60, side="right"))
        # The range is only judged when the quotes inside the window really
        # span it: an old tape with a hole in it has not watched the stock.
        range_ready = je - jw >= 6 and (t[je - 1] - t[jw]) / 60.0 >= RANGE_COVER
        el5 = (t_now - t[j5]) / 60.0 if j5 < i else 0.0
        share5 = day_fraction(mso) - day_fraction(mso - el5) if el5 >= 1.5 else 0.0
        share_day = max(day_fraction(mso), 0.05)
        waiting = {}

        for sym, lv in feed["levels"].items():
            q = snap.get(sym)
            r = d["row"].get(sym)
            if not q or r is None:
                continue
            px, cum, pc = _num(q, "ltp"), _num(q, "volume"), _num(q, "prev_close")
            if px <= 0 or pc <= 0 or cum <= 0:
                continue
            opn = _num(q, "open") or pc
            vwap = _num(q, "vwap") or None
            first = sym not in d["seen"]
            atr = float(lv.get("atr") or 2.0)
            med = float(lv["v"])
            move = (px / pc - 1) * 100

            pace = cum / (med * share_day)
            v0 = float(d["vol"][r, j5]) if share5 > 0 else float("nan")
            surge = ((cum - v0) / (med * share5)) if (share5 > 0 and np.isfinite(v0) and cum >= v0) else None
            lo15, hi15 = _span(d["px"][r, j15:i + 1])
            rl, rh = _span(d["px"][r, jw:je]) if range_ready else (None, None)
            tight = bool(rh and (rh - rl) / px * 100 <= max(RANGE_ATR * atr, 0.25))

            for sign in ((1, -1) if SHORTS else (1,)):
                side = "UP" if sign > 0 else "DOWN"
                if (sym, side) in fired:
                    continue
                ladder = list(lv["up"] if sign > 0 else lv["dn"])
                orb = d["orb"].get(sym)
                if orb and mso <= ORB_END:
                    ladder.append({"l": orb[0] if sign > 0 else orb[1],
                                   "k": "ORB" if sign > 0 else "ORB_DN", "s": SIG["ORB"], "also": []})
                through = [x for x in ladder if sign * (px - x["l"] * (1 + sign * BUFFER_PCT / 100)) >= 0]

                # A level the price has fallen back inside is forgotten, so the
                # next cross of it is a fresh break and not a late one.
                slot = (sym, side)
                cleared = {x["l"] for x in through}
                armed = d["armed"].get(slot)
                if armed:
                    for lvl in [k for k in armed if k not in cleared]:
                        del armed[lvl]
                if slot in d["late"]:
                    d["late"][slot] &= cleared

                trig = None
                if through:
                    x = max(through, key=lambda z: sign * z["l"])      # the furthest level cleared
                    key = (sym, side, x["l"])
                    armed = d["armed"].setdefault(slot, {})
                    if key in d["dead"] or x["l"] in d["late"].get(slot, ()):
                        pass
                    elif sign * (pc - x["l"]) > 0:
                        d["dead"].add(key)             # through it before today
                    elif x["l"] not in armed:
                        gapped = x["k"] not in ("ORB", "ORB_DN") and sign * (opn - x["l"]) > 0
                        if gapped or (first and mso > START_MIN + 4):
                            d["dead"].add(key)         # opened through it, or broke before we looked
                        else:
                            armed[x["l"]] = t_now
                            trig = x
                    else:
                        trig = x
                    if trig is not None:
                        waited = (t_now - armed[x["l"]]) / 60.0
                        if waited > CHASE_MIN or sign * (px / x["l"] - 1) * 100 > CHASE_PCT:
                            d["late"].setdefault(slot, set()).add(x["l"])   # ran without its volume
                            trig = None

                # The day's own consolidation, broken in the direction of the day.
                edge = rh if sign > 0 else rl
                ranged = bool(tight and edge and sign * (px - edge * (1 + sign * BUFFER_PCT / 100)) >= 0
                              and sign * (px / edge - 1) * 100 <= CHASE_PCT and sign * move > 0)
                if trig is None and not ranged:
                    continue
                if trig is None:
                    trig = {"l": round(edge, 2), "k": "RANGE" if sign > 0 else "RANGE_DN",
                            "s": SIG["RANGE"], "also": []}
                level = trig["l"]

                def wait(why):
                    waiting[(sym, side)] = {"symbol": sym, "dir": side, "kind": trig["k"],
                                            "level": level, "price": round(px, 2), "why": why}

                # VOLUME
                if surge is None:
                    if pace < max(1.5, SURGE * 0.75):
                        wait(f"day volume {pace:.1f}x normal, too early to read the last 5 minutes")
                        continue
                elif surge < SURGE or pace < PACE_FLOOR:
                    wait(f"last-5-minute volume {surge:.1f}x usual, needs {SURGE:g}x")
                    continue
                # SIDE
                if vwap and sign * (px - vwap) < 0:
                    wait("wrong side of VWAP")
                    continue
                # MARKET
                if index_pct is not None and sign * index_pct < -REGIME:
                    wait(f"index {index_pct:+.2f}% is against it")
                    continue
                # NOT SPENT
                if abs(move) > max(2.5 * atr, 3.0):
                    wait(f"already {move:+.1f}% on the day")
                    continue
                # RISK
                max_risk = min(MAX_RISK, max(0.6 * atr, MIN_RISK + 0.2))
                back = level * (1 - sign * 0.003)                      # just back inside the level
                far = (rl if sign > 0 else rh) if (ranged and rl) else (lo15 if sign > 0 else hi15)
                stop = back
                if far:
                    far = far * (1 - sign * 0.001)
                    stop = min(back, far) if sign > 0 else max(back, far)
                risk_pct = sign * (px - stop) / px * 100
                if risk_pct > max_risk:
                    stop, risk_pct = back, sign * (px - back) / px * 100
                if risk_pct > max_risk:
                    wait(f"stop would be {risk_pct:.1f}% away, limit {max_risk:.1f}%")
                    continue
                if risk_pct < MIN_RISK:
                    stop = px * (1 - sign * MIN_RISK / 100)
                    risk_pct = MIN_RISK
                risk = abs(px - stop)
                # ROOM
                ahead = [x["l"] for x in (lv["up"] if sign > 0 else lv["dn"]) if sign * (x["l"] - px) > 0]
                nxt = min(ahead, key=lambda z: sign * z) if ahead else None
                if nxt is not None and sign * (nxt - px) < ROOM_R * risk:
                    wait(f"next level {nxt:,.2f} is too close")
                    continue

                # SCORE: 0-100, so the day's cap keeps the best and a
                # threshold can be set from the measured record.
                rel = sign * (move - (index_pct or 0.0))
                vol_x = surge if surge is not None else pace
                score = (min(vol_x, 4.0) / 4.0 * 30
                         + {5: 25, 4: 21, 3: 15, 2: 9}[trig["s"]] + min(len(trig["also"]), 2) * 4
                         + (1 - risk_pct / max_risk) * 10 + (8 if ranged else 0)
                         + (10 if (index_pct or 0) * sign > 0.3 else 6 if abs(index_pct or 0) <= 0.3 else 2)
                         + max(0.0, min(rel, 2.0)) / 2.0 * 10)
                score = int(round(min(score, 100)))
                if score < MIN_SCORE:
                    wait(f"score {score}, needs {MIN_SCORE}")
                    continue

                kind = trig["k"]
                base = lv.get("base")
                # The two things a reader asked for, by name. A break that
                # ends a consolidation — weeks inside a base, or 40 tight
                # minutes today — is a CONSOLIDATION breakout; every other
                # break of a level is an INTRADAY call.
                consolidation = ranged or kind in ("BASE", "BASE_DN", "RANGE", "RANGE_DN")
                what = WORDS[kind]
                if kind in ("BASE", "BASE_DN") and base:
                    what = f"the {'top' if sign > 0 else 'bottom'} of a {base['n']}-day consolidation"
                elif kind in ("RANGE", "RANGE_DN"):
                    what = f"a tight {RANGE_MIN}-minute range"
                elif ranged:
                    what += f", after {RANGE_MIN} minutes in a tight range"
                verb = "Crossed above" if sign > 0 else "Fell below"
                why = (f"{verb} {level:,.2f}, {what}, on {vol_x:.1f} times its normal volume. "
                       "Exit by 3:15 pm.")
                out.append({
                    "date": today, "time": now.strftime("%H:%M"), "symbol": sym,
                    "kind": "BO_" + kind, "direction": side,
                    "call": "CONSOLIDATION" if consolidation else "INTRADAY",
                    # What the level is, on its own, for the card's second line.
                    "level_name": what[:1].upper() + what[1:],
                    "headline": f"{verb.lower()} {level:,.2f}, {what}",
                    "level": round(level, 2), "price": round(px, 2),
                    "rvol": round(vol_x, 1), "day_rvol": round(pace, 1),
                    "range_pos": None, "vwap": round(vwap, 2) if vwap else None,
                    "entry": round(px, 2), "stop": round(stop, 2),
                    "t1": round(px + sign * risk, 2), "target": round(px + sign * RR * risk, 2),
                    "rr": round(RR, 1), "risk_pct": round(risk_pct, 2),
                    "move_pct": round(move, 2), "score": score, "regime": index_pct,
                    "sector": lv.get("sector"), "why": why,
                    "outcome": None, "closed_at": None,
                })
        d["seen"].update(s for s in snap if s in d["row"])
        d["waiting"] = waiting
    return sorted(out, key=lambda a: -a["score"])


# ---------------------------------------------------------------------------
# What the page reads
# ---------------------------------------------------------------------------

def rules():
    return {
        "levels": "yesterday's high or low, the 20-day and 52-week extremes, the edge of a base, "
                  "the opening range, and a tight intraday range",
        "fires": (f"the price is through the level by {BUFFER_PCT:g}%, the last five minutes traded "
                  f"{SURGE:g}x their usual volume, and it is on the right side of VWAP"),
        "risk": (f"stop {MIN_RISK:g}% to {MAX_RISK:g}% away, target {RR:g} times the risk, "
                 "next level at least one risk away"),
        "window": "09:20 to 15:00, one alert per stock per direction a day",
        "universe": f"the {UNIVERSE} most-traded stocks, at least Rs {MIN_TURNOVER_CR:g} crore a day",
    }


def status(now=None):
    now = now or now_ist()
    today = now.date().isoformat()
    feed = _feed()
    d = _mem["day"] if (_mem["day"] and _mem["day"]["day"] == today) else None
    tape_min = round((d["t"][d["n"] - 1] - d["t"][0]) / 60.0) if d and d["n"] > 1 else 0
    return {
        "enabled": ENABLED,
        "asof": feed.get("asof"),
        "built_at": feed.get("built_at"),
        "usable": _usable(feed, today),
        "stocks": len(feed.get("levels") or {}),
        "near": (feed.get("near") or [])[:20],
        "waiting": list((d or {}).get("waiting", {}).values())[:12],
        "passes_today": d["passes"] if d else 0,
        "last_pass": d["last"] if d else None,
        "tape_minutes": tape_min,
        "opening_ranges": len(d["orb"]) if d else 0,
        "rules": rules(),
        "session_live": session_live(now),
        "telegram": notify.health() if notify is not None else {"configured": False},
    }


def sample():
    """A made-up alert in the live shape, for the Telegram test."""
    return {"date": "", "time": "10:42", "symbol": "TESTMSG", "kind": "BO_BASE", "direction": "UP",
            "call": "CONSOLIDATION", "level_name": "The top of a 64-day consolidation",
            "headline": "crossed above 412.50, the top of a 64-day consolidation",
            "level": 412.50, "price": 414.10, "rvol": 2.6, "day_rvol": 1.4, "range_pos": None,
            "vwap": 410.85, "entry": 414.10, "stop": 411.25, "t1": 416.95, "target": 419.80,
            "rr": 2.0, "risk_pct": 0.69, "move_pct": 1.8, "score": 74, "regime": 0.35,
            "sector": "Power",
            "why": ("Crossed above 412.50, the top of a 64-day consolidation, on 2.6 times its "
                    "normal volume. Exit by 3:15 pm."),
            "outcome": None, "closed_at": None}
