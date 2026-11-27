# The Ideas study

November 2026. Why the Ideas list was losing, what replaced it, and how well the
replacement tested. Every number here is produced by `research/ideas_study.py`
and stored in `research/ideas-study.json`; the Ideas page reads the same file.
The trials behind "One stock, one list" are in `research/separation_lab.py`
and `research/separation-lab.json`. The trials behind the fifth list, the
younger companies and everything in "What did not earn a place" are in
`research/signals_lab.py` and `research/signals-lab.json`.

December 2026: the page now leads with three lists that read each company's
filings beside its chart, in place of the five below. Their trials and their
record come from `research/fundamental_ideas_lab.py` (all of it in
`research/fundamental-ideas-lab.json`); see "Three fundamental lists
(December 2026)".

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

## The five lists

*Replaced in December 2026* by the three lists in "Three fundamental lists"
below. This month became Swing / This month, long term became Long-term
compounders and after results kept its name, all three rebuilt on company
filings; this week was folded into the first and momentum into the third.
This section, "One stock,
one list", "What a reader asked for, tested" and "Two tabs" are the record of
the five as they ran, with the figures measured in November 2026. The study
file keeps this week's and momentum's records under `retired`;
`research/fundamental-ideas-lab.json` replays all five again on the windows
the new lists were chosen and checked on.

Four rank on price. Each of those ranks every liquid stock (a typical day trades ₹10 crore or more, price
₹20 or more: about 390 companies on a median day, 721 today) on percentile
ranks, keeps those in an uptrend and outside the most volatile fifth, and takes
the top 15. `backend/leaders.py` holds the recipes.

| List | Recipe | Hold | Exit line |
|---|---|---|---|
| This week | half leader score, half five-day dip | 5 sessions | close 7% under |
| This month | a leader (top 30%) that fell this month: half month dip, half 52-week high | 21 | close 12% under |
| Momentum | leader score, leaving out the long-term top 15 | 63 | close 15% under |
| Long term | 12-month return, 52-week high, straightness | 252 | close 30% under |

The fifth is made from a filing, not a recipe:

| List | What it ranks | Hold | Exit line |
|---|---|---|---|
| After results | liquid companies whose quarterly results were first priced in the last ten sessions, by that session's move less the average stock's | 21 | close 12% under |

It has no uptrend or volatility gate, because it was tested without one, and
it is empty between results seasons. See "After results" below.

Companies listed six to twelve months are on the week and momentum lists as
well, their 6-month return standing in for the 12-month one. See "Younger
companies" below.

The leader score is the average of four ranks: 12-month and 6-month return for
their volatility, closeness to the 52-week high, and straightness of the trend.
This month and momentum changed on 12 November 2026 so the lists stop showing
the same stocks; see "One stock, one list" below.

### How they tested

A list every five sessions from January 2017, bought next morning, held for the
period, left on a close under the exit line.

| List | Picks | Rose | Average | Nifty 500 | Half made less than | Worst 1 in 20 |
|---|---|---|---|---|---|---|
| This week | 7,243 | 52% | +0.43% | +0.27% | +0.3% | −8% |
| This month | 7,177 | 54% | +1.74% | +1.08% | +0.9% | −13% |
| After results | 3,518 | 54% | +1.76% | +1.00% | +1.0% | −14% |
| Momentum | 7,011 | 55.5% | +5.61% | +3.20% | +2.7% | −18% |
| Long term | 6,434 | 58% | +23.7% | +13.8% | +8.1% | −33% |

The results list starts in June 2018, where its filings start, and made a
list on 244 of 411 dates: the rest fell between results seasons.

A random 15 from the same stocks, for the four price lists: 49%, 51%, 52% and
55% rose, and averaged +0.04%, +0.86%, +3.22% and +15.1%.

After a 0.49% round trip (brokerage, STT, charges, stamp duty, GST, a little
slippage) the average pick made −0.06% on this week, +1.25% on this month,
+1.27% after results, +5.12% on momentum and +23.2% on long term. **The
one-week list does not pay for its own costs.**

The first recipes were chosen on 2017–21 and checked on 2022–26:

| List | 2017–21: average vs index | 2022–26: average vs index |
|---|---|---|
| This week | +0.56% vs +0.33% | +0.30% vs +0.20% |
| This month | +2.45% vs +1.46% | +1.02% vs +0.69% |
| After results (from 2018) | +1.84% vs +1.35% | +1.69% vs +0.70% |
| Momentum | +6.61% vs +3.72% | +4.55% vs +2.66% |
| Long term | +22.3% vs +14.2% | +25.6% vs +13.3% |

### Against the average stock

The Nifty 500 is weighted to the largest companies, and these lists mostly
hold smaller ones, which beat the large ones by a wide margin in 2020–24. So
each list is also measured against the average liquid stock, every one of them
held over the same dates. The t-statistic uses Newey-West errors because lists
five sessions apart hold overlapping periods.

| List | Ahead of the average stock | t | 2017–21 | 2022–26 |
|---|---|---|---|---|
| This week | +0.32% | 4.1 | +0.42% | +0.22% |
| This month | +0.69% | 2.4 | +1.25% | +0.11% |
| After results (from 2018) | +0.71% | 2.4 | +0.61% | +0.80% |
| Momentum | +2.15% | 3.4 | +3.69% | +0.51% |
| Long term | +7.60% | 2.2 | +9.75% | +4.83% |

Every list led the average stock in both halves. In 2022–26 the month and
momentum lists led it only narrowly: most of what they gained on the Nifty 500
then came from holding smaller companies, not from the recipe.

### The exit lines

The line is read on the close. A tighter line cost more than it saved:

| Momentum list | Rose | Average | Worst 1 in 20 |
|---|---|---|---|
| No exit line | 58% | +6.3% | −23% |
| Close 7.5% under | 44% | +4.3% | −11% |
| **Close 15% under** | 55.5% | +5.6% | −18% |
| Close 22.5% under | 58% | +6.0% | −24% |

There is no target. On the momentum list a +15% target raised the share of
picks that rose from 55.5% to 62% and cut the average from +5.6% to +3.5%. On the
long-term list a +30% target raised it from 58% to 65% and cut the average from
+23.7% to +8.8%. A few large winners carry each list, and a target sells
exactly those. A higher hit rate is not a better list.

*Added 20 November 2026.* The page now shows a target on each pick, because a
reader asked where a good result would be. It is the nearer of the two tested
above, as far over the price as the exit line is under it, and it is a mark
and not a rule: the plan still says hold, nothing is sold at it, and the page
prints the two rows of this comparison beside it (`leaders.target_tested`).
The finding above stands.

Momentum held six months instead of three, on a line 20% under: 57% rose,
+9.9% a pick against +6.4% for the index.

## Three fundamental lists (December 2026)

Four of the five lists above read a stock's chart and nothing else, and the
fifth read only when a company's results came out, so a company whose profit
had just collapsed could top them. Since December 2026 the page
leads with three lists that read each company's own filings beside its
chart. This week was folded into the first and momentum into the third; an
old link to either opens the list that replaced it. The figures the lists
read (sales and margin growth, return on capital, cash against profit, debt,
F-score, P/E and the rest) are built by `backend/fund_snapshot.py`, the same
code for the live scan and for the replay.

