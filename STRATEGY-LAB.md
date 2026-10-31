# Strategy lab: what quants.md is, what we took, and what we left

The Strategy lab (Ideas › Strategy lab, `#research/strategies`) runs eleven
textbook trading rules on any stock's own daily history. It measures them the
way quants.md measures its library and sets each one beside buying and holding
the same stock. This file covers what quants.md is, what its numbers say, what
the lab borrowed from it, what it added for an Indian investor, and what it
deliberately left out.

| file | what it does |
| --- | --- |
| `backend/strategy_lab.py` | The rules, the execution model, the metrics, tax, the luck bar and a small cache |
| `main.py` → `GET /strategies?ticker=&years=&cost=` | The report. `years` is 3, 5, 10 or 15; `cost` overrides the round trip in percent |
| `frontend/strategy-lab.js`, `strategy-lab.css` | The tab: verdict, growth and underwater charts, sortable table, compare, detail, calculators, glossary |
| `stock.html` (Chart pane) | A link into the lab with the stock filled in (`index.html?go=strategies&lab=SYM`) |
| `backend/tests/test_strategy_lab.py` | No lookahead, execution arithmetic, tax, luck bar, endpoint, the no-directive line |
| `frontend/tests/strategy-lab-browser.cjs` | Sorting, filtering, compare, calculators, errors, phone width, in a real browser |

---

## 1 · What quants.md is

An open library of **50 trading strategies**, each with a backtest, a results
dashboard and the Python that produced it. It was read on 31 Oct 2026.

- **Source:** the example suite of the QuantJourney backtester, licensed
  Apache-2.0. The site is published by AgenKit, which sells a kit for turning
  a strategy into a trading bot inside an AI coding tool, plus a $9.99
  "Portfolio Builder" spreadsheet.
- **Three families:** *Orders* (O01–O20) place explicit market, limit, stop,
  stop-limit, trailing, bracket and OCO orders. *Weights* (W01–W25) set target
  portfolio weights: trend, momentum, mean reversion, inverse volatility,
  volatility targeting, risk parity, pairs, FX, futures. *Walk-forward*
  (WF01–WF05) covers rolling, expanding and anchored validation, a 3×3 grid
  search, and 30-trial Optuna optimisation.
- **Universe:** US ETFs, a few US stocks, FX pairs and futures. Data comes from
  yfinance. Each run starts with $100,000; the longest test is 26 years.
- **Six headline numbers per strategy:** return, CAGR, Sharpe (after a 2%
  risk-free rate), maximum drawdown, win rate and profit factor. They are
  defined in words, with no formulas.
- **Interface:** a log-scale "growth of $1" chart of 40 strategies, filters by
  family, asset class and bar size, seven sort orders, and a compare button.
- **Position sizing (in the paid workbook):** risk per trade, volatility
  target and Kelly calculators, plus a strategy correlation matrix.

## 2 · What its own numbers say

This is the most useful thing on the site, and it is not in the marketing
copy. Of the **40 strategies that report a Sharpe ratio**:

- **18 are negative.** They earned less than cash after the 2% risk-free rate.
  This includes most of the order-type variants and every FX strategy.
- **3 reach 0.5:** O17 Monthly Rotation (0.53), W18 Vol Target Momentum (0.57)
  and W25 Continuous Futures Trend (0.62, the best in the library).
- W20 Risk Parity Capped shows a profit factor of 11.14 alongside a −47.9%
  drawdown. A high profit factor does not make a smooth ride.
- The walk-forward cards carry the library's own caveat: *"Slice diagnostics,
  not independent out-of-sample evidence."*

Simple textbook rules, honestly costed, mostly do not beat owning the asset.
That is the lesson worth importing, and the lab is built to show it.

## 3 · What the lab found on real stocks

Live runs on 31 Oct 2026, 10 years unless stated, Indian costs:

| stock | holding CAGR | rules beating holding on CAGR | rules with a shallower worst fall | best rule's Sharpe lead over holding | luck bar |
| --- | --- | --- | --- | --- | --- |
| RELIANCE | 17.6% | 0 of 11 (0 after tax) | 8 of 11 | none | 0.21 |
| TCS | 10.3% | 0 of 11 (0 after tax) | 11 of 11 | none | 0.21 |
| Nifty 50, 15 years | 10.2% | 0 of 11 (0 after tax) | 9 of 11 | none | 0.19 |
| AAPL | 29.5% | 0 of 11 | 8 of 11 | none | 0.20 |

This matches what `special.py` found for delivery-weighted momentum: these
rules are a **risk** improvement, not a **return** improvement. They make the
ride shallower, not richer. The page says so whenever the numbers show it:
*"On this stock the rules bought a smoother ride, not a richer one."*

## 4 · What we took

| quants.md | in the Strategy lab |
| --- | --- |
| Six headline numbers | The same six, plus volatility, Calmar, time in market, turnover and an after-tax CAGR |
| Trend / momentum / mean-reversion / breakout / risk-sizing rules | 11 long-only daily rules, each naming the library entry it adapts (W01, O01, W06, W22, W04, O02/W03, W21, O05/O20, O09, W17, W05) |
| Growth of $1, log scale, every strategy drawn | Growth of ₹1 with every rule faint and holding and the selected rule highlighted, plus an underwater (drawdown) chart |
| Sort orders (Sharpe, CAGR, return, drawdown, win rate, profit factor) | The same sorts, plus after-tax CAGR, and family chips |
| Compare | Up to three rules side by side, each drawn in its own colour |
| Walk-forward caveat | Two-halves consistency, every calendar year against holding, and no parameter fitting at all |
| Workbook position-sizing tab | Risk-per-trade, volatility-target and Kelly calculators, free, prefilled from the selected rule's trades |
| Workbook correlation matrix | Each rule's correlation with holding, and the effective number of distinct rules, which feeds the luck bar |
| "Reading the numbers" | A glossary that gives the formula for every measure; quants.md gives none |
| "Research examples, not recommendations" | The same, plus: the report never says what a rule is doing today |

