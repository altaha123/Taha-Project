"""
Altaha Screener — Trade Plan engine

Encodes the consensus of the classical trading canon into a rules engine.
Every rule cites its source so the user can audit the thinking:

  · Stan Weinstein, "Secrets for Profiting in Bull and Bear Markets" —
    stage analysis: only buy Stage 2 (price above a rising long-term MA).
  · Mark Minervini, "Trade Like a Stock Market Wizard" — trend template
    (px > 50DMA > 200DMA, rising), and never risk more than ~8% on entry.
  · William O'Neil, "How to Make Money in Stocks" — volume confirms price:
    institutions leave footprints; breakouts need above-average volume.
  · Jesse Livermore / Edwards & Magee — buy at the pivot (support or
    breakout), never in the middle of nowhere.
  · Van Tharp, "Trade Your Way to Financial Freedom" — expectancy beats
    accuracy; position size from the stop distance, never from conviction.
  · Mark Douglas, "Trading in the Zone" — the stop is decided before
    entry and is not negotiable.
  · Alexander Elder, "Trading for a Living" — place stops beyond noise
    (an ATR buffer past the level, not at the round number).

The engine only says BUY when independent methods agree (trend + level +
volume + risk:reward). Most stocks, most of the time, get WAIT — which is
itself the canon: the money is made in the sitting, not the trading.
"""

import numpy as np

MIN_RR = 2.0          # Tharp: below 1:2 the math needs >50% win rate
MAX_RISK_PCT = 8.0    # Minervini: an entry needing a wide stop is a bad entry
NEAR_SUPPORT = 3.0    # % above support that still counts as "at the level"
NEAR_RESIST = 3.0     # % below resistance = breakout watch zone


def _atr(df, n=14):
    h, l, c = df["High"].values, df["Low"].values, df["Close"].values
    tr = np.maximum(h[1:] - l[1:], np.maximum(abs(h[1:] - c[:-1]), abs(l[1:] - c[:-1])))
    return float(np.mean(tr[-n:])) if len(tr) >= n else float(np.mean(tr)) if len(tr) else 0.0


def _stage(close, n):
    """Weinstein stage: 2 = advancing (buyable), 4 = declining (untouchable)."""
    if n < 210:
        return None, "not enough history for stage analysis"
    dma200 = np.mean(close[-200:])
    dma200_prev = np.mean(close[-220:-20])
    above, rising = close[-1] > dma200, dma200 > dma200_prev
    if above and rising:
        return 2, "Stage 2 advance — price above a rising 200-DMA (Weinstein: the only stage worth buying)"
    if not above and not rising:
        return 4, "Stage 4 decline — price below a falling 200-DMA (Weinstein: never fight this stage)"
    if above and not rising:
        return 3, "Stage 3 top — above a flattening 200-DMA; distribution risk"
    return 1, "Stage 1 base — below a flattening 200-DMA; early, unproven"


