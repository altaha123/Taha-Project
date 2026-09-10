# Altaha Portfolio Intelligence

## Audit of the previous implementation

Audited the complete portfolio request / job worker and report renderer, advice,
engine checks, v4 ranker and factor ledger, profiles/archetypes, universe scan,
XBRL pipeline, data_source / Dhan, sector index module, exchange announcements,
press RSS, market news aggregator, persistence, navigation/shell, exports and
existing tests. Baseline: main `8262929ecfc52f1f0d677bf4b26ebca8e39b9483`;
local source tree verified against GitHub tree `6637daee08562223f396e5304de68b0415e98d10`.

Findings addressed:

- Partial purchase costs inflated P&L: all holdings' value minus only known
  costs. Now both sides use the same cost-covered positions.
- Failed technical scoring discarded a valid priced position. Prices survive
  scoring / enrichment failures, with explicit coverage and warnings.
- Duplicate lots overstated diversification. Validate and coalesce symbols;
  withhold aggregate cost if any lot lacks a purchase price.
- Portfolio UI hid sector comparisons when momentum downloads failed, and
  excluded sectors not held, obscuring the largest benchmark underweights.
- Old SVGs used fixed viewBoxes, small text and mostly static interactions;
  index-dependent charts silently disappeared. There was no portfolio test suite.
- Filing code read `when/date`, but exchange feed uses `at`; timestamps were lost.
- Per-request worker pools and synchronous enrichments delayed the whole report.
- Scores come from the last v4 universe scan, not the current quote. The old
  narrative blurred their dates and used directive, score-only action labels.
- Holdings persist in localStorage; job results are ephemeral memory. DATA_DIR
  is configured for `/data` in Render, but portfolio history had no durable path.

## Calculations and limits

All portfolio weights divide by **priced capital**. Failed holdings are listed;
unknown exposure cannot be assigned a made-up weight. Costs never default to zero.
P&L is unrealised, excluding dividends, fees, taxes and realised transactions.
Contribution % means holding P&L / current priced capital, not return attribution.

Altaha score and each factor are value weighted over covered positions. Every
factor has its own coverage denominator. The v4 position horizon is retained;
annual provider technical/fundamental checks are labelled separately from v4
XBRL factors. No scoring-engine reweighting is performed.

HHI uses unrounded fractional weights; effective holdings = 1/HHI. Top 1/3/5
use priced value. They describe weight concentration, not independent bets.
Risk rules expose their measurements, thresholds and explanations. Trigger count:
0 = Low observed, 1 = Moderate, 2 = Elevated, 3+ = High. Unknown measures are
unassessed. This is a transparent monitoring heuristic, not a loss probability
or portfolio variance attribution. Health is deterministic from score and these
rules, and marked provisional for incomplete score / price coverage or stale scans.

Benchmark allocation is the **existing approximate Nifty 500 March 2026 proxy**.
It is not live. Momentum uses existing sector-index proxies against **Nifty 50**;
proxy notes and timestamps are visible. No benchmark factor exposure is invented.
V4 market-cap buckets are relative to the scanned universe, not official Indian
size classes, so the market-cap toggle honestly shows Unclassified until an
independently sourced classification is attached.

Historical scatter uses 21/63/126/252 sessions; annualised sample volatility =
standard deviation of daily returns × sqrt(252). Correlations outer-align prices
before calculating returns, require 60 overlapping observations, use up to 126
returns, and do not fill gaps. Dated, explicitly adjusted history ending within
seven days is required. Yahoo's `auto_adjust=True` carries provenance. Dhan's
adjustment status is unverified in this repository, so its histories are withheld
from these analytics. No beta, commodity/FX/rate sensitivities or synthetic
historical portfolio returns are inferred from holdings' purchase dates.
Scenarios are labelled hypothetical, with exposure × equal sector shock shown.

News joins existing exchange/press caches. Every rendered item needs a source,
HTTP(S) URL and publication timestamp within seven days. Relevance = exposed
weight × source category materiality × exp(−age hours / 72). Source category
rules can be wrong and are labelled as such. Existing feeds have no validated
contextual sentiment: directional impact stays neutral/unverified. A structured
interpretation can appear only with verified context and a matching source URL.
The feature does not invent company events or require an LLM/provider key.

## Architecture and operations

- Existing CSV mapping, named portfolios, purchase-price arithmetic, exports,
  policy endpoint and synchronous `/portfolio` result remain available.
- `/portfolio/start` / `/portfolio/status`: publish cached valuation, batch Dhan
  quotes, then enrich holdings through a shared four-worker pool. Two enrichment
  workers are shared; two active async jobs and twenty retained jobs cap memory.
- An eight-second quote wait and 100-second holding enrichment deadline retain
  available results. Python cannot terminate an already-running provider call;
  running tasks occupy the fixed pool until their provider timeouts return.
  Pending tasks are cancelled. This bounds concurrency rather than claiming to
  kill network work at the report deadline.
- Press refresh already runs in the background. Filing queries are indexed
  in-memory joins, not N network calls. Fundamentals/history reuse source caches;
  the provider has no batch fundamental API, so these remain bounded requests.
- Response `revision` supports staged rendering. Poll retries retain previous
  results. Request generations protect against stale responses.
- Browser snapshots: up to ten reviews for twenty portfolio keys; same method
  and benchmark vintage required. No fabricated comparisons on first run.
  Named portfolios support composition changes; unnamed books match the symbol
  set. Partial valuations and incomplete enrichment do not overwrite history.
  Snapshots survive server redeploys but not clearing browser storage, and are
  not synced between devices. Store failures are surfaced in the report.
- Locally bundled **Chart.js 4.5.1**, MIT license retained; ~70.5 KB gzip,
  loaded only on first report. Official distribution:
  https://github.com/chartjs/chartjs.github.io/tree/master/dist/4.5.1
  Upstream blob SHA: `008464faaecaf20a761739a61da2278be62b4963`.
  TradingView Lightweight Charts already in the shell serves price time series,
  but is not suited to categorical allocation, grouped bars and bubbles.
- Chart.js uses dedicated sized containers, resize observers, theme redraws,
  touch tooltips, reduced-motion support and instance destruction. Data tables
  remain available after script-load or rendering failures. HTML exports embed
  chart PNGs, open the evidence tables and require no remote assets or scripts.

## Verification

- `python -m unittest discover -s backend/tests -p test_portfolio_intelligence.py -v`
- `node frontend/portfolio-intelligence.test.js` and existing frontend tests.
- `python -m compileall -q backend` and Node syntax checks.
- Existing CI runs the complete backend pytest suite.
- Portfolio UI workflow runs Chromium against the actual frontend shell at
  320/390/768/1280 pixels, both themes, populated charts, sector filtering,
  50 holdings, standalone exports and missing chart-library fallbacks. Screenshots
  and machine-readable verification are uploaded as a workflow artifact.

Local environment lacks FastAPI/pytest and a Chromium binary; Cloud Browser
blocks local URL/file previews. Local unittest/Node checks are separate from
remote full-suite and responsive-browser checks. PR checks are the authority for
those gates. No deployment, merge, production data mutation or new credentials.
