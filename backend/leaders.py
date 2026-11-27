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

THREE FUNDAMENTAL LISTS (December 2026)
---------------------------------------
The price lists below read a stock's chart and nothing else, so a company
whose profit had just collapsed could top them. They are now three lists,
each read from the company's own filings as well as its chart
(fund_snapshot.py builds the figures, the same code for the live scan and
for the replay):

  Swing / This month       a market leader (leader score in the top 30%), in
                an uptrend and outside the most volatile fifth, in an industry
                in the top half on money flow, that pulled back over the last
                month, ranked on the pullback, its closeness to the 52-week
                high, its last quarter's sales and margin growth, its
                industry's money flow and a live catalyst. Left out: a loss or
                a fall in profit last quarter, results the market sold in the
                last month, promoters pledging more than 10% of the company.
                About a month, left on a close 12% under.
  After results            companies whose results the market rewarded for a
                real reason: sales up 8% or more, profit and operating profit
                up, not carried by other income or a one-off gain, and not
                already up 18% on the day. Ranked on that day's move against
                the average stock, the volume behind it and the growth itself.
                About a month, 12% under. Empty, and saying when it fills in,
                between results seasons.
  Long-term compounders    high returns on capital backed by cash, little
                debt, no heavy pledge, an F-score of 5 or more, a P/E under 90
                unless three-year growth carries it, above the 200-day average
                and calm; ranked on quality, compounding, governance,
                valuation against its own industry and the year-long trend.
                Banks and lenders are judged on return on equity instead.
                About a year.

Every threshold and weight is in the MONTH, RESULTS and LONG dictionaries
below, so research/fundamental_ideas_lab.py can replay the engine itself on
each declared version, point in time, and write the chosen one back here. A
figure a company has not filed is unknown, never zero: it counts as the
middle of the field in a score and skips only the check that needs it.
Pledges, holdings, deliveries and orders have no history to replay; the live
lists read them and the replay treats them as unknown.

This week and momentum became these two (week to this month, momentum to
long term). Their names still resolve, so an old link opens the list that
replaced it, and their calls in the log keep their labels.

WHAT THE FIVE PRICE LISTS WERE (November 2026)
----------------------------------------------
Four were one per holding period, because "what should I buy for a week"
and "what should I hold for a year" are different questions. Those four were
built from the same measurements, each a published, decades-old effect that
also held on our own data, turned into a percentile among every liquid stock:

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
companies were on the week and momentum lists, where their picks led the
average stock in both halves of the test. Those two lists are gone, so since
December 2026 they are on the emerging list only (YOUNG_LISTS is empty).
Under six months nothing ranks them.

THE SETUP LISTS, REBUILT (December 2026)
Breakouts, technicals, quick trades, money flow and emerging were losing
their edge to three habits, each measured in research/setups_lab.py --v2 on
the same ten years (research/setups-lab-v2.json):

  · THE EXIT. Every one left within 7 to 21 sessions on a 7-10% stop. Held
    63 sessions instead, the very same old picks made several times as much
    after costs (technicals +0.8% to +4.4% a pick, breakouts +0.7% to
    +2.9%), because a few picks in ten that make 25% or more carry an
    average and a month is too short for them.
  · THE COST. The quick trade (two-day RSI under 10, out at the 5-day
    average) rose two times in three and lost 0.2% a pick after a 0.49%
    round trip. Held a month it keeps a profit after costs.
  · THE BASE. The breakout wanted a 40-session base 18% wide or tighter in
    a stock already in the top half of 12-month leaders: the stock that has
    already moved. RATNAVEER's July 2026 launch came out of a wider base that
    tightened at the end, and the old rule never fired on it.

What each list is now, version chosen on 2017-2021 by a rule set before the
run (the best lead over the Nifty 500 among the new versions with a profit
after costs; for quick trades the most picks rising among those also ahead
of the index), its 2022-2026 record then printed whatever it was:

  Breakouts    a VCP launchpad: a close above a 40- or 60-session base 28%
               wide or less that was tight or tightened, on 1.6 times the
               usual volume, not already stretched (16% over the 50-day, 55%
               in three months), its industry's own index within 3% of
               its 60-session high (research/setups-lab-sector.json).
               Held 63 sessions, out on a close 12% under.
               The base-turnaround pattern (a first 60-session high on twice
               the volume, for a stock not yet a leader) is measured too and
               is on the watch list; see LAUNCH_PATTERNS.
  Technicals   an early Stage-2 pullback: a rising 200-day average, a dip to
               the 20-day average and a green close within 6% of it. 63 / 12%.
               Measured honestly: the old seven-of-nine scorecard, held the
               same 63 sessions, did better still in both halves. The rule
               chose among the new versions, and this is the one the reader
               asked for; the comparison is in the lab's output.
  Swing dips   (the quick list) a leader in the top 35% sold hard while
               still holding its 50-day average. 21 sessions / 10%.
  Money flow   the three sectors ranked best on rotation (three-month median
               move 45%, breadth 35%, turnover shift 20%) and the five
               strongest stocks in each that beat the Nifty 500 over one
               month and three. 63 sessions / 15%.
  Emerging     companies listed six to eighteen months in a Stage-2 advance,
               ahead of the market, not stretched. 90 sessions, out on a
               close under the 50-day after the first 15, or 15% under.

A market-weather screen (the Nifty 500 above its 50-day average) was tried
on breakouts, swing dips and emerging. It did not improve both the share of
picks rising and the average after costs in both halves for any of them,
so no list is held back in a weak market.

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
# 6-month one stands in. It was admitted to the two lists on which such
# companies led the average stock in both halves of the test (this week and
# momentum; research/IDEAS-STUDY.md, "Younger companies"). Both lists were
# folded into the fundamental ones in December 2026, which need a year of
# prices and filings, so a young company is on the emerging list only. Under
# six months there is no 6-month return either, and nothing here ranks it.
MIN_YOUNG_SESSIONS = 127           # six months of closes plus the base one
MAX_YOUNG_SPAN_DAYS = 215          # calendar days those 127 closes may cover
YOUNG_LISTS = ()
CALM_FLOOR = 0.20                  # calm percentile under which a name is out
# The leader percentile a month pick must reach: the top 30%. The specification
# asked for the top 35%; research/fundamental_ideas_lab.py tried both, and the
# rule declared before the run chose this one (version M3, with the pullback
# read over the month alone) on 2018-21. MONTH reads it.
LEADER_FLOOR = 0.70
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
# The recent daily moves (and volumes) each stock carries, to find the session
# a result was first priced in. The month list asks whether the market sold a
# company's results in the last 21 sessions; a result is placed only from the
# second session held, so 21 needs 22, and one more is the spare for a stock
# that missed a day.
DAYS_KEPT = 23
# A session's volume is read against the median of the sessions before it:
# "3.2 times its usual volume". Fewer than VOLUME_BASE_MIN of those with a
# volume on record is no usual to speak of.
VOLUME_BASE_SESSIONS = 20
VOLUME_BASE_MIN = 10
# Sector breakout (research/setups_lab.py --sector): an industry's own index,
# the mean daily move of its liquid stocks chained, at a new 60-session
# closing high in the last 10 sessions, or within 3% of that high.
SECTOR_PATH = 70                   # daily moves each stock carries to build it
SECTOR_HIGH_WINDOW = 60
SECTOR_RECENT = 10
SECTOR_NEAR = 0.97
# The breakout list asks the stock's industry to be near a high too. The lab
# (research/setups-lab-sector.json) tried two such screens, declared before
# the run; the rule adopted "within 3% of its 60-session high" for this list
# because it raised the 2017-2021 lead over the Nifty 500 (2.26 points a pick
# against 2.22), with fewer picks and 2022-2026 about level (1.33 against
# 1.35). It made the technical list worse in both halves, so only here. A
# stock with no industry on NSE's list passes, as on every sector screen.
BREAKOUT_SECTOR_NEAR_HIGH = True
# Stamped on every block rank() writes. A scan made under an earlier recipe
# still serves its lists after a deploy, but the page must not print this
# recipe's tested record beside them. Change it whenever LISTS changes.
RECIPE = "2026-12 fundamental lists v3"

# The three fundamental lists' recipes (December 2026). Every threshold and
# weight each list reads is here, so research/fundamental_ideas_lab.py can
# replay the engine itself on each declared version by swapping one of these
# dictionaries, and write the version its rule chose back as the default.
# The defaults are the versions the lab's rule chose (M3, R4 and L1; R4 and
# L1 are the recipe as specified, M3 the month list with its leader floor and
# pullback changed). Each `mix` sums to 1; `sector_cap` is how many stocks of
# one NSE industry a list may hold.
MONTH = {
    "leader_floor": LEADER_FLOOR,      # leader percentile a pick must reach
    "sector_gate": True,               # its industry must rank on money flow ...
    "sector_floor": 50.0,              # ... at this score (0-100) or better: the top half
    "profit_guard": True,              # no loss, and no fall in profit, last quarter
    "result_guard": True,              # no results the market sold ...
    "result_lookback": 21,             # ... in this many sessions ...
    "bad_reaction": -0.02,             # ... by this much against the average stock
    "pledge_max": 10.0,                # % of the company promoters may have pledged
    "catalyst_order_pct": 2.0,         # an order worth this % of market value is a catalyst
    "mix": {"pull": 0.30, "high": 0.25, "fundmom": 0.20, "secflow": 0.15, "catalyst": 0.10},
    "pull_mix": {"dip21": 1.0},        # the month's pullback (M3; M0 blended in the week's)
    "min_score": 0.0,                  # a score floor, as a fraction of 100
    "sector_cap": 4,
}
RESULTS = {
    "quality_gate": True,              # the result must be real growth (below)
    "rev_min": 8.0,                    # sales growth on a year ago, %
    "other_income_max": 35.0,          # other income as a % of profit before tax
    "exceptional_max": 0.30,           # an exceptional gain as a share of profit before tax
    "chase_max": 0.18,                 # a result-day rise past this is not chased
    "floor": "sma200_85",              # None | "sma200_85" (within 15% of the 200-day) | "sma50"
    "mix": {"reaction": 0.50, "volume": 0.25, "growth": 0.25},
    "accel_bonus": 0.10,               # added to growth when sales growth sped up
    "min_qualified": 8,                # fewer passing every test is no list
    "sector_cap": 4,
}
LONG = {
    "floors": True,                    # the return, cash and debt floors below
    "valuation_ceiling": True,         # the P/E ceiling below
    "pledge_max": 5.0,                 # % of the company promoters may have pledged
    "pledge_scale": 10.0,              # governance falls to nothing at a pledge this size
    "f_score_min": 5,
    "roce_min": 14.0,                  # return on capital employed, %, non-lenders
    "cfo_to_pat_min": 0.70,            # cash from operations over profit, non-lenders
    "de_max": 1.0,                     # debt over equity, non-lenders
    "roe_min_fin": 13.0,               # return on equity, %, lenders
    "pe_max": 90.0,                    # the P/E past which a stock is priced out ...
    "peg_escape": 1.5,                 # ... unless its PEG is this or under ...
    "cagr_escape": 35.0,               # ... on three-year profit growth of this or more
    "mix": {"quality": 0.30, "compounding": 0.25, "governance": 0.15,
            "valuation": 0.15, "trendq": 0.15},
    "min_score": 0.0,
    "sector_cap": 4,
}
# A part with nothing to read counts as the middle of the field.
NEUTRAL = 0.5
# A percentile against its own industry needs this many pool members with the
# figure; with fewer it is taken against every liquid stock.
INDUSTRY_PCT_MIN = 5
# The results list's floors. "sma200_85": a close more than 15% under the
# 200-day average is a stock still falling, whatever the day said.
RESULTS_SMA200_FLOOR = 0.85
# A table row filed more than this many days before a result reached the
# exchange is an earlier quarter, not the one the market just read.
RESULT_MATCH_DAYS = 3
# When companies report: seasons begin about the tenth of the month after a
# quarter ends, and run about fifty days (the March quarter has sixty).
RESULTS_SEASON_STARTS = ((1, 10), (4, 10), (7, 10), (10, 10))
RESULTS_SEASON_DAYS = 50

