# Money Flow

Where institutional money is moving in Indian markets, sector by sector: which
sectors foreign portfolio investors are buying, whether price is confirming it
against the Nifty 50, and which stocks inside a favoured sector are being taken
to delivery.

It is a **ranking of published data, not a forecast**. FPI figures arrive a
fortnight at a time and about a week late; a sector FPIs bought has gone on to
fall often enough. Nothing here changes an Altaha Score.

- Page: Market › Money flow (`#discover/flows`), `frontend/money-flow.js`
- Engine: `backend/money_flow.py`, with `money_flow_sources.py` (reading),
  `money_flow_store.py` (keeping) and `money_flow_config.py` (the mapping and
  every weight)
- Job: `.github/workflows/money-flow.yml`, and `backend/backfill_money_flow.py`

## First run

The page is empty until history is read once. Either start the workflow by
hand with `job=backfill`, or:

```bash
python backend/backfill_money_flow.py --api https://taha-project.onrender.com --key "$ADMIN_KEY"
```

It reads two years in bounded slices and can be stopped and re-run; every row
is keyed on what it is, so nothing is written twice. After that the workflow
keeps it current on its own.

## What is read

| Source | What | Where | When it is published |
|---|---|---|---|
| NSDL | FPI equity net investment and assets under custody, per sector, per fortnight | A static page per fortnight, linked from the dropdown on `fpi.nsdl.co.in/web/Reports/FPI_Fortnightly_Selection.aspx` | About a week after the fortnight ends, on no fixed day |
| NSE | Every index's close | `nsearchives.nseindia.com/content/indices/ind_close_all_DDMMYYYY.csv` | Each evening |
| NSE | FII and DII cash-market buy, sell and net (provisional) | `nseindia.com/api/fiidiiTradeReact` | Each evening, **latest session only** |
| NSE | Bulk and block deals | `nsearchives.nseindia.com/content/equities/bulk.csv`, `block.csv`; history from the site's CSV download | Each evening |
| NSE | Delivered share, volume and close per stock (`sec_bhavdata_full`) | Already kept by `special.py` as 400-session panels | Each evening |

Three things about reading them that are easy to get wrong:

- **NSDL's file names are typed by hand** (`..._June302026.html` beside
  `..._Jul152026.html`, and one early `FIIInvestSecor_`). A URL is never built
  from a date, only read from the dropdown.
- **NSDL's table has changed width three times.** The parser rebuilds the
  header (colspans expanded) and finds a figure by what it is called: the block
  named "Net Investment *period*", in INR, the first column headed Equity. A
  report that cannot be read that way fails with the reason and is asked for
  again; it is never stored from guessed columns. The page's own Grand Total
  is the check that the right column was read.
- **NSE's deals history API returns 70 rows as JSON and says nothing about the
  rest.** One busy session is more than 70. It is read as the CSV download,
  which is whole.

Each NSDL report carries two fortnights, so every fortnight is published
twice. Both copies are stored into one row and a figure that moved is counted
(`revisions`). Over the two years backfilled while building this, none did.

## The sector mapping

NSDL files FPI money under the 22 sectors of the industry classification NSE
and BSE adopted in 2022. `backend/nse_industries.csv`, which this site's stock
universe already uses, is NSE's copy of the same 22. So **NSDL sector → our
stocks is the same list, one to one** (NSDL writes two names with commas).
`test_every_industry_in_our_universe_is_a_sector_in_the_table` pins that.

**NSDL sector → NSE index is a judgement**, and each row says how good:

| NSDL sector | NSE index | Fit |
|---|---|---|
| Automobile and Auto Components | Nifty Auto | Clean |
| Capital Goods | Nifty Capital Goods | Clean, new index |
| Chemicals | Nifty Chemicals | Clean, new index |
| Construction | Nifty Infrastructure | **A judgement.** No construction index exists; this one is led by Reliance, Airtel, L&T and power |
| Construction Materials | Nifty Cement | Broad: cement is most of the sector, not all. New index |
| Consumer Durables | Nifty Consumer Durables | Clean |
| Consumer Services | Nifty Consumer Services | Clean, new index |
| Fast Moving Consumer Goods | Nifty FMCG | Clean |
| Financial Services | Nifty Financial Services | Clean. NSDL does not split banks from NBFCs and insurers |
| Healthcare | Nifty Healthcare Index | Clean. Pharma is a part of it |
| Information Technology | Nifty IT | Clean |
| Media, Entertainment & Publication | Nifty Media | Clean |
| Metals & Mining | Nifty Metal | Clean |
| Oil, Gas & Consumable Fuels | Nifty Oil & Gas | Clean. Nifty Energy also holds power |
| Power | Nifty Power | Clean, new index |
| Realty | Nifty Realty | Clean |
| Services | Nifty Transportation & Logistics | **A judgement.** "Nifty Services Sector" is banks, IT and telecom |
| Telecommunication | Nifty Telecommunications | Clean, new index |
| Textiles | none | Basket of its own stocks |
| Diversified, Forest Materials, Utilities | none | 1, 1 and 4 companies in our universe: flows shown, not scored |
| Sovereign, Others | — | Not equity sectors; stored, left off the page |

