# Lenses — current-state data audit and sourcing plan

Phase 1 deliverable for the Lenses feature. No feature code ships with this
document. It answers four questions: what data the codebase has today, what
each lens rule needs, where the missing fields can come from, and what to do
about it.

Audit date: 23 September 2026. Every claim about the codebase cites the file it
comes from. Every vendor price was checked on the audit date. Where a vendor
does not publish a price, or its page blocked the check, the doc says so and
does not guess.

---

## Summary

- **The "persistent DB" is several SQLite files on a 1 GB Render disk
  (`DATA_DIR=/data`), plus JSON and pickle caches. There is no fundamentals
  table.** Fundamentals are fetched when a page asks for them. They come from
  two places: yfinance (4 annual and about 5 quarterly statements) and NSE
  XBRL results filings, parsed on demand and cached to disk. Only the ~200
  Phase-2 names in each universe scan get their derived factors written to
  `altaha_pit.db`.
- **The XBRL reader is the best asset we have.** It already reads the income
  statement, EPS, paid-up capital and face value (so share count), and the
  segment-reconciliation totals from NSE's own filings. NSE's filing index goes
  back about 8 years (Reliance: 65 documents, 33 per basis). The reader does
  not parse the half-yearly balance sheet or cash-flow statement yet.
- **Ownership comes from NSE shareholding XBRL, about 5 years deep, on demand,
  NSE symbols only.** It covers promoter, FII and DII. It does not read pledges
  (`ownership_insights.py` returns `"pledge_pct": None`).
- **Of the 10 lenses:**
  - **Live now, with small parser work:** Cannibal, Owner (once the pledge
    parse is added), Tenbagger, QGLP (partly: the ROE rule needs the balance
    sheet).
  - **Live once the data is sourced:** Gorilla, Nomad, Akre. These need the
    half-yearly balance sheet and cash-flow XBRL plus NSE industry
    classification.
  - **Blocked on 10-year history:** Moat and Coffee Can. The free exchange XBRL
    history is about 8 years.
  - **Blocked:** Capital Cycle. It needs industry-level capex and a history of
    listings.
- **Recommended stack: ₹0 a month in data fees.**
  - India: extend our own NSE/BSE XBRL reader (build, not buy), and add the
    NSE industry classification and pledge disclosures.
  - US: the SEC EDGAR companyfacts API.
  - To get from about 8 years of India history to 10: backfill from the BSE
    XBRL archive, and put the two 10-year lenses behind "Coming soon" until a
    per-company check shows 10 fiscal years.
  - Paid feeds are not needed to launch. None of the retail-priced ones
    (EODHD, FMP) allows public display without a separate commercial licence.

---

## A. What we have today

### A.1 Every data source in the codebase