| List | What it is | Hold | Exit line |
|---|---|---|---|
| **Swing / This month** | A market leader (leader score in the top 30%) in an uptrend and outside the most volatile fifth, in an industry ranked in the top half of industries on money flow. A pullback is ranked, not required. Left out: a loss or a fall in profit last quarter, results the market sold in the last 21 sessions, more than 10% of the company pledged. Ranked on the month's pullback, closeness to the 52-week high, last quarter's sales and margin growth (a lender's sales alone), the industry's money flow and a live catalyst | 21 sessions | close 12% under |
| **After results** | A company whose quarterly results were first priced in the last 10 sessions and showed real growth: sales up 8% or more on a year ago; a profit and an operating profit, both up on a year ago, with one-off items left out of the operating profit; other income no more than 35% and an exceptional gain no more than 30% of profit before tax; cash from operations positive in the last full year. A lender is tested on its sales, its profit and the exceptional share only. Not already up more than 18% on the day, nor more than 15% under its 200-day average. Ranked half on the day's move against the average stock, a quarter on the volume behind it and a quarter on the growth: a rise on the day is ranked, not required. No list unless eight pass | 21 | close 12% under |
| **Long-term compounders** | Above its 200-day average and outside the most volatile fifth; a profit over the last four quarters, an F-score of 5 or more, no more than 5% pledged, a return on capital of 14% or more, cash from operations positive and at least 0.7 times profit, debt no more than equity (a lender instead: a return on equity of 13% or more), a positive shareholders' equity, and a P/E of 90 or under unless its PEG is 1.5 or under on three-year profit growth of 35% a year or more. Ranked on quality, three-year compounding, governance, valuation against its own industry and the year-long trend | 252 | close 30% under |

Each holds at most four stocks of one NSE industry. A figure a company has not
filed is unknown, never zero: it counts as the middle of the field and skips
only the check that needs it. The results list's profit is the one exception:
a result whose profit is not yet in the filings tables is not listed.

### The protocol, declared before the run

`research/fundamental_ideas_lab.py` replays the engine itself
(`backend/leaders.rank`), not a copy of it, on every fifth session from
January 2017: candidates cut from the price panel at that session, and each
company's figures rebuilt from the filings that had reached the exchange by
that session's close (filed by 15:30 on a trading day, that day; later, the
next). Picks are bought at the next open, as everywhere in this study.

Each list had a few versions, all declared before any run:

| List | Versions |
|---|---|
| Swing / This month | **M0** as specified: leader in the top 35%, the pullback half the month's and half the week's. **M1** M0 without the industry gate. **M2** M0 without the profit and results guards. **M3** M0 with the leader in the top 30% and the pullback over the month alone |
| After results | **R1** the quality gate and the chase guard, ranked on the day's move alone. **R2** R1, and not more than 15% under the 200-day average. **R3** R1, and above the 50-day average. **R4** as specified: R2 ranked half on the move, a quarter on volume and a quarter on growth. **R5** R4 without the floor |
| Long-term compounders | **L1** as specified, with a 30% line. **L2** L1 with a 25% line. **L3** L1 with valuation's weight moved to the trend. **L4** L1's gates with the old long-term ranking, the trend alone |

The rule: on the first window, the highest mean lead over the average liquid
stock after a 0.49% round trip, among versions with enough picks there (400
for the month list, 250 for after results, 300 for long term) and a positive
mean after costs; within 0.05 of a point, the one with fewer rules. The
second window is then printed whatever it shows.

- **Swing / This month and After results**: first window, lists made from
  June 2018 to December 2021; second, from January 2022 to the last list
  whose month had run, 23 October 2026.
- **Long-term compounders**: balance sheets are on file only from September
  2022, so its windows are later: November 2022 to April 2024, then May 2024
  to the last list whose year had run, 17 November 2025. 2018–22, with the
  balance-sheet checks skipped as unknown, is reported for reference only.
  The checks did not all start with the sheets. A check is made only where
  its figure is known, and the lab counts, on every list date from 24 January
  2017 (`coverage` in its file), how many of the liquid companies the list
  ranks, lenders aside, had each figure. Over 2017–21 return on capital, debt
  to equity and the F-score were known for 0% of them on average and cash
  from operations against profit for 9.4%. At least half had cash against
  profit from 28 May 2021 on, debt to equity from 9 November 2022, return on
  capital from 19 May 2023 and an F-score, which needs two year-end sheets
  running, only from 21 May 2024. In the first window the F-score was known
  for 0.4% of them on average, so the version was chosen with its F-score
  floor effectively untested.

What each version did, the lead over the average stock with its t:

| List | Version | Picks, first window | After costs | Lead, first window | Lead, second window |
|---|---|---|---|---|---|
| Swing / This month | M0 | 2,386 | +2.05% | +1.40 (2.2) | +0.26 (0.8) |
| | M1 | 2,647 | +2.13% | +1.40 (2.3) | +0.31 (1.0) |
| | M2 | 2,448 | +2.00% | +1.34 (2.2) | +0.09 (0.3) |
| | **M3, taken** | 2,316 | +2.08% | +1.49 (2.4) | +0.22 (0.6) |
| After results | R1 | 1,261 | +1.90% | +0.86 (1.1) | +0.89 (4.0) |
| | R2 | 1,195 | +1.57% | +1.02 (1.4) | +0.76 (3.4) |
| | R3 | 939 | +1.71% | +0.99 (1.0) | +1.22 (4.1) |
| | **R4, taken** | 1,195 | +1.59% | +1.17 (1.6) | +0.70 (2.7) |
| | R5 | 1,261 | +1.82% | +0.90 (1.2) | +0.84 (3.3) |
| Long-term compounders | **L1, taken** | 1,110 | +49.18% | +4.87 (2.1) | +5.13 (3.9) |
| | L2 | 1,110 | +48.50% | +4.19 (1.9) | +4.33 (3.4) |
| | L3 | 1,110 | +46.23% | +1.92 (2.4) | +0.38 (0.3) |
| | L4 | 1,093 | +45.61% | +1.21 (0.4) | +0.60 (0.3) |

The rule took **M3**, **R4** and **L1**. R4 and L1 are the recipes as
specified. M3 is not: the specification asked for a leader in the top 35%
and a pullback read half over the week, and M3's two values were written back
into `backend/leaders.py`. Before the
record was written, `--publish` re-ranked seven list dates with `leaders.py`
as it stands and found every list the one replayed (21 of 21).

### Before and after, on the same windows

"Before" is each list the new one replaced, replayed on the same dates by
`research/ideas_study.py`'s price recipes. This week is held 5 sessions and
momentum 63, so their averages are not comparable with a month's or a
year's; the lead over the average liquid stock, held over the same sessions,
is. Worst 1 in 20 is the fifth percentile of picks.

**Swing / This month, June 2018 to December 2021**

| | Picks | Rose | Average | After costs | Median | Worst 1 in 20 | vs Nifty 500 | vs the average stock (t) |
|---|---|---|---|---|---|---|---|---|
| **New (M3)** | 2,316 | 56.4% | +2.57% | +2.08% | +1.52% | −13.1% | +1.09 | +1.49 (2.4) |
| This month as it ran (21, 12%) | 2,649 | 56.5% | +2.67% | +2.18% | +1.60% | −13.3% | +1.19 | +1.45 (2.5) |
| This week (5 sessions, 7% line) | 2,653 | 52.7% | +0.53% | +0.04% | +0.27% | −8.0% | +0.21 | +0.41 (2.9) |

**Swing / This month, January 2022 to October 2026**

| | Picks | Rose | Average | After costs | Median | Worst 1 in 20 | vs Nifty 500 | vs the average stock (t) |
|---|---|---|---|---|---|---|---|---|
| **New (M3)** | 3,562 | 50.6% | +1.14% | +0.65% | +0.16% | −14.0% | +0.34 | +0.22 (0.6) |
| This month as it ran (21, 12%) | 3,569 | 51.5% | +1.05% | +0.56% | +0.35% | −13.5% | +0.25 | +0.13 (0.5) |
| This week (5 sessions, 7% line) | 3,615 | 51.1% | +0.29% | −0.20% | +0.09% | −8.6% | +0.08 | +0.22 (2.1) |

**After results, June 2018 to December 2021**

| | Picks | Rose | Average | After costs | Median | Worst 1 in 20 | vs Nifty 500 | vs the average stock (t) |
|---|---|---|---|---|---|---|---|---|
| **New (R4)** | 1,195 | 55.1% | +2.08% | +1.59% | +1.19% | −13.5% | +0.83 | +1.17 (1.6) |
| After results as it ran (21, 12%) | 1,629 | 53.6% | +1.78% | +1.29% | +0.86% | −13.9% | +0.46 | +0.62 (1.1) |

**After results, January 2022 to October 2026**