# The lists. Each spec carries how long a pick is held and where it is left
# (`exit_pct`, a close that far under the call price), what the page calls
# it, and `mix`, the weight on each part of its score. The three fundamental
# lists name their recipe dictionary in `recipe`; rank() reads that live, so
# a dictionary swapped by the lab is the one used. `gives_way_to` would name
# a list whose top LIST_SIZE this list leaves out (none does since December
# 2026: the three lists overlap little without it).
#
# `tested` is what each recipe did when replayed: research/ideas_study.py and
# research/fundamental_ideas_lab.py write it, research/IDEAS-STUDY.md
# explains it, and the page prints it only for the recipe it was measured on.
LISTS = {
    "month": {
        "label": "Swing / This month", "setup": "Month pick", "setup_key": "pick_month",
        "hold_sessions": 21, "hold_days": 30, "hold_text": "about a month", "exit_pct": 12.0,
        "mix": MONTH["mix"], "recipe": "MONTH",
        "idea": "Market leaders pulling back in industries money is moving into, with sales and margins growing.",
    },
    "results": {
        "label": "After results", "setup": "Results pick", "setup_key": "pick_results",
        "hold_sessions": 21, "hold_days": 30, "hold_text": "about a month", "exit_pct": 12.0,
        "mix": RESULTS["mix"], "recipe": "RESULTS", "event": "results",
        "idea": "Companies whose stock jumped on quarterly results that showed real growth.",
    },
    "long": {
        "label": "Long-term compounders", "setup": "Long-term pick", "setup_key": "pick_long",
        "hold_sessions": 252, "hold_days": 365, "hold_text": "about a year", "exit_pct": 30.0,
        "mix": LONG["mix"], "recipe": "LONG",
        "idea": "High returns on capital backed by cash, little debt, a steady climb and a price under the list's ceiling.",
    },
}
# The setup lists. Each was asked for by name and is built as a list of its
# own. research/setups_lab.py chose which version of each (November 2026),
# and research/setups_lab.py --v2 rebuilt breakouts, technicals, quick trades,
# money flow and emerging in December 2026: entries before a stock is
# extended, and holds long enough for the large winners that carry an
# average (research/setups-lab-v2.json). The record printed beside each is
# the engine's own, replayed, whatever it is.
LISTS.update({
    "breakout": {
        "label": "Breakouts", "setup": "Breakout", "setup_key": "pick_breakout", "kind": "setup",
        "hold_sessions": 63, "hold_days": 91, "hold_text": "about 3 months", "exit_pct": 12.0,
        "let_run": True, "mix": {"breakout": 1.0}, "calm_gate": False, "trend_gate": False,
        "idea": "A base that tightened, broken on heavy volume, before the stock is stretched.",
    },
    "technical": {
        "label": "Technicals", "setup": "Technical pick", "setup_key": "pick_technical", "kind": "setup",
        "hold_sessions": 63, "hold_days": 91, "hold_text": "about 3 months", "exit_pct": 12.0,
        "let_run": True, "mix": {"technical": 1.0}, "calm_gate": False, "trend_gate": False,
        "idea": "Rising-trend leaders that pulled back to their 20-day average and turned up.",
    },
    "quick": {
        "label": "Swing dips", "setup": "Swing dip", "setup_key": "pick_quick", "kind": "setup",
        "hold_sessions": 21, "hold_days": 30, "hold_text": "about a month", "exit_pct": 10.0,
        "let_run": True, "mix": {"quick": 1.0}, "calm_gate": False, "trend_gate": True,
        "idea": "Market leaders sold off hard for a few days, still holding their 50-day average.",
    },
    "flow": {
        "label": "Money flow", "setup": "Money-flow pick", "setup_key": "pick_flow", "kind": "setup",
        "hold_sessions": 63, "hold_days": 91, "hold_text": "about 3 months", "exit_pct": 15.0,
        "let_run": True, "mix": {"flow": 1.0}, "calm_gate": True, "trend_gate": True,
        "idea": "The strongest stocks in the three sectors money is rotating into.",
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
        "hold_sessions": 90, "hold_days": 130, "hold_text": "about 4 months", "exit_pct": 15.0,
        "sell_rule": "sma50", "trail_after": 15,
        "let_run": True, "mix": {"emerging": 1.0}, "calm_gate": False, "trend_gate": False,
        "idea": "Companies listed six to eighteen months, near their highs and ahead of the market.",
    },
})
ORDER = ("month", "results", "long")
SETUPS = ("short", "breakout", "technical", "quick", "flow", "emerging")
# The two the Ideas page shows. The rest are still ranked and still answer by name.
PRIMARY = ("short", "long")
ALL = ORDER + SETUPS
SETUP_KEYS = {v["setup_key"]: k for k, v in LISTS.items()}
# Older links, the old two-way switch and the two lists folded into the
# fundamental ones (December 2026) still ask for these. Each opens the list
# that took its place, so an old link never lands on an error.
ALIASES = {"medium": "long", "invest": "long",
           "week": "month", "trade": "month",
           "momentum": "long", "position": "long"}

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


def recipe_of(key):
    """The live recipe dictionary (MONTH, RESULTS or LONG) of one of the three
    fundamental lists, or None for any other list. Looked up at call time, so
    a dictionary the lab swapped in is the one read."""
    name = (LISTS.get(key) or {}).get("recipe")
    return globals().get(name) if name else None


def mix_of(key):
    """The weights a list's score is made of, as the engine uses them now."""
    cfg = recipe_of(key)
    if cfg is not None:
        return dict(cfg.get("mix") or {})
    return dict((LISTS.get(key) or {}).get("mix") or {})


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

    days = _recent_days(frame, c)
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
        "days": days,
        # Each of those sessions' volume beside the median of the twenty
        # before it, so the results list can say how heavily a result traded.
        "day_vols": _recent_vols(frame, days),
        # The last SECTOR_PATH daily moves and the date of the last, so
        # sector_flow() can chain an industry's own index (sector breakout).
        "path": [round(float(x), 5) for x in (c[-SECTOR_PATH:] / c[-SECTOR_PATH - 1:-1] - 1.0)],
        "path_end": _last_day(frame),
    }


# The short-term list's base (research/short_term_lab.py chose it), and the
# window every breakout is listed in.
BOX_SESSIONS = 40          # how long the base is
BOX_MAX_WIDTH = 0.18       # high over low of the base, less one
BOX_MIN_VOLUME = 2.0       # the breakout session's volume against its usual
BOX_LOOKBACK = 5           # how many sessions back a breakout is still listed
BOX_LEADER_FLOOR = 0.50
# The nine chart conditions the short-term list counts (it needs six).
SCORECARD_LABELS = (
    "Above its 20-day average", "20-day average above the 50-day", "50-day average above the 200-day",
    "RSI over 55", "MACD above its signal line", "ADX at 25 or more, buyers ahead",
    "More volume on up days", "Volume above its usual this week", "Within 5% of its 52-week high")
FLOW_SECTORS = 3           # the sectors money is rotating into
FLOW_PER_SECTOR = 5        # and the strongest stocks taken from each
FLOW_MIN_MEMBERS = 8       # a sector needs this many liquid stocks to be ranked
SHORT_SCORECARD = 6        # chart conditions the short-term list needs, of nine
SHORT_SECTOR_FLOOR = 50.0  # its industry in the top half on money flow
SHORT_BAD_REACTION = -0.02 # results the market sold this hard are a no
VERGE_PCT = 3.0            # how near the top of its base counts as on the verge

# The setup lists as rebuilt in December 2026 (research/setups_lab.py --v2,
# where each value below was declared before the run). Breakouts: two
# patterns, A and B (see _launches), and the screens both share.
#
# LAUNCH_PATTERNS says which pattern the list picks from. The lab's rule,
# set before the run, took the best 2017-2021 lead over the Nifty 500 among
# the new versions, and that was pattern A alone (a lead of 2.2 points a
# pick, 1.4 on 2022-2026), ahead of A or B (1.6, 1.2) and B alone (0.5,
# 1.8). B is still measured on every stock, shown on the watch list, and is
# one edit away: ("A", "B"), then a replay (ideas_study.py --setups).
LAUNCH_PATTERNS = ("A",)
LAUNCH_A_WIDTH = 0.28      # the base, high over low, less one
LAUNCH_A_TIGHT = 0.20      # a base this tight needs no further sign of tightening
LAUNCH_A_SQUEEZE = 0.90    # ... otherwise one of these, read on the bars before the break
LAUNCH_A_RANGE = 0.55
LAUNCH_A_DRY = 0.95
LAUNCH_A_VOLUME = 1.6
LAUNCH_A_LEADER = 0.45     # pattern A's leader floor
LAUNCH_A_SECTOR_TOP = 0.60 # its industry in the top 60% on money flow, where it has one
LAUNCH_B_WIDTH = 0.35
LAUNCH_B_RANGE = 0.65
LAUNCH_B_SQUEEZE = 0.95
LAUNCH_B_VOLUME = 2.0
LAUNCH_B_CLV = 0.60
LAUNCH_B_QUIET = 20        # sessions without a 60-session high before the break
LAUNCH_CLV = 0.55          # the breakout close in the top 45% of its day's range
CHASE_EXT50 = 16.0         # % above the 50-day average past which a stock is not bought
CHASE_RET3M = 0.55         # nor one that rose more than this in three months
BAD_PROFIT_PCT = -10.0     # a known fall in quarterly profit worse than this is a no
BAD_REACTION = -0.02       # results sold this hard (against the market) are a no
# Technicals: an early Stage-2 pullback to the 20-day average.
PULL_LEADER = 0.55
PULL_TOUCH = 1.015         # a low within 1.5% of the 20-day average in the last 3 sessions
PULL_EXT_MAX = 6.0         # and the close no more than 6% above it now
PULL_RSI = (48.0, 68.0)
PULL_SECTOR_TOP = 0.50
# Quick trades: a leader's swing dip.
DIP_LEADER = 0.65
DIP_RSI2 = 10.0
DIP_DROP5 = -0.04
DIP_SMA50_FLOOR = 0.97
# Money flow: the top sectors on rotation, and non-extended leaders in each.
ROTATION_WEIGHTS = {"month3": 0.45, "breadth": 0.35, "shift": 0.20}
FLOW_NEAR_HIGH = 0.85
# The anti-chasing screen was measured on money flow too, and the version
# without it led by more on 2017-2021 (2.6 points a pick against 2.4), so
# the rule took that one. Kept, switched off.
FLOW_ANTI_CHASE = False
FLOW_EXT50 = 16.0
FLOW_RET3M = 0.50
# Emerging: listed six to eighteen months, in a Stage-2 advance.
EMERGING_MIN_SESSIONS = 127
EMERGING_MAX_SESSIONS = 380
EMERGING_NEAR_HIGH = 0.90
EMERGING_LEADER = 0.60
EMERGING_EXT50 = 18.0

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

    # ---- what the December 2026 setup lists read ---------------------------
    has_open = "Open" in frame.columns
    o = np.asarray(frame["Open"], dtype=float) if has_open else None
    if o is not None and np.isfinite(o[-1]) and o[-1] > 0:
        out["closed_up"] = bool(price > o[-1])            # a green candle
    else:
        out["closed_up"] = bool(price > c[-2])            # no open in the feed: up on the day
    spread = h[-1] - low[-1]
    out["clv"] = float((price - low[-1]) / spread) if spread > 0 else None
    out["ema20"] = float(ema20[-1])
    out["ema10"] = float(_ema(c, 10)[-1])
    out["ext_20d_pct"] = float((price / ema20[-1] - 1) * 100)
    out["ext_50d_pct"] = float((price / sma50 - 1) * 100)
    out["low3_vs_ema20"] = float(low[-3:].min() / ema20[-1])
    out["sma50_rising"] = bool(sma50 > float(c[-60:-10].mean()))
    out["sma200_rising"] = (bool(sma200 > float(c[-220:-20].mean())) if n >= 220 else None)
    out["launch"] = _launches(c, h, low, v, lr, has_vol)
    out["watch"] = _launch_watch(c, h, low, v, lr, has_vol, out)
    return out


def _sma(c, t, w):
    """The w-session average of closes ending at bar t, or None."""
    return float(c[t - w + 1:t + 1].mean()) if t - w + 1 >= 0 else None


def _pre(c, h, low, v, lr, t, has_vol):
    """How the base looked on the bars BEFORE bar t: squeeze (10- over
    60-session volatility), range_15_60 and dry_up, as research/signals_lab.py
    defines them. Low numbers mean the base tightened."""
    a, b = lr[max(0, t - 11):t - 1], lr[max(0, t - 61):t - 1]
    squeeze = float(a.std(ddof=1) / b.std(ddof=1)) if len(a) >= 8 and len(b) >= 50 and b.std(ddof=1) > 0 else None
    r60 = float(h[max(0, t - 60):t].max() - low[max(0, t - 60):t].min())
    rng = float((h[t - 15:t].max() - low[t - 15:t].min()) / r60) if r60 > 0 and t >= 15 else None
    dry = None
    if has_vol and t >= 50:
        m50 = float(v[t - 50:t].mean())
        dry = float(v[t - 10:t].mean() / m50) if m50 > 0 else None
    return squeeze, rng, dry


def _le(x, limit):
    return x is not None and x <= limit