| # | Source | Module | What it provides | How often it is fetched | Where it is stored | History depth |
|---|---|---|---|---|---|---|
| 1 | **Dhan API v2** (`api.dhan.co/v2`) | `dhan_source.py`, `livefeed.py`, `intraday.py` | Daily OHLCV (`/charts/historical`), intraday candles 1–60 min (`/charts/intraday`), quotes with volume (`/marketfeed/quote`), option chain, instrument master CSV. **No fundamentals.** | On request (30-min in-memory cache in `data_source.py`). Intraday scanner every 60 s (`POLL_SECONDS`). WebSocket live relay. | In memory only. `intraday.py` writes `signal_log.json` and `vol_profiles.json` to `DATA_DIR`. | Daily history is requested 400 days back by default (`daily_ohlcv(days=400)`). Intraday: 5–7 days. |
| 2 | **Yahoo Finance via yfinance** | `data_source.py`, `engine.py`, `scan.py`, `sectors.py`, `sector_story.py` | Prices (fallback to Dhan, and the only price source for US tickers). Annual income statement, balance sheet and cash flow (`t.financials`, `balance_sheet`, `cashflow`). `t.info` (sector, industry, marketCap, trailingPE, trailingEps, bookValue, dividendYield, heldPercentInsiders/Institutions). | On request (30-min cache). The universe scan pulls 1–2 y of prices in bulk plus Phase-2 fundamentals. | Memory. Phase-2 derivatives go to `altaha_pit.db` → `factor_snapshots`, and the leaderboard to `leaderboard.json`. | Statements: **4 fiscal years annual** and about 5 quarters. Prices: 2 y for Phase 2. |
| 3 | **NSE results XBRL** (LODR Reg 33) | `xbrl.py`, `fundamentals.py` | Full quarterly P&L, EPS, paid-up capital, face value, segment totals (total assets and liabilities), D/E, DSCR and ISCR ratios where filed. Standalone and consolidated. | On request. The filing index is fetched live. Each parsed document is cached for good (filed XBRL never changes). | `$DATA_DIR/xbrl-cache/*.json`. Scoring rows are copied to `altaha_pit.db → quarter_versions` (append-only). | The filing index spans two regimes: legacy up to Dec 2024 and Integrated Filing since. **About 8 years** (Reliance: 33 standalone + 32 consolidated quarterly documents, per `FUNDAMENTALS.md`). |
| 4 | **NSE shareholding pattern XBRL** (LODR Reg 31) | `shareholding_filings.py`, `ownership_insights.py` | Promoter, FII, DII, non-institutional and govt %. Holder counts. Named promoter entities and public holders above 1%. | On request (index TTL 6 h). The nightly GitHub workflow `holdings.yml` crawls slices for the investor ledger. | Parse cache `$DATA_DIR/shp-cache/*.json`. Named holder rows in `altaha_holdings.db → holdings` (`symbol, period_end, holder, pct, shares, promoter flag`), crawl state in `coverage`. **Category totals (promoter %, FII %, DII %) are not persisted as rows.** | About **5 years** (what NSE serves). A page parses up to 12 quarters (`MAX_PARSE`). |
| 5 | **BSE corporate announcements** | `announcements.py` | Filing headlines, category (rule-based, including a "Pledge" category), PDF links, ISIN join. | Polled every 300 s (`ANN_POLL_SECONDS`). | In memory, capped at 1,200 items (`ANN_MAX_STORED`). Filing dates are also written to `altaha_pit.db → filings` for point-in-time use. | Rolling. Backfill `poll(days=…)` of a few days. |
| 6 | **NSE corporate announcements** | `announcements.py` (secondary) | Same, keyed by symbol. | With the poller. | Memory. | Rolling. |
| 7 | **Filing PDFs** (BSE/NSE attachments) | `filings_text.py`, `wow_orders.py`, `concalls.py` | Text of the filing: order values, earnings-call transcripts. | On demand and backfill job (`/jobs/wow-backfill`). | `$DATA_DIR/filing-text/`, `wow_orders.db`, `concalls.db`. | Whatever has been backfilled. |
| 8 | **NSE bulk, block and short deals** | `deals.py` | Deal disclosures. | Snapshot polled intraday. History queried on demand. | In-memory cache. | Up to 365 days per query (NSE `/api/historical`). |
| 9 | **NSE full bhavcopy** (`DELIV_PER`) | `special.py` | Per-stock daily OHLC, volume, delivery %, for the whole exchange (about 2,665 EQ symbols). | Daily build in chunks. | `$DATA_DIR/delivery_panels_v3.pkl` (float32 panels). | 400 sessions (`SPECIAL_RETAIN`). |
| 10 | **NSE equity list** `EQUITY_L.csv` | `scan.py` | Universe of about 2,000+ NSE equities, with listing date. | Each universe scan. | Memory. | Current listings only (no delisted names). |
| 11 | **AMC monthly portfolio workbooks** (via AMFI's list) | `fund_portfolios.py`, `fund_workbook.py` | Every scheme holding with ISIN, quantity, value and % of NAV. | Nightly workflow. | `altaha_holdings.db → fund_holdings, fund_packs`. ISIN map `nse-isin-map.json`. | From when the crawl started. About 22 of 53 AMCs are reachable. |
| 12 | **Press RSS** (Moneycontrol, ET, BS, Mint, TOI, Hindu BL, CNBC, FT) | `news_feed.py`, `market_news.py` | Headlines only. By design they **never touch a score**. | `news_feed` on a TTL. `market_news` every 900 s. | `news_feed`: memory. `market_news`: `$DATA_DIR/market_news.json`, capped at 2,000. | Rolling. |
| 13 | **Bundled sector map** | `sectors.py`, `sector_story.py` | A hand-written symbol → sector map (GICS-style names) covering Nifty-500 names, used as the fallback for yfinance `info["sector"]`. | Static. | Code. | n/a |
| 14 | **Outbound only** (Telegram, X, Resend/Brevo, Google OAuth) | `alerts.py`, `social_x.py`, `mailer.py`, `accounts.py` | Not data sources. Listed so the inventory is complete. | | | |

Local SQLite databases in `DATA_DIR`:
- `altaha_pit.db`: `scan_runs`, `factor_snapshots` (long format), `filings`,
  `forward_returns`, `quarter_versions`
- `altaha_holdings.db`: `holdings`, `coverage`, `fund_holdings`, `fund_packs`
- `altaha_accounts.db`: users, sessions, holdings, watchlist, risk profiles,
  send log
- `concalls.db`
- `wow_orders.db`

The disk is 1 GB (`render.yaml`).

### A.2 Fundamentals fields stored today

**India.** Three stores, none of which is a queryable fundamentals table:

| Field | yfinance (annual, 4 y) | NSE XBRL (quarterly, ~8 y, on-demand cache) | Persisted to PIT DB? |
|---|---|---|---|
| Revenue | `Total Revenue` | `revenue`, `total_income`, `other_income` | Only derived factors (`revenue_growth`, `revenue_acceleration`) for Phase-2 names |
| Expense lines | — | materials, purchases, inventory change, employee, finance cost, depreciation, other expenses, total expenses | No |
| EBIT / Operating income | `EBIT` / `Operating Income` | derivable: PBT + finance cost − other income | No |
| EBITDA, EBITDA margin | — | `ebitda`, `ebitda_margin_pct` (derived, all add-backs required) | `margin_level`, `margin_trend` factors |
| PBT, tax, PAT | `Net Income` | `pbt`, `pbt_before_exceptional`, `exceptional`, `current_tax`, `deferred_tax`, `tax`, `pat`, `comprehensive_income` | `earnings_growth`, `earnings_consistency` |
| EPS basic and diluted | `trailingEps` (info) | `eps_basic`, `eps_diluted` | `earnings_yield`, `eps_acceleration`, `earnings_surprise`, and `trailing_eps` in the scan row |
| Share count | `Ordinary Shares Number` (2 y used) | `equity_capital` ÷ `face_value` | No |
| Total assets | `Total Assets` | `total_assets` (from the **segment reconciliation**, so blank for single-segment filers) | `return_on_assets` |
| Total liabilities | — | `total_liabilities` (segment reconciliation) | No |
| Current assets and liabilities | `Current Assets`, `Current Liabilities` | **not parsed** | No |
| Equity | `Stockholders Equity` | **not parsed** (half-yearly balance-sheet tags are not read) | `roe` in grid ratios (latest only) |
| Long-term debt | `Long Term Debt` | `debt_equity` ratio (withheld: units unvalidated) | `de` grid ratio (latest only) |
| Operating cash flow | `Operating Cash Flow` | **not parsed** | No |
| Capex | `Capital Expenditure` | **not parsed** | No |
| ROCE | computed: EBIT ÷ (TA − CL), latest year | — | `roce` grid ratio (latest only) |
| Market cap, P/E, book value, dividend yield | `info` | — | In the scan row, not as history |
| Sector and industry | `info["sector"]`, `info["industry"]` (often blank for small caps) + bundled map | — | `sector` text factor |
| Promoter %, FII %, DII % | `heldPercentInsiders/Institutions` (rough) | **Shareholding XBRL**, quarterly, ~5 y | Named rows only, in `holdings` |
| Pledge % | — | **not parsed** | No |

**US.** Only the yfinance path. The same annual statements and `info` fields
as above, 4 fiscal years, fetched per request, with nothing persisted outside
a scan. The universe scan is NSE-only (`scan.py` builds `f"{s}.NS"` tickers),
so **US stocks exist only as single-symbol lookups**. There is no US universe
to screen over.

### A.3 The existing scoring in `scoring.js`

The task brief calls it "six-component". The code does not match that:
`scoring.js` renders **five pillars** (v3 `profiles.PILLARS`). When
`altaha_score_v4` is present it renders the **eight v4 families** instead. None
of the lenses need either one; this section is here so nothing gets
double-built.

| Pillar (`profiles.PILLARS`) | Inputs | Source |
|---|---|---|
| Momentum (price trend) | EMA structure, Hull MA, RSI, MACD, ADX, Supertrend, 52-week position (`engine.technical_score`). v4: 12–1 momentum and trend R². | Dhan daily OHLCV → Yahoo fallback |
| Participation | Volume and turnover vs history (v4 `volume_shock`). Promoter and institutional holding points in `engine.fundamental_score`. | Dhan/Yahoo volume; yfinance `info` ownership |
| Quality | Piotroski F-Score (yfinance statements), ROCE, D/E. v4: ROA and EBITDA margin from XBRL, earnings persistence, other-income share. | yfinance annual + NSE XBRL quarterly |
| Improvement | Revenue growth YoY, margin delta, G-Score. v4: growth and acceleration families from XBRL. | yfinance + NSE XBRL |
| Valuation | Trailing P/E (`info.trailingPE`). v4: TTM EPS ÷ price, and a cyclical 3-year median yield. | yfinance `info`, XBRL EPS, Dhan price |

v4 adds `risk` (reversal, low volatility) and `financial_strength` (interest
coverage; leverage is withheld). Weights come from `archetypes.py` and
`profiles.v4_weights`, by business model and horizon. The frontend gets it all
from `/analyze` as `scoring` / `altaha_score_v4` and does not fetch data of
its own.

---

## B. Gap analysis

Status key:
- **A** — available: the data is in the codebase and a lens can compute it
  today.
- **P** — partial: some of it is there (latest only, on-demand only, subset of
  companies, or short history).
- **M** — missing.

"Have" is the best current source for India. The US column assumes SEC
companyfacts, which is not wired yet.

| Lens | Rule | Fields required | India status | History needed | History we have (India) | US via SEC (not wired) |
|---|---|---|---|---|---|---|
| **gorilla** | Industry revenue rank ≤ 2 | Revenue (annual/TTM) for all peers; **industry classification** | **P**: revenue via XBRL on demand; industry is yfinance or the bundled map, which is coarse and blank for many small caps | 1 y | TTM computable from 4 XBRL quarters | Revenue ✓; industry = SIC from the submissions API |
| | 5y revenue CAGR > 15% | Annual revenue, 6 fiscal years | **P**: yfinance 4 y; XBRL ~8 y but not stored as annual series | 5 y (6 points) | yfinance 4 y ✗; XBRL ~8 y ✓ once aggregated | ✓ |
| | ROCE > 20% | EBIT, total assets, current liabilities | **P**: latest year from yfinance only; XBRL lacks CL | 1 y | yfinance latest | ✓ |
| | EBITDA margin > industry median, each of last 3 y | EBITDA, revenue, industry peers | **P**: EBITDA from XBRL ✓; industry ✗ | 3 y | XBRL ✓ | ✓ (OperatingIncome + D&A) |
| **moat** | ROE > 15% every year for 10 y | PAT, shareholders' equity per year | **M**: equity only from yfinance (4 y); XBRL balance sheet not parsed | 10 y | 4 y | ✓ (2009+) |
| | D/E < 0.5 | Total debt, equity | **P**: yfinance latest; XBRL `DebtEquityRatio` withheld | 1 y | latest | ✓ |
| | FCF positive in ≥ 8 of 10 y | CFO, capex per year | **M**: yfinance 4 y only; XBRL cash flow not parsed | 10 y | 4 y | ✓ |
| | 10y margin std dev in bottom third | Margin series, universe distribution | **P**: XBRL EBITDA margin ~8 y | 10 y | ~8 y | ✓ |
| **tenbagger** | EPS growth 20–50% | EPS, TTM vs prior TTM | **A**: XBRL EPS | 2 y | ✓ | ✓ |
| | PEG < 1 | Price, TTM EPS, EPS growth | **A**: Dhan price + XBRL | 2 y | ✓ | ✓ (price from yfinance) |
| | Small or mid cap | Market cap; SEBI/AMFI rank bands | **P**: yfinance `marketCap` (patchy); AMFI list not ingested | now | — | Mcap from shares × price |
| | FII + DII < 20% | Shareholding categories | **P**: SHP XBRL on demand; totals not persisted | 1 q | ~5 y | **n/a** (no FII/DII concept); 13F is not equivalent |
| **coffeecan** | Revenue growth ≥ 10% every one of last 10 y | Annual revenue, 11 fiscal years | **M** for 10 y: XBRL ~8 y | 10 y (11 points) | ~8 y | ✓ |
| | ROCE ≥ 15% every one of last 10 y | EBIT, CE per year | **M** | 10 y | yfinance 4 y | ✓ |
| **qglp** | ROE > 20% | PAT, equity | **P**: yfinance latest | 1 y | latest | ✓ |
| | 3y EPS CAGR > 20% | Annual EPS, 4 fiscal years | **A**: XBRL ~8 y | 3 y | ✓ | ✓ |
| | Positive EPS growth each of last 3 y | Annual EPS | **A** | 3 y | ✓ | ✓ |
| | PEG < 1 | as above | **A** | 2 y | ✓ | ✓ |
| **akre** | ROCE > 20% | as above | **P** | 1 y | latest | ✓ |
| | Promoter holding > 50% | SHP | **P**: on demand | 1 q | ~5 y | **n/a** (US: insider % is not equivalent) |
| | Pledge = 0 | Promoter encumbrance | **M**: parser returns `None` | 1 q | — | **n/a** |
| | Reinvestment rate > 50% | Capex, D&A, ΔWC, NOPAT | **M**: no cash flow and no working capital | 3 y | — | ✓ |
| | ROCE not falling over 3 y | ROCE series | **M** (needs CL history) | 3 y | yfinance ≤ 4 y | ✓ |
| **nomad** | 5y revenue CAGR > 15% | as gorilla | **P** | 5 y | XBRL ~8 y | ✓ |
| | Margin change over 5 y within ±2 pp | EBITDA margin series | **A**: XBRL | 5 y | ~8 y | ✓ |
| | Asset turnover rising over 3 y | Revenue, total assets | **P**: XBRL TA only for multi-segment filers | 3 y | partial | ✓ |
| **cannibal** | Share count down > 2% p.a. over 3 y | Shares outstanding series | **A**: XBRL paid-up capital ÷ face value, quarterly. Must adjust for splits/bonus (see note). | 3 y | ~8 y | ✓ (`dei:EntityCommonStockSharesOutstanding`) |
| **owner** | Promoter holding > 50% | SHP | **P**: on demand | 1 q | ~5 y | **n/a** |
| | Pledge = 0 | encumbrance | **M** | 1 q | — | **n/a** |
| | Promoter stake up in last 4 quarters | SHP series | **P**: on demand, 12 q parse cap | 5 q | ~5 y | **n/a** |
| **capcycle** | Industry capex / depreciation falling over 3 y | Capex (cash flow) and D&A for **every company in the industry**; industry classification | **M**: capex not parsed; industry coarse | 4 y | — | ✓ capex/D&A; SIC industries |
| | Number of listed peers flat or falling | Listings **and delistings** by industry over time | **M**: `EQUITY_L.csv` is current listings only | 3 y | — | Partial: EDGAR submissions carry no delisting flag |

**Cross-cutting gaps**

1. **There is no persisted fundamentals table.** Every lens needs a stored,
   nightly-refreshed, per-company annual (and TTM) series for the whole
   universe. Today XBRL is parsed on demand and only for companies someone
   has viewed.
2. **Industry classification.** NSE's four-level scheme (12 macro-sectors, 22
   sectors, 59 industries, 197 basic industries) is not ingested. Gorilla,
   Capital Cycle and the margin-vs-median rule depend on it.
