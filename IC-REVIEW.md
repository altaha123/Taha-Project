# What happens when somebody uploads a portfolio

Two halves. The first half already existed and is described here because
nobody could read it off the code in one sitting. The second half is the
Investment Committee review in `backend/ic_review.py`, which is new.

---

## Part 1 — The pipeline, from broker file to report

### 1. The file never leaves the browser

`frontend/portfolio.js` parses the CSV itself — a real parser, not
`line.split(',')`, so quoted fields with commas survive — and recognises the
column layouts of the Indian brokers by name (`Avg. Buy Rate` is Dhan's, and
it matched nothing before it was taught). When no layout is recognised the
page shows a column mapper instead of rejecting the file. Symbols are then
resolved against the cached universe so a broker's `RELIANCE-EQ` becomes
`RELIANCE`.

A broker statement carries the client code, the PAN and the holding pattern of
a real person. None of it is uploaded: what leaves the browser is a list of
`{symbol, qty, buy_price}`, and nothing else.

### 2. `POST /portfolio/start` — validation and coalescing

`_pf_inputs` in `backend/main.py` enforces 1–50 holdings, NSE symbols with no
foreign suffix, positive finite quantities, and optional purchase prices. Tax
lots in the same name are merged into one position, and the average cost is
**withheld entirely if any lot lacks a price** — a portfolio is never told its
cost basis is lower than it is because one lot came in blank.

The request returns a `job_id` immediately. Analysis runs on a background
thread with a 100-second enrichment deadline.

### 3. The job publishes three times, each one complete

`_pf_run` never makes the reader wait for the slowest data source:

| Stage | What it has | Where it comes from |
|---|---|---|
| `Cached valuation` | weights, sectors, scores | the last universe scan, instantly |
| `Prices & scores` | live prices | one batched Dhan quote call, 8-second budget |
| `Complete` | technicals, fundamentals, history, sectors, filings, press | per-holding workers + two enrichment threads |

`GET /portfolio/status` returns whatever the latest published revision is, so
the page fills in rather than spinning. **Every stage is a whole report**: if
enrichment dies at stage 3, the stage-2 report survives with a warning
attached, never a 500.

Per holding, `_analyse_holding` fetches adjusted price history, runs
`technical_score`, pulls annual statements for `fundamental_score`, resolves
the sector, and records the P/E, P/B and market cap. Any of those can fail on
its own; the position keeps its valuation and gains a named warning.

### 4. `portfolio.build_report` — the measurement

Weights over **priced capital only**. Sector aggregation with benchmark and
momentum overlays. Herfindahl concentration and effective holdings. P&L over
cost-covered positions only. Then the rulebook audit: every user limit
(`max_stock_pct`, `max_sector_pct`, `min_composite`, `review_drawdown`,
`min_holdings`, `max_unclassified_pct`) produces a finding carrying **the
rule, the measured value, the limit, and the arithmetic to close the gap** —
share count, rupee value, resulting weight. Never an instruction.

The trim arithmetic solves `(V − x)/(T − x) = cap`, not `V − cap·T`: selling
shrinks the denominator too, and the naive form understates the gap.

### 5. `portfolio_intelligence.enrich` — the evidence layer

Coverage and freshness for every number, history analytics (volatility,
drawdown, a correlation matrix that outer-aligns prices before differencing),
news joined to holdings by symbol and sector, factor exposures, score
distribution, scenario arithmetic, and the data-quality warnings that mark the
whole report provisional when coverage is thin.

### 6. `ic_review.build` — the judgement layer *(new)*

Everything above is true and flat: forty honest numbers, no ordering. Part 2
is what turns them into a read.

---

## Part 2 — The Investment Committee review

`backend/ic_review.py`. Pure: no network, no persistence, no clock beyond the
`now` it is handed. Every input arrives as an argument and every output
discloses its coverage.

### Risk budget — the part a weight table cannot show

Capital weight says how much money sits in a name. **Risk contribution** says
how much of the portfolio's movement that name causes, and the two are
routinely far apart.

```
Σ           sample covariance of daily adjusted returns × 252
σₚ          √(wᵀΣw)                       portfolio volatility
MCTRᵢ       (Σw)ᵢ / σₚ                    marginal contribution
CTRᵢ        wᵢ · MCTRᵢ                    contribution, and Σ CTRᵢ = σₚ exactly
```