"New index" means it was not in NSE's daily file in November 2024. A sector
whose index has under 130 sessions stored is measured on a **basket of its own
stocks**, weighted by rupees traded and capped at 25% a stock, until the index
has enough; its card says which it used.

Nifty Bank, Private Bank, PSU Bank, Pharma, PSE and Energy cut across the
classification, so no NSDL sector stands behind them. They can be switched on
in the rotation chart as **themes**: price only, no FPI flow, no score.

## The Sector Money Flow Score

Out of 100. Weights are `SCORE_WEIGHTS` in `money_flow_config.py`, or
`MONEYFLOW_WEIGHTS="fpi=40,rs=35,breadth=25"`.

| Part | Weight | What it is |
|---|---:|---|
| FPI flow | 40 | Three percentile ranks among the scored sectors, of flow as a share of the sector's assets under custody: the last three fortnights together (0.5), the latest (0.3), the change from the one before (0.2) |
| Rotation | 35 | The sector's quadrant (Leading 1.0, Improving 0.75, Weakening 0.4, Lagging 0.1) at 0.4, and percentile ranks of its return against the Nifty 50 over 63 sessions (0.35) and 21 (0.25) |
| Breadth | 25 | The share of the sector's stocks above their own 50-day average |

A part that cannot be measured is left out and the rest re-weighted, and the
card says which. One part alone is not a score.

**Flow as a share of assets under custody**, not rupees: Rs 600 crore into
Media is a larger event for Media than Rs 5,000 crore is for Financials. The
price of that choice is that a small sector's score moves on small sums.

**The flow trend**: accelerating (same direction as the fortnight before,
larger), decelerating (same direction, smaller), reversing (the direction
changed). A sector whose latest fortnight is an inflow after an outflow is
flagged as having flipped.

**The rotation chart is RRG-style, not the licensed formula.** On daily closes:
RS is the sector over the Nifty 50; RS-ratio is RS's 10-session exponential
average over its 50-session one; RS-momentum is that ratio over its own
20-session average; both times 100, read at each week's last session. Unsmoothed
weekly points were tried first and moved four or five points a week in both
directions, which drawn as a trail is a scribble.

**Stock-level accumulation**, per stock in a sector, 0 to 100: delivered share
over the last 5 sessions against the 20 before (up to 45; 0.9× scores 0, 1.5×
all 45), sessions of the last 5 closed up on above-usual volume (8 each, up to
40), and net buying in bulk and block deals over 30 days (+15, or −15 for net
selling), with market makers and same-client round trips taken out the way
`deals.py` does. A split or bonus in the window, or under Rs 2 crore a day
traded, and the stock is not ranked.

## Storage

`DATA_DIR/altaha_money_flow.db`, SQLite, schema in
`backend/migrations/moneyflow/`.

| Table | Holds |
|---|---|
| `fpi_sector_fortnight`, `fpi_reports` | NSDL rows, and which report pages have been read |
| `inst_flow_daily` | FII and DII per session. **The only copy**: NSE has no archive |
| `index_close_daily`, `index_days` | Index closes, and days already settled (stored, or no file) |
| `deals_daily`, `deals_windows` | Disclosures, keyed on the whole disclosure |
| `sector_score_daily`, `stock_accumulation_daily`, `snapshots` | What was worked out, per session |
| `job_runs`, `alerts_sent` | Every job run with what each step did; alerts already sent |

The bhavcopy is not copied in: `special.py` already holds it as panels and
`bhav_archive.py` keeps five years of the files in R2.

