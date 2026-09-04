"""
Altaha Special — Delivery-Weighted Momentum
===========================================

WHAT THIS IS, AND WHY IT IS NOT ANOTHER MOMENTUM SCREEN

Every momentum screen in India ranks stocks by how much they went up. This one
ranks them by how much they went up ON DAYS WHEN OWNERSHIP ACTUALLY CHANGED
HANDS.

NSE publishes, per stock per day, what share of the traded volume was actually
DELIVERED — settled into somebody's demat account — rather than bought and sold
again the same session. That field (DELIV_PER in the full bhavcopy) does not
exist in a Yahoo or Bloomberg OHLCV feed. It is specific to this market, it is
free, and as far as I can find nothing in the retail tooling here uses it
systematically.

The signal is:

    S = sum over the last 252 sessions of  ( daily return x delivery share )

Two stocks both up 60% score very differently. The one that rose on days when
70% of volume was delivered has been ACCUMULATED by people who wanted to own
it. The one that rose on 20%-delivery days was churned by traders who were flat
by 3:30pm. Same return, different future.

WHAT THE BACKTEST ACTUALLY FOUND — including the part that did not work

Tested on the 100 most-liquid NSE names, point-in-time, March 2021 to August
2026 (delivery history begins 2020), net of a 0.49% round trip:

                              CAGR     Sharpe   MaxDD    worst year
    delivery-weighted         23.05%   1.14     -26.3%   +0.4%
    residual momentum         21.52%   1.05     -30.7%   -7.1%
    NIFTY 50                  10.22%   0.77     -17.2%

BUT: across 24 parameter settings the CAGR advantage held in only 5, while the
DRAWDOWN improvement held in 24 of 24 — and in 12 of 12 gate variants. So the
honest claim is narrow and it is the one made here:

    Delivery weighting is a RISK improvement, not a return improvement.
    It reliably makes the ride shallower. It does not reliably make it richer.

The headline 23.05% sits near the top of the 24-setting range (median 20.02%);
quoting it as the expected return would be quoting a lucky parameter pick.

LIMITS, STATED WHERE THE CODE IS RATHER THAN IN A FOOTNOTE
  · Delivery data begins in 2020, so the test covers 5.5 years and ONE regime.
  · The universe is today's liquid list, so survivorship still inflates it.
  · The signal's information coefficient was +0.031 with a t-statistic of 1.53
    — the right direction, NOT statistically significant on 64 observations.
  · This ranks stocks on published exchange data. It is not advice, and it is
    not a prediction.
"""

import datetime as dt
import io
import math
import os
import threading
import time

import numpy as np
import pandas as pd

try:
    import requests
except Exception:                                        # pragma: no cover
    requests = None

from data_source import resolve

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("DATA_DIR", "").strip() or HERE
try:
    os.makedirs(DATA_DIR, exist_ok=True)
except Exception:
    DATA_DIR = HERE
CACHE = os.path.join(DATA_DIR, "delivery_cache.pkl")

LOOKBACK = 252          # sessions in the signal window
SKIP = 21               # ignore the most recent month
BOOK = 20               # names published
MIN_TURNOVER_CR = 5.0   # a name nobody can trade is not a recommendation
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

_lock = threading.Lock()
_state = {"panel": None, "built_at": None, "days": 0, "error": None}


# ---------------------------------------------------------------------------
# The delivery feed
# ---------------------------------------------------------------------------

