# V4 validation — 9 September 2026

Baseline commit: `634d4e8e8c2376ea36f41b2ec8e10ad011876ed1`.
Untouched baseline: **447 backend tests passed**. V4: **469 passed** before integrating upstream changes; **518 passed** after merging main at `30b4a3f` (including its 49 new regression tests).
The four warnings also occur in the baseline: zero-price indicator divisions
and FastAPI's existing startup-event deprecation. No deployment performed.
All frontend script/inline-script syntax, share.js unit tests and duplicate-ID
checks passed. Python modules compile and `git diff --check` is clean.

## Live filing checks

Read-only NSE retrieval was run for RELIANCE, TCS, HDFCBANK, TATASTEEL,
HINDUNILVR, NTPC, DLF and PAYTM. Each returned a 16-quarter history with
newest period ending **30 June 2026**, known by the evaluation date, age 71
days. The JSON companion records every source URL and computed fundamental.
Bank taxonomy does not provide the required mapped corporate-style fields;
these remain absent, not proxies for bank asset quality. PAYTM is a new-age
example, not an assertion that it remains loss-making: live classification
uses filed EPS; the separate synthetic emerging case explicitly uses losses.

This exercise verified current/legacy merged history, fresh filings,
acceleration arithmetic and observable input gaps. Reported ratio tags had
ambiguous scaling (`0.004` debt/equity, `0.0467` interest coverage under pure
units) and zero placeholders. Unverified leverage is therefore withheld;
interest coverage is rebuilt from explicit monetary statement lines.

No production scan or authenticated Dhan request was triggered. Actual
cross-sectional final scores for these eight were **not** asserted: eight
companies do not meet the ten-peer minimum, and a cross-sector sample is not
an economically valid banking comparison group. A full production-like
universe rehearsal on Render with its credentials remains a rollout check;
it is not required to create/review this PR and has not been performed.

## Controlled representative examples

`python research/validate_score_v4.py` builds 240 synthetic observations over
the eight representative contexts (30 each). These are **arithmetic examples,
not current stock scores or backtest evidence**. `v4-validation.json` contains
raw and final scores, confidence and trade/invest alternatives. Scores stay
bounded and explainable; a lender retains lower confidence even with all
applicable synthetic factors because its capital-quality and value toolkit
is still missing. A 240-name run took approximately 0.4 seconds locally;
this is a ranker timing, not a Render memory/latency guarantee.

| Behaviour | Previous implementation | V4 |
| --- | --- | --- |
| Four EPS observations with gaps | Accepted as TTM in the old test | Withheld until four consecutive quarters |
| Stock with only strong momentum | No score below family floor | Raw high rank shrinks toward neutral; low confidence visible |
| Duplicate momentum metric | One family vote | One group/family vote; no extra confidence |
| Fundamental scan input | `quarters=None` | Cached PIT-selected XBRL history |
| Cyclical low trailing P/E | Generic earnings-yield vote | Excluded; three-year median annual EPS yield if supported |
| Bank corporate leverage/margin | Universal factor ranking | Excluded and bank fundamentals never pooled with corporates |
| Old filing revised later | Revision could displace old metadata before cutoff | Version retention, then cutoff, then revision selection |
| Ranking API | Re-ranked retained top rows | Reuses complete cached cohort scores for chosen horizon |

The test suite additionally covers ties, winsorisation, extreme values,
nonfinite/missing inputs, stale/future filings, exact seasonal matching,
consolidated/standalone separation, losses and tiny denominators, confidence
arithmetic, all horizon weights, correlation sample gates, IC/SD and quintile
metrics, version persistence, API/cache integration, full-cohort banking and
mismatched benchmark dates. Dynamic weight suggestions cannot activate changes.

## Remaining limitations

No v4 forward-return history yet exists to establish improved prediction.
EPS histories are not corporate-action adjusted or reconstructed from later
comparative contexts. Three annual EPS sums do not cover every commodity
cycle. Reliable bank PB/NPA/NIM/capital adequacy, book equity/EV inputs, cash
flow/accruals and ROCE capital-employed data remain missing. The Phase-2 cohort
is selected, the benchmark is broad-market, and overlapping IC observations
are not independent. See SCORING-V4.md for the complete methodology and limits.
