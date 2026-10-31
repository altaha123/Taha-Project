"""
Altaha Screener — the Strategy lab

WHAT THIS IS
Eleven textbook trading rules, run on one stock's own past prices, measured
the way quants measure a strategy, and set beside the one rule everyone can
follow without a screen: buy it and hold it.

The idea, and the shape of the report, come from quants.md, an open library of
fifty strategies built on the QuantJourney backtester examples (Apache-2.0).
That library reports six numbers for every strategy (return, CAGR, Sharpe,
maximum drawdown, win rate, profit factor) on US ETFs, futures and FX. The
rules here are the long-only daily ones from that library that an Indian
investor can actually run in a cash account. The code is this project's own.

WHAT THIS ADDS THAT THE LIBRARY DOES NOT
  · Indian costs. 0.49% a round trip, the figure the Altaha Special backtest
    already uses: STT on both legs, stamp duty, exchange and SEBI charges,
    GST, DP charges and a little slippage.
  · Indian tax. A rule that trades often pays 20% short-term gains tax on
    every winning trade; holding for over a year pays 12.5% once. Pre-tax
    tables flatter active rules, so for NSE stocks the report also gives an
    after-tax CAGR (method and simplifications in `_after_tax`).
  · A luck bar. Try eleven rules and one of them will look good by chance.
    `_luck` estimates how much of the best rule's lead over holding that
    alone would explain (the expected maximum of N Sharpe ratios, Bailey and
    López de Prado's deflated Sharpe ratio, 2014), using the number of rules
    that are actually different, not the number listed.
  · Consistency. The test is cut in two halves, and every calendar year is
    set against holding, because one lucky stretch can carry a ten-year
    number.
  · A risk-free rate that is India's. Sharpe here is measured above 6% a
    year for rupee stocks (about the 91-day Treasury bill over the last
    decade), not quants.md's 2%. Cash in a trading account earns nothing in
    this model, so a rule that sits out pays for it in Sharpe, as it would.

HOW A RULE IS RUN, AND WHY IT CANNOT SEE THE FUTURE
A rule reads every bar up to and including today's close and decides what
share of the account it wants in the stock. That decision is filled at the
NEXT session's open. The overnight gap belongs to yesterday's position; the
session from open to close belongs to today's. `test_strategy_lab.py` changes
every price after a date and checks that no position up to that date moves.

Every rule, and holding, starts measuring on the same day: after a year of
warm-up, so the 200-day average and the twelve-month return exist. All of
them start in cash and pay their own way in.

WHAT THIS REFUSES TO DO
It does not say what any rule is doing today. A rule's current position is a
signal, and stock pages here show evidence, never buy or sell directives (see
README, "Scores and evidence everywhere; calls in one place"). The report is a
record of how fixed rules behaved in the past. Parameters are the textbook
ones and are never fitted to the stock: fitting them on the same prices they
are measured on is how a backtest becomes fiction.
"""

import datetime as dt
import math
import threading
import time
from statistics import NormalDist

import numpy as np
import pandas as pd

from engine import bollinger, macd, rsi, atr

TRADING_DAYS = 252

# A year of bars before anything is measured: the 200-day average needs 200,
# the twelve-month return needs 252, and a little slack keeps the first day of
# the test clear of the edge.
WARMUP = 260

# Below this many years after warm-up, no report. Two years of one regime
# says almost nothing about a rule, and a table of six confident numbers would
# say it anyway.
MIN_YEARS = 3.0

YEAR_CHOICES = (3, 5, 10, 15)
DEFAULT_YEARS = 10

# A round trip, in percent. The rupee figure is the one the Altaha Special
# backtest uses (special.py). The dollar figure is a US discount broker's: no
# commission, a few basis points of spread and slippage each way.
COST_ROUND_TRIP_PCT = {"INR": 0.49, "USD": 0.10}

# Annual, in percent. For India, roughly the average 91-day Treasury bill
# yield over 2015 to 2025; for the US, the 2% quants.md uses.
RISK_FREE_PCT = {"INR": 6.0, "USD": 2.0}

# The risk-sizing rules aim the position at this much annual volatility.
VOL_TARGET_PCT = 15.0
VOL_WINDOW = 63

# A weight is only changed when the new target is this far from the old one.
# Rebalancing a volatility-sized position every day to chase a 2% change in
# weight would spend more on costs than the sizing earns.
DRIFT_BAND = 0.10

# Fewer closed trades than this and the win rate and profit factor are shown
# with a warning. The same floor the pattern base rates use (patterns.py).
MIN_TRADES = 8

# India's capital gains rates from 23 July 2024, applied to the whole history.
STCG_PCT = 20.0
LTCG_PCT = 12.5

# A one-day move this large is almost never the market. It is usually a
# corporate action (demerger, bonus, rights) the feed did not adjust for.
SUSPECT_MOVE = 0.40