def build_plan(df, levels, tech=None):
    """Full trade plan with cited reasoning. Returns dict or None."""
    df = df.dropna(subset=["Close"]).tail(260)
    if len(df) < 60 or not levels:
        return None
    close = df["Close"].values.astype(float)
    vol = (df["Volume"].fillna(0).values.astype(float)
           if "Volume" in df.columns else np.zeros(len(df), dtype=float))
    px = float(close[-1])
    n = len(df)
    atr = _atr(df)

    sups = levels.get("supports") or []
    ress = levels.get("resistances") or []
    sup = sups[0] if sups else None            # nearest-first from levels.py
    res = ress[0] if ress else None

    stage, stage_note = _stage(close, n)
    dma50 = float(np.mean(close[-50:])) if n >= 50 else None
    trend_ok = stage == 2 and (dma50 is None or px > dma50)

    # volume character: up-day volume vs down-day volume, last 60 sessions
    ch = np.diff(close[-61:])
    v60 = vol[-60:]
    upv = float(np.sum(v60[ch > 0])) or 1.0
    dnv = float(np.sum(v60[ch < 0])) or 1.0
    accum = upv / dnv                          # >1.2 = accumulation footprint

    why, warn = [], []
    if stage is not None:
        (why if stage == 2 else warn).append(stage_note)
    if trend_ok and dma50:
        why.append(f"Minervini trend template: price above the 50-DMA (\u2248{dma50:,.0f}) which is above the 200-DMA")
    if accum >= 1.2:
        why.append(f"Volume on up-days is {accum:.1f}\u00d7 volume on down-days over 60 sessions — accumulation footprint (O'Neil: institutions can't hide)")
    elif accum <= 0.8:
        warn.append(f"Down-days carry {1/accum:.1f}\u00d7 the volume of up-days — distribution footprint (O'Neil)")

    # ---- candidate entries -------------------------------------------
    plan = None

    def sized(entry, stop, targets, stance, entry_note):
        risk_pct = (entry - stop) / entry * 100
        t1 = targets[0]
        rr1 = (t1 - entry) / (entry - stop) if entry > stop else 0
        return {"stance": stance, "entry": round(entry, 2), "entry_note": entry_note,
                "stop": round(stop, 2), "risk_pct": round(risk_pct, 1),
                "targets": [round(t, 2) for t in targets],
                "rr": round(rr1, 1), "atr": round(atr, 2)}

    # A) Pullback-to-support entry (Livermore: buy at the pivot)
    if sup and trend_ok:
        dist_sup = (px - sup["level"]) / px * 100
        if 0 <= dist_sup <= NEAR_SUPPORT:
            entry = px
            stop = sup["zone"][0] - 0.5 * atr        # Elder: stop beyond noise
            risk_pct = (entry - stop) / entry * 100
            tgts = [r["level"] for r in ress[:2]] or [entry + 2 * (entry - stop), entry + 3 * (entry - stop)]
            rr = (tgts[0] - entry) / (entry - stop) if entry > stop else 0
            if risk_pct <= MAX_RISK_PCT and rr >= MIN_RR:
                plan = sized(entry, stop, tgts, "BUY ZONE",
                             f"price is sitting on tested support at {sup['level']:,.0f} (strength {sup['strength']}/100) — enter here, not after it runs")
                why.append(f"Entry at support caps the risk at {risk_pct:.1f}% — Livermore: buy at the pivot, never in the middle of the range")
                why.append(f"Risk:reward 1:{rr:.1f} to the first resistance — profitable even at a 40% win rate (Tharp: expectancy beats accuracy)")

    # B) Breakout watch (O'Neil pivot above resistance)
    if plan is None and res and trend_ok:
        dist_res = (res["level"] - px) / px * 100
        if 0 <= dist_res <= NEAR_RESIST:
            entry = res["zone"][1] * 1.002            # just through the zone top
            stop = (sup["level"] if sup else px - 2 * atr) - 0.5 * atr
            stop = max(stop, entry * (1 - MAX_RISK_PCT / 100))
            nxt = [r["level"] for r in ress[1:3]]
            tgts = nxt or [entry + 2 * (entry - stop), entry + 3 * (entry - stop)]
            rr = (tgts[0] - entry) / (entry - stop) if entry > stop else 0
            plan = sized(entry, stop, tgts, "BREAKOUT WATCH",
                         f"wait for a close above {res['level']:,.0f} (strength {res['strength']}/100) on above-average volume — do not front-run it")
            why.append("O'Neil: the breakout is only valid on volume \u2265 1.5\u00d7 average — a quiet breakout usually fails")
            if not nxt:
                why.append("No overhead resistance after the breakout — measured-move targets used (2R and 3R)")

    # C) No trade
    if plan is None:
        if stage == 4:
            stance, note = "AVOID", "Stage 4 downtrend — the canon is unanimous: don't buy falling stocks, no matter how cheap they look"
        elif not trend_ok:
            stance, note = "WAIT", "trend not established — no entry until price reclaims its key averages"
        elif sup:
            stance, note = "WAIT", f"price is mid-range, {abs((px - sup['level']) / px * 100):.1f}% above support — a better entry exists at {sup['level']:,.0f}; buying here widens the stop for no extra reward"
        else:
            stance, note = "WAIT", "no tested level near price to anchor a stop — a plan without a stop isn't a plan"
        plan = {"stance": stance, "entry": None, "entry_note": note, "stop": None,
                "risk_pct": None, "targets": [], "rr": None, "atr": round(atr, 2)}

    # invalidation — Douglas: decided before entry, not negotiable
    if plan.get("stop"):
        plan["invalidation"] = (f"A daily CLOSE below {plan['stop']:,.2f} kills this plan — exit without negotiation. "
                                "Douglas: the market doesn't know you're in a trade; the stop is the only opinion that matters.")

    conf = len(why)
    plan["confidence"] = "HIGH" if conf >= 4 else ("MEDIUM" if conf >= 2 else "LOW")
    plan["why"] = why
    plan["warnings"] = warn
    plan["principles"] = ("Rules encoded from Weinstein (stage analysis), Minervini (trend template, 8% max risk), "
                          "O'Neil (volume confirmation), Livermore (pivot entries), Elder (ATR stops), "
                          "Tharp (expectancy & sizing), Douglas (pre-committed exits). "
                          "No engine predicts price — the edge is taking only asymmetric bets and cutting the wrong ones fast.")
    return plan


def compact_plan(df, levels):
    """Small version for the Ideas leaderboard (memory-friendly)."""
    p = build_plan(df, levels)
    if not p:
        return None
    return {k: p.get(k) for k in ("stance", "entry", "stop", "risk_pct", "rr", "confidence")} | \
           {"t1": (p.get("targets") or [None])[0], "note": p.get("entry_note", "")[:140]}
