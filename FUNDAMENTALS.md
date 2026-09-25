# Fundamentals — the quarterly P&L, on one accounting basis

`backend/fundamentals.py` · `/fundamentals` · the Fundamentals pane on
`stock.html`

## What it is

Every listed Indian company files its quarterly results with the exchanges
under LODR Regulation 33. The filing is XBRL: machine readable, free, and
authoritative, because it is the company's own submission rather than a scrape
of someone's summary page. This reads that document and shows:

* sixteen P&L lines — revenue through to earnings per share — for the last six
  quarters, in ₹ crore;
* six ratios computed from those lines, the same way in every quarter, each
  printed with its arithmetic;
* two change columns: against the same quarter a year earlier, and against the
  quarter just gone;
* the filing each quarter came from, one click away.

Nothing here is estimated. Every figure is the company's own.

## The one thing you must not do to this data

**Almost every Indian company files its results twice — once standalone and
once consolidated — and the two are not comparable.** Reliance's filing index
carries 65 results documents: 33 standalone, 32 consolidated, paired by
quarter. For the December 2025 quarter:

```
standalone    revenue  ₹1,26,000 cr
consolidated  revenue  ₹2,69,496 cr
```

`xbrl.statements()` does not filter by basis unless asked, and it keys its rows
by period end — so where both exist, one silently overwrites the other. A
series built that way alternates bases and reports a 114% swing that is nothing
but the difference between a parent company and a group. It does not crash, it
does not log, and it looks entirely normal on screen. That is the whole reason
this module exists.

So:

* `_pick_basis()` chooses **one** basis for the whole series and returns the
  reason for it. Consolidated where the company files it, because that is the
  group a shareholder owns; standalone where that is all there is.
* The choice is made from the **filing index**, which is one cheap call, before
  any document is fetched. Pulling both bases and discarding half doubles the
  documents fetched over the wire — and NSE throttles bursts, so the wasted
  half is what makes the wanted half fail.
* `statements()` falls back to the other basis when a company files only one,
  so the module checks what actually came back rather than trusting what it
  asked for.
* `basis` and `basis_reason` are in the payload and printed on screen, and
  `basis_alternatives` names the other basis where the company files it. That
  list is read from the **index**, not from the rows in use — read from the
  filtered set it would always claim the other basis does not exist.
* `?basis=standalone` serves the other one on request.

## The other thing you must not do: a percentage across zero

A company that lost ₹100 crore and then made ₹50 crore has not grown 150%. A
percentage change only means something when the base is positive, and printing
one anyway is how a screener reports a turnaround as a decline, or a collapse
as growth.

`change(now, before)` returns `{pct, abs, kind}` and sets `pct` to `None`
whenever the base is not positive. `kind` says what happened, so the page never
has to infer a turnaround from a sign:

| `kind` | when | `pct` |
| --- | --- | --- |
| `grew` / `shrank` | positive base, positive now | a real percentage |
| `loss_to_profit` | crossed zero upwards | `None` |
| `profit_to_loss` | crossed zero downwards | `None` |
| `loss_narrowed` | both negative, improving | `None` |
| `loss_widened` | both negative, worsening | `None` |
| `flat` / `unavailable` | no move, or a missing figure | `None` |

Where `pct` is `None` the pane prints words instead, in rupees terms. It uses
two vocabularies: the profit lines get profit words ("to profit"), everything
else gets sign words ("to positive") — because a tax credit becoming a tax
charge is not a company turning profitable.

Ratios follow the same rule. `_div()` returns `None` on a denominator at or
below zero: an effective tax rate against a loss before tax is not a rate, and
a blank cell is more useful than a number a reader would act on.

## Year-on-year is the headline, not quarter-on-quarter

Most Indian businesses are seasonal, so the previous quarter compares a festive
season with a monsoon. The same quarter twelve months earlier is the comparison
that means something, and it is the first change column. The sequential one is
there too, labelled with the quarter it compares against, because it is what
tells you about a turn.

The year-ago quarter is found by date window — 350 to 380 days back — not by
counting rows. A company whose history has a gap would otherwise be compared
against whatever row happened to sit five places down.

## What gets filtered out

* **Cumulative periods.** A Reg 33 filing carries several periods and the index
  does not always say which one a row is. `_is_quarterly()` keeps rows spanning
  60–130 days; a nine-month or full-year figure in a quarterly series overstates
  every line in it.
* **Superseded filings.** A revised filing for a quarter arrives later, so rows
  are sorted by period end then by filing date and the latest one for a period
  wins. One row per quarter, always.

## When it comes back short