CURVE_POINTS = 260

DISCLAIMER = ("A historical simulation of fixed textbook rules on this stock's past "
              "prices. It is not a recommendation and not a forecast: past results do "
              "not predict future ones, and real costs, slippage and taxes differ.")

ATTRIBUTION = ("Rule ideas and the six headline measures follow quants.md, an open "
               "library of 50 strategies built on the QuantJourney backtester examples "
               "(Apache-2.0). The code is Altaha's own.")


# ---------------------------------------------------------------------------
# The rules
# ---------------------------------------------------------------------------
#
# Each returns the share of the account (0 to 1) the rule wants in the stock
# at today's close. Long only: an Indian cash account cannot hold a short
# overnight, so the long/short rules in the library are left out rather than
# shown on a basis nobody here can trade.

def _sma(s, n):
    return s.rolling(n, min_periods=n).mean()


def _flag(cond):
    return cond.fillna(False).astype(float)


def _state(enter, leave):
    """In from the first bar `enter` holds until the first bar `leave` holds."""
    e = enter.fillna(False).to_numpy(bool)
    x = leave.fillna(False).to_numpy(bool)
    out = np.zeros(len(e))
    on = False
    for i in range(len(e)):
        if on and x[i]:
            on = False
        elif not on and e[i]:
            on = True
        out[i] = 1.0 if on else 0.0
    return pd.Series(out, index=enter.index)


def _realised_vol(close, n=VOL_WINDOW):
    r = np.log(close / close.shift(1))
    return r.rolling(n, min_periods=n).std() * math.sqrt(TRADING_DAYS)


def _banded(target, band=DRIFT_BAND):
    """Follow `target`, but only move when it is more than `band` away.

    Going to zero, or coming in from zero, always happens: the band is there
    to stop small resizing trades, not to delay a rule stepping aside."""
    t = target.fillna(0.0).clip(0.0, 1.0).to_numpy(float)
    out = np.zeros(len(t))
    w = 0.0
    for i in range(len(t)):
        if t[i] == 0.0 or w == 0.0 or abs(t[i] - w) > band:
            w = t[i]
        out[i] = w
    return pd.Series(out, index=target.index)


def r_trend_50_200(df, rf):
    c = df["Close"]
    return _flag(_sma(c, 50) > _sma(c, 200))


def r_sma_20_50(df, rf):
    c = df["Close"]
    return _flag(_sma(c, 20) > _sma(c, 50))


def r_above_200(df, rf):
    c = df["Close"]
    return _flag(c > _sma(c, 200))


def r_macd_trend(df, rf):
    line, signal, _ = macd(df["Close"])
    return _flag(line > signal)


def r_momentum_12m(df, rf):
    c = df["Close"]
    return _flag(c / c.shift(TRADING_DAYS) - 1 > rf)


def r_rsi_reversion(df, rf):
    r = rsi(df["Close"], 14)
    return _state(r < 35, r > 60)


def r_bollinger_reversion(df, rf):
    c = df["Close"]
    mid, upper, lower, _, _ = bollinger(c, 20, 2.0)
    return _state(c < lower, c > mid)


def r_donchian(df, rf):
    c = df["Close"]
    hi = df["High"].rolling(20, min_periods=20).max().shift(1)
    lo = df["Low"].rolling(10, min_periods=10).min().shift(1)
    return _state(c > hi, c < lo)


def r_trailing_trend(df, rf):
    """A 50-day closing high above the 200-day average, held until the close
    falls three ATRs below the highest close since entry."""
    c = df["Close"]
    enter = ((c >= c.rolling(50, min_periods=50).max()) & (c > _sma(c, 200))).fillna(False).to_numpy(bool)
    a = atr(df, 14).to_numpy(float)
    cl = c.to_numpy(float)
    out = np.zeros(len(cl))
    on, peak = False, 0.0
    for i in range(len(cl)):
        if on:
            peak = max(peak, cl[i])
            if np.isfinite(a[i]) and cl[i] < peak - 3.0 * a[i]:
                on = False
        elif enter[i]:
            on, peak = True, cl[i]
        out[i] = 1.0 if on else 0.0
    return pd.Series(out, index=c.index)


def r_vol_target_trend(df, rf):
    c = df["Close"]
    vol = _realised_vol(c)
    size = (VOL_TARGET_PCT / 100.0 / vol).clip(upper=1.0)
    return _banded(size.where(c > _sma(c, 200), 0.0))


def r_vol_target_hold(df, rf):
    vol = _realised_vol(df["Close"])
    return _banded((VOL_TARGET_PCT / 100.0 / vol).clip(upper=1.0))


