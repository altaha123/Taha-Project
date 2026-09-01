"""
Altaha Screener — Chart pattern recognition

WHAT THIS IS, AND WHAT IT IS NOT
--------------------------------
This finds the classical chart patterns — cup and handle, double bottom, head
and shoulders, triangles, flags, wedges — in an OHLCV series, and for each one
reports four things:

    SHAPE        the pivots that form it, so you can check the call yourself
    TRIGGER      the price that confirms it, and the price that invalidates it
    TARGET       the measured move the pattern's own geometry implies
    BASE RATE    what actually happened the last N times this shape appeared
                 in this stock's own history

The fourth is the point. A pattern name on its own is an assertion; a pattern
name next to "resolved upward in 11 of 19 past instances, median +4.2% over 20
sessions" is evidence someone can argue with. Where the sample is too small to
mean anything the module says so rather than printing a confident percentage —
under about 8 instances no rate is reported at all.

NOTHING HERE PREDICTS A PRICE. A measured move is arithmetic on the pattern's
own height, not a forecast, and it is labelled as such. A base rate is a
historical frequency, not a probability for tomorrow. The distinction matters
legally as well as intellectually: this tool shows evidence, it does not issue
recommendations.

WHY TOLERANCES ARE IN ATR, NOT PERCENT
--------------------------------------
"The two tops are within 2%" means something completely different for a ₹40
stock that moves 6% a day and a ₹4,000 stock that moves 0.8%. Every tolerance
below is expressed in multiples of ATR, so the same rule reads the same way
across the whole universe. This is the single most common way a pattern
detector produces garbage on real data.
"""

import datetime as dt

import numpy as np
import pandas as pd

from engine import atr, rsi

# A swing point needs this many bars either side. Smaller finds more shapes and
# more noise; larger finds fewer and cleaner ones.
PIVOT_K = 5

# Minimum instances before a base rate is worth printing.
MIN_SAMPLE = 8

# Forward windows the base rate is measured over.
HORIZONS = (5, 10, 20, 40)


# ---------------------------------------------------------------------------
# Swing structure
# ---------------------------------------------------------------------------

def _pivots(df, k=PIVOT_K):
    """
    [(index, price, 'H'|'L'), ...] in time order.

    A bar is a swing high if nothing in the k bars either side traded higher.
    The last k bars can never qualify — the right-hand side does not exist
    yet — which is exactly why a pattern is only ever "forming" until price
    confirms it.
    """
    high = df["High"].values.astype(float)
    low = df["Low"].values.astype(float)
    out = []
    for i in range(k, len(df) - k):
        win_h = high[i - k:i + k + 1]
        win_l = low[i - k:i + k + 1]
        if high[i] >= win_h.max():
            out.append((i, float(high[i]), "H"))
        elif low[i] <= win_l.min():
            out.append((i, float(low[i]), "L"))
    return out


def _alternating(piv):
    """Collapse runs of same-type pivots to the most extreme of each run, so
    the sequence alternates H, L, H, L. Without this a noisy stretch produces
    four 'highs' in a row and every shape rule downstream misreads it."""
    out = []
    for p in piv:
        if out and out[-1][2] == p[2]:
            keep = p if ((p[2] == "H" and p[1] > out[-1][1]) or
                         (p[2] == "L" and p[1] < out[-1][1])) else out[-1]
            out[-1] = keep
        else:
            out.append(p)
    return out


def _ctx(df):
    """Everything the detectors share: ATR, volume baseline, dates."""
    a = atr(df, 14)
    last_atr = float(a.iloc[-1]) if len(a) and not pd.isna(a.iloc[-1]) else None
    if not last_atr or last_atr <= 0:
        last_atr = max(float(df["Close"].iloc[-1]) * 0.02, 0.01)
    vol = df["Volume"].fillna(0).values.astype(float) if "Volume" in df else np.zeros(len(df))
    return {
        "atr": last_atr,
        "vol": vol,
        "vol_base": float(np.mean(vol[-60:])) if len(vol) >= 60 else (float(np.mean(vol)) if len(vol) else 0.0),
        "close": df["Close"].values.astype(float),
        "high": df["High"].values.astype(float),
        "low": df["Low"].values.astype(float),
        "index": df.index,
        "n": len(df),
    }


def _date(idx, i):
    try:
        return pd.Timestamp(idx[i]).strftime("%d %b %y")
    except Exception:
        return str(i)


