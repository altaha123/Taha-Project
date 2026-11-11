"""
Altaha Screener — Steady leaders: the Ideas list, rebuilt on measurement

WHY THIS EXISTS
---------------
The Ideas list was losing. By November 2026 the tracker had closed 33 ideas:
30% made money, the average was -2.6%, and 62% hit their stop. Three causes,
each measured in research/ideas_study.py on NSE's own daily files for every
session from 2016 to 2026, delisted companies included:

  1. THE STOP. Every plan carried an 8% stop and a target at the nearest
     resistance, often closer than the stop. Replayed over ten years, the old
     list's stop was hit on 54% of its picks: 39% ended up, against 56% of the
     very same picks simply held. This was the largest single cause.
  2. THE ORDER. Rows were ordered by a score that leaned on "fell last week"
     and "unusual volume". Over ten years the first carried almost no
     information beyond a fortnight and the second none at all.
  3. THE POOL. Only the ~150 stocks on the whole exchange with the highest
     technical score reached the list, down to companies trading 50 lakh a
     day, and two rows in three then said WAIT.

WHAT IT DOES INSTEAD
--------------------
Four lists, one per holding period, because "what should I buy for a week"
and "what should I hold for a year" are different questions. All four are
built from the same five measurements, each a published, decades-old effect
that also held on our own data, turned into a percentile among every liquid
stock:

  · 12-month return, last month skipped, per unit of volatility
  · 6-month return, last month skipped, per unit of volatility
  · closeness to the 52-week high
  · how straight the climb was (R-squared of log price over 90 sessions)
  · calm: low volatility over the past year
  · dip: how far it fell over the last five sessions

  LEADER SCORE  = the average of the first four.

  This week    half leader score, half dip. A strong stock that just fell.
  This month   three parts leader score, one part dip.
  Momentum     the leader score. About three months.
  Long term    12-month return, 52-week high and straightness, equally: the
               leader score without its six-month part. About a year.

Gates, for every list: a typical day trades Rs 10 crore or more, the price is
Rs 20 or more, the stock is in an uptrend (price above its 200-day average,
50-day above 200-day) and it is not among the most volatile fifth of liquid
stocks.

A calmer long-term recipe, ranking on low volatility, was the first choice
and was dropped: it looked best until exchange-traded cash funds were found
in the data, and on company shares alone it trailed the index in 2017-2021.
What held in both halves of the decade was the leaders, held longer.

Each list's plan is the one the same test supports: hold for the period, and
leave on a close a set distance under the call price (7%, 12%, 15%, 30%).
There is no target. A target caps the few large winners that carry the
average, and it was the single most expensive rule tested.

WHAT IT IS NOT
--------------
A forecast. Between three and five picks in ten still lost money in the test,
the one-week edge is smaller than a careless trader's costs, and 2018 and 2022
were flat against the index. The numbers are in LISTS below, the page prints
them, and the tracker keeps the live record beside them.

Nothing here is fitted: the windows (12 months, 6 months, 90 sessions, 200
days) are the textbook ones, and each recipe was chosen on 2017-2021 and then
checked on 2022-2026, which it had not seen.
"""

import datetime as dt
import math

try:
    import numpy as np
except Exception:                                  # pragma: no cover
    np = None

MIN_TURNOVER_RS = float(10e7)      # Rs 10 crore: the median day over 60 sessions
MIN_PRICE = 20.0
MIN_SESSIONS = 253                 # twelve months of closes plus the base one
MAX_SPAN_DAYS = 395                # calendar days those 253 closes may cover
CALM_FLOOR = 0.20                  # calm percentile under which a name is out
# Nothing that moves less than this in a year is a company share. A liquid-fund
# ETF creeps up in a straight line at about 1% volatility, which every
# return-for-its-risk measure here would rank first on the exchange. The scan
# reads NSE's list of company shares, so one should never arrive; this is the
# guard for the day a symbol list carries one anyway.
MIN_VOLATILITY = 0.08
LIST_SIZE = 15