RULES = [
    {
        "id": "trend_50_200", "fn": r_trend_50_200,
        "name": "Golden cross trend", "family": "Trend",
        "rule": "In while the 50-day average is above the 200-day average; in cash otherwise.",
        "idea": "Big trends last longer than people expect. The slow cross keeps you in them "
                "and out of the long declines, at the price of arriving and leaving late.",
        "inspired_by": "W01 Daily SMA Trend",
    },
    {
        "id": "sma_20_50", "fn": r_sma_20_50,
        "name": "Fast average cross", "family": "Trend",
        "rule": "In while the 20-day average is above the 50-day average; in cash otherwise.",
        "idea": "The same trend idea on a shorter clock: quicker in and out, more trades, more "
                "false starts.",
        "inspired_by": "O01 Market SMA Cross",
    },
    {
        "id": "above_200", "fn": r_above_200,
        "name": "Above the 200-day", "family": "Trend",
        "rule": "In while the close is above its 200-day average; in cash otherwise.",
        "idea": "The simplest defensive filter there is. It gives up some of every rally to "
                "skip most of every crash.",
        "inspired_by": "W06 Signal Change Defensive",
    },
    {
        "id": "macd_trend", "fn": r_macd_trend,
        "name": "MACD trend", "family": "Trend",
        "rule": "In while the MACD line (12, 26) is above its 9-day signal line; in cash otherwise.",
        "idea": "Momentum of momentum. Reacts faster than average crosses, so it trades a lot "
                "and gets whipsawed in sideways markets.",
        "inspired_by": "W22 MACD Trend",
    },
    {
        "id": "momentum_12m", "fn": r_momentum_12m,
        "name": "Twelve-month momentum", "family": "Trend",
        "rule": "In while the stock's return over the last 12 months beats the risk-free rate; "
                "in cash otherwise.",
        "idea": "Absolute momentum: own it only while it has paid more than a Treasury bill "
                "over the past year. One of the best-documented effects in finance.",
        "inspired_by": "W04 Quarterly Dual Momentum",
    },
    {
        "id": "rsi_reversion", "fn": r_rsi_reversion,
        "name": "RSI dip", "family": "Mean reversion",
        "rule": "In when the 14-day RSI closes below 35; out when it closes above 60.",
        "idea": "Sharp short-term falls tend to partly reverse. Works in range-bound stocks and "
                "fails badly in ones that keep falling.",
        "inspired_by": "O02 Market RSI Reversion · W03 Weekly RSI Reversion",
    },
    {
        "id": "bollinger_reversion", "fn": r_bollinger_reversion,
        "name": "Bollinger dip", "family": "Mean reversion",
        "rule": "In when the close is below the lower Bollinger band (20 days, 2 deviations); out "
                "when it closes above the middle band.",
        "idea": "A close two standard deviations below its average is stretched. The rule bets "
                "on the stretch relaxing back to the average.",
        "inspired_by": "W21 Bollinger Reversion",
    },
    {
        "id": "donchian", "fn": r_donchian,
        "name": "20-day breakout", "family": "Breakout",
        "rule": "In when the close breaks above the highest high of the previous 20 sessions; out "
                "when it breaks below the lowest low of the previous 10.",
        "idea": "The channel breakout the Turtle traders made famous: join a move once it has "
                "proved itself, and leave quickly when it fails.",
        "inspired_by": "O05 Stop Breakout Entry · O20 Futures Donchian",
    },
    {
        "id": "trailing_trend", "fn": r_trailing_trend,
        "name": "Trend with a trailing exit", "family": "Breakout",
        "rule": "In on a 50-day closing high while above the 200-day average; out when the close "
                "falls three ATRs below the highest close since entry.",
        "idea": "Let winners run, cut the ride when it turns. The exit is measured in the stock's "
                "own volatility (ATR), so a calm stock and a wild one get the same treatment.",
        "inspired_by": "O09 Trailing Stop Trend",
    },
    {
        "id": "vol_target_trend", "fn": r_vol_target_trend,
        "name": "Volatility-sized trend", "family": "Risk sizing",
        "rule": "Above the 200-day average, hold enough to run at about 15% annual volatility "
                "(never more than the whole account); in cash below it.",
        "idea": "Two ideas stacked: the trend filter decides whether to be in, and volatility "
                "decides how much, so a stock in a storm is held smaller.",
        "inspired_by": "W17 Vol Target Trend",
    },
    {
        "id": "vol_target_hold", "fn": r_vol_target_hold,
        "name": "Volatility-sized holding", "family": "Risk sizing",
        "rule": "Always invested, sized to run at about 15% annual volatility (never more than the "
                "whole account); the rest sits in cash.",
        "idea": "No timing at all, just sizing. It shows what scaling down in turbulent stretches "
                "does on its own, separate from any view on direction.",
        "inspired_by": "W05 Monthly Inverse Vol",
    },
]

FAMILIES = ["Trend", "Mean reversion", "Breakout", "Risk sizing"]


# ---------------------------------------------------------------------------
# Running a rule
# ---------------------------------------------------------------------------