| | Picks | Rose | Average | After costs | Median | Worst 1 in 20 | vs Nifty 500 | vs the average stock (t) |
|---|---|---|---|---|---|---|---|---|
| **New (R4)** | 1,719 | 54.9% | +1.63% | +1.14% | +1.09% | −13.9% | +0.79 | +0.70 (2.7) |
| After results as it ran (21, 12%) | 1,935 | 54.1% | +1.73% | +1.24% | +1.05% | −13.9% | +0.89 | +0.79 (3.0) |

**Long-term compounders, November 2022 to April 2024**

| | Picks | Rose | Average | After costs | Median | Worst 1 in 20 | vs Nifty 500 | vs the average stock (t) |
|---|---|---|---|---|---|---|---|---|
| **New (L1)** | 1,110 | 81.1% | +49.67% | +49.18% | +37.50% | −30.3% | +23.29 | +4.87 (2.1) |
| Long term as it ran (252, 30%) | 1,099 | 79.9% | +50.24% | +49.75% | +35.84% | −30.5% | +23.86 | +5.54 (3.4) |
| Momentum (63 sessions, 15% line) | 1,110 | 62.9% | +9.65% | +9.16% | +6.09% | −17.2% | +3.35 | −0.54 (−0.5) |

**Long-term compounders, May 2024 to November 2025**

| | Picks | Rose | Average | After costs | Median | Worst 1 in 20 | vs Nifty 500 | vs the average stock (t) |
|---|---|---|---|---|---|---|---|---|
| **New (L1)** | 1,155 | 49.7% | +6.53% | +6.04% | −0.18% | −32.4% | +4.29 | +5.13 (3.9) |
| Long term as it ran (252, 30%) | 1,142 | 44.2% | +10.11% | +9.62% | −4.96% | −32.2% | +7.87 | +8.78 (1.4) |
| Momentum (63 sessions, 15% line) | 1,719 | 46.5% | +1.84% | +1.35% | −1.43% | −18.2% | +1.28 | +0.74 (0.6) |

Read plainly:

- **After results led the average stock in both windows, and in 2018–21 it
  beat the list it replaced on every figure but the number of picks.** Against
  the average liquid stock it was +1.17 a pick in 2018–21 and +0.70 in
  2022–26, against +0.62 and +0.79. In 2022–26 more of its picks rose (54.9%
  against 54.1%) and its median was higher (+1.09% against +1.05%), but its
  average was lower (+1.63% against +1.73%) and so was its lead over the
  average stock. Against the other companies that had just reported, the
  comparison the old list was chosen on, it led by +0.83 (t 2.8). Its tests of
  real growth make it a shorter list: 2,914 picks over the whole replay
  against 3,564, and a list on 205 of the 415 dates tried against 247.
- **Swing / This month made less after costs than the month list it replaced
  in 2018–21, and more in 2022–26**: +2.08% and +0.65% a pick, against +2.18%
  and +0.56% (this week made +0.04% and −0.20%). In 2018–21 it still led the
  average stock by a little more (+1.49, t 2.4, against +1.45, t 2.5). **Its
  lead over the average stock in 2022–26 is small and not distinguishable from
  luck**: +0.22 a pick with a t of 0.6. In those years it also rose a little
  less often than the old month list (50.6% against 51.5%) and its median pick
  made less (+0.16% against +0.35%). Most of its 2018–21 edge did not carry
  over.
- **Long-term compounders rose more often, with a better median, and made less
  on average, in both windows.** In its second window 49.7% of picks rose
  against 44.2% for the long-term list it replaced, the median pick lost 0.18%
  against 4.96%, and its lead over the average stock was +5.13 with a t of 3.9
  against +8.78 with a t of 1.4. But the average pick made +6.53% against
  +10.11%, and in the selection window +49.67% against +50.24%. **The old
  price-momentum list made more on average in both windows**, and in the
  selection window it also led the average stock by more and more steadily
  (+5.54, t 3.4, against +4.87, t 2.1). Its average leaned on its largest
  winners: in the second window its best one in twenty made 78.5% or more,
  against 71.8%.

The record the page prints beside each list is the whole replay, every list
date from 2017 whose hold had finished:

| List | List dates | Picks | Rose | Average | After costs | Median | Nifty 500 | Worst 1 in 20 | vs the average stock (t) | 2017–21 / 2022–26 |
|---|---|---|---|---|---|---|---|---|---|---|
| Swing / This month | 482 | 6,765 | 53.6% | +1.68% | +1.19% | +0.85% | +1.13% | −13.6% | +0.71 (2.3) | +1.20 / +0.22 |
| After results (from June 2018) | 205 | 2,914 | 55.0% | +1.81% | +1.32% | +1.14% | +1.01% | −13.7% | +0.90 (2.7) | +1.17 / +0.70 |
| Long-term compounders | 436 | 6,512 | 58.4% | +21.88% | +21.39% | +9.32% | +13.70% | −32.7% | +5.74 (2.4) | +7.33 / +3.72 |

On the same dates the lists they replaced made +1.76% (this month), +1.75%
(after results) and +23.91% (long term) a pick, and led the average stock by
+0.70 (t 2.5), +0.71 (t 2.4) and +7.88 (t 2.2). Before late 2022 the long list
had no balance sheets to read; see below.

- **They share few names.** On 486 list dates the swing and long-term lists
  shared 2.73 of their fifteen on average (one or more on 92.4% of dates). On
  the 209 dates the results list was made, it shared 1.22 with long term
  (68.9%) and 0.97 with the swing list (51.2%), and the three held 38.9
  different stocks between them. No list gives way to another.
- **The exit lines and the mark say what they said before.** Held with no line
  at all the swing list made +1.80% a pick against +1.68% with its 12% line;
  sold at a mark 12% over, more picks rose (55.2%) and the average fell to
  +1.34%. On long term a mark 30% over raised the share rising from 58.4% to
  65.4% and cut the average from +21.88% to +9.22%. The page prints these
  beside the mark (`leaders.target_tested`); after results has no tested mark.

What to hold against it:

- **The rule chose on the first window, and the second does not always agree
  with it.** On 2022–26 the swing list as specified (M0) led the average stock
  by more than the version taken (+0.26, t 0.8, against +0.22), and so did M1,
  M0 without the industry gate (+0.31, t 1.0). Every other results version did
  better there than R4 (+0.70, t 2.7), and R3, the one that stays above its
  50-day average, did best (+1.22, t 4.1). On long term the two windows agree:
  L1 led every other version in both. Taking any of the others now would turn
  the second window into a second selection, so none is taken; the live record
  is left to settle them.
- **Long term's windows are short.** Eighteen months of list dates in each (74
  and 77), every hold a year long and overlapping its neighbours. A t of 3.9
  on 77 overlapping holds is fragile. Before September 2022 there are no
  balance sheets: return on capital, debt and the F-score were unknown and
  skipped, and on 2018–22 the list led the average stock by +6.64 with a t
  of 1.4. So the 2017–21 half of its record on the page was ranked mostly on
  its trend and its income figures. Nor did the sheets bring every check at
  once: return on capital ran for half the companies only from May 2023 and
  the F-score only from May 2024, so the first window, which chose L1, left
  its F-score floor effectively untested (the protocol above has the dates).
- **Some years were behind the index**: the swing list's lists made in 2017
  and 2025, after results in 2018, 2019, 2022 and 2025, long term in 2017,
  2018 and 2024.
- **Inputs the replay could not test.** Pledges, promoter and institutional
  holdings, delivery surges and order wins have no history to replay. Here
  they were unknown, which every list counts as neutral: no stock was refused
  for a pledge and no catalyst moved a pick. The live lists read them, so a
  live list can refuse a stock, or rank one higher on a catalyst, in a way the
  record never saw.