Each quarter is a separate document on the exchange, fetched as it is needed,
and NSE throttles bursts. A first view of a company nobody has looked at can
legitimately return four quarters instead of six. The payload says so —
`partial`, `count`, `requested`, and a note on the page — because presenting
four quarters as though that were the whole history is the kind of quiet lie
this project keeps trying not to tell. Filings already read are kept, so the
history fills in rather than being re-fetched.

## Served from the disk first

The market-wide crawl (below) already holds every company's filings in
`altaha_fundamentals.db`, so `/fundamentals` reads that before it goes near
the exchange: `fundamentals.series_from_store()` builds the identical payload
from `income_statement` — same ratios, same `change()`, same year-ago lookup,
through the same `_assemble()` the live reader uses — in milliseconds instead
of an index call plus one document per quarter. `served_from` says which
(`store` or `exchange`).

The exchange is still read when the store cannot answer honestly:

* the crawl has not reached the company yet;
* `?basis=` asks for the basis the crawl does not keep (it keeps one);
* the newest stored quarter ended more than `STORE_FRESH_DAYS` (154) ago, so a
  newer filing has probably been made since the last crawl.

If that live read then fails, an older stored series is served anyway with
`stale: true` and a note naming its newest quarter, rather than an empty pane.
From the store `basis_alternatives` lists only what is held, so the pane does
not claim the company also files the other basis.

## Everything else that reads the tables

The same principle — the crawl has already read it, so do not read it again —
now covers every other consumer of a company's statements. Each one falls back
to the live source when the store cannot answer honestly, and says which
answered where the caller can see it.

| What | Reads | Falls back to live when |
|---|---|---|
| **Fundamental score** (Piotroski checks, stock page, portfolio rows, scan Phase 2) — `data_source.stored_statements()` | `yf_statements`, rebuilt into the exact frames yfinance returns | not an `.NS` listing (a bare ticker is a US one — AGI is Alamos Gold, not AGI Greenpac), any of the three statements missing, or the newest annual period older than 515 days. `info` (valuation, ownership) is still read live. |
| **Factor history** for the scan and `/factors` — `xbrl.scoring_statements()` → `fundamentals_store.scoring_quarters()` | `income_statement` quarters in `xbrl.statements()`'s shape; return on assets annualised against the balance sheet at or before the quarter, as `normalise()` derives it | a historical `as_of` read (the table keeps only the latest revision, and a backtest needs the one known at the time), the company not crawled, or the newest quarter older than 154 days. Filing times are written back in NSE's own format so the point-in-time store keys a stored row and the same filing read live as one version. |
| **Balance sheet and cash flow** on the stock page — `GET /fundamentals/position` | `balance_sheet` (March and September), `cash_flow` (full years only — a half-year beside a year reads as a collapse) | nothing to fall back to; the pane says the company has not been read yet. Lines a company never filed are not drawn, so a bank shows deposits and a manufacturer inventories. Cash conversion and FCF margin only over a positive base. |
| **Against its industry** — `GET /fundamentals/peers` | each peer's newest quarter, balance sheet and year, one query per table; NSE industry from `lens_company` | a measure is shown only when at least 5 peers with results in the last 154 days have a value for it; how many of the industry were read is printed. |
| **Quarterly screens** under the lens cards — `GET /fundamentals/screens`, `/fundamentals/screens/{id}` | the whole store, cached for an hour and until the tables change | a company whose newest quarter is more than 154 days old is left out, not failed. Every match carries the figures that met the condition. |

The five screens (`fundamentals_screens.py`): four quarters in a row of revenue
up more than 20% YoY; back to profit against a loss a year earlier; operating
margin up 3+ points YoY with revenue higher; cash and current investments above
borrowings with a profitable latest year; free cash flow positive three full
years running with operating cash flow above profit in the latest. The lenses
do the same for investing philosophies over full years; these answer what
changed in the latest quarters.

Tests: `backend/tests/test_fundamentals_uses.py` for each reader;
`frontend/tests/stock-fundamentals-browser.cjs` and
`frontend/tests/lenses-browser.cjs` for the pages, against fixtures that
`make_fundamentals_fixture.py` produces from the real modules over a temporary
store.

## Reaching NSE at all

`backend/nse_http.py` is the shared transport. Plain `requests` gets a 403 from
a datacenter IP — NSE fingerprints the TLS handshake — so every call goes
through `curl_cffi` with `impersonate="chrome"`, against a warmed session that
carries the cookies the site sets on its home page. Where that library is
missing, `available()` is false and the endpoint says so rather than returning
an empty table.

This was not hypothetical. `xbrl.py` had its own plain-`requests` transport and
had been returning nothing in production for as long as it had been deployed:
no error, no log line, just an empty index. Switching it to `nse_http` took the
filing index for Reliance from 0 rows to 65.

## API