3. **Half-yearly balance sheet and cash flow.** LODR Reg 33(3)(f),(g) requires
   a statement of assets and liabilities and a cash-flow statement with the
   Q2 and Q4 results, and they are filed in the same results XBRL. `xbrl.py`'s
   docstring says the quarterly filing "does NOT carry" them. That is true of
   Q1 and Q3 only. **This needs a probe on real Q2/Q4 documents before Phase 2
   depends on it**, because it is the single biggest unlock.
4. **Splits and bonus issues in share count.** `equity_capital ÷ face_value`
   follows splits. A bonus issue raises the count with no economic dilution,
   and without an adjustment a Cannibal rule would read it as issuance. The
   corporate-actions feed (NSE `corporates-corporateActions`) gives bonus
   ratios. Until that adjustment exists, a bonus year is marked `n/a`, not a
   fail.

### Conclusion: which lenses can go live when

| Lens | Verdict | What unlocks it |
|---|---|---|
| **cannibal** | **Live now** (India + US once SEC is wired) | Persist the XBRL share-count series. Bonus-year handling as above. |
| **tenbagger** | **Live now** (India) | Persist EPS and TTM. Size band from the AMFI list. Persist SHP category totals. On US stocks the FII+DII rule is `n/a`, so coverage caps at 3 of 4 = 75%, which just meets `min_coverage`. |
| **qglp** | **Live now at 3 of 4 rules**, fully live after the BS parse | ROE needs equity (half-yearly BS XBRL). Until then ROE is `n/a` and the lens runs at 75% coverage. |
| **owner** | **Live after a small parser change** (India only) | Read the encumbered-shares columns already in the SHP XBRL (Table II) and persist the category history. US: the whole lens is `n/a`, so those stocks show "insufficient data". |
| **gorilla** | **After sourcing** | NSE industry classification, plus balance sheet for ROCE, plus the annual revenue series. |
| **nomad** | **After sourcing** | Total assets for single-segment filers (half-yearly BS). |
| **akre** | **After sourcing** | Cash flow (capex) and BS for the reinvestment rate and the ROCE trend, plus pledge. |
| **moat** | **Blocked** on 10-year history (India). Live for US once SEC is wired. | See D.3. |
| **coffeecan** | **Blocked** on 10-year history (India). Live for US once SEC is wired. | See D.3. |
| **capcycle** | **Blocked** | Needs capex for the whole industry and a listings/delistings history per industry. Ships as "Coming soon". |