def _launches(c, h, low, v, lr, has_vol):
    """
    The two breakout patterns, on each of the last BOX_LOOKBACK sessions.

    For each session t (k sessions ago) it says which pattern's chart tests
    the close at t passed, measured with bars up to t only:

      A  VCP launchpad. A close above the top of the last 40 (or 60)
         sessions, that base 28% wide or less and either 20% or tighter or
         tightening before the break (squeeze, the last fortnight's range or
         volume drying up); 1.6 times the usual volume; a close in the top
         45% of the day's range; above the 200-day average, with the 50-day
         at least 98% of it.
      B  Base turnaround. The first close above the 60-session top after 20
         sessions without one, from a base 35% wide or less that tightened;
         twice the usual volume; a close in the top 40% of the day's range;
         above the 200- and 50-day averages, the 50-day rising.

    The leader, sector and quarterly screens are rank()'s: they need the
    whole market. Oldest first, so the earliest breakout in the window wins.
    """
    n = len(c)
    out = []
    for k in range(BOX_LOOKBACK - 1, -1, -1):
        t = n - 1 - k
        if t - 81 < 0:
            continue
        s200, s50 = _sma(c, t, 200), _sma(c, t, 50)
        if s200 is None or s50 is None:
            continue
        before = v[max(0, t - 50):t]
        med = float(np.median(before)) if len(before) >= 40 else 0.0
        rel = float(v[t] / med) if med > 0 else 0.0
        spread = h[t] - low[t]
        clv = float((c[t] - low[t]) / spread) if spread > 0 else 0.0
        squeeze, rng, dry = _pre(c, h, low, v, lr, t, has_vol)
        bases = {}
        for w in (40, 60):
            top, bot = float(h[t - w:t].max()), float(low[t - w:t].min())
            bases[w] = (top, bot, (top - bot) / bot if bot > 0 else 9.9)
        a = None
        if c[t] > s200 and s50 >= s200 * 0.98 and rel >= LAUNCH_A_VOLUME and clv >= LAUNCH_CLV:
            tight = _le(squeeze, LAUNCH_A_SQUEEZE) or _le(rng, LAUNCH_A_RANGE) or _le(dry, LAUNCH_A_DRY)
            for w in (40, 60):
                top, bot, width = bases[w]
                if c[t] > top and width <= LAUNCH_A_WIDTH and (width <= LAUNCH_A_TIGHT or tight):
                    a = {"base": w, "top": top, "low": bot, "width": width}
                    break
        b = None
        top, bot, width = bases[60]
        s50_then = _sma(c, t - 10, 50)
        if (c[t] > top and width <= LAUNCH_B_WIDTH and rel >= LAUNCH_B_VOLUME and clv >= LAUNCH_B_CLV
                and c[t] > s200 and c[t] > s50 and s50_then is not None and s50 > s50_then
                and (_le(rng, LAUNCH_B_RANGE) or _le(squeeze, LAUNCH_B_SQUEEZE))):
            quiet = all(c[s] <= h[s - 60:s].max() for s in range(t - LAUNCH_B_QUIET, t))
            if quiet:
                b = {"base": 60, "top": top, "low": bot, "width": width}
        if a or b:
            out.append({"sessions_ago": int(k), "a": a, "b": b, "rel_volume": rel, "clv": clv,
                        "close": float(c[t]), "squeeze": squeeze, "range_15_60": rng, "dry_up": dry})
    return out


def _launch_watch(c, h, low, v, lr, has_vol, t_out):
    """A base that would be a launch on a close above its top: the same
    chart tests as _launches, read today, the price within VERGE_PCT of the
    top of the base. Nearest pattern first: A, then B."""
    n = len(c)
    t = n          # the bars before a breakout tomorrow are every bar up to today
    price = float(c[-1])
    s200, s50 = _sma(c, n - 1, 200), _sma(c, n - 1, 50)
    s50_then = _sma(c, n - 11, 50)
    if s200 is None or s50 is None or price <= s200:
        return None
    squeeze, rng, dry = _pre(c, h, low, v, lr, t, has_vol)
    for w in (40, 60):
        top, bot = float(h[n - w:].max()), float(low[n - w:].min())
        if bot <= 0 or price > top:
            continue
        width, to_top = (top - bot) / bot, top / price - 1
        if to_top * 100 > VERGE_PCT:
            continue
        tight = _le(squeeze, LAUNCH_A_SQUEEZE) or _le(rng, LAUNCH_A_RANGE) or _le(dry, LAUNCH_A_DRY)
        if s50 >= s200 * 0.98 and width <= LAUNCH_A_WIDTH and (width <= LAUNCH_A_TIGHT or tight):
            return {"pattern": "VCP launchpad", "base": w, "top": top, "low": bot, "width": width, "to_top": to_top}
        if (w == 60 and width <= LAUNCH_B_WIDTH and price > s50 and s50_then is not None and s50 > s50_then
                and (_le(rng, LAUNCH_B_RANGE) or _le(squeeze, LAUNCH_B_SQUEEZE))
                and all(c[s] <= h[s - 60:s].max() for s in range(n - LAUNCH_B_QUIET, n))):
            return {"pattern": "Base turnaround", "base": w, "top": top, "low": bot, "width": width, "to_top": to_top}
    return None


def _last_day(frame):
    """The ISO date of a frame's last bar, or None for an undated frame."""
    try:
        d = frame.index[-1]
        d = d.date().isoformat() if hasattr(d, "date") else str(d)[:10]
        return d if len(d) == 10 and d[4] == "-" else None
    except Exception:
        return None


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


def _recent_vols(frame, days):
    """
    Beside each of `days`: (ISO date, that session's volume, the median volume
    of the VOLUME_BASE_SESSIONS sessions before it), oldest first. A volume
    the feed did not carry is None, and so is a median with fewer than
    VOLUME_BASE_MIN volumes behind it. None for an undated frame, as `days`.
    The date strings are the ones `days` holds, so they cost nothing twice.
    """
    if not days:
        return None
    if "Volume" not in frame.columns:
        return [(d, None, None) for d, _m in days]
    v = np.asarray(frame["Volume"], dtype=float)
    n, out = len(v), []
    for k, (d, _m) in enumerate(days):
        t = n - len(days) + k
        before = v[max(0, t - VOLUME_BASE_SESSIONS):t]
        before = before[np.isfinite(before)]
        med = float(np.median(before)) if len(before) >= VOLUME_BASE_MIN else None
        vol = float(v[t]) if t >= 0 and np.isfinite(v[t]) else None
        out.append((d, vol, med))
    return out


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
    if key == "breakout" and (ev or {}).get("launch"):
        L, pattern = ev["launch"], ev["pattern"]
        base = L["a"] if pattern == "VCP launchpad" else L["b"]
        ago = L["sessions_ago"]
        out.append(pattern)
        out.append("Broke out today" if ago == 0 else
                   ("Broke out yesterday" if ago == 1 else f"Broke out {ago} sessions ago"))
        if _finite(L.get("rel_volume")) is not None:
            out.append(f"On {L['rel_volume']:.1f}\u00d7 its usual volume")
        out.append(f"{base['base']} sessions inside a {base['width'] * 100:.0f}% range")
        return out[:4]
    if key == "technical" and _finite(t.get("ext_20d_pct")) is not None and ev is not None:
        out.append("Pulled back to its 20-day average")
        out.append(f"Now {t['ext_20d_pct']:.1f}% above it")
        if _finite(t.get("rsi")) is not None:
            out.append(f"RSI {t['rsi']:.0f}")
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
    if key == "quick" and _finite(t.get("rsi2")) is not None:
        out.append(f"Two-day RSI {t['rsi2']:.0f}")
        r5q = sig.get("ret_5d")
        if r5q is not None and r5q <= -0.01:
            out.append(f"Fell {abs(r5q) * 100:.0f}% this week")
    if key == "emerging" and ev and ev.get("listed"):
        out.append(f"Listed {max(6, round(ev['listed'] / 21))} months")
        r3e = sig.get("ret_3m")
        if r3e is not None:
            out.append(f"{'Up' if r3e >= 0 else 'Down'} {abs(r3e) * 100:.0f}% in three months")
        nh = sig.get("near_high")
        if nh is not None:
            gap = (1 - nh) * 100
            out.append("At its 52-week high" if gap < 1 else f"{gap:.0f}% below its 52-week high")
        return out[:4]
    if key == "flow" and ev and ev.get("sector"):
        out.append(f"{ev['sector']}: money moving in")
        out.append(f"Sector ranked {ev['rank']} of {ev['of']}")
        r3f = sig.get("ret_3m")
        if r3f is not None:
            out.append(f"{'Up' if r3f >= 0 else 'Down'} {abs(r3f) * 100:.0f}% in three months")
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


