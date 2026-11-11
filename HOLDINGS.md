# Holdings — what investors and fund houses own

`backend/holdings_store.py` · `backend/investors.py` · `backend/holdings_crawl.py` ·
`backend/fund_portfolios.py` · `backend/fund_workbook.py` ·
`/investors` `/investor` `/funds` `/fund` `/holders` · two tabs on the homepage

## Two features, two sources, opposite limitations

Both answer "what does this person or institution own", and they are built on
data with almost inverted properties. A reader who carries an assumption from
one page to the other will be wrong, so each page states its own limits in its
own words rather than sharing a vague disclaimer.

| | Investor portfolios | Fund house portfolios |
| --- | --- | --- |
| Source | Company shareholding filings (LODR Reg 31) | The AMC's own monthly portfolio disclosure |
| Cadence | Quarterly, filed up to 21 days late | Monthly, due by the 10th |
| Completeness | **Only stakes above 1%** of a company | The **whole book**, every position |
| Joined by | A curated name table | **ISIN** — an exact identifier |
| Main risk | Attributing a stake to the wrong person | Looking more complete than it is |

## Investor portfolios

### The problem

A shareholding filing answers "who holds this company". Nothing anywhere
answers "what does this person hold" — that answer is spread across two
thousand separate documents, one per listed company. So it has to be
**collected**, not looked up.

`holdings_store.py` is an append-only SQLite ledger. `holdings_crawl.py` fills
it in bounded slices — a full sweep is two thousand documents from an exchange
that throttles bursts, on a 512 MB instance, so it takes many runs and the
coverage table is what makes each run continue the last rather than restart it.

### The row that must not collapse

Titan's March 2026 filing names **Rekha Jhunjhunwala twice** — 4.24% in one
folio and 1.07% in another:

```
Rekha Jhunjhunwala                    4.24%
Life Insurance Corporation Of India   2.34%
Rekha Jhunjhunwala                    1.07%
```

Keyed on `(symbol, period_end, holder)` the second row overwrites the first and
the position reads **1.07% instead of 5.31%** — a fifth of its real size, with
nothing on screen suggesting anything was lost. Hence `slot` in the primary
key, and hence the page sums per holder rather than deduplicating.

### Names are matched by hand, and the table is checkable

Three real rows from three real filings:

```
ATULAUTO     VIJAY KEDIA                          18.20%
ATULAUTO     KEDIA SECURITIES PRIVATE LIMITED      2.71%
ELECON       Vijay Kishanlal Kedia                 1.00%
METROBRAND   ARYAMAN JHUNJHUNWALA DISCRETIONARY TRUST
             (TRUSTEE - REKHA RAKESH JHUNJHUNWALA)  4.79%
```

No similarity score gets all of those right, and the cost of getting one wrong
is not a bad recommendation — it is **publishing a false statement about what a
named private individual owns**. So:

* `investors.py` holds a hand-written table. There is **no fuzzy matching
  anywhere** in this feature.
* `holder_key()` folds only what is never a different person: case, spacing,
  punctuation, corporate suffixes (`KEDIA SECURITIES PRIVATE LIMITED` →
  `kedia securities`), honorifics. It deliberately does **not** fold middle
  names — `Vijay Kedia` and `Vijay Kishanlal Kedia` are one man, but
  `Ashish Kumar Jain` and `Ashish Jain` routinely are not.
* `holder_base()` additionally drops a bracketed annotation, because the
  trustee wording inside a trust's name varies between companies. It is used
  only as a fallback for a curated alias, never to group rows on its own.
* **`verify()` checks every alias against the ledger** and reports the ones
  that have never matched anything. That is what makes the table evidence
  rather than assertion — it caught two real errors while this was written.
* `unknown_big_holders()` lists large holders no tracked investor claims, which
  is how the table grows from what companies actually filed rather than from
  guessed spellings.

Both of those have already earned their place. `verify()` found that the
trustee wording inside a trust's name varies between companies, and that the
table carried **"Ashish Dhawan Kacholia"** — a name that exists nowhere, made
by running two real and unrelated investors together. It matched nothing, so it
was harmless; the same mistake with a name that *does* appear in a filing would
credit one man with the other's holdings. A test now asserts structurally that
no alias contains another tracked investor's full name.

Two entries were removed for the same reason in advance of any error: an
invented middle name, and names common enough that an exact match is as likely
to be somebody else as the right person. A tracked name that might attribute a
stranger's stake is worse than no entry at all.

An asset manager's own name is never an alias either — "Abakkus Mutual Fund" is
the AMC, and its schemes belong to the fund-house side. Folding them into one
man's personal holdings would credit him with every rupee the house manages.
That is also asserted by a test.

### Rolled up, but never silently

