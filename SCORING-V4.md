# Altaha Score v4 methodology

V4 is an interpretable research ranking, **not a probability of profit, a
price forecast, or a measured improvement in predictive accuracy**. The
existing study in ENGINE-ACCURACY.md concerns the older technical engine;
its results do not validate this implementation. No model fitting or weight
search was performed for this change.

## One scoring path

`factors.SPEC` → raw observations → `multifactor.rank` → business-model peer
percentiles → related-signal group means → eight pillar means →
`profiles.v4_weights` → raw horizon score → confidence shrinkage.

The full completed Phase-2 cohort is ranked **before** the displayed top 60
are selected. The cohort includes the existing random controls. It remains
conditioned on liquidity and technical screening: it is not a census of NSE.
`factor_universe` preserves all analysed names and their scores in the scan
cache. Analysis reads the same dated result. No per-request NSE-wide rerank,
no scoring a live company against yesterday's selectively retained top 60.
A stock outside that cohort needs a scan including it; the UI says awaiting
scan instead of substituting a competing headline score.

`composite` on v4 scan rows aliases the position score; `factor_score` aliases
the requested horizon. `legacy_composite`, technical/fundamental scores,
Piotroski, adapted G-Score, and setup fit remain diagnostic. `scoring` and
`horizons` on `/analyze` are adapters of v4 for existing components;
`legacy_scoring` retains the former profile result. The old `verdict` API
field remains for compatibility; updated score views use v4. Ideas preserve
existing setup/liquidity/adverse-filing filters, but their headline conviction
and ordering use the v4 horizon score. The old context blend is retained as
`legacy_conviction`, not added to v4. Research must use versioned fields,
never combine old and new `composite` observations as one methodology.

## Factors, formulas, and overlap

All raw factors are oriented higher-is-better. None/NaN/infinity never count
as zero. Negative EPS is not a positive earnings yield. Growth refuses
negative bases, sign changes, bases <=1e-8, or bases <1% of current magnitude.
That last guard withholds an unstable ratio rather than turning it into a
large positive score. Parameters are disclosed priors, not estimated truths.

| Pillar | Group | Inputs and transformation |
| --- | --- | --- |
| Quality | profitability | Reported annualised ROA; EBITDA margin level; equal group mean |
| Quality | persistence | Negative sample SD of 4–8 consecutive seasonal PAT changes; each change = `200*(PAT_t-PAT_t-4)/(abs(PAT_t)+abs(PAT_t-4))`; both zero means unavailable |
| Quality | earnings quality | `-other_income/PBT`, only when other income >=0, revenue >0 and PBT >1% of revenue and >1e-8 |
| Growth | earnings | Quarterly PAT YoY percentage growth |
| Growth | revenue | Quarterly revenue YoY percentage growth |
| Growth | margin | EBITDA margin minus same-quarter-last-year margin (percentage points) |
| Acceleration | earnings | Current EPS YoY growth minus previous-quarter EPS YoY growth; combined with historical surprise before this group gets its vote |
| Acceleration | revenue | Current revenue YoY growth minus previous-quarter YoY growth |
| Acceleration | margin | Current YoY EBITDA-margin change minus previous-quarter YoY change |
| Acceleration | earnings | Surprise: let `d_t = EPS_t-EPS_t-4`; `(d_t-median(d_t-1…d_t-8))/(1.4826*MAD(d_t-1…d_t-8))`. Current innovation is excluded from the scale; 13 consecutive quarterly EPS values required; scale <=max(1e-8, max historical absolute change ×1e-6) withholds |
| Value | valuation | Positive sum of four **consecutive** quarterly EPS / price ×100 |
| Value | valuation | Cyclicals only: median of three non-overlapping annual EPS sums / price ×100; needs 12 consecutive quarters and positive median; replaces trailing yield |
| Financial Strength | leverage | Negative reported debt/equity, only with explicitly validated ratio units; current feed withholds |
| Financial Strength | coverage | Operating coverage `(PBT before exceptional + finance cost - other income)/finance cost` and its same-quarter YoY change; all lines required, positive finance cost; averaged together |
| Momentum | trend | Existing 12–1 momentum and signed R² of log prices, averaged together |
| Risk | reversal / volatility | Existing negative 5-session return and negative realised annualised volatility |
| Participation | turnover | Existing `100*log(recent turnover / historical median turnover)` |

Factors first average within the group, then groups average within the pillar.
Adding an identical second trend or interest-coverage metric does not increase
the pillar's weight or confidence. Earnings surprise and EPS acceleration do
not get independent pillar weights. Related margin **levels** and **changes**
remain different hypotheses, monitored for correlation across pillars.
Participation is an attention prior, not evidence of institutional buying;
it is not a standalone buy signal.

