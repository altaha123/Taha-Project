# The Ideas study

November 2026. Why the Ideas list was losing, what replaced it, and how well the
replacement tested. Every number here is produced by `research/ideas_study.py`
and stored in `research/ideas-study.json`; the Ideas page reads the same file.
The trials behind "One stock, one list" are in `research/separation_lab.py`
and `research/separation-lab.json`. The trials behind the fifth list, the
younger companies and everything in "What did not earn a place" are in
`research/signals_lab.py` and `research/signals-lab.json`.

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

Momentum held six months instead of three, on a line 20% under: 57% rose,
+9.9% a pick against +6.4% for the index.

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
python research/ideas_study.py --study      # tables and research/ideas-study.json
python research/separation_lab.py           # every trial behind "One stock, one list"
python research/signals_lab.py              # every trial behind "What a reader asked for"
python research/short_term_lab.py           # every trial behind "Two tabs"
python research/setups_lab.py               # every trial behind "The setup lists"
python research/ideas_study.py --setups     # the setup lists' records alone, into the same file
```

`--study` first checks that `backend/leaders.py` picks the same stocks the
study picked: 810 picks, on six past dates for the four price lists, six on
which a young company made a list and six on which the results list was made.
It stops if they differ. It also stops if the young picks no longer lead the
average stock in both halves on a list that admits them.

`--fetch` downloads the results table from the site's own API. Without it
`--study` keeps the results record it last wrote and says so; without the
half-hour `--baseline` replay it keeps the last "what was wrong" table.