def _epoch(idx, i):
    """
    The pivot's timestamp in seconds, so the browser can put it on the chart.

    The panel's dates are formatted for a human ("14 Mar 25") and cannot be
    parsed back reliably, which is why drawing the shape on the chart needed
    this. It is the identical expression /chart uses to stamp its candles —
    int(Timestamp.timestamp()) — so a point and its candle land on the same
    x-coordinate rather than nearly the same one.
    """
    try:
        return int(pd.Timestamp(idx[i]).timestamp())
    except Exception:
        return None


def _pt(c, i, price, label):
    return {"i": int(i), "date": _date(c["index"], i), "t": _epoch(c["index"], i),
            "price": round(float(price), 2), "label": label}


def _near(a, b, atr_val, mult):
    """Are two prices within `mult` ATRs of each other?"""
    return abs(a - b) <= mult * atr_val


# ---------------------------------------------------------------------------
# The detectors
#
# Each returns a dict or None. They share a shape:
#   name, direction, status, confidence, points, trigger, invalidation,
#   target, checks  (what was tested and whether it passed — the audit trail
#                    this project puts on everything else)
# ---------------------------------------------------------------------------

def _result(name, direction, status, points, trigger, invalidation, target,
            checks, note, formed_at):
    passed = sum(1 for c in checks if c["ok"])
    return {
        "name": name,
        "direction": direction,                 # bullish | bearish
        "status": status,                       # forming | confirmed | failed
        "confidence": round(100.0 * passed / max(1, len(checks))),
        "checks": checks,
        "points": points,
        "trigger": round(float(trigger), 2) if trigger is not None else None,
        "invalidation": round(float(invalidation), 2) if invalidation is not None else None,
        "target": round(float(target), 2) if target is not None else None,
        "note": note,
        "formed_at": formed_at,
    }


def _chk(label, ok, detail):
    return {"check": label, "ok": bool(ok), "detail": detail}


def double_bottom(df, c, piv):
    """Two lows at roughly the same level with a high between them. Confirms on
    a close above that middle high; dies on a close below the lower low."""
    if len(piv) < 3:
        return None
    lows = [p for p in piv if p[2] == "L"]
    if len(lows) < 2:
        return None
    b2 = lows[-1]
    b1 = lows[-2]
    mids = [p for p in piv if p[2] == "H" and b1[0] < p[0] < b2[0]]
    if not mids:
        return None
    mid = max(mids, key=lambda p: p[1])

    a = c["atr"]
    depth = mid[1] - min(b1[1], b2[1])
    level = _near(b1[1], b2[1], a, 1.2)
    deep = depth >= 1.5 * a
    spaced = (b2[0] - b1[0]) >= 12
    last = c["close"][-1]

    checks = [
        _chk("Two lows at the same level", level,
             f"₹{b1[1]:.2f} and ₹{b2[1]:.2f} — {abs(b1[1]-b2[1])/a:.1f} ATR apart"),
        _chk("Meaningful separation between them", spaced,
             f"{b2[0]-b1[0]} sessions apart"),
        _chk("Recovery between the lows is real", deep,
             f"the middle high is {depth/a:.1f} ATR above the lows"),
        _chk("Second low held above the first", b2[1] >= b1[1] - 0.5 * a,
             "a lower second low weakens the base"),
    ]
    if not (level and spaced and deep):
        return None

    trigger, invalid = mid[1], min(b1[1], b2[1])
    status = "confirmed" if last > trigger else ("failed" if last < invalid else "forming")
    return _result(
        "Double bottom", "bullish", status,
        [_pt(c, b1[0], b1[1], "First low"), _pt(c, mid[0], mid[1], "Middle high"),
         _pt(c, b2[0], b2[1], "Second low")],
        trigger, invalid, trigger + depth, checks,
        "Two failed attempts to break lower, then a close above the high between them. "
        "The measured move adds the base's own depth to the breakout level.",
        _date(c["index"], b2[0]))


