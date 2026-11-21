"""
Altaha Screener — Live Intraday Scanner  (v23)

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
PROFILE_FILE = os.path.join(DATA_DIR, "vol_profiles.json")

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

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))

_state = {
    "running": False, "last_run": None, "alerts": [], "watch": [],
    "profiles": {}, "profile_day": None, "levels": {}, "error": None,
    "scanned": 0, "warm_pending": [], "warm_fail": {}, "warm_done": False,
    "regime": None, "heartbeat_day": None, "eod_day": None,
    "last_reject": {}, "top_rvol": [],
}
_lock = threading.Lock()

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
# Volume profile — what does this stock normally trade BY this minute?
# ---------------------------------------------------------------------------

def build_profile(symbol):
    """
    Cumulative volume by minute-of-day, across recent sessions.
    Returns {minutes_since_open: expected_cumulative_volume} or None.
    """
    df = dhan.intraday_ohlcv(symbol, interval="5", days=7)
    if df is None or len(df) < 20:
        return None
    df = df.copy()
    try:
        idx = df.index.tz_convert(IST) if df.index.tz is not None else df.index
    except Exception:
        idx = df.index
    df["day"] = [d.date() for d in idx]
    df["mso"] = [max(0, (d.hour * 60 + d.minute) - 555) for d in idx]

    days = sorted(df["day"].unique())[-5:]
    curves = []
    for d in days:
        sub = df[df["day"] == d].sort_values("mso")
        if len(sub) < 10:
            continue
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
        if blob.get("day") == _today():
            _state["profiles"] = {k: {int(m): v for m, v in p.items()}
                                  for k, p in (blob.get("profiles") or {}).items()}
            _state["levels"] = blob.get("levels") or {}
            _state["profile_day"] = blob["day"]
    except Exception:
        pass


def _save_profiles():
    try:
        with open(PROFILE_FILE, "w") as f:
            json.dump({"day": _state["profile_day"],
                       "profiles": {k: {str(m): v for m, v in p.items()}
                                    for k, p in _state["profiles"].items()},
                       "levels": _state["levels"]}, f)
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
    return [a for a in _state["alerts"] if a["date"] == _today()]


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

def _load_log():
    if os.path.exists(LOG_FILE):
        try:
            with open(LOG_FILE) as f:
                return json.load(f)
        except Exception:
            return []
    return []


def _save_log():
    try:
        with open(LOG_FILE, "w") as f:
            json.dump(_state["alerts"][-800:], f)
    except Exception:
        pass


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
        req = list(dict.fromkeys(list(syms) + bo_syms + [INDEX_PROXY]))
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

    # Breakouts, up and down (breakouts.py). They join the same list, so they
    # share the day's cap, the filing join, the log and the outcome marking.
    if breakouts is not None:
        try:
            done = {(a["symbol"], a.get("direction", "UP")) for a in _alerts_today()
                    if str(a.get("kind", "")).startswith("BO_")}
            fired.extend(breakouts.check_live(snap, index_pct=regime_pct, fired=done))
        except Exception as e:
            _state["error"] = "breakouts: " + str(e)[:140]

    # Daily cap, best first. Better to miss the 16th idea than to train
    # yourself to ignore the notification.
    room = MAX_ALERTS_DAY - len(_alerts_today())
    if room <= 0:
        fired = []
    elif len(fired) > room:
        fired = sorted(fired, key=lambda a: -a["score"])[:room]

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
        fired = sorted(fired, key=lambda a: -a["score"])
        with _lock:
            _state["alerts"].extend(fired)
            _save_log()
        if notify:
            try:
                notify.send_batch(
                    fired,
                    index_pct=_state.get("regime"),
                    total_today=len(_alerts_today()),
                    clock=now_ist().strftime("%H:%M"),
                )
            except Exception:
                pass

    _state["scanned"] = len(snap)
    _state["last_run"] = now_ist().isoformat()
    _heartbeat()
    return fired


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
            notify.send_plain(notify.format_day_open(
                stocks=st.get("stocks", 0) if st.get("usable") else 0,
                levels_asof=st.get("asof"),
                index_pct=_state["regime"],
                poll_seconds=POLL_SECONDS,
            ))
        except Exception:
            pass


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
            with open(MARKS_FILE, "w") as f:
                json.dump({"result_day": day}, f)
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


def call_record():
    """
    The breakout calls' record in plain terms, for the Alerts page: for each
    of the two kinds of call, how many were made, how many hit the target,
    how many hit the stop loss, and the average profit or loss per call in
    percent. Alerts from the older volume scanner are not counted — they
    were a different system.
    """
    groups = {"INTRADAY": [], "CONSOLIDATION": []}
    for a in _state["alerts"]:
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
    """
    open_alerts = [a for a in _state["alerts"] if a["outcome"] is None]
    if not open_alerts:
        return 0
    today = _today()
    cutoff = (now_ist().date() - dt.timedelta(days=10)).isoformat()
    done = 0

    by_day = {}
    for a in open_alerts:
        if a["date"] >= cutoff:
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
                    if hi is None:
                        df = dhan.daily_ohlcv(s, days=15)
                        if df is None or df.empty:
                            continue
                        row = df.iloc[-1]
                        hi, lo, last = (float(row["High"]), float(row["Low"]),
                                        float(row["Close"]))
                        approx = True

                    up = a.get("direction", "UP") == "UP"
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
                    a["r"] = _r_multiple(a, last)
                    a["pnl_pct"] = _pnl_pct(a, last)
                    done += 1
            except Exception:
                continue
    _save_log()
    return done


