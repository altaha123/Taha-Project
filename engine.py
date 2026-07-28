"""
Altaha Screener — Scoring Engine
Where Logic Meets Validations

Every function returns not just a value but the inputs that produced it,
so the frontend can render a full audit trail. No black boxes.
"""

import math
import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Technical indicators (validated textbook formulas, computed from raw OHLCV)
# ---------------------------------------------------------------------------

def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def wma(series: pd.Series, period: int) -> pd.Series:
    weights = np.arange(1, period + 1)
    return series.rolling(period).apply(
        lambda x: np.dot(x, weights) / weights.sum(), raw=True
    )


def hma(series: pd.Series, period: int = 21) -> pd.Series:
    """Hull Moving Average: WMA(2*WMA(n/2) - WMA(n), sqrt(n))"""
    half = max(2, period // 2)
    sqrt_n = max(2, int(math.sqrt(period)))
    return wma(2 * wma(series, half) - wma(series, period), sqrt_n)


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def macd(series: pd.Series):
    line = ema(series, 12) - ema(series, 26)
    signal = line.ewm(span=9, adjust=False).mean()
    return line, signal, line - signal


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    hl = df["High"] - df["Low"]
    hc = (df["High"] - df["Close"].shift()).abs()
    lc = (df["Low"] - df["Close"].shift()).abs()
    tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    up = df["High"].diff()
    down = -df["Low"].diff()
    plus_dm = pd.Series(np.where((up > down) & (up > 0), up, 0.0), index=df.index)
    minus_dm = pd.Series(np.where((down > up) & (down > 0), down, 0.0), index=df.index)
    tr = atr(df, period)
    plus_di = 100 * plus_dm.ewm(alpha=1 / period, adjust=False).mean() / tr
    minus_di = 100 * minus_dm.ewm(alpha=1 / period, adjust=False).mean() / tr
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return dx.ewm(alpha=1 / period, adjust=False).mean()


def supertrend(df: pd.DataFrame, period: int = 10, mult: float = 3.0) -> pd.Series:
    """Returns +1 (price above supertrend, bullish) / -1 (bearish) per bar."""
    _atr = atr(df, period)
    hl2 = (df["High"] + df["Low"]) / 2
    upper = hl2 + mult * _atr
    lower = hl2 - mult * _atr
    close = df["Close"]

    direction = pd.Series(1, index=df.index, dtype=int)
    ub, lb = upper.copy(), lower.copy()
    for i in range(1, len(df)):
        ub.iloc[i] = min(upper.iloc[i], ub.iloc[i - 1]) if close.iloc[i - 1] <= ub.iloc[i - 1] else upper.iloc[i]
        lb.iloc[i] = max(lower.iloc[i], lb.iloc[i - 1]) if close.iloc[i - 1] >= lb.iloc[i - 1] else lower.iloc[i]
        if close.iloc[i] > ub.iloc[i - 1]:
            direction.iloc[i] = 1
        elif close.iloc[i] < lb.iloc[i - 1]:
            direction.iloc[i] = -1
        else:
            direction.iloc[i] = direction.iloc[i - 1]
    return direction


# ---------------------------------------------------------------------------
# Technical scoring — each check contributes points and an audit record
# ---------------------------------------------------------------------------

def fmt(x, dec=2):
    if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))):
        return None
    return round(float(x), dec)