def double_top(df, c, piv):
    """The mirror. Confirms on a close below the middle low."""
    if len(piv) < 3:
        return None
    highs = [p for p in piv if p[2] == "H"]
    if len(highs) < 2:
        return None
    t2, t1 = highs[-1], highs[-2]
    mids = [p for p in piv if p[2] == "L" and t1[0] < p[0] < t2[0]]
    if not mids:
        return None
    mid = min(mids, key=lambda p: p[1])

    a = c["atr"]
    depth = max(t1[1], t2[1]) - mid[1]
    level = _near(t1[1], t2[1], a, 1.2)
    deep = depth >= 1.5 * a
    spaced = (t2[0] - t1[0]) >= 12
    last = c["close"][-1]

    checks = [
        _chk("Two highs at the same level", level,
             f"₹{t1[1]:.2f} and ₹{t2[1]:.2f} — {abs(t1[1]-t2[1])/a:.1f} ATR apart"),
        _chk("Meaningful separation between them", spaced, f"{t2[0]-t1[0]} sessions apart"),
        _chk("Pullback between the highs is real", deep,
             f"the middle low is {depth/a:.1f} ATR below the highs"),
        _chk("Second high failed to exceed the first", t2[1] <= t1[1] + 0.5 * a,
             "a higher second high is continuation, not a top"),
    ]
    if not (level and spaced and deep):
        return None

    trigger, invalid = mid[1], max(t1[1], t2[1])
    status = "confirmed" if last < trigger else ("failed" if last > invalid else "forming")
    return _result(
        "Double top", "bearish", status,
        [_pt(c, t1[0], t1[1], "First high"), _pt(c, mid[0], mid[1], "Middle low"),
         _pt(c, t2[0], t2[1], "Second high")],
        trigger, invalid, trigger - depth, checks,
        "Two failed attempts to break higher, then a close below the low between them.",
        _date(c["index"], t2[0]))


def head_and_shoulders(df, c, piv, inverse=False):
    """
    Three peaks, the middle one highest, with a neckline through the two
    troughs. Inverse flips every comparison.
    """
    want, other = ("L", "H") if inverse else ("H", "L")
    peaks = [p for p in piv if p[2] == want]
    if len(peaks) < 3:
        return None
    ls, head, rs = peaks[-3], peaks[-2], peaks[-1]

    troughs = [p for p in piv if p[2] == other]
    t1 = [p for p in troughs if ls[0] < p[0] < head[0]]
    t2 = [p for p in troughs if head[0] < p[0] < rs[0]]
    if not t1 or not t2:
        return None
    t1, t2 = t1[-1], t2[0]

    a = c["atr"]
    if inverse:
        head_extreme = head[1] < ls[1] - 0.8 * a and head[1] < rs[1] - 0.8 * a
        depth = ((t1[1] + t2[1]) / 2) - head[1]
    else:
        head_extreme = head[1] > ls[1] + 0.8 * a and head[1] > rs[1] + 0.8 * a
        depth = head[1] - ((t1[1] + t2[1]) / 2)

    shoulders_even = _near(ls[1], rs[1], a, 1.5)
    neckline = (t1[1] + t2[1]) / 2.0
    neck_flat = _near(t1[1], t2[1], a, 1.5)
    last = c["close"][-1]

    checks = [
        _chk("Head clears both shoulders", head_extreme,
             f"head ₹{head[1]:.2f} against shoulders ₹{ls[1]:.2f} / ₹{rs[1]:.2f}"),
        _chk("Shoulders roughly level", shoulders_even,
             f"{abs(ls[1]-rs[1])/a:.1f} ATR apart"),
        _chk("Neckline roughly flat", neck_flat,
             ("peaks between the shoulders at " if inverse else "troughs at ")
             + f"₹{t1[1]:.2f} and ₹{t2[1]:.2f}"),
        _chk("Pattern has room", (rs[0] - ls[0]) >= 20, f"{rs[0]-ls[0]} sessions wide"),
    ]
    if not (head_extreme and shoulders_even and depth >= 1.5 * a):
        return None

    if inverse:
        status = "confirmed" if last > neckline else ("failed" if last < head[1] else "forming")
        return _result("Inverse head and shoulders", "bullish", status,
                       [_pt(c, ls[0], ls[1], "Left shoulder"), _pt(c, head[0], head[1], "Head"),
                        _pt(c, rs[0], rs[1], "Right shoulder")],
                       neckline, head[1], neckline + depth, checks,
                       "A lower low the market refused to extend, then a higher low. "
                       "Confirms on a close above the neckline.",
                       _date(c["index"], rs[0]))
    status = "confirmed" if last < neckline else ("failed" if last > head[1] else "forming")
    return _result("Head and shoulders", "bearish", status,
                   [_pt(c, ls[0], ls[1], "Left shoulder"), _pt(c, head[0], head[1], "Head"),
                    _pt(c, rs[0], rs[1], "Right shoulder")],
                   neckline, head[1], neckline - depth, checks,
                   "A higher high the market could not hold, then a lower high. "
                   "Confirms on a close below the neckline.",
                   _date(c["index"], rs[0]))