# The four lists. `mix` is the weight on each percentile; `calm_gate` says
# whether the most volatile fifth is removed (True) or merely ranked lower.
#
# `tested` is what each recipe did when replayed on NSE's daily bhavcopy from
# January 2017 to 2026: a list every five sessions, 15 picks, bought at the
# next session's open, held for the period, left early on a close under the
# exit line. Price returns, before costs and tax. research/ideas_study.py
# reproduces every figure and research/IDEAS-STUDY.md explains them.
LISTS = {
    "week": {
        "label": "This week", "setup": "Week pick", "setup_key": "pick_week",
        "hold_sessions": 5, "hold_days": 7, "hold_text": "about a week", "exit_pct": 7.0,
        "mix": {"leader": 0.5, "dip": 0.5}, "calm_gate": True,
        "idea": "Strong stocks that fell this week.",
    },
    "month": {
        "label": "This month", "setup": "Month pick", "setup_key": "pick_month",
        "hold_sessions": 21, "hold_days": 30, "hold_text": "about a month", "exit_pct": 12.0,
        "mix": {"leader": 0.75, "dip": 0.25}, "calm_gate": True,
        "idea": "Market leaders, with a tilt to the ones that just dipped.",
    },
    "momentum": {
        "label": "Momentum", "setup": "Momentum pick", "setup_key": "pick_momentum",
        "hold_sessions": 63, "hold_days": 91, "hold_text": "about 3 months", "exit_pct": 15.0,
        "mix": {"leader": 1.0}, "calm_gate": True,
        "idea": "The strongest steady uptrends on the exchange.",
    },
    "long": {
        "label": "Long term", "setup": "Long-term pick", "setup_key": "pick_long",
        "hold_sessions": 252, "hold_days": 365, "hold_text": "about a year", "exit_pct": 30.0,
        "mix": {"m12": 1 / 3, "high": 1 / 3, "trend": 1 / 3}, "calm_gate": True,
        "idea": "Steady year-long climbers near their highs.",
    },
}
ORDER = ("week", "month", "momentum", "long")
SETUP_KEYS = {v["setup_key"]: k for k, v in LISTS.items()}
# Older links and the old two-way switch still ask for these.
ALIASES = {"short": "momentum", "medium": "long", "trade": "week", "position": "momentum",
           "invest": "long"}

TESTED = {}     # filled from research/ideas-study.json by _load_tested()


def _load_tested():
    """
    The measured record of each list, read from the file the study wrote.

    Kept in a data file, not typed into this module, so the page can never
    print a number the study did not produce. A missing file leaves TESTED
    empty and the page says the record is unavailable.
    """
    import json
    import os
    here = os.path.dirname(os.path.abspath(__file__))
    for path in (os.path.join(here, "ideas_study.json"),
                 os.path.join(here, "..", "research", "ideas-study.json")):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue
        TESTED.clear()
        TESTED.update(data)
        return True
    return False


_load_tested()


def resolve(horizon):
    """A list key for any horizon name the site has ever used, or None."""
    h = str(horizon or "").strip().lower()
    h = ALIASES.get(h, h)
    return h if h in LISTS else None


