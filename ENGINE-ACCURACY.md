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

## The XBRL feed: what "stale" turned out to mean

Investigated properly. **NSE's `corporates-financial-results` API is itself
frozen**, not our parser. Queried for the *entire* equities universe it returns
**3,816 rows whose newest period end is 31-Dec-2024**, and no combination of
symbol, `period`, or date-range parameter produces anything newer. As of
1 Sep 2026 that is **609 days** old.

BSE, by contrast, is live — its announcement feed returns 50 filings for
28 Aug 2026 — but it does not expose a results XBRL document at any path that
resolves, so it cannot replace NSE as a source. It does serve as a
**cross-check**: the gap between "NSE's newest XBRL for this company" and "BSE
saw it file results on this date" turns a vague worry into a dated fact.

So the fix is not to the fetching, which was already correct. It is to the
silence:

- `xbrl.freshness()` publishes `age_days`, a `stale` flag, and a note that says
  the problem is the **source, not the company** — otherwise a reader concludes
  the business stopped reporting.
- **`factors.py` refuses to compute fundamental factors past 225 days.** This is
  the one that mattered. Without it, every growth, margin, yield and ROA factor
  would have been computed from twenty-month-old filings and fed into the
  ranking looking perfectly healthy — well-formed numbers, correct arithmetic,
  describing a company that has since reported six more times. Stale
  fundamentals presented as current are worse than absent ones.
- A stock whose fundamentals are withheld still ranks on its price families;
  the ranker renormalises. Withholding degrades the reading, it does not delete
  the stock.
- `/factors` reports `fundamentals.withheld` and why, so a caller can tell "this
  company has no value factor" from "we refused to invent one".

The thresholds allow a normal reporting lag — a quarterly filer owes results
within 45 days of the quarter end, so a cutoff inside that gap would flag every
company for part of every quarter and be ignored within a week.

**What would actually restore fresh fundamentals:** a source that publishes
current Indian quarterly results in machine-readable form. BSE's results PDFs
exist and are current but need parsing; a paid fundamentals feed is the
reliable route. Until then the engine ranks on price factors and says so.

## What still needs money

Earnings **estimate revisions** — the strongest single alpha family in emerging
markets — need a paid estimates feed. Everything above runs on data you already
have.