def simulate(df, weight, cost_side):
    """
    Daily net returns and the position held, for a target-weight series.

    `weight[t]` is decided at the close of bar t and is held from the open of
    bar t+1. So on bar t the position is weight[t-1]: it earns the overnight
    gap at the previous position, pays to rebalance at the open, then earns
    the session at the new one.
    """
    o = df["Open"].astype(float)
    c = df["Close"].astype(float)
    prev = c.shift(1)
    o = o.where((o > 0) & o.notna(), prev)   # a missing open is treated as no gap
    gap = (o / prev - 1).fillna(0.0)
    session = (c / o - 1).fillna(0.0)
    p = weight.shift(1).fillna(0.0)
    p_prev = p.shift(1).fillna(0.0)
    net = (1 + p_prev * gap) * (1 - (p - p_prev).abs() * cost_side) * (1 + p * session) - 1
    return net, p


def _sharpe(r, rf_daily):
    r = np.asarray(r, float)
    if len(r) < 20:
        return None
    sd = r.std(ddof=1)
    if not np.isfinite(sd) or sd <= 0:
        return None
    return float((r - rf_daily).mean() / sd * math.sqrt(TRADING_DAYS))


def _cagr(growth, years):
    if years <= 0 or growth <= 0:
        return None
    return growth ** (1.0 / years) - 1


def _max_dd(equity):
    e = np.concatenate([[1.0], np.asarray(equity, float)])
    return float((e / np.maximum.accumulate(e) - 1).min())


def _trades(net, pos, index):
    """
    Closed trades: each run of days with a position, closed on the first day
    the position is gone (the exit fills at that day's open, so that day's
    overnight gap and exit cost belong to the trade).

    Returns (closed, open_runs). A trade's P&L is the change in account value
    from the close before entry to the close of the exit day: cash earns
    nothing here, so every change in that window is the trade's.
    """
    p = np.asarray(pos, float)
    eq = np.cumprod(1 + np.asarray(net, float))
    eq_before = np.concatenate([[1.0], eq[:-1]])
    closed, open_runs = [], 0
    i, n = 0, len(p)
    while i < n:
        if p[i] > 0:
            a = i
            while i < n and p[i] > 0:
                i += 1
            if i >= n:
                open_runs += 1
                break
            b = i                         # the exit day
            start_val = eq_before[a]
            end_val = eq[b]
            closed.append({
                "entry": index[a], "exit": index[b],
                "sessions": b - a,
                "ret": end_val / start_val - 1,
                "pnl": end_val - start_val,
            })
        else:
            i += 1
    return closed, open_runs


def _trade_stats(closed):
    n = len(closed)
    if not n:
        return {"trades": 0, "win_rate_pct": None, "profit_factor": None,
                "profit_factor_note": None, "avg_win_pct": None, "avg_loss_pct": None,
                "avg_hold_sessions": None, "few_trades": True}
    wins = [t for t in closed if t["ret"] > 0]
    losses = [t for t in closed if t["ret"] <= 0]
    gross_win = sum(t["pnl"] for t in closed if t["pnl"] > 0)
    gross_loss = -sum(t["pnl"] for t in closed if t["pnl"] < 0)
    pf, note = None, None
    if gross_loss > 0:
        pf = round(gross_win / gross_loss, 2)
    elif gross_win > 0:
        note = "no losing trade"
    return {
        "trades": n,
        "win_rate_pct": round(100.0 * len(wins) / n, 1),
        "profit_factor": pf,
        "profit_factor_note": note,
        "avg_win_pct": round(100 * float(np.mean([t["ret"] for t in wins])), 2) if wins else None,
        "avg_loss_pct": round(100 * float(np.mean([t["ret"] for t in losses])), 2) if losses else None,
        "avg_hold_sessions": round(float(np.mean([t["sessions"] for t in closed])), 1),
        "few_trades": n < MIN_TRADES,
    }


def _fy(d):
    """The Indian financial year a date falls in, by its starting year."""
    return d.year if d.month >= 4 else d.year - 1


