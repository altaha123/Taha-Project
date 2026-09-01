# Measuring the engine

## The thing to understand before reading any number here

Nobody achieves accuracy on individual stocks. Not the big funds, not the
famous analysts. Chasing "maximum accuracy" is the wrong target and it is why
looking at the Ideas list felt bad.

What professional quant investors do instead:

- **They lower the bar and raise the count.** A world-class equity signal has an
  information coefficient of **0.03 to 0.05** — right about **52%** of the time.
  Money is made by applying that 2% edge across hundreds of names, hundreds of
  times a year. Grinold's Fundamental Law puts it as `IR ≈ IC × √breadth`.
- **They combine many weak, uncorrelated signals.** Five signals at IC 0.03 that
  do not correlate beat one signal at IC 0.06.
- **They measure out-of-sample before anything goes live.** This is the entire
  discipline, and it is what this change adds.
- **They neutralise what they are not betting on** — sector, size, beta — so the
  "alpha" is not secretly a bet on metals having a good quarter.
- **Sizing and exits are often more than half the return.**

An IC of 0.10 sustained is almost always a bug: a lookahead leak, a
survivorship filter, or a factor fitted to the sample it is measured on.

## What was measured, and what it found

The engine had never been scored. Replaying `technical_score` over 343 liquid
NSE names — computed on frames truncated at each date, so no bar after the
evaluation date was visible — against forward returns versus NIFTYBEES:

| horizon | mean IC | top-minus-bottom quintile |
| --- | --- | --- |
| 10 sessions | **+0.036** | +0.81% |
| 21 sessions | **−0.013** | −0.31% |

Weakly positive at a fortnight, gone by a month. Three months of data in one
regime — a point estimate, not a significance test.

The decomposition mattered more than the headline:

- **60 of the technical score's 132 points were doing nothing or working
  against it.** Volatility squeeze ran IC −0.035, MACD −0.012, and at 21 days
  volume trend ran −0.060 with a 20% hit rate.
- **The twelve checks have 5.5 effective degrees of freedom.** Trend structure
  and 52-week position correlate at **0.86**; RSI and Bollinger position at
  0.70. The first principal component explains 35.7% of variance.

That is one momentum factor wearing twelve hats. A score built from one idea
has the predictive ceiling of one idea, and no reweighting changes that.

## What is now in the codebase

### Phase 0 — the system measures itself

| file | what it does |
| --- | --- |
| `pit_store.py` | Fixed. It was failing in production with `unable to open database file` and answering 503 with that string, so nothing had been banked and nothing said so. Now reports its resolved path, whether the directory exists and is writable, and whether it is on a persistent disk — and falls back rather than recording nothing. |
| `forward_returns.py` | Attaches what each stock actually did, against the index over the identical window, at 5/10/21/63 sessions. Idempotent, runs from `/cron/tick`. |
| `factor_lab.py` | The information coefficient for every recorded factor. **Withholds the average below eight measured dates** rather than annotating it. |
| `scan.py` | Every scan now banks the orthogonal factors and each technical check individually. The Lab cannot measure what was never recorded. |

### Phase 1 — the ranking defects

| file | what changed |
| --- | --- |
| `engine.py` | Volatility squeeze scored **0 instead of 5**. A squeeze says a move is coming, not which way — paying points for ambiguity inside a score read as "this looks bullish". A reasoning argument, not a fitted one; it is the only weight touched by hand. The check is still shown. |
| `multifactor.py` | Cross-sectional percentile ranking. Fixes saturation (a live list scored eight names inside 3.4 points with a tie) and double counting (factors are averaged **within their family** before families are weighted, so two measures of one idea sharpen an estimate instead of casting two votes). Separate weights for short and medium horizons. |

### Phase 2 — signals that are not momentum

`factors.py`. Every fundamental factor respects the **filing date, not the
period end** — the December quarter was not knowable in December.

| factor | family | why |
| --- | --- | --- |
| `momentum_12_1` | momentum | Skips the last month. Over 1–4 weeks stocks reverse; including the last month mixes a positive signal with a negative one and they cancel. Likely the main reason the current score reads zero at a month. |
| `trend_quality` | momentum | R² of log price — how straight the advance was, not how big. |
| `reversal_5d` | reversal | The other side of that coin, isolated. Mechanically anti-correlated with momentum. |
| `low_volatility` | volatility | Negated. Decades of risk-adjusted outperformance nobody has explained away. |
| `volume_shock` | attention | Turnover against its own history, log-scaled. |
| `earnings_yield` | value | TTM EPS over price. The family that was **entirely absent**. |
| `earnings_growth`, `revenue_growth` | growth | YoY, from the company's own XBRL filing. |
| `margin_trend` | quality | EBITDA margin change YoY. |
| `return_on_assets` | quality | Annualised, from the filing. |