`relation` records what each association is, and the total is always shown
above the rows it came from:

| relation | meaning | counted? |
| --- | --- | --- |
| `self` | the investor's own name, as filed | yes |
| `family` | an immediate family member | yes |
| `entity` | a company or LLP they invest through | yes |
| `trust` | a trust they are **trustee** of | yes, and labelled |
| `joint` | filed in two people's names together | **no** — shown beside |

A discretionary trust someone is trustee of is not shares they own outright.
It is counted because that is what readers mean by the portfolio, marked as a
trust everywhere it appears, and called out in the notes. Reasonable people put
that line in different places; what is not reasonable is moving it without
telling the reader.

A holding filed in two names does not say how it divides, so crediting all of
it to one of them is a claim the document never makes. It is listed beside the
total, not inside it.

A **promoter stake** is flagged. Radhakishan Damani's 23% of Avenue Supermarts
is the largest line in his register and it is his own company, not a stock pick.

### An empty portfolio is a fact about the ledger

Every directory card carries how many companies that name is currently known to
hold, and names with holdings sort first — so an empty page is never something
a reader discovers by clicking. When a portfolio is empty the page says how
much of the exchange has been read and that the sweep continues, because
without that a reader concludes the investor holds nothing, which is the one
thing it must not be read as.

### Only quarter ends go in

Regulation 31 also requires a filing within ten days of a capital change, and
those carry their own date. One company filed under **1 July 2026**, and the
crawler let it through because it checks the INDEX's date while the ledger
stores the date inside the DOCUMENT — and the two can disagree.

That single row did real damage. It became `MAX(period_end)`, so every caller
asking for the current quarter got a period containing one company: the
investor directory counts each name's holdings in the current quarter, and
showed **all twenty-seven as holding nothing** while their portfolio pages were
full. Exactly the symptom the directory counts were added to prevent.

Both the crawler and `record_filing()` now reject a period that is not 31
March, 30 June, 30 September or 31 December, `latest_period()` returns the
newest *quarter* rather than the newest date, and `purge_non_quarter_rows()`
repairs a ledger that already has them — a deliberate and narrow exception to
the append-only rule, which exists so a re-crawl cannot rewrite what a company
said, not to oblige the ledger to keep rows a defect put there. The nightly
workflow calls it before crawling; it is a no-op once clean.

### What it refuses to claim

* **The 1% floor.** A company names a public shareholder only above 1% of its
  equity. A ₹500 crore position in a large cap sits below that and is invisible.
  Every portfolio is a *floor*, and says so in its own header.
* **The lag.** Filings are quarterly and land up to 21 days after quarter end,
  so a position can be four months old.
* **A company dropping off is not a sale.** Below 1% the filing simply stops
  naming a holder. It is labelled "no longer disclosed", and the notes say the
  filing does not say which happened.
* **Rakesh Jhunjhunwala died in August 2022.** His id redirects to Rekha
  Jhunjhunwala and the page says why. There is no 2026 portfolio to show under
  his name.

## Fund house portfolios

### There is no feed

SEBI requires every asset manager to publish each scheme's full portfolio
monthly. AMFI lists who must do it and **aggregates nothing**: its
portfolio-disclosure page is a directory — 57 entries in November 2026, 55
with a link — and every link points at a different website.

Measured on 11 November 2026, end to end — not "can a link be found" but "did
October's portfolio actually land in the ledger". The eight largest houses:

```
SBI                read   POST the page makes -> "All Schemes" xlsx   4,413 positions
ICICI Prudential   read   fixed monthly zip of 151 workbooks          6,529
HDFC               read   site answers 403; files fetched by name     3,933
Nippon India       read   plain HTML links                            3,985
UTI                read   public JSON API -> zip, one sheet per house 4,332
Aditya Birla SL    read   accordion API -> zip with a legacy .xls     5,231
Kotak              not    bot challenge (ShieldSquare / hCaptcha)
Axis               not    CMS API needs a site-issued session token
```