def _after_tax(net, pos, index, closed, cost_side, years):
    """
    CAGR after Indian capital gains tax, as if the account were closed on the
    last day.

    Every closed trade is taxed in the financial year it closes: short-term
    (held a year or less) at 20%, long-term at 12.5%. Within a year,
    short-term losses offset short-term gains first and then long-term gains;
    long-term losses offset only long-term gains, as the Income Tax Act
    allows. The tax is paid at 31 March out of the account. A position still
    open on the last day is closed then, paying its exit cost and its tax.

    Simplified, and said so on the page: today's rates for the whole history,
    no ₹1.25 lakh long-term exemption, no surcharge or cess, and no
    carry-forward of a year's net loss (which overstates tax after a losing
    year). Returns None if there is nothing to measure.
    """
    eq = np.cumprod(1 + np.asarray(net, float))
    if not len(eq):
        return None
    eq_before = np.concatenate([[1.0], eq[:-1]])
    p = np.asarray(pos, float)
    trades = list(closed)
    final = float(eq[-1])
    # Close whatever is open at the end.
    if p[-1] > 0:
        a = len(p) - 1
        while a > 0 and p[a - 1] > 0:
            a -= 1
        final = float(eq[-1]) * (1 - p[-1] * cost_side)
        trades.append({"entry": index[a], "exit": index[-1],
                       "pnl": final - eq_before[a]})

    by_year = {}
    for t in trades:
        out_day = pd.Timestamp(t["exit"])
        held = (out_day - pd.Timestamp(t["entry"])).days
        bucket = by_year.setdefault(_fy(out_day), [0.0, 0.0])   # [short-term, long-term]
        bucket[1 if held > 365 else 0] += t["pnl"]

    # Tax as a fraction of the account on the day it is paid. Because every
    # return here is multiplicative, paying tax scales the whole future path
    # by (1 - fraction), and the fraction is the same whether it is measured
    # on the pre-tax or the after-tax account.
    dates = pd.DatetimeIndex(index)
    if getattr(dates, "tz", None) is not None:
        dates = dates.tz_localize(None)
    keep = 1.0
    last_fy = _fy(dates[-1])
    for fy, (st, lt) in sorted(by_year.items()):
        if st < 0:
            lt += st
            st = 0.0
        tax = STCG_PCT / 100 * max(st, 0.0) + LTCG_PCT / 100 * max(lt, 0.0)
        if tax <= 0:
            continue
        if fy >= last_fy:
            value = final
        else:
            pay_day = pd.Timestamp(fy + 1, 3, 31)
            at = dates.searchsorted(pay_day, side="right") - 1
            value = float(eq[max(at, 0)])
        if value > 0:
            keep *= max(0.0, 1 - tax / value)
    c = _cagr(final * keep, years)
    return None if c is None else float(c)


def _yearly(net, index):
    s = pd.Series(np.asarray(net, float), index=pd.DatetimeIndex(index))
    out = {}
    for y, g in s.groupby(s.index.year):
        out[int(y)] = {"ret": float(np.prod(1 + g.to_numpy()) - 1), "days": len(g)}
    return out


def _curve(equity, picks):
    e = np.asarray(equity, float)
    return [round(float(e[i]), 4) for i in picks]


def _luck(rule_returns, years, rows, hold_sharpe):
    """
    How much of the best rule's lead could be luck.

    The expected maximum of N independent Sharpe ratios that are all really
    zero, each measured over T years, is roughly

        (1/sqrt(T)) * ((1 - g) * Z(1 - 1/N) + g * Z(1 - 1/(N e)))

    with Z the inverse normal and g Euler's constant (Bailey and López de
    Prado, "The Deflated Sharpe Ratio", 2014). Rules that are near-copies of
    each other are not separate tries, so N is the number of genuinely
    different rules, read off the eigenvalues of their return correlations
    (the participation ratio: (sum of eigenvalues)^2 / sum of squares).

    The lead it is set against is a Sharpe lead over holding, which is the
    comparison the page draws. It is an approximation, offered as one.
    """
    # A rule that never traded is not a try: its flat line would correlate
    # with nothing and be counted as one more independent rule.
    live = [np.asarray(r, float) for r in rule_returns if np.asarray(r, float).std() > 0]
    n = len(rule_returns)
    if not live:
        live = [np.zeros(2)]
    mat = np.vstack(live)
    with np.errstate(invalid="ignore", divide="ignore"):
        corr = np.atleast_2d(np.corrcoef(mat))
    corr = np.nan_to_num(corr, nan=0.0)
    np.fill_diagonal(corr, 1.0)
    eig = np.clip(np.linalg.eigvalsh(corr), 0, None)
    n_eff = float(eig.sum() ** 2 / (eig ** 2).sum()) if (eig ** 2).sum() > 0 else 1.0
    n_eff = max(1.0, min(float(n), n_eff))
    bar = 0.0
    if n_eff >= 1.5 and years > 0:
        z = NormalDist().inv_cdf
        g = 0.5772156649
        nn = max(n_eff, 2.0)
        bar = (1 / math.sqrt(years)) * ((1 - g) * z(1 - 1 / nn) + g * z(1 - 1 / (nn * math.e)))
    ranked = [r for r in rows if r["metrics"].get("sharpe") is not None]
    best = max(ranked, key=lambda r: r["metrics"]["sharpe"]) if ranked else None
    edge = None
    if best is not None and hold_sharpe is not None:
        edge = round(best["metrics"]["sharpe"] - hold_sharpe, 2)
    verdict = None
    if edge is not None:
        if edge <= 0:
            verdict = "no_lead"
        elif edge <= bar:
            verdict = "within_luck"
        else:
            verdict = "clears_luck"
    return {
        "rules_tried": n,
        "effective_rules": round(n_eff, 1),
        "years": round(years, 1),
        "luck_bar_sharpe": round(bar, 2),
        "best_id": best["id"] if best else None,
        "best_name": best["name"] if best else None,
        "best_sharpe_lead": edge,
        "verdict": verdict,
    }