```
GET /fundamentals?ticker=RELIANCE&quarters=6[&basis=standalone]
```

```jsonc
{
  "available": true,
  "basis": "consolidated",
  "basis_reason": "the company files consolidated results",
  "basis_alternatives": ["consolidated", "standalone"],
  "count": 6, "requested": 6, "partial": false,
  "unit": "crore", "unit_divisor": 10000000,
  "lines":      [{ "key": "revenue", "label": "Revenue from operations", "unit": "money" }],
  "ratio_defs": [{ "key": "opm_pct", "label": "Operating margin", "formula": "EBITDA ÷ revenue" }],
  "rows": [{
    "period_end": "2026-06-30", "label": "Q1 FY27",
    "filed_at": "...", "audited": "Unaudited", "source": "https://nsearchives...",
    "values":  { "revenue": 3118500000000, "pat": 231960000000 },
    "ratios":  { "opm_pct": 15.24 },
    "yoy": { "revenue": { "pct": 10.51, "abs": 2.96e11, "kind": "grew" } },
    "qoq": { "revenue": { "pct": 4.43,  "abs": 1.32e11, "kind": "grew" } },
    "yoy_against": "Q1 FY26", "qoq_against": "Q4 FY26"
  }],
  "notes": ["..."]
}
```

Values are in rupees; divide by `unit_divisor` for crore. The page does.

## Tests

* `backend/tests/test_fundamentals.py` — `change()` across every sign
  combination, ratio denominators, fiscal-quarter labelling, cumulative-period
  and revised-filing filtering, and basis selection end to end against a
  stubbed reader. The basis test builds a company filing both bases at
  realistic ratios and asserts the series has exactly one revenue level.
* `frontend/tests/stock-fundamentals-browser.cjs` — the pane in a real
  Chromium: the basis named on screen and the figures matching it, a turnaround
  rendered in words with no percentage anywhere near it, both change columns
  naming their baseline, every line and ratio drawn, and the table readable at
  320px with its line-item column pinned while the quarters scroll.
* `backend/tests/make_fundamentals_fixture.py` regenerates the browser
  fixture **from the real module**, so a key renamed in `fundamentals.py`
  cannot keep passing against a stale JSON literal.

## The whole market, as three tables

`backend/fundamentals_store.py` · `backend/fundamentals_crawl.py` ·
`.github/workflows/fundamentals.yml`

Every Reg 33 filing carries the quarter's P&L, and the March and September
ones also carry the balance sheet at that date and the cash flow for the year
to date. A crawl running around the clock — gentler during market hours — reads every NSE company's filings into
`altaha_fundamentals.db` on the data disk:

| Table | One row per | History | Columns |
|---|---|---|---|
| `income_statement` | company × quarter, and company × financial year (`freq`) | from Sep 2018: ~32 quarters, 8 years | P&L lines in ₹ crore (`*_cr`), EPS, six ratios, YoY for revenue, EBITDA, PAT |
| `balance_sheet` | company × March / September | from Sep 2022: 4 years, growing | assets, equity, borrowings, deposits and loans for banks, debt/equity, current ratio |
| `cash_flow` | company × half-year and year (`months` 6 or 12) | from FY21: 6 years | operating, investing, financing, capex, free cash flow, dividends, buybacks |

One accounting basis per company (consolidated where filed), named on every
row. A revised filing replaces the row for its period; an older one never
does. `docs` records every document read, so a re-crawl fetches only new ones.

What NSE's own filings get wrong, and the parser now handles: 2018–2020
filings that reference `OneD`/`FourD` without defining them; a `FourD` defined
as the quarter while its facts say the year (TCS, FY24); filings that state
only period ends (HDFC Bank, to FY21); and cash flows tagged against the
quarter although only a year-to-date one is ever filed (to FY21). Each has a
real fixture in `tests/test_xbrl_statements.py`.

* `GET /fundamentals/table?table=income&symbol=TCS&freq=annual&format=csv`
* `GET /fundamentals/table?table=balance&symbol=TCS`
* `GET /fundamentals/table?table=cashflow&period_end=2026-03-31&format=csv` — one period, every company
* `GET /fundamentals/coverage` — how much of the market each table holds
* `POST /admin/fundamentals/crawl` — the next slice (admin key); `&source=yfinance` for Yahoo

### Yahoo Finance, as a second opinion

The same crawl with `source=yfinance` stores Yahoo's income statement,
balance sheet and cash flow in `yf_statements` (long format; the view
`yf_statements_v` joins item names back). Yahoo reaches no further back than
the filings — four annual balance sheets — and is never mixed into the three
tables above.

* `GET /fundamentals/statements?symbol=TCS&statement=balance&freq=annual&format=csv`
