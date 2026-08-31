"""
Altaha Screener — Forward-looking indicator mechanics

Every number in this file is arithmetic on values that already exist. None of
it is a forecast, and that distinction is the whole design.

An indicator is a function of past prices plus tomorrow's close. Fix the
history — which is already fixed — and each indicator becomes a function of one
unknown. So instead of guessing where price goes, you can solve for the price
at which something happens:

    "RSI(14) reaches 70 at a close of ₹2,118."
    "Supertrend flips bearish on a close under ₹1,904."
    "The 20-day average crosses the 50-day in 6 sessions if price holds here."

Those are facts about the indicators, checkable with a calculator, and they are
genuinely forward-looking in the only sense that survives contact with a market
— they tell you what has to happen, not what will.

WHAT THIS DELIBERATELY REFUSES TO DO
Extrapolate price. A moving average projected forward on the assumption that
price keeps rising at its current rate is a drawing, not an analysis, and it is
the standard way "forward-looking indicators" become nonsense. Where a
projection needs a price path this module states the assumption in the payload
("if price holds flat") and offers the flat case, because that is the one
assumption that adds no opinion of its own.
"""

import numpy as np
import pandas as pd

from engine import atr, ema, macd, rsi


def _f(x):
    try:
        v = float(x)
        return None if v != v else round(v, 2)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Solving for tomorrow
# ---------------------------------------------------------------------------

def rsi_trigger_prices(close, period=14, targets=(30, 50, 70)):
    """
    The close that would put RSI at each target on the next bar.

    Wilder's RSI smooths gains and losses:  avg = (prev*(p-1) + today)/p.
    With prev_gain and prev_loss known, RSI = 100 - 100/(1+RS) inverts cleanly
    to a required gain or loss, and from there to a price.
    """
    s = pd.Series(close, dtype=float).dropna()
    if len(s) < period + 2:
        return None
    delta = s.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    ag = gain.ewm(alpha=1 / period, adjust=False).mean().iloc[-1]
    al = loss.ewm(alpha=1 / period, adjust=False).mean().iloc[-1]
    last = float(s.iloc[-1])

    out = {}
    for t in targets:
        if t <= 0 or t >= 100:
            continue
        rs_needed = t / (100.0 - t)
        # Try the "up day" branch: loss decays, gain must supply the ratio.
        al_next = al * (period - 1) / period
        g_needed = rs_needed * al_next
        up_move = g_needed * period - ag * (period - 1)
        if up_move >= 0:
            out[t] = _f(last + up_move)
            continue
        # Otherwise it is a down day: gain decays, loss must supply it.
        ag_next = ag * (period - 1) / period
        if rs_needed <= 0:
            continue
        l_needed = ag_next / rs_needed
        down_move = l_needed * period - al * (period - 1)
        out[t] = _f(last - max(down_move, 0.0))
    cur = rsi(s, period)
    return {"current": _f(cur.iloc[-1]), "prices": out,
            "note": "The close that would put RSI(14) at each level on the next bar."}


def supertrend_flip_price(df, period=10, mult=3.0):
    """
    The close that flips the Supertrend regime on the next bar.

    engine.supertrend() returns the DIRECTION (+1/-1), not the band, so the
    bands are recomputed here. Anything comparing a price against that
    function's output is comparing rupees to +1, which is always false — a
    silent no-op rather than a visible error.
    """
    if len(df) < period + 2:
        return None
    a = atr(df, period)
    hl2 = (df["High"] + df["Low"]) / 2.0
    upper = hl2 + mult * a
    lower = hl2 - mult * a
    close = df["Close"]

    ub = upper.copy()
    lb = lower.copy()
    direction = 1
    for i in range(1, len(df)):
        ub.iloc[i] = min(upper.iloc[i], ub.iloc[i - 1]) if close.iloc[i - 1] <= ub.iloc[i - 1] else upper.iloc[i]
        lb.iloc[i] = max(lower.iloc[i], lb.iloc[i - 1]) if close.iloc[i - 1] >= lb.iloc[i - 1] else lower.iloc[i]
        if close.iloc[i] > ub.iloc[i - 1]:
            direction = 1
        elif close.iloc[i] < lb.iloc[i - 1]:
            direction = -1
    return {
        "direction": "bullish" if direction == 1 else "bearish",
        "band": _f(lb.iloc[-1] if direction == 1 else ub.iloc[-1]),
        "flip_price": _f(lb.iloc[-1] if direction == 1 else ub.iloc[-1]),
        "note": ("Supertrend is bullish; a close below this band flips it bearish."
                 if direction == 1 else
                 "Supertrend is bearish; a close above this band flips it bullish."),
    }


