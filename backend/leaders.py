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
     list's stop was hit on 57% of its picks: 38% ended up, against 54% of the
     very same picks simply held. This was the largest single cause.
  2. THE ORDER. Rows were ordered by a score that leaned on "fell last week"
     and "unusual volume". Over ten years the first carried almost no
     information beyond a fortnight and the second none at all.
  3. THE POOL. Only the ~150 stocks on the whole exchange with the highest
     technical score reached the list, down to companies trading 50 lakh a
     day, and two rows in three then said WAIT.

WHAT IT DOES INSTEAD
--------------------
Five lists. Four are one per holding period, because "what should I buy for
a week" and "what should I hold for a year" are different questions. Those
four are built from the same measurements, each a published, decades-old effect
that also held on our own data, turned into a percentile among every liquid
stock:

  · 12-month return, last month skipped, per unit of volatility
  · 6-month return, last month skipped, per unit of volatility
  · closeness to the 52-week high
  · how straight the climb was (R-squared of log price over 90 sessions)
  · calm: low volatility over the past year
  · dip: how far it fell over the last five sessions
  · month dip: how far it fell over the last twenty-one sessions

  LEADER SCORE  = the average of the first four.

  This week    half leader score, half dip. A strong stock that just fell.
  This month   a leader (leader score in the top 30%) that fell over the
               last month: half month dip, half closeness to the 52-week high.
  Momentum     the leader score, leaving out the long-term top 15. About
               three months.
  Long term    12-month return, 52-week high and straightness, equally: the
               leader score without its six-month part. About a year.

ONE STOCK, ONE LIST (November 2026)
The first version of the four lists shared most of their names: on 484 past
dates momentum and long term had 12 of their 15 stocks in common, and this
week and this month 10. Readers saw the same stocks under four tabs. Two
changes, both measured (research/IDEAS-STUDY.md, "One stock, one list"):

  · This month became the month-dip recipe above. It shares about 4 names
    with this week instead of 10, and it tested better on 2017-2021 than the
    old month recipe did once that one was made to give way to this week.
  · Momentum gives way to long term: a stock in the top 15 of the long-term
    ranking is left off momentum, which takes its next names instead. Long
    term is untouched. Momentum's average fell (+6.4% to +5.5% a pick) and its
    lead over the average stock became steadier (t 2.4 to 3.3).

Across all four lists that is about 46 different stocks in 60 places, where
it was 31, and no two lists share more than about four.

Gates, for the four price lists: a typical day trades Rs 10 crore or more,
the price is Rs 20 or more, the stock is in an uptrend (price above its
200-day average, 50-day above 200-day) and it is not among the most volatile
fifth of liquid stocks.

AFTER RESULTS, THE FIFTH LIST (November 2026)
Not a price recipe: it is made from a filing. Every liquid company whose
quarterly results were first priced in the last ten sessions is ordered by how
its stock moved that session, less the average liquid stock's move. The
session is the first whose close came after the filing reached the exchange,
so a result filed in the evening is read against the next day. Held about a
month, left on a close 12% under. It has the liquidity and price gates and no
others, because that is how it was tested, and it is empty between results
seasons: with fewer than eight such companies there is no list.

Replayed on 47,115 filings from 2018 to 2026 it led the other companies that
had just reported in both halves (research/IDEAS-STUDY.md, "After results").
The reported growth itself carried nothing for a month: by that session's
close the price had read it.

COMPANIES LISTED UNDER A YEAR (November 2026)
A company with six to twelve months of prices has no 12-month return, so its
6-month one stands in. It is placed against the established universe (its
percentile on each measure is the share of established stocks at or below its
figure) so that letting it in changes no established stock's score. Such
companies are on the week and momentum lists, where their picks led the
average stock in both halves of the test, and on no other, where they did not.
Under six months nothing ranks them.

WHAT DID NOT EARN A PLACE
Asked for, tested, and shown beside a pick as facts that move no rank:
breakouts (nine recipes, none led the average stock in both halves), RSI,
MACD, ADX, the 20-day average and three volume measures (one of twenty-one
trials raised a list in both halves, by 0.05 of a point), and holding a list
back in a weak market (picks made under a falling index did better, not
worse). technicals() computes them; research/signals_lab.py is every trial.

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
A forecast. Between four and five picks in ten still lost money in the test,
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
# A company listed six to twelve months. It has no 12-month return, so its
# 6-month one stands in, and it is admitted to the two lists on which such
# companies led the average stock in both halves of the test (this week and
# momentum; research/IDEAS-STUDY.md, "Younger companies"). Under six months
# there is no 6-month return either, and nothing here ranks it.
MIN_YOUNG_SESSIONS = 127           # six months of closes plus the base one
MAX_YOUNG_SPAN_DAYS = 215          # calendar days those 127 closes may cover
YOUNG_LISTS = ("week", "momentum")
CALM_FLOOR = 0.20                  # calm percentile under which a name is out
LEADER_FLOOR = 0.70                # leader percentile a month pick must reach
# Nothing that moves less than this in a year is a company share. A liquid-fund
# ETF creeps up in a straight line at about 1% volatility, which every
# return-for-its-risk measure here would rank first on the exchange. The scan
# reads NSE's list of company shares, so one should never arrive; this is the
# guard for the day a symbol list carries one anyway.
MIN_VOLATILITY = 0.08
LIST_SIZE = 15
# The results list: how many sessions back a company's results may have
# reached the exchange, and how many such companies there must be before
# ranking them means anything. Both are the study's.
RESULTS_WINDOW = 10
RESULTS_MIN_POOL = 8
# A filing that reaches the exchange after this time of day is first priced
# by the NEXT session's close.
MARKET_CLOSE_MIN = 15 * 60 + 30
DAYS_KEPT = 12                     # recent daily moves each stock carries for that
# Stamped on every block rank() writes. A scan made under an earlier recipe
# still serves its lists after a deploy, but the page must not print this
# recipe's tested record beside them. Change it whenever LISTS changes.
RECIPE = "2026-11 short-term list"

