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

TWO LANES
---------
Every pass runs two sets of rules over the same quotes, so the second one
costs no extra request:

    CLASSIC   the rules above, exactly as they were. intraday.py caps it at
              MAX_ALERTS_DAY calls; 09:20 to 15:00; a break is a call on the
              first pass that shows it. The BO_* variables.

    ★ SELECT  fewer, stronger calls spread across the session. The BOS_*
              variables. On top of the Classic tests:
      - HELD      the break must still be through the level on the next
                  pass (BOS_CONFIRM_PASSES), and a pass only counts once
                  BOS_CONFIRM_MIN_GAP_SEC (15 s) have gone since the last one
                  that did, so one wick through the level at 09:31 is not a
                  call, and neither is an extra pass a second later;
      - OWN VOLUME  the last five minutes are compared with what THIS stock
                  trades in those five minutes (its own profile, built from
                  its last five sessions), not with one curve for every stock;
      - QUALITY   high in the day's range, not stretched far past VWAP, not
                  buying into a wall of resting sell orders, its sector not
                  falling against it, and yesterday's high on its own needs
                  more volume than a base does;
      - TWO SETUPS the day makes later on: a fresh day high (or low) broken
                  after a 30-minute pause that held VWAP, and a pullback to
                  VWAP that breaks back out of its 15-minute high;
      - A BUDGET  3 calls in the opening hour, 3 mid-morning, 3 in the
                  afternoon, 8 a day, at most 2 at once and 2 per sector, so
                  the morning cannot spend the whole day.

Each call carries its lane (`engine`), and each lane keeps its own record,
so the log measures one against the other on the same days. When both lanes
call the same break, intraday.py sends one card, not two.

THE DAY'S MEMORY
----------------
The tape covers the whole session (BO_TAPE passes). Every few minutes it is
written to DATA_DIR/breakout_day.npz with the opening ranges, the day's
highs and lows and each lane's state, so a restart or a redeploy carries on
from where it was instead of starting the day blind.