def technical_score(df: pd.DataFrame) -> dict:
    close = df["Close"]
    price = close.iloc[-1]
    checks = []
    earned, possible = 0, 0

    def add(name, points, max_pts, value, formula, explain):
        nonlocal earned, possible
        earned += points
        possible += max_pts
        checks.append({
            "name": name, "points": points, "max": max_pts,
            "value": value, "formula": formula, "explain": explain,
        })

    # Trend structure: price vs EMA 20/50/200 (30 pts)
    e20, e50, e200 = ema(close, 20).iloc[-1], ema(close, 50).iloc[-1], ema(close, 200).iloc[-1]
    trend_pts = sum([price > e20, price > e50, price > e200, e20 > e50, e50 > e200]) * 6
    add("Trend structure", trend_pts, 30,
        f"Price {fmt(price)} | EMA20 {fmt(e20)} | EMA50 {fmt(e50)} | EMA200 {fmt(e200)}",
        "6 pts each: P>EMA20, P>EMA50, P>EMA200, EMA20>EMA50, EMA50>EMA200",
        "Moving averages smooth price into a trend line. Price above rising averages, with short averages above long ones, is the classic definition of an uptrend.")

    # Hull MA slope (10 pts)
    h = hma(close, 21)
    hma_rising = h.iloc[-1] > h.iloc[-2]
    add("Hull MA direction", 10 if hma_rising else 0, 10,
        f"HMA21 {fmt(h.iloc[-2])} → {fmt(h.iloc[-1])} ({'rising' if hma_rising else 'falling'})",
        "10 pts if HMA(21) today > HMA(21) yesterday",
        "The Hull Moving Average reacts faster than a normal average with less lag. Its slope is a quick read on short-term direction.")

    # RSI regime (15 pts)
    r = rsi(close).iloc[-1]
    if 50 <= r <= 70:
        rsi_pts, tag = 15, "healthy momentum"
    elif 40 <= r < 50 or 70 < r <= 78:
        rsi_pts, tag = 8, "neutral / stretched"
    else:
        rsi_pts, tag = 0, "weak or overheated"
    add("RSI(14) regime", rsi_pts, 15, f"RSI = {fmt(r, 1)} ({tag})",
        "15 pts: 50–70 · 8 pts: 40–50 or 70–78 · 0 pts otherwise",
        "RSI measures the speed of recent gains vs losses on a 0–100 scale. 50–70 is strength without overheating; above ~78 the move is often exhausted.")

    # MACD (15 pts)
    line, sig, hist = macd(close)
    macd_pts = (7 if line.iloc[-1] > sig.iloc[-1] else 0) + (8 if hist.iloc[-1] > hist.iloc[-2] else 0)
    add("MACD momentum", macd_pts, 15,
        f"MACD {fmt(line.iloc[-1])} vs signal {fmt(sig.iloc[-1])}; histogram {fmt(hist.iloc[-2])} → {fmt(hist.iloc[-1])}",
        "7 pts: MACD above signal · 8 pts: histogram expanding",
        "MACD compares a fast and slow average of price. Above its signal line with a growing gap means momentum is building, not fading.")

    # ADX trend strength (10 pts)
    a = adx(df).iloc[-1]
    adx_pts = 10 if a >= 25 else (5 if a >= 20 else 0)
    add("ADX trend strength", adx_pts, 10, f"ADX(14) = {fmt(a, 1)}",
        "10 pts: ADX ≥ 25 · 5 pts: 20–25 · 0 pts: < 20",
        "ADX measures how strongly price is trending (in either direction). Below 20 means choppy, directionless trade — signals are less reliable there.")

    # Supertrend (10 pts)
    st = supertrend(df).iloc[-1]
    add("Supertrend", 10 if st == 1 else 0, 10,
        "Price above Supertrend(10,3) — bullish" if st == 1 else "Price below Supertrend(10,3) — bearish",
        "10 pts if close is above the Supertrend(10, 3×ATR) band",
        "Supertrend draws a volatility-adjusted band under (or over) price. Which side price sits on is a simple trend-following regime filter.")

    # 52-week position (10 pts)
    lo52, hi52 = close.tail(252).min(), close.tail(252).max()
    pos = (price - lo52) / (hi52 - lo52) if hi52 > lo52 else 0.5
    pos_pts = 10 if pos >= 0.75 else (6 if pos >= 0.5 else (3 if pos >= 0.3 else 0))
    add("52-week range position", pos_pts, 10,
        f"At {fmt(pos * 100, 0)}% of 52w range ({fmt(lo52)} – {fmt(hi52)})",
        "10 pts: top quartile · 6: upper half · 3: 30–50% · 0: bottom 30%",
        "Stocks near 52-week highs statistically continue outperforming (momentum effect); stocks in the bottom of their range are fighting overhead supply.")

    score = round(100 * earned / possible)
    vol_pct = fmt(100 * atr(df).iloc[-1] / price, 1)
    return {"score": score, "checks": checks, "atr_pct": vol_pct, "price": fmt(price)}