def result_reactions(pool, results, window=RESULTS_WINDOW):
    """
    How each stock moved on the session its results were first priced in.

    `pool` is [(SYMBOL, signals)] for the liquid universe; `results` maps a
    symbol to at least {"filed_at": when the filing reached the exchange}.
    The session is the first one whose close came after the filing. The move
    is the stock's close-to-close change that session, less the average
    liquid stock's the same day. Only results priced in the last `window`
    sessions are returned (RESULTS_WINDOW for the results list: an older one
    is no longer news; the month list looks back a month for results the
    market sold).

    Each event also carries `vol_x`, that session's volume over the median of
    the twenty before it (None when unknown), and where the stock stands now:
    `sma200_ratio` (price over its 200-day average) and `above_sma50`.
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
    window = set(sessions[-max(1, int(window)):])
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
        vol, usual = next(((v, m) for d, v, m in (g.get("day_vols") or ()) if d == d0), (None, None))
        vol, usual = _finite(vol), _finite(usual)
        price, s200, s50 = _finite(g.get("price")), _finite(g.get("sma200")), _finite(g.get("sma50"))
        out[sym] = {
            "filed_at": str(r.get("filed_at"))[:19], "session": d0,
            "sessions_ago": len(sessions) - 1 - k,
            "move": float(move), "market_move": market, "reaction": float(move - market),
            "quarter": r.get("quarter"),
            "pat_yoy_pct": _finite(r.get("pat_yoy_pct")),
            "revenue_yoy_pct": _finite(r.get("revenue_yoy_pct")),
            "vol_x": (vol / usual) if (vol is not None and usual and usual > 0) else None,
            "sma200_ratio": (price / s200) if (price is not None and s200 and s200 > 0) else None,
            "above_sma50": (bool(price > s50) if (price is not None and s50 is not None) else None),
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
        # December 2026: what the rebuilt setup lists read.
        "ext_50d_pct": r(t.get("ext_50d_pct"), 1), "ext_20d_pct": r(t.get("ext_20d_pct"), 1),
        "ema20": r(t.get("ema20")), "clv": r(t.get("clv")),
        "sma50_rising": t.get("sma50_rising"), "sma200_rising": t.get("sma200_rising"),
        "closed_up": t.get("closed_up"),
        "launch": [{"sessions_ago": L["sessions_ago"], "rel_volume": r(L.get("rel_volume"), 1),
                    "close": r(L.get("close")), "clv": r(L.get("clv")),
                    "a": (None if not L.get("a") else {"base": L["a"]["base"], "top": r(L["a"]["top"]),
                                                        "low": r(L["a"]["low"]),
                                                        "width_pct": r(L["a"]["width"] * 100, 1)}),
                    "b": (None if not L.get("b") else {"base": L["b"]["base"], "top": r(L["b"]["top"]),
                                                        "low": r(L["b"]["low"]),
                                                        "width_pct": r(L["b"]["width"] * 100, 1)})}
                   for L in (t.get("launch") or [])],
        "watch": (None if not t.get("watch") else {
            "pattern": t["watch"]["pattern"], "base": t["watch"]["base"], "top": r(t["watch"]["top"]),
            "low": r(t["watch"]["low"]), "width_pct": r(t["watch"]["width"] * 100, 1),
            "to_top_pct": r(t["watch"]["to_top"] * 100, 1)}),
    }


def _sector_breakout(paths):
    """An industry's own index from its stocks' last SECTOR_PATH daily moves
    (their mean, chained): whether it made a new 60-session closing high in
    the last 10 sessions, whether it is within 3% of that high, and how far
    under the high it is. Unknown (None) with fewer than FLOW_MIN_MEMBERS."""
    paths = [p for p in paths if p]
    if len(paths) < FLOW_MIN_MEMBERS:
        return {"breakout": None, "near_high": None, "from_high_pct": None}
    moves = np.mean(np.asarray(paths, dtype=float), axis=0)
    level = np.cumprod(1.0 + moves)
    n = len(level)
    new_high = any(level[k] >= level[k - SECTOR_HIGH_WINDOW + 1:k + 1].max()
                   for k in range(max(SECTOR_HIGH_WINDOW - 1, n - SECTOR_RECENT), n))
    top = float(level[-SECTOR_HIGH_WINDOW:].max())
    return {"breakout": bool(new_high), "near_high": bool(level[-1] >= SECTOR_NEAR * top),
            "from_high_pct": round(float((1 - level[-1] / top) * 100), 1)}


def sector_flow(pool, sectors):
    """
    Where money is moving: every sector with enough liquid stocks, ranked.

    `pool` is [(SYMBOL, signals)] for the established universe; `sectors`
    maps a symbol to its sector. Four measurements, each turned into a rank
    among the sectors:

      shift    the sector's share of all rupee turnover this week, over its
               share across the last sixty sessions (above 1: money moving in)
      breadth  the share of its stocks above their own 50-day average
      month    the median move of its stocks over the last 21 sessions
      month3   the median move of its stocks over the last 63 sessions

    and, beside the rank, whether the industry is breaking out: its own
    index (the mean daily move of its stocks, chained) at a new 60-session
    high in the last 10 sessions (`breakout`), within 3% of it
    (`near_high`), and how far under it (`from_high_pct`).

    Since December 2026 the sectors are ordered on rotation: 45% the
    three-month median, 35% breadth, 20% the turnover shift
    (ROTATION_WEIGHTS), which research/setups_lab.py --v2 measured. A month
    is too short for a sector's turn to show. The earlier score (shift,
    breadth and month, equally) is kept as `classic_score` and
    `classic_rank`: the short-term list was tested on it and still reads it.

    Returns the sectors best first, each with its figures, its score and its
    rank. Empty when no sector list was given.
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

    def median(xs):
        xs = sorted(xs)
        mid = len(xs) // 2
        return xs[mid] if len(xs) % 2 else (xs[mid - 1] + xs[mid]) / 2.0
    # The session most stocks' paths end on: a stock whose last bar is older
    # (halted, or a stale feed) is left out of its industry's index.
    ends = {}
    for _sym, g in pool:
        if g.get("path_end"):
            ends[g["path_end"]] = ends.get(g["path_end"], 0) + 1
    last = max(ends, key=lambda d: (ends[d], d)) if ends else None
    rows = []
    for sec, members in groups.items():
        if len(members) < FLOW_MIN_MEMBERS or tot5 <= 0 or tot60 <= 0:
            continue
        s5, s60 = sum(m[2] for m in members), sum(m[3] for m in members)
        brk = _sector_breakout([m[1].get("path") for m in members
                                if m[1].get("path_end") == last and len(m[1].get("path") or ()) == SECTOR_PATH])
        rows.append({
            "sector": sec, "stocks": len(members), **brk,
            "shift": (s5 / tot5) / (s60 / tot60) if s60 > 0 else None,
            "breadth": sum(1 for m in members if m[4]) / len(members),
            "month": median([_finite(m[1].get("ret_1m")) or 0.0 for m in members]),
            "month3": median([_finite(m[1].get("ret_3m")) or 0.0 for m in members]),
        })
    if not rows:
        return []
    ranks = {k: _pct_ranks([r[k] for r in rows]) for k in ("shift", "breadth", "month", "month3")}
    for i, r in enumerate(rows):
        parts = [ranks[k][i] for k in ("shift", "breadth", "month") if ranks[k][i] is not None]
        r["classic_score"] = sum(parts) / len(parts) if parts else 0.0
        got = {k: ranks[k][i] for k in ROTATION_WEIGHTS if ranks[k][i] is not None}
        w = sum(ROTATION_WEIGHTS[k] for k in got)
        r["score"] = sum(ROTATION_WEIGHTS[k] * x for k, x in got.items()) / w if w else 0.0
    for n, r in enumerate(sorted(rows, key=lambda r: (-r["classic_score"], r["sector"])), 1):
        r["classic_rank"] = n
    rows.sort(key=lambda r: (-r["score"], r["sector"]))
    for n, r in enumerate(rows, 1):
        r.update(rank=n, of=len(rows),
                 shift=None if r["shift"] is None else round(r["shift"], 3),
                 breadth_pct=round(r.pop("breadth") * 100, 1),
                 month_pct=round(r.pop("month") * 100, 1),
                 month3_pct=round(r.pop("month3") * 100, 1),
                 score=round(r["score"] * 100, 1), classic_score=round(r["classic_score"] * 100, 1))
    return rows


def _short(sym, g, part, sectors, flow_by, pat_yoy, growth, ev):
    """(score, why not or None, order) for the short-term list: a breakout
    from a tight base that is still holding, passed through five screens."""
    t = g.get("tech") or {}
    b = t.get("box")
    row = flow_by.get(sectors.get(sym))
    if row:
        # Tested on the three-part sector score of November 2026; it still reads it.
        row = dict(row, score=row.get("classic_score", row["score"]), rank=row.get("classic_rank", row["rank"]))
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


def _standing(row):
    """A sector's place from the top over the number ranked: 1/N is first,
    1.0 last. None when it was not ranked."""
    return row["rank"] / float(row["of"]) if row and row.get("of") else None


def _chasing(g, t):
    """Why a stock is too extended to buy now, or None (research/setups_lab.py
    --v2: buying more than 16% over the 50-day, or after 55% in three months,
    left little of the move)."""
    ext = _finite(t.get("ext_50d_pct"))
    if ext is not None and ext > CHASE_EXT50:
        return f"Already {ext:.0f}% above its 50-day average; the list buys {CHASE_EXT50:.0f}% or less."
    r3 = _finite(g.get("ret_3m"))
    if r3 is not None and r3 > CHASE_RET3M:
        return f"Up {r3 * 100:.0f}% in three months already; the list stops at {CHASE_RET3M * 100:.0f}%."
    return None


def _quarter_bad(fund, ev):
    """Why the last quarter rules a stock out, or None. A company with no
    filing on record is never refused for it."""
    p = _finite((fund or {}).get("pat_yoy_pct"))
    if p is not None and p < BAD_PROFIT_PCT:
        return f"Profit fell {abs(p):.0f}% on a year ago in its last quarter."
    if ev and _finite(ev.get("reaction")) is not None and ev["reaction"] < BAD_REACTION:
        return (f"Its results were sold: {ev['move'] * 100:+.1f}% the day they were priced, against "
                f"{ev['market_move'] * 100:+.1f}% for the average stock.")
    return None


def _launch(g, t, part, row, fund):
    """(the breakout that counts, its pattern, why none counts). The earliest
    breakout of the last five sessions that passes its pattern's screens and
    is still above the top of its base."""
    launches = t.get("launch") or []
    if not launches:
        return None, None, (f"No close above a 40- or 60-session base on heavy volume in the last "
                            f"{BOX_LOOKBACK} sessions.")
    stand = _standing(row)
    p, r = _finite((fund or {}).get("pat_yoy_pct")), _finite((fund or {}).get("revenue_yoy_pct"))
    known = [x for x in (p, r) if x is not None]
    growing = not known or any(x > 0 for x in known)
    why = None
    for L in launches:
        a = L.get("a") if "A" in LAUNCH_PATTERNS else None
        if a and part["leader"] < LAUNCH_A_LEADER:
            why, a = f"Its leader score is under the {LAUNCH_A_LEADER * 100:.0f}th percentile.", None
        if a and stand is not None and stand > LAUNCH_A_SECTOR_TOP:
            why, a = (f"Its industry, {row['sector']}, ranks {row['rank']} of {row['of']} on money flow: "
                      f"outside the top {LAUNCH_A_SECTOR_TOP * 100:.0f}%."), None
        b = L.get("b") if "B" in LAUNCH_PATTERNS else None
        if b and not growing:
            why, b = "A base turnaround needs sales or profit growing on a year ago; neither is.", None
        base = a or b
        if not base:
            continue
        if g["price"] < base["top"]:
            why = "It has closed back under the top of its base since breaking out."
            continue
        return L, ("VCP launchpad" if a else "Base turnaround"), None
    return None, None, why or "Its breakout did not pass the screens."


def _setup(key, sym, g, part, is_calm, ctx):
    """(score out of 100, why it is not on the list or None, the figure it is
    ordered on) for one stock on one of the setup lists. `ctx` carries what
    the whole market says: sectors and their flow, the benchmark, the last
    quarter and the results reaction."""
    t = g.get("tech") or {}
    leader = part["leader"]
    sectors, flow_by = ctx["sectors"], ctx["flow_by"]
    row = flow_by.get(sectors.get(sym))
    fund, ev, bench = ctx["fund"].get(sym), ctx["events"].get(sym), ctx["bench"]
    r1 = _finite(g.get("ret_1m"))
    if key == "breakout":
        L, pattern, why = _launch(g, t, part, row, fund)
        if L is None:
            return 0.0, why, -1.0
        vol = _finite(L.get("rel_volume")) or 0.0
        score = min(vol, 6.0) / 6.0 * 100.0
        why = None
        if r1 is None or r1 <= bench["ret_1m"]:
            why = (f"Its month ({(r1 or 0) * 100:+.1f}%) did not beat the market's "
                   f"({bench['ret_1m'] * 100:+.1f}%).")
        if not why and BREAKOUT_SECTOR_NEAR_HIGH and row and row.get("near_high") is False:
            why = (f"Its industry, {row['sector']}, is {row.get('from_high_pct')}% under its 60-session high: "
                   "the list wants the industry within 3% of it.")
        why = why or _chasing(g, t) or _quarter_bad(fund, ev)
        # The newest breakout first, then the heaviest volume.
        return score, why, (BOX_LOOKBACK - L["sessions_ago"]) * 10.0 + min(vol, 9.9)
    if key == "technical":
        if t.get("ema20") is None or t.get("rsi") is None:
            return 0.0, "Not enough history to read the chart.", -1.0
        ext = _finite(t.get("ext_20d_pct")) or 0.0
        rsi = t["rsi"]
        stand = _standing(row)
        score = max(0.0, min(100.0, (leader + (1 - (stand if stand is not None else 0.5))) / 2 * 100))
        why = None
        if not g["uptrend"]:
            why = "Not in an uptrend: price or its 50-day average is under the 200-day average."
        elif not t.get("sma200_rising"):
            why = "Its 200-day average is not rising."
        elif leader < PULL_LEADER:
            why = f"Its leader score is under the {PULL_LEADER * 100:.0f}th percentile."
        elif (_finite(t.get("low3_vs_ema20")) or 9) > PULL_TOUCH:
            why = "Has not pulled back to its 20-day average in the last three sessions."
        elif ext <= 0:
            why = "Closed under its 20-day average."
        elif ext > PULL_EXT_MAX:
            why = f"{ext:.1f}% above its 20-day average; the list buys {PULL_EXT_MAX:.0f}% or less."
        elif not t.get("closed_up"):
            why = "Did not close up on the day."
        elif not PULL_RSI[0] <= rsi <= PULL_RSI[1]:
            why = f"RSI is {rsi:.0f}; the list wants {PULL_RSI[0]:.0f} to {PULL_RSI[1]:.0f}."
        elif stand is not None and stand > PULL_SECTOR_TOP:
            why = (f"Its industry, {row['sector']}, ranks {row['rank']} of {row['of']} on money flow: "
                   "the bottom half.")
        else:
            p = _finite((fund or {}).get("pat_yoy_pct"))
            if p is not None and p < BAD_PROFIT_PCT:
                why = f"Profit fell {abs(p):.0f}% on a year ago in its last quarter."
        order = leader + (1 - (stand if stand is not None else 0.5)) + (ctx["updown"].get(sym) or 0.5)
        return score, why, order
    if key == "quick":
        r2 = _finite(t.get("rsi2"))
        if r2 is None:
            return 0.0, "Not enough history to read the chart.", -1.0
        r5 = _finite(g.get("ret_5d")) or 0.0
        why = None
        if not g["uptrend"]:
            why = "Not in an uptrend: price or its 50-day average is under the 200-day average."
        elif r2 >= DIP_RSI2 and r5 > DIP_DROP5:
            why = (f"Not sold off: two-day RSI {r2:.0f} (the setup is under {DIP_RSI2:.0f}) and "
                   f"{r5 * 100:+.1f}% this week (or {DIP_DROP5 * 100:.0f}% or worse).")
        elif leader < DIP_LEADER:
            why = f"Not a market leader: its leader score is under the top {100 - DIP_LEADER * 100:.0f}%."
        elif g["price"] < g["sma50"] * DIP_SMA50_FLOOR:
            why = "Fell more than 3% under its 50-day average: the support it was meant to hold."
        elif ev and _finite(ev.get("reaction")) is not None and ev["reaction"] < BAD_REACTION:
            why = "Sold off on its results: a different kind of fall."
        return max(0.0, (100.0 - r2)), why, -r2
    # Money flow.
    sec = sectors.get(sym)
    score = leader * 100.0
    flow_top, flow_pick = ctx["flow_top"], ctx["flow_pick"]
    if not sectors:
        return score, "No sector list was available for this scan.", -1.0
    if not sec:
        return score, "Not in NSE's sector list.", -1.0
    if sec not in flow_by:
        return score, f"Fewer than {FLOW_MIN_MEMBERS} liquid stocks in its sector to measure a flow on.", -1.0
    if sec not in flow_top:
        return score, (f"Its sector, {sec}, ranks {row['rank']} of {row['of']} on money flow; "
                       f"the list takes the top {FLOW_SECTORS}."), -1.0
    if sym not in flow_pick:
        return score, (ctx["flow_why"].get(sym) or f"Not among the {FLOW_PER_SECTOR} strongest in {sec}."), -1.0
    # Within the tested names, a stock the institutions are buying comes first
    # (live only: there is no history of these to test on, so they reorder the
    # names and never choose them).
    inst = _finite((ctx["institutional"].get(sym) or {}).get("accumulation"))
    return score, None, (FLOW_SECTORS - flow_top.index(sec)) * 10.0 + leader + (inst or 0.0) / 1000.0


