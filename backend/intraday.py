"""
Altaha Screener — Live Intraday Scanner

Three signals, all gated on relative volume. Nothing fires without unusual
participation, because volume is the only one of these that is an *event*
rather than a derived pattern.

  1. RVOL SPIKE     — traded volume is N× what this stock normally does
                      BY THIS TIME OF DAY (time-of-day normalised, which is
                      the part most retail scanners get wrong).
  2. ORB            — clears the first 15 minutes' high/low, volume-confirmed.
  3. LEVEL BREAK    — crosses a support/resistance zone from levels.py that
                      scored above 70, volume-confirmed.

Every fired alert is logged with its entry, stop and target, then marked
up/down at the close. After a few weeks this file — not any book — tells
Taha whether his own signals work.

Design notes:
  · One bulk quote call covers the whole watchlist, so the per-minute cost
    is 1-2 requests regardless of universe size.
  · The time-of-day volume profile is built once per day from 5-minute
    intraday history and cached.
  · Alerts de-duplicate: one alert per symbol per signal per day.
"""

import datetime as dt
import json
import os
import threading
import time

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

HERE = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(HERE, "signal_log.json")

RVOL_MIN = 2.5           # spike threshold
RVOL_CONFIRM = 1.8       # confirmation floor for ORB / level breaks
LEVEL_MIN_STRENGTH = 70
POLL_SECONDS = 60
MIN_PRICE = 30.0         # skip penny names — spreads eat the edge

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))

_state = {
    "running": False, "last_run": None, "alerts": [], "watch": [],
    "profiles": {}, "profile_day": None, "levels": {}, "error": None,
    "scanned": 0,
}
_lock = threading.Lock()


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


# ---------------------------------------------------------------------------
# Volume profile — what does this stock normally trade BY this minute?
# ---------------------------------------------------------------------------

def build_profile(symbol):
    """
    Cumulative volume by minute-of-day, averaged over the last few sessions.
    Returns {minutes_since_open: expected_cumulative_volume} or None.
    """
    df = dhan.intraday_ohlcv(symbol, interval="5", days=5)
    if df is None or len(df) < 20:
        return None
    df = df.copy()
    try:
        idx = df.index.tz_convert(IST) if df.index.tz is not None else df.index
    except Exception:
        idx = df.index
    df["day"] = [d.date() for d in idx]
    df["mso"] = [max(1, (d.hour * 60 + d.minute) - 555) for d in idx]

    days = sorted(df["day"].unique())[-5:]
    curves = []
    for d in days:
        sub = df[df["day"] == d].sort_values("mso")
        if len(sub) < 10:
            continue
        curves.append(dict(zip(sub["mso"], np.cumsum(sub["Volume"].values))))
    if not curves:
        return None

    prof = {}
    for m in range(5, 380, 5):
        vals = [c[k] for c in curves for k in (m,) if k in c]
        if vals:
            prof[m] = float(np.mean(vals))
    return prof or None


def expected_volume(prof, mso):
    if not prof:
        return None
    keys = sorted(prof)
    below = [k for k in keys if k <= mso]
    if not below:
        return prof[keys[0]] * (mso / keys[0])
    k = below[-1]
    return prof[k]


def ensure_profiles(symbols):
    today = now_ist().date().isoformat()
    if _state["profile_day"] == today and _state["profiles"]:
        return
    profs, lvls = {}, {}
    for s in symbols:
        try:
            p = build_profile(s)
            if p:
                profs[s] = p
            d = dhan.daily_ohlcv(s)
            if d is not None and len(d) > 60:
                lv = compute_levels(d.dropna(subset=["Close"]))
                if lv:
                    lvls[s] = lv
        except Exception:
            continue
    with _lock:
        _state["profiles"] = profs
        _state["levels"] = lvls
        _state["profile_day"] = today


# ---------------------------------------------------------------------------
# Signal detection
# ---------------------------------------------------------------------------

def _fired_today(sym, kind):
    today = now_ist().date().isoformat()
    return any(a["symbol"] == sym and a["kind"] == kind and a["date"] == today
               for a in _state["alerts"])


