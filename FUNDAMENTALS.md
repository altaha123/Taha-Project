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