### Phase 3 — attention, inverted

`attention.py`. For Indian small and mid caps a mention spike is far more often
a pump in progress than a discovery, so this ships as a **risk flag and never a
buy signal**, and never touches a score.

Reddit's free JSON answers **403** to datacenter IPs (it needs OAuth now) and
X's read API is paid, so neither works from a server without credentials. The
default source is the market itself — turnover against the stock's own history,
plus filings and press already ingested. Reddit and X plug in behind
`REDDIT_CLIENT_ID` / `X_BEARER_TOKEN` when you have them; until then the
payload says which sources answered rather than degrading silently.

## Endpoints

```
GET /pit/coverage              store health — answers 200 even when broken
GET /pit/ic?horizon=21         every factor's measured IC
GET /pit/ic?factor=momentum_12_1
GET /pit/label                 attach forward returns (also runs on /cron/tick)
GET /factors?ticker=RELIANCE   the orthogonal block for one stock
GET /factors/rank?horizon=short   the universe ranked against itself
GET /attention?ticker=RELIANCE    unusual-attention risk flag
```

The **Engine Lab** panel at the bottom of the Tracker tab surfaces all of it,
including the wait: with fewer than eight measured dates it explains why no
average is shown instead of drawing an empty chart.

## The honest status

The new weights are **priors from published factor research, not values fitted
to this universe.** Fitting weights on the same three months used to measure
them is how a backtest becomes fiction. They are meant to be replaced by the
Lab's measurements once those have survived a regime they did not start in.

Nothing here makes the engine accurate today. It makes it **measurable**, which
is the only route to accuracy that is not guessing.

## Reproducing the study

```bash
python research/ic_study.py --fetch       # candles from your own API
python research/ic_study.py --study       # IC by horizon
python research/ic_study.py --decompose   # per-check IC and collinearity
```

## The XBRL feed: it was the wrong endpoint

My first conclusion here was wrong and is corrected below.

I found NSE's `corporates-financial-results` API returning nothing newer than
31-Dec-2024 for the *entire* 3,816-row equities universe, and concluded the
source itself was dead. It is not. **SEBI's Integrated Filing regime replaced
the standalone results filing from the quarter ending December 2024** — which
is exactly where the data stopped. The old endpoint was not frozen, it was
finished, and everything since is filed somewhere else:

```
https://www.nseindia.com/api/integrated-filing-results?index=equities&symbol=SYM
```

Live, and current: for RELIANCE the newest filing covers the quarter ending
**30 Jun 2026**, broadcast 17 Jul 2026 — 63 days old, not stale. The XBRL
documents sit on `nsearchives.nseindia.com` under a new taxonomy
(`in-capmkt` rather than `in-bse-fin`), but the element names are unchanged and
our parser strips namespaces, so it read the new documents correctly with no
changes at all.

### What changed

- `filings()` reads **both regimes and merges them**, integrated first so the
  newer filing wins where they overlap. RELIANCE now returns 65 filings from
  Jun 2026 back to Jun 2018.
- The legacy endpoint is still needed and still read: the year-earlier
  comparatives for the first integrated quarters exist only there, so dropping
  it would silently delete every YoY figure for the newest quarters.
- Governance filings ride the same feed and carry no income statement, so they
  are filtered out by `type`.
- The integrated feed labels a filing by quarter-end date alone where the old
  one carried "Third Quarter" in words. Growth is matched on the quarter label,
  so one is derived — without it every integrated filing would fail to find its
  comparative.
- Each regime is fetched behind its own guard. One endpoint failing degrades
  the history rather than emptying it.

Verified end to end: Q1 FY27 revenue ₹3,11,850cr, +25.41% YoY, PAT −24.65% YoY,
earnings yield 4.32%, margin trend −2.01.

### The staleness machinery stays

Built when I thought the source was dead, and worth keeping now that it is not.
`xbrl.freshness()` publishes `age_days` and a `stale` flag; `factors.py`
withholds fundamental factors past 225 days and says why; a stock whose
fundamentals are withheld still ranks on its price families. It correctly
reports **"current"** today, which is what a regression guard is supposed to do
— it caught this once and will catch the next endpoint migration the week it
happens rather than twenty months later.

## What still needs money

Earnings **estimate revisions** — the strongest single alpha family in emerging
markets — need a paid estimates feed. Everything above runs on data you already
have.