The whole directory, swept live the same day with the finished code (from a
cloud address — the deployed instance's may be refused by different CDNs):

```
20 read          the six above; DSP 3,436 · Groww 3,175 · Baroda BNP 1,712 ·
                 Angel One 1,703 · HSBC 1,492 (August: the newest complete
                 month its page links) · Samco 514 · Helios 425 · Shriram 425 ·
                 NJ 375 · Quantum 367 · PPFAS 310 · Unifi 162 · Old Bridge 154 ·
                 Capitalmind 147                        ~42,700 positions
20 JavaScript    no workbook link in the HTML: 360 ONE, ASK, AlphaGrep,
                 Bandhan, Bank of India, Canara Robeco, Carnelian, Franklin
                 Templeton, Invesco, ITI, JM Financial, Jio BlackRock,
                 Mahindra Manulife, Mirae, Motilal Oswal, PGIM, Taurus,
                 The Wealth Company, Trust, WhiteOak
 5 blocked       Edelweiss, Navi (403) · Kotak (bot challenge) · Union
                 (connection reset) · IL&FS (503)
 9 no portfolio  the page links workbooks, none of them a portfolio: Abakkus
                 (scheme summaries), Bajaj, Choice, LIC, Monarch, Sundaram,
                 Tata, Zerodha, quant
 1 token         Axis: a CMS API that wants a site-issued session token
 2 no page       Lakshya, Nuvama: AMFI lists no disclosure link
```

The JavaScript group is where a headless browser in the scheduled workflow
would pay off; the per-AMC sources above are what that costs per house when
it is done by hand instead — the endpoint each page calls, found once.

Coverage is therefore **published on the page**: the number of fund houses
read, out of those AMFI lists. A fund house that is absent is absent because
it has **not been read**, never because it holds nothing.

### One parser, not fifty-three

The regulation fixes the *content* — name of instrument, ISIN, industry,
quantity, market value, per cent to net assets — even though every AMC lays the
file out differently. `fund_workbook.py` parses the content:

* **The header is searched for**, not assumed: packs put a title, blank rows
  and a "Monthly Portfolio Statement as on …" line above it.
* **Columns are anchored on ISIN, found from the data.** Baroda BNP's header
  begins at "Name of the Instrument" but its data rows begin with an internal
  scrip code and *then* the name — the header is off by one against the rows it
  describes. Parsed by position, every name becomes a scrip code and every ISIN
  becomes a company name: a table that looks entirely reasonable and is wrong in
  every row.
* **The percentage scale is detected per sheet.** "% to Net Assets" is written
  `0.0333` by some AMCs and `3.33` by others for the same holding. A full
  portfolio's weights sum to about 1 or about 100, and those are far enough
  apart to tell apart safely. Taking either at face value is a hundredfold
  error in the column readers compare across funds.
* **An .xlsx served under an .xls name** is recognised by sniffing the
  container. Baroda BNP's pack is one. **A genuine legacy .xls** is read too,
  with xlrd — Aditya Birla Sun Life publishes one inside a zip, and before
  that one of the five largest houses was refused for its file format alone.
* **A zip of workbooks** is read member by member: ICICI Prudential's month is
  151 per-scheme workbooks; UTI's zip holds the portfolio beside futures,
  dividend and risk-o-meter files, which are skipped.
* **A whole house in one sheet** is cut at its `SCHEME:` lines. UTI publishes
  every scheme that way; read as one table, ninety schemes become one and a
  company held by forty of them is one position.
* **Scheme names** come from the index sheet, found by matching its codes to
  the workbook's sheet names rather than by its header wording (SBI says
  "Scheme Short code", Nippon India has no header at all), or from the sheet's
  own title line, with the regulatory "(An open ended …)" description removed.
* **The weight column** is "% to Net Assets", "% to NAV" or "% to AUM" (SBI,
  Aditya Birla) — the last went unrecognised, and every weight in those packs
  came out empty.
* Section headings and totals (`Equity & Equity related`, `TREPS`, `Grand
  Total`) are not holdings.

### ISIN is why this side is safe

Every row carries a registered identifier, so joining a holding to a listed
company is an exact lookup against NSE's own equity list — not a judgement
about spellings. **Nothing here is inferred.**

The map is cached on disk and refreshed fortnightly. When the exchange refuses,
the cached map is used and `stale` says so: a map from last month maps
essentially every holding correctly, whereas mapping nothing would push every
position into the unmatched pile.

A row whose ISIN is **not** in the equity list — another fund's units, an
unlisted holding, something quoted only on BSE — is kept, stored with a null
symbol, counted, and shown in its own block. Dropping it would make the weights
on screen quietly add up to less than the fund holds.

### Percentages are not added

A company held by twenty-two schemes has twenty-two weights, each a share of a
different portfolio. Adding them produces a number that means nothing. The
headline across a house is the **rupee value**; the scheme weights sit
underneath, unsummed.

## Running the collectors

There are two ways to fill it, and the second exists because the first has a
single point of failure that has now bitten twice.

**From the page itself.** The *Fill the ledger* panel at the foot of the
Investor portfolios tab starts a background sweep on the API and polls it. It
asks for the admin key, keeps it in memory for that tab only, and sends it as a
header. Start it, close the tab, come back — the work happens on the server, not
in the browser, because a sweep is over an hour and no proxy holds a request
open that long. Whoever can see an empty page can fill it, with no repository
secret involved at all.