def _finite(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def signals(df):
    """
    The raw inputs for one stock from its daily bars, or None.

    Reads only the frame it is given, so cutting the frame at a past date
    gives exactly what was knowable on that date. Needs 253 closes: a
    12-month return needs a price from 252 sessions ago.
    """
    if np is None or df is None:
        return None
    try:
        frame = df.dropna(subset=["Close"])
    except Exception:
        return None
    if len(frame) < MIN_SESSIONS:
        return None
    c = np.asarray(frame["Close"], dtype=float)
    if not np.all(np.isfinite(c[-MIN_SESSIONS:])) or np.any(c[-MIN_SESSIONS:] <= 0):
        return None
    # A year of closes has to be a year of calendar. A stock that was halted
    # or suspended for a month reaches 253 bars only by going back further,
    # and its "12-month return" is then something else. The study left out
    # anything that missed more than twenty of the last 260 sessions.
    try:
        span = (frame.index[-1] - frame.index[-MIN_SESSIONS]).days
        if span > MAX_SPAN_DAYS:
            return None
    except Exception:
        pass                                     # an undated frame cannot be checked
    price = float(c[-1])

    rets = np.diff(np.log(c[-MIN_SESSIONS:]))
    vol = float(rets.std(ddof=1) * math.sqrt(252))
    if not math.isfinite(vol) or vol <= 0:
        return None

    mom_12_1 = c[-22] / c[-253] - 1.0
    mom_6_1 = c[-22] / c[-127] - 1.0

    high = frame["High"] if "High" in frame.columns else frame["Close"]
    h = np.asarray(high, dtype=float)[-252:]
    h = h[np.isfinite(h)]
    top = float(h.max()) if len(h) else price
    near_high = price / top if top > 0 else None

    y = np.log(c[-90:])
    x = np.arange(len(y), dtype=float)
    r = None
    if y.var() > 0:
        r = float(((x - x.mean()) * (y - y.mean())).mean() / math.sqrt(x.var() * y.var()))
    trend = None if r is None else (r * r) * 100.0 * (1.0 if r > 0 else -1.0)

    sma50, sma200 = float(c[-50:].mean()), float(c[-200:].mean())

    turnover = None
    if "Volume" in frame.columns:
        v = np.asarray(frame["Volume"], dtype=float)[-60:]
        t = c[-60:] * np.where(np.isfinite(v), v, 0.0)
        if len(t) >= 40:
            turnover = float(np.median(t))

    return {
        "price": round(price, 2),
        "mom_12_1": float(mom_12_1), "mom_6_1": float(mom_6_1),
        "vol": vol,
        "va12": float(mom_12_1 / vol), "va6": float(mom_6_1 / vol),
        "near_high": near_high, "trend": trend,
        "sma50": round(sma50, 2), "sma200": round(sma200, 2),
        "uptrend": bool(price > sma200 and sma50 > sma200),
        "turnover": turnover,
        "ret_12m": float(c[-1] / c[-253] - 1.0),
        "ret_3m": float(c[-1] / c[-64] - 1.0),
        "ret_5d": float(c[-1] / c[-6] - 1.0),
    }


def _pct_ranks(values):
    """Average-rank percentiles in (0, 1], ties sharing a rank. None stays None."""
    idx = [i for i, v in enumerate(values) if _finite(v) is not None]
    out = [None] * len(values)
    if not idx:
        return out
    xs = np.asarray([float(values[i]) for i in idx])
    order = xs.argsort(kind="mergesort")
    ranks = np.empty(len(xs), dtype=float)
    i = 0
    while i < len(xs):
        j = i
        while j + 1 < len(xs) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        ranks[order[i:j + 1]] = (i + j) / 2.0 + 1.0
        i = j + 1
    for k, i in enumerate(idx):
        out[i] = float(ranks[k] / len(xs))
    return out


def in_universe(sig):
    """Liquid enough, priced high enough and with every signal measurable."""
    if not sig:
        return False
    if (_finite(sig.get("turnover")) or 0) < MIN_TURNOVER_RS:
        return False
    if (_finite(sig.get("price")) or 0) < MIN_PRICE:
        return False
    if (_finite(sig.get("vol")) or 0) < MIN_VOLATILITY:
        return False
    return all(_finite(sig.get(k)) is not None
               for k in ("va12", "va6", "near_high", "trend", "vol", "ret_5d"))


def _why(key, sig, calm):
    """The evidence in words a first-time reader can use. Facts, no advice."""
    out = []
    r5 = sig.get("ret_5d")
    if key in ("week", "month") and r5 is not None and r5 <= -0.01:
        out.append(f"Fell {abs(r5) * 100:.0f}% this week")
    r12 = sig.get("ret_12m")
    if r12 is not None:
        out.append(f"Up {r12 * 100:.0f}% in a year" if r12 >= 0 else f"Down {abs(r12) * 100:.0f}% in a year")
    nh = sig.get("near_high")
    if nh is not None:
        gap = (1 - nh) * 100
        out.append("At its 52-week high" if gap < 1 else f"{gap:.0f}% below its 52-week high")
    t = sig.get("trend")
    if t is not None and t >= 60:
        out.append("A steady climb")
    if calm is not None:
        calmer = int(calm * 10)
        if calmer >= 5:
            out.append(f"Calmer than {min(calmer, 9)} in 10 stocks")
    return out[:4]


def rank(candidates):
    """
    Score every candidate against the whole liquid universe, for all four lists.

    `candidates` is a list of dicts carrying `symbol` and `leader_sig` (the
    output of signals(), or None). Returns {SYMBOL: block}. A stock outside
    the universe gets no block: it was not compared, which is different from
    being compared and failing a gate.
    """
    if np is None:
        return {}
    pool = [(str(c.get("symbol") or "").upper(), c.get("leader_sig")) for c in candidates or []]
    pool = [(s, g) for s, g in pool if s and in_universe(g)]
    if len(pool) < 30:
        # Thirty names is too few for a percentile to mean anything. A short
        # test list or a scan that stopped early says so instead of ranking.
        return {}
    m12 = _pct_ranks([g["va12"] for _, g in pool])
    m6 = _pct_ranks([g["va6"] for _, g in pool])
    high = _pct_ranks([g["near_high"] for _, g in pool])
    trend = _pct_ranks([g["trend"] for _, g in pool])
    calm = _pct_ranks([-g["vol"] for _, g in pool])
    dip = _pct_ranks([-g["ret_5d"] for _, g in pool])

    blocks, exact = {}, {}
    for i, (sym, g) in enumerate(pool):
        part = {"m12": m12[i], "m6": m6[i], "high": high[i], "trend": trend[i],
                "calm": calm[i], "dip": dip[i]}
        part["leader"] = (m12[i] + m6[i] + high[i] + trend[i]) / 4.0
        is_calm = calm[i] >= CALM_FLOOR
        lists = {}
        for key, spec in LISTS.items():
            score = sum(part[k] * w for k, w in spec["mix"].items()) * 100.0
            why_not = None
            if not g["uptrend"]:
                why_not = "Not in an uptrend: price or its 50-day average is under the 200-day average."
            elif spec["calm_gate"] and not is_calm:
                why_not = "Among the most volatile fifth of liquid stocks."
            exact[(sym, key)] = score
            lists[key] = {"score": round(score, 1), "eligible": why_not is None,
                          "why_not": why_not, "rank": None,
                          "why": _why(key, g, calm[i])}
        blocks[sym] = {
            "universe": len(pool),
            "uptrend": bool(g["uptrend"]),
            "calm": bool(is_calm),
            "score": round(part["leader"] * 100.0, 1),
            "parts": {
                "momentum_12m": round(m12[i] * 100), "momentum_6m": round(m6[i] * 100),
                "near_high": round(high[i] * 100), "steady_trend": round(trend[i] * 100),
                "calm": round(calm[i] * 100), "dip": round(dip[i] * 100),
            },
            "facts": {
                "return_12m_pct": round(g["ret_12m"] * 100, 1),
                "return_3m_pct": round(g["ret_3m"] * 100, 1),
                "return_5d_pct": round(g["ret_5d"] * 100, 1),
                "below_high_pct": round((1 - g["near_high"]) * 100, 1),
                "trend_straightness": round(g["trend"], 0),
                "volatility_pct": round(g["vol"] * 100, 1),
                "turnover_cr": round(g["turnover"] / 1e7, 1),
                "sma50": g["sma50"], "sma200": g["sma200"],
            },
            "lists": lists,
        }
    for key in LISTS:
        # Ordered on the exact score. The printed one is rounded to a decimal,
        # and ranking on that would settle every near-tie alphabetically.
        ordered = sorted((s for s in blocks if blocks[s]["lists"][key]["eligible"]),
                         key=lambda s: (-exact[(s, key)], s))
        for n, sym in enumerate(ordered, 1):
            blocks[sym]["lists"][key]["rank"] = n
    return blocks


def best_rank(block):
    """The best standing a stock has on any list, or None if it is on none."""
    ranks = [v.get("rank") for v in ((block or {}).get("lists") or {}).values() if v.get("rank")]
    return min(ranks) if ranks else None


def plan(key, price, called_on=None):
    """
    The plan the test supports, and nothing more precise than that.

    `stop` is kept under that name because the tracker and the call log judge
    an idea against `plan.stop`; here it is the exit line, a set distance
    under the call price, read on a close. There is deliberately no target.
    """
    spec = LISTS.get(key)
    p = _finite(price)
    if spec is None or p is None or p <= 0:
        return None
    day = called_on or dt.date.today()
    if isinstance(day, dt.datetime):
        day = day.date()
    line = p * (1 - spec["exit_pct"] / 100.0)
    return {
        "style": "hold",
        "stance": "HOLD",
        "entry": round(p, 2),
        "stop": round(line, 2),
        "risk_pct": spec["exit_pct"],
        "rr": None,
        "t1": None,
        "hold_sessions": spec["hold_sessions"],
        "hold_text": spec["hold_text"],
        "review_on": (day + dt.timedelta(days=spec["hold_days"])).isoformat(),
        "note": (f"Hold {spec['hold_text']}. Leave if it closes below "
                 f"\u20b9{line:,.2f}, {spec['exit_pct']:.0f}% under this price."),
    }