def detect(sym, q, prof, lv, opening):
    """Return a list of alert dicts for one symbol from one quote snapshot."""
    out = []
    px = q.get("ltp") or q.get("close")
    vol = q.get("volume")
    if not px or not vol or float(px) < MIN_PRICE:
        return out
    px, vol = float(px), float(vol)

    exp = expected_volume(prof, minutes_since_open())
    rvol = (vol / exp) if exp and exp > 0 else None
    if rvol is None:
        return out

    day_high = float(q.get("high") or px)
    day_low = float(q.get("low") or px)
    prev_close = float(q.get("prev_close") or q.get("close") or px)

    def mk(kind, headline, entry, stop, target, why):
        rr = round((target - entry) / (entry - stop), 1) if entry > stop else None
        return {
            "date": now_ist().date().isoformat(),
            "time": now_ist().strftime("%H:%M"),
            "symbol": sym, "kind": kind, "headline": headline,
            "price": round(px, 2), "rvol": round(rvol, 1),
            "entry": round(entry, 2), "stop": round(stop, 2),
            "target": round(target, 2), "rr": rr,
            "risk_pct": round((entry - stop) / entry * 100, 1),
            "why": why, "outcome": None, "closed_at": None,
        }

    # ---- 1. RVOL spike ------------------------------------------------
    if rvol >= RVOL_MIN and not _fired_today(sym, "RVOL"):
        rng = max(day_high - day_low, px * 0.005)
        up = px > prev_close
        if up:
            entry, stop = px, day_low if (px - day_low) / px < 0.03 else px - rng * 0.6
            target = px + 2 * (entry - stop)
            out.append(mk("RVOL", f"{rvol:.1f}\u00d7 normal volume, price above yesterday's close",
                          entry, stop, target,
                          f"Trading {rvol:.1f}\u00d7 the volume it normally does by {now_ist().strftime('%H:%M')} \u2014 "
                          "unusual participation is the footprint of size entering, not a lagging indicator."))

    # ---- 2. Opening range breakout ------------------------------------
    if opening and rvol >= RVOL_CONFIRM and not _fired_today(sym, "ORB"):
        orh, orl = opening["high"], opening["low"]
        if px > orh > 0:
            entry, stop = px, orl
            if (entry - stop) / entry <= 0.035:
                target = entry + 2 * (entry - stop)
                out.append(mk("ORB", f"cleared the opening-range high {orh:,.1f}",
                              entry, stop, target,
                              f"Broke the first 15 minutes' high ({orh:,.1f}) on {rvol:.1f}\u00d7 volume. "
                              "ORB without volume is close to a coin flip \u2014 the volume filter is the edge."))

    # ---- 3. Strong level break ----------------------------------------
    if lv and rvol >= RVOL_CONFIRM and not _fired_today(sym, "LEVEL"):
        for r in (lv.get("resistances") or []):
            if r["strength"] >= LEVEL_MIN_STRENGTH and prev_close < r["level"] <= px:
                sup = (lv.get("supports") or [{}])[0]
                stop = sup.get("level") or (px * 0.97)
                stop = max(stop, px * 0.965)
                nxt = [x["level"] for x in (lv.get("resistances") or []) if x["level"] > px]
                target = nxt[0] if nxt else px + 2 * (px - stop)
                out.append(mk("LEVEL", f"broke resistance {r['level']:,.1f} (strength {r['strength']}/100)",
                              px, stop, target,
                              f"Cleared a zone price reversed at {r['touches']}\u00d7 (last {r['last_touch']}), "
                              f"on {rvol:.1f}\u00d7 volume. {r['why'][:120]}"))
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