def ma_cross_projection(close, fast=20, slow=50, max_sessions=60):
    """
    How many sessions until the fast average crosses the slow one, if price
    simply holds where it is.

    The flat-price assumption is the honest one: it adds no view. Both averages
    still move — they are shedding old bars — so the answer is not "never", it
    is a real number of sessions, and it says which way the gap is closing.
    """
    s = pd.Series(close, dtype=float).dropna()
    if len(s) < slow + 5:
        return None
    f = ema(s, fast)
    sl = ema(s, slow)
    fv, sv = float(f.iloc[-1]), float(sl.iloc[-1])
    above = fv > sv
    last = float(s.iloc[-1])

    kf, ks = 2.0 / (fast + 1), 2.0 / (slow + 1)
    a, b = fv, sv
    for step in range(1, max_sessions + 1):
        a = a + kf * (last - a)
        b = b + ks * (last - b)
        if (a > b) != above:
            return {
                "fast": fast, "slow": slow,
                "current_gap_pct": _f((fv - sv) / sv * 100 if sv else None),
                "state": "fast above slow" if above else "fast below slow",
                "sessions_to_cross": step,
                "cross_direction": "death cross" if above else "golden cross",
                "assumption": "price holds at today's close",
                "note": (f"If price simply stays at ₹{last:,.2f}, the {fast}-day crosses "
                         f"the {slow}-day in about {step} session{'s' if step != 1 else ''}."),
            }
    return {
        "fast": fast, "slow": slow,
        "current_gap_pct": _f((fv - sv) / sv * 100 if sv else None),
        "state": "fast above slow" if above else "fast below slow",
        "sessions_to_cross": None,
        "assumption": "price holds at today's close",
        "note": (f"No cross within {max_sessions} sessions at today's price — the "
                 "averages are not converging on their own."),
    }


def price_for_ma_touch(close, period, sessions=1):
    """The close that would put price exactly on its own N-day EMA next bar."""
    s = pd.Series(close, dtype=float).dropna()
    if len(s) < period + 2:
        return None
    e = float(ema(s, period).iloc[-1])
    k = 2.0 / (period + 1)
    # price_next == ema_next  =>  p = e + k(p - e)  =>  p = e
    return {"period": period, "ema_now": _f(e),
            "price_to_touch": _f(e),
            "distance_pct": _f((float(s.iloc[-1]) - e) / e * 100 if e else None)}


def bollinger_state(close, period=20, mult=2.0, lookback=250):
    """
    Where the band width sits against its own history.

    A squeeze does not say which way price breaks and this does not pretend
    otherwise — it says the range is unusually tight, which historically
    precedes expansion in either direction.
    """
    s = pd.Series(close, dtype=float).dropna()
    if len(s) < period + 20:
        return None
    mid = s.rolling(period).mean()
    sd = s.rolling(period).std()
    width = ((mid + mult * sd) - (mid - mult * sd)) / mid.replace(0, np.nan) * 100
    w = width.dropna().tail(lookback)
    if len(w) < 30:
        return None
    cur = float(w.iloc[-1])
    pct = float((w < cur).mean() * 100)
    if pct <= 15:
        state, note = "squeeze", ("Band width is in the tightest "
                                  f"{pct:.0f}% of the last {len(w)} sessions. Tight ranges "
                                  "expand — this says nothing about which way.")
    elif pct >= 85:
        state, note = "expanded", (f"Band width is wider than {pct:.0f}% of the last "
                                   f"{len(w)} sessions. Moves this stretched tend to "
                                   "consolidate rather than continue at the same pace.")
    else:
        state, note = "normal", f"Band width sits at the {pct:.0f}th percentile of its own range."
    return {"width_pct": _f(cur), "percentile": round(pct), "state": state,
            "upper": _f(mid.iloc[-1] + mult * sd.iloc[-1]),
            "lower": _f(mid.iloc[-1] - mult * sd.iloc[-1]),
            "note": note}