def stats():
    """Honest expectancy over logged alerts — the whole point of the log.
    Every marked trade counts, including the ones flat at the square-off."""
    done = []
    for a in _state["alerts"]:
        if a.get("outcome") not in ("STOP", "TARGET", "OPEN_AT_CLOSE"):
            continue
        r = a.get("r")
        if r is None:
            r = _r_multiple(a)
        if r is not None:
            done.append((a, r))

    def bucket(rows):
        n = len(rows)
        if not n:
            return None
        return {"trades": n,
                "win_rate": round(sum(1 for _a, r in rows if r > 0) / n * 100),
                "targets": sum(1 for a, _r in rows if a["outcome"] == "TARGET"),
                "stops": sum(1 for a, _r in rows if a["outcome"] == "STOP"),
                "expectancy_R": round(sum(r for _a, r in rows) / n, 2),
                "total_R": round(sum(r for _a, r in rows), 1)}

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
        sc = a.get("score") or 0
        skey = "<50" if sc < 50 else "50-64" if sc < 65 else "65-79" if sc < 80 else "80+"
        by_score.setdefault(skey, []).append((a, r))

    return {
        "by_signal": {k: bucket(v) for k, v in by_signal.items()},
        "by_direction": {k: bucket(v) for k, v in by_dir.items()},
        "by_hour": {k: bucket(v) for k, v in sorted(by_hour.items())},
        "by_rvol_bucket": {k: bucket(v) for k, v in by_rvol.items()},
        "by_score_bucket": {k: bucket(v) for k, v in by_score.items()},
        "overall": bucket(done),
        "calls": call_record(),
        "total_closed": len(done),
        "note": ("Results are in R: one R is the distance from entry to stop. A target is +2R, "
                 "a stop is -1R, and a trade still open at 15:15 counts for wherever it stood. "
                 "Positive expectancy makes money even under a 50% win rate. Under about 30 "
                 "trades a row is noise; after that, switch off the kinds that lose."),
    }


def diagnose():
    """Why did nothing fire? Answers it without reading logs."""
    reasons = {}
    for s, r in (_state["last_reject"] or {}).items():
        if r:
            reasons[r] = reasons.get(r, 0) + 1
    return {
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
        "breakouts": breakouts.status() if breakouts is not None else None,
        "volume_alerts_on": VOLUME_ALERTS,
        "poll_seconds": POLL_SECONDS,
        "error": _state["error"],
        "log_path": LOG_FILE,
        "log_is_ephemeral": DATA_DIR == HERE,
    }


def _loop():
    marked_day = None
    while _state["running"]:
        try:
            _ensure_levels()
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


def status():
    return {
        "running": _state["running"],
        "market_open": market_open(),
        "watchlist_size": len(_state["watch"]),
        "quotes_last_pass": _state["scanned"],
        "last_run": _state["last_run"],
        "profiles_built": len(_state["profiles"]),
        "profiles_pending": len(_state["warm_pending"]),
        "index_change_pct": _state["regime"],
        "alerts_today": _alerts_today()[::-1],
        "top_rvol_now": _state["top_rvol"][:8],
        "profiles_given_up": sum(1 for n in _state["warm_fail"].values() if n >= 2),
        "in_alert_window": (market_open()
                            and ALERT_START_MIN <= minutes_since_open() <= ALERT_END_MIN),
        "alerts_configured": bool(notify and notify.configured()),
        "volume_alerts_on": VOLUME_ALERTS,
        "poll_seconds": POLL_SECONDS,
        "daily_cap": MAX_ALERTS_DAY,
        "error": _state["error"],
    }