A lens is only shown as live when it has real coverage for its market. Where a
lens is live for the US but blocked for India (Moat, Coffee Can), I propose
showing it as **"Coming soon"** until India is unlocked. It would otherwise
look like a US-only screen on an India-first site. This is your call (see
"Decisions I need").

---

## C. Sourcing options for each missing field

Prices were checked on 23 Sep 2026. "Not published" means the vendor quotes
on request. We did not guess a figure.

### C.1 India: official and free

| Source | Fields covered | History | Coverage | Cost | Access | Reliability | Licensing for a public site |
|---|---|---|---|---|---|---|---|
| **NSE results XBRL** (Reg 33; legacy + Integrated Filing) | Full P&L quarterly. **Q2 and Q4: balance sheet and cash-flow statement** (to verify). EPS, paid-up capital, face value. | ~8 y on NSE's index | All NSE-listed | Free | JSON index + XML documents. `curl_cffi` needed (WAF). **Already built** (`xbrl.py`, `nse_http.py`). | Good once warmed. Throttles bursts. Formats changed twice (legacy → Integrated, Dec 2024). | The documents are the companies' own statutory filings. NSE's website terms restrict the portal to non-commercial use, and commercial use of *market data* is licensed by NSE Data ([policy](https://www.nseindia.com/static/market-data/nse-data-policy), [terms](https://www.nseindia.com/static/nse-terms-of-use)). Showing figures derived from issuer filings with attribution is what this site already does. Automated bulk fetching is the grey area. Keep request rates polite and **get a written opinion before relying on it commercially.** |
| **BSE results XBRL** | Same filings, BSE copy | BSE's archive is typically deeper than NSE's index (XBRL on BSE since about FY2011–12 for larger filers). **Needs a probe per company.** | All BSE-listed (includes BSE-only scrips NSE lacks) | Free | `api.bseindia.com` JSON + XML. Plain `requests` works (as `announcements.py` shows). | Good | Same position as NSE. |
| **Shareholding pattern XBRL** (Reg 31) | Promoter/FII/DII/public %, holder counts, named holders, **and promoter shares pledged/encumbered (Table II columns)** | NSE ~5 y. BSE deeper. | All listed | Free | **Already built** (`shareholding_filings.py`). Pledge columns need adding. | Good. Two taxonomies handled. | Same as above. |
| **SAST Reg 31 pledge disclosures** + NSE "Pledged Data" page | Event-level creation, invocation and release of encumbrance. Aggregate pledged % per company. | Several years | NSE-listed | Free | NSE JSON behind the same WAF, with a CSV download | Medium (event data, needs reconciling) | Same as NSE. |
| **NSE industry classification** (NSE Indices four-level: 12 / 22 / 59 / 197) | Macro-sector → sector → industry → basic industry, per company | Current, plus the NSE Indices change notices | All NSE-listed | Free | Per-symbol in NSE's quote API (`industryInfo`), and the structure PDF from NSE Indices | Good | Classification is published by NSE Indices. Attribution is the norm. Confirm in the same written opinion. |
| **MCA annual filings** (AOC-4 XBRL) | Full statutory financials, including notes | FY2011+ for XBRL filers | All companies (listed and unlisted) | ₹100 per company view (public documents) | **Portal, no API.** Documents are per company and per year, behind a CAPTCHA and login. | Poor for automation | Public documents, but the portal is not built for bulk use. **Not recommended.** |
| **NSE equity list + delisted list** | Listing dates. Delisted companies with dates. | Delisted archive goes back years | NSE | Free | CSV | Good | As above |
| **AMFI large/mid/small-cap list** | SEBI category rank (1–100 large, 101–250 mid, 251+ small) | Semi-annual since 2018 | All listed | Free | XLSX on amfiindia.com | Good | Public regulatory list |