# ---------------------------------------------------------------------------
# Fundamental scoring — Piotroski F-Score + quality overlays
# ---------------------------------------------------------------------------

def _get(frame: pd.DataFrame, keys, col=0):
    """Fetch first matching row label from a yfinance statement frame."""
    if frame is None or frame.empty or col >= frame.shape[1]:
        return None
    for k in keys:
        if k in frame.index:
            v = frame.loc[k].iloc[col]
            if v is not None and not (isinstance(v, float) and math.isnan(v)):
                return float(v)
    return None


def fundamental_score(fin: pd.DataFrame, bs: pd.DataFrame, cf: pd.DataFrame, info: dict) -> dict:
    checks = []
    earned, possible = 0, 0

    def add(name, points, max_pts, value, formula, explain):
        nonlocal earned, possible
        earned += points
        possible += max_pts
        checks.append({"name": name, "points": points, "max": max_pts,
                       "value": value, "formula": formula, "explain": explain})

    def cr(v, dec=2):  # crores/readable
        if v is None:
            return "n/a"
        return f"{v / 1e7:,.0f} Cr" if abs(v) >= 1e7 else f"{v:,.0f}"

    ni_now = _get(fin, ["Net Income", "Net Income Common Stockholders"], 0)
    ni_prev = _get(fin, ["Net Income", "Net Income Common Stockholders"], 1)
    ta_now = _get(bs, ["Total Assets"], 0)
    ta_prev = _get(bs, ["Total Assets"], 1)
    cfo = _get(cf, ["Operating Cash Flow", "Total Cash From Operating Activities"], 0)
    ltd_now = _get(bs, ["Long Term Debt", "Long Term Debt And Capital Lease Obligation"], 0)
    ltd_prev = _get(bs, ["Long Term Debt", "Long Term Debt And Capital Lease Obligation"], 1)
    ca_now = _get(bs, ["Current Assets", "Total Current Assets"], 0)
    cl_now = _get(bs, ["Current Liabilities", "Total Current Liabilities"], 0)
    ca_prev = _get(bs, ["Current Assets", "Total Current Assets"], 1)
    cl_prev = _get(bs, ["Current Liabilities", "Total Current Liabilities"], 1)
    rev_now = _get(fin, ["Total Revenue", "Operating Revenue"], 0)
    rev_prev = _get(fin, ["Total Revenue", "Operating Revenue"], 1)
    gp_now = _get(fin, ["Gross Profit"], 0)
    gp_prev = _get(fin, ["Gross Profit"], 1)
    shares_now = _get(bs, ["Ordinary Shares Number", "Share Issued"], 0)
    shares_prev = _get(bs, ["Ordinary Shares Number", "Share Issued"], 1)
    ebit = _get(fin, ["EBIT", "Operating Income"], 0)
    te_now = _get(bs, ["Stockholders Equity", "Total Stockholder Equity", "Common Stock Equity"], 0)

    # --- Piotroski F-Score (9 binary checks, 6 pts each = 54) -------------
    f_bits = []

    def fbit(label, cond, detail, why):
        pts = 6 if cond else 0
        f_bits.append(cond)
        add(f"F-Score · {label}", pts if cond is not None else 0, 6, detail,
            "6 pts if condition holds (1 Piotroski point)", why)

    roa_now = (ni_now / ta_now) if ni_now is not None and ta_now else None
    roa_prev = (ni_prev / ta_prev) if ni_prev is not None and ta_prev else None

    fbit("Positive ROA", bool(roa_now and roa_now > 0),
         f"ROA = NI {cr(ni_now)} / Assets {cr(ta_now)} = {fmt((roa_now or 0) * 100, 1)}%",
         "A company earning profit on its asset base clears the most basic quality bar.")
    fbit("Positive operating cash flow", bool(cfo and cfo > 0),
         f"CFO = {cr(cfo)}",
         "Cash from operations is harder to manipulate than accounting profit. Positive CFO means the business generates real cash.")
    fbit("ROA improving", bool(roa_now is not None and roa_prev is not None and roa_now > roa_prev),
         f"ROA {fmt((roa_prev or 0) * 100, 1)}% → {fmt((roa_now or 0) * 100, 1)}%",
         "Rising return on assets means the business is getting more productive, not just bigger.")
    fbit("CFO exceeds net income", bool(cfo is not None and ni_now is not None and cfo > ni_now),
         f"CFO {cr(cfo)} vs NI {cr(ni_now)}",
         "When cash flow beats reported profit, earnings quality is high — profits are backed by cash, not accruals.")
    fbit("Leverage falling", bool(ltd_now is not None and ltd_prev is not None and ta_now and ta_prev
                                  and (ltd_now / ta_now) <= (ltd_prev / ta_prev)),
         f"LTD/Assets {fmt((ltd_prev or 0) / ta_prev * 100, 1) if ta_prev else 'n/a'}% → {fmt((ltd_now or 0) / ta_now * 100, 1) if ta_now else 'n/a'}%",
         "Reducing long-term debt relative to assets lowers financial risk.")
    cur_now = (ca_now / cl_now) if ca_now and cl_now else None
    cur_prev = (ca_prev / cl_prev) if ca_prev and cl_prev else None
    fbit("Liquidity improving", bool(cur_now and cur_prev and cur_now > cur_prev),
         f"Current ratio {fmt(cur_prev)} → {fmt(cur_now)}",
         "A rising current ratio means more short-term assets per rupee of short-term liability — better ability to pay bills.")
    fbit("No dilution", bool(shares_now is not None and shares_prev is not None and shares_now <= shares_prev * 1.005),
         f"Shares {cr(shares_prev)} → {cr(shares_now)}",
         "If share count isn't rising, existing shareholders aren't being diluted to fund the business.")
    gm_now = (gp_now / rev_now) if gp_now and rev_now else None
    gm_prev = (gp_prev / rev_prev) if gp_prev and rev_prev else None
    fbit("Gross margin expanding", bool(gm_now and gm_prev and gm_now > gm_prev),
         f"Gross margin {fmt((gm_prev or 0) * 100, 1)}% → {fmt((gm_now or 0) * 100, 1)}%",
         "Expanding gross margin signals pricing power or falling input costs — both marks of a strengthening franchise.")
    at_now = (rev_now / ta_now) if rev_now and ta_now else None
    at_prev = (rev_prev / ta_prev) if rev_prev and ta_prev else None
    fbit("Asset turnover rising", bool(at_now and at_prev and at_now > at_prev),
         f"Revenue/Assets {fmt(at_prev)} → {fmt(at_now)}",
         "More revenue per rupee of assets means efficiency is improving.")

    f_score = sum(1 for b in f_bits if b)

    # --- Quality overlays (46 pts) ---------------------------------------
    roce = (ebit / (ta_now - (cl_now or 0))) if ebit and ta_now and ta_now > (cl_now or 0) else None
    roce_pts = 0 if roce is None else (16 if roce >= 0.18 else (10 if roce >= 0.12 else (5 if roce >= 0.08 else 0)))
    add("ROCE", roce_pts, 16,
        f"EBIT {cr(ebit)} / Capital employed {cr((ta_now - (cl_now or 0)) if ta_now else None)} = {fmt((roce or 0) * 100, 1)}%",
        "16 pts: ≥18% · 10: 12–18% · 5: 8–12% · 0: <8%",
        "Return on Capital Employed is the single best test of business quality: how much operating profit each rupee tied up in the business earns. Consistently high ROCE compounds wealth.")

    de = (ltd_now / te_now) if ltd_now is not None and te_now and te_now > 0 else (0.0 if te_now and te_now > 0 and not ltd_now else None)
    de_pts = 0 if de is None else (10 if de <= 0.3 else (6 if de <= 0.8 else (2 if de <= 1.5 else 0)))
    add("Debt / Equity", de_pts, 10,
        f"LTD {cr(ltd_now)} / Equity {cr(te_now)} = {fmt(de)}",
        "10 pts: ≤0.3 · 6: 0.3–0.8 · 2: 0.8–1.5 · 0: >1.5",
        "Low debt means the company survives bad years and doesn't hand its upside to lenders.")

    rev_g = ((rev_now / rev_prev) - 1) if rev_now and rev_prev else None
    g_pts = 0 if rev_g is None else (10 if rev_g >= 0.15 else (6 if rev_g >= 0.08 else (3 if rev_g > 0 else 0)))
    add("Revenue growth (YoY)", g_pts, 10,
        f"{cr(rev_prev)} → {cr(rev_now)} = {fmt((rev_g or 0) * 100, 1)}%",
        "10 pts: ≥15% · 6: 8–15% · 3: 0–8% · 0: negative",
        "Quality without growth stagnates. Double-digit revenue growth shows real demand for what the company sells.")

    pe = info.get("trailingPE")
    pe_pts = 0
    pe_detail = "P/E unavailable"
    if pe and pe > 0:
        pe_pts = 10 if pe <= 25 else (6 if pe <= 45 else (2 if pe <= 70 else 0))
        pe_detail = f"Trailing P/E = {fmt(pe, 1)}"
    add("Valuation (P/E)", pe_pts, 10, pe_detail,
        "10 pts: ≤25 · 6: 25–45 · 2: 45–70 · 0: >70 or loss-making",
        "Price matters. Even a great business bought at an extreme multiple can deliver poor returns for years. P/E is a rough but honest first check.")

    # If the core statement lines are all missing, data is unavailable —
    # report None rather than a misleading zero.
    has_data = any(v is not None for v in (ni_now, ta_now, rev_now, cfo, te_now))
    if not has_data:
        return {"score": None, "f_score": None, "checks": []}

    score = round(100 * earned / possible) if possible else None
    return {"score": score, "f_score": f_score, "checks": checks}