def _emerging(sym, g, part, ctx, listed):
    """(score, why not, order) for the emerging list: a company listed six to
    eighteen months in a Stage-2 advance."""
    t = g.get("tech") or {}
    leader = part["leader"]
    bench = ctx["bench"]
    score = leader * 100.0
    fund = ctx["fund"].get(sym) or {}
    r1, r3 = _finite(g.get("ret_1m")), _finite(g.get("ret_3m"))
    ext = _finite(t.get("ext_50d_pct"))
    months = f"{EMERGING_MIN_SESSIONS // 21} to {EMERGING_MAX_SESSIONS // 21}"
    if listed is None or not EMERGING_MIN_SESSIONS <= listed <= EMERGING_MAX_SESSIONS:
        why = (f"Listed more than {EMERGING_MAX_SESSIONS // 21} months: this list is for companies listed "
               f"{months} months.")
    elif not t.get("above_50d"):
        why = "Under its own 50-day average."
    elif not t.get("sma50_rising"):
        why = "Its 50-day average is not rising."
    elif (g.get("near_high") or 0) < EMERGING_NEAR_HIGH:
        why = f"{(1 - (g.get('near_high') or 0)) * 100:.0f}% under its high; the list wants within 10%."
    elif leader < EMERGING_LEADER:
        why = f"Its leader score is under the {EMERGING_LEADER * 100:.0f}th percentile."
    elif r1 is None or r3 is None or r1 <= bench["ret_1m"] or r3 <= bench["ret_3m"]:
        why = "Has not beaten the market over both one month and three."
    elif ext is not None and ext > EMERGING_EXT50:
        why = f"Already {ext:.0f}% above its 50-day average; the list buys {EMERGING_EXT50:.0f}% or less."
    elif (_finite(fund.get("pat_cr")) or 0) < 0:
        why = "Made a loss in its last quarter."
    elif (_finite(fund.get("revenue_yoy_pct")) or 0) < 0:
        why = "Sales fell on a year ago in its last quarter."
    else:
        return score, None, leader
    return score, why, -1.0


# ---------------------------------------------------------------------------
# The three fundamental lists (December 2026): Swing / This month, After
# results, Long-term compounders. Each reads the company's snapshot (its
# filings, fund_snapshot.py) beside its chart, through MONTH, RESULTS and LONG.
# ---------------------------------------------------------------------------

# What each part of the three lists' scores is called on the page.
FACTOR_LABELS = {
    "pull": "Pullback over the last month and week",
    "high": "Closeness to the 52-week high",
    "fundmom": "Sales and margin growth last quarter",
    "secflow": "Its industry's money flow",
    "catalyst": "A live catalyst: deliveries or an order",
    "reaction": "Move on the day its results were priced",
    "volume": "Volume that day",
    "growth": "Growth in the quarter it reported",
    "quality": "Returns on capital, backed by cash",
    "compounding": "Growth over three years",
    "governance": "Pledges and who is buying",
    "valuation": "Price against its own industry",
    "trendq": "The year-long trend",
}
# The figures each block carries from the filings for the page.
FUNDAMENTALS_SHOWN = ("quarter", "revenue_yoy_pct", "opm_yoy_chg", "pat_yoy_pct", "earnings_quality_ok",
                      "roce_pct", "roe_pct", "cfo_to_pat", "fcf_pos_years_3y", "debt_equity_x", "pe", "peg",
                      "pledge_pct", "f_score", "is_financial", "sector_mf_quadrant")
WHY_MAX = 4                        # facts printed beside a pick
TOP_HALF_SCORE = 50.0              # an industry's money-flow score at or over this is the top half
FCF_YEARS = 3                      # the years free cash flow is counted over
F_SCORE_TOP = 9                    # Piotroski's scale
PROFIT_TEXT_MAX = 1000.0           # a growth figure past this is a near-zero base, not news
UPTREND_TEXT = "Not in an uptrend: price or its 50-day average is under the 200-day average."
VOLATILE_TEXT = "Among the most volatile fifth of liquid stocks."
BELOW_FLOOR_TEXT = "Ranks below the list's conviction floor."


def _num(x, dp=1):
    """A figure as the page prints it: at most `dp` decimals, no trailing zero."""
    s = f"{x:.{dp}f}"
    return s.rstrip("0").rstrip(".") if "." in s else s


def _pc(x):
    """A size in percent: whole numbers from ten up, one decimal under it."""
    return f"{x:.0f}" if abs(x) >= 10 else _num(x, 1)


def _two(x):
    """A ratio to two decimals at most: 0.7, 1.25."""
    return _num(x, 2)


def _whole(x):
    """A whole number: a P/E of 95."""
    return f"{x:.0f}"


def _vs(x, limit, fmt=_pc):
    """A figure printed beside the limit it missed, with as many decimals as
    it takes to differ from it: 13.6% against a floor of 14% is "13.6", not
    "14", which would read as passing."""
    text = fmt(x)
    for dp in (1, 2):
        if text != fmt(limit) or x == limit:
            break
        text = _num(x, dp)
    return text


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def _cap(text):
    """The first letter in capitals, the rest as written."""
    return text[:1].upper() + text[1:] if text else text


def _said(pairs):
    """The phrases whose figure is on file, joined: [(known, phrase)]."""
    return ", ".join(text for known, text in pairs if known)


def _fig(snap, key):
    """One figure of a snapshot as a finite float, or None when unknown."""
    return _finite((snap or {}).get(key))


def _figure_pct(values):
    """{SYMBOL: percentile} among the stocks that have the figure. A stock
    whose figure is None is left out, and reads as NEUTRAL where it is used."""
    have = sorted(s for s, v in values.items() if v is not None)
    return dict(zip(have, _pct_ranks([values[s] for s in have]))) if have else {}


def _industry_pct(values, industry):
    """As _figure_pct, but within each NSE industry that has at least
    INDUSTRY_PCT_MIN stocks with the figure, and against every stock for the
    rest: a cheap bank and a cheap software company are cheap on different
    scales."""
    out = _figure_pct(values)
    groups = {}
    for s, v in values.items():
        if v is not None and industry.get(s):
            groups.setdefault(industry[s], []).append(s)
    for members in groups.values():
        if len(members) >= INDUSTRY_PCT_MIN:
            out.update(_figure_pct({s: values[s] for s in members}))
    return out


def _snapshot_pcts(syms, snaps, sectors):
    """
    The filings' figures the month and long-term lists rank on, each as a
    percentile among the established stocks that have it. Lenders are kept
    out of the manufacturer's measures (return on capital, cash conversion,
    debt), and their return on equity is ranked among lenders when there are
    enough of them, else among every company that has one.
    """
    fin = {s: bool((snaps.get(s) or {}).get("is_financial")) for s in syms}

    def col(key, lenders=None, sign=1.0):
        out = {}
        for s in syms:
            if lenders is not None and fin[s] != lenders:
                continue
            v = _fig(snaps.get(s), key)
            out[s] = None if v is None else sign * v
        return out
    pct = {k: _figure_pct(col(k)) for k in ("revenue_yoy_pct", "opm_yoy_chg", "rev_cagr_3y", "pat_cagr_3y",
                                             "revenue_ttm_yoy_pct", "pat_ttm_yoy_pct", "opm_trend_2y")}
    pct["roce_pct"] = _figure_pct(col("roce_pct", lenders=False))
    pct["cfo_to_pat"] = _figure_pct(col("cfo_to_pat", lenders=False))
    pct["neg_de"] = _figure_pct(col("debt_equity_x", lenders=False, sign=-1.0))
    lenders = col("roe_pct", lenders=True)
    if sum(v is not None for v in lenders.values()) >= INDUSTRY_PCT_MIN:
        pct["roe_fin"] = _figure_pct(lenders)
    else:
        pct["roe_fin"] = {s: p for s, p in _figure_pct(col("roe_pct")).items() if fin[s]}
    pct["neg_peg"] = _industry_pct(col("peg", sign=-1.0), sectors)
    pct["neg_ev_ebitda"] = _industry_pct(col("ev_ebitda", lenders=False, sign=-1.0), sectors)
    return pct


def _breakdown(mix, values, details):
    """
    The weighted parts of a score: for each part of `mix` its weight, what it
    read (0-100), the points it adds and a line on what it measured. The
    points add up to the score, which is returned beside them (out of 100). A
    part weighted zero adds nothing and is left out; one with nothing to read
    is NEUTRAL.
    """
    rows, total = [], 0.0
    for k, w in (mix or {}).items():
        w = _finite(w) or 0.0
        if w <= 0:
            continue
        v = _finite(values.get(k))
        v = NEUTRAL if v is None else min(1.0, max(0.0, v))
        pts = w * v * 100.0
        total += pts
        rows.append({"factor": k, "label": FACTOR_LABELS.get(k, k), "weight": round(w, 4),
                     "value": round(v * 100.0, 1), "points": round(pts, 2), "detail": details.get(k) or ""})
    return rows, total


def _sold_text(ev):
    """A result the market sold, in the words the setup lists already use."""
    return (f"Its results were sold: {ev['move'] * 100:+.1f}% the day they were priced, against "
            f"{ev['market_move'] * 100:+.1f}% for the average stock.")


def _sales_margin(snap, margin="margin"):
    """The last quarter's growth in words, from what it filed: "Sales +28%,
    margin +3.4 pts", or either half alone, or None."""
    rev, opm = _fig(snap, "revenue_yoy_pct"), _fig(snap, "opm_yoy_chg")
    out = []
    if rev is not None and abs(rev) < PROFIT_TEXT_MAX:
        out.append(f"Sales {rev:+.0f}%")
    if opm is not None:
        out.append(f"{margin if out else margin.capitalize()} {opm:+.1f} pts")
    return ", ".join(out) or None


def _high_text(g):
    """Where the price stands against its 52-week high, in words, or None."""
    nh = _finite(g.get("near_high"))
    if nh is None:
        return None
    gap = (1 - nh) * 100
    return "At its 52-week high" if gap < 1 else f"{gap:.0f}% below its 52-week high"


def _catalyst(snap, cfg):
    """The month list's live catalyst in words, or None: deliveries that
    surged on a falling week (someone taking stock off sellers), or an order
    large against the company's value."""
    if (snap or {}).get("delivery_spike") is True:
        return "Heavy deliveries on a falling week"
    order = _fig(snap, "order_win_pct_mcap")
    if order is not None and order >= cfg["catalyst_order_pct"]:
        return f"An order worth {_pc(order)}% of its market value"
    return None