- **What the filings tables hold.** Balance sheets from September 2022,
  full-year cash flows from 2020–21, quarterly results from mid-2018 (before
  then the swing list's profit guard passed everyone). The tables hold
  companies listed today, so a company delisted after a bad year is missing
  from them (not from the prices), and it then passes a check unread. They
  hold the latest filing for each period: a revised quarter is seen from the
  revision's date, which is later than the original and never earlier, but
  with the revised figures. Industries are NSE's list as it stands today.
- **P/E** is the traded price over the last four quarters' earnings per share
  as filed. It reads low for up to three quarters after a split or bonus, and
  where a filing put the year to date's EPS in a quarter's row, so a stock can
  pass the long list's ceiling of 90 on a P/E that is too low. Why it is not
  restated is under "What the review changed".
- **Thirteen versions were run.** One rule chose among them, declared before
  the run, but some of what passed will have passed by luck.

### What the review changed

A review of the engine led to these changes:

1. **Lenders.** A financial company is one in NSE's Financial Services
   industry, or one whose own filings show bank-format lines, deposits over
   20% of its liabilities or loans over half its assets. For a company outside
   NSE's list, the live scan reads its stored Yahoo sector instead. Such a
   company now carries no operating margin at all, so no list ranks or prints
   one. Before, a lender's margin change counted in all three lists.
2. **Margins leave exceptional items out.** Every margin, and the results
   list's test that operating profit grew, now reads EBITDA without
   exceptional items (core EBITDA). The stored figures had one-off gains in
   them. In one example from the review, a 474 crore exceptional gain made a
   quarter's stored margin 103%.
3. **A negative shareholders' equity** fails the long list's floors and ranks
   last on debt. Before, it had no debt ratio, and the unknown ratio skipped
   the floors.
4. **EV/EBITDA** is worked out only where net debt is known, on core EBITDA.
   Before, a missing net debt counted as none.
5. **The month list's industry gate is the top half by rank**, as specified.
   It had been a money-flow score of 50 or more, which let in industries
   ranked 10th and 11th of 18.
6. **Trailing EPS stays the quarters as filed.** Restating it on profit over
   EPS was tried and dropped. Profit is the group's, minority interests
   included, and EPS is the owners', so the ratio moves with no share issued.
   On the 1,986 companies with a fresh trailing year it restated 173, and only
   40 of those had a recorded split or bonus. A stricter version still
   misfired on about a quarter of what it restated, because some filings put
   the year to date's EPS in a quarter's row. So for up to three quarters
   after a split or bonus the P/E reads low.
7. **The recipe stamp became v4**, and the record was replayed and published
   again. The rule took M3, R4 and L1 again.

What the record now says:

- **Swing / This month** led the average liquid stock by +0.71 a pick (t 2.3):
  +1.20 in 2017–21 and +0.22 (t 0.6) in 2022–26. The replay could pick only
  companies in NSE's industry map as it stands today, and on the same dates
  the liquid stocks in that map beat the average liquid stock by 0.23% a hold
  (0.22% in 2017–21, 0.25% in 2022–26). Against those stocks it led by +0.48
  (t 1.6): +0.98 in 2017–21 and −0.04 (t −0.1) in 2022–26. In 2022–26 it did
  not lead those stocks.
- **After results** led the average liquid stock by +0.90 a pick (t 2.7):
  +1.17 in 2018–21 and +0.70 in 2022–26. Against the companies whose results
  were priced in the same 10 sessions it led by +0.83 (t 2.8): +1.09 (t 1.8)
  in 2018–21 and +0.64 (t 2.7) in 2022–26.
- **Long-term compounders** led the average liquid stock by +5.74 a pick
  (t 2.4): +7.33 in 2017–21 and +3.72 in 2022–26. A check is made only where
  its figure is known. In 2017–21 return on capital, debt to equity and the
  F-score were known for 0% of the companies it ranks, lenders aside, and cash
  against profit for 9.4%, so that half ran without the return, debt and
  F-score checks. In the window that chose L1 the F-score was known for 0.4%
  of them (85.9% in the window after), so it was effectively untested there.
  Its two windows hold 74 and 77 list dates, a list every 5 sessions held 252
  sessions, so each window's Newey-West t (2.1 and 3.9) rests on about one and
  a half independent years: it is indicative only.

## One stock, one list

This section is the record of a decision made on 12 November 2026, with the
figures as they stood that day. Two things have moved since: companies listed
six to twelve months joined the week and momentum lists (momentum now leads
the average stock by +2.15%, t 3.4, where this section says +2.03%, t 3.3),
and a fifth list was added, which shares almost no names with the other four.

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

## What a reader asked for, tested

Mid-November 2026 a reader asked for more in the lists: stocks about to break
out, chart technicals, volume, the state of the market, what results and
other filings do to a stock, the news, and companies with less history. Each
was tested before anything changed (`research/signals_lab.py`). Every trial
was declared before any of them ran, with the rule for taking it into the site
written beside it, and every one is in `research/signals-lab.json`, including
the ones that did nothing. A choice was made on 2017–21 and read on 2022–26,
as before.

About sixty trials ran. That many will throw up a few passes by luck, so a
pass here is a reason to watch the live record, not proof.

### After results: the fifth list

The site's own fundamentals tables hold 47,115 quarterly filings from 2,211
companies since 2018, each with the time it reached the exchange. For each
one, the first session whose close came after the filing is the day the result
was priced (a result filed after 15:30 is priced the next session; two in
three are). What the stock did that session, less the average liquid stock's
move, was set against what it did next. Rank correlation, among companies
that had just reported:

| Measured on the day the result was priced | Next 5 sessions | 21 | 63 |
|---|---|---|---|
| The stock's move against the average stock | 0.066 | 0.066 | 0.058 |
| Volume against its usual | 0.033 | 0.036 | 0.043 |
| Year-on-year profit growth | −0.006 | −0.001 | 0.039 |
| Year-on-year revenue growth | −0.001 | 0.018 | 0.049 |
| Change in operating margin on a year ago | 0.001 | 0.003 | 0.044 |

The move carried about as much as closeness to the 52-week high does at a
month (0.058), and the same in both halves (0.049 and 0.079 at 21 sessions).
The reported growth carried nothing for a month: by the close of that session
the price had already read it.

Five ways of turning that into a list were declared, each at a month and at a
quarter. The rule was that a list is taken only if it led the other companies
that reported in the same ten sessions in both halves. Eight of the ten did.
The one taken is the simplest: the fifteen largest result-day moves, held 21
sessions, left on a close 12% under. It needs only the date of the filing,
its lead was the steadiest of the eight (t 2.9; the others 0.6 to 2.0) and it
was the same size in both halves. **That choice among the ones that passed
was made after seeing them.**

As the site runs it (`ideas_study.py`, which builds the list exactly as
`backend/leaders.py` does):

| After results | Picks | Rose | Average | Nifty 500 | Ahead of other reporters | Ahead of the average stock |
|---|---|---|---|---|---|---|
| 2018–26 | 3,518 | 54% | +1.76% | +1.00% | +0.87% (t 3.0) | +0.71% (t 2.4) |
| 2018–21 | 1,614 | 54% | +1.84% | +1.35% | +0.94% (t 1.6) | +0.61% (t 1.1) |
| 2022–26 | 1,904 | 54% | +1.69% | +0.70% | +0.81% (t 3.3) | +0.80% (t 3.0) |

Half the picks made less than +1.0% and one in twenty lost more than 14%. The
exit line was reached on 16% of them. A line 6% under cut the average to
+1.4%; one 18% under gave +1.8% and a worse tail.

What to hold against it:

- **The results table holds companies listed today.** One delisted after a
  bad quarter is missing, which flatters any results test. That is why the
  first comparison is with the other companies in the same table, which share
  the bias. The comparison with the average stock on the whole exchange
  (delisted companies included) is beside it.
- **The first half alone is not convincing** (t 1.6 and 1.1). Most of the
  evidence is 2022–26.
- **It trailed the index in lists made in 2018, 2019 and 2022.**
- **It is a list for the weeks companies report.** On 167 of 411 dates fewer
  than eight liquid companies had reported in the last ten sessions, and there
  was no list.
- **No uptrend gate.** A falling stock that jumps on its numbers is on it.
  The variants that added the uptrend gate tested no better over a month.

### Younger companies

The lists never needed ten years of a company's history. They needed one: a
12-month return requires a price from a year ago. The decade is how far back
they were tested, and that test took in every company from its first
anniversary, including the ones later delisted.

What was left out was any company listed under a year. Three trials:

**Six to twelve months, on the price lists.** About twelve liquid companies a
day are that young. For them the 6-month return stands in for the 12-month
one, and volatility, the 52-week high and the 200-day average are taken over
the history there is. The rule: admitted to a list only if the picks that
were that young led the average liquid stock in both halves.

| List | Young picks | Rose | Average | Ahead of the average stock | 2017–21 | 2022–26 | |
|---|---|---|---|---|---|---|---|
| This week | 131 | 53% | +0.93% | +1.12% | +0.96% | +1.23% | admitted |
| This month | 84 | 52% | +1.16% | +0.36% | +3.07% | −1.19% | not |
| Momentum | 125 | 58% | +7.20% | +5.42% | +6.17% | +4.75% | admitted |
| Long term | 42 | 52% | +6.64% | −6.16% | −11.93% | +7.80% | not |

So they are on the week and momentum lists and no other. As the site runs it,
a young company is placed against the established universe (its percentile on
each measure is the share of established stocks at or below its figure), so
letting them in changes no established stock's score and the month, long-term
and results lists are exactly what they were. Measured that way: 123 young
picks on the week list (+1.08% ahead of the average stock, t 2.1; +1.05% and
+1.09% by half) and 177 on momentum (+5.29% ahead, t 1.3; +7.39% and +3.20%).
The momentum list as a whole went from +5.50% a pick to +5.61%.

**These are small samples.** A hundred and seventy-seven picks in ten years,
with a t of 1.3, passes the rule that was set and would not pass a stricter
one. The young picks are also few: about one pick in forty on momentum and one in
sixty on the week list.

**Three to twelve months, on the results list.** Not admitted. The 152 young
picks rose 40% of the time and averaged −0.6%; they trailed the other
reporters in 2018–21 (−2.2%).

**Under six months.** Nothing ranks them. There is no 6-month return to rank
on, and the one list that needs no price history is the one they did worst on.

### What did not earn a place

**Breakouts.** Nine recipes, held 21 sessions with an exit line 10% under:
stocks coiled under their high (a tight fortnight, volume dried up), fresh
six-month and 52-week closing highs with and without 1.5 times the usual
volume, breakouts from a tightened range, and leaders doing either. A "fresh"
high is the first in at least 20 sessions. The rule: the best on 2017–21 among
those making eight picks a list, taken only if it also led on 2022–26.

| Recipe | Picks a list | Rose | Average | Nifty 500 | Ahead of the average stock | 2017–21 | 2022–26 |
|---|---|---|---|---|---|---|---|
| Coiled under the high | 13.5 | 52% | +1.08% | +0.99% | +0.07% | +0.59% | −0.46% |
| A coiled leader | 7.3 | 51% | +1.23% | +1.01% | +0.58% | +1.80% | −0.66% |
| Accumulation near the high | 14.7 | 52% | +1.29% | +1.04% | +0.29% | +0.73% | −0.16% |
| Fresh 6-month high | 7.6 | 51% | +1.01% | +1.05% | −0.11% | −0.03% | −0.18% |
| Fresh 6-month high on volume | 6.6 | 50% | +0.99% | +0.99% | −0.23% | −0.29% | −0.17% |
| Breakout from a tight base | 3.8 | 51% | +1.11% | +1.12% | −0.16% | −0.43% | +0.08% |
| A leader breaking out | 4.1 | 50% | +0.88% | +1.17% | +0.16% | +0.51% | −0.16% |
| Fresh 52-week high | 5.9 | 51% | +0.92% | +1.00% | +0.13% | +0.47% | −0.18% |
| Fresh 52-week high on volume | 4.9 | 51% | +0.93% | +0.93% | −0.11% | +0.20% | −0.37% |

None was taken. About half the picks rose, the average pick made what the
index made, and eight of the nine trailed the average stock in 2022–26. Held
42 sessions two of them looked better (+1.2% ahead), but 21 was the hold
declared, and choosing the hold after seeing the results is how a study finds
whatever it is looking for. What the lists already use, closeness to the
52-week high, is the part of a breakout that carried information; the
breakout itself, and the volume on it, added nothing to it.

**Indicators and volume, one at a time.** Rank correlation with the next 5,
21 and 63 sessions, every stock trading ₹5 crore a day:

| Measure | 5 | 21 | 63 |
|---|---|---|---|
| Closeness to the 52-week high (already used) | 0.036 | 0.058 | 0.097 |
| Closeness to the 60-day high | 0.020 | 0.034 | 0.070 |
| Above the 20-, 50- and 200-day averages, in order | 0.010 | 0.032 | 0.053 |
| Narrow Bollinger bands (which is low volatility) | 0.035 | 0.034 | 0.033 |
| ADX(14) | 0.001 | 0.009 | 0.022 |
| RSI(14) | −0.011 | 0.002 | 0.034 |
| MACD histogram | −0.018 | −0.013 | −0.001 |
| Price above its 20-day average | −0.020 | −0.005 | 0.028 |
| Volume today against its usual | −0.019 | −0.002 | 0.009 |
| More volume on up days than down days | −0.017 | −0.006 | 0.014 |
| A tightened range | 0.007 | −0.002 | −0.010 |
| A fresh 6-month closing high | 0.001 | 0.003 | 0.005 |

The top three rows are the trend the lists already rank on, and the fourth is
low volatility, which they use as a gate. Below those, nothing reaches 0.015
at a month.

**Indicators and volume as a confirmation.** Each of seven (RSI between 50
and 70, MACD above its signal line, ADX at 25 or more, a close above the
20-day average, more volume on up days, volume above its usual, a tightened
range) was tried as a gate or a quarter-weight tilt on the week, month and
momentum lists: twenty-one trials. The rule: added only if it raised the
list's lead over the average stock in both halves. On the week list all seven
lowered it. One of the twenty-one passed, the 20-day average on momentum,
which moved the lead from +2.03% to +2.08%. One pass in twenty-one of that
size is what luck looks like, so it was not added.

**Holding a list back in a weak market.** The rule: only if the picks made in
that state lost money on average in both halves. They did not. The Nifty 500
was under its 200-day average on a quarter of days:

| List | Picks made above it: rose, average | Picks made under it: rose, average |
|---|---|---|
| This week | 52%, +0.37% | 54%, +0.61% |
| This month | 52%, +1.48% | 60%, +2.58% |
| After results | 54%, +1.88% | 54%, +1.43% |
| Momentum | 53%, +4.46% | 65%, +9.43% |
| Long term | 55%, +22.3% | 68%, +28.7% |

Four of the five did better when the list was made in a weak market: a leader
bought after the market has fallen has further to recover. The old Ideas page
printed "trend setups fail more often here" whenever the index was under its
50-day average. Measured on these lists that was not so, and the page now
prints what was measured.

**A lower turnover floor.** ₹5 crore a day (534 stocks on a median day) and
₹3 crore (660) against ₹10 crore (386). The rule: lowered only if every list
led its own wider universe's average stock by at least as much in both halves.
Month and momentum did a little better on the wider universes; the week list
did worse in 2022–26 (+0.05% at ₹5 crore against +0.22%), and so did the
results list. The floor stays. Thinner stocks also cost more to trade than
this test charges anyone.

### Filings, orders and the news

Results are the one filing with eight years of dated history to test on, and
they are now a list. For the rest there is no such history: the order ledger
goes back a hundred and twenty days, and no archive of news exists to replay.
So they are shown beside a pick and rank nothing:

- an order the company disclosed, with its size against the company's market
  value (read out of the filing by `wow_orders.py`);
- the latest filing by category, and a serious adverse one still removes the
  stock from every list;
- press coverage, labelled as press, which by the site's own rule never
  touches a score;
- the chart and volume measurements above, and the clearest classical chart
  pattern in the bars, under a line that says none of them changes a rank.

Each scan banks the same measurements for every stock it analyses (the
indicators, the breakout flag and its volume, the result-day move), with what
the stock then did. That is how the live record gets to overrule this test.

## Two tabs: short term and long term

*The page showed these two tabs for one day and then went back to ten at the
owner's request. The short-term list below is still ranked by the engine and
answers on the API; it has no tab. Its trials and record stand as written.*

The page had grown to ten tabs. A reader asked for two, and for the
short-term one to be a single list: stocks that have consolidated and are
breaking out or about to, picked on fundamentals, technicals, the industry
and the news together, with the highest hit rate that can honestly be had.

### What was tried

`research/short_term_lab.py` declared sixty versions before running any:
two pools (a breakout from a tight 40-session base that is still holding;
a stock still inside such a base within 3% of its top), five screens added
one at a time and together, and two exits. Picks are the top twelve a list
date. Figures are a month's hold with a close 8% under as the exit,
against the Nifty 500 over the same sessions.

| Version | Picks | Rose | Average | Lead (t) | 2017–21 rose / lead | 2022–26 rose / lead |
|---|---|---|---|---|---|---|
| Breakout, trend and strength only | 1,938 | 52.5% | +1.22% | +0.42 (1.4) | 53.8% / +0.17 | 51.6% / +0.63 |
| + industry in the top half on money flow | 1,318 | 54.6% | +1.57% | +0.87 (2.6) | 58.8% / +0.64 | 52.3% / +1.06 |
| + chart, industry, no fall in profit, results not sold | 1,067 | 54.5% | +1.46% | +0.94 (3.4) | 58.4% / +0.95 | 52.0% / +0.92 |
| + profit AND sales both up (strict) | 667 | 55.2% | +1.88% | +1.18 (3.3) | 63.1% / +1.37 | 53.4% / +1.12 |
| On the verge, trend and strength only | 3,674 | 50.7% | +0.89% | −0.06 (−0.2) | 53.2% / +0.40 | 48.7% / −0.50 |
| On the verge, every screen | 1,913 | 49.4% | +0.61% | −0.15 (−0.5) | 53.6% / +0.50 | 46.8% / −0.71 |
| Both pools, every screen | 2,674 | 51.1% | +0.89% | +0.09 (0.4) | 54.8% / +0.62 | 48.5% / −0.37 |

What this says:

- **The industry is the screen that matters.** A breakout in an industry
  money is moving into did better than a breakout anywhere, in both halves.
  The chart conditions, the profit screen and the results screen added
  little on top; none of them hurt.
- **"On the verge" did not work.** Bought before the breakout, such stocks
  rose as often as a coin lands heads and trailed the index in 2022–26,
  with every screen applied or none. So the list waits for the breakout,
  and stocks on the verge are shown under it to watch, said plainly not to
  be picks.
- **A ten-session hold was worse than a month** for every version.

The rule declared beforehand (most picks rising in 2017–21, among versions
with 400 picks there and a positive lead) chose "breakout + industry"
(58.8%). The list that was built is the third row: the full combination
that was asked for. It scored 58.4% on the same rule, a difference of two
picks in five hundred, and was the steadiest across the two halves. The
strict-fundamentals row has the best figures and too few picks to trust
(122 in 2017–21, because quarterly filings start in 2018), and would leave
the list empty on half of all days.

### What the page prints

The engine itself replayed (`ideas_study.py --setups`), every fifth session
from 2017 to 2026, its top fifteen bought at the next open:

| | Picks | Rose | Average | Median | Nifty 500 | After costs | Against the average stock (t) | 2017–21 / 2022–26 |
|---|---|---|---|---|---|---|---|---|
| **Short term** | 1,009 | 53.8% | +1.38% | +0.81% | +0.80% | +0.89% | +0.97% (2.5) | +1.13 / +0.84 |

Read plainly: **54 picks in 100 rose over a month. That is the highest hit
rate any tested version of this idea reached on a usable number of picks,
and it is not high.** The edge is in the average (about one percentage
point a month over the average stock, in both halves), not in being right
most of the time. One pick in five hit its exit line. Years differ widely:
67 in 100 rose in 2023, 34 in 100 in 2022, and 47 in 100 so far in 2026.
The list is short, about three names when there is one, and on roughly
three list dates in ten there is none.

Two things flatter the record. Industries are NSE's list as it stands
today, and quarterly results cover companies listed today and start in
2018, so before then the profit screen passes everyone.

**Long term** is the list it was: steady year-long climbers near their
highs, held about a year with a close 30% under as the exit (58 in 100
rose, +23.7% against +13.8% for the index). The other eight lists are
still ranked and still answer by name on the API; the page no longer asks
a reader to choose between them.

## The setup lists

Five more lists were asked for by name: stocks breaking out of a
consolidation on volume, stocks picked on technicals, quick trades, stocks
where money is flowing, and emerging companies. An earlier round of this
study tested ideas like these as *improvements to the horizon lists*, found
none improved them, and left them off the page. That answered a question
nobody had asked. They are built now as lists of their own, each with the
record it earned printed beside it, whatever that record is.

`research/setups_lab.py` declared several versions of each before running
any, chose on 2017–21 and read 2022–26. The chosen version went into
`backend/leaders.py`. The record on the page is not the lab's: it is the
engine itself replayed (`ideas_study.py --setups`), run on every fifth
session from frames cut at that session, its top fifteen bought at the next
open.

| List | The rule | Hold, exit |
|---|---|---|
| **Breakouts** | 40 sessions inside a range 18% wide or tighter, then a close above its top on 2× usual volume in the last five sessions; above the 200-day average; leader score in the top half | 21 sessions, close 8% under |
| **Technicals** | 7 or more of 9 conditions: above the 20-day average, 20 above 50, 50 above 200, RSI over 55, MACD above signal, ADX ≥ 25 with buyers ahead, more volume on up days, this week's volume above usual, within 5% of the 52-week high | 21 sessions, close 10% under |
| **Quick trades** | In an uptrend, leader score in the top 30%, two-day RSI under 10 | Sold at the first close above the 5-day average, at most 7 sessions, close 7% under |
| **Money flow** | Sectors ranked on turnover share (this week against sixty sessions), share of stocks above the 50-day average, and median month; the four strongest stocks in each of the top four | 21 sessions, close 10% under |
| **Emerging** | Listed six to twelve months, above its own 50-day average, leader score in the top half of the established market | 21 sessions, close 10% under |

### How they tested

Engine replay, 2017–2026, 483 list dates tried, before costs:

| List | Picks | Rose | Average | Median | Nifty 500 | After 0.49% costs | Against the average stock (t) | 2017–21 / 2022–26 |
|---|---|---|---|---|---|---|---|---|
| Breakouts | 2,308 | 51.4% | +1.05% | +0.38% | +0.91% | +0.56% | +0.49% (1.3) | +0.75 / +0.25 |
| Technicals | 6,936 | 51.7% | +1.29% | +0.46% | +1.05% | +0.80% | +0.36% (1.3) | +0.49 / +0.22 |
| Quick trades | 3,403 | 65.1% | +0.35% | +1.07% | +0.06% | **−0.14%** | +0.27% (2.5) | +0.41 / +0.14 |
| Money flow | 6,581 | 52.4% | +1.39% | +0.53% | +1.10% | +0.90% | +0.40% (1.3) | +0.87 / **−0.07** |
| Emerging | 1,403 | 48.8% | +1.51% | −0.43% | +0.75% | +1.02% | +0.40% (0.5) | +1.12 / **−0.14** |

Read plainly:

- **None of these is a strong edge.** Four of the five led the average liquid
  stock by under half a percent a pick with a t-statistic near 1.3, which is
  not distinguishable from luck. The horizon lists above did better on the
  same test.
- **Quick trades have the highest hit rate and lose money after costs.**
  Two picks in three rose, over about three sessions, and the average gain
  (+0.35%) is smaller than the cost of a round trip (0.49%). In 2022–26 the
  average pick was flat before costs. The page says this above the list, not
  inside a fold.
- **Money flow and Emerging trailed the average stock in 2022–26.** Both led
  in 2017–21 and gave it back. Emerging's median pick lost money: a few large
  winners carry its average.
- **Breakouts** kept a small lead in both halves. About one list date in
  eight had no breakout to show; the list is then empty and says why.

The exit used for Breakouts (21 sessions or a close 8% under) was chosen
after seeing that the textbook exit, "sell on a close back inside the base",
left 31% of picks up and a lead of +0.27%. That choice was made on the whole
period, so its record flatters it a little. The sector map is NSE's list as
it stands today: a company since delisted has no sector and could not be a
money-flow pick, which flatters that list too.

Under the breakout list the page also shows **Setting up**: tight bases not
yet broken, nearest their top first. Those are watched, not picked, and have
no record.

### Rebuilt, December 2026

A reader named four faults in these lists, and each was measured before
anything changed (`research/setups_lab.py --v2`, every version declared
before the run, all in `research/setups-lab-v2.json`):

1. **They left too early.** Every list was out within 7 to 21 sessions on a
   7–10% stop. Held 63 sessions on a 12% stop, the *same old picks* made
   several times as much after costs: the old technical scorecard went from
   +0.84% to +4.40% a pick, the old breakout from +0.65% to +2.90%. A few
   picks in ten that make 25% or more carry an average, and a month is too
   short for them.
2. **The quick trade lost money after costs** (−0.20% a pick in the lab,
   −0.14% in the replay), however often it rose.
3. **The breakout missed early launches.** It wanted a 40-session base 18%
   wide or tighter in a stock already in the top half of 12-month leaders.
   RATNAVEER's July 2026 breakout (a 40-session base 24% wide whose last
   fortnight spanned 44% of its range, volume down to 0.57 of usual) never
   qualified; nor did HFCL's April 2026 turn (a 60-session base 29% wide).