Minimum histories and eligibility are machine-readable in `factors.SPEC`.
Price histories require 260 (12–1), 90 (trend), 8 (reversal), 61 (volatility),
and 65 (turnover) rows respectively. Phase-2 Yahoo history is now two years
so its old one-year request no longer makes a 260-row factor impossible.
Dhan history is reused; insufficient Dhan rows remain missing.

EBITDA reconstruction requires PBT, finance cost, depreciation, and other
income explicitly present; missing addbacks are not assumed to be zero.
The XML cache key is versioned to prevent reuse of older derived arithmetic.

## Cross-sectional transformation and peer selection

1. Filter invalid business models, missing/nonfinite and stale observations.
2. Choose a peer pool with at least **10 distinct observations for this factor**.
3. Winsorise at that pool's 2nd and 98th percentiles (NumPy linear quantiles).
4. Use average ranks for ties, scaled as `100*rank/(n-1)` with zero-based ranks.
   An all-equal factor returns 50; a tiny pool returns no percentile.
5. Average factors within groups and groups within pillars.

Fallback order is business model → sector → size bucket → eligible universe.
Sector fallback is explicit; the model classifier itself uses industry before
sector. Fundamental lender pools **never** fall back into corporate pools.
Price factors may use broad market pools. A small bank peer group therefore
means unknown bank accounting ranks, not a ranking against FMCG and steel.
Peer source, sample size, raw value, percentile and missing reason are returned
for every ledger entry. These are local peer percentiles: an 80 in different
peer groups means similar relative standing, not identical absolute economics.

Market-cap buckets use positive finite market cap observed at the scan date:
bottom 30% small, middle 40% mid, top 30% large; ties use midranks. They are
relative to this cohort, not official regulatory/index size classifications.
No static stock lists and no size alpha vote. Missing size skips that fallback.

## Business models and horizon priors

The existing `profiles.classify` rules and business biases are reused.
No second classification engine was introduced. Metadata is observed and
banked on the scan date; historical callers must provide contemporaneous
classification/size metadata, never query today's provider metadata to replay
an old score.

- Lenders: no corporate leverage, EBITDA margin, finance-cost coverage or
  other-income dependence tests; no corporate CFO/asset-turnover tests are
  introduced. ROA/growth can be ranked only with lender peers. Valuation and
  capital/asset-quality coverage remain incomplete.
- Cyclicals: trailing earnings yield is excluded. Three-year median annual EPS
  is a limited historical normalisation, not proof of a full commodity cycle.
- Compounders/staples: existing quality bias applies; no low-capex penalty.
- Utilities: structural debt/equity excluded; debt-service coverage still counts.
- Realty: no universal asset-turnover factor. Presales/collections remain absent.
- Emerging: no positive-yield score manufactured from losses. Bounded PAT
  consistency and EPS differences can exist through losses; consistency alone
  is not profitability and does not receive the profitability group's vote.

Base weights, before the **existing business-model bias** and renormalisation:

| Horizon | Quality | Growth | Acceleration | Value | Strength | Momentum | Risk | Participation |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Trade | 10 | 5 | 5 | 5 | 5 | 20 | 30 | 20 |
| Position | 20 | 15 | 15 | 15 | 10 | 15 | 5 | 5 |
| Invest | 25 | 15 | 10 | 20 | 15 | 8 | 5 | 2 |

Trade/position/invest risk internally weights reversal at 65%/20%/0%, with
volatility taking the remainder. `short` and `medium` alias trade and position.
Growth/acceleration inherit the profile's improvement bias, value its valuation
bias, and strength its quality bias. These fixed priors are not optimised.

## Confidence, not a missing-data penalty

Raw score renormalises available pillar weights. Final score:

`50 + (raw_score - 50) * confidence`

Confidence is the sum of **intended**, not renormalised, horizon weights times:

- fraction of eligible groups available in that pillar;
- mean `min(peer_count/30, 1)` of its available eligible observations;
- for fundamental pillars, freshness × source validity × history adequacy.

Freshness is 1 through 135 period-age days, decreases linearly toward .5
through 225, and is 0 above 225 or when unknown. Source is 1 with documented
filing URLs, .5 without verified provenance. History adequacy is
`.5 + .5*min(consecutive_quarters/13, 1)`. Price pillars use their actual input
availability instead. A wholly unsupported pillar, including lender capital
adequacy/valuation, contributes zero confidence. The raw score is neutral 50
with confidence 0 if nothing can be measured. Reduced confidence can raise a
below-neutral raw score: missing information is not adverse evidence.