That identity is asserted in `backend/tests/test_ic_review.py`, so the table
always reconciles to the headline. In the shipped fixture HDFCBANK is 24.0% of
capital and **43.7% of risk** — the single most useful line the review
produces, and one that is invisible in every weight table.

Alongside it:

- **Diversification ratio** — weighted average holding volatility ÷ portfolio
  volatility. 1.0 means one bet wearing many tickers.
- **Effective positions by risk** — 1/HHI of the risk shares, beside the
  familiar 1/HHI of the capital weights.
- **Value at risk**, both historical (the loss the observed distribution
  exceeded 5% and 1% of the time) and parametric (z × daily σ), because the
  gap between them is itself information about the tails.
- **Worst day and window drawdown** on today's weights.

Weights are renormalised over the holdings with usable history and the
coverage figure states how much priced capital that is. A holding whose price
source has unverified adjustment status is withheld, not mixed in.

### Benchmark sensitivity

The Nifty 50 series the sector overlay already downloads is now kept
(`sectors.benchmark_closes`) and handed to the review, so beta, R², tracking
error and **separate up-day and down-day capture** are measured rather than
listed as unassessed. Supplied as an argument, never fetched inside the
analytics; adjustment provenance is stamped on the frame and checked.

### Aggregate valuation, done correctly

A weighted arithmetic mean of P/E is wrong and common. P/E is unbounded above,
so one 180× holding drags an ordinary book into nonsense, and loss-making
names have no multiple at all.

```
portfolio P/E = 1 ÷ Σ(wᵢ × 1/PEᵢ)          the harmonic mean
```

which is what aggregating earnings actually gives. Loss-making holdings are
counted and reported separately rather than dropped in silence, and the
coverage denominator travels with the figure. The 15–28× reference band is
disclosed as a convention for placing a number, not a fair-value judgement.

### The pro-forma book

Every single-stock gap already carried its own share count. Nothing added them
up, so a reader could not tell whether closing all of them freed 4% of the
book or 26%, nor whether the result still broke a ceiling somewhere else. The
capital plan sums the releases and recomputes top-1, top-3 and effective
holdings **on the resulting weights**. Released capital is shown as cash: no
destination is proposed.

### Scorecard

Six dimensions — construction, research evidence, risk posture, valuation
discipline, benchmark positioning, data completeness — each computed from
measured inputs, each carrying its own inputs and method, each able to return
*unavailable*. The overall figure is the mean of the dimensions that could be
computed and names its own denominator. **A dimension with no data is never
scored 50 to keep the average tidy**; that is how a data gap becomes a
verdict.

### The memo and the agenda

Sections in the order a committee reads a book — what it is, how it is built,
what moves it, how it tracks the index, what the evidence says and what it
costs, where it differs from the benchmark, what has happened around it, and
what the review cannot see. Then a ranked agenda: each item carries the
measurement, the threshold it crossed, the arithmetic where one exists, and a
question.

The questions are the point. *"Is this position deliberately sized above the
ceiling, or has it drifted there?"* is answerable only by the person whose
money it is.

---

## Framing, unchanged

Every sentence is an observation with the arithmetic shown, measured against
the reader's own rulebook and disclosed reference bands. `"Two positions carry
38% of measured risk against 21% of capital"` is a fact about a covariance
matrix. `"Reduce them"` is advice this platform is not registered to give.
`test_ic_review.py` asserts the prose contains no directive verbs.

## What is still unassessed

Liquidity and the market impact of changing these positions; promoter
pledging, related-party exposure and governance history; currency, commodity
and interest-rate sensitivity; tax position, realised transactions, dividends
and charges; and the holder's income, obligations and horizon — everything no
uploaded file contains. The review prints this list rather than letting its
absence read as an all-clear.

## Where it lives

| Concern | File |
|---|---|
| CSV parsing, column mapping, symbol resolution | `frontend/portfolio.js` |
| Validation, job orchestration, enrichment | `backend/main.py` (`_pf_inputs`, `_pf_run`) |
| Weights, sectors, rulebook audit, trim arithmetic | `backend/portfolio.py` |
| Coverage, history, news, factors | `backend/portfolio_intelligence.py` |
| Risk budget, valuation, pro-forma, scorecard, memo | `backend/ic_review.py` |
| Benchmark series for beta and capture | `backend/sectors.py` |
| Rendering | `frontend/portfolio-intelligence.js` / `.css` |
| Tests | `backend/tests/test_ic_review.py`, `frontend/portfolio-intelligence.test.js` |
