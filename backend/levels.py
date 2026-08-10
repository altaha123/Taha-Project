"""
Altaha Screener — Support & Resistance engine

Method (and why it's built this way):

1. FRACTAL PIVOTS — a bar whose high is the highest of its neighbourhood
   (±3 bars) is a swing high; same idea for swing lows. These are the points
   where price actually reversed, which is the only honest definition of
   support/resistance — not lines drawn after the fact.

2. CLUSTERING — pivots within ~1.5% of each other are merged into a zone.
   Real levels are zones, not exact prices: institutions work orders across
   a band, so three reversals at 1,412 / 1,405 / 1,418 are one level.

3. STRENGTH SCORING — each zone is scored 0-100 from:
     · touches   — more independent reversals = more proven
     · recency   — a level tested last month matters more than last year
     · volume    — reversals on heavy volume mean real money defended it
     · role flip — a zone that served as BOTH support and resistance
                   (broken, then retested from the other side) is the
                   strongest pattern in classical charting

4. CONFLUENCE — zones near the 50/200-DMA or the 52-week extreme get a
   note: independent methods agreeing on one price is what "accurate"
   actually means in technical analysis.

Everything returned includes a human "why" so the user can audit the level
instead of trusting a black box.
"""

import numpy as np


TOL = 0.015          # 1.5% clustering band
PIVOT_K = 3          # neighbourhood half-width for a fractal pivot
LOOKBACK = 260       # ~1 trading year
MAX_DIST = 0.28      # ignore zones further than 28% from price


def _fmt_date(ts):
    try:
        return ts.strftime("%d %b %y")
    except Exception:
        return str(ts)[:10]


def _pivots(high, low, k=PIVOT_K):
    out = []
    n = len(high)
    for i in range(k, n - k):
        win_h = high[i - k:i + k + 1]
        win_l = low[i - k:i + k + 1]
        if high[i] >= win_h.max():
            out.append((float(high[i]), i, "high"))
        if low[i] <= win_l.min():
            out.append((float(low[i]), i, "low"))
    return out


