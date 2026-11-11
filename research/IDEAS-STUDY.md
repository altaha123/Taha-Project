# The Ideas study

November 2026. Why the Ideas list was losing, what replaced it, and how well the
replacement tested. Every number here is produced by `research/ideas_study.py`
and stored in `research/ideas-study.json`; the Ideas page reads the same file.
The trials behind "One stock, one list" are in `research/separation_lab.py`
and `research/separation-lab.json`.

## The problem

The tracker had closed 33 ideas. 30% made money, the average was −2.6%, and
62% hit their stop. Two rows in three on the live list said WAIT.

## The data

NSE's own daily bhavcopy for every session from January 2016 to 9 November
2026: 2,679 sessions and 3,276 companies, including every company that was
later delisted. A list of today's survivors would flatter any method.

- **Company shares only.** The same files carry exchange-traded funds. A
  liquid-fund ETF climbs in a straight line at about 1% volatility, so it
  ranked first on every return-for-risk measure. Only ISINs beginning `INE`
  are kept. This was found late, and it changed a decision (see Long term).
- **Splits and bonuses** are removed where a session opens more than 21% from
  the previous close, which a 20% price band makes impossible otherwise.
- **Price returns.** No dividends, costs or tax. The benchmark is the Nifty 500
  price index over the same dates.
- **No look-ahead.** A signal uses bars up to its date. The pick is bought at
  the next session's open.

## What was wrong

The old method was replayed on 241 past dates (3,545 picks, held 42 sessions).

| | Picks that rose | Average | Nifty 500 |
|---|---|---|---|
| Old list with its 8% stop | 38% | +2.0% | +2.2% |
| Same picks, no stop | 54% | +3.7% | +2.2% |

1. **The stop.** It was hit on 57% of picks. It was the largest single cause.
   Targets could not be replayed from prices; they would have made this worse.
2. **The order.** Rows were ranked by a score that leaned on "fell last week"
   and "unusual turnover". Neither predicted much (table below).
3. **The pool.** Only the 150 highest technical scores on the exchange reached
   the list, down to companies trading ₹50 lakh a day.

Rank correlation of each signal with what the stock did next, across every
stock trading ₹5 crore a day:

| Signal | 5 sessions | 21 | 63 | 126 |
|---|---|---|---|---|
| Closeness to the 52-week high | 0.036 | 0.058 | 0.097 | 0.123 |
| Low volatility | 0.055 | 0.056 | 0.064 | 0.081 |
| 12-month return, last month skipped | 0.020 | 0.045 | 0.072 | 0.077 |
| Straightness of the trend | 0.016 | 0.029 | 0.054 | 0.079 |
| One-week reversal | 0.030 | 0.011 | −0.009 | −0.019 |
| Turnover against its own history | −0.016 | 0.001 | 0.016 | 0.012 |

## The four lists

Each ranks every liquid stock (a typical day trades ₹10 crore or more, price
₹20 or more: about 390 companies on a median day, 721 today) on percentile
ranks, keeps those in an uptrend and outside the most volatile fifth, and takes
the top 15. `backend/leaders.py` holds the recipes.

| List | Recipe | Hold | Exit line |
|---|---|---|---|
| This week | half leader score, half five-day dip | 5 sessions | close 7% under |
| This month | a leader (top 30%) that fell this month: half month dip, half 52-week high | 21 | close 12% under |
| Momentum | leader score, leaving out the long-term top 15 | 63 | close 15% under |
| Long term | 12-month return, 52-week high, straightness | 252 | close 30% under |

The leader score is the average of four ranks: 12-month and 6-month return for
their volatility, closeness to the 52-week high, and straightness of the trend.
This month and momentum changed on 12 November 2026 so the lists stop showing
the same stocks; see "One stock, one list" below.

### How they tested

A list every five sessions from January 2017, bought next morning, held for the
period, left on a close under the exit line.

| List | Picks | Rose | Average | Nifty 500 | Half made less than | Worst 1 in 20 |
|---|---|---|---|---|---|---|
| This week | 7,243 | 52% | +0.42% | +0.27% | +0.3% | −8% |
| This month | 7,177 | 54% | +1.74% | +1.08% | +0.9% | −13% |
| Momentum | 7,007 | 55% | +5.50% | +3.20% | +2.6% | −18% |
| Long term | 6,434 | 58% | +23.7% | +13.8% | +8.1% | −33% |