Confidence is data support, **not a calibrated chance of being correct**.
Each response exposes raw score, final score, confidence (0–1), family coverage,
factor coverage, period age, source URLs, history length and reduction reasons.
The legacy presentation adapter displays confidence as a percentage.

## Point-in-time rules

Filings must have a parseable filing date <= the evaluation date. Future period
ends and periods after their claimed filing date are rejected. No fallback to
quarter end or today's date on a malformed historical cutoff. Dates are
end-of-day observations: this is not an intraday filing-time backtest.

The legacy and Integrated NSE feeds remain independently guarded and merged.
The scoring path retains metadata revisions until applying the cutoff; then
selects the latest known revision per period. Period order precedes filing
order, so a late revision of an old year cannot become the latest quarter.
Same-day timestamp strings and Integrated regime preference break ties
 deterministically. Exact quarter months match YoY; exact three-month steps
match consecutive quarters. Declared annual/YTD durations are rejected.

Default basis: prefer consolidated if present for the newest eligible period;
otherwise standalone. Keep that basis throughout the history; never fill a
missing consolidated comparative with a standalone value. The legacy statement
endpoint keeps its response contract. Parsed documents remain cached and dated
versions are appended to `quarter_versions` without overwriting earlier values.
A one-hour, 256-entry cache bounds repeated scoring-history retrieval.

An original missing from the exchange and never archived cannot be recovered.
V4 does not infer it. Corporate actions may make old EPS incomparable, and
current parsing does not extract restated comparative contexts or reconstruct
split-adjusted EPS history; these remain limitations for EPS-based factors.

## Measurement and calibration

Completed scans bank eligible `v4_raw_*`, every `v4_<horizon>_family_*`, raw and
final horizon scores, confidence, and the full `v4_audit`. Numeric versioned
names isolate new definitions from earlier unversioned factors. Snapshots
remain first-write-wins; rerunning cannot rewrite those historical values.

Factor Lab measures 5/10/21/63/**126** session excess returns against NIFTYBEES,
on identical stock/benchmark start and end dates. Missing benchmark dates
withhold labels. Labels are checked against the evaluation date. The benchmark
is broad-market, not a sector benchmark; this is not sector-neutral alpha.

Each factor reports per-date Spearman IC, mean, sample SD, unannualised IC/SD,
positive-IC date hit rate, top/bottom quintile excess returns, spread, evaluation
dates and usable observations. Summary needs >=25 stocks/date by default and
>=8 dates. `reliable` is retained as a legacy sample-gate field;
`statistically_validated` remains false. Overlapping dates are not independent
and the naive t-stat is explicitly not a significance test. No IC-to-win-rate
conversion or accuracy claim is justified.

`/pit/correlations` warns only after >=8 dates when absolute cross-sectional
Spearman correlation >=.85 on >=75% of those dates (last 126 scan dates).
It never changes weights. `/pit/suggested-weights` is research-only: after
126 warm-up dates it requires 60 widely spaced held-out dates for every pillar,
then suggests 70% prior +30% normalised nonnegative mean IC. This is a
conservative calendar-spacing approximation, not proof of independence.
No production scoring code calls it, and further independent validation and
human review would still be necessary.

## Missing fields and operational limits

Reported debt/equity and coverage tags showed ambiguous scaling in live XML
(e.g. `0.004` and `0.0467` under `unitRef="pure"`), plus zero sentinels.
V4 therefore withholds unverified leverage and derives interest coverage from
explicit income-statement lines. It never silently multiplies ratios by 100.

Reliable filed book equity/PB, EV/EBIT inputs, ROCE capital-employed inputs,
CFO/accruals, lender NPA/NIM/CASA/capital adequacy, and real-estate operating
KPIs are **not** derived from unsupported proxies. Existing `NetSegmentLiabilities`
is liabilities plus equity, not debt or book equity; paid-up share capital is
not book equity. These fields need verified taxonomy coverage and PIT provenance
before inclusion. Financial strength can therefore be sparsely covered.

No new production dependency or opaque ML model. NumPy arrays are per factor
and peer pool; full OHLCV DataFrames are not retained across the cohort.
First-time downloading 16 filings per analysed stock adds scan latency and
must be observed on Render; subsequent scans reuse cached documents. Partial
checkpoints publish partial-universe scores but are never banked as completed
v4 snapshots. Only completed scans enter measurement. Small partial cohorts
under 10 have no published ranks. Scan dates are visible; historical cached
scores are not represented as live recalculations.

Run `python -m pytest backend/tests -q`, `python -m compileall -q backend research`,
and `python research/validate_score_v4.py`. Add `--live` for read-only NSE checks.
The representative script labels synthetic arithmetic examples explicitly;
it does not claim current investable rankings from synthetic peers.