**From the schedule.** `.github/workflows/holdings.yml` does the same thing
nightly, driving the same bounded endpoint. It needs `ALTAHA_ADMIN_KEY` set as
a repository secret, matching `ADMIN_KEY` on Render. When that secret is
missing the job fails in under a second; when it is set but WRONG the job gets
401 and says so in those words, because a wrong value looks identical to a
missing one in every other respect.

**This is not optional plumbing** — nothing else writes to the ledger, and
without one of the two both pages are correct, tested, and empty.

The crawl runs on the API rather than in the runner, because the ledger lives
on the disk mounted to the API; the workflow's only job is to keep asking for
the next slice. The admin key travels in the `X-Admin-Key` header, not the
query string: a query parameter ends up in access logs, proxy logs and error
reports, which is a poor place for the credential that can start a crawl.

### The universe has to be the real one

`scan.fetch_nse_list()` fetched the official equity list with plain `requests`,
which NSE answers with 403 from a datacenter IP — so in production it fell
through to the curated `FALLBACK` list of 204 large caps. Silently: its own
label said so, in a string nobody reads.

That is not a small difference for this feature. The real list is about 2,300
symbols, and the ~2,100 missing ones are the small and mid caps — which is
exactly where these investors hold. A crawler pointed at the fallback can never
find Atul Auto, Repro India or Carysil however long it runs, so every tracked
investor except the handful holding large caps would stay permanently empty.
The list now goes through `nse_http`, and is cached for an hour and shared, so
the two callers that want it do not fetch it twice and get the second one
throttled back onto the fallback.

Both collectors are driven by scheduled workflows rather than in-process timers
— Render's cron is a paid add-on and a timer dies with the worker.

```
POST /admin/holdings/crawl?limit=40&quarters=4   # next slice of companies
POST /admin/funds/ingest?limit=4                 # next few AMC packs that are due
POST /admin/funds/ingest?limit=4&force=true      # from the top, ignoring the cursor
POST /admin/funds/ingest?amc=22                  # one fund house, now
POST /admin/funds/ingest?amc=20&url=…            # one workbook or zip directly
GET  /admin/funds/directory                      # every AMC, last try and why
GET  /admin/holdings/unclaimed                   # holders to consider adding
GET  /investors/coverage                         # published, not admin
```

All of them take the key as `X-Admin-Key:` (preferred) or `?key=`.

**The fund ingest keeps a cursor** (`fund_tries`). Each call skips houses
already read for the month every AMC owes by now (October, from 11 November)
and houses tried within the last day, largest houses first — so one night's
slices walk the directory once and `attempted: 0` means it has caught up.
Before it did, every call took the first four AMCs of the directory: fourteen
nightly slices read 360 ONE, Abakkus, Aditya Birla and AlphaGrep fourteen
times and never reached the other fifty-one, which is why the live page said
"0 of 53". The nightly job now **fails** when the ledger holds no fund house,
and writes the per-AMC reasons into the run summary.

Each run is bounded. The shareholding crawl stops early after eight consecutive
unreadable companies — a crawler that keeps asking after the exchange starts
refusing collects nothing and earns a longer ban. The fund ingest is bounded
because each pack is a fifteen-megabyte download.

## Tests

* `backend/tests/test_holdings_store.py` — normalisation, the two-folio case,
  category headings, append-only behaviour, the crawl queue, and the column
  migration (`CREATE TABLE IF NOT EXISTS` does nothing to an existing table, so
  without it a live ledger keeps its old shape and every query naming a new
  column fails).
* `backend/tests/test_investors.py` — no alias claimed by two investors, no
  alias that is a category heading, roll-up with parts, trusts counted and
  labelled, joint holdings excluded from the total, added/trimmed/new, and the
  refusal to call a drop-off a sale.
* `backend/tests/test_holdings_crawl.py` — bounds, resumption, interim filings
  excluded, and that "no filings" never counts towards giving up.
* `backend/tests/test_fund_workbook.py` — the header offset, the scale trap,
  section headings, the .xlsx-named-.xls case, a real legacy .xls
  (`fixtures/funds_legacy_pack.xls`, written by `make_funds_fixture.py`), the
  one-sheet house, index sheets in every shape, and every date wording.
* `backend/tests/test_fund_portfolios.py` — month normalisation, the AMFI
  payload, ISIN map caching and staleness, that debt never becomes equity, the
  cursor (each house once per night, none twice), each per-AMC source against
  the shape its site serves, zips, per-scheme files recorded as one pack, and
  blocked pages reported as blocked.
* `frontend/tests/investors-browser.cjs` and `funds-browser.cjs` — the same
  guards on the rendered page, at 320–1280px in both themes.

Fixtures for both browser tests are generated **from the real modules**
(`backend/tests/make_investors_fixture.py`, `make_funds_fixture.py`), so a key
renamed in the backend cannot keep passing against a stale JSON literal.