def scan_once():
    """One pass over the watchlist. Returns newly fired alerts."""
    if dhan is None or not dhan.configured():
        _state["error"] = "Dhan not configured"
        return []
    syms = _state["watch"]
    if not syms:
        return []
    ensure_profiles(syms)

    try:
        snap = dhan.bulk_quotes(syms, mode="ohlc")
    except Exception as e:
        _state["error"] = str(e)[:160]
        return []
    if not snap:
        return []

    # opening range: captured once, at 09:30
    mso = minutes_since_open()
    if mso >= 15 and not _state.get("opening_day") == now_ist().date().isoformat():
        if mso <= 25:                       # capture window
            _state["opening"] = {s: {"high": float(q.get("high") or 0),
                                     "low": float(q.get("low") or 0)}
                                 for s, q in snap.items() if q.get("high")}
            _state["opening_day"] = now_ist().date().isoformat()

    fired = []
    for s, q in snap.items():
        try:
            new = detect(s, q, _state["profiles"].get(s),
                         _state["levels"].get(s),
                         (_state.get("opening") or {}).get(s))
            fired.extend(new)
        except Exception:
            continue

    if fired:
        with _lock:
            _state["alerts"].extend(fired)
            _save_log()
        if notify:
            for a in fired:
                try:
                    notify.send_alert(a)
                except Exception:
                    pass
    _state["scanned"] = len(snap)
    _state["last_run"] = now_ist().isoformat()
    return fired


def mark_outcomes():
    """At/after close, mark each open alert as target hit, stop hit, or neither."""
    open_alerts = [a for a in _state["alerts"] if a["outcome"] is None]
    if not open_alerts:
        return 0
    syms = sorted({a["symbol"] for a in open_alerts})
    done = 0
    for s in syms:
        try:
            df = dhan.daily_ohlcv(s, days=10)
            if df is None or df.empty:
                continue
            row = df.iloc[-1]
            hi, lo = float(row["High"]), float(row["Low"])
            for a in [x for x in open_alerts if x["symbol"] == s]:
                if a["date"] != now_ist().date().isoformat():
                    continue
                if lo <= a["stop"]:
                    a["outcome"] = "STOP"
                elif hi >= a["target"]:
                    a["outcome"] = "TARGET"
                else:
                    a["outcome"] = "OPEN_AT_CLOSE"
                a["closed_at"] = round(float(row["Close"]), 2)
                done += 1
        except Exception:
            continue
    _save_log()
    return done


def stats():
    """Honest hit rate over logged alerts — the whole point of the log."""
    done = [a for a in _state["alerts"] if a["outcome"] in ("STOP", "TARGET")]
    by = {}
    for a in done:
        k = a["kind"]
        b = by.setdefault(k, {"n": 0, "win": 0, "rr_sum": 0.0})
        b["n"] += 1
        if a["outcome"] == "TARGET":
            b["win"] += 1
            b["rr_sum"] += (a.get("rr") or 0)
        else:
            b["rr_sum"] -= 1
    out = {}
    for k, b in by.items():
        out[k] = {"trades": b["n"],
                  "win_rate": round(b["win"] / b["n"] * 100) if b["n"] else None,
                  "expectancy_R": round(b["rr_sum"] / b["n"], 2) if b["n"] else None}
    total = sum(b["n"] for b in by.values())
    return {"by_signal": out, "total_closed": total,
            "note": ("Expectancy is in R \u2014 average return per unit risked. Positive R makes money "
                     "even below a 50% win rate; that is the number that matters, not accuracy. "
                     "Fewer than ~30 closed trades per signal means the sample is too small to trust.")}


def _loop():
    _state["running"] = True
    marked_day = None
    while _state["running"]:
        try:
            if market_open():
                scan_once()
            else:
                today = now_ist().date().isoformat()
                if marked_day != today and now_ist().hour >= 16:
                    mark_outcomes()
                    marked_day = today
        except Exception as e:
            _state["error"] = str(e)[:160]
        time.sleep(POLL_SECONDS)


def start(watchlist):
    _state["watch"] = watchlist
    if not _state["alerts"]:
        _state["alerts"] = _load_log()
    if not _state["running"]:
        threading.Thread(target=_loop, daemon=True).start()
    return True


def stop():
    _state["running"] = False


def status():
    today = now_ist().date().isoformat()
    return {
        "running": _state["running"],
        "market_open": market_open(),
        "watchlist_size": len(_state["watch"]),
        "quotes_last_pass": _state["scanned"],
        "last_run": _state["last_run"],
        "profiles_built": len(_state["profiles"]),
        "alerts_today": [a for a in _state["alerts"] if a["date"] == today][::-1],
        "error": _state["error"],
    }