def _metrics(net, pos, index, years, rf_daily, cost_side, currency):
    eq = np.cumprod(1 + np.asarray(net, float))
    growth = float(eq[-1]) if len(eq) else 1.0
    r = np.asarray(net, float)
    closed, open_runs = _trades(net, pos, index)
    cagr = _cagr(growth, years)
    dd = _max_dd(eq)
    vol = float(r.std(ddof=1) * math.sqrt(TRADING_DAYS)) if len(r) > 2 else None
    p = np.asarray(pos, float)
    turnover = float(np.abs(np.diff(np.concatenate([[0.0], p]))).sum())
    m = {
        "total_return_pct": round(100 * (growth - 1), 2),
        "cagr_pct": None if cagr is None else round(100 * cagr, 2),
        "sharpe": None if (s := _sharpe(r, rf_daily)) is None else round(s, 2),
        "max_drawdown_pct": round(100 * dd, 2),
        "volatility_pct": None if vol is None else round(100 * vol, 2),
        "calmar": round(cagr / abs(dd), 2) if (cagr is not None and dd < 0) else None,
        "exposure_pct": round(100 * float((p > 0).mean()), 1),
        "turnover_per_year": round(turnover / years, 1) if years > 0 else None,
    }
    m.update(_trade_stats(closed))
    if currency == "INR":
        at = _after_tax(net, pos, index, closed, cost_side, years)
        m["after_tax_cagr_pct"] = None if at is None else round(100 * at, 2)
    else:
        m["after_tax_cagr_pct"] = None
    return m


# ---------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------

def _clean(df):
    df = df.copy()
    if isinstance(df.index, pd.DatetimeIndex) and df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    df = df[~df.index.duplicated(keep="last")].sort_index()
    for col in ("Open", "High", "Low"):
        if col not in df.columns:
            df[col] = df["Close"]
    df = df[df["Close"].notna() & (df["Close"] > 0)]
    hi = df[["High", "Close"]].max(axis=1)
    lo = df[["Low", "Close"]].min(axis=1)
    df["High"] = hi.where(df["High"].notna() & (df["High"] > 0), df["Close"])
    df["Low"] = lo.where(df["Low"].notna() & (df["Low"] > 0), df["Close"])
    return df


def _warnings(df, start):
    out = []
    r = df["Close"].pct_change()
    r = r[r.index >= start]
    big = r[r.abs() > SUSPECT_MOVE]
    for d, v in big.head(3).items():
        out.append(f"A one-day move of {100 * v:+.0f}% on {d:%d %b %Y}. That is usually a "
                   "corporate action the price feed did not adjust (a demerger, bonus or "
                   "rights issue), not the market. Results around it are unreliable.")
    return out


# Yahoo's Indian index symbols. Nifty, Sensex and the sector indices are
# rupee series, and an index fund on them is taxed like any other equity fund.
INDIAN_INDEX_PREFIXES = ("^NSE", "^BSE", "^CNX", "^CRSL", "^INDIA")


def currency_of(symbol):
    s = (symbol or "").upper()
    if s.endswith(".NS") or s.endswith(".BO") or s.startswith(INDIAN_INDEX_PREFIXES):
        return "INR"
    return "USD"