A random 15 from the same stocks: 49%, 51%, 52% and 55% rose, and averaged
+0.04%, +0.86%, +3.22% and +15.1%.

After a 0.49% round trip (brokerage, STT, charges, stamp duty, GST, a little
slippage) the average pick made −0.07% on this week, +1.25% on this month,
+5.01% on momentum and +23.2% on long term. **The one-week list does not pay
for its own costs.**

The first recipes were chosen on 2017–21 and checked on 2022–26:

| List | 2017–21: average vs index | 2022–26: average vs index |
|---|---|---|
| This week | +0.55% vs +0.33% | +0.30% vs +0.20% |
| This month | +2.45% vs +1.46% | +1.02% vs +0.69% |
| Momentum | +6.56% vs +3.72% | +4.37% vs +2.66% |
| Long term | +22.3% vs +14.2% | +25.6% vs +13.3% |

### Against the average stock

The Nifty 500 is weighted to the largest companies, and these lists mostly
hold smaller ones, which beat the large ones by a wide margin in 2020–24. So
each list is also measured against the average liquid stock, every one of them
held over the same dates. The t-statistic uses Newey-West errors because lists
five sessions apart hold overlapping periods.

| List | Ahead of the average stock | t | 2017–21 | 2022–26 |
|---|---|---|---|---|
| This week | +0.32% | 4.0 | +0.41% | +0.22% |
| This month | +0.69% | 2.4 | +1.25% | +0.11% |
| Momentum | +2.03% | 3.3 | +3.64% | +0.33% |
| Long term | +7.60% | 2.2 | +9.75% | +4.83% |

Every list led the average stock in both halves. In 2022–26 the month and
momentum lists led it only narrowly: most of what they gained on the Nifty 500
then came from holding smaller companies, not from the recipe.

### The exit lines

The line is read on the close. A tighter line cost more than it saved:

| Momentum list | Rose | Average | Worst 1 in 20 |
|---|---|---|---|
| No exit line | 58% | +6.2% | −22% |
| Close 7.5% under | 44% | +4.2% | −11% |
| **Close 15% under** | 55% | +5.5% | −18% |
| Close 22.5% under | 57% | +5.9% | −24% |

There is no target. On the momentum list a +15% target raised the share of
picks that rose from 55% to 62% and cut the average from +5.5% to +3.4%. On the
long-term list a +30% target raised it from 58% to 65% and cut the average from
+23.7% to +8.8%. A few large winners carry each list, and a target sells
exactly those. A higher hit rate is not a better list.

Momentum held six months instead of three, on a line 20% under: 57% rose,
+9.9% a pick against +6.4% for the index.

## One stock, one list

The lists as first built shared most of their names. On 484 past dates:

| Names in common, of 15 | First version | Now |
|---|---|---|
| This week / this month | 10.0 | 3.6 |
| Momentum / long term | 12.0 | 0 |
| This month / momentum | 6.2 | 3.9 |
| This month / long term | 5.4 | 2.6 |
| This week / momentum | 3.0 | 3.6 |
| This week / long term | 2.5 | 2.5 |
| **Different stocks in the 60 places** | **31** | **46** |

Readers saw the same stocks under four tabs. It was not a bug in the code: the
best three-month momentum stocks are also the best year-long climbers, and two
recipes that differ by a quarter of their weight pick the same names.

**What was tried, all of it reported** (`separation_lab.py`, 20 trials):

1. Ten other recipes, declared and run together: three for the week, three
   for the month, two for momentum, two for the long term, and momentum held
   six months. None beat the first version on 2017–21. Recipes alone could
   not separate the lists without giving up what they earned.
2. Each stock on one list only, three ways, declared together. Longest first
   kept long term whole but left this week with nothing (+0.02% ahead of the
   average stock). Shortest first took long term from +7.6% ahead to −0.3%: its
   edge is in the very names the short lists want. Best fit took it to +2.3%.