4. **Technicals and money flow bought stretched stocks**, and money flow
   ignored how long a sector's turn takes.

The rule, set before the run: for each list the version taken is the best on
2017–21 among the *new* versions (lead over the Nifty 500 for breakouts,
technicals, money flow and emerging, among versions with a pick on a quarter
of sessions, 150 picks in 2017–21 and a profit after costs; for quick trades
the most picks rising among versions with a profit after costs and a lead
over the index). The version shipped until now is measured beside it.

| List | What was taken | Hold, exit |
|---|---|---|
| **Breakouts** | VCP launchpad: a close above a 40- or 60-session base 28% wide or less that was 20% or tighter or tightened before the break (squeeze, the last fortnight's range, or volume drying up), on 1.6× volume, closing in the top 45% of the day; above the 200-day, 50-day ≥ 98% of it; leader ≥ 45; industry in the top 60% on money flow; a month better than the Nifty 500's; not more than 16% over the 50-day or 55% up in three months; no profit fall over 10% or results sold | 63 sessions, close 12% under |
| **Technicals** | Early Stage-2 pullback: price and 50-day above a rising 200-day, leader ≥ 55; a low within 1.5% of the 20-day average in three sessions and a green close 0–6% above it; RSI 48–68; industry in the top half; no profit fall over 10% | 63 sessions, close 12% under |
| **Swing dips** (was Quick trades) | Uptrend, leader in the top 35%, a two-day RSI under 10 or a 4% fall in five sessions, still within 3% of the 50-day, results not just sold | 21 sessions, close 10% under |
| **Money flow** | Top three sectors on rotation (three-month median move 45%, share above the 50-day 35%, turnover shift 20%); in each, the five strongest stocks in an uptrend, outside the most volatile fifth, within 15% of their high and ahead of the Nifty 500 over one month and three | 63 sessions, close 15% under |
| **Emerging** | Listed 6–18 months; above a rising 50-day average, within 10% of its high, leader ≥ 60, ahead of the Nifty 500 over one month and three, not more than 18% over the 50-day; no loss or fall in sales last quarter where one is on file | 90 sessions; after 15, a close under the 50-day; a close 15% under |

What the rule took that the reader did not ask for, said plainly:

- **Breakouts are pattern A alone.** A or B led by 1.6 points on 2017–21, A
  alone by 2.2, B alone by 0.5 (B did best of the three on 2022–26, 1.8,
  which the rule may not look at). B, the base turnaround, is measured on
  every stock, listed under the breakouts as *Setting up*, and one constant
  away (`leaders.LAUNCH_PATTERNS`).
- **Money flow has no anti-chasing screen.** The version without it led by
  2.6 points on 2017–21 against 2.4 with it.
- **Emerging leaves on the 50-day average.** On 2017–21 it led 63 sessions
  with a 15% line by 5.23 points against 5.17: a tie the rule broke. On
  2022–26 the 63-session version did better (3.9 against 2.9).
- **The technical list is the pullback the reader asked for, but the old
  scorecard held 63 sessions did better in both halves** (lead +2.30 / +2.23
  against +2.22 / +1.34 in the lab). The rule chose among the new versions;
  the comparison stands in the lab's output.

**The market-weather screen** (Nifty 500 above its 50-day average) was tried
on breakouts, swing dips and emerging. It did not raise both the share of
picks rising and the average after costs in both halves for any of them,
so no list is held back in a weak market. On breakouts it raised the lead in
both halves but cut the share rising on 2017–21 by a tenth of a point.

Engine replay, every fifth session, 486 list dates tried, after 0.49% costs:

| List | Picks | Rose | 25%+ winners | After costs | Nifty 500 | Against the average stock (t) | 2017–21 / 2022–26 | Before (after costs) |
|---|---|---|---|---|---|---|---|---|
| Breakouts | 2,131 | 52.6% | 10.4% | **+3.11%** | +2.39% | +1.70% (2.0) | +3.40 / +0.11 | +0.56% |
| Technicals | 5,637 | 49.3% | 13.7% | **+3.86%** | +3.30% | +0.96% (1.3) | +2.53 / **−0.72** | +0.80% |
| Swing dips | 4,439 | 50.9% | 4.0% | **+0.87%** | +1.07% | +0.81% (2.5) | +1.31 / +0.32 | **−0.14%** |
| Money flow | 5,629 | 55.5% | 13.9% | **+4.94%** | +3.32% | +2.12% (2.5) | +3.17 / +1.01 | +0.90% |
| Emerging | 736 | 38.6% | 11.8% | **+4.20%** | +2.18% | +3.77% (1.8) | +7.08 / +1.12 | +1.02% |

The Nifty 500 column is larger than before because the holds are longer;
compare a list with the index and the average stock over the same sessions,
not with its old self alone. Read plainly:

- **Money flow is the strongest of the five**: ahead of the average stock in
  both halves by a point or more, and more than half its picks rose.
- **Swing dips now keep a profit after costs**, in both halves, at the price
  of a hit rate near half where it was two in three.
- **Breakouts and technicals are mostly a 2017–21 result.** Against the
  average stock on the same days, breakouts were level in 2022–26 (+0.08) and
  technicals behind it (−0.72, with fewer than half the picks rising).
- **Emerging is carried by a few large winners.** Six picks in ten fell; the
  median pick lost 3%. Only 292 of 486 dates had a list, 2.5 names on average.
- The lab picked every day; the replay is the engine every fifth session,
  with its own order, so the two do not print the same figures. The page
  prints the replay's.

**The two stocks a reader named**, replayed through the old and new rules
(every date the rule fired on the stock, whether or not it made the top 15):

- **RATNAVEER**: the new breakout fired on 27 Jul 2026, bought at ₹202.28,
  +71.7% over the 63 sessions it was held, as a VCP launchpad. The old
  breakout never fired. The old technical bought the same day and was
  stopped out at −10.3% four sessions later; the new pullback bought on 6 Jul
  2026 at ₹181.00 and was +87.5% at 63 sessions.
- **HFCL**: the old breakout never fired. The new one fired three times since
  2022: 31 Oct 2022 (VCP launchpad, ₹83.15, stopped at −13.4%), 7 Aug 2023
  (base turnaround, ₹73.80, stopped at −12.1%) and 9 Apr 2026 (base
  turnaround, ₹80.40, **+167%** in 63 sessions). The 2026 move came from
  pattern B, which the shipped list does not pick from. The late-2023 and
  mid-2024 rallies were not caught by either version.

### Sector breakout and live catalysts

A reader pointed out that RATNAVEER's and HFCL's moves came with their
industry breaking out and with news: orders, an earnings call, the press.

**Sector breakout** can be tested. `research/setups_lab.py --sector` builds
each NSE industry's own index (the mean daily move of its liquid stocks,
chained) and declared two screens before the run: the index at a new
60-session high in the last 10 sessions, or within 3% of that high. The rule:
adopt a screen on a list if it raises the 2017–21 lead over the Nifty 500,
keeping a profit after costs and enough picks
(`research/setups-lab-sector.json`).