Every threshold is an environment variable, so it can be tuned on Render
without a redeploy.
"""

import csv
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


def _opt_f(name):
    """A number when the variable is set, else None: the Select lane then
    uses the Classic value, so one change moves both."""
    v = os.environ.get(name, "").strip()
    if not v:
        return None
    try:
        return float(v)
    except ValueError:
        return None


def _opt_b(name):
    v = os.environ.get(name, "").strip().lower()
    if not v:
        return None
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
# Passes kept: 1200 at 20 seconds is 6 h 40 min, the whole 09:15-15:30
# session, so the day's morning is still on the tape in the afternoon.
TAPE = max(60, _i("BO_TAPE", 1200))

# What the Select lane switched on, here for Classic: every one off, which
# is today's behaviour. Each can be turned on for Classic too.
CONFIRM_PASSES = _i("BO_CONFIRM_PASSES", 1)       # passes a break must hold before it is a call
# A pass counts towards holding a break only this many seconds after the one
# that last counted: an extra pass a second after the loop's (the owner's
# "Scan once now", a cron tick) is not a second look at the break.
CONFIRM_MIN_GAP_SEC = _f("BO_CONFIRM_MIN_GAP_SEC", 15.0)
USE_PROFILE = _b("BO_USE_PROFILE", False)         # the stock's own 5-minute volume profile
MIN_RPOS = _f("BO_MIN_RPOS", 0.0)                 # share of the day's range below the price (0 = off)
MIN_RPOS_VWAP = _f("BO_MIN_RPOS_VWAP", 0.0)       # the same for a VWAP pullback, which sits lower
MAX_VWAP_EXT = _f("BO_MAX_VWAP_EXT", 0.0)         # percent past VWAP allowed (0 = off)
MAX_BOOK_AGAINST = _f("BO_MAX_BOOK_AGAINST", 0.0)  # resting orders against / for: score penalty
BOOK_REJECT = _f("BO_BOOK_REJECT", 0.0)           # ... and refused outright past this
SECTOR_AGAINST = _f("BO_SECTOR_AGAINST", 0.0)     # sector median percent against the call (0 = off)
PDH_STRICT = _b("BO_PDH_STRICT", False)           # yesterday's high alone needs more volume
PDH_SURGE = _f("BO_PDH_SURGE", 3.0)
PDH_PACE = _f("BO_PDH_PACE", 1.1)
HOD_SETUP = _b("BO_HOD", False)                   # fresh day-high / day-low re-break
VWAP_SETUP = _b("BO_VWAP", False)                 # VWAP pullback and reclaim
MONEY_FLOW = _b("BO_MONEY_FLOW", False)           # +/-5 for the sector's money-flow quadrant
REENTRY = _b("BO_REENTRY", False)                 # a second call later in the day on a day-made setup
MAX_DAY = _i("BO_MAX_DAY", 0)                     # 0: intraday.MAX_ALERTS_DAY caps Classic
SLOT_OPEN = _i("BO_SLOT_OPEN", 0)                 # calls per session window (0 = no budget)
SLOT_MID = _i("BO_SLOT_MID", 0)
SLOT_PM = _i("BO_SLOT_PM", 0)
MAX_PER_PASS = _i("BO_MAX_PER_PASS", 0)
MAX_PER_SECTOR = _i("BO_MAX_PER_SECTOR", 0)
MAX_PER_SECTOR_PASS = _i("BO_MAX_PER_SECTOR_PASS", 0)

# The two setups the day makes after the open, for whichever lane uses them.
HOD_FROM_MIN = _i("BO_HOD_FROM_MIN", 75)          # 10:30
HOD_PAUSE_MIN = _i("BO_HOD_PAUSE_MIN", 30)        # the old extreme must be this old
VWAP_FROM_MIN = _i("BO_VWAP_FROM_MIN", 45)        # 10:00
VWAP_TO_MIN = _i("BO_VWAP_TO_MIN", 315)           # 14:30
VWAP_TREND = _f("BO_VWAP_TREND", 0.8)             # percent the stock must be up (down) on the day
VWAP_TOUCH = _f("BO_VWAP_TOUCH", 0.35)            # how near VWAP the pullback came, percent
VWAP_HOLD = _f("BO_VWAP_HOLD", 0.15)              # how far through VWAP it may poke and still hold
VWAP_LOOK_MIN = _i("BO_VWAP_LOOK_MIN", 30)        # the pullback happened within this many minutes
VWAP_STOP = _f("BO_VWAP_STOP", 0.25)              # stop this far across VWAP, percent
SECTOR_MIN_N = _i("BO_SECTOR_MIN_N", 3)           # quoted stocks a sector needs for a median
CHECKPOINT_SEC = _i("BO_CHECKPOINT_SEC", 180)     # how often the day's memory is written (0 = never)
RESTORE_GAP_MIN = _f("BO_RESTORE_GAP_MIN", 10.0)  # a longer blind gap restores without "seen"
PROFILE_MAX_AGE = _i("BO_PROFILE_MAX_AGE", 7)     # days a volume profile stays usable

# Which lanes run. BO_LANES=classic keeps only today's alerts.
_want = (os.environ.get("BO_LANES", "").strip().lower() or "classic,select").replace(" ", "").split(",")
LANES = tuple(n for n in ("classic", "select") if n in _want)

# The Select lane. None means "the Classic value".
SELECT = {
    "UNIVERSE": _i("BOS_UNIVERSE", 250),          # the most liquid of the watch list
    "SURGE": _f("BOS_SURGE", 2.5),
    "MIN_SCORE": _i("BOS_MIN_SCORE", 66),
    "START_MIN": _i("BOS_START_MIN", 10),         # 09:25: the opening whipsaw is skipped
    "END_MIN": _i("BOS_END_MIN", 330),            # 14:45: 30 minutes before the 15:15 exit
    "MAX_DAY": _i("BOS_MAX_DAY", 8),
    "SLOT_OPEN": _i("BOS_SLOT_OPEN", 3),          # 09:25-10:15
    "SLOT_MID": _i("BOS_SLOT_MID", 3),            # 10:15-12:30
    "SLOT_PM": _i("BOS_SLOT_PM", 3),              # 12:30-14:45
    "MID_FROM": _i("BOS_MID_FROM", 60),           # 10:15
    "PM_FROM": _i("BOS_PM_FROM", 195),            # 12:30
    "MAX_PER_PASS": _i("BOS_MAX_PER_PASS", 2),
    "MAX_PER_SECTOR": _i("BOS_MAX_PER_SECTOR", 2),
    "MAX_PER_SECTOR_PASS": _i("BOS_MAX_PER_SECTOR_PASS", 1),
    "CONFIRM_PASSES": _i("BOS_CONFIRM_PASSES", 2),
    "CONFIRM_MIN_GAP_SEC": _f("BOS_CONFIRM_MIN_GAP_SEC", 15.0),   # seconds between passes that count
    "USE_PROFILE": _b("BOS_USE_PROFILE", True),
    "MIN_RPOS": _f("BOS_MIN_RPOS", 0.72),
    "MIN_RPOS_VWAP": _f("BOS_MIN_RPOS_VWAP", 0.50),
    "MAX_VWAP_EXT": _f("BOS_MAX_VWAP_EXT", 1.6),
    "MAX_BOOK_AGAINST": _f("BOS_MAX_BOOK_AGAINST", 3.0),
    "BOOK_REJECT": _f("BOS_BOOK_REJECT", 6.0),
    "SECTOR_AGAINST": _f("BOS_SECTOR_AGAINST", 0.6),
    "PDH_STRICT": _b("BOS_PDH_STRICT", True),
    "PDH_SURGE": _f("BOS_PDH_SURGE", 3.0),
    "PDH_PACE": _f("BOS_PDH_PACE", 1.1),
    "HOD": _b("BOS_HOD", True),
    "VWAP": _b("BOS_VWAP", True),
    "MONEY_FLOW": _b("BOS_MONEY_FLOW", True),
    "REENTRY": _b("BOS_REENTRY", True),
    # Shared with Classic unless set on their own.
    "BUFFER_PCT": _opt_f("BOS_BUFFER_PCT"), "PACE_FLOOR": _opt_f("BOS_PACE_FLOOR"),
    "CHASE_MIN": _opt_f("BOS_CHASE_MIN"), "CHASE_PCT": _opt_f("BOS_CHASE_PCT"),
    "MIN_RISK": _opt_f("BOS_MIN_RISK"), "MAX_RISK": _opt_f("BOS_MAX_RISK"),
    "RR": _opt_f("BOS_RR"), "ROOM_R": _opt_f("BOS_ROOM_R"), "REGIME": _opt_f("BOS_REGIME"),
    "SHORTS": _opt_b("BOS_SHORTS"),
}

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("DATA_DIR", "").strip() or HERE
try:
    os.makedirs(DATA_DIR, exist_ok=True)
except Exception:
    DATA_DIR = HERE
FEED_FILE = os.path.join(DATA_DIR, "breakout_feed.json")
DAY_FILE = os.path.join(DATA_DIR, "breakout_day.npz")          # the session's memory
PROFILE_FILE = os.path.join(DATA_DIR, "bo_vol_profiles.json")  # each stock's own volume curve
SECTORS_FILE = os.path.join(HERE, "nse_industries.csv")

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))

# How much a level matters, and what it is called in a sentence.
SIG = {"BASE_LONG": 5, "BASE": 4, "HIGH52": 4, "LOW52": 4, "HIGH20": 3, "LOW20": 3,
       "RANGE": 3, "ORB": 2, "PDH": 2, "PDL": 2,
       "HOD": 3, "LOD": 3, "VWAP": 3, "VWAP_DN": 3}
WORDS = {"BASE": "the top of its consolidation", "HIGH52": "its 52-week high",
         "HIGH20": "its 20-day high", "PDH": "yesterday's high",
         "ORB": "the high of the first 15 minutes", "RANGE": "a tight intraday range",
         "BASE_DN": "the bottom of its consolidation", "LOW52": "its 52-week low",
         "LOW20": "its 20-day low", "PDL": "yesterday's low",
         "ORB_DN": "the low of the first 15 minutes", "RANGE_DN": "a tight intraday range",
         # Plain words on purpose: these reach a phone, not a trading desk.
         "HOD": "today's high", "LOD": "today's low",
         "VWAP": "the 15-minute high, after a pullback to the day's average price",
         "VWAP_DN": "the 15-minute low, after a bounce to the day's average price"}
# The short tag the Alerts page puts on each call.
SETUP = {"BASE": "Base breakout", "BASE_DN": "Base breakdown",
         "HIGH52": "52-week high", "LOW52": "52-week low",
         "HIGH20": "20-day high", "LOW20": "20-day low",
         "PDH": "Yesterday's high", "PDL": "Yesterday's low",
         "ORB": "Opening range", "ORB_DN": "Opening range",
         "RANGE": "Tight range", "RANGE_DN": "Tight range",
         "HOD": "Fresh day high", "LOD": "Fresh day low",
         "VWAP": "VWAP reclaim", "VWAP_DN": "VWAP rejection"}
# Levels the day makes as it goes. They are not "through it before today",
# and they cannot have been gapped through at the open.
DYNAMIC = ("HOD", "LOD", "VWAP", "VWAP_DN")
QUADRANTS = ("Leading", "Improving", "Weakening", "Lagging")
# NSE's industry names, as a badge has room for them.
SECTOR_SHORT = {"Automobile and Auto Components": "Auto", "Fast Moving Consumer Goods": "FMCG",
                "Information Technology": "IT", "Oil Gas & Consumable Fuels": "Oil & Gas",
                "Financial Services": "Financials", "Consumer Services": "Consumer",
                "Consumer Durables": "Durables", "Construction Materials": "Cement",
                "Metals & Mining": "Metals", "Capital Goods": "Capital goods",
                "Telecommunication": "Telecom", "Media Entertainment & Publication": "Media",
                "Forest Materials": "Forest"}
SLOT_LABEL = {"open": "Opening", "mid": "Mid-morning", "pm": "Afternoon"}


def sector_short(name):
    return SECTOR_SHORT.get(name, name) if name else name

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


_SECTORS = {"map": None}


def _csv_sectors():
    """{SYMBOL: NSE industry} from the copy of NSE's list shipped with the
    code. Read once; {} if it is unreadable."""
    if _SECTORS["map"] is None:
        out = {}
        try:
            with open(SECTORS_FILE, encoding="utf-8") as fh:
                for row in csv.DictReader(fh):
                    row = {(k or "").strip(): (v or "").strip() for k, v in row.items()}
                    if row.get("Symbol") and row.get("Industry"):
                        out[row["Symbol"].upper()] = row["Industry"]
        except Exception:
            pass
        _SECTORS["map"] = out
    return _SECTORS["map"]


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
    # The scan hands over each stock's sector; a morning rebuild has none to
    # give, and without it every sector rule would quietly switch itself off.
    # NSE's own industry list ships with the code, so it fills the gap.
    sectors = _csv_sectors()
    for sym, r in pool:
        b = r.get("base")
        levels[sym] = {"c": r["close"], "atr": r["atr_pct"], "v": r["vol_med50"],
                       "up": _ladder(r, True), "dn": _ladder(r, False),
                       "base": ({"n": b["sessions"], "w": b["width_pct"]} if b else None),
                       "sector": (meta.get(sym) or {}).get("sector") or sectors.get(sym)}
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
        # The day's memory is kept: _day() sees the new levels and carries the
        # tape, the opening ranges and each lane's state across to them. A
        # rebuild at 10:40 used to wipe all three and start the day blind.
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


# ---------------------------------------------------------------------------
# Lanes
# ---------------------------------------------------------------------------

def _cfg(name):
    """One lane's rules. Classic reads this module's values when it is
    called, so a change (or a test's patch) takes effect at once; Select
    starts from the same values and overrides them with SELECT."""
    c = {"name": name, "label": "Classic",
         "UNIVERSE": UNIVERSE, "BUFFER_PCT": BUFFER_PCT, "SURGE": SURGE,
         "PACE_FLOOR": PACE_FLOOR, "CHASE_MIN": CHASE_MIN, "CHASE_PCT": CHASE_PCT,
         "MIN_RISK": MIN_RISK, "MAX_RISK": MAX_RISK, "RR": RR, "ROOM_R": ROOM_R,
         "REGIME": REGIME, "MIN_SCORE": MIN_SCORE, "SHORTS": SHORTS,
         "START_MIN": START_MIN, "END_MIN": END_MIN,
         "CONFIRM_PASSES": CONFIRM_PASSES, "CONFIRM_MIN_GAP_SEC": CONFIRM_MIN_GAP_SEC,
         "USE_PROFILE": USE_PROFILE,
         "MIN_RPOS": MIN_RPOS, "MIN_RPOS_VWAP": MIN_RPOS_VWAP, "MAX_VWAP_EXT": MAX_VWAP_EXT,
         "MAX_BOOK_AGAINST": MAX_BOOK_AGAINST, "BOOK_REJECT": BOOK_REJECT,
         "SECTOR_AGAINST": SECTOR_AGAINST, "PDH_STRICT": PDH_STRICT,
         "PDH_SURGE": PDH_SURGE, "PDH_PACE": PDH_PACE,
         "HOD": HOD_SETUP, "VWAP": VWAP_SETUP, "MONEY_FLOW": MONEY_FLOW, "REENTRY": REENTRY,
         "MAX_DAY": MAX_DAY, "SLOT_OPEN": SLOT_OPEN, "SLOT_MID": SLOT_MID, "SLOT_PM": SLOT_PM,
         "MID_FROM": SELECT.get("MID_FROM") or 60, "PM_FROM": SELECT.get("PM_FROM") or 195,
         "MAX_PER_PASS": MAX_PER_PASS, "MAX_PER_SECTOR": MAX_PER_SECTOR,
         "MAX_PER_SECTOR_PASS": MAX_PER_SECTOR_PASS}
    if name == "select":
        c["label"] = "★ Select"
        for k, v in SELECT.items():
            if v is not None:
                c[k] = v
    return c


def _hhmm(mso):
    m = 555 + int(round(mso))
    return f"{m // 60:02d}:{m % 60:02d}"


def _clock12(stamp):
    """An epoch second as '10:42 am'."""
    try:
        t = dt.datetime.fromtimestamp(float(stamp), IST)
    except (TypeError, ValueError, OverflowError, OSError):
        return ""
    return f"{(t.hour - 1) % 12 + 1}:{t.minute:02d} {'am' if t.hour < 12 else 'pm'}"


def window_of(mso):
    """Which part of the session `mso` minutes after the open falls in:
    early (before 09:25), open (to 10:15), mid (to 12:30), pm (to 14:45),
    late. The Select lane's budget is spent per window."""
    s = _cfg("select")
    if mso < s["START_MIN"]:
        return "early"
    if mso < s["MID_FROM"]:
        return "open"
    if mso < s["PM_FROM"]:
        return "mid"
    if mso < s["END_MIN"]:
        return "pm"
    return "late"


def _slot_key(win):
    """The budget a window spends: the minutes either side of the slots
    count against the nearest one."""
    return {"early": "open", "open": "open", "mid": "mid", "pm": "pm", "late": "pm"}.get(win)


def _engine(a):
    return (a.get("engine") or "classic") if isinstance(a, dict) else "classic"


# ---------------------------------------------------------------------------
# The day's memory
# ---------------------------------------------------------------------------

def _new_day(today, feed):
    syms = list(feed["levels"].keys())
    n = len(syms)
    return {"day": today, "asof": feed.get("asof"), "feed": feed, "syms": syms,
            "row": {s: i for i, s in enumerate(syms)},
            "t": np.zeros(TAPE), "n": 0,
            "px": np.full((n, TAPE), np.nan, dtype=np.float32),
            "vol": np.full((n, TAPE), np.nan, dtype=np.float32),
            "vw": np.full((n, TAPE), np.nan, dtype=np.float32),
            "orb": {}, "orb_done": False, "seen": set(), "hod": {}, "lod": {},
            "lanes": {}, "sectors": {}, "passes": 0, "last": None,
            "saved_t": 0.0, "saved_at": None, "restored": None,
            # Checks that failed on one stock (bad data, a bug): counted for
            # the page, while the pass goes on with every other stock.
            "errors": {"n": 0, "last": None, "at": None}}


def _lane(d, name):
    """One lane's working state for the day: the levels armed and how many
    passes each has held, the ones that are dead or were chased, what is
    waiting and why, the calls made, and which gate held which stock."""
    L = d["lanes"].get(name)
    if L is None:
        L = d["lanes"][name] = {"armed": {}, "dead": set(), "late": {}, "rconf": {},
                                "waiting": {}, "emitted": [], "gates": {}, "since": {}}
    return L


def _day(today, feed, now=None):
    """The session's working memory, rebuilt each morning, carried across a
    restart from the checkpoint and across a mid-session rebuild of the
    levels from memory."""
    d = _mem["day"]
    if d is not None and d["day"] == today and d["asof"] == feed.get("asof"):
        if d.get("feed") is feed:
            return d
        if d["syms"] == list(feed["levels"].keys()):
            # The same stocks, their levels rebuilt: whatever is new on a
            # stock's ladder is checked against where its price already is.
            before = _ladder_levels(d.get("feed"))
            d["feed"] = feed
            try:
                _new_levels(d, before, feed)
            except Exception:
                pass
            return d
    nd = _new_day(today, feed)
    src = d if (d is not None and d["day"] == today) else _load_day(today)
    if src is not None:
        try:
            _carry(nd, src, (now or now_ist()).timestamp())
        except Exception:
            nd, src = _new_day(today, feed), None
    if src is not None:
        try:
            # What the day traded before: the old feed in memory, or the
            # ladders the checkpoint kept (None from an older checkpoint).
            before = _ladder_levels(src["feed"]) if src.get("feed") else src.get("ladders")
            _new_levels(nd, before, feed)
        except Exception:
            pass
    _mem["day"] = nd
    return nd


def _ladder_levels(feed):
    """{SYMBOL: [up levels, down levels]}: the prices a feed's ladders trade."""
    out = {}
    for sym, lv in ((feed or {}).get("levels") or {}).items():
        try:
            out[sym] = [sorted({float(x["l"]) for x in lv.get("up") or ()}),
                        sorted({float(x["l"]) for x in lv.get("dn") or ()})]
        except (TypeError, ValueError, KeyError, AttributeError):
            continue
    return out


def _last_px(d, r):
    """The last price the tape has for row `r`, or None."""
    n = int(d.get("n") or 0)
    if r is None or n <= 0:
        return None
    row = d["px"][r, :n]
    hit = np.flatnonzero(np.isfinite(row))
    return float(row[hit[-1]]) if hit.size else None


def _old_news(d, sym, side, levels, bufs):
    """A level the day learns of after the session started (the levels
    rebuilt at 10:40, an opening range backfilled from candles) may have been
    crossed long before. Where the tape's last price is already through it,
    it is dead in every lane, as a first look at the stock would have found
    it: not a fresh break. A stock with no price on the tape gets that first
    look on its next pass. `bufs` is {lane: BUFFER_PCT}."""
    px = _last_px(d, d["row"].get(sym))
    if px is None:
        d["seen"].discard(sym)
        return 0
    sign = 1 if side == "UP" else -1
    n = 0
    for name, buf in bufs.items():
        L = _lane(d, name)
        armed = L["armed"].get((sym, side)) or {}
        for lvl in levels:
            if lvl not in armed and sign * (px - lvl * (1 + sign * buf / 100)) >= 0:
                L["dead"].add((sym, side, lvl))
                n += 1
    return n


def _new_levels(d, before, feed):
    """The levels a stock's ladder gained over `before` ({SYMBOL: [up, dn]},
    what the day traded until now), each checked by _old_news. With `before`
    None nothing is known to be new, and nothing is marked."""
    if before is None:
        return 0
    bufs = {name: _cfg(name)["BUFFER_PCT"] for name in LANES}
    n = 0
    for sym, (up, dn) in _ladder_levels(feed).items():
        old = before.get(sym)
        for side, levels, k in (("UP", up, 0), ("DOWN", dn, 1)):
            try:
                had = {float(x) for x in old[k]} if old else set()
            except (TypeError, ValueError, IndexError, KeyError):
                had = set()                  # unreadable: every level is checked
            new = [lvl for lvl in levels if lvl not in had]
            if new:
                n += _old_news(d, sym, side, new, bufs)
    return n


def _carry(nd, src, t_now):
    """Bring a day across: the tape of every stock in both lists, the
    opening ranges, the day's extremes and every lane's state."""
    n = int(src.get("n") or 0)
    k = min(n, TAPE)
    if k > 0 and float(np.asarray(src["t"], dtype=float)[n - 1]) > t_now:
        k = 0                                # a tape from "the future" (a clock jump) is not spliced in
    if k > 0:
        lo = n - k
        nd["t"][:k] = np.asarray(src["t"], dtype=float)[lo:n]
        for sym, r_new in nd["row"].items():
            r_old = src["row"].get(sym)
            if r_old is None:
                continue
            for key in ("px", "vol", "vw"):
                arr = src.get(key)
                if arr is not None and r_old < arr.shape[0]:
                    nd[key][r_new, :k] = arr[r_old, lo:n]
        nd["n"] = k
    nd["passes"] = int(src.get("passes") or 0)
    nd["last"] = src.get("last")
    rows = nd["row"]
    nd["orb"] = {s: (float(v[0]), float(v[1])) for s, v in (src.get("orb") or {}).items() if s in rows}
    nd["orb_done"] = bool(src.get("orb_done"))
    nd["hod"] = {s: [float(v[0]), float(v[1])] for s, v in (src.get("hod") or {}).items() if s in rows}
    nd["lod"] = {s: [float(v[0]), float(v[1])] for s, v in (src.get("lod") or {}).items() if s in rows}
    nd["lanes"] = src.get("lanes") or {}
    nd["saved_t"] = float(src.get("saved_t") or 0.0)
    nd["saved_at"] = src.get("saved_at")
    if isinstance(src.get("errors"), dict):
        nd["errors"] = dict(src["errors"])
    if src.get("from_disk"):
        gap = max(0.0, (t_now - nd["saved_t"]) / 60.0)
        # After a long blind gap a stock may have broken out while nobody
        # watched. Forgetting which stocks were seen makes the first look
        # treat anything already through a level as old news, as it did
        # before there was a checkpoint.
        nd["seen"] = set(src.get("seen") or ()) if gap <= RESTORE_GAP_MIN else set()
        nd["restored"] = {"from": src.get("last"), "gap_min": round(gap, 1)}
    else:
        nd["seen"] = set(src.get("seen") or ())
        nd["restored"] = src.get("restored")


def _lane_blob(L):
    # Each armed level: [symbol, side, level, armed at, passes, trigger, last pass counted].
    return {"armed": [[s, sd, float(lvl), float(e["t"]), int(e["n"]), e.get("trig"),
                       float(e.get("c") or e["t"])]
                      for (s, sd), m in L["armed"].items() for lvl, e in m.items()],
            "dead": [[s, sd, float(lvl)] for s, sd, lvl in L["dead"]],
            "late": [[s, sd, sorted(float(x) for x in v)] for (s, sd), v in L["late"].items() if v],
            "rconf": [[s, sd, float(e["l"]), int(e["n"]), int(e["p"]), float(e.get("c") or 0.0)]
                      for (s, sd), e in L["rconf"].items()],
            "emitted": list(L["emitted"])[-200:],
            "gates": {code: [list(k) for k in v] for code, v in L["gates"].items()}}


def _lane_from(blob):
    L = {"armed": {}, "dead": set(), "late": {}, "rconf": {},
         "waiting": {}, "emitted": [], "gates": {}, "since": {}}
    # A checkpoint written before the last-counted time was kept has six
    # fields an armed level and five a range; the time then is the arming.
    for row in blob.get("armed") or []:
        s, sd, lvl, t0, n, trig = row[:6]
        tc = row[6] if len(row) > 6 and row[6] is not None else t0
        L["armed"].setdefault((s, sd), {})[float(lvl)] = {"t": float(t0), "n": int(n), "trig": trig,
                                                          "c": float(tc)}
    for s, sd, lvl in blob.get("dead") or []:
        L["dead"].add((s, sd, float(lvl)))
    for s, sd, lv in blob.get("late") or []:
        L["late"][(s, sd)] = {float(x) for x in lv}
    for row in blob.get("rconf") or []:
        s, sd, lvl, n, p = row[:5]
        tc = row[5] if len(row) > 5 and row[5] is not None else 0.0
        L["rconf"][(s, sd)] = {"l": float(lvl), "n": int(n), "p": int(p), "c": float(tc)}
    L["emitted"] = [e for e in blob.get("emitted") or [] if isinstance(e, dict)]
    for code, v in (blob.get("gates") or {}).items():
        L["gates"][code] = {tuple(k) for k in v}
    return L


def _save_day(d, now):
    """Write the day's memory: tmp file, then one rename, so a crash mid-
    write leaves the previous checkpoint whole."""
    d["saved_t"] = now.timestamp()
    if not DAY_FILE:
        return
    n = d["n"]
    meta = {"v": 1, "day": d["day"], "asof": d["asof"], "syms": d["syms"], "n": n,
            "passes": d["passes"], "last": d["last"],
            "orb": {s: [float(v[0]), float(v[1])] for s, v in d["orb"].items()},
            "orb_done": d["orb_done"], "seen": sorted(d["seen"]),
            "hod": {s: [float(v[0]), float(v[1])] for s, v in d["hod"].items()},
            "lod": {s: [float(v[0]), float(v[1])] for s, v in d["lod"].items()},
            "saved_t": d["saved_t"], "saved_at": now.strftime("%H:%M:%S"),
            "lanes": {name: _lane_blob(L) for name, L in d["lanes"].items()},
            # The levels the day was trading, so a restart onto levels rebuilt
            # meanwhile can tell which of them are new (_new_levels).
            "ladders": _ladder_levels(d.get("feed"))}
    tmp = DAY_FILE + ".tmp"
    try:
        raw = json.dumps(meta).encode("utf-8")
        with open(tmp, "wb") as fh:
            np.savez(fh, t=d["t"][:n], px=d["px"][:, :n], vol=d["vol"][:, :n],
                     vw=d["vw"][:, :n], meta=np.frombuffer(raw, dtype=np.uint8))
        os.replace(tmp, DAY_FILE)
        d["saved_at"] = meta["saved_at"]
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass


def _load_day(today):
    """Today's checkpoint, or None (another day's, unreadable, or none)."""
    if not DAY_FILE or not os.path.exists(DAY_FILE):
        return None
    try:
        with np.load(DAY_FILE, allow_pickle=False) as z:
            meta = json.loads(z["meta"].tobytes().decode("utf-8"))
            if meta.get("day") != today:
                return None
            src = {"t": np.asarray(z["t"], dtype=float), "px": np.asarray(z["px"], dtype=np.float32),
                   "vol": np.asarray(z["vol"], dtype=np.float32),
                   "vw": np.asarray(z["vw"], dtype=np.float32)}
        syms = list(meta.get("syms") or [])
        n = int(meta.get("n") or 0)
        if src["px"].shape != (len(syms), n) or src["t"].size != n:
            return None
        src.update(row={s: i for i, s in enumerate(syms)}, n=n,
                   passes=meta.get("passes"), last=meta.get("last"), orb=meta.get("orb"),
                   orb_done=meta.get("orb_done"), seen=meta.get("seen"), hod=meta.get("hod"),
                   lod=meta.get("lod"), saved_t=meta.get("saved_t"), saved_at=meta.get("saved_at"),
                   from_disk=True,
                   ladders=meta.get("ladders") if isinstance(meta.get("ladders"), dict) else None,
                   lanes={name: _lane_from(b) for name, b in (meta.get("lanes") or {}).items()})
        return src
    except Exception:
        return None


def _push(d, snap, stamp):
    if d["n"] == TAPE:                       # full: drop the oldest quarter
        k = TAPE // 4
        d["t"][:-k] = d["t"][k:]
        for key in ("px", "vol", "vw"):
            d[key][:, :-k] = d[key][:, k:]
            d[key][:, -k:] = np.nan
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
                vw = float(q.get("vwap") or 0)
                if vw > 0:
                    d["vw"][r, i] = vw
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


def _extremes(d, snap, t_now):
    """The day's high and low for every stock, and when each was set: the
    fresh-day-high setup needs to know how long the old high has stood."""
    for sym, q in snap.items():
        if sym not in d["row"] or not q:
            continue
        hi, lo = _num(q, "high"), _num(q, "low")
        if hi > 0:
            cur = d["hod"].get(sym)
            if cur is None or hi > cur[0] * (1 + 1e-6):
                d["hod"][sym] = [hi, float(t_now)]
        if lo > 0:
            cur = d["lod"].get(sym)
            if cur is None or lo < cur[0] * (1 - 1e-6):
                d["lod"][sym] = [lo, float(t_now)]


def _sector_moves(feed, snap):
    """{sector: (median percent move today, stocks quoted)} straight from the
    pass's own quotes, for sectors with SECTOR_MIN_N stocks or more."""
    groups = {}
    for sym, lv in feed["levels"].items():
        sec, q = lv.get("sector"), snap.get(sym)
        if not sec or not q:
            continue
        px, pc = _num(q, "ltp"), _num(q, "prev_close")
        if px > 0 and pc > 0:
            groups.setdefault(sec, []).append((px / pc - 1) * 100)
    return {s: (float(np.median(v)), len(v)) for s, v in groups.items() if len(v) >= SECTOR_MIN_N}


# ---------------------------------------------------------------------------
# Each stock's own volume profile, and the sectors' money flow
# ---------------------------------------------------------------------------

def _profiles():
    p = _mem.get("prof")
    if p is None:
        blob = _read_json(PROFILE_FILE, {}) or {}
        p = {"built_for": blob.get("built_for"), "built_at": blob.get("built_at"),
             "map": blob.get("profiles") or {}, "xy": None}
        _mem["prof"] = p
    return p


def _fresh_enough(built_for, today):
    try:
        age = (dt.date.fromisoformat(today) - dt.date.fromisoformat(built_for)).days
    except (TypeError, ValueError):
        return False
    return 0 <= age <= PROFILE_MAX_AGE


def _prof_xy(today):
    """{SYMBOL: (minutes, cumulative volume)} ready for np.interp, from
    profiles young enough to describe this week's trading."""
    p = _profiles()
    if not p["map"] or not _fresh_enough(p.get("built_for"), today):
        return {}
    if p.get("xy") is None:
        xy = {}
        for sym, vals in p["map"].items():
            ms, vs = [0.0], [0.0]
            for k, v in enumerate(vals or []):
                try:
                    v = float(v)
                except (TypeError, ValueError):
                    continue
                if v > 0 and v >= vs[-1]:
                    ms.append(5.0 * (k + 1))
                    vs.append(v)
            if len(ms) >= 20:                # most of a session, or it is not a profile
                xy[sym] = (np.asarray(ms), np.asarray(vs))
        p["xy"] = xy
    return p["xy"]


def profile_symbols():
    """The stocks that want their own volume profile: the universe of every
    lane that measures volume that way, most traded first."""
    syms = universe()
    n = 0
    for name in LANES:
        c = _cfg(name)
        if c["USE_PROFILE"]:
            n = max(n, int(c["UNIVERSE"]))
    return syms[:n]


def profiles_fresh(now=None):
    """True when the stored profiles were built from the sessions up to the
    last close."""
    return _profiles().get("built_for") == last_close(now).isoformat()


def save_profiles(profiles, built_for):
    """Store {SYMBOL: [median cumulative volume at 09:20, 09:25 ... 15:30]}
    (75 numbers, by the END of each five-minute bar) for the live loop."""
    clean = {}
    for sym, vals in (profiles or {}).items():
        if isinstance(vals, (list, tuple)) and len(vals) == 75:
            row = []
            for v in vals:
                try:
                    row.append(None if v is None else round(float(v), 1))
                except (TypeError, ValueError):
                    row.append(None)
            clean[str(sym).upper()] = row
    now = now_ist()
    blob = {"built_for": built_for, "built_at": now.isoformat(timespec="minutes"), "profiles": clean}
    _write_json(PROFILE_FILE, blob)
    _mem["prof"] = {"built_for": built_for, "built_at": blob["built_at"], "map": clean, "xy": None}


def set_money_flow(quadrants, day):
    """{sector name, lower case: quadrant} from money_flow.overview(), which
    intraday.py reads in the background once a day."""
    m = {}
    for k, v in (quadrants or {}).items():
        if k and v in QUADRANTS:
            m[str(k).strip().lower()] = v
    _mem["mflow"] = {"day": day, "map": m}


def _mflow_map():
    return (_mem.get("mflow") or {}).get("map") or {}


def set_orb(day, mapping, now=None):
    """The opening range, backfilled from 5-minute candles when the live
    capture at 09:30 was missed (a restart, a deploy). Returns how many."""
    now = now or now_ist()
    today = now.date().isoformat()
    if day != today or not mapping:
        return 0
    feed = _feed()
    if not _usable(feed, today):
        return 0
    n = 0
    with _lock:
        d = _day(today, feed, now)
        bufs = {name: _cfg(name)["BUFFER_PCT"] for name in LANES}
        for sym, v in mapping.items():
            try:
                hi, lo = float(v[0]), float(v[1])
            except (TypeError, ValueError, IndexError, KeyError):
                continue
            if sym in d["row"] and hi > lo > 0 and sym not in d["orb"]:
                d["orb"][sym] = (hi, lo)
                n += 1
                # Learned after the fact: a range the price has already left
                # is old news, as it would have been to a first look.
                _old_news(d, sym, "UP", [hi], bufs)
                _old_news(d, sym, "DOWN", [lo], bufs)
        d["orb_done"] = True
    return n


def orb_missing(now=None):
    """True while the opening range is still worth fetching: the session is
    live, the 09:30 capture has passed without one, and the range is still
    traded (it stops at ORB_END)."""
    now = now or now_ist()
    if not ENABLED or not session_live(now) or not usable(now):
        return False
    mso = _mso(now)
    if not (ORB_MIN + 5 < mso < ORB_END - 10):
        return False
    d = _mem["day"]
    if d is None or d["day"] != now.date().isoformat():
        # Not known until the first pass has loaded the day: right after a
        # restart the checkpoint may be about to bring the ranges back, and
        # a backfill then would spend a few hundred requests for nothing.
        return False
    return not d["orb"]


# ---------------------------------------------------------------------------
# The day's own setups
# ---------------------------------------------------------------------------

def _hod_trig(d, f, sign, mso, i, t, t_now):
    """A fresh day high (low): the old extreme has stood HOD_PAUSE_MIN
    minutes, the pause never lost VWAP, and the stock is up (down) on the
    day. The level is the old extreme."""
    if mso < HOD_FROM_MIN or sign * f["move"] <= 0:
        return None
    ext = (d["hod"] if sign > 0 else d["lod"]).get(f["sym"])
    if not ext:
        return None
    level, t_set = float(ext[0]), float(ext[1])
    pause = (t_now - t_set) / 60.0
    if pause < HOD_PAUSE_MIN:
        return None
    j = int(np.searchsorted(t[:i], t_set))
    px_s = d["px"][f["r"], j:i].astype(float)
    vw_s = d["vw"][f["r"], j:i].astype(float)
    ok = np.isfinite(px_s) & np.isfinite(vw_s) & (vw_s > 0)
    if int(ok.sum()) < 6:                    # no tape of the pause, no proof it held
        return None
    dev = sign * (px_s[ok] - vw_s[ok]) / vw_s[ok] * 100
    if float(dev.min()) < -VWAP_HOLD:
        return None
    return {"l": round(level, 2), "k": "HOD" if sign > 0 else "LOD", "s": SIG["HOD"],
            "also": [], "set": t_set, "pause": int(pause)}


def _vwap_trig(d, f, sign, mso, i, t, t_now, index_pct, since=None):
    """A pullback to VWAP that held, in a stock trending with the day and
    stronger than the index, now breaking its 15-minute high (low). After a
    reclaim that was called, or that ran without its volume, `since` is when
    that one was armed: the next needs a pullback of its own, after it."""
    vwap = f["vwap"]
    if not vwap or not (VWAP_FROM_MIN <= mso <= VWAP_TO_MIN):
        return None
    move = f["move"]
    if sign * move < VWAP_TREND or sign * (move - (index_pct or 0.0)) <= 0:
        return None
    r = f["r"]
    jl = int(np.searchsorted(t, t_now - VWAP_LOOK_MIN * 60))
    if since:
        jl = max(jl, int(np.searchsorted(t, since, side="right")))
    px_s = d["px"][r, jl:i].astype(float)
    vw_s = d["vw"][r, jl:i].astype(float)
    ok = np.isfinite(px_s) & np.isfinite(vw_s) & (vw_s > 0)
    if int(ok.sum()) < 6:
        return None
    lowest = float((sign * (px_s[ok] - vw_s[ok]) / vw_s[ok] * 100).min())
    if lowest > VWAP_TOUCH or lowest < -VWAP_HOLD:   # never came back to it, or lost it
        return None
    j15 = int(np.searchsorted(t, t_now - 900))
    seg = d["px"][r, j15:i].astype(float)
    seg = seg[np.isfinite(seg)]
    if seg.size < 6:
        return None
    level = float(seg.max() if sign > 0 else seg.min())
    if sign * (level - vwap) <= 0:
        return None
    return {"l": round(level, 2), "k": "VWAP" if sign > 0 else "VWAP_DN", "s": SIG["VWAP"],
            "also": []}


def _range_held(L, slot, edge, passes, t_now=None, gap=0.0):
    """Consecutive passes a tight-range break has held at (about) one edge.
    A pass counts only `gap` seconds after the one that last counted; a pass
    in between that still holds keeps the run going without adding to it."""
    rc = L["rconf"].get(slot)
    if rc and rc["p"] == passes - 1 and abs(rc["l"] / edge - 1) <= 0.0015:
        if t_now is None or t_now - float(rc.get("c") or 0.0) >= gap:
            rc["n"] += 1
            rc["c"] = t_now
        rc["p"] = passes
    else:
        rc = L["rconf"][slot] = {"l": float(edge), "n": 1, "p": passes, "c": t_now}
    return rc["n"]


def _called(prior):
    """(kind, level) of every call a lane already made on one stock and side
    today: one setup is called once."""
    out = set()
    for p in prior or ():
        try:
            out.add((str(p.get("kind") or "")[3:], round(float(p.get("level")), 2)))
        except (TypeError, ValueError, AttributeError):
            continue
    return out


def _reentry_ok(prior, win):
    """A second call on a stock the lane already called today: only from a
    setup the day made since, in a later part of the session, at most two a
    day, and not after the first one was stopped out."""
    if len(prior) >= 2:
        return False
    for p in prior:
        if _slot_key(p.get("window")) == _slot_key(win):
            return False
        if p.get("live_outcome") == "STOP" or p.get("outcome") == "STOP":
            return False
    return True


# ---------------------------------------------------------------------------
# One pass
# ---------------------------------------------------------------------------

def check_live(snap, now=None, index_pct=None, fired=None, log=None):
    """
    One pass. `snap` is {SYMBOL: quote}; `fired` is the set of
    (symbol, direction) the Classic lane already alerted today; `log` is
    today's logged alerts (any lane), from which each lane reads its own
    calls. Returns the alerts this pass produced, every lane together, best
    first, in the scanner's alert shape — the caller logs and sends them.
    Never sends anything itself.
    """
    if not ENABLED or not snap:
        return []
    now = now or now_ist()
    today = now.date().isoformat()
    feed = _feed()
    if not _usable(feed, today) or not session_live(now):
        return []
    mso = _mso(now)
    lanes = [_cfg(name) for name in LANES]
    out = []

    with _lock:
        d = _day(today, feed, now)
        i = _push(d, snap, now.timestamp())
        d["last"] = now.strftime("%H:%M:%S")
        t = d["t"][:i + 1]
        t_now = t[i]

        # The opening range, taken once from the day's high and low at 09:30.
        # A process that started after 09:35 has missed it; intraday.py then
        # backfills it from the 5-minute candles (set_orb).
        if not d["orb_done"] and mso >= ORB_MIN:
            d["orb_done"] = True
            if mso <= ORB_MIN + 5:
                for sym, q in snap.items():
                    hi, lo = _num(q, "high"), _num(q, "low")
                    if sym in d["row"] and hi > lo > 0:
                        d["orb"][sym] = (hi, lo)

        d["sectors"] = _sector_moves(feed, snap)
        active = [c for c in lanes if c["START_MIN"] <= mso <= c["END_MIN"]]
        names = {c["name"] for c in active}
        for c in lanes:
            if c["name"] not in names:
                _lane(d, c["name"])["waiting"] = {}
        if active:
            out = _pass(d, feed, snap, now, mso, i, t, t_now, index_pct, fired, log, active)
        _extremes(d, snap, t_now)
        d["seen"].update(s for s in snap if s in d["row"])
        if CHECKPOINT_SEC > 0 and t_now - d["saved_t"] >= CHECKPOINT_SEC:
            _save_day(d, now)
    return sorted(out, key=lambda a: -a["score"])


def _history(c, L, fired, log, today):
    """The lane's calls so far today, and {(symbol, side): [calls]}."""
    rows = None
    if log is not None:
        rows = [a for a in log if isinstance(a, dict)
                and str(a.get("kind", "")).startswith("BO_")
                and (a.get("date") or today) == today and _engine(a) == c["name"]]
    if rows is None:
        # Classic has always been told what fired by its caller; Select
        # also remembers its own calls, for a caller that keeps no log.
        rows = [] if c["name"] == "classic" else list(L["emitted"])
    fm = {}
    for a in rows:
        fm.setdefault((a.get("symbol"), a.get("direction", "UP")), []).append(a)
    if c["name"] == "classic":
        for s in fired or ():
            fm.setdefault(tuple(s), [])
    return rows, fm


def _fault(d, where, err, now):
    """One check failed. It is counted, and the last one kept in words, for
    status(); the pass carries on."""
    e = d.get("errors")
    if not isinstance(e, dict):
        e = d["errors"] = {"n": 0, "last": None, "at": None}
    e["n"] = int(e.get("n") or 0) + 1
    e["last"] = f"{where}: {type(err).__name__}: {str(err)[:120]}"
    e["at"] = now.strftime("%H:%M:%S")


def _pass(d, feed, snap, now, mso, i, t, t_now, index_pct, fired, log, active):
    today = d["day"]
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
    win = window_of(mso)
    sel = _cfg("select")                     # the quality bar every call is measured against
    prof = _prof_xy(today) if any(c["USE_PROFILE"] for c in active) else {}
    mflow = _mflow_map()
    order = list(feed["levels"].keys())
    lanes = []
    for c in active:
        L = _lane(d, c["name"])
        hist, fm = _history(c, L, fired, log, today)
        uni = set(order[:int(c["UNIVERSE"])]) if int(c["UNIVERSE"]) < len(order) else None
        lanes.append((c, L, hist, fm, uni, {}, []))

    # Each stock, and each side of it in each lane, is checked on its own: a
    # quote or a level that trips a check up costs that one check (counted
    # in status()), never the pass for every other stock and both lanes.
    for sym, lv in feed["levels"].items():
        q = snap.get(sym)
        r = d["row"].get(sym)
        if not q or r is None:
            continue
        try:
            px, cum, pc = _num(q, "ltp"), _num(q, "volume"), _num(q, "prev_close")
            if px <= 0 or pc <= 0 or cum <= 0:
                continue
            atr = float(lv.get("atr") or 2.0)
            med = float(lv["v"])
            move = (px / pc - 1) * 100
            pace = cum / (med * share_day)
            v0 = float(d["vol"][r, j5]) if share5 > 0 else float("nan")
            surge = ((cum - v0) / (med * share5)) if (share5 > 0 and np.isfinite(v0) and cum >= v0) else None
            lo15, hi15 = _span(d["px"][r, j15:i + 1])
            rl, rh = _span(d["px"][r, jw:je]) if range_ready else (None, None)
            hi_d, lo_d = (_num(q, "high") or px), (_num(q, "low") or px)
            sec = lv.get("sector")
            sm = d["sectors"].get(sec) if sec else None
            f = {"sym": sym, "r": r, "px": px, "cum": cum, "pc": pc, "opn": _num(q, "open") or pc,
                 "vwap": _num(q, "vwap") or None, "first": sym not in d["seen"], "atr": atr,
                 "med": med, "move": move, "pace": pace, "surge": surge,
                 "lo15": lo15, "hi15": hi15, "rl": rl, "rh": rh,
                 "tight": bool(rh and (rh - rl) / px * 100 <= max(RANGE_ATR * atr, 0.25)),
                 "rpos": min(1.0, max(0.0, (px - lo_d) / max(hi_d - lo_d, px * 0.002))),
                 "sector": sec, "sector_pct": sm[0] if sm else None,
                 "mf": mflow.get(sec.strip().lower()) if sec else None,
                 "bq": _num(q, "buy_qty"), "sq": _num(q, "sell_qty"),
                 "p_pace": None, "p_surge": None}
            xy = prof.get(sym)
            if xy is not None:
                # The stock's own curve: what it trades by now, and in these five
                # minutes, on a normal day. Floored at a third of the generic
                # expectation, so a near-empty lunch bucket in five sessions of
                # history cannot turn a trickle into a "surge".
                ed = float(np.interp(mso, xy[0], xy[1]))
                if ed > 0:
                    f["p_pace"] = cum / max(ed, 0.3 * med * share_day)
                    if share5 > 0 and np.isfinite(v0) and cum >= v0:
                        ew = ed - float(np.interp(max(mso - el5, 0.0), xy[0], xy[1]))
                        f["p_surge"] = (cum - v0) / max(ew, 0.3 * med * share5, 1.0)
        except Exception as e:
            _fault(d, sym, e, now)
            continue
        for c, L, hist, fm, uni, W, rows in lanes:
            if uni is not None and sym not in uni:
                continue
            for sign in ((1, -1) if c["SHORTS"] else (1,)):
                try:
                    a = _side(c, L, d, lv, f, sign, mso, i, t, t_now, index_pct, fm, win, sel, W, now)
                except Exception as e:
                    _fault(d, f"{sym} {'UP' if sign > 0 else 'DOWN'} {c['name']}", e, now)
                    continue
                if a is not None:
                    rows.append(a)

    out = []
    for c, L, hist, fm, uni, W, rows in lanes:
        rows = _pace(c, L, rows, W, hist, win)
        for a in rows:
            L["emitted"].append({"symbol": a["symbol"], "direction": a["direction"],
                                 "kind": a["kind"], "level": a.get("level"), "window": a["window"],
                                 "sector": a.get("sector"), "time": a["time"], "date": a["date"]})
        _since(L, W, now)
        L["waiting"] = W
        out.extend(rows)
    # A Classic call Select did not make: what held Select back on the same
    # stock and side this pass, for the owner's line under the card. Its
    # `shadow` covers only Select's quality filters, and an empty one must
    # not read as "Select would have taken it". (Should Select call it on a
    # later pass, the two pair and the note is moot.)
    held = next((W for c, L, hist, fm, uni, W, rows in lanes if c["name"] == "select"), None)
    if held:
        for a in out:
            w = held.get((a["symbol"], a["direction"])) if a["engine"] == "classic" else None
            if w:
                a["select_wait"] = {"code": w.get("code"), "why": w.get("why")}
    return out


def _side(c, L, d, lv, f, sign, mso, i, t, t_now, index_pct, fm, win, sel, W, now):
    """One stock, one direction, one lane: is this a call? Returns the
    alert, or None (and says why in W when there is a level to wait on)."""
    sym = f["sym"]
    side = "UP" if sign > 0 else "DOWN"
    slot = (sym, side)
    reentry = False
    if slot in fm:
        if not (c["REENTRY"] and _reentry_ok(fm[slot], win)):
            return None
        reentry = True                       # only a level the day made since may call it again
    px, pc, opn, move, atr = f["px"], f["pc"], f["opn"], f["move"], f["atr"]
    buf = c["BUFFER_PCT"]

    ladder = []
    if not reentry:
        ladder = list(lv["up"] if sign > 0 else lv["dn"])
        orb = d["orb"].get(sym)
        if orb and mso <= ORB_END:
            ladder.append({"l": orb[0] if sign > 0 else orb[1],
                           "k": "ORB" if sign > 0 else "ORB_DN", "s": SIG["ORB"], "also": []})
    armed = L["armed"].get(slot)
    late = L["late"].get(slot, ())
    called = _called(fm.get(slot))
    # A day-made level armed on an earlier pass stays a candidate until the
    # price falls back inside it. While it can still fire, a new one of the
    # same kind is not looked for, so a stock that keeps rising does not keep
    # resetting it. One that ran without its volume (late) or was called
    # already holds nothing back: the next setup of its kind is a new one
    # (a fresh day high needs its own 30-minute pause; a VWAP reclaim, a
    # pullback of its own after the spent one).
    held = [e["trig"] for e in (armed or {}).values() if e.get("trig")]
    kinds, since = set(), {}
    for lvl, e in (armed or {}).items():
        x = e.get("trig")
        if not x:
            continue
        if lvl in late or (x["k"], round(lvl, 2)) in called:
            since[x["k"]] = max(since.get(x["k"], 0.0), float(e["t"]))
        else:
            kinds.add(x["k"])
    dyn = []
    if c["HOD"] and ("HOD" if sign > 0 else "LOD") not in kinds:
        x = _hod_trig(d, f, sign, mso, i, t, t_now)
        if x:
            dyn.append(x)
    vk = "VWAP" if sign > 0 else "VWAP_DN"
    if c["VWAP"] and vk not in kinds:
        x = _vwap_trig(d, f, sign, mso, i, t, t_now, index_pct, since=since.get(vk))
        if x:
            dyn.append(x)
    cands = list(ladder)
    taken = {x["l"] for x in ladder}
    for x in dyn + held:
        # A day-made level at the price of one already on the ladder is that
        # level; the ladder's name for it wins.
        if x["l"] in taken or any(abs(x["l"] / y["l"] - 1) <= 0.0015 for y in ladder):
            continue
        taken.add(x["l"])
        cands.append(x)

    through = [x for x in cands if sign * (px - x["l"] * (1 + sign * buf / 100)) >= 0]

    # A level the price has fallen back inside is forgotten, so the next
    # cross of it is a fresh break and not a late one.
    cleared = {x["l"] for x in through}
    if armed:
        for lvl in [k for k in armed if k not in cleared]:
            del armed[lvl]
    if slot in L["late"]:
        L["late"][slot] &= cleared

    trig, entry = None, None
    if through:
        x = max(through, key=lambda z: sign * z["l"])      # the furthest level cleared
        key = (sym, side, x["l"])
        armed = L["armed"].setdefault(slot, {})
        day_made = x["k"] in DYNAMIC
        if key in L["dead"] or x["l"] in L["late"].get(slot, ()) or (x["k"], round(x["l"], 2)) in called:
            pass                               # dead, chased, or this very setup already called
        elif not day_made and sign * (pc - x["l"]) > 0:
            L["dead"].add(key)                 # through it before today
        elif x["l"] not in armed:
            gapped = (x["k"] not in ("ORB", "ORB_DN") and not day_made
                      and sign * (opn - x["l"]) > 0)
            if gapped or (f["first"] and mso > c["START_MIN"] + 4):
                L["dead"].add(key)             # opened through it, or broke before we looked
            else:
                armed[x["l"]] = {"t": t_now, "n": 1, "trig": x if day_made else None, "c": t_now}
                trig = x
        else:
            e = armed[x["l"]]
            # Held again, but it only counts as another pass once the one
            # that last counted is CONFIRM_MIN_GAP_SEC behind.
            if t_now - float(e.get("c") or e["t"]) >= c["CONFIRM_MIN_GAP_SEC"]:
                e["n"] += 1
                e["c"] = t_now
            trig = x
        if trig is not None:
            entry = armed[x["l"]]
            waited = (t_now - entry["t"]) / 60.0
            if waited > c["CHASE_MIN"] or sign * (px / x["l"] - 1) * 100 > c["CHASE_PCT"]:
                L["late"].setdefault(slot, set()).add(x["l"])   # ran without its volume
                trig = None

    # The day's own consolidation, broken in the direction of the day.
    edge = f["rh"] if sign > 0 else f["rl"]
    ranged = bool(f["tight"] and edge and sign * (px - edge * (1 + sign * buf / 100)) >= 0
                  and sign * (px / edge - 1) * 100 <= c["CHASE_PCT"] and sign * move > 0)
    if trig is None and (not ranged or reentry):
        return None
    if trig is None:
        trig = {"l": round(edge, 2), "k": "RANGE" if sign > 0 else "RANGE_DN",
                "s": SIG["RANGE"], "also": []}
        passes = (_range_held(L, slot, edge, d["passes"], t_now, c["CONFIRM_MIN_GAP_SEC"])
                  if c["CONFIRM_PASSES"] > 1 else 1)
    else:
        passes = entry["n"]
    level, kind = trig["l"], trig["k"]

    def wait(code, why, **extra):
        row = {"symbol": sym, "dir": side, "kind": kind, "level": level,
               "price": round(px, 2), "why": why, "code": code, "lane": c["name"],
               "setup": SETUP.get(kind)}
        row.update(extra)
        W[slot] = row
        L["gates"].setdefault(code, set()).add(slot)
        return None

    # VOLUME — against the stock's own profile where the lane uses one.
    surge, pace, own = f["surge"], f["pace"], False
    if c["USE_PROFILE"] and f["p_pace"] is not None:
        surge, pace, own = f["p_surge"], f["p_pace"], True
    S = c["SURGE"]
    if surge is None:
        if pace < max(1.5, S * 0.75):
            return wait("volume", f"day volume {pace:.1f}x normal, too early to read the last 5 minutes",
                        rvol=round(pace, 1), need=S)
    elif surge < S or pace < c["PACE_FLOOR"]:
        return wait("volume", f"last-5-minute volume {surge:.1f}x usual, needs {S:g}x",
                    rvol=round(surge, 1), need=S)
    lone_pdh = kind in ("PDH", "PDL") and not trig["also"] and not ranged
    if c["PDH_STRICT"] and lone_pdh:
        need = max(S, c["PDH_SURGE"])
        if surge is None or surge < need or pace < c["PDH_PACE"]:
            what = "yesterday's high" if sign > 0 else "yesterday's low"
            got = f"{surge:.1f}x" if surge is not None else "too early to read"
            return wait("volume", f"{what} on its own needs {need:g}x volume, has {got}",
                        rvol=round(surge if surge is not None else pace, 1), need=need)
    # SIDE
    vwap = f["vwap"]
    if not vwap and kind in ("VWAP", "VWAP_DN"):
        # A VWAP reclaim is measured from VWAP and its stop sits across it:
        # a quote that came without one waits for the next that has it.
        return wait("novwap", "no VWAP on this quote")
    if vwap and sign * (px - vwap) < 0:
        return wait("vwap", "wrong side of VWAP")
    ext = sign * (px - vwap) / vwap * 100 if vwap else None
    if c["MAX_VWAP_EXT"] > 0 and ext is not None:
        cap = min(c["MAX_VWAP_EXT"], 0.75 * atr)
        if ext > cap:
            return wait("extended", f"extended {ext:.1f}% {'above' if sign > 0 else 'below'} VWAP, "
                                    f"limit {cap:.1f}%")
    # WHERE IN THE DAY'S RANGE
    pos = f["rpos"] if sign > 0 else 1 - f["rpos"]
    need_pos = c["MIN_RPOS_VWAP"] if kind in ("VWAP", "VWAP_DN") else c["MIN_RPOS"]
    if need_pos > 0 and pos < need_pos:
        return wait("rpos", f"only {int(pos * 100)}% {'up' if sign > 0 else 'down'} the day's range, "
                            f"needs {int(round(need_pos * 100))}%")
    # MARKET
    if index_pct is not None and sign * index_pct < -c["REGIME"]:
        return wait("index", f"index {index_pct:+.2f}% is against it")
    # SECTOR
    sp = f["sector_pct"]
    if c["SECTOR_AGAINST"] > 0 and sp is not None and sign * sp < -c["SECTOR_AGAINST"]:
        return wait("sector", f"{sector_short(f['sector'])} stocks are {sp:+.1f}% today, against it")
    # NOT SPENT
    if abs(move) > max(2.5 * atr, 3.0):
        return wait("spent", f"already {move:+.1f}% on the day")
    # RISK
    max_risk = min(c["MAX_RISK"], max(0.6 * atr, c["MIN_RISK"] + 0.2))
    if kind in ("VWAP", "VWAP_DN"):
        stop = vwap * (1 - sign * VWAP_STOP / 100)              # just across VWAP
        risk_pct = sign * (px - stop) / px * 100
    elif kind in ("HOD", "LOD"):
        back = level * (1 - sign * 0.003)                      # just back inside the old extreme
        far = f["lo15"] if sign > 0 else f["hi15"]
        stop = back
        if far:
            far = far * (1 - sign * 0.001)
            stop = max(back, far) if sign > 0 else min(back, far)   # the tighter of the two
        risk_pct = sign * (px - stop) / px * 100
    else:
        back = level * (1 - sign * 0.003)                      # just back inside the level
        far = (f["rl"] if sign > 0 else f["rh"]) if (ranged and f["rl"]) else \
            (f["lo15"] if sign > 0 else f["hi15"])
        stop = back
        if far:
            far = far * (1 - sign * 0.001)
            stop = min(back, far) if sign > 0 else max(back, far)
        risk_pct = sign * (px - stop) / px * 100
        if risk_pct > max_risk:
            stop, risk_pct = back, sign * (px - back) / px * 100
    if risk_pct > max_risk:
        return wait("risk", f"stop would be {risk_pct:.1f}% away, limit {max_risk:.1f}%")
    if risk_pct < c["MIN_RISK"]:
        stop = px * (1 - sign * c["MIN_RISK"] / 100)
        risk_pct = c["MIN_RISK"]
    risk = abs(px - stop)
    # ROOM
    ahead = [x["l"] for x in (lv["up"] if sign > 0 else lv["dn"]) if sign * (x["l"] - px) > 0]
    nxt = min(ahead, key=lambda z: sign * z) if ahead else None
    if nxt is not None and sign * (nxt - px) < c["ROOM_R"] * risk:
        return wait("room", f"next level {nxt:,.2f} is too close")
    # THE ORDER BOOK — resting orders on the other side, a crude wall gauge.
    book = None
    if f["bq"] > 0 and f["sq"] > 0:
        book = f["sq"] / f["bq"] if sign > 0 else f["bq"] / f["sq"]
    if c["BOOK_REJECT"] > 0 and book is not None and book > c["BOOK_REJECT"]:
        return wait("book", f"{'sell' if sign > 0 else 'buy'} orders waiting are {book:.1f}x the "
                            f"{'buy' if sign > 0 else 'sell'} side")

    # SCORE: 0-100, so the day's cap keeps the best and a threshold can be
    # set from the measured record. Summed in the order it always was.
    rel = sign * (move - (index_pct or 0.0))
    vol_x = surge if surge is not None else pace
    p_vol = min(vol_x, 4.0) / 4.0 * 30
    p_sig = {5: 25, 4: 21, 3: 15, 2: 9}[trig["s"]]
    p_also = min(len(trig["also"]), 2) * 4
    p_risk = (1 - risk_pct / max_risk) * 10
    p_rng = 8 if ranged else 0
    p_idx = 10 if (index_pct or 0) * sign > 0.3 else 6 if abs(index_pct or 0) <= 0.3 else 2
    p_rel = max(0.0, min(rel, 2.0)) / 2.0 * 10
    score = p_vol + p_sig + p_also + p_risk + p_rng + p_idx + p_rel
    mf = f["mf"]
    p_sec = p_flow = p_book = 0.0
    if c["SECTOR_AGAINST"] > 0 and sp is not None:
        p_sec = max(-1.0, min(1.0, sign * sp)) * 6             # a sector moving with it
    if c["MONEY_FLOW"] and mf:
        good = ("Leading", "Improving") if sign > 0 else ("Weakening", "Lagging")
        p_flow = 5.0 if mf in good else -5.0                    # institutional tailwind or headwind
    if c["MAX_BOOK_AGAINST"] > 0 and book is not None and book > c["MAX_BOOK_AGAINST"]:
        p_book = -6.0
    if p_sec or p_flow or p_book:
        score = score + p_sec + p_flow + p_book
    score = int(round(max(0.0, min(score, 100))))
    if score < c["MIN_SCORE"]:
        return wait("score", f"score {score}, needs {c['MIN_SCORE']}", score=score,
                    rvol=round(vol_x, 1))
    # HELD — the break has to still be there on the next pass.
    if passes < c["CONFIRM_PASSES"]:
        return wait("confirm", f"confirming breakout ({passes}/{c['CONFIRM_PASSES']} passes)",
                    score=score, rvol=round(vol_x, 1), need=S)

    # What the Select lane's quality filters would say about this call,
    # whichever lane made it: the measurement of whether they help.
    shadow = []
    need_s = sel["MIN_RPOS_VWAP"] if kind in ("VWAP", "VWAP_DN") else sel["MIN_RPOS"]
    if need_s > 0 and pos < need_s:
        shadow.append("rpos")
    if ext is not None and sel["MAX_VWAP_EXT"] > 0 and ext > min(sel["MAX_VWAP_EXT"], 0.75 * atr):
        shadow.append("extended")
    if book is not None and sel["MAX_BOOK_AGAINST"] > 0 and book > sel["MAX_BOOK_AGAINST"]:
        shadow.append("book")
    if sp is not None and sel["SECTOR_AGAINST"] > 0 and sign * sp < -sel["SECTOR_AGAINST"]:
        shadow.append("sector")
    if lone_pdh and (surge is None or surge < max(sel["SURGE"], sel["PDH_SURGE"])
                     or pace < sel["PDH_PACE"]):
        shadow.append("pdh")

    base = lv.get("base")
    # The two things a reader asked for, by name. A break that ends a
    # consolidation — weeks inside a base, or 40 tight minutes today — is a
    # CONSOLIDATION breakout; every other break of a level is an INTRADAY call.
    consolidation = ranged or kind in ("BASE", "BASE_DN", "RANGE", "RANGE_DN")
    what = WORDS[kind]
    if kind in ("BASE", "BASE_DN") and base:
        what = f"the {'top' if sign > 0 else 'bottom'} of a {base['n']}-day consolidation"
    elif kind in ("RANGE", "RANGE_DN"):
        what = f"a tight {RANGE_MIN}-minute range"
    elif kind in ("HOD", "LOD"):
        at = _clock12(trig.get("set"))
        what = (f"today's {'high' if sign > 0 else 'low'}" + (f" from {at}" if at else "")
                + f", after a {int(trig.get('pause') or HOD_PAUSE_MIN)}-minute pause")
    elif ranged:
        what += f", after {RANGE_MIN} minutes in a tight range"
    verb = "Crossed above" if sign > 0 else "Fell below"
    why = (f"{verb} {level:,.2f}, {what}, on {vol_x:.1f} times its normal volume. "
           "Exit by 3:15 pm.")
    a = {
        "date": d["day"], "time": now.strftime("%H:%M"), "symbol": sym,
        "kind": "BO_" + kind, "direction": side,
        "call": "CONSOLIDATION" if consolidation else "INTRADAY",
        # What the level is, on its own, for the card's second line.
        "level_name": what[:1].upper() + what[1:],
        "headline": f"{verb.lower()} {level:,.2f}, {what}",
        "level": round(level, 2), "price": round(px, 2),
        "rvol": round(vol_x, 1), "day_rvol": round(pace, 1),
        "range_pos": round(f["rpos"], 2), "vwap": round(vwap, 2) if vwap else None,
        "entry": round(px, 2), "stop": round(stop, 2),
        "t1": round(px + sign * risk, 2), "target": round(px + sign * c["RR"] * risk, 2),
        "rr": round(c["RR"], 1), "risk_pct": round(risk_pct, 2),
        "move_pct": round(move, 2), "score": score, "regime": index_pct,
        "sector": lv.get("sector"), "why": why,
        "outcome": None, "closed_at": None,
        # Which lane, and what the call was made of.
        "engine": c["name"], "setup": SETUP.get(kind), "window": window_of(mso),
        "sector_short": sector_short(lv.get("sector")),
        "sector_pct": round(sp, 2) if sp is not None else None,
        "money_flow_quadrant": mf,
        "book_ratio": round(book, 2) if book is not None else None,
        "vwap_ext_pct": round(ext, 2) if ext is not None else None,
        "profile": own, "confirm_passes": int(passes), "shadow": shadow,
        "score_parts": {"volume": round(p_vol, 1), "level": round(p_sig + p_also, 1),
                        "risk": round(p_risk, 1), "range": float(p_rng), "index": float(p_idx),
                        "strength": round(p_rel, 1), "sector": round(p_sec, 1),
                        "flow": p_flow, "book": p_book},
    }
    if reentry:
        a["reentry"] = True
    return a


def _pace(c, L, rows, W, hist, win):
    """The lane's budget, best first: the day's cap, the session window's
    slots, calls per pass, and calls per sector. What does not fit waits,
    with the reason, and may still go on a later pass."""
    caps = (c["MAX_DAY"], c["SLOT_OPEN"], c["SLOT_MID"], c["SLOT_PM"], c["MAX_PER_PASS"],
            c["MAX_PER_SECTOR"], c["MAX_PER_SECTOR_PASS"])
    if not rows or not any(caps):
        return rows
    sk = _slot_key(win)
    cap_win = {"open": c["SLOT_OPEN"], "mid": c["SLOT_MID"], "pm": c["SLOT_PM"]}.get(sk, 0)
    used_day = len(hist)
    used_win = sum(1 for a in hist if _slot_key(a.get("window")) == sk)
    sec_day = {}
    for a in hist:
        s = a.get("sector")
        if s:
            sec_day[s] = sec_day.get(s, 0) + 1
    kept, sec_pass = [], {}
    for a in sorted(rows, key=lambda a: -a["score"]):
        s = a.get("sector")
        why = None
        if c["MAX_DAY"] and used_day >= c["MAX_DAY"]:
            why = f"daily cap reached ({used_day}/{c['MAX_DAY']} calls today)"
        elif cap_win and used_win >= cap_win:
            why = f"session slots full ({SLOT_LABEL.get(sk, sk).lower()} {used_win}/{cap_win})"
        elif c["MAX_PER_PASS"] and len(kept) >= c["MAX_PER_PASS"]:
            why = f"{c['MAX_PER_PASS']} calls this pass already, kept the stronger"
        elif s and c["MAX_PER_SECTOR_PASS"] and sec_pass.get(s, 0) >= c["MAX_PER_SECTOR_PASS"]:
            why = "sector cap reached (leader already alerted)"
        elif s and c["MAX_PER_SECTOR"] and sec_day.get(s, 0) >= c["MAX_PER_SECTOR"]:
            why = f"sector cap reached ({sec_day[s]} {sector_short(s)} calls today)"
        if why:
            slot = (a["symbol"], a["direction"])
            W[slot] = {"symbol": a["symbol"], "dir": a["direction"], "kind": a["kind"][3:],
                       "level": a["level"], "price": a["price"], "why": why, "code": "cap",
                       "lane": c["name"], "setup": a.get("setup"), "score": a["score"],
                       "rvol": a.get("rvol")}
            L["gates"].setdefault("cap", set()).add(slot)
            continue
        kept.append(a)
        used_day += 1
        used_win += 1
        if s:
            sec_day[s] = sec_day.get(s, 0) + 1
            sec_pass[s] = sec_pass.get(s, 0) + 1
    return kept


def _since(L, W, now):
    """When each waiting stock started waiting at this level."""
    old, new, clock = L.get("since") or {}, {}, now.strftime("%H:%M")
    for row in W.values():
        k = (row["symbol"], row["dir"], row["kind"], row["level"])
        new[k] = old.get(k, clock)
        row["since"] = new[k]
    L["since"] = new


# ---------------------------------------------------------------------------
# What the page reads
# ---------------------------------------------------------------------------

def rules():
    s = _cfg("select")
    return {
        "levels": "yesterday's high or low, the 20-day and 52-week extremes, the edge of a base, "
                  "the opening range, and a tight intraday range",
        "fires": (f"the price is through the level by {BUFFER_PCT:g}%, the last five minutes traded "
                  f"{SURGE:g}x their usual volume, and it is on the right side of VWAP"),
        "risk": (f"stop {MIN_RISK:g}% to {MAX_RISK:g}% away, target {RR:g} times the risk, "
                 "next level at least one risk away"),
        "window": f"{_hhmm(START_MIN)} to {_hhmm(END_MIN)}, one alert per stock per direction a day",
        "universe": f"the {UNIVERSE} most-traded stocks, at least Rs {MIN_TURNOVER_CR:g} crore a day",
        "select": {
            "what": "fewer, stronger calls, spread across the session",
            "fires": (f"the break holds for {s['CONFIRM_PASSES']} passes, on {s['SURGE']:g}x the "
                      "stock's own usual volume for the time of day, high in the day's range, not "
                      f"more than {s['MAX_VWAP_EXT']:g}% past VWAP, its sector not against it, "
                      f"and a score of {s['MIN_SCORE']} or more"),
            "setups": ("the Classic levels, a fresh day high or low after a "
                       f"{HOD_PAUSE_MIN}-minute pause, and a pullback to VWAP that breaks out again"),
            "budget": (f"up to {s['MAX_DAY']} a day: {s['SLOT_OPEN']} from {_hhmm(s['START_MIN'])}, "
                       f"{s['SLOT_MID']} from {_hhmm(s['MID_FROM'])}, {s['SLOT_PM']} from "
                       f"{_hhmm(s['PM_FROM'])}; at most {s['MAX_PER_PASS']} at once and "
                       f"{s['MAX_PER_SECTOR']} per sector"),
            "window": f"{_hhmm(s['START_MIN'])} to {_hhmm(s['END_MIN'])}",
            "universe": f"the {s['UNIVERSE']} most-traded stocks of the watch list",
        },
    }


def _session(now, s):
    """Where the session stands, by name."""
    mso = _mso(now)
    if now.weekday() >= 5 or mso >= 375:
        return {"key": "closed", "label": "Market closed", "from": None, "to": None}
    if mso < 0:
        return {"key": "pre", "label": "Pre-open", "from": None, "to": "09:15"}
    if mso < s["START_MIN"]:
        return {"key": "early", "label": "Opening minutes", "from": "09:15", "to": _hhmm(s["START_MIN"])}
    if mso < s["MID_FROM"]:
        return {"key": "open", "label": "Opening", "from": _hhmm(s["START_MIN"]), "to": _hhmm(s["MID_FROM"])}
    if mso < s["PM_FROM"]:
        return {"key": "mid", "label": "Mid-morning", "from": _hhmm(s["MID_FROM"]), "to": _hhmm(s["PM_FROM"])}
    if mso < s["END_MIN"]:
        return {"key": "pm", "label": "Afternoon", "from": _hhmm(s["PM_FROM"]), "to": _hhmm(s["END_MIN"])}
    return {"key": "late", "label": "Wind-down", "from": _hhmm(s["END_MIN"]), "to": "15:30"}


def pacing(log=None, now=None):
    """The Select lane's budget for the page: which part of the session it
    is, and how many of its slots are spent. Counts come from `log` (today's
    logged alerts) when given, else from the engine's own memory."""
    now = now or now_ist()
    today = now.date().isoformat()
    s = _cfg("select")
    if log is not None:
        rows = [a for a in log if isinstance(a, dict) and _engine(a) == "select"
                and str(a.get("kind", "")).startswith("BO_") and (a.get("date") or today) == today]
    else:
        d = _mem["day"] if (_mem["day"] and _mem["day"]["day"] == today) else None
        rows = list(((d or {}).get("lanes") or {}).get("select", {}).get("emitted") or [])
    used = {"open": 0, "mid": 0, "pm": 0}
    for a in rows:
        k = _slot_key(a.get("window"))
        if k:
            used[k] += 1
    bounds = {"open": (s["START_MIN"], s["MID_FROM"]), "mid": (s["MID_FROM"], s["PM_FROM"]),
              "pm": (s["PM_FROM"], s["END_MIN"])}
    slots = [{"key": k, "label": SLOT_LABEL[k], "from": _hhmm(bounds[k][0]), "to": _hhmm(bounds[k][1]),
              "used": used[k], "cap": int(s["SLOT_" + {"open": "OPEN", "mid": "MID", "pm": "PM"}[k]])}
             for k in ("open", "mid", "pm")]
    ses = _session(now, s)
    clock = now.strftime("%H:%M")
    enabled = bool(ENABLED and "select" in LANES)
    total = sum(used.values())
    start12 = _clock12(dt.datetime.combine(now.date(), dt.time(0, 0), IST).timestamp()
                       + (555 + s["START_MIN"]) * 60)
    if ses["key"] in ("open", "mid", "pm"):
        slot = next(x for x in slots if x["key"] == ses["key"])
        line = f"{ses['label']} session · {slot['used']}/{slot['cap']} ★ slots used · Live {clock} IST"
    elif ses["key"] == "early":
        line = f"Opening minutes · ★ Select starts {start12} · Live {clock} IST"
    elif ses["key"] == "late":
        line = f"Wind-down · ★ Select made {total} of {s['MAX_DAY']} calls · Live {clock} IST"
    elif ses["key"] == "pre":
        line = f"Pre-open · ★ Select starts {start12}"
    else:
        line = "Market closed · back at 9:15 am"
    return {"lane": "select", "enabled": enabled, "clock": clock, "session": ses,
            "used_today": total, "cap_day": int(s["MAX_DAY"]), "slots": slots, "line": line}


_CODE_RANK = {"confirm": 0, "cap": 1, "score": 2, "volume": 3}


def _waiting_rows(d):
    """One row per stock and direction across the lanes: Select's reason
    when it has one (it is the stricter, more telling of the two), with
    Classic's alongside when it differs."""
    if not d:
        return []
    lanes = d.get("lanes") or {}
    rows = {}
    for slot, w in (lanes.get("classic") or {}).get("waiting", {}).items():
        rows[slot] = dict(w)
    for slot, w in (lanes.get("select") or {}).get("waiting", {}).items():
        prev = rows.get(slot)
        row = dict(w)
        if prev and prev.get("why") != row.get("why"):
            row["classic_why"] = prev.get("why")
        rows[slot] = row

    def heat(r):
        need, x = r.get("need"), r.get("rvol")
        near = min(float(x) / float(need), 1.0) if (need and x is not None) else 0.0
        return (_CODE_RANK.get(r.get("code"), 4), -near, -(r.get("score") or 0))
    return sorted(rows.values(), key=heat)


def status(now=None):
    now = now or now_ist()
    today = now.date().isoformat()
    feed = _feed()
    p = _profiles()
    prof_ready = len(p.get("map") or {}) if _fresh_enough(p.get("built_for"), today) else 0
    mflow = _mem.get("mflow") or {}
    s = _cfg("select")
    # The page is served from another thread than the one running the
    # passes: the day's memory is read under the same lock it is written in.
    with _lock:
        d = _mem["day"] if (_mem["day"] and _mem["day"]["day"] == today) else None
        tape_min = round((d["t"][d["n"] - 1] - d["t"][0]) / 60.0) if d and d["n"] > 1 else 0
        lanes = (d or {}).get("lanes") or {}
        waiting = _waiting_rows(d)[:24]
        gates = {name: {code: len(v) for code, v in (L.get("gates") or {}).items()}
                 for name, L in lanes.items()}
        sectors = sorted(((sec, m, n) for sec, (m, n) in ((d or {}).get("sectors") or {}).items()),
                         key=lambda x: -x[1])
        passes = d["passes"] if d else 0
        last = d["last"] if d else None
        orbs = len(d["orb"]) if d else 0
        saved_at = (d or {}).get("saved_at")
        restored = (d or {}).get("restored")
        errs = dict((d or {}).get("errors") or {})
        pace = pacing(now=now)
    return {
        "enabled": ENABLED,
        "asof": feed.get("asof"),
        "built_at": feed.get("built_at"),
        "usable": _usable(feed, today),
        "stocks": len(feed.get("levels") or {}),
        "near": (feed.get("near") or [])[:20],
        "waiting": waiting,
        "passes_today": passes,
        "last_pass": last,
        "tape_minutes": tape_min,
        "opening_ranges": orbs,
        "rules": rules(),
        "session_live": session_live(now),
        "telegram": notify.health() if notify is not None else {"configured": False},
        "lanes": {"classic": {"enabled": bool(ENABLED and "classic" in LANES), "label": "Classic",
                              "window": f"{_hhmm(START_MIN)}–{_hhmm(END_MIN)}"},
                  "select": {"enabled": bool(ENABLED and "select" in LANES), "label": "★ Select",
                             "window": f"{_hhmm(s['START_MIN'])}–{_hhmm(s['END_MIN'])}",
                             "cap_day": int(s["MAX_DAY"])}},
        "pacing": pace,
        "session": _session(now, s),
        "profiles": {"ready": prof_ready, "universe": len(profile_symbols()),
                     "built_for": p.get("built_for")},
        "checkpoint": {"saved_at": saved_at, "restored": bool(restored),
                       "restored_gap_min": (restored or {}).get("gap_min")},
        "gates": gates,
        "sectors_live": [{"sector": sec, "short": sector_short(sec), "pct": round(m, 2), "n": n}
                         for sec, m, n in sectors],
        "money_flow": {"ready": bool(mflow.get("map")), "day": mflow.get("day"),
                       "sectors": len(mflow.get("map") or {})},
        # Checks that failed on one stock today (the pass went on without
        # it), and the last one in words.
        "errors": {"count": int(errs.get("n") or 0), "last": errs.get("last"), "at": errs.get("at")},
    }


def sample(engine="classic"):
    """A made-up alert in the live shape, for the Telegram test."""
    a = {"date": "", "time": "10:42", "symbol": "TESTMSG", "kind": "BO_BASE", "direction": "UP",
         "call": "CONSOLIDATION", "level_name": "The top of a 64-day consolidation",
         "headline": "crossed above 412.50, the top of a 64-day consolidation",
         "level": 412.50, "price": 414.10, "rvol": 2.6, "day_rvol": 1.4, "range_pos": None,
         "vwap": 410.85, "entry": 414.10, "stop": 411.25, "t1": 416.95, "target": 419.80,
         "rr": 2.0, "risk_pct": 0.69, "move_pct": 1.8, "score": 74, "regime": 0.35,
         "sector": "Power",
         "why": ("Crossed above 412.50, the top of a 64-day consolidation, on 2.6 times its "
                 "normal volume. Exit by 3:15 pm."),
         "outcome": None, "closed_at": None}
    if engine == "select":
        a.update(engine="select", setup="Base breakout", window="mid", score=81, range_pos=0.94,
                 sector_short="Power", sector_pct=1.1, money_flow_quadrant="Leading",
                 confirm_passes=2, shadow=[])
    return a