## Jobs

`POST /admin/moneyflow/run?job=daily|backfill|recompute` (admin key).

- **daily**: the last ten days of index closes, FII/DII, deals, any NSDL
  report not yet read, then the scores. Weekdays 20:40 IST, and 08:55 IST the
  next morning for a file that landed late.
- **backfill**: one bounded slice; call until `remaining` is 0.
- There is no separate fortnightly job: NSDL publishes on no fixed day, so
  every run reads its list and fetches only what is new.

Each step is caught on its own, so NSE refusing the deals file does not lose
the day's index closes. A failed step is in the run's `errors`, the workflow
goes red, and `GET /moneyflow/status` keeps the last runs.

## Endpoints

| | |
|---|---|
| `GET /moneyflow` | The page in one payload |
| `GET /moneyflow/sector/{slug}` | A sector's card, 24 fortnights, and its accumulation rows |
| `GET /moneyflow/brief` | A few figures for the Market page's card |
| `GET /moneyflow/status` | Coverage, last runs, alerts, the weights in force |
| `POST /admin/moneyflow/run` | Run a job |

Every public endpoint is a read of what the job stored.

## Where it touches the rest of the site

- **The Altaha Score: nowhere.** v4 is a peer-percentile score with
  point-in-time rules and no sector input; adding one moves every score and
  needs its own validation study.
- **Beside a stock**: `/analyze` and every Ideas row carry `sector_tailwind`
  (the sector's rank, quadrant and latest FPI flow in one line). Printed on
  the stock page under the key figures and on a pick as a fact. It ranks
  nothing.
- **Ideas sector caps**: `IDEAS_MONEYFLOW_CAPS=on` lets a sector in the top
  quarter on money flow give 5 names to a list and one in the bottom quarter
  2, where every sector gives 4 today. **Off by default**; with it off a list
  is exactly the list it was (`test_with_the_flag_off_a_list_is_what_it_was`).
  No weight in `ideas.py` changed.
- **Not done**: feeding the score into the existing "Money flow" pick list.
  That list's record is a ten-year replay of its own rule (turnover shift,
  breadth, one-month move); changing its input needs a replay of its own.
- **Telegram**: when a sector moves into Improving or Leading while FPIs were
  net buyers in the latest fortnight, one message to the private chat, once
  per sector per fortnight. `MONEYFLOW_TELEGRAM=off` silences it;
  `MONEYFLOW_ALERT_REQUIRE_FLIP=on` narrows it to sectors FPIs had been
  selling the fortnight before.

## What is missing, and what was assumed

- **Daily FII/DII history starts when the job starts.** NSE publishes the
  latest session only. The store is seeded from the 90 days `market_week.py`
  already recorded; the 5- and 20-session totals say how many sessions they
  cover until there are enough. Under five sessions the page shows the two
  figures, not a chart.
- **FII/DII figures are provisional.** The final NSDL/CDSL numbers land a day
  later and differ slightly.
- **FPI flow includes primary-market and block purchases**, not only what was
  bought on screen. One large IPO or stake sale can be a sector's whole
  fortnight.
- **Deal history may not backfill from Render.** NSE refuses its history API
  from many datacenter addresses. The job notes it and carries on; the daily
  file fills the record from then on. Run the backfill from a laptop to get it.
- **The stock universe is about 750 names** (Nifty Total Market). A stock
  outside it has no sector here and no tailwind.
- **Prices are unadjusted.** A one-session move the size of a split or bonus
  leaves that stock out of breadth, the basket and accumulation for 50
  sessions rather than counting it as a fall.
- **Three sectors are not scored** (Diversified, Forest Materials, Utilities):
  too few companies to measure breadth or a basket.
- **Before April 2022 NSDL used a different sector list.** The parser reads
  those pages; the mapping does not know those names and reports them as
  unknown. A backfill past that date needs a second mapping.
- **AMFI monthly category flows** are not read. Phase 2.

## Tests

```bash
python -m pytest backend/tests/test_money_flow_sources.py backend/tests/test_money_flow.py backend/tests/test_money_flow_endpoints.py
node frontend/money-flow.test.js
node frontend/tests/money-flow-browser.cjs
```

The parser tests read trimmed copies of the real NSDL and NSE files
(`backend/tests/fixtures/moneyflow/`). Everything else runs on an invented
market whose answers can be worked out by hand.