| List | As shipped (lead 2017–21 / 2022–26) | New high in 10 sessions | Within 3% of the high | Adopted |
|---|---|---|---|---|
| Breakouts (pattern A) | +2.22 / +1.35 | +2.25 / +0.84 | +2.26 / +1.33 | **within 3%** |
| Breakouts (A or B) | +1.62 / +1.19 | +1.88 / +1.26 | +1.86 / +1.47 | (B is off) |
| Technicals (pullback) | +2.22 / +1.34 | +1.82 / +0.47 | +2.14 / +0.75 | none |

The breakout list now asks for the stock's industry to be within 3% of its
own 60-session high. The gain is small and honest: replayed, the list made
**+3.11%** a pick after costs against +2.87% without the screen, 52.6% of
picks rose against 51.9%, and it led the average stock by +1.70 against
+1.60, a little more in each half. A stock with no industry on NSE's list
passes; RATNAVEER is one. HFCL's industry, Telecommunication, was at a new
high on 9 Apr 2026 and on 7 Aug 2023, and not on 31 Oct 2022. Every
sector on the money-flow table now shows its own index against that high.

**Concalls, orders and news** cannot be tested here: the site reads them as
they arrive and keeps no ten-year history of them. They are shown on each
setup pick as **Catalyst** facts:
- the newest earnings call read in the last 100 days, with its brief's headline;
- the largest order disclosed in the last 45 days, against the company's
  market value;