## 5 · What we added that quants.md does not have

- **Indian costs.** A 0.49% round trip, the same figure the Altaha Special
  backtest uses. It covers STT on both legs, stamp duty, exchange and SEBI
  charges, GST, DP charges and slippage. It is charged on every change in
  position.
- **Indian tax.** For NSE/BSE stocks and Indian indices, every rule also gets
  a CAGR after capital gains tax: 20% on gains held a year or less, 12.5% on
  gains held longer. Gains are netted per financial year as the Act allows and
  paid at 31 March out of the account. Everything is closed on the last day so
  holding is taxed too. A rule that trades often pays short-term rates on
  every winner, which pre-tax tables hide. Simplifications, stated on the
  page: today's rates for the whole history, no ₹1.25 lakh exemption, no
  surcharge or cess, no loss carry-forward.
- **An Indian risk-free rate.** Sharpe is measured above 6% a year for rupee
  stocks, about the 91-day Treasury bill over the last decade, not 2%. Cash
  earns nothing in the model, because money waiting in a trading account does
  not earn a T-bill yield.
- **A luck bar.** The best of eleven tries will look good by chance. The lab
  estimates how many genuinely different rules were tried, using the
  eigenvalue participation ratio of the rules' return correlations. It is
  usually about 2 to 3, not 11. It then reports the Sharpe lead that the best
  of that many zero-skill rules would show by luck over the test's length.
  This is the expected maximum Sharpe ratio from Bailey and López de Prado,
  *The Deflated Sharpe Ratio* (2014). The verdict says whether the best rule's
  lead over holding clears the bar.
- **An explicit, tested execution model.** A rule decides at the close and is
  filled at the next session's open. The overnight gap belongs to the old
  position. A test changes every price after a date and checks that no
  earlier decision moves.
- **One start line.** Every rule and holding start in cash on the same day,
  after a one-year warm-up, and each pays its own way in.
- **Corporate-action warnings.** A one-day move beyond 40% is flagged as
  probably an unadjusted demerger, bonus or rights issue, not the market.
- **Thin-sample flags.** Fewer than 8 closed trades and the win rate and
  profit factor are marked. "No losing trade" is said in words instead of ∞.

## 6 · What we deliberately left out, and why

| quants.md | left out because |
| --- | --- |
| **AgenKit bot building and broker automation** (Alpaca, IBKR, OANDA, "paper first, then live") | Turning a backtest into live orders makes the site an execution and advice product. The README draws the line at evidence, not directives, except the portfolio review. In India, retail algorithmic trading now runs through brokers under SEBI's 2025 retail-algo framework. Nothing here places or suggests an order. |
| **"What the rule is doing today"** | A rule's current position is a buy or sell signal. The report does not send it, the page does not rebuild it, and a test fails if a field like it appears. |
| **Shorts and long/short** (W13–W16 pairs and cross-sectional, W25's short side) | An Indian cash account cannot hold a short overnight. Showing results on a basis nobody here can trade would mislead. |
| **FX and futures** (O19, O20, W23–W25) | Outside the screener's universe. |
| **Intraday rules** (O15, O16, W07–W09) | They need Dhan intraday history, the samples are tiny, and quants.md itself reports no Sharpe or CAGR for them. |
| **Order-type mechanics** (limit, stop-limit, bracket, OCO: O03–O14) | Simulating limit and stop fills on daily bars is guesswork about the order of the day's high and low. The one exit idea that survives on daily bars, a trailing exit, is kept (ATR-scaled, O09). |
| **Grid search and Optuna** (WF04, WF05) | Tuning parameters on the same prices they are measured on is how a backtest becomes fiction. The Factor Lab refuses to fit weights for the same reason. It would also add a heavy dependency to a 512 MB instance. |
| **The $9.99 workbook, the 50 dashboards, the US-ETF numbers** | Their commercial content and their market. We used the ideas and the shape of the report. |
| **quants.md's Python** | Apache-2.0 allows reuse with notice, but the lab is ~900 lines of its own numpy and pandas, needs no new dependency, and is built around Indian costs, tax and execution. The page credits the source and links to it. |

## 7 · What else could be used next

In order of value for this project:

1. **The six numbers on Altaha's own record.** The Call log has dated calls
   with stops and targets, which is exactly what win rate and profit factor
   need. Add them, with the same thin-sample flag and luck framing, to the
   Call log and Track record.
2. **Rotation across NSE sector indices.** O17 Monthly Rotation and W04 Dual
   Momentum are the library's best long-only rules and need a basket, not one
   stock. `^CNXIT`, `^NSEBANK`, `^CNXPHARMA` and the other sector indices are
   that basket. A "Sector rotation" view would reuse `simulate()` with weight
   vectors.
3. **Base rates across the universe.** Run the lab over every liquid NSE name
   overnight and report which rule families have held up on which archetypes
   (quality compounders, cyclicals, small caps). Report it with a luck bar for
   the whole sweep, because a universe-wide search is a far bigger data-mine
   than eleven rules on one stock.
4. **Volatility-target sizing in the Allocation plan.** The calculator's
   arithmetic, applied to the plan's suggested amounts, would size volatile
   holdings smaller.

---

*Rule ideas and the six headline measures follow quants.md
(https://quants.md/), built on the QuantJourney backtester examples
(Apache-2.0). The code is Altaha's own. Every report is a historical
simulation, not a recommendation or a forecast.*