def macd_cross_projection(close, max_sessions=30):
    """Sessions until the MACD line crosses its signal, if price holds flat."""
    s = pd.Series(close, dtype=float).dropna()
    if len(s) < 60:
        return None
    line, sig, _hist = macd(s)
    lv, sv = float(line.iloc[-1]), float(sig.iloc[-1])
    above = lv > sv
    last = float(s.iloc[-1])

    e12 = float(ema(s, 12).iloc[-1])
    e26 = float(ema(s, 26).iloc[-1])
    k12, k26, k9 = 2 / 13.0, 2 / 27.0, 2 / 10.0
    a, b, sg = e12, e26, sv
    for step in range(1, max_sessions + 1):
        a = a + k12 * (last - a)
        b = b + k26 * (last - b)
        ln = a - b
        sg = sg + k9 * (ln - sg)
        if (ln > sg) != above:
            return {"state": "above signal" if above else "below signal",
                    "sessions_to_cross": step,
                    "cross_direction": "bearish crossover" if above else "bullish crossover",
                    "assumption": "price holds at today's close",
                    "note": (f"At an unchanged price the MACD line crosses its signal in "
                             f"about {step} session{'s' if step != 1 else ''}.")}
    return {"state": "above signal" if above else "below signal",
            "sessions_to_cross": None, "assumption": "price holds at today's close",
            "note": f"No crossover within {max_sessions} sessions at today's price."}


def expected_range(df, sessions=(1, 5, 10)):
    """
    The range price has covered per session lately, scaled by the square root
    of time. A dispersion estimate, with no direction in it whatsoever.
    """
    if len(df) < 20:
        return None
    a = float(atr(df, 14).iloc[-1])
    last = float(df["Close"].iloc[-1])
    if not a or a != a or last <= 0:
        return None
    out = {}
    for h in sessions:
        band = a * (h ** 0.5)
        out[h] = {"sessions": h, "band": _f(band),
                  "low": _f(last - band), "high": _f(last + band),
                  "pct": _f(band / last * 100)}
    return {"atr": _f(a), "bands": out,
            "note": ("One ATR scaled by the square root of the horizon. It describes how "
                     "far this stock typically travels, not which way it goes, and it is "
                     "not a confidence interval.")}


def build(df):
    """Everything above, for one symbol, with the assumptions attached."""
    close = df["Close"].dropna()
    if len(close) < 60:
        return {"available": False,
                "message": "Not enough history to project the indicators."}
    return {
        "available": True,
        "last_close": _f(close.iloc[-1]),
        "rsi": rsi_trigger_prices(close),
        "supertrend": supertrend_flip_price(df),
        "ema_cross_20_50": ma_cross_projection(close, 20, 50),
        "ema_cross_50_200": ma_cross_projection(close, 50, 200) if len(close) > 210 else None,
        "macd": macd_cross_projection(close),
        "bollinger": bollinger_state(close),
        "ema20_touch": price_for_ma_touch(close, 20),
        "ema50_touch": price_for_ma_touch(close, 50),
        "expected_range": expected_range(df),
        "method": ("Each figure is solved from the indicator's own formula with history "
                   "held fixed — the price at which something happens, or the number of "
                   "sessions it takes at an unchanged price. Nothing here extrapolates "
                   "price, and nothing here is a forecast."),
    }