def run(df, symbol, years=DEFAULT_YEARS, cost_round_trip_pct=None, ticker=None):
    """
    The full report for one stock. `df` is daily OHLCV, adjusted for splits
    and dividends, oldest first; anything longer than needed is trimmed.

    Raises ValueError with a reader-facing sentence when there is not enough
    history to say anything.
    """
    if years not in YEAR_CHOICES:
        years = DEFAULT_YEARS
    currency = currency_of(symbol)
    rt = COST_ROUND_TRIP_PCT[currency] if cost_round_trip_pct is None else float(cost_round_trip_pct)
    rt = max(0.0, min(3.0, rt))
    cost_side = rt / 100.0 / 2.0
    rf_pct = RISK_FREE_PCT[currency]
    rf = rf_pct / 100.0
    rf_daily = (1 + rf) ** (1 / TRADING_DAYS) - 1

    df = _clean(df)
    if len(df) < WARMUP + int(MIN_YEARS * TRADING_DAYS):
        have = max(0.0, (len(df) - WARMUP) / TRADING_DAYS)
        raise ValueError(f"Not enough price history. The lab needs a year of warm-up and at least "
                         f"{MIN_YEARS:.0f} years to test; this stock has about {have:.1f} usable years.")

    end = df.index[-1]
    want_start = end - pd.DateOffset(years=years)
    i0 = int(df.index.searchsorted(want_start))
    i0 = max(i0, WARMUP)
    df = df.iloc[i0 - WARMUP:]
    i0 = WARMUP
    idx = df.index
    start = idx[i0]
    span_years = (idx[-1] - start).days / 365.25
    short = span_years < years - 0.25

    picks = np.unique(np.linspace(0, len(df) - i0 - 1, min(CURVE_POINTS, len(df) - i0)).astype(int))
    eval_index = idx[i0:]

    def measure(weight):
        w = weight.copy()
        w.iloc[:i0 - 1] = 0.0                  # everyone starts in cash
        net, pos = simulate(df, w, cost_side)
        net, pos = net.iloc[i0:], pos.iloc[i0:]
        return net.to_numpy(float), pos.to_numpy(float)

    hold_w = pd.Series(1.0, index=idx)
    h_net, h_pos = measure(hold_w)
    hold_m = _metrics(h_net, h_pos, eval_index, span_years, rf_daily, cost_side, currency)
    h_eq = np.cumprod(1 + h_net)
    h_years = _yearly(h_net, eval_index)
    half = len(h_net) // 2

    def halves(net):
        a, b = net[:half], net[half:]
        ya = (eval_index[half - 1] - eval_index[0]).days / 365.25
        yb = (eval_index[-1] - eval_index[half]).days / 365.25
        return [
            {"from": str(eval_index[0].date()), "to": str(eval_index[half - 1].date()),
             "sharpe": None if (s := _sharpe(a, rf_daily)) is None else round(s, 2),
             "cagr_pct": None if (c := _cagr(float(np.prod(1 + a)), ya)) is None else round(100 * c, 2)},
            {"from": str(eval_index[half].date()), "to": str(eval_index[-1].date()),
             "sharpe": None if (s := _sharpe(b, rf_daily)) is None else round(s, 2),
             "cagr_pct": None if (c := _cagr(float(np.prod(1 + b)), yb)) is None else round(100 * c, 2)},
        ]

    hold = {
        "id": "hold", "name": "Buy and hold", "family": "Benchmark",
        "rule": "In from the first day of the test to the last. One entry, no exits.",
        "metrics": hold_m,
        "halves": halves(h_net),
        "years": [{"year": y, "ret_pct": round(100 * v["ret"], 2), "partial": v["days"] < 200}
                  for y, v in sorted(h_years.items())],
        "curve": _curve(h_eq, picks),
    }

    rows, rule_returns = [], []
    for spec in RULES:
        w = spec["fn"](df, rf).reindex(idx).fillna(0.0).clip(0.0, 1.0)
        net, pos = measure(w)
        m = _metrics(net, pos, eval_index, span_years, rf_daily, cost_side, currency)
        eq = np.cumprod(1 + net)
        yr = _yearly(net, eval_index)
        full = [y for y, v in yr.items() if v["days"] >= 200 and y in h_years]
        beat = sum(1 for y in full if yr[y]["ret"] > h_years[y]["ret"])
        hv = halves(net)
        with np.errstate(invalid="ignore", divide="ignore"):
            corr = np.corrcoef(net, h_net)[0, 1] if net.std() > 0 and h_net.std() > 0 else None
        rows.append({
            "id": spec["id"], "name": spec["name"], "family": spec["family"],
            "rule": spec["rule"], "idea": spec["idea"], "inspired_by": spec["inspired_by"],
            "metrics": m,
            "vs_hold": {
                "cagr_pts": None if (m["cagr_pct"] is None or hold_m["cagr_pct"] is None)
                else round(m["cagr_pct"] - hold_m["cagr_pct"], 2),
                "sharpe": None if (m["sharpe"] is None or hold_m["sharpe"] is None)
                else round(m["sharpe"] - hold_m["sharpe"], 2),
                "drawdown_pts": round(m["max_drawdown_pct"] - hold_m["max_drawdown_pct"], 2),
                "after_tax_cagr_pts": None if (m["after_tax_cagr_pct"] is None or hold_m["after_tax_cagr_pct"] is None)
                else round(m["after_tax_cagr_pct"] - hold_m["after_tax_cagr_pct"], 2),
                "years_beat": beat, "years_full": len(full),
                "correlation": None if corr is None or not np.isfinite(corr) else round(float(corr), 2),
            },
            "halves": hv,
            "consistent": all(h["sharpe"] is not None and h["sharpe"] > 0 for h in hv),
            "years": [{"year": y, "ret_pct": round(100 * v["ret"], 2), "partial": v["days"] < 200}
                      for y, v in sorted(yr.items())],
            "curve": _curve(eq, picks),
        })
        rule_returns.append(net)

    luck = _luck(rule_returns, span_years, rows, hold_m["sharpe"])

    def count(pred):
        return sum(1 for r in rows if pred(r))

    summary = {
        "of": len(rows),
        "beat_hold_cagr": count(lambda r: (r["vs_hold"]["cagr_pts"] or 0) > 0),
        "beat_hold_sharpe": count(lambda r: (r["vs_hold"]["sharpe"] or 0) > 0),
        "shallower_drawdown": count(lambda r: r["vs_hold"]["drawdown_pts"] > 0),
        "beat_hold_after_tax": count(lambda r: (r["vs_hold"]["after_tax_cagr_pts"] or 0) > 0)
        if currency == "INR" else None,
        "consistent": count(lambda r: r["consistent"]),
    }

    return {
        "ticker": ticker or symbol.replace(".NS", "").replace(".BO", ""),
        "symbol": symbol,
        "currency": currency,
        "start": str(start.date()),
        "end": str(idx[-1].date()),
        "years": round(span_years, 1),
        "years_asked": years,
        "short_history": short,
        "curve_dates": [str(eval_index[i].date()) for i in picks],
        "assumptions": {
            "cost_round_trip_pct": round(rt, 3),
            "risk_free_pct": rf_pct,
            "vol_target_pct": VOL_TARGET_PCT,
            "drift_band_pct": round(100 * DRIFT_BAND),
            "min_trades": MIN_TRADES,
            "execution": "Decided at the close, filled at the next session's open.",
            "cash": "Cash earns nothing. Money waiting in a trading account does not earn a Treasury bill's yield.",
            "long_only": True,
            "start": "Every rule, and holding, starts in cash on the same day after a one-year warm-up.",
            "tax": {
                "stcg_pct": STCG_PCT, "ltcg_pct": LTCG_PCT,
                "note": ("Today's rates (from 23 July 2024) for the whole history; gains taxed in the "
                         "financial year a trade closes; no ₹1.25 lakh exemption, surcharge, cess or "
                         "loss carry-forward; everything closed on the last day."),
            } if currency == "INR" else None,
        },
        "hold": hold,
        "strategies": rows,
        "families": FAMILIES,
        "luck": luck,
        "summary": summary,
        "warnings": _warnings(df, start),
        "disclaimer": DISCLAIMER,
        "attribution": ATTRIBUTION,
        "source": {"name": "quants.md", "url": "https://quants.md/"},
    }