- the last week's news, rumours left out.

A pick with a fresh catalyst moves up its own list (an order worth 1% or more
of the company counts most). A catalyst never puts a stock on a list or takes
one off, so the tested record still describes exactly the stocks on it. The
watch list shows each base's catalyst too.

## The daily brief

`backend/policy_brief.py` reads every new DGFT notification, public notice,
circular and trade notice, RBI press release and notification, SEBI circular
and English PIB release three times each weekday
(`.github/workflows/policy-brief.yml`). Each is read once. With
`ANTHROPIC_API_KEY` set, Claude reads it (the PDF itself for DGFT) and
returns a summary, the direction, the sectors and the stocks with a reason;
symbols NSE does not list are dropped. Without a key a keyword table names
sectors and a direction and no stocks, and the brief says which did the
reading. `brief.html` shows it; the evening run emails it to digest
subscribers on days something matters.

**It has no tested record and cannot have one yet.** There is no archive of
past circulars with timestamps to replay against prices, so how well a read
predicts a move is unknown. It changes no rank on any list. As the brief
accumulates, each read can be scored against what the named stocks did next;
that study is the next thing to build here.

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

*For the three lists the page leads with since December 2026, see "What to
hold against it" under "Three fundamental lists". The points below were
written for the five lists they replaced and for the setup lists.*