# The four lists. `mix` is the weight on each percentile; `calm_gate` says
# whether the most volatile fifth is removed (True) or merely ranked lower.
# `leader_floor`, where set, is the leader percentile a stock must reach to be
# on the list at all. `gives_way_to` names a list whose top LIST_SIZE this
# list leaves out, so the two never show the same stock.
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
        "mix": {"dip21": 0.5, "high": 0.5}, "calm_gate": True, "leader_floor": LEADER_FLOOR,
        "idea": "Market leaders that pulled back over the last month.",
    },
    "results": {
        "label": "After results", "setup": "Results pick", "setup_key": "pick_results",
        "hold_sessions": 21, "hold_days": 30, "hold_text": "about a month", "exit_pct": 12.0,
        "mix": {"reaction": 1.0}, "calm_gate": False, "trend_gate": False, "event": "results",
        "idea": "Companies whose stock jumped on their quarterly results.",
    },
    "momentum": {
        "label": "Momentum", "setup": "Momentum pick", "setup_key": "pick_momentum",
        "hold_sessions": 63, "hold_days": 91, "hold_text": "about 3 months", "exit_pct": 15.0,
        "mix": {"leader": 1.0}, "calm_gate": True, "gives_way_to": "long",
        "idea": "Strong steady uptrends, other than the long-term picks.",
    },
    "long": {
        "label": "Long term", "setup": "Long-term pick", "setup_key": "pick_long",
        "hold_sessions": 252, "hold_days": 365, "hold_text": "about a year", "exit_pct": 30.0,
        "mix": {"m12": 1 / 3, "high": 1 / 3, "trend": 1 / 3}, "calm_gate": True,
        "idea": "Steady year-long climbers near their highs.",
    },
}
# The four setup lists. Each was asked for by name and is built as a list of
# its own; research/setups_lab.py chose which version of each, and its record
# is printed beside it whatever it is. They are ranked on what the setup
# itself measures, not on the price recipes above.
LISTS.update({
    "breakout": {
        "label": "Breakouts", "setup": "Breakout", "setup_key": "pick_breakout", "kind": "setup",
        "hold_sessions": 21, "hold_days": 30, "hold_text": "about a month", "exit_pct": 8.0,
        "mix": {"breakout": 1.0}, "calm_gate": False, "trend_gate": False,
        "idea": "Forty sessions in a tight range, then a close above it on twice the usual volume.",
    },
    "technical": {
        "label": "Technicals", "setup": "Technical pick", "setup_key": "pick_technical", "kind": "setup",
        "hold_sessions": 21, "hold_days": 30, "hold_text": "about a month", "exit_pct": 10.0,
        "mix": {"technical": 1.0}, "calm_gate": False, "trend_gate": False,
        "idea": "Stocks meeting seven or more of nine chart conditions: the averages, RSI, MACD, ADX and volume.",
    },
    "quick": {
        "label": "Quick trades", "setup": "Quick trade", "setup_key": "pick_quick", "kind": "setup",
        "hold_sessions": 7, "hold_days": 10, "hold_text": "a few days", "exit_pct": 7.0,
        "sell_rule": "sma5",
        "mix": {"quick": 1.0}, "calm_gate": False, "trend_gate": True,
        "idea": "Market leaders sold off hard for a day or two.",
    },
    "flow": {
        "label": "Money flow", "setup": "Money-flow pick", "setup_key": "pick_flow", "kind": "setup",
        "hold_sessions": 21, "hold_days": 30, "hold_text": "about a month", "exit_pct": 10.0,
        "mix": {"flow": 1.0}, "calm_gate": True, "trend_gate": True,
        "idea": "The strongest stocks in the four sectors money is moving into.",
    },
    # The short-term list: the one the Ideas page leads with. A breakout from a
    # consolidation, screened on the chart, the industry, the last quarter and
    # the market's reading of the latest results. research/short_term_lab.py
    # tried sixty versions; this is the full combination that was asked for,
    # and it tested the same as the best of them.
    "short": {
        "label": "Short term", "setup": "Short-term pick", "setup_key": "pick_short", "kind": "setup",
        "hold_sessions": 21, "hold_days": 30, "hold_text": "about a month", "exit_pct": 8.0,
        "mix": {"short": 1.0}, "calm_gate": False, "trend_gate": False,
        "idea": "Stocks breaking out of a consolidation, in industries money is moving into.",
    },
    "emerging": {
        "label": "Emerging", "setup": "Emerging company", "setup_key": "pick_emerging", "kind": "setup",
        "hold_sessions": 21, "hold_days": 30, "hold_text": "about a month", "exit_pct": 10.0,
        "mix": {"emerging": 1.0}, "calm_gate": False, "trend_gate": False,
        "idea": "Companies listed six to twelve months that already stand among the market's leaders.",
    },
})
ORDER = ("week", "month", "results", "momentum", "long")
SETUPS = ("short", "breakout", "technical", "quick", "flow", "emerging")
# The two the Ideas page shows. The rest are still ranked and still answer by name.
PRIMARY = ("short", "long")
ALL = ORDER + SETUPS
SETUP_KEYS = {v["setup_key"]: k for k, v in LISTS.items()}
# Older links and the old two-way switch still ask for these.
ALIASES = {"medium": "long", "trade": "week", "position": "momentum",
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
    gives exactly what was knowable on that date. A full set needs 253
    closes: a 12-month return needs a price from 252 sessions ago. A company
    with 127 to 252 closes is "young": its 6-month return stands in for the
    12-month one, and its volatility, 52-week high and 200-day average are
    taken over the history it has.
    """
    if np is None or df is None:
        return None
    try:
        frame = df.dropna(subset=["Close"])
    except Exception:
        return None
    n = len(frame)
    if n < MIN_YOUNG_SESSIONS:
        return None
    young = n < MIN_SESSIONS
    w = n if young else MIN_SESSIONS          # the closes the measures may read
    c = np.asarray(frame["Close"], dtype=float)
    if not np.all(np.isfinite(c[-w:])) or np.any(c[-w:] <= 0):
        return None
    # A year of closes has to be a year of calendar. A stock that was halted
    # or suspended for a month reaches 253 bars only by going back further,
    # and its "12-month return" is then something else. The study left out
    # anything that missed more than twenty of the last 260 sessions.
    try:
        back, limit = (MIN_YOUNG_SESSIONS, MAX_YOUNG_SPAN_DAYS) if young else (MIN_SESSIONS, MAX_SPAN_DAYS)
        if (frame.index[-1] - frame.index[-back]).days > limit:
            return None
    except Exception:
        pass                                     # an undated frame cannot be checked
    price = float(c[-1])

    rets = np.diff(np.log(c[-w:]))
    vol = float(rets.std(ddof=1) * math.sqrt(252))
    if not math.isfinite(vol) or vol <= 0:
        return None

    mom_6_1 = c[-22] / c[-127] - 1.0
    mom_12_1 = mom_6_1 if young else c[-22] / c[-253] - 1.0

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
        "young": young, "sessions": int(n),
        "mom_12_1": float(mom_12_1), "mom_6_1": float(mom_6_1),
        "vol": vol,
        "va12": float(mom_12_1 / vol), "va6": float(mom_6_1 / vol),
        "near_high": near_high, "trend": trend,
        "sma50": round(sma50, 2), "sma200": round(sma200, 2),
        "uptrend": bool(price > sma200 and sma50 > sma200),
        "turnover": turnover,
        "ret_12m": None if young else float(c[-1] / c[-253] - 1.0),
        "ret_6m": float(c[-1] / c[-127] - 1.0),
        "ret_3m": float(c[-1] / c[-64] - 1.0),
        "ret_1m": float(c[-1] / c[-22] - 1.0),
        "ret_5d": float(c[-1] / c[-6] - 1.0),
        "tech": _safe_technicals(frame),
        "days": _recent_days(frame, c),
    }


# The four setup lists (research/setups_lab.py chose each version).
BOX_SESSIONS = 40          # how long the base is
BOX_MAX_WIDTH = 0.18       # high over low of the base, less one
BOX_MIN_VOLUME = 2.0       # the breakout session's volume against its usual
BOX_LOOKBACK = 5           # how many sessions back a breakout is still listed
BOX_LEADER_FLOOR = 0.50
QUICK_RSI2 = 10.0          # the two-day RSI under which a leader counts as sold off
QUICK_LEADER_FLOOR = 0.70
SCORECARD_MIN = 7          # of nine technical conditions
SCORECARD_LABELS = (
    "Above its 20-day average", "20-day average above the 50-day", "50-day average above the 200-day",
    "RSI over 55", "MACD above its signal line", "ADX at 25 or more, buyers ahead",
    "More volume on up days", "Volume above its usual this week", "Within 5% of its 52-week high")
FLOW_SECTORS = 4           # the sectors money is moving into
FLOW_PER_SECTOR = 4        # and the strongest stocks taken from each
FLOW_MIN_MEMBERS = 8
EMERGING_FLOOR = 0.50
SHORT_SCORECARD = 6        # chart conditions the short-term list needs, of nine
SHORT_SECTOR_FLOOR = 50.0  # its industry in the top half on money flow
SHORT_BAD_REACTION = -0.02 # results the market sold this hard are a no
VERGE_PCT = 3.0            # how near the top of its base counts as on the verge       # a sector needs this many liquid stocks to be ranked

# How far back a breakout may be and still be "fresh", and how long the price
# must have gone without a six-month closing high for a new one to count as a
# breakout and not as one more day of a run.
BREAKOUT_LOOKBACK = 5
BREAKOUT_QUIET = 20
HIGH_WINDOW = 126


def _ema(x, span):
    """Exponential average as pandas' ewm(span, adjust=False) computes it."""
    a = 2.0 / (span + 1.0)
    out = np.empty(len(x), dtype=float)
    out[0] = x[0]
    for i in range(1, len(x)):
        out[i] = a * x[i] + (1 - a) * out[i - 1]
    return out


def _wilder(x, n=14):
    """Wilder's smoothing: an exponential average with alpha 1/n."""
    a = 1.0 / n
    out = np.empty(len(x), dtype=float)
    out[0] = x[0]
    for i in range(1, len(x)):
        out[i] = a * x[i] + (1 - a) * out[i - 1]
    return out


def technicals(df):
    """
    Price action, volume and the textbook indicators for one stock, or None.

    Every figure reads bars up to the last one only. The definitions are the
    ones research/signals_lab.py measured, written the same way, so a number
    printed beside a pick is the number that was tested:

      to_pivot        the close over the highest high of the last 60 sessions
      near_6m_high    the close over the highest close of the last 126
      breakout        the first close at a 126-session high after 20 sessions
                      without one, if it came in the last five sessions, with
                      that day's volume against the median of the 50 before it
      squeeze         ten-day volatility over sixty-day: under 1 is a
                      tightening range
      range_15_60     the last fortnight's high-low range over the last
                      quarter's
      dry_up          ten-day average volume over fifty-day
      up_down_volume  volume traded on rising days over falling days, 50 days
      rel_volume      today's volume against the median of the 50 before it
      rsi, macd, adx  14-day RSI, MACD(12, 26, 9) and ADX(14), Wilder's way
    """
    if np is None or df is None:
        return None
    try:
        frame = df.dropna(subset=["Close"])
    except Exception:
        return None
    n = len(frame)
    if n < HIGH_WINDOW + BREAKOUT_QUIET + BREAKOUT_LOOKBACK + 1:
        return None
    # Three hundred bars is every window below with room to spare, and it
    # bounds the smoothing loops however long a frame the caller holds.
    frame = frame.iloc[-300:]
    n = len(frame)
    c = np.asarray(frame["Close"], dtype=float)
    if not np.all(np.isfinite(c[-200:])) or np.any(c[-200:] <= 0):
        return None
    c = np.where(np.isfinite(c) & (c > 0), c, c[-200:].mean())
    h = np.asarray(frame["High"], dtype=float) if "High" in frame.columns else c.copy()
    low = np.asarray(frame["Low"], dtype=float) if "Low" in frame.columns else c.copy()
    h = np.where(np.isfinite(h), h, c)
    low = np.where(np.isfinite(low), low, c)
    has_vol = "Volume" in frame.columns
    v = np.asarray(frame["Volume"], dtype=float) if has_vol else np.zeros(n)
    v = np.where(np.isfinite(v), v, 0.0)
    price = float(c[-1])
    lr = np.diff(np.log(c))

    out = {"to_pivot": float(price / h[-60:].max()),
           "near_6m_high": float(price / c[-HIGH_WINDOW:].max())}

    # A fresh six-month closing high in the last five sessions.
    span = BREAKOUT_LOOKBACK + BREAKOUT_QUIET
    is_high = np.zeros(span, dtype=bool)
    for k in range(span):                      # k = 0 is today
        t = n - 1 - k
        if t - (HIGH_WINDOW - 1) < 0:
            break
        is_high[k] = c[t] >= c[t - (HIGH_WINDOW - 1):t + 1].max()
    out["breakout"] = None
    for k in range(BREAKOUT_LOOKBACK - 1, -1, -1):          # the earliest in the window wins
        if is_high[k] and not is_high[k + 1:k + 1 + BREAKOUT_QUIET].any():
            t = n - 1 - k
            before = v[max(0, t - 50):t]
            med = float(np.median(before)) if len(before) >= 40 else 0.0
            level = float(c[max(0, t - HIGH_WINDOW):t].max()) if t > 0 else None
            out["breakout"] = {"sessions_ago": int(k),
                               "rel_volume": float(v[t] / med) if med > 0 else None,
                               "level": level}
            break

    s10, s60 = float(lr[-10:].std(ddof=1)), float(lr[-60:].std(ddof=1))
    out["squeeze"] = float(s10 / s60) if s60 > 0 else None
    r60 = float(h[-60:].max() - low[-60:].min())
    out["range_15_60"] = float((h[-15:].max() - low[-15:].min()) / r60) if r60 > 0 else None

    if has_vol and v[-50:].sum() > 0:
        m50 = float(v[-50:].mean())
        out["dry_up"] = float(v[-10:].mean() / m50) if m50 > 0 else None
        up = float(v[-50:][lr[-50:] > 0].sum())
        dn = float(v[-50:][lr[-50:] < 0].sum())
        out["up_down_volume"] = float(up / dn) if dn > 0 else None
        med = float(np.median(v[-51:-1]))
        out["rel_volume"] = float(v[-1] / med) if med > 0 else None
    else:
        out.update(dry_up=None, up_down_volume=None, rel_volume=None)

    # The textbook indicators. Smoothed from the start of the frame, so they
    # settle within a hundred bars or so of it.
    d = np.diff(c)
    gain, loss = _wilder(np.clip(d, 0, None)), _wilder(np.clip(-d, 0, None))
    out["rsi"] = float(100 - 100 / (1 + gain[-1] / loss[-1])) if loss[-1] > 0 else 100.0
    macd = _ema(c, 12) - _ema(c, 26)
    hist = macd - _ema(macd, 9)
    out["macd_hist_pct"] = float(hist[-1] / price * 100)
    out["macd_rising"] = bool(hist[-1] > hist[-2])
    ema20 = _ema(c, 20)
    out["above_20d_pct"] = float((price / ema20[-1] - 1) * 100)
    up_m, dn_m = np.diff(h), -np.diff(low)
    plus = np.where((up_m > dn_m) & (up_m > 0), up_m, 0.0)
    minus = np.where((dn_m > up_m) & (dn_m > 0), dn_m, 0.0)
    pc = c[:-1]
    tr = np.maximum(h[1:] - low[1:], np.maximum(np.abs(h[1:] - pc), np.abs(low[1:] - pc)))
    atr = _wilder(tr)
    with np.errstate(divide="ignore", invalid="ignore"):
        pdi = 100 * _wilder(plus) / atr
        mdi = 100 * _wilder(minus) / atr
        dx = np.where((pdi + mdi) > 0, 100 * np.abs(pdi - mdi) / (pdi + mdi), 0.0)
    dx = np.where(np.isfinite(dx), dx, 0.0)
    out["adx"] = float(_wilder(dx)[-1])
    out["atr_pct"] = float(atr[-1] / price * 100) if np.isfinite(atr[-1]) else None
    out["di_spread"] = float(pdi[-1] - mdi[-1]) if np.isfinite(pdi[-1]) and np.isfinite(mdi[-1]) else None

    # ---- what the four setup lists read ------------------------------------
    # Quick trades: the two-day RSI and the 5-day average the trade is sold at.
    g2, l2 = _wilder(np.clip(d, 0, None), 2), _wilder(np.clip(-d, 0, None), 2)
    out["rsi2"] = float(100 - 100 / (1 + g2[-1] / l2[-1])) if l2[-1] > 0 else 100.0
    out["sma5"] = float(c[-5:].mean())
    sma50, sma200 = float(c[-50:].mean()), float(c[-200:].mean())
    out["above_50d"] = bool(price > sma50)
    out["above_200d"] = bool(price > sma200)

    # Money flow: this week's rupee turnover and the last sixty sessions'.
    turn = c * v
    out["turnover_5"] = float(turn[-5:].mean()) if has_vol else None
    out["turnover_60"] = float(turn[-60:].mean()) if has_vol else None
    usual5 = float(np.median(v[-55:-5])) if has_vol and n >= 55 else 0.0
    out["rel_volume_5"] = float(v[-5:].mean() / usual5) if usual5 > 0 else None

    # The 40-session base. `box` is a close above it in the last five sessions,
    # the earliest if there were two: the top and bottom of the base it broke
    # out of, how wide that was, and the breakout session's volume against the
    # median of the fifty before it.
    out["box"] = None
    for k in range(BOX_LOOKBACK - 1, -1, -1):
        t = n - 1 - k
        if t - BOX_SESSIONS < 0:
            continue
        top, bot = float(h[t - BOX_SESSIONS:t].max()), float(low[t - BOX_SESSIONS:t].min())
        if bot <= 0 or c[t] <= top:
            continue
        before = v[max(0, t - 50):t]
        med = float(np.median(before)) if len(before) >= 40 else 0.0
        out["box"] = {"sessions_ago": int(k), "top": top, "low": bot, "width": (top - bot) / bot,
                      "rel_volume": float(v[t] / med) if med > 0 else None,
                      "close": float(c[t]), "holding": bool(price >= top)}
        break
    # The base as it stands today, for a stock still inside one.
    top, bot = float(h[-BOX_SESSIONS - 1:-1].max()), float(low[-BOX_SESSIONS - 1:-1].min())
    out["base"] = ({"top": top, "low": bot, "width": (top - bot) / bot, "to_top": float(top / price - 1)}
                   if bot > 0 and price <= top else None)

    # The technical scorecard: nine textbook conditions, and which hold.
    near_52w = float(price / h[-252:].max())
    checks = [
        ("Above its 20-day average", price > ema20[-1]),
        ("20-day average above the 50-day", ema20[-1] > sma50),
        ("50-day average above the 200-day", sma50 > sma200),
        ("RSI over 55", out["rsi"] > 55),
        ("MACD above its signal line", hist[-1] > 0),
        ("ADX at 25 or more, buyers ahead", out["adx"] >= 25 and (out["di_spread"] or 0) > 0),
        ("More volume on up days", (out.get("up_down_volume") or 0) > 1.2),
        ("Volume above its usual this week", (out.get("rel_volume_5") or 0) > 1.2),
        ("Within 5% of its 52-week high", near_52w >= 0.95),
    ]
    assert tuple(label for label, _ok in checks) == SCORECARD_LABELS
    out["scorecard"] = int(sum(1 for _label, ok in checks if ok))
    out["scorecard_met"] = [label for label, ok in checks if ok]
    return out


def _recent_days(frame, c):
    """The last DAYS_KEPT sessions as (ISO date, close-to-close move), oldest
    first, or None for a frame with no dates. What the results list needs to
    find the session a result was first priced in."""
    try:
        idx = frame.index[-DAYS_KEPT:]
        dates = [d.date().isoformat() if hasattr(d, "date") else str(d)[:10] for d in idx]
        if any(len(d) != 10 or d[4] != "-" for d in dates):
            return None
    except Exception:
        return None
    moves = c[-DAYS_KEPT:] / c[-DAYS_KEPT - 1:-1] - 1.0
    return [(d, float(m)) for d, m in zip(dates, moves)]


def _safe_technicals(frame):
    try:
        return technicals(frame)
    except Exception:
        return None


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


def _short_day(iso):
    try:
        d = dt.date.fromisoformat(str(iso)[:10])
        return f"{d.day} {d.strftime('%b')}"
    except Exception:
        return str(iso or "")[:10]


def _why(key, sig, calm, ev=None):
    """The evidence in words a first-time reader can use. Facts, no advice."""
    out = []
    t = sig.get("tech") or {}
    if key == "breakout" and t.get("box"):
        b = t["box"]
        ago = b["sessions_ago"]
        out.append("Broke out today" if ago == 0 else
                   ("Broke out yesterday" if ago == 1 else f"Broke out {ago} sessions ago"))
        if _finite(b.get("rel_volume")) is not None:
            out.append(f"On {b['rel_volume']:.1f} times its usual volume")
        out.append(f"{BOX_SESSIONS} sessions inside a {b['width'] * 100:.0f}% range")
    if key == "short" and t.get("box"):
        b = t["box"]
        ago = b["sessions_ago"]
        out.append("Broke out today" if ago == 0 else
                   ("Broke out yesterday" if ago == 1 else f"Broke out {ago} sessions ago"))
        if _finite(b.get("rel_volume")) is not None:
            out.append(f"{b['rel_volume']:.1f}\u00d7 usual volume")
        row = (ev or {}).get("sector_row")
        if row:
            out.append(f"{row['sector']}: ranked {row['rank']} of {row['of']} on money flow")
        p = (ev or {}).get("pat_yoy_pct")
        if p is not None and p > 0:
            out.append(f"Profit up {min(p, 999):.0f}% on a year ago")
        return out[:4]
    if key == "technical" and t.get("scorecard") is not None:
        out.append(f"{t['scorecard']} of 9 chart conditions")
        if _finite(t.get("rsi")) is not None:
            out.append(f"RSI {t['rsi']:.0f}")
    if key == "quick" and _finite(t.get("rsi2")) is not None:
        out.append(f"Two-day RSI {t['rsi2']:.0f}")
        r5q = sig.get("ret_5d")
        if r5q is not None and r5q <= -0.01:
            out.append(f"Fell {abs(r5q) * 100:.0f}% this week")
    if key == "emerging" and sig.get("young"):
        r3e = sig.get("ret_3m")
        if r3e is not None:
            out.append(f"{'Up' if r3e >= 0 else 'Down'} {abs(r3e) * 100:.0f}% in three months")
    if key == "flow" and ev and ev.get("sector"):
        out.append(f"{ev['sector']}: money moving in")
        out.append(f"Sector ranked {ev['rank']} of {ev['of']}")
    if key == "results" and ev and ev.get("filed_at"):
        out.append(f"Results on {_short_day(ev['filed_at'])}")
        move = ev["move"] * 100
        out.append(f"{'Rose' if move >= 0 else 'Fell'} {abs(move):.0f}% the day they were priced")
        g = _finite(ev.get("pat_yoy_pct"))
        if g is not None and abs(g) < 1000:
            out.append(f"Profit {'up' if g >= 0 else 'down'} {abs(g):.0f}% on a year ago")
    r5 = sig.get("ret_5d")
    if key == "week" and r5 is not None and r5 <= -0.01:
        out.append(f"Fell {abs(r5) * 100:.0f}% this week")
    r21 = sig.get("ret_1m")
    if key == "month" and r21 is not None and r21 <= -0.01:
        out.append(f"Fell {abs(r21) * 100:.0f}% this month")
    r12 = sig.get("ret_12m")
    if sig.get("young"):
        out.append(f"Listed {max(6, round((sig.get('sessions') or 0) / 21))} months")
        r6 = sig.get("ret_6m")
        if r6 is not None:
            out.append(f"Up {r6 * 100:.0f}% in six months" if r6 >= 0 else f"Down {abs(r6) * 100:.0f}% in six months")
    elif r12 is not None:
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


def _parse_filed(value):
    """When a filing reached the exchange, as a datetime, or None. A bare date
    is read as after the close: two results in three arrive after the close."""
    if isinstance(value, dt.datetime):
        return value.replace(tzinfo=None)
    if isinstance(value, dt.date):
        return dt.datetime(value.year, value.month, value.day, 23, 59)
    text = str(value or "").strip().replace("T", " ")
    if len(text) < 10:
        return None
    try:
        day = dt.date.fromisoformat(text[:10])
    except ValueError:
        return None
    try:
        hh, mm = int(text[11:13]), int(text[14:16])
    except ValueError:
        hh, mm = 23, 59
    return dt.datetime(day.year, day.month, day.day, hh, mm)


def result_reactions(pool, results):
    """
    How each stock moved on the session its results were first priced in.

    `pool` is [(SYMBOL, signals)] for the liquid universe; `results` maps a
    symbol to at least {"filed_at": when the filing reached the exchange}.
    The session is the first one whose close came after the filing. The move
    is the stock's close-to-close change that session, less the average
    liquid stock's the same day. Only results priced in the last
    RESULTS_WINDOW sessions are returned: an older one is no longer news.
    """
    if not results:
        return {}
    by_date = {}
    for _sym, g in pool:
        for d, m in (g.get("days") or ()):
            by_date.setdefault(d, []).append(m)
    # A date most of the market traded on. One stock's stray bar is not a session.
    need = max(3, len(pool) // 2)
    sessions = sorted(d for d, ms in by_date.items() if len(ms) >= need)
    window = set(sessions[-RESULTS_WINDOW:])
    if not window:
        return {}
    out = {}
    for sym, g in pool:
        r = results.get(sym)
        if not r:
            continue
        filed = _parse_filed(r.get("filed_at"))
        if filed is None:
            continue
        fday = filed.date().isoformat()
        late = filed.hour * 60 + filed.minute > MARKET_CLOSE_MIN
        k = next((i for i, d in enumerate(sessions) if d > fday or (d == fday and not late)), None)
        # The first known session cannot be told from "some session before
        # everything we hold", so a result that old is not placed at all.
        if k is None or k == 0 or sessions[k] not in window:
            continue
        d0 = sessions[k]
        move = dict(g.get("days") or ()).get(d0)
        if move is None or not math.isfinite(move):
            continue                       # it did not trade that session
        market = float(np.mean(by_date[d0]))
        out[sym] = {
            "filed_at": str(r.get("filed_at"))[:19], "session": d0,
            "sessions_ago": len(sessions) - 1 - k,
            "move": float(move), "market_move": market, "reaction": float(move - market),
            "quarter": r.get("quarter"),
            "pat_yoy_pct": _finite(r.get("pat_yoy_pct")),
            "revenue_yoy_pct": _finite(r.get("revenue_yoy_pct")),
        }
    return out


def _tech_block(t):
    """The technicals as the page prints them: rounded, nothing else changed."""
    if not t:
        return None

    def r(v, dp=2):
        f = _finite(v)
        return None if f is None else round(f, dp)
    b = t.get("breakout")
    return {
        "below_60d_high_pct": r((1 - t["to_pivot"]) * 100, 1) if _finite(t.get("to_pivot")) is not None else None,
        "below_6m_high_pct": (r((1 - t["near_6m_high"]) * 100, 1)
                              if _finite(t.get("near_6m_high")) is not None else None),
        "breakout": ({"sessions_ago": b["sessions_ago"], "rel_volume": r(b.get("rel_volume"), 1),
                      "level": r(b.get("level"))} if b else None),
        "squeeze": r(t.get("squeeze")), "range_15_60": r(t.get("range_15_60")),
        "dry_up": r(t.get("dry_up")), "up_down_volume": r(t.get("up_down_volume")),
        "rel_volume": r(t.get("rel_volume"), 1),
        "rsi": r(t.get("rsi"), 0), "macd_hist_pct": r(t.get("macd_hist_pct")),
        "macd_rising": t.get("macd_rising"), "above_20d_pct": r(t.get("above_20d_pct"), 1),
        "adx": r(t.get("adx"), 0), "atr_pct": r(t.get("atr_pct"), 1),
        "rsi2": r(t.get("rsi2"), 0), "sma5": r(t.get("sma5")),
        "rel_volume_5": r(t.get("rel_volume_5"), 1),
        "above_50d": t.get("above_50d"), "above_200d": t.get("above_200d"),
        "scorecard": t.get("scorecard"), "scorecard_met": t.get("scorecard_met"),
        "box": (None if not t.get("box") else {
            "sessions_ago": t["box"]["sessions_ago"], "top": r(t["box"]["top"]), "low": r(t["box"]["low"]),
            "width_pct": r(t["box"]["width"] * 100, 1), "rel_volume": r(t["box"].get("rel_volume"), 1),
            "close": r(t["box"]["close"]), "holding": t["box"]["holding"]}),
        "base": (None if not t.get("base") else {
            "top": r(t["base"]["top"]), "low": r(t["base"]["low"]),
            "width_pct": r(t["base"]["width"] * 100, 1), "to_top_pct": r(t["base"]["to_top"] * 100, 1)}),
    }


def sector_flow(pool, sectors):
    """
    Where money is moving: every sector with enough liquid stocks, ranked.

    `pool` is [(SYMBOL, signals)] for the established universe; `sectors`
    maps a symbol to its sector. Three measurements, each turned into a
    rank among the sectors and averaged:

      shift    the sector's share of all rupee turnover this week, over its
               share across the last sixty sessions (above 1: money moving in)
      breadth  the share of its stocks above their own 50-day average
      month    the median move of its stocks over the last 21 sessions

    Returns the sectors best first, each with its three figures, its score
    and its rank. Empty when no sector list was given.
    """
    if not sectors:
        return []
    groups, tot5, tot60 = {}, 0.0, 0.0
    for sym, g in pool:
        t = g.get("tech") or {}
        t5, t60 = _finite(t.get("turnover_5")), _finite(t.get("turnover_60"))
        if t5 is None or not t60:
            continue
        tot5 += t5
        tot60 += t60
        sec = sectors.get(sym)
        if sec:
            groups.setdefault(sec, []).append((sym, g, t5, t60, bool(t.get("above_50d"))))
    rows = []
    for sec, members in groups.items():
        if len(members) < FLOW_MIN_MEMBERS or tot5 <= 0 or tot60 <= 0:
            continue
        s5, s60 = sum(m[2] for m in members), sum(m[3] for m in members)
        month = sorted(_finite(m[1].get("ret_1m")) or 0.0 for m in members)
        mid = len(month) // 2
        rows.append({
            "sector": sec, "stocks": len(members),
            "shift": (s5 / tot5) / (s60 / tot60) if s60 > 0 else None,
            "breadth": sum(1 for m in members if m[4]) / len(members),
            "month": month[mid] if len(month) % 2 else (month[mid - 1] + month[mid]) / 2.0,
        })
    if not rows:
        return []
    ranks = [_pct_ranks([r[k] for r in rows]) for k in ("shift", "breadth", "month")]
    for i, r in enumerate(rows):
        parts = [x[i] for x in ranks if x[i] is not None]
        r["score"] = sum(parts) / len(parts) if parts else 0.0
    rows.sort(key=lambda r: (-r["score"], r["sector"]))
    for n, r in enumerate(rows, 1):
        r.update(rank=n, of=len(rows),
                 shift=None if r["shift"] is None else round(r["shift"], 3),
                 breadth_pct=round(r.pop("breadth") * 100, 1),
                 month_pct=round(r.pop("month") * 100, 1), score=round(r["score"] * 100, 1))
    return rows


def _short(sym, g, part, sectors, flow_by, pat_yoy, growth, ev):
    """(score, why not or None, order) for the short-term list: a breakout
    from a tight base that is still holding, passed through five screens."""
    t = g.get("tech") or {}
    b = t.get("box")
    row = flow_by.get(sectors.get(sym))
    card = t.get("scorecard") or 0
    sec = (row["score"] / 100.0) if row else 0.5
    score = (part["leader"] + card / 9.0 + sec + (growth if growth is not None else 0.5)) / 4.0 * 100.0
    why = None
    if not b:
        base = t.get("base")
        if base and base["width"] <= BOX_MAX_WIDTH and base["to_top"] * 100 <= VERGE_PCT:
            why = (f"On the verge: {base['to_top'] * 100:.1f}% under the top of its base, not yet through it. "
                   "The list waits for the breakout.")
        else:
            why = f"No breakout from a {BOX_SESSIONS}-session base in the last {BOX_LOOKBACK} sessions."
    elif b["width"] > BOX_MAX_WIDTH:
        why = f"The range it broke out of was {b['width'] * 100:.0f}% wide; a base is {BOX_MAX_WIDTH * 100:.0f}% or tighter."
    elif (_finite(b.get("rel_volume")) or 0.0) < BOX_MIN_VOLUME:
        why = f"The breakout came on {(_finite(b.get('rel_volume')) or 0.0):.1f} times its usual volume; it needs {BOX_MIN_VOLUME:.0f}."
    elif not b["holding"]:
        why = "It has closed back under the top of its base since breaking out."
    elif not g["price"] > g["sma200"]:
        why = "Under its 200-day average."
    elif part["leader"] < BOX_LEADER_FLOOR:
        why = "Its leader score is in the bottom half of liquid stocks."
    elif card < SHORT_SCORECARD:
        why = f"Meets {card} of the nine chart conditions; the list needs {SHORT_SCORECARD}."
    elif row is None:
        why = "Its industry could not be ranked on money flow."
    elif row["score"] < SHORT_SECTOR_FLOOR:
        why = f"Its industry, {row['sector']}, ranks {row['rank']} of {row['of']} on money flow: the bottom half."
    elif pat_yoy is not None and pat_yoy < 0:
        why = f"Profit fell {abs(pat_yoy):.0f}% on a year ago in its last quarter."
    elif ev and ev["reaction"] < SHORT_BAD_REACTION:
        why = (f"Its results were sold: {ev['move'] * 100:+.1f}% the day they were priced, against "
               f"{ev['market_move'] * 100:+.1f}% for the average stock.")
    return score, why, score


def _setup(key, sym, g, part, is_calm, sectors, flow_by, flow_top, flow_pick):
    """(score out of 100, why it is not on the list or None, the figure it is
    ordered on) for one stock on one of the four setup lists."""
    t = g.get("tech") or {}
    leader = part["leader"]
    if key == "breakout":
        b = t.get("box")
        if not b:
            return 0.0, f"No close above a {BOX_SESSIONS}-session range in the last {BOX_LOOKBACK} sessions.", -1.0
        vol = _finite(b.get("rel_volume")) or 0.0
        score = min(vol, 6.0) / 6.0 * 100.0
        why = None
        if b["width"] > BOX_MAX_WIDTH:
            why = (f"The range it broke out of was {b['width'] * 100:.0f}% wide; a base is "
                   f"{BOX_MAX_WIDTH * 100:.0f}% or tighter.")
        elif vol < BOX_MIN_VOLUME:
            why = f"The breakout came on {vol:.1f} times its usual volume; it needs {BOX_MIN_VOLUME:.0f}."
        elif not g["price"] > g["sma200"]:
            why = "Under its 200-day average."
        elif leader < BOX_LEADER_FLOOR:
            why = "Its leader score is in the bottom half of liquid stocks."
        # Still above the base first, then the newest, then the heaviest volume.
        order = (1000.0 if b["holding"] else 0.0) + (BOX_LOOKBACK - b["sessions_ago"]) * 10.0 + min(vol, 9.9)
        return score, why, order
    if key == "technical":
        n = t.get("scorecard")
        if n is None:
            return 0.0, "Not enough history to read the chart.", -1.0
        why = None if n >= SCORECARD_MIN else f"Meets {n} of the nine chart conditions; the list needs {SCORECARD_MIN}."
        return n / 9.0 * 100.0, why, n + 0.5 * part["high"]
    if key == "quick":
        r2 = _finite(t.get("rsi2"))
        if r2 is None:
            return 0.0, "Not enough history to read the chart.", -1.0
        why = None
        if not g["uptrend"]:
            why = "Not in an uptrend: price or its 50-day average is under the 200-day average."
        elif r2 >= QUICK_RSI2:
            why = f"Two-day RSI is {r2:.0f}; the setup is under {QUICK_RSI2:.0f}."
        elif leader < QUICK_LEADER_FLOOR:
            why = "Not a market leader: its leader score is under the top 30% of liquid stocks."
        return max(0.0, (QUICK_RSI2 - r2) / QUICK_RSI2) * 100.0, why, -r2
    # Money flow.
    sec = sectors.get(sym)
    score = leader * 100.0
    if not sectors:
        return score, "No sector list was available for this scan.", -1.0
    if not sec:
        return score, "Not in NSE's sector list.", -1.0
    if sec not in flow_by:
        return score, f"Fewer than {FLOW_MIN_MEMBERS} liquid stocks in its sector to measure a flow on.", -1.0
    if sec not in flow_top:
        row = flow_by[sec]
        return score, (f"Its sector, {sec}, ranks {row['rank']} of {row['of']} on money flow; "
                       f"the list takes the top {FLOW_SECTORS}."), -1.0
    if sym not in flow_pick:
        why = ("Not in an uptrend." if not g["uptrend"] else
               ("Among the most volatile fifth of liquid stocks." if not is_calm else
                f"Not among the {FLOW_PER_SECTOR} strongest in {sec}."))
        return score, why, -1.0
    return score, None, (FLOW_SECTORS - flow_top.index(sec)) * 10.0 + leader


def rank(candidates, results=None, sectors=None, fundamentals=None):
    """
    Score every candidate against the whole liquid universe, for every list.

    `candidates` is a list of dicts carrying `symbol` and `leader_sig` (the
    output of signals(), or None). `results` maps a symbol to when its latest
    quarterly results reached the exchange ({"filed_at": ...}); without it the
    results list is simply empty. `sectors` maps a symbol to its sector;
    without it the money-flow list is empty. `fundamentals` maps a symbol to
    its latest quarter ({"pat_yoy_pct", "revenue_yoy_pct"}); the short-term
    list refuses a known fall in profit and ranks growth higher.
    Returns {SYMBOL: block}. A stock outside
    the universe gets no block: it was not compared, which is different from
    being compared and failing a gate.
    """
    if np is None:
        return {}
    everyone = [(str(c.get("symbol") or "").upper(), c.get("leader_sig")) for c in candidates or []]
    everyone = [(s, g) for s, g in everyone if s and in_universe(g)]
    # The universe every percentile is taken over: companies with a full year
    # of history. Younger ones are placed against it afterwards (below), so
    # letting them in changes no established stock's score.
    pool = [(s, g) for s, g in everyone if not g.get("young")]
    newcomers = [(s, g) for s, g in everyone if g.get("young")]
    if len(pool) < 30:
        # Thirty names is too few for a percentile to mean anything. A short
        # test list or a scan that stopped early says so instead of ranking.
        return {}

    def month_dip(g):
        # A frame from before ret_1m existed (an old checkpoint) ranks as no dip.
        return -(g.get("ret_1m") if _finite(g.get("ret_1m")) is not None else 0.0)
    raw = {"m12": [g["va12"] for _, g in pool], "m6": [g["va6"] for _, g in pool],
           "high": [g["near_high"] for _, g in pool], "trend": [g["trend"] for _, g in pool],
           "calm": [-g["vol"] for _, g in pool], "dip": [-g["ret_5d"] for _, g in pool],
           "dip21": [month_dip(g) for _, g in pool]}
    m12, m6, high, trend = (_pct_ranks(raw[k]) for k in ("m12", "m6", "high", "trend"))
    calm, dip, dip21 = (_pct_ranks(raw[k]) for k in ("calm", "dip", "dip21"))
    # Where a newcomer would stand among the established: the share of them
    # at or below its figure. Its 6-month return-for-risk is set against their
    # 12-month one, which is what "stands in" means.
    ladder = {k: np.sort(np.asarray(v, dtype=float)) for k, v in raw.items()}

    def standing(key, value):
        return max(1, int(np.searchsorted(ladder[key], float(value), side="right"))) / len(pool)
    for sym, g in newcomers:
        m12.append(standing("m12", g["va12"]))
        m6.append(standing("m6", g["va6"]))
        high.append(standing("high", g["near_high"]))
        trend.append(standing("trend", g["trend"]))
        calm.append(standing("calm", -g["vol"]))
        dip.append(standing("dip", -g["ret_5d"]))
        dip21.append(standing("dip21", month_dip(g)))

    # Results priced in the last ten sessions, ranked among themselves: the
    # comparison the study made was with other companies that had just reported.
    events = result_reactions(pool, {str(k).upper(): v for k, v in (results or {}).items()})
    reaction = {}
    if len(events) >= RESULTS_MIN_POOL:
        syms = sorted(events)
        reaction = dict(zip(syms, _pct_ranks([events[x]["reaction"] for x in syms])))

    # Where money is moving, and the strongest established stocks in each of
    # those sectors: uptrend, outside the most volatile fifth, best leader
    # score first.
    sectors = {str(k).upper(): v for k, v in (sectors or {}).items() if v}
    flow_rows = sector_flow(pool, sectors)
    flow_by = {r["sector"]: r for r in flow_rows}
    flow_top = [r["sector"] for r in flow_rows[:FLOW_SECTORS]]
    flow_pick = {}
    for sec in flow_top:
        members = [(-(m12[i] + m6[i] + high[i] + trend[i]) / 4.0, sym)
                   for i, (sym, g) in enumerate(pool)
                   if sectors.get(sym) == sec and g["uptrend"] and calm[i] >= CALM_FLOOR]
        for _lead, sym in sorted(members)[:FLOW_PER_SECTOR]:
            flow_pick[sym] = sec

    # The last quarter, where it is known: profit growth as a percentile
    # among the established stocks that have one.
    fundamentals = {str(k).upper(): v for k, v in (fundamentals or {}).items() if v}
    pat = {sym: _finite((fundamentals.get(sym) or {}).get("pat_yoy_pct")) for sym, _g in pool}
    have = [sym for sym, v in pat.items() if v is not None]
    growth = dict(zip(have, _pct_ranks([max(-100.0, min(300.0, pat[x])) for x in have]))) if have else {}

    blocks, exact = {}, {}
    for i, (sym, g) in enumerate(pool + newcomers):
        young = bool(g.get("young"))
        part = {"m12": m12[i], "m6": m6[i], "high": high[i], "trend": trend[i],
                "calm": calm[i], "dip": dip[i], "dip21": dip21[i],
                "reaction": reaction.get(sym)}
        part["leader"] = (m12[i] + m6[i] + high[i] + trend[i]) / 4.0
        is_calm = calm[i] >= CALM_FLOOR
        ev = events.get(sym)
        lists = {}
        for key, spec in LISTS.items():
            why_not = None
            floor = spec.get("leader_floor")
            if key == "emerging":
                # Newly listed companies alone, placed against the established
                # universe: above their own 50-day average, in its top half
                # on the leader score, strongest first.
                score = part["leader"] * 100.0
                t = g.get("tech") or {}
                if not young:
                    why_not = "Listed more than a year: this list is for companies listed six to twelve months."
                elif not t.get("above_50d"):
                    why_not = "Under its own 50-day average."
                elif part["leader"] < EMERGING_FLOOR:
                    why_not = "Its leader score is in the bottom half of liquid stocks."
                exact[(sym, key)] = part["leader"] if young else -1.0
                part[key] = part["leader"]
            elif young and key not in YOUNG_LISTS:
                # Tested and not admitted: on these lists the younger picks
                # trailed the average stock in at least one half.
                score = 0.0
                why_not = ("Listed under a year. This list needs twelve months of prices; "
                           f"younger companies are on {', '.join(LISTS[k]['label'].lower() for k in YOUNG_LISTS)} "
                           "and emerging.")
                exact[(sym, key)] = -1.0
            elif spec.get("kind") == "setup":
                if key == "short":
                    score, why_not, exact[(sym, key)] = _short(sym, g, part, sectors, flow_by,
                                                                pat.get(sym), growth.get(sym), ev)
                else:
                    score, why_not, exact[(sym, key)] = _setup(key, sym, g, part, is_calm,
                                                                sectors, flow_by, flow_top, flow_pick)
                part[key] = score / 100.0
            elif spec.get("event") == "results":
                score = (part["reaction"] or 0.0) * 100.0
                if ev is None:
                    why_not = f"No results priced in the last {RESULTS_WINDOW} sessions."
                elif part["reaction"] is None:
                    why_not = (f"Fewer than {RESULTS_MIN_POOL} liquid companies have had results "
                               f"priced in the last {RESULTS_WINDOW} sessions.")
                # Ordered on the move itself; the percentile is only how it prints.
                exact[(sym, key)] = ev["reaction"] if ev else -1.0
            else:
                score = sum(part[k] * w for k, w in spec["mix"].items()) * 100.0
                if spec.get("trend_gate", True) and not g["uptrend"]:
                    why_not = "Not in an uptrend: price or its 50-day average is under the 200-day average."
                elif spec["calm_gate"] and not is_calm:
                    why_not = "Among the most volatile fifth of liquid stocks."
                elif floor is not None and part["leader"] < floor:
                    why_not = (f"Not a market leader: its leader score is under the top "
                               f"{100 - floor * 100:.0f}% of liquid stocks.")
                exact[(sym, key)] = score
            fact = ev
            if key == "short":
                fact = {"sector_row": flow_by.get(sectors.get(sym)), "pat_yoy_pct": pat.get(sym)}
            if key == "flow" and sectors.get(sym) in flow_by:
                fact = flow_by[sectors[sym]]
            lists[key] = {"score": round(score, 1), "eligible": why_not is None,
                          "why_not": why_not, "rank": None,
                          "why": _why(key, g, calm[i], fact)}
        blocks[sym] = {
            "recipe": RECIPE,
            "universe": len(pool),
            # Listed six to twelve months: ranked against the established
            # universe, on the lists in YOUNG_LISTS only.
            "young": young,
            "listed_sessions": g.get("sessions"),
            "uptrend": bool(g["uptrend"]),
            "calm": bool(is_calm),
            "score": round(part["leader"] * 100.0, 1),
            "parts": {
                "momentum_12m": round(m12[i] * 100), "momentum_6m": round(m6[i] * 100),
                "near_high": round(high[i] * 100), "steady_trend": round(trend[i] * 100),
                "calm": round(calm[i] * 100), "dip": round(dip[i] * 100),
                "dip_month": round(dip21[i] * 100), "leader": round(part["leader"] * 100),
                "reaction": None if part["reaction"] is None else round(part["reaction"] * 100),
            },
            "facts": {
                "return_12m_pct": (round(g["ret_12m"] * 100, 1)
                                   if _finite(g.get("ret_12m")) is not None else None),
                "return_6m_pct": (round(g["ret_6m"] * 100, 1)
                                  if _finite(g.get("ret_6m")) is not None else None),
                "return_3m_pct": round(g["ret_3m"] * 100, 1),
                "return_1m_pct": (round(g["ret_1m"] * 100, 1)
                                  if _finite(g.get("ret_1m")) is not None else None),
                "return_5d_pct": round(g["ret_5d"] * 100, 1),
                "below_high_pct": round((1 - g["near_high"]) * 100, 1),
                "trend_straightness": round(g["trend"], 0),
                "volatility_pct": round(g["vol"] * 100, 1),
                "turnover_cr": round(g["turnover"] / 1e7, 1),
                "sma50": g["sma50"], "sma200": g["sma200"],
            },
            # What the chart and the tape say. Shown beside a pick as facts;
            # none of it moves a rank (research/IDEAS-STUDY.md, "What did not
            # earn a place").
            "technicals": _tech_block(g.get("tech")),
            # Its sector (NSE's own), and where that sector stands on money flow.
            "sector": sectors.get(sym),
            # The last quarter against the same quarter a year before.
            "quarter": (None if sym not in fundamentals else {
                "pat_yoy_pct": _finite(fundamentals[sym].get("pat_yoy_pct")),
                "revenue_yoy_pct": _finite(fundamentals[sym].get("revenue_yoy_pct")),
                "label": fundamentals[sym].get("quarter")}),
            "sector_flow": flow_by.get(sectors.get(sym)),
            # The result this stock was last priced on, if it was in the last
            # ten sessions, with how many companies it was ranked among.
            "results": (None if ev is None else {
                "filed_at": ev["filed_at"], "session": ev["session"],
                "sessions_ago": ev["sessions_ago"], "quarter": ev.get("quarter"),
                "move_pct": round(ev["move"] * 100, 1),
                "market_move_pct": round(ev["market_move"] * 100, 1),
                "reaction_pct": round(ev["reaction"] * 100, 1),
                "pat_yoy_pct": ev.get("pat_yoy_pct"), "revenue_yoy_pct": ev.get("revenue_yoy_pct"),
                "reported": len(events)}),
            "lists": lists,
        }
    # A list that gives way is ranked after the list it gives way to, so it
    # knows which names that list's top LIST_SIZE took.
    order = sorted(LISTS, key=lambda k: 1 if LISTS[k].get("gives_way_to") else 0)
    for key in order:
        taken = set()
        other = LISTS[key].get("gives_way_to")
        if other:
            taken = {s for s in blocks if (blocks[s]["lists"][other]["rank"] or 0) and
                     blocks[s]["lists"][other]["rank"] <= LIST_SIZE}
            label = LISTS[other]["label"].lower()
            for s in taken:
                entry = blocks[s]["lists"][key]
                if entry["eligible"]:
                    entry.update(eligible=False, why_not=(
                        f"On the {label} list. Each stock is on one of the two, so "
                        f"{LISTS[key]['label'].lower()} shows different names."))
        # Ordered on the exact score. The printed one is rounded to a decimal,
        # and ranking on that would settle every near-tie alphabetically.
        ordered = sorted((s for s in blocks if blocks[s]["lists"][key]["eligible"]),
                         key=lambda s: (-exact[(s, key)], s))
        for n, sym in enumerate(ordered, 1):
            blocks[sym]["lists"][key]["rank"] = n
    return blocks


def breakout_watch(blocks, limit=20):
    """
    Tight bases not yet broken: stocks whose last 40 sessions fit inside an
    18% range, above their 200-day average, in the stronger half on the
    leader score, within 3% of the top of the base, not in an industry in
    the bottom half on money flow, and without a fall in profit last quarter. Nearest the top
    first. Watched, not picked: nothing here has broken out.
    """
    out = []
    for sym, b in (blocks or {}).items():
        t, facts = b.get("technicals") or {}, b.get("facts") or {}
        base = t.get("base")
        if not base or b.get("young") or t.get("box"):
            continue
        if base["width_pct"] > BOX_MAX_WIDTH * 100 or base["to_top_pct"] > VERGE_PCT:
            continue
        # The same screens the short-term list applies after a breakout.
        flow, q = b.get("sector_flow"), b.get("quarter") or {}
        if flow is not None and flow["score"] < SHORT_SECTOR_FLOOR:
            continue
        if q.get("pat_yoy_pct") is not None and q["pat_yoy_pct"] < 0:
            continue
        if (b.get("score") or 0) < BOX_LEADER_FLOOR * 100 or not t.get("above_200d"):
            continue
        out.append({"symbol": sym, "sector": b.get("sector"), "top": base["top"], "low": base["low"],
                    "width_pct": base["width_pct"], "to_top_pct": base["to_top_pct"],
                    "rel_volume_5": t.get("rel_volume_5"), "leader": b.get("score"),
                    "turnover_cr": facts.get("turnover_cr")})
    out.sort(key=lambda r: (r["to_top_pct"], -(r["leader"] or 0), r["symbol"]))
    return out[:limit]


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
    note = (f"Hold {spec['hold_text']}. Leave if it closes below "
            f"\u20b9{line:,.2f}, {spec['exit_pct']:.0f}% under this price.")
    if spec.get("sell_rule") == "sma5":
        note = (f"Sell at the first close above its 5-day average, or after {spec['hold_sessions']} "
                f"sessions. Leave if it closes below \u20b9{line:,.2f}, "
                f"{spec['exit_pct']:.0f}% under this price.")
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
        "sell_rule": spec.get("sell_rule"),
        "note": note,
    }