def compute_levels(df, max_each=3):
    """Return {'supports': [...], 'resistances': [...], 'method': str} or None."""
    df = df.dropna(subset=["Close"]).tail(LOOKBACK)
    if len(df) < 60:
        return None

    close = df["Close"].values.astype(float)
    high = df["High"].fillna(df["Close"]).values.astype(float)
    low = df["Low"].fillna(df["Close"]).values.astype(float)
    vol = df["Volume"].fillna(0).values.astype(float)
    dates = df.index
    n = len(df)
    px = float(close[-1])
    avg_vol = max(1.0, float(np.mean(vol[-120:])) if n >= 120 else float(np.mean(vol)))

    piv = _pivots(high, low)
    if not piv:
        return None

    # --- cluster pivots into zones -------------------------------------
    piv.sort(key=lambda p: p[0])
    clusters = []
    for price, idx, kind in piv:
        if clusters and abs(price - np.median(clusters[-1]["prices"])) <= TOL * price:
            c = clusters[-1]
        else:
            c = {"prices": [], "idx": [], "kinds": set()}
            clusters.append(c)
        c["prices"].append(price)
        c["idx"].append(idx)
        c["kinds"].add(kind)

    # --- confluence anchors --------------------------------------------
    dma50 = float(np.mean(close[-50:])) if n >= 50 else None
    dma200 = float(np.mean(close[-200:])) if n >= 200 else None
    hi52, hi52_i = float(high.max()), int(high.argmax())
    lo52, lo52_i = float(low.min()), int(low.argmin())

    def near(a, b):
        return a is not None and b is not None and abs(a - b) <= TOL * b

    # --- score every zone ----------------------------------------------
    zones = []
    for c in clusters:
        level = float(np.median(c["prices"]))
        dist = abs(level - px) / px
        if dist > MAX_DIST or dist < 0.004:
            continue
        touches = len(c["prices"])
        last_i = max(c["idx"])
        recency = last_i / (n - 1)                       # 0 old … 1 today
        zvol = float(np.mean([vol[i] for i in c["idx"]])) / avg_vol
        flip = ("high" in c["kinds"]) and ("low" in c["kinds"])

        score = (min(touches, 4) * 12          # up to 48
                 + recency * 25                # up to 25
                 + min(zvol, 2.0) * 8.5        # up to 17
                 + (10 if flip else 0))        # flip-zone bonus
        strength = int(round(min(100, score)))

        why = [f"price reversed here {touches}\u00d7, last on {_fmt_date(dates[last_i])}"]
        if zvol >= 1.3:
            why.append(f"those reversals ran on {zvol:.1f}\u00d7 average volume \u2014 real money defended this zone")
        if flip:
            why.append("has acted as BOTH support and resistance \u2014 flip zones are the most reliable levels in charting")
        if near(level, dma200):
            why.append(f"sits on the 200-DMA (\u2248{dma200:,.0f}) \u2014 long-term trend line agrees")
        elif near(level, dma50):
            why.append(f"sits on the 50-DMA (\u2248{dma50:,.0f}) \u2014 medium-term trend line agrees")
        if near(level, hi52):
            why.append("this is the 52-week high \u2014 the ceiling where the last big rally stalled")
        if near(level, lo52):
            why.append("this is the 52-week low \u2014 the floor of the entire year")

        zones.append({
            "level": round(level, 2),
            "zone": [round(float(min(c["prices"])), 2), round(float(max(c["prices"])), 2)],
            "kind": "support" if level < px else "resistance",
            "strength": strength,
            "touches": touches,
            "last_touch": _fmt_date(dates[last_i]),
            "distance_pct": round((level - px) / px * 100, 1),
            "why": (lambda s: s[:1].upper() + s[1:])("; ".join(why)),
        })

    # 52-week extremes as standalone levels when no cluster covered them
    if not any(near(z["level"], hi52) for z in zones) and (hi52 - px) / px <= MAX_DIST and hi52 > px * 1.004:
        zones.append({"level": round(hi52, 2), "zone": [round(hi52, 2), round(hi52, 2)],
                      "kind": "resistance", "strength": 55, "touches": 1,
                      "last_touch": _fmt_date(dates[hi52_i]),
                      "distance_pct": round((hi52 - px) / px * 100, 1),
                      "why": "52-week high \u2014 supply sits where the last rally topped out; "
                             "breakouts above it often accelerate because nobody overhead is stuck at a loss."})
    if not any(near(z["level"], lo52) for z in zones) and (px - lo52) / px <= MAX_DIST and lo52 < px * 0.996:
        zones.append({"level": round(lo52, 2), "zone": [round(lo52, 2), round(lo52, 2)],
                      "kind": "support", "strength": 55, "touches": 1,
                      "last_touch": _fmt_date(dates[lo52_i]),
                      "distance_pct": round((lo52 - px) / px * 100, 1),
                      "why": "52-week low \u2014 the price the market refused to sell below all year."})

    supports = sorted([z for z in zones if z["kind"] == "support"],
                      key=lambda z: -z["strength"])[:max_each]
    resist = sorted([z for z in zones if z["kind"] == "resistance"],
                    key=lambda z: -z["strength"])[:max_each]
    # display nearest-first
    supports.sort(key=lambda z: -z["level"])
    resist.sort(key=lambda z: z["level"])

    if not supports and not resist:
        return None

    return {
        "current": round(px, 2),
        "supports": supports,
        "resistances": resist,
        "method": ("Swing highs and lows from the last year are clustered into zones (\u00b11.5%), "
                   "then scored on touches, recency, volume at the reversal, and whether the zone "
                   "flipped roles. Zones agreeing with the 50/200-DMA or 52-week extremes are flagged \u2014 "
                   "independent methods pointing at one price is what makes a level trustworthy."),
    }