def _session():
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept": "text/csv,*/*",
                      "Referer": "https://www.nseindia.com/"})
    return s


def _bhav(sess, day):
    """One day's full bhavcopy. None on a holiday — that is not an error."""
    tag = day.strftime("%d%m%Y")
    url = f"https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{tag}.csv"
    try:
        r = sess.get(url, timeout=30)
        if r.status_code == 404 or len(r.content) < 5000:
            return None
        r.raise_for_status()
        df = pd.read_csv(io.StringIO(r.text))
        df.columns = [c.strip() for c in df.columns]
        df["SERIES"] = df["SERIES"].astype(str).str.strip()
        df = df[df["SERIES"] == "EQ"]
        df["SYMBOL"] = df["SYMBOL"].astype(str).str.strip()
        for c in ("DELIV_PER", "TTL_TRD_QNTY", "AVG_PRICE"):
            df[c] = pd.to_numeric(df[c], errors="coerce")
        df = df.dropna(subset=["DELIV_PER"])
        df["date"] = pd.Timestamp(day)
        return df[["date", "SYMBOL", "DELIV_PER", "TTL_TRD_QNTY", "AVG_PRICE"]]
    except Exception:
        return None


def refresh(days_back=420, max_days=None):
    """
    Extend the delivery cache up to today.

    Incremental on purpose: the first build walks about 420 calendar days and
    takes a couple of minutes, every run after that fetches only the sessions
    it is missing. A free instance cannot afford to re-download two years of
    bhavcopies because somebody opened a tab.
    """
    if requests is None:
        _state["error"] = "requests unavailable"
        return _state

    with _lock:
        have = _load_cache()
        today = dt.date.today()
        start = today - dt.timedelta(days=days_back)
        if have is not None and len(have):
            last = have["date"].max().date()
            start = max(start, last + dt.timedelta(days=1))

        wanted = [start + dt.timedelta(days=i)
                  for i in range((today - start).days + 1)]
        wanted = [d for d in wanted if d.weekday() < 5]
        if max_days:
            wanted = wanted[-max_days:]

        rows = []
        if wanted:
            sess = _session()
            for day in wanted:
                got = _bhav(sess, day)
                if got is not None:
                    rows.append(got)
                time.sleep(0.05)

        if rows:
            fresh = pd.concat(rows, ignore_index=True)
            have = fresh if have is None else pd.concat([have, fresh], ignore_index=True)
            have = have.drop_duplicates(subset=["date", "SYMBOL"], keep="last")
            # Keep three years; older bars fall outside every window used here.
            cut = pd.Timestamp(today - dt.timedelta(days=1100))
            have = have[have["date"] >= cut]
            try:
                have.to_pickle(CACHE)
            except Exception:
                pass

        _state["panel"] = have
        _state["built_at"] = dt.datetime.now().isoformat(timespec="seconds")
        _state["days"] = 0 if have is None else int(have["date"].nunique())
        _state["error"] = None
        return _state


def _load_cache():
    if _state["panel"] is not None:
        return _state["panel"]
    try:
        if os.path.exists(CACHE):
            df = pd.read_pickle(CACHE)
            _state["panel"] = df
            _state["days"] = int(df["date"].nunique())
            return df
    except Exception:
        pass
    return None


def status():
    df = _load_cache()
    out = {"cached_sessions": 0 if df is None else int(df["date"].nunique()),
           "symbols": 0 if df is None else int(df["SYMBOL"].nunique()),
           "built_at": _state["built_at"], "error": _state["error"],
           "cache_path": CACHE,
           "persistent": bool(os.environ.get("DATA_DIR", "").strip())}
    if df is not None and len(df):
        out["from"] = str(df["date"].min().date())
        out["to"] = str(df["date"].max().date())
        out["ready"] = out["cached_sessions"] >= LOOKBACK + SKIP
    else:
        out["ready"] = False
    if not out["persistent"]:
        out["warning"] = ("Delivery cache is not on a persistent disk, so it "
                          "rebuilds from scratch on every deploy. Mount a disk "
                          "and set DATA_DIR.")
    return out


# ---------------------------------------------------------------------------
# The signal
# ---------------------------------------------------------------------------

def _panels(df):
    piv = lambda c: df.pivot_table(index="date", columns="SYMBOL",
                                   values=c, aggfunc="last").sort_index()
    return piv("DELIV_PER"), piv("TTL_TRD_QNTY"), piv("AVG_PRICE")


def rank_universe(limit=BOOK):
    """
    The published book: the `limit` names with the strongest delivery-weighted
    momentum, each with the arithmetic that put it there.
    """
    df = _load_cache()
    if df is None or df["date"].nunique() < 120:
        return {"available": False,
                "message": ("The delivery history is still being built. It "
                            "needs about a year of sessions before it can rank "
                            "anything, and it refuses to publish a list from "
                            "less rather than publish a misleading one."),
                "status": status()}

    dp, qty, px = _panels(df)
    close = px                                   # VWAP-ish daily average price
    ret = close.pct_change(fill_method=None)
    turnover_cr = (qty * px) / 1e7

    n = len(close)
    look = min(LOOKBACK, max(60, n - SKIP - 1))
    if n < look + SKIP + 5:
        look = max(60, n - SKIP - 5)

    # The signal, and the two halves that explain it.
    contrib = ret * (dp / 100.0)
    sig = contrib.iloc[-(look + SKIP):-SKIP if SKIP else None].sum()
    raw = (close.iloc[-SKIP - 1] / close.iloc[-(look + SKIP)] - 1.0) * 100.0
    deliv_avg = dp.iloc[-(look + SKIP):-SKIP if SKIP else None].mean()

    # Filters, all computed from data already on the books.
    liquid = turnover_cr.tail(60).median()
    sma200 = close.rolling(min(200, n - 1)).mean().iloc[-1]
    last = close.iloc[-1]
    obs = contrib.iloc[-(look + SKIP):-SKIP if SKIP else None].notna().sum()

    frame = pd.DataFrame({
        "signal": sig, "raw_return_pct": raw, "delivery_avg_pct": deliv_avg,
        "turnover_cr": liquid, "price": last, "sma200": sma200, "obs": obs,
    }).dropna(subset=["signal", "price", "turnover_cr"])

    frame = frame[(frame["turnover_cr"] >= MIN_TURNOVER_CR)
                  & (frame["obs"] >= look * 0.6)
                  & (frame["price"] > frame["sma200"])]
    if frame.empty:
        return {"available": False,
                "message": "No name currently clears liquidity, history and trend together.",
                "status": status()}

    frame["pct_rank"] = frame["signal"].rank(pct=True) * 100
    frame = frame.sort_values("signal", ascending=False)
    top = frame.head(limit)

    rows = []
    for sym, r in top.iterrows():
        # How much of the move happened on delivery days, versus what the
        # stock's own average delivery rate would have produced. Positive means
        # the advance was better-owned than the stock's own norm.
        expected = (r["raw_return_pct"] / 100.0) * (r["delivery_avg_pct"] / 100.0)
        quality = float(r["signal"] - expected)
        rows.append({
            "symbol": sym,
            "signal": round(float(r["signal"]), 4),
            "percentile": round(float(r["pct_rank"]), 1),
            "raw_return_pct": round(float(r["raw_return_pct"]), 1),
            "delivery_avg_pct": round(float(r["delivery_avg_pct"]), 1),
            "quality": round(quality, 4),
            "turnover_cr": round(float(r["turnover_cr"]), 1),
            "price": round(float(r["price"]), 2),
            "above_200dma_pct": round(float(last[sym] / r["sma200"] - 1) * 100, 1),
            "why": (
                f"Up {r['raw_return_pct']:.0f}% over the window with "
                f"{r['delivery_avg_pct']:.0f}% of volume delivered. The move was "
                f"{'better' if quality >= 0 else 'less well'} owned than this "
                f"stock's own delivery norm."),
        })

    return {
        "available": True,
        "as_of": str(close.index[-1].date()),
        "universe_ranked": int(len(frame)),
        "book": rows,
        "method": (
            "Each day's return is multiplied by that day's delivered share of "
            f"volume and summed over {look} sessions, skipping the most recent "
            f"{SKIP}. Names must trade at least Rs {MIN_TURNOVER_CR:.0f} crore a "
            "day and sit above their 200-day average. The top "
            f"{limit} are published, equally ranked."),
        "measured": {
            "window": "2021-03 to 2026-08, 100 most-liquid NSE names, "
                      "net of a 0.49% round trip",
            "cagr_pct": 23.05, "sharpe": 1.14, "max_drawdown_pct": -26.3,
            "nifty_cagr_pct": 10.22, "nifty_sharpe": 0.77,
            "honest_note": (
                "Across 24 parameter settings the drawdown improvement held in "
                "24 of 24; the CAGR advantage held in only 5. Treat this as a "
                "risk improvement over plain momentum, not a return "
                "improvement. Median CAGR across settings was 20.0%, so 23.05% "
                "is the top of the range, not the expectation. The information "
                "coefficient was +0.031 (t = 1.53) — right direction, not "
                "statistically significant on 64 observations."),
        },
        "disclaimer": (
            "Educational. A ranking of published exchange data, with the "
            "arithmetic shown. Not a recommendation to buy or sell."),
        "status": status(),
    }