def _month(sym, g, part, is_calm, snap, ctx):
    """
    Swing / This month: a market leader in a strong industry that pulled
    back, with its last quarter growing. Returns {"score", "why_not",
    "exact", "breakdown", "why"}; the gates are checked in the order the page
    explains them, and the first that fails is the reason.
    """
    cfg = MONTH
    row = ctx["flow_by"].get(ctx["sectors"].get(sym))
    pct = ctx["snap_pct"]
    pull_mix = {k: w for k, w in (cfg.get("pull_mix") or {}).items() if (_finite(w) or 0) > 0}
    weight = sum(pull_mix.values())
    pull = sum(part.get(k, NEUTRAL) * w for k, w in pull_mix.items()) / weight if weight else NEUTRAL
    fund = _mean([pct["revenue_yoy_pct"].get(sym), pct["opm_yoy_chg"].get(sym)])
    catalyst = _catalyst(snap, cfg)
    values = {"pull": pull, "high": part["high"], "fundmom": fund,
              "secflow": (row["score"] / 100.0) if row else None,
              "catalyst": 1.0 if catalyst else NEUTRAL}
    r21, r5 = _finite(g.get("ret_1m")), _finite(g.get("ret_5d"))
    growth = _sales_margin(snap)
    details = {
        "pull": (f"{(r21 or 0) * 100:+.1f}% over the last month and {(r5 or 0) * 100:+.1f}% over the last "
                 "five sessions"),
        "high": _high_text(g) or "Its 52-week high is not known",
        "fundmom": ((_sales_margin(snap, "operating margin") + " on a year ago") if growth else
                    "No recent quarter on file: counted as the middle of the field"),
        "secflow": (f"{row['sector']} ranks {row['rank']} of {row['of']} industries on money flow" if row else
                    "Its industry could not be ranked on money flow: counted as the middle"),
        "catalyst": catalyst or "No delivery surge or large order on record: counted as the middle",
    }
    breakdown, score = _breakdown(cfg["mix"], values, details)

    floor = cfg["leader_floor"]
    pat, pat_yoy, pledge = _fig(snap, "pat_cr"), _fig(snap, "pat_yoy_pct"), _fig(snap, "pledge_pct")
    ev = ctx["events_month"].get(sym)
    why = None
    if not g["uptrend"]:
        why = UPTREND_TEXT
    elif not is_calm:
        why = VOLATILE_TEXT
    elif part["leader"] < floor:
        why = f"Not a market leader: its leader score is under the top {100 - floor * 100:.0f}% of liquid stocks."
    elif cfg["sector_gate"] and row is None:
        why = "Its industry could not be ranked on money flow."
    elif cfg["sector_gate"] and row["score"] < cfg["sector_floor"]:
        why = (f"Its industry, {row['sector']}, ranks {row['rank']} of {row['of']} on money flow: "
               + ("the bottom half." if cfg["sector_floor"] == TOP_HALF_SCORE else
                  f"under the list's floor of {cfg['sector_floor']:.0f}."))
    elif cfg["profit_guard"] and pat is not None and pat <= 0:
        why = "Made a loss in its last quarter."
    elif cfg["profit_guard"] and pat_yoy is not None and pat_yoy < 0:
        why = f"Profit fell {_pc(abs(pat_yoy))}% on a year ago in its last quarter."
    elif cfg["result_guard"] and ev and ev["reaction"] < cfg["bad_reaction"]:
        why = _sold_text(ev)
    elif pledge is not None and pledge > cfg["pledge_max"]:
        why = f"Promoters have pledged {_vs(pledge, cfg['pledge_max'])}% of the company."
    elif score < cfg["min_score"] * 100.0:
        why = BELOW_FLOOR_TEXT

    facts = []
    if r21 is not None and r21 <= -0.01:
        facts.append(f"Pulled back {abs(r21) * 100:.0f}% this month")
    elif r5 is not None and r5 <= -0.01:
        facts.append(f"Pulled back {abs(r5) * 100:.0f}% this week")
    if growth:
        facts.append(growth)
    if row:
        facts.append(f"{row['sector']}: top half on money flow" if row["score"] >= TOP_HALF_SCORE else
                     f"{row['sector']}: ranked {row['rank']} of {row['of']} on money flow")
    if _high_text(g):
        facts.append(_high_text(g))
    if catalyst:
        facts.append(catalyst)
    return {"score": score, "why_not": why, "exact": score, "breakdown": breakdown, "why": facts[:WHY_MAX]}


def _reported(ev, snap):
    """The snapshot, if its latest quarter is the one this result reported:
    the fundamentals tables can lag the exchange by a day, and judging a
    fresh result on the quarter before it would judge the wrong numbers.
    A snapshot or result with no filing time is taken as matching."""
    if not snap or not ev:
        return None
    filed, held = _parse_filed(ev.get("filed_at")), _parse_filed(snap.get("filed_at"))
    if filed and held and (filed - held).days > RESULT_MATCH_DAYS:
        return None
    q_ev, q_snap = ev.get("quarter"), snap.get("quarter")
    if q_ev and q_snap and str(q_ev).strip() != str(q_snap).strip():
        return None
    return snap


def _result_quality(q, cfg):
    """Why a reported quarter is not real growth, or None. Each test is made
    only where its figure is on file, except the profit itself: a result
    whose profit is unknown cannot be shown to be real. A lender's other
    income and cash flow are its business, so those two tests are for
    everyone else."""
    fin = bool((q or {}).get("is_financial"))
    rev = _fig(q, "revenue_yoy_pct")
    if rev is not None and rev < cfg["rev_min"]:
        if rev < 0:
            return f"Sales fell {_pc(abs(rev))}% on a year ago; the list needs {_pc(cfg['rev_min'])}% growth."
        return f"Sales grew {_vs(rev, cfg['rev_min'])}% on a year ago; the list needs {_pc(cfg['rev_min'])}%."
    pat = _fig(q, "pat_cr")
    if pat is None:
        return "The figures it reported are not in the fundamentals tables yet."
    if pat <= 0:
        return "Made a loss in the quarter it reported."
    pat_yoy = _fig(q, "pat_yoy_pct")
    if pat_yoy is not None and pat_yoy <= 0:
        return "Profit did not grow on a year ago."
    if not fin:
        core, ebitda_yoy = _fig(q, "core_ebitda_cr"), _fig(q, "ebitda_yoy_pct")
        if (core is not None and core <= 0) or (ebitda_yoy is not None and ebitda_yoy <= 0):
            return "Operating profit did not grow."
        oi = _fig(q, "other_income_share_pct")
        if oi is not None and oi > cfg["other_income_max"]:
            return (f"Other income was {_vs(oi, cfg['other_income_max'])}% of profit before tax: not the "
                    "business's own earnings.")
    exc, pbt = _fig(q, "exceptional_cr"), _fig(q, "pbt_cr")
    if exc is not None and pbt and pbt > 0 and exc > cfg["exceptional_max"] * pbt:
        return (f"An exceptional gain made up {_vs(exc / pbt * 100, cfg['exceptional_max'] * 100)}% of profit "
                "before tax.")
    cfo = _fig(q, "cfo_cr")
    if not fin and cfo is not None and cfo <= 0:
        return "Its last full year's operations used cash."
    return None


def _results_list(events, reaction, snapshot):
    """
    The After results list's entry for every company whose result was priced
    in the window: {SYMBOL: entry}, and how many passed every test. Ranked
    among those companies only, the comparison the study made. When fewer
    than RESULTS["min_qualified"] pass, there is no list this season.
    """
    cfg = RESULTS
    if not events or not reaction:
        return {}, 0
    reported = {s: _reported(events[s], snapshot.get(s)) for s in events}
    pct = {"volume": _figure_pct({s: _finite(events[s].get("vol_x")) for s in events}),
           "revenue_yoy_pct": _figure_pct({s: _fig(reported[s], "revenue_yoy_pct") for s in events}),
           "opm_yoy_chg": _figure_pct({s: _fig(reported[s], "opm_yoy_chg") for s in events})}
    out = {}
    for s, ev in events.items():
        q = reported[s]
        rev, prev = _fig(q, "revenue_yoy_pct"), _fig(q, "prev_revenue_yoy_pct")
        growth = _mean([pct["revenue_yoy_pct"].get(s), pct["opm_yoy_chg"].get(s)])
        faster = rev is not None and prev is not None and rev > prev
        if growth is not None and faster:
            growth = min(1.0, growth + cfg["accel_bonus"])
        values = {"reaction": reaction.get(s), "volume": pct["volume"].get(s), "growth": growth}
        vol_x, day = _finite(ev.get("vol_x")), _short_day(ev["session"])
        details = {
            "reaction": (f"{ev['move'] * 100:+.1f}% on {day}, the first session after its results reached the "
                         f"exchange; the average liquid stock moved {ev['market_move'] * 100:+.1f}%. Against the "
                         f"{len(events)} companies priced on results in the last {RESULTS_WINDOW} sessions"),
            "volume": (f"{vol_x:.1f} times its usual volume that day" if vol_x is not None else
                       "Its volume that day is not known: counted as the middle"),
            "growth": (((_sales_margin(q, "operating margin") or "") + " on a year ago"
                        + (", sales growing faster than the quarter before" if faster else ""))
                       if _sales_margin(q) else "Its quarter's growth is not on file: counted as the middle"),
        }
        breakdown, score = _breakdown(cfg["mix"], values, details)
        why = _result_quality(q, cfg) if cfg["quality_gate"] else None
        if why is None and ev["move"] > cfg["chase_max"]:
            why = (f"Already rose {_vs(ev['move'] * 100, cfg['chase_max'] * 100)}% the day results were priced: "
                   "the list does not chase.")
        if why is None and cfg["floor"] == "sma200_85":
            ratio = _finite(ev.get("sma200_ratio"))
            if ratio is not None and ratio < RESULTS_SMA200_FLOOR:
                why = f"More than {(1 - RESULTS_SMA200_FLOOR) * 100:.0f}% under its 200-day average."
        if why is None and cfg["floor"] == "sma50" and ev.get("above_sma50") is False:
            why = "Under its 50-day average."

        move = ev["move"] * 100
        filed_day = _short_day(ev["filed_at"])
        facts = [f"Results on {filed_day}: {'rose' if move >= 0 else 'fell'} {abs(move):.0f}% "
                 + ("that day" if filed_day == day else f"on {day}")]
        if vol_x is not None:
            facts.append(f"Volume {vol_x:.1f}\u00d7 usual")
        ebitda_yoy = _fig(q, "ebitda_yoy_pct")
        line = _said([(rev is not None and abs(rev or 0) < PROFIT_TEXT_MAX, f"Sales {rev or 0:+.0f}%"),
                      (ebitda_yoy is not None, "operating profit " + ("up" if (ebitda_yoy or 0) > 0 else "down"))])
        if line:
            facts.append(_cap(line))
        pat_yoy = _fig(q, "pat_yoy_pct")
        if pat_yoy is None:
            pat_yoy = _finite(ev.get("pat_yoy_pct"))
        if pat_yoy is not None and abs(pat_yoy) < PROFIT_TEXT_MAX:
            facts.append(f"Profit {'up' if pat_yoy >= 0 else 'down'} {abs(pat_yoy):.0f}% on a year ago")
        out[s] = {"score": score, "why_not": why, "exact": score, "breakdown": breakdown, "why": facts[:WHY_MAX]}
    passed = [s for s, e in out.items() if e["why_not"] is None]
    if len(passed) < cfg["min_qualified"]:
        for s in passed:
            out[s]["why_not"] = (f"Fewer than {cfg['min_qualified']} companies passed every test this "
                                 "results season.")
    return out, len(passed)


def _long_floor(snap, fin, cfg):
    """Why a company fails the long list's return, cash or debt floors, or
    None. A lender is judged on its return on equity alone: its debt is its
    stock in trade and its cash flow follows its lending."""
    if fin:
        roe = _fig(snap, "roe_pct")
        if roe is not None and roe < cfg["roe_min_fin"]:
            return f"Return on equity {_vs(roe, cfg['roe_min_fin'])}%: a lender needs {_pc(cfg['roe_min_fin'])}%."
        return None
    roce, cfo = _fig(snap, "roce_pct"), _fig(snap, "cfo_cr")
    c2p, de = _fig(snap, "cfo_to_pat"), _fig(snap, "debt_equity_x")
    if roce is not None and roce < cfg["roce_min"]:
        return f"Return on capital {_vs(roce, cfg['roce_min'])}%: the list needs {_pc(cfg['roce_min'])}%."
    if cfo is not None and cfo <= 0:
        return "Operations used cash last year."
    if c2p is not None and c2p < cfg["cfo_to_pat_min"]:
        return (f"Cash from operations was {_vs(c2p, cfg['cfo_to_pat_min'], _two)}\u00d7 profit: the list "
                f"needs {_two(cfg['cfo_to_pat_min'])}\u00d7.")
    if de is not None and de > cfg["de_max"]:
        return f"Debt is {_vs(de, cfg['de_max'], _num)}\u00d7 equity: the list allows {_num(cfg['de_max'])}\u00d7."
    return None