# ---------------------------------------------------------------------------
# Fetching, with a small cache
# ---------------------------------------------------------------------------
#
# A long daily history is a few hundred kilobytes. Eight symbols' worth is a
# rounding error on a 512 MB instance; eighty would not be, hence the cap.

_HIST = {}
_REPORTS = {}
_LOCK = threading.Lock()
_GATE = threading.BoundedSemaphore(2)
HIST_TTL = 6 * 3600
MAX_HIST = 8
MAX_REPORTS = 24


def _bounded_put(store, key, value, cap):
    if len(store) >= cap:
        for old in sorted(store, key=lambda k: store[k][0])[: max(1, cap // 3)]:
            store.pop(old, None)
    store[key] = (time.time(), value)


def long_history(symbol, ticker_obj):
    """Daily history long enough for the longest test, cached for six hours."""
    with _LOCK:
        hit = _HIST.get(symbol)
        if hit and time.time() - hit[0] < HIST_TTL:
            return hit[1]
    period = "max"
    h = ticker_obj.history(period=period, auto_adjust=True)
    if h is None or not len(h):
        return None
    h = h.dropna(subset=["Close"])
    # Keep a little more than the longest test plus its warm-up.
    cut = h.index[-1] - pd.DateOffset(years=max(YEAR_CHOICES) + 2)
    h = h[h.index >= cut][["Open", "High", "Low", "Close"] + (["Volume"] if "Volume" in h.columns else [])]
    with _LOCK:
        _bounded_put(_HIST, symbol, h, MAX_HIST)
    return h


def report(symbol, ticker_obj, years=DEFAULT_YEARS, cost_round_trip_pct=None, ticker=None):
    """The cached report for a symbol, rebuilt when the price history is."""
    key = (symbol, years, None if cost_round_trip_pct is None else round(float(cost_round_trip_pct), 3))
    with _LOCK:
        hit = _REPORTS.get(key)
        if hit and time.time() - hit[0] < HIST_TTL:
            return hit[1]
    with _GATE:
        hist = long_history(symbol, ticker_obj)
        if hist is None:
            raise LookupError(symbol)
        out = run(hist, symbol, years=years, cost_round_trip_pct=cost_round_trip_pct, ticker=ticker)
    out["computed_at"] = dt.datetime.now(dt.timezone.utc).replace(microsecond=0, tzinfo=None).isoformat() + "Z"
    with _LOCK:
        _bounded_put(_REPORTS, key, out, MAX_REPORTS)
    return out