def cup_and_handle(df, c, piv):
    """
    A rounded base between two rims at a similar level, then a shallow drift
    lower on lighter volume, then a break of the rim.

    The rules that keep this from matching every V-bottom: the base must be
    ROUNDED (the low sits near the middle of the span, and the two halves are
    of comparable length), the handle must be shallow relative to the cup
    (under half its depth — a deeper one is a new downtrend), and volume in
    the handle must be lighter than in the cup.
    """
    highs = [p for p in piv if p[2] == "H"]
    lows = [p for p in piv if p[2] == "L"]
    if len(highs) < 2 or not lows:
        return None

    right_rim = highs[-1]
    left_rims = [p for p in highs if p[0] < right_rim[0] - 20]
    if not left_rims:
        return None
    left_rim = left_rims[-1]

    base = [p for p in lows if left_rim[0] < p[0] < right_rim[0]]
    if not base:
        return None
    cup_low = min(base, key=lambda p: p[1])

    a = c["atr"]
    depth = min(left_rim[1], right_rim[1]) - cup_low[1]
    span = right_rim[0] - left_rim[0]
    if span < 25 or depth < 2.0 * a:
        return None

    left_half = cup_low[0] - left_rim[0]
    right_half = right_rim[0] - cup_low[0]
    rounded = min(left_half, right_half) >= 0.30 * span
    rims_even = _near(left_rim[1], right_rim[1], a, 1.5)

    # The handle is everything after the right rim.
    h_start = right_rim[0]
    if c["n"] - h_start < 3:
        return None
    h_low = float(np.min(c["low"][h_start:]))
    handle_depth = right_rim[1] - h_low
    shallow = handle_depth <= 0.5 * depth
    handle_len = c["n"] - h_start
    handle_ok = 3 <= handle_len <= max(25, span // 2)

    cup_vol = float(np.mean(c["vol"][left_rim[0]:h_start])) if h_start > left_rim[0] else 0.0
    h_vol = float(np.mean(c["vol"][h_start:])) if handle_len else 0.0
    vol_dry = (cup_vol <= 0) or (h_vol <= cup_vol)

    last = c["close"][-1]
    checks = [
        _chk("Base is rounded, not a V", rounded,
             f"low sits {left_half}/{right_half} sessions between the rims"),
        _chk("Rims at a similar level", rims_even,
             f"₹{left_rim[1]:.2f} and ₹{right_rim[1]:.2f}"),
        _chk("Cup is deep enough to matter", depth >= 2.0 * a, f"{depth/a:.1f} ATR deep"),
        _chk("Handle is a pause, not a new decline", shallow,
             f"handle {handle_depth/max(depth,1e-9)*100:.0f}% of cup depth"),
        _chk("Handle length is sane", handle_ok, f"{handle_len} sessions"),
        _chk("Volume dried up in the handle", vol_dry,
             "handle volume at or below the cup's average"),
    ]
    if not (rounded and rims_even and shallow and handle_ok):
        return None

    trigger = max(left_rim[1], right_rim[1])
    invalid = h_low
    status = "confirmed" if last > trigger else ("failed" if last < cup_low[1] else "forming")
    return _result(
        "Cup and handle", "bullish", status,
        [_pt(c, left_rim[0], left_rim[1], "Left rim"), _pt(c, cup_low[0], cup_low[1], "Cup low"),
         _pt(c, right_rim[0], right_rim[1], "Right rim"),
         _pt(c, c["n"] - 1, h_low, "Handle low")],
        trigger, invalid, trigger + depth, checks,
        "A rounded base that reclaimed its old high, then a shallow drift on lighter "
        "volume. The measured move adds the cup's depth to the rim.",
        _date(c["index"], right_rim[0]))


def _fit(xs, ys):
    """
    Least-squares slope and intercept, plus the typical distance of the points
    from the line in PRICE units.

    Deliberately not r². An ascending triangle's ceiling is by definition flat,
    so the variance of those highs is almost zero — and r², which divides by
    exactly that variance, collapses to noise over noise. A textbook flat top
    scored r² = 0.45 and was rejected for not sitting on its own line. Residual
    distance has no such blind spot, and measured against ATR it means the same
    thing on any stock.
    """
    if len(xs) < 2:
        return None, None, float("inf")
    xs = np.asarray(xs, dtype=float)
    ys = np.asarray(ys, dtype=float)
    slope, intercept = np.polyfit(xs, ys, 1)
    resid = ys - (slope * xs + intercept)
    rmse = float(np.sqrt(np.mean(resid ** 2)))
    return float(slope), float(intercept), rmse


def triangle(df, c, piv):
    """
    Converging trendlines through the recent highs and lows.

    Ascending  — flat top, rising lows
    Descending — flat base, falling highs
    Symmetrical— both converging
    Wedges are the same machinery with both lines sloping the same way, and
    they resolve against that slope, which is why they are named separately.
    """
    recent = [p for p in piv if p[0] >= c["n"] - 90]
    highs = [p for p in recent if p[2] == "H"][-4:]
    lows = [p for p in recent if p[2] == "L"][-4:]
    if len(highs) < 2 or len(lows) < 2:
        return None

    hs, hi_c, h_rmse = _fit([p[0] for p in highs], [p[1] for p in highs])
    ls, lo_c, l_rmse = _fit([p[0] for p in lows], [p[1] for p in lows])
    if hs is None or ls is None:
        return None

    a = c["atr"]
    i = c["n"] - 1
    top_now = hs * i + hi_c
    bot_now = ls * i + lo_c
    width_now = top_now - bot_now
    start = min(highs[0][0], lows[0][0])
    width_then = (hs * start + hi_c) - (ls * start + lo_c)
    if width_now <= 0 or width_then <= 0:
        return None

    converging = width_now < width_then * 0.85
    # Slope measured in ATR per session keeps "flat" meaningful across prices.
    h_flat = abs(hs) < 0.05 * a
    l_flat = abs(ls) < 0.05 * a
    # 0.6 ATR, not 0.9: at the looser figure a converging random walk scored a
    # clean "descending triangle", which is precisely the false positive this
    # kind of detector is famous for. Tight enough to need a real line.
    tol = 0.6 * a
    fits = h_rmse <= tol and l_rmse <= tol
    # And a line needs three touches. Two points define a line through any two
    # noisy swings; three is the first number that can be wrong.
    enough = max(len(highs), len(lows)) >= 3 and (len(highs) + len(lows)) >= 5
    last = c["close"][-1]

    if h_flat and ls > 0:
        name, direction = "Ascending triangle", "bullish"
    elif l_flat and hs < 0:
        name, direction = "Descending triangle", "bearish"
    elif hs < 0 and ls > 0:
        name, direction = "Symmetrical triangle", "neutral"
    elif hs < 0 and ls < 0 and converging:
        name, direction = "Falling wedge", "bullish"
    elif hs > 0 and ls > 0 and converging:
        name, direction = "Rising wedge", "bearish"
    else:
        return None

    checks = [
        _chk("Lines are converging", converging,
             f"range narrowed from {width_then/a:.1f} to {width_now/a:.1f} ATR"),
        _chk("Highs sit on their line", h_rmse <= tol,
             f"highs are {h_rmse/a:.2f} ATR off the line on average"),
        _chk("Lows sit on their line", l_rmse <= tol,
             f"lows are {l_rmse/a:.2f} ATR off the line on average"),
        _chk("Enough touches to be a line", enough,
             f"{len(highs)} highs, {len(lows)} lows"),
    ]
    if not (converging and fits and enough):
        return None

    if direction == "bearish":
        trigger, invalid, target = bot_now, top_now, bot_now - width_then
    elif direction == "bullish":
        trigger, invalid, target = top_now, bot_now, top_now + width_then
    else:
        # Symmetrical resolves either way; report the nearer edge as trigger.
        up = abs(top_now - last) <= abs(last - bot_now)
        trigger, invalid = (top_now, bot_now) if up else (bot_now, top_now)
        target = trigger + width_then if up else trigger - width_then

    if direction == "bearish":
        status = "confirmed" if last < trigger else ("failed" if last > invalid else "forming")
    else:
        status = "confirmed" if last > trigger else ("failed" if last < invalid else "forming")

    pts = [_pt(c, p[0], p[1], "High") for p in highs] + [_pt(c, p[0], p[1], "Low") for p in lows]
    return _result(name, direction, status, sorted(pts, key=lambda p: p["i"]),
                   trigger, invalid, target, checks,
                   "Converging trendlines. The measured move projects the widest part of "
                   "the range from the breakout, which is the textbook rule and nothing more.",
                   _date(c["index"], max(highs[-1][0], lows[-1][0])))


def flag(df, c, piv):
    """
    A steep move (the pole), then a shallow drift against it on lighter volume.
    Continuation, not reversal — the target projects the pole from the breakout.
    """
    n = c["n"]
    if n < 40:
        return None
    a = c["atr"]

    best = None
    for pole_len in (8, 12, 16, 20):
        for flag_len in (5, 8, 12, 16):
            if pole_len + flag_len + 2 > n:
                continue
            f0 = n - flag_len
            p0 = f0 - pole_len
            pole_move = c["close"][f0 - 1] - c["close"][p0]
            if abs(pole_move) < 3.0 * a:
                continue
            f_high = float(np.max(c["high"][f0:]))
            f_low = float(np.min(c["low"][f0:]))
            f_range = f_high - f_low
            if f_range > 0.5 * abs(pole_move) or f_range <= 0:
                continue
            pole_vol = float(np.mean(c["vol"][p0:f0])) if f0 > p0 else 0.0
            flag_vol = float(np.mean(c["vol"][f0:])) if flag_len else 0.0
            # A flag with flat volume is still a flag. Volume easing is
            # textbook and is scored below, but gating on it threw away real
            # patterns whenever the pole happened to be quiet — and the
            # combination search would settle on a shape that then failed the
            # gate, so the pattern vanished rather than scoring lower.
            score = abs(pole_move) / a - f_range / a
            if pole_vol > 0 and flag_vol <= pole_vol:
                score += 1.0                       # prefer the textbook case
            if best is None or score > best["score"]:
                best = {"score": score, "p0": p0, "f0": f0, "pole": pole_move,
                        "hi": f_high, "lo": f_low, "pv": pole_vol, "fv": flag_vol,
                        "flag_len": flag_len}
    if not best:
        return None

    bull = best["pole"] > 0
    vol_dry = best["pv"] <= 0 or best["fv"] <= best["pv"]
    last = c["close"][-1]
    checks = [
        _chk("Pole is a real move", abs(best["pole"]) >= 3.0 * a,
             f"{abs(best['pole'])/a:.1f} ATR in {best['f0']-best['p0']} sessions"),
        _chk("Consolidation is shallow", (best["hi"] - best["lo"]) <= 0.5 * abs(best["pole"]),
             f"drift is {(best['hi']-best['lo'])/abs(best['pole'])*100:.0f}% of the pole"),
        _chk("Volume eased in the flag", vol_dry, "flag volume at or below the pole's"),
        _chk("Flag has not overstayed", best["flag_len"] <= 20,
             f"{best['flag_len']} sessions"),
    ]
    if bull:
        trigger, invalid, target = best["hi"], best["lo"], best["hi"] + abs(best["pole"])
        status = "confirmed" if last > trigger else ("failed" if last < invalid else "forming")
        name, direction = "Bull flag", "bullish"
    else:
        trigger, invalid, target = best["lo"], best["hi"], best["lo"] - abs(best["pole"])
        status = "confirmed" if last < trigger else ("failed" if last > invalid else "forming")
        name, direction = "Bear flag", "bearish"

    return _result(name, direction, status,
                   [_pt(c, best["p0"], c["close"][best["p0"]], "Pole start"),
                    _pt(c, best["f0"] - 1, c["close"][best["f0"] - 1], "Pole end"),
                    _pt(c, n - 1, last, "Flag")],
                   trigger, invalid, target, checks,
                   "A sharp move that paused rather than reversed. The measured move "
                   "repeats the pole from the breakout.",
                   _date(c["index"], best["f0"]))


def rectangle(df, c, piv):
    """A horizontal range: repeated touches of the same ceiling and floor."""
    recent = [p for p in piv if p[0] >= c["n"] - 80]
    highs = [p for p in recent if p[2] == "H"][-4:]
    lows = [p for p in recent if p[2] == "L"][-4:]
    if len(highs) < 2 or len(lows) < 2:
        return None

    a = c["atr"]
    top = float(np.mean([p[1] for p in highs]))
    bot = float(np.mean([p[1] for p in lows]))
    height = top - bot
    if height < 2.0 * a:
        return None

    top_tight = all(_near(p[1], top, a, 1.0) for p in highs)
    bot_tight = all(_near(p[1], bot, a, 1.0) for p in lows)
    checks = [
        _chk("Ceiling is a level, not a slope", top_tight, f"{len(highs)} highs around ₹{top:.2f}"),
        _chk("Floor is a level, not a slope", bot_tight, f"{len(lows)} lows around ₹{bot:.2f}"),
        _chk("Range is wide enough to trade", height >= 2.0 * a, f"{height/a:.1f} ATR tall"),
    ]
    if not (top_tight and bot_tight):
        return None

    last = c["close"][-1]
    if last > top:
        status, direction, trigger, invalid, target = "confirmed", "bullish", top, bot, top + height
    elif last < bot:
        status, direction, trigger, invalid, target = "confirmed", "bearish", bot, top, bot - height
    else:
        status, direction = "forming", "neutral"
        up = abs(top - last) <= abs(last - bot)
        trigger, invalid = (top, bot) if up else (bot, top)
        target = trigger + height if up else trigger - height

    pts = [_pt(c, p[0], p[1], "Ceiling touch") for p in highs] + \
          [_pt(c, p[0], p[1], "Floor touch") for p in lows]
    return _result("Rectangle range", direction, status, sorted(pts, key=lambda p: p["i"]),
                   trigger, invalid, target, checks,
                   "Price bounded by a flat ceiling and floor. The measured move projects "
                   "the range height from whichever edge breaks.",
                   _date(c["index"], max(highs[-1][0], lows[-1][0])))


DETECTORS = [
    ("cup_and_handle", cup_and_handle),
    ("double_bottom", double_bottom),
    ("double_top", double_top),
    ("inverse_head_and_shoulders", lambda d, c, p: head_and_shoulders(d, c, p, inverse=True)),
    ("head_and_shoulders", lambda d, c, p: head_and_shoulders(d, c, p, inverse=False)),
    ("triangle", triangle),
    ("flag", flag),
    ("rectangle", rectangle),
]


# ---------------------------------------------------------------------------
# Base rates
#
# The honest answer to "what is going to happen" is a frequency, not a
# forecast. This walks the stock's own history, finds every prior instance of
# the same shape, and reports what happened next.
#
# Two rules keep it from flattering itself:
#   · the detector only ever sees bars up to the instance being measured, so
#     it cannot use information that did not exist at the time
#   · instances closer together than the measurement horizon are dropped, so
#     one long move is not counted as five separate successes
# ---------------------------------------------------------------------------

def _forward_returns(close, i, horizons):
    out = {}
    base = float(close[i])
    if base <= 0:
        return out
    for h in horizons:
        j = i + h
        if j < len(close):
            out[h] = (float(close[j]) - base) / base * 100.0
    return out


def base_rate(df, detector, horizons=HORIZONS, step=3, min_sample=MIN_SAMPLE):
    """
    Historical outcomes for one detector on this symbol.

    Deliberately expensive-looking and deliberately capped: it re-runs the
    detector over a sliding window, which is the only way to be sure the
    instances it counts are the ones this code would actually have flagged.
    """
    n = len(df)
    if n < 160:
        return None
    close = df["Close"].values.astype(float)
    max_h = max(horizons)

    hits, last_i = [], -10 ** 9
    # Leave max_h bars at the end so every counted instance has a full outcome.
    for i in range(140, n - max_h, step):
        if i - last_i < max_h:
            continue
        win = df.iloc[:i + 1]
        try:
            c = _ctx(win)
            piv = _alternating(_pivots(win))
            res = detector(win, c, piv)
        except Exception:
            continue
        if not res or res["status"] == "failed":
            continue
        fwd = _forward_returns(close, i, horizons)
        if not fwd:
            continue
        hits.append({"i": i, "direction": res["direction"], "fwd": fwd})
        last_i = i

    if len(hits) < min_sample:
        return {"instances": len(hits), "reliable": False,
                "note": (f"Only {len(hits)} prior instance"
                         f"{'' if len(hits) == 1 else 's'} in this stock's history — "
                         "too few to quote a rate. Treat the pattern as a shape, not "
                         "as a statistic.")}

    out = {"instances": len(hits), "reliable": True, "horizons": {}}
    for h in horizons:
        vals = [x["fwd"][h] for x in hits if h in x["fwd"]]
        if not vals:
            continue
        direction = hits[-1]["direction"]
        if direction == "bearish":
            resolved = sum(1 for v in vals if v < 0)
        else:
            resolved = sum(1 for v in vals if v > 0)
        arr = np.array(vals, dtype=float)
        out["horizons"][h] = {
            "sessions": h,
            "n": len(vals),
            "resolved_in_direction_pct": round(100.0 * resolved / len(vals)),
            "median_return_pct": round(float(np.median(arr)), 2),
            "mean_return_pct": round(float(np.mean(arr)), 2),
            "best_pct": round(float(np.max(arr)), 2),
            "worst_pct": round(float(np.min(arr)), 2),
        }
    out["note"] = (f"Measured across {len(hits)} prior instances of this shape in this "
                   "stock's own history, each scored only on bars that existed at the "
                   "time. A frequency, not a probability for this instance.")
    return out


# ---------------------------------------------------------------------------
# Top level
# ---------------------------------------------------------------------------

def _confluence(res, fwd):
    """
    Does the forward indicator picture agree with the pattern, or argue with
    it? Disagreement is the useful signal and is reported as such rather than
    quietly dropped, because a bullish shape under a bearish Supertrend is
    exactly the case a reader needs told.
    """
    if not fwd or not fwd.get("available"):
        return None
    agree, against = [], []
    st = fwd.get("supertrend") or {}
    if st.get("direction"):
        (agree if st["direction"] == res["direction"] else against).append(
            f"Supertrend is {st['direction']}")
    cross = fwd.get("ema_cross_20_50") or {}
    if cross.get("state"):
        bull = cross["state"] == "fast above slow"
        (agree if (bull == (res["direction"] == "bullish")) else against).append(
            f"20-day EMA is {'above' if bull else 'below'} the 50-day")
    r = (fwd.get("rsi") or {}).get("current")
    if r is not None:
        if res["direction"] == "bullish" and r < 30:
            agree.append(f"RSI {r:.0f} is oversold")
        elif res["direction"] == "bearish" and r > 70:
            agree.append(f"RSI {r:.0f} is overbought")
        elif res["direction"] == "bullish" and r > 70:
            against.append(f"RSI {r:.0f} is already stretched")
        elif res["direction"] == "bearish" and r < 30:
            against.append(f"RSI {r:.0f} is already washed out")
    return {"agrees": agree, "argues": against,
            "verdict": ("The indicators line up with the shape." if agree and not against
                        else "The indicators argue with the shape." if against and not agree
                        else "Mixed — the indicators are split on this one."
                        if agree and against else "Nothing to add.")}


def analyse(df, symbol="", with_base_rates=True, timeframe="1D"):
    """
    Every pattern present, with its geometry, its base rate, and the forward
    indicator mechanics around it.

    Returns patterns sorted by confidence. An empty list is a real answer and
    the common one — most stocks, most days, are not in a textbook pattern,
    and a detector that always finds something is a detector that has stopped
    detecting.
    """
    df = df.dropna(subset=["Close"])
    if len(df) < 80:
        return {"available": False,
                "message": "Need at least 80 bars to look for patterns on this timeframe."}

    c = _ctx(df)
    piv = _alternating(_pivots(df))
    fwd = None
    try:
        import forward
        fwd = forward.build(df)
    except Exception:
        fwd = None

    found = []
    for key, fn in DETECTORS:
        try:
            res = fn(df, c, piv)
        except Exception:
            continue
        if not res:
            continue
        res["key"] = key
        res["timeframe"] = timeframe
        if with_base_rates:
            try:
                res["base_rate"] = base_rate(df, fn)
            except Exception:
                res["base_rate"] = None
        res["confluence"] = _confluence(res, fwd)
        # Distance to the trigger, which is the number a reader actually wants.
        last = float(c["close"][-1])
        if res["trigger"]:
            res["distance_to_trigger_pct"] = round((res["trigger"] - last) / last * 100, 2)
        found.append(res)

    found.sort(key=lambda r: (r["status"] == "confirmed", r["confidence"]), reverse=True)

    return {
        "available": True,
        "symbol": symbol,
        "timeframe": timeframe,
        "as_of": _date(c["index"], c["n"] - 1),
        "last_close": round(float(c["close"][-1]), 2),
        "atr": round(c["atr"], 2),
        "patterns": found,
        "count": len(found),
        "forward": fwd,
        "pivots": [{"date": _date(c["index"], i), "t": _epoch(c["index"], i),
                    "price": round(p, 2),
                    "kind": "high" if k == "H" else "low"} for i, p, k in piv[-12:]],
        "disclaimer": (
            "Patterns are shapes measured on past prices. A measured move is arithmetic "
            "on the pattern's own geometry, not a price forecast, and a base rate is how "
            "often this shape resolved in this stock's history, not the probability it "
            "resolves that way now. Nothing here is a recommendation to buy or sell."),
        "method": (
            f"Swing points need {PIVOT_K} bars either side. Every tolerance is measured in "
            "ATR rather than percent, so the same rule means the same thing on a ₹40 stock "
            "and a ₹4,000 one. A pattern is 'forming' until price closes through its "
            "trigger, 'confirmed' once it does, and 'failed' if it closes through its "
            "invalidation level first."),
    }