def _long(sym, g, part, is_calm, snap, ctx):
    """
    Long-term compounders: returns on capital backed by cash, growth over
    three years, clean governance and a fair price, in a calm climb. Returns
    {"score", "why_not", "exact", "breakdown", "why"}.
    """
    cfg = LONG
    pct = ctx["snap_pct"]
    fin = bool((snap or {}).get("is_financial"))
    fpos = _fig(snap, "fcf_pos_years_3y")
    if fin:
        quality = pct["roe_fin"].get(sym)
    else:
        quality = _mean([pct["roce_pct"].get(sym), pct["cfo_to_pat"].get(sym),
                         None if fpos is None else fpos / FCF_YEARS, pct["neg_de"].get(sym)])
    compounding = _mean([pct[k].get(sym) for k in ("rev_cagr_3y", "pat_cagr_3y", "revenue_ttm_yoy_pct",
                                                    "pat_ttm_yoy_pct", "opm_trend_2y")])
    pledge, pchg, inst = _fig(snap, "pledge_pct"), _fig(snap, "promoter_chg_4q"), _fig(snap, "fii_dii_chg_1q")
    governance = _mean([None if pledge is None else
                        (1.0 if pledge == 0 else max(0.0, 1.0 - pledge / cfg["pledge_scale"])),
                        None if pchg is None else (1.0 if pchg >= 0 else 0.0),
                        None if inst is None else (1.0 if inst >= 0 else 0.0)])
    valuation = _mean([pct["neg_peg"].get(sym)] + ([] if fin else [pct["neg_ev_ebitda"].get(sym)]))
    trendq = (part["m12"] + part["high"] + part["trend"]) / 3.0
    values = {"quality": quality, "compounding": compounding, "governance": governance,
              "valuation": valuation, "trendq": trendq}

    roce, roe, c2p, de = (_fig(snap, k) for k in ("roce_pct", "roe_pct", "cfo_to_pat", "debt_equity_x"))
    rev3, pat3 = _fig(snap, "rev_cagr_3y"), _fig(snap, "pat_cagr_3y")
    pe, peg, ev_e = _fig(snap, "pe"), _fig(snap, "peg"), _fig(snap, "ev_ebitda")
    eps, f = _fig(snap, "eps_ttm"), _fig(snap, "f_score")

    q_line = (_said([(roe is not None, f"return on equity {_pc(roe or 0)}%")]) if fin else
              _said([(roce is not None, f"return on capital {_pc(roce or 0)}%"),
                     (c2p is not None, f"cash from operations {_num(c2p or 0)}\u00d7 profit"),
                     (fpos is not None, f"free cash flow in {fpos or 0:.0f} of the last {FCF_YEARS} years"),
                     (de is not None, f"debt {_num(de or 0)}\u00d7 equity")]))
    c_line = _said([(rev3 is not None, f"sales {rev3 or 0:+.0f}% a year"),
                    (pat3 is not None, f"profit {pat3 or 0:+.0f}% a year over three years")])
    g_line = _said([(pledge is not None, "no shares pledged" if pledge == 0 else f"{_pc(pledge or 0)}% pledged"),
                    (pchg is not None, f"promoters {pchg or 0:+.1f} pts over the year"),
                    (inst is not None, f"institutions {inst or 0:+.1f} pts over the quarter")])
    v_line = _said([(pe is not None, f"P/E {pe or 0:.0f}"), (peg is not None, f"PEG {_num(peg or 0, 2)}"),
                    (ev_e is not None, f"EV/EBITDA {ev_e or 0:.0f}")])
    r12 = _finite(g.get("ret_12m"))
    t_line = _said([(r12 is not None, f"{(r12 or 0) * 100:+.0f}% over 12 months"),
                    (_high_text(g) is not None, (_high_text(g) or "").lower()),
                    (_finite(g.get("trend")) is not None, f"straightness {_finite(g.get('trend')) or 0:.0f}/100")])
    details = {
        "quality": _cap(q_line) or "Not on file: counted as the middle of the field",
        "compounding": _cap(c_line) or "No three-year record on file: counted as the middle",
        "governance": _cap(g_line) or "Pledges and holdings are not on file: counted as the middle",
        "valuation": (v_line + ", against its own industry") if v_line else
                     "No valuation on file: counted as the middle",
        "trendq": _cap(t_line) or "Its year is not on record",
    }
    breakdown, score = _breakdown(cfg["mix"], values, details)

    floor_why = _long_floor(snap, fin, cfg) if cfg["floors"] else None
    priced_out = (cfg["valuation_ceiling"] and pe is not None and pe > cfg["pe_max"]
                  and not (peg is not None and peg <= cfg["peg_escape"]
                           and pat3 is not None and pat3 >= cfg["cagr_escape"]))
    why = None
    if not g["price"] > g["sma200"]:
        why = "Under its 200-day average."
    elif not is_calm:
        why = VOLATILE_TEXT
    elif eps is not None and eps <= 0:
        why = "Lost money over the last four quarters."
    elif f is not None and f < cfg["f_score_min"]:
        why = f"F-score {f:.0f} of {F_SCORE_TOP}: the list needs {cfg['f_score_min']:.0f}."
    elif pledge is not None and pledge > cfg["pledge_max"]:
        why = f"Promoters have pledged {_vs(pledge, cfg['pledge_max'])}% of the company."
    elif floor_why:
        why = floor_why
    elif priced_out:
        why = f"P/E of {_vs(pe, cfg['pe_max'], _whole)}: priced past the list's ceiling of {cfg['pe_max']:.0f}."
    elif score < cfg["min_score"] * 100.0:
        why = BELOW_FLOOR_TEXT

    facts = []
    if fin and roe is not None:
        facts.append(f"ROE {_pc(roe)}%")
    elif not fin and (roce is not None or c2p is not None):
        facts.append(_cap(_said([(roce is not None, f"ROCE {_pc(roce or 0)}%"),
                                 (c2p is not None, f"cash flow {_num(c2p or 0)}\u00d7 profit")])))
    if rev3 is not None:
        facts.append(f"Sales {rev3:+.0f}% a year for 3 years")
    if pledge is not None:
        facts.append("No shares pledged" if pledge == 0 else f"Promoters pledged {_pc(pledge)}%")
    if pe is not None:
        facts.append(f"P/E {pe:.0f}" + (f", PEG {_num(peg)}" if peg is not None else ""))
    if r12 is not None and len(facts) < WHY_MAX:
        facts.append(f"Up {r12 * 100:.0f}% in a year" if r12 >= 0 else f"Down {abs(r12) * 100:.0f}% in a year")
    if _high_text(g) and len(facts) < WHY_MAX:
        facts.append(_high_text(g))
    return {"score": score, "why_not": why, "exact": score, "breakdown": breakdown, "why": facts[:WHY_MAX]}


def next_results_season(day):
    """(the next results season's first day, whether one is running now).
    Companies report from about the tenth of the month after a quarter ends,
    for about fifty days."""
    day = day or dt.date.today()
    if isinstance(day, dt.datetime):
        day = day.date()
    for year in (day.year - 1, day.year):
        for m, d in RESULTS_SEASON_STARTS:
            start = dt.date(year, m, d)
            if start <= day <= start + dt.timedelta(days=RESULTS_SEASON_DAYS):
                return start, True
    starts = sorted(dt.date(y, m, d) for y in (day.year, day.year + 1) for m, d in RESULTS_SEASON_STARTS)
    return next(s for s in starts if s > day), False