### C.2 India: paid feeds

| Vendor | Fields | History | India / US | Price (checked 23 Sep 2026) | Access | Licensing for a public site |
|---|---|---|---|---|---|---|
| **Trendlyne API** | Fundamentals, shareholding, and their own scores | Not published | India (US site exists) | **Not published.** Their API page refused automated access (HTTP 405). Quote needed. | API | Must be negotiated. Their consumer terms bar reproduction. |
| **CMOTS** (APIDataFeed) | Equity fundamentals, shareholding, corporate actions, announcements, industry classification | Long (10 y+ is typical of their product; **not published**) | India | **Not published.** Subscription, quote on request ([cmots.com](https://www.cmots.com/)). | API / FTP (CSV, XML, JSON) | B2B redistribution licences are their core business. Needs a contract. |
| **Accord Fintech (ACE Datafeed)** | Same class as CMOTS. Authorised vendor of BSE/NSE/MCX data. | Long; not published | India | Feed **not published** ([accordfintech.com](https://www.accordfintech.com/market-data-feed)). ACE Equity Nxt terminal: **from ₹1,25,000 / USD 3,500 a year** + taxes, single-browser licence ([source](https://www.aceequitynxt.com/subscribe-now)). | FTP / API | Terminal licence ≠ redistribution. The feed needs its own contract. |
| **ACE Equity** | Same database as above, as a terminal | 20 y+ | India | As above | Desktop/web | Not for redistribution |
| **Capitaline** | 1,500+ data points per company. P&L, BS, cash flow, segments, NIC industry. 10 y+. | 10 y+ | India | **Not published** ([capitaline.com](https://www.capitaline.com/)) | Terminal / feed | Contract |
| **EODHD** | Fundamentals (IS, BS, CF), earnings, EOD prices, `.NSE` tickers | Non-US "from 2000", **but minor companies only the last 6 years and 20 quarters** | India + US | Fundamentals Data Feed **$59.99/mo** ($599.90/yr). All-in-One $99.99/mo. Free: 20 calls/day. ([pricing](https://eodhd.com/pricing)) | REST API | **Every retail plan is "personal use only".** Public display needs a separate commercial plan (contact sales). |

### C.3 India: unofficial (not to be built on without your sign-off)

| Source | Notes | Risk |
|---|---|---|
| **yfinance** | Already in use. 4 annual statements, thin for small caps. | Unofficial scrape of Yahoo, whose terms restrict it to personal use. It breaks without warning. **Already a dependency. This audit does not recommend extending it.** |
| **Screener.in** | 10 y of standardised annual statements. The deepest free source in practice. | ⚠️ **ToS risk.** Its terms allow only "personal, non-commercial transitory viewing" and forbid "any public display (commercial or non-commercial)" and mirroring ([terms](https://www.screener.in/guides/terms/)). Scraping it for a public site is a clear breach. **Not recommended.** |
| **Tickertape** | Fundamentals and ratios | ⚠️ **ToS risk.** Its terms prohibit "reproduction of any information… data… in any form" without written permission ([terms](https://www.tickertape.in/meta/terms)). **Not recommended.** |

### C.4 US

| Source | Fields | History | Cost | Access | Licensing |
|---|---|---|---|---|---|
| **SEC EDGAR XBRL `companyfacts`** (+ `submissions` for SIC industry, + nightly `companyfacts.zip`) | Every us-gaap/dei fact a filer has tagged: revenue, operating income, D&A, assets, current liabilities, equity, debt, CFO, capex, EPS, shares outstanding | 10-K/10-Q XBRL from FY2009–2011 onward, so **10 y+ for nearly all current filers** | **Free**, no key | JSON API, or a bulk zip rebuilt nightly around 03:00 ET. **10 requests a second max.** A descriptive `User-Agent` with contact email is **required** ([SEC](https://www.sec.gov/search-filings/edgar-application-programming-interfaces), [fair access](https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data)). | US government public data. Free to redistribute. |
| **Financial Modeling Prep** | Standardised IS/BS/CF, ratios, key metrics | Starter 5 y. Premium/Ultimate 30 y. | Starter **~$29/mo**, Premium **~$69/mo** (US/UK/CA), Ultimate **~$139/mo** (global). **FMP's own pricing page returned HTTP 403 to our check**, so these are third-party figures: verify before purchase. | REST | **Individual plans do not allow display or distribution to end users.** Public display needs FMP's Data Display and Licensing Agreement ([FAQ](https://site.financialmodelingprep.com/faqs)). |
| **EODHD** | As in C.2 | US major companies from 1985 | $59.99/mo | REST | Personal use only on retail plans |

### C.5 Already reachable via our Dhan subscription

Nothing for fundamentals. The DhanHQ v2 docs and release notes (v2 → v2.5)
list trading, quotes, historical candles, option chain and live feed. There is
no fundamentals, financial-statement or shareholding endpoint
([releases](https://dhanhq.co/docs/v2/releases/)).

What Dhan does give the lenses:
- **price** for PEG and market cap, via `daily_ohlcv` and quotes
- **the instrument master**, which carries ISINs and can be the join key to
  BSE XBRL

---

## D. Recommendation

### D.1 Cheapest reliable stack: ₹0 a month in data fees

| Layer | India | US |
|---|---|---|
| Statements | NSE XBRL, already built. **Add:** balance-sheet and cash-flow tags from the Q2/Q4 documents. **Add:** the BSE XBRL archive for depth and BSE-only scrips. | SEC `companyfacts.zip`, nightly |
| Ownership | SHP XBRL, already built. **Add:** pledge columns, and persist category totals. | n/a (the ownership rules score `n/a`) |
| Classification | NSE four-level industry from the quote API, refreshed weekly | SIC from EDGAR `submissions` |
| Size bands | AMFI semi-annual list | Market-cap terciles of the US universe |
| Universe | NSE `EQUITY_L` + BSE scrip master (ISIN-joined) | **A defined list is needed.** Proposed: S&P 500 + S&P 400 members, from the S&P-published constituent files, or EDGAR filers with a current 10-K and a NYSE/Nasdaq listing. |
| Price | Dhan → Yahoo fallback (unchanged) | Yahoo (unchanged) |

This unlocks **7 of 10 lenses for India** (all but Moat, Coffee Can and Capital
Cycle), and **9 of 10 for US** (all but Capital Cycle). The US figure counts
Akre and Owner as live even though their ownership rules score `n/a` there.

A paid feed (CMOTS or Accord, under a redistribution contract) is the fallback
if either of these happens:
- the legal opinion on automated exchange fetching comes back negative, or
- the BSE archive probe shows less than 10 years for most of the universe.

Get quotes from both in parallel so the choice is ready if needed.

### D.2 XBRL parsing: build, not buy

**Build.** Three reasons:
- Most of it exists and is tested. `xbrl.py` already handles contexts,
  dimensions, both filing regimes, basis selection and revised filings, and
  `test_xbrl.py` and `test_fundamentals.py` cover it.
- What is left is mapping about 25 more Ind-AS tags (balance sheet and cash
  flow), plus a BSE transport.
- Buying brings a redistribution contract and a second source of truth that
  will disagree with the filings we already display.

Revisit the call only if the legal opinion forbids automated exchange access.

Phase 2 work that follows from this:
- A `fundamentals_annual` table (wide: one row per symbol, fiscal year and
  basis) and a `fundamentals_ttm` table in `altaha_pit.db`, via a
  numbered migration file.
- The table is filled by a nightly slice crawler, the same pattern as
  `holdings_crawl.py`, driven by a GitHub workflow.
- Storage: about 3,000 companies × 10 years × ~40 numeric columns is about
  30k rows, well under 50 MB. That fits the 1 GB disk.

### D.3 Backfill plan to 10 years

1. **Weeks 1–2:** probe 50 companies across market-cap bands on both NSE and
   BSE. Record the earliest XBRL year per company and whether Q2/Q4 carry the
   BS and CF. Publish the result as `docs/lenses-coverage-probe.md`.
2. **Weeks 2–6:** run the slice crawler at about 40 companies a run, several
   runs a night. Each company is ~35–45 documents; the parse cache means each
   is fetched once. About 3,000 companies × 40 docs = 120k documents. At a
   polite 1 request/second that is about 33 hours of crawl, spread over 3–4
   weeks of nightly windows.
3. **Pre-XBRL years:** SEBI XBRL for results started around FY2012. A 10-year
   window ending FY2026 starts at FY2017, so XBRL depth is enough *in
   principle* for the 10-year lenses. The practical limit is what each
   exchange's index serves. If the probe shows BSE serving FY2017+ for most
   companies, Moat and Coffee Can come off "blocked". If not, they stay
   "Coming soon" and a paid feed quote decides it.
4. **Per company, the engine checks history itself:** a 10-year rule on a
   company with 7 fiscal years scores `n/a`. It never scores a "pass on what
   we have". Coverage rules then mark the stock "insufficient data".
5. **US:** one download of `companyfacts.zip`, then nightly.

### D.4 Refresh cadence

| Field group | Source | Cadence | Why |
|---|---|---|---|
| Quarterly P&L, EPS, share capital | NSE/BSE results XBRL | Nightly **index** check. Parse only new or revised filings. | Results arrive within 45 days of quarter end (60 for Q4), and revisions happen. |
| Balance sheet, cash flow | Q2/Q4 XBRL | Same crawl, half-yearly in practice | Filed only with Q2 and Q4 |
| Shareholding categories, pledge | SHP XBRL | Nightly index check. New filings within 21 days of quarter end. | Quarterly filing |
| Pledge events | SAST Reg 31 | Daily | Event-driven, 7 working days |
| Industry classification | NSE quote API | Weekly | Changes rarely. NSE Indices publishes change notices. |
| Size bands | AMFI list | Semi-annually (January and July) | That is when it is published |
| Price, market cap, PEG | Dhan / Yahoo | Nightly, with the lens compute | PEG and size move with price |
| US statements | `companyfacts.zip` | Nightly | 10-K/10-Q flow |
| Lens results | `lens_engine.py` | Nightly, after the crawls | As specified |

### Decisions I need before Phase 2

1. **Approve the ₹0 stack** (own XBRL + SEC). The alternative is starting paid
   quotes (CMOTS/Accord) now.
2. **Legal comfort** with automated fetching of exchange filing documents for a
   public site, given NSE's non-commercial portal terms. I recommend a short
   written opinion. This is the biggest non-technical risk.
3. **Lenses that are live in one market and blocked in the other** (Moat and
   Coffee Can: US yes, India not yet). Options: "Coming soon" everywhere
   (recommended), or show US results only.
4. **The US universe definition**, for example S&P 1500 or all EDGAR filers
   with a current 10-K.
5. **Scope of Phase 2.** I propose Phase 2 ships:
   - the engine, config, endpoints, UI, nightly job and migration;
   - the data work that unlocks Cannibal, Tenbagger, QGLP and Owner;
   - Gorilla, Nomad, Akre, Moat, Coffee Can and Capital Cycle in the
     "Coming soon" state.

   Each "Coming soon" lens is flipped live by a config edit once its data
   lands. The BS/CF parse, BSE backfill and industry classification would be a
   follow-up PR, or the same PR if you prefer one larger change.

---

*Lenses are rules-based filters applied to historical financial data. They are
not investment advice or recommendations.*