# ---------------------------------------------------------------------------
# Composite verdict
# ---------------------------------------------------------------------------

def composite(tech: dict, fund: dict) -> dict:
    t, f = tech["score"], fund.get("score")
    if f is None:
        overall = t
        basis = "Technical only — fundamental statements unavailable for this ticker"
    else:
        overall = round(0.5 * t + 0.5 * f)
        basis = "50% technical · 50% fundamental"

    if overall >= 72:
        label, tone = "STRONG PROFILE", "strong"
        summary = "Both the price action and the business quality clear high bars. Names like this belong on a serious watchlist — the remaining work is valuation comfort and position sizing."
    elif overall >= 55:
        label, tone = "CONSTRUCTIVE", "constructive"
        summary = "More going right than wrong, with specific weak spots identified in the ledger below. Worth studying — read the failed checks first; they tell you exactly what to monitor."
    elif overall >= 40:
        label, tone = "MIXED", "mixed"
        summary = "The evidence genuinely conflicts. When technicals and fundamentals disagree this much, the honest answer is that conviction isn't available yet — wait for the picture to resolve."
    else:
        label, tone = "WEAK PROFILE", "weak"
        summary = "The majority of objective checks fail. This doesn't predict the future — but buying against this much evidence requires a specific thesis about what the numbers are missing."

    return {"score": overall, "label": label, "tone": tone, "summary": summary, "basis": basis}