def rank(candidates, results=None, sectors=None, fundamentals=None, benchmark=None,
         institutional=None, snapshot=None):
    """
    Score every candidate against the whole liquid universe, for every list.

    `candidates` is a list of dicts carrying `symbol` and `leader_sig` (the
    output of signals(), or None). `results` maps a symbol to when its latest
    quarterly results reached the exchange ({"filed_at": ...}); without it the
    results list is simply empty. `sectors` maps a symbol to its sector;
    without it the money-flow list is empty. `fundamentals` maps a symbol to
    its latest quarter ({"pat_yoy_pct", "revenue_yoy_pct", "pat_cr"}); the
    short-term and setup lists refuse a known fall in profit, and a company
    with no filing is never refused for it. `benchmark` is the Nifty 500's
    {"ret_1m", "ret_3m"} (fractions); without it the median liquid stock's
    stand in. `institutional` maps a symbol to live Money Flow facts
    ({"accumulation": 0..100, "sector_score": 0..100}); it reorders the
    money-flow list's tested names and never chooses them. A candidate may
    carry `listed_sessions`, how long it has traded, when its frame is
    shorter than its history.

    `snapshot` maps a symbol to its fundamentals snapshot (fund_snapshot.build
    with a price, plus the live-only facts: scan.fundamental_snapshot() live,
    the lab's point-in-time equivalent in a replay). The three fundamental
    lists read it, with prices, `results` and `sectors`, and nothing else;
    the setup lists never read it and keep reading `fundamentals` exactly as
    they always have. A company with no snapshot, or a figure it has not
    filed, is the middle of the field on that part and skips the check that
    needs it.

    Returns {SYMBOL: block}. A stock outside
    the universe gets no block: it was not compared, which is different from
    being compared and failing a gate.
    """
    if np is None:
        return {}
    listed = {str(c.get("symbol") or "").upper(): c.get("listed_sessions") for c in candidates or []}
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
    filings = {str(k).upper(): v for k, v in (results or {}).items()}
    events = result_reactions(pool, filings)
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

    # What the three fundamental lists read beside the chart: each company's
    # filings (an all-empty snapshot is no snapshot), their figures as
    # percentiles among the established, the month list's month of results
    # and the After results list, built for every reporter at once because
    # it is empty unless enough of them pass.
    snaps = {str(k).upper(): v for k, v in (snapshot or {}).items() if isinstance(v, dict) and v}
    tabs = {"sectors": sectors, "flow_by": flow_by,
            "snap_pct": _snapshot_pcts([s for s, _g in pool], snaps, sectors),
            "events_month": (result_reactions(pool, filings, window=MONTH["result_lookback"])
                             if MONTH.get("result_guard") else {})}
    after_results, qualified = _results_list(events, reaction, snaps)

    # The market the setups are measured against: the Nifty 500 when the scan
    # could read it, else the median liquid stock.
    def _median(xs):
        xs = sorted(x for x in xs if x is not None)
        if not xs:
            return 0.0
        m = len(xs) // 2
        return xs[m] if len(xs) % 2 else (xs[m - 1] + xs[m]) / 2.0
    bench = {"ret_1m": _finite((benchmark or {}).get("ret_1m")),
             "ret_3m": _finite((benchmark or {}).get("ret_3m"))}
    bench["source"] = "Nifty 500" if bench["ret_1m"] is not None and bench["ret_3m"] is not None else "median stock"
    if bench["ret_1m"] is None:
        bench["ret_1m"] = _median([_finite(g.get("ret_1m")) for _s, g in pool])
    if bench["ret_3m"] is None:
        bench["ret_3m"] = _median([_finite(g.get("ret_3m")) for _s, g in pool])

    flow_pick, flow_why = {}, {}
    for sec in flow_top:
        members = []
        for i, (sym, g) in enumerate(pool):
            if sectors.get(sym) != sec:
                continue
            t = g.get("tech") or {}
            ext = _finite(t.get("ext_50d_pct"))
            r1, r3 = _finite(g.get("ret_1m")), _finite(g.get("ret_3m"))
            if not g["uptrend"]:
                flow_why[sym] = "Not in an uptrend."
            elif calm[i] < CALM_FLOOR:
                flow_why[sym] = "Among the most volatile fifth of liquid stocks."
            elif (g.get("near_high") or 0) < FLOW_NEAR_HIGH:
                flow_why[sym] = f"More than {(1 - FLOW_NEAR_HIGH) * 100:.0f}% under its 52-week high."
            elif FLOW_ANTI_CHASE and ext is not None and ext > FLOW_EXT50:
                flow_why[sym] = f"Already {ext:.0f}% above its 50-day average; the list buys {FLOW_EXT50:.0f}% or less."
            elif FLOW_ANTI_CHASE and r3 is not None and r3 > FLOW_RET3M:
                flow_why[sym] = f"Up {r3 * 100:.0f}% in three months already; the list stops at {FLOW_RET3M * 100:.0f}%."
            elif r1 is None or r3 is None or r1 <= bench["ret_1m"] or r3 <= bench["ret_3m"]:
                flow_why[sym] = "Has not beaten the market over both one month and three."
            else:
                members.append((-(m12[i] + m6[i] + high[i] + trend[i]) / 4.0, sym))
        for _lead, sym in sorted(members)[:FLOW_PER_SECTOR]:
            flow_pick[sym] = sec

    # The last quarter, where it is known: profit growth as a percentile
    # among the established stocks that have one.
    fundamentals = {str(k).upper(): v for k, v in (fundamentals or {}).items() if v}
    pat = {sym: _finite((fundamentals.get(sym) or {}).get("pat_yoy_pct")) for sym, _g in pool}
    have = [sym for sym, v in pat.items() if v is not None]
    growth = dict(zip(have, _pct_ranks([max(-100.0, min(300.0, pat[x])) for x in have]))) if have else {}
    # More volume on up days than down days, as a percentile: one of the three
    # things the technical list is ordered on.
    ud = [(sym, _finite((g.get("tech") or {}).get("up_down_volume"))) for sym, g in pool]
    ud = [(sym, v) for sym, v in ud if v is not None]
    updown = dict(zip([u[0] for u in ud], _pct_ranks([u[1] for u in ud]))) if ud else {}
    ctx = {"sectors": sectors, "flow_by": flow_by, "flow_top": flow_top, "flow_pick": flow_pick,
           "flow_why": flow_why, "bench": bench, "fund": fundamentals, "events": events,
           "updown": updown,
           "institutional": {str(k).upper(): v for k, v in (institutional or {}).items() if v}}

    blocks, exact = {}, {}
    for i, (sym, g) in enumerate(pool + newcomers):
        young = bool(g.get("young"))
        part = {"m12": m12[i], "m6": m6[i], "high": high[i], "trend": trend[i],
                "calm": calm[i], "dip": dip[i], "dip21": dip21[i],
                "reaction": reaction.get(sym)}
        part["leader"] = (m12[i] + m6[i] + high[i] + trend[i]) / 4.0
        is_calm = calm[i] >= CALM_FLOOR
        ev = events.get(sym)
        snap = snaps.get(sym) or {}
        lists = {}
        for key, spec in LISTS.items():
            why_not, tab = None, None
            if key == "emerging":
                # Companies listed six to eighteen months (the younger ones
                # placed against the established universe), in a Stage-2
                # advance, strongest first.
                age = _finite(listed.get(sym))
                age = int(age) if age is not None else g.get("sessions")
                score, why_not, exact[(sym, key)] = _emerging(sym, g, part, ctx, age)
                part[key] = part["leader"]
            elif young and key not in YOUNG_LISTS:
                # Tested and not admitted: the lists that read a year of
                # prices and filings, where the younger picks trailed the
                # average stock in at least one half.
                score = 0.0
                elsewhere = ", ".join([LISTS[k]["label"].lower() for k in YOUNG_LISTS] + ["emerging"])
                why_not = ("Listed under a year. This list needs twelve months of prices; "
                           f"younger companies are on {elsewhere}.")
                exact[(sym, key)] = -1.0
                if spec.get("recipe"):
                    tab = {"breakdown": [], "why": None}
            elif spec.get("kind") == "setup":
                if key == "short":
                    score, why_not, exact[(sym, key)] = _short(sym, g, part, sectors, flow_by,
                                                                pat.get(sym), growth.get(sym), ev)
                else:
                    score, why_not, exact[(sym, key)] = _setup(key, sym, g, part, is_calm, ctx)
                part[key] = score / 100.0
            elif key == "results":
                tab = after_results.get(sym)
                if tab is None:
                    # Not ranked: nothing priced, or too few reporters to rank among.
                    tab = {"score": 0.0, "exact": -1.0, "breakdown": [], "why": None,
                           "why_not": (f"No results priced in the last {RESULTS_WINDOW} sessions." if ev is None
                                       else f"Fewer than {RESULTS_MIN_POOL} liquid companies have had results "
                                            f"priced in the last {RESULTS_WINDOW} sessions.")}
                score, why_not, exact[(sym, key)] = tab["score"], tab["why_not"], tab["exact"]
            elif key == "month":
                tab = _month(sym, g, part, is_calm, snap, tabs)
                score, why_not, exact[(sym, key)] = tab["score"], tab["why_not"], tab["exact"]
            else:
                tab = _long(sym, g, part, is_calm, snap, tabs)
                score, why_not, exact[(sym, key)] = tab["score"], tab["why_not"], tab["exact"]
            fact = ev
            if key == "short":
                srow = flow_by.get(sectors.get(sym))
                if srow:
                    srow = dict(srow, rank=srow.get("classic_rank", srow["rank"]))
                fact = {"sector_row": srow, "pat_yoy_pct": pat.get(sym)}
            if key == "flow" and sectors.get(sym) in flow_by:
                fact = flow_by[sectors[sym]]
            if key == "breakout":
                launch, pattern, _w = _launch(g, g.get("tech") or {}, part, flow_by.get(sectors.get(sym)),
                                              fundamentals.get(sym))
                fact = {"launch": launch, "pattern": pattern} if launch else None
            if key == "technical":
                fact = {} if why_not is None else None
            if key == "emerging":
                fact = {"listed": _finite(listed.get(sym)) or g.get("sessions")}
            lists[key] = {"score": round(score, 1), "eligible": why_not is None,
                          "why_not": why_not, "rank": None,
                          "why": (tab or {}).get("why") or _why(key, g, calm[i], fact)}
            if tab is not None:
                # The weighted parts of the score, which add up to it.
                lists[key]["breakdown"] = tab["breakdown"]
        blocks[sym] = {
            "recipe": RECIPE,
            "universe": len(pool),
            # Listed six to twelve months: ranked against the established
            # universe, on the lists in YOUNG_LISTS only.
            "young": young,
            "listed_sessions": (int(listed[sym]) if _finite(listed.get(sym)) is not None and listed[sym] < 1e4
                                else g.get("sessions")),
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
            # ten sessions, with how many companies it was ranked among and
            # how many of them passed every test of the After results list.
            "results": (None if ev is None else {
                "filed_at": ev["filed_at"], "session": ev["session"],
                "sessions_ago": ev["sessions_ago"], "quarter": ev.get("quarter"),
                "move_pct": round(ev["move"] * 100, 1),
                "market_move_pct": round(ev["market_move"] * 100, 1),
                "reaction_pct": round(ev["reaction"] * 100, 1),
                "vol_x": None if ev.get("vol_x") is None else round(ev["vol_x"], 2),
                "pat_yoy_pct": ev.get("pat_yoy_pct"), "revenue_yoy_pct": ev.get("revenue_yoy_pct"),
                "reported": len(events), "qualified": qualified}),
            # What its filings say, as the page shows it beside a pick.
            "fundamentals": ({k: snap.get(k) for k in FUNDAMENTALS_SHOWN} if snap else None),
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
        # The three fundamental lists hold at most `sector_cap` stocks of one
        # NSE industry: a strong industry would otherwise fill a list with
        # stocks that rise and fall together. A stock with no industry on
        # NSE's list is not capped.
        cap = int((recipe_of(key) or {}).get("sector_cap") or 0)
        if cap > 0:
            held, kept = {}, []
            for s in ordered:
                industry = sectors.get(s)
                if industry and held.get(industry, 0) >= cap:
                    blocks[s]["lists"][key].update(
                        eligible=False, why_not=f"{cap} stocks from its industry rank higher on this list.")
                    continue
                if industry:
                    held[industry] = held.get(industry, 0) + 1
                kept.append(s)
            ordered = kept
        for n, sym in enumerate(ordered, 1):
            blocks[sym]["lists"][key]["rank"] = n
    return blocks


def breakout_watch(blocks, limit=20):
    """
    Bases not yet broken, for the breakouts list: a stock whose base would
    make a breakout on a close above its top (technicals()["watch"]: a VCP
    launchpad 28% wide or less that has tightened, or a 60-session base
    turnaround 35% wide or less), within 3% of that top today, above its
    200-day average, not already extended, and passing the screens the list
    applies after a breakout: for a launchpad a leader score of 45 or more
    and an industry outside the bottom 40% on money flow; for either, no
    known fall in profit last quarter. Nearest the top first. Watched, not
    picked: nothing here has broken out.
    """
    out = []
    for sym, b in (blocks or {}).items():
        t, facts = b.get("technicals") or {}, b.get("facts") or {}
        w = t.get("watch")
        if not w or b.get("young") or t.get("launch"):
            continue
        ext = t.get("ext_50d_pct")
        if (ext is not None and ext > CHASE_EXT50) or (facts.get("return_3m_pct") or 0) > CHASE_RET3M * 100:
            continue
        flow, q = b.get("sector_flow"), b.get("quarter") or {}
        if q.get("pat_yoy_pct") is not None and q["pat_yoy_pct"] < BAD_PROFIT_PCT:
            continue
        if BREAKOUT_SECTOR_NEAR_HIGH and flow is not None and flow.get("near_high") is False:
            continue
        if w["pattern"] == "VCP launchpad":
            if (b.get("score") or 0) < LAUNCH_A_LEADER * 100:
                continue
            if flow is not None and flow["rank"] / float(flow["of"]) > LAUNCH_A_SECTOR_TOP:
                continue
        out.append({"symbol": sym, "sector": b.get("sector"), "pattern": w["pattern"], "base": w["base"],
                    "top": w["top"], "low": w["low"], "width_pct": w["width_pct"], "to_top_pct": w["to_top_pct"],
                    "rel_volume_5": t.get("rel_volume_5"), "leader": b.get("score"),
                    "turnover_cr": facts.get("turnover_cr")})
    out.sort(key=lambda r: (r["to_top_pct"], -(r["leader"] or 0), r["symbol"]))
    return out[:limit]


def short_watch(blocks, limit=20):
    """
    The short-term list's waiting room, unchanged from November 2026: tight
    bases not yet broken, whose last 40 sessions fit inside an 18% range,
    above their 200-day average, in the stronger half on the leader score,
    within 3% of the top of the base, not in an industry in the bottom half
    on money flow, and without a fall in profit last quarter. Nearest the
    top first. Watched, not picked.
    """
    out = []
    for sym, b in (blocks or {}).items():
        t, facts = b.get("technicals") or {}, b.get("facts") or {}
        base = t.get("base")
        if not base or b.get("young") or t.get("box"):
            continue
        if base["width_pct"] > BOX_MAX_WIDTH * 100 or base["to_top_pct"] > VERGE_PCT:
            continue
        flow, q = b.get("sector_flow"), b.get("quarter") or {}
        if flow is not None and flow.get("classic_score", flow["score"]) < SHORT_SECTOR_FLOOR:
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


def target_tested(key):
    """
    What the study measured when a pick was SOLD at the mark plan() puts on it.

    The study ran the month and long-term lists' picks twice more (as it ran
    the price lists before them): held to the end with the exit line, and
    sold at the first high as far above the entry as that line is below it.
    Both records are in the file's `exits` table, and this returns the two
    side by side, so the page can say what selling at the mark did in the
    study's own numbers and in no others. None for a list the study did not
    run that way (the results list and the setups), and the page then says
    only what the mark is.
    """
    spec = LISTS.get(key)
    if spec is None or spec.get("sell_rule"):
        return None
    pct = spec["exit_pct"]
    runs = (TESTED.get("exits") or {}).get(key) or {}
    held = runs.get(f"close {pct:g}% under")
    sold = runs.get(f"close {pct:g}% under, target {pct:g}% over")
    if not held or not sold:
        return None
    keep = ("up_pct", "avg_pct", "median_pct", "picks")
    return {"target_pct": pct,
            "sold": {k: sold.get(k) for k in keep},
            "held": {k: held.get(k) for k in keep}}


def best_rank(block):
    """The best standing a stock has on any list, or None if it is on none."""
    ranks = [v.get("rank") for v in ((block or {}).get("lists") or {}).values() if v.get("rank")]
    return min(ranks) if ranks else None


def plan(key, price, called_on=None):
    """
    The plan the test supports, and nothing more precise than that.

    `stop` is kept under that name because the tracker and the call log judge
    an idea against `plan.stop`; here it is the exit line, a set distance
    under the call price, read on a close.

    There is deliberately no target to SELL at: `t1` and `rr` stay None, so
    the tracker and the call log close a call exactly as they did. `aim` is
    something else, for the page only: a mark as far above the call price as
    the exit line is below it, which is the nearer of the two targets the
    study tested (research/ideas_study.py, "target X% over"). A reader asked
    where a good result would be; this is where, and target_tested() below is
    what the study found on selling there. A list with a sell rule of its own
    (emerging leaves on a close under the 50-day average) carries no mark.
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
    if spec.get("sell_rule") == "sma50":
        note = (f"Hold {spec['hold_text']} ({spec['hold_sessions']} sessions). After the first "
                f"{spec.get('trail_after', 15)}, sell on a close under its 50-day average. Leave at any "
                f"time if it closes below \u20b9{line:,.2f}, {spec['exit_pct']:.0f}% under this price.")
    # The rebuilt setup lists (`let_run`) show no mark: they are held for
    # the large winners, and no target was tested on them.
    marked = not spec.get("sell_rule") and not spec.get("let_run")
    return {
        "style": "hold",
        "stance": "HOLD",
        "entry": round(p, 2),
        "stop": round(line, 2),
        "risk_pct": spec["exit_pct"],
        "rr": None,
        "t1": None,
        "aim": round(p * (1 + spec["exit_pct"] / 100.0), 2) if marked else None,
        "aim_pct": spec["exit_pct"] if marked else None,
        "hold_sessions": spec["hold_sessions"],
        "hold_text": spec["hold_text"],
        "review_on": (day + dt.timedelta(days=spec["hold_days"])).isoformat(),
        "sell_rule": spec.get("sell_rule"),
        "note": note,
    }