3. After seeing those, two more orders, and one that only splits the two heavy
   pairs.
4. After seeing those, the month recipe that buys a month's pullback in a
   leader (trial R6) in place of the first one. It shares about 4 names with
   this week rather than 10, and on 2017–21 it led every option that separates
   the week from the month (+1.25% ahead of the average stock, against +1.14%
   for the first recipe made to give way to the week).

What the site runs, beside the first version, ahead of the average stock:

| List | First version | Now | What changed |
|---|---|---|---|
| This week | +0.32% (t 4.0) | +0.32% (t 4.0) | nothing |
| This month | +0.93% (t 3.1) | +0.69% (t 2.4) | the month-dip recipe |
| Momentum | +2.75% (t 2.4) | +2.03% (t 3.3) | leaves out the long-term top 15 |
| Long term | +7.60% (t 2.2) | +7.60% (t 2.2) | nothing |

The price of different stocks: this month and momentum average less. Momentum's
smaller lead was also a steadier one (its t rose from 2.4 to 3.3); why is not
established here. Steps 3 and 4 were chosen after
earlier results were seen, so their numbers are less trustworthy than the first
version's, and the live record is what should settle them.

### Long term: a recipe that was dropped

The first long-term recipe ranked on low volatility. It tested best until the
ETFs were found. On company shares alone it averaged +13.3% a year in 2017–21
against +14.2% for the index, so it was replaced by the recipe above, which led
in both halves. The page also leaves out loss-makers and a Piotroski score
under 4 on that list. That screen is a precaution; no ten-year filing history
exists to test it.

## The score

The three price pillars of the Altaha Score were re-weighted from the same
data. Closeness to the 52-week high joined Momentum. Participation went from
20 to 5 points for a trade and to 0 beyond. One-week reversal went from 65% of
Risk to 25% for a trade and to 0 beyond.

| Horizon | Rank correlation before | After | Both halves, after |
|---|---|---|---|
| Trade (next 21 sessions) | 0.052 | 0.076 | 0.083, 0.069 |
| Position (next 63) | 0.089 | 0.105 | 0.128, 0.080 |
| Invest (next 252) | 0.128 | 0.141 | 0.163, 0.112 |

The five business pillars are unchanged. There is no ten-year point-in-time
filing history to measure them on.

## What this does not show

- **Barely more than half the picks rose.** The edge is in the size of the
  winners. Anyone holding two or three picks from a list is not holding the
  list.
- **The one-week edge is about 0.15% a week before costs.** After a 0.49%
  round trip the average week pick lost 0.07%. It is the weakest list to hand
  to anyone who pays to trade.
- **Some years were flat or behind.** Momentum trailed the index for lists
  made in 2022 and 2025. This month trailed it in 2024 and 2025 and matched
  it in 2017. The long-term list trailed for 2017, 2018 and 2024.
- **In 2022–26 the month and momentum lists barely led the average stock**
  (+0.11% and +0.33%). Their lead on the Nifty 500 in those years was mostly
  the lead small and mid-sized companies had on large ones.
- **Two of the four recipes were changed after results were seen**, to stop
  the lists repeating each other (see "One stock, one list").
- **Picks are often small and mid-sized companies.** A larger-companies-only
  variant tested worse, so it was not used.
- **The page caps one sector at four names and removes serious adverse
  filings.** Neither was in the test.
- **It is ten years of one market.** It is not a forecast.

## The live record

The call log dates every pick and keeps the exit line it was called with. The
daily job (`.github/workflows/ideas.yml`) runs the scan after the close, marks
the tracker and attaches forward returns. Before it existed the store held
350,000 observations and no measured outcomes.

## Reproducing it

```bash
python research/ideas_study.py --fetch      # NSE daily files, once
python research/ideas_study.py --build      # adjusted price panel
python research/ideas_study.py --baseline   # replay the old ranking (about 30 minutes)
python research/ideas_study.py --study      # tables and research/ideas-study.json
python research/separation_lab.py           # every trial behind "One stock, one list"
```

`--study` first checks that `backend/leaders.py` picks the same 360 stocks the
study picked on six past dates, and stops if it does not.