- **Barely more than half the picks rose.** The edge is in the size of the
  winners. Anyone holding two or three picks from a list is not holding the
  list.
- **The one-week edge is about 0.15% a week before costs.** After a 0.49%
  round trip the average week pick lost 0.07%. It is the weakest list to hand
  to anyone who pays to trade.
- **Some years were flat or behind.** Momentum trailed the index for lists
  made in 2022 and only matched it in 2025. This month trailed it in 2024 and
  2025 and matched it in 2017. The long-term list trailed for 2017, 2018 and
  2024. The results list trailed for 2018, 2019 and 2022.
- **In 2022–26 the month and momentum lists barely led the average stock**
  (+0.11% and +0.33%). Their lead on the Nifty 500 in those years was mostly
  the lead small and mid-sized companies had on large ones.
- **Two of the four recipes were changed after results were seen**, to stop
  the lists repeating each other (see "One stock, one list"). The results
  list's hold was chosen after seeing eight variants that passed.
- **The results list rests on a table of today's companies**, and most of its
  evidence is 2022–26.
- **The young picks are a small sample**: 123 on the week list and 177 on
  momentum in ten years.
- **About sixty more trials were run in November 2026.** Some of what passed
  will have passed by luck.
- **Picks are often small and mid-sized companies.** A larger-companies-only
  variant tested worse, so it was not used.
- **The page caps one sector at four names and removes serious adverse
  filings.** Neither was in the test.
- **Orders, other filings, press and the chart facts are shown and not
  tested.** They rank nothing for that reason.
- **It is ten years of one market.** It is not a forecast.

## The live record

The call log dates every pick and keeps the exit line it was called with. The
daily job (`.github/workflows/ideas.yml`) runs the scan after the close, marks
the tracker and attaches forward returns. Before it existed the store held
350,000 observations and no measured outcomes.

## Reproducing it

```bash
python research/ideas_study.py --fetch      # NSE daily files and the results table, once
python research/ideas_study.py --build      # adjusted price panel
python research/ideas_study.py --baseline   # replay the old ranking (about 30 minutes)
python research/fundamental_ideas_lab.py --prepare   # the engine's candidates on every fifth session (about 8 minutes)
python research/fundamental_ideas_lab.py --replay    # every declared version, through the engine (about 2.5 minutes)
python research/fundamental_ideas_lab.py --report    # the windows and the choice: research/fundamental-ideas-lab.json
python research/fundamental_ideas_lab.py --publish   # the chosen versions' records, into research/ideas-study.json
python research/ideas_study.py --study      # tables and research/ideas-study.json
python research/separation_lab.py           # every trial behind "One stock, one list"
python research/signals_lab.py              # every trial behind "What a reader asked for"
python research/short_term_lab.py           # every trial behind "Two tabs"
python research/setups_lab.py               # every trial behind "The setup lists"
python research/setups_lab.py --v2          # every trial behind "Rebuilt, December 2026"
python research/setups_lab.py --sector      # the sector-breakout screens
python research/ideas_study.py --setups     # the setup lists' records alone, into the same file
```

The fundamental lab needs the filings tables beside the price panel:
`income_quarterly_full.csv`, `income_annual.csv`, `balance.csv` and
`cashflow.csv` in the data folder, from the same `/fundamentals/table`
endpoint as the results table (`--fetch` downloads only the quarterly one),
and NSE's industries (`IDEAS_SECTORS_CSV=backend/nse_industries.csv` when the
data folder has none). `--replay` runs every version as overrides of the
recipe as specified (`SPEC`), so it replays the same versions now that M3 is
the default. `--publish` first checks that the cached candidates still carry
the values `signals()` gives and that `leaders.rank` with today's defaults
ranks what the chosen versions picked on seven list dates, and stops if
either differs. It then writes the three lists' records, their exit lines and
their overlap, moves this week's and momentum's records under `retired`,
keeps the old overlap as `overlap_before`, stamps the file with the recipe
(`2026-12 fundamental lists v4`) and leaves every other key as it was.

`--study` first checks that `backend/leaders.py` still reads the market the
way the price recipes here do, stock by stock, on eighteen past dates: six
spread over the decade, six on which a young company made a list and six on
which the results list was made. Every established liquid stock must have the
same leader score, uptrend, calm and dips, every young company the same
place, and every company that had just reported the same move against the
average stock that session. It stops if any differs. The engine no longer
runs the price lists, so this is what can still be held equal. The three
fundamental lists have no second implementation to check: `--study` takes
their records from the lab's replay, with the same check `--publish` makes,
or without a replay keeps the records the file last held for this recipe.

`--fetch` downloads the results table from the site's own API. Without it the
lab cannot replay the lists and `--study` keeps the three lists' records it
last wrote for this recipe, and says so; without the half-hour `--baseline`
replay it keeps the last "what was wrong" table.
