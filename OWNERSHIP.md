# Ownership — who holds the company, from the company's own filing

`backend/shareholding_filings.py` · `/shareholding` · the Ownership pane on
`stock.html`

## What it is

Every listed Indian company files its shareholding pattern with the exchanges
each quarter under LODR Regulation 31. The filing is XBRL: machine readable,
free, and authoritative, because it is the company's own submission rather than
a scrape of someone's summary page. This reads that document and shows:

* the split between promoters, foreign institutions, domestic institutions and
  the rest of the public, with the quarter-on-quarter and year-on-year change
  in percentage points;
* how many shareholders sit behind each line, and the total on the register;
* every promoter entity and every public holder above 1%, by name, with how
  their stake moved;
* up to twelve quarters of history, each row linking the filing it came from.

## The one thing you must not do to this data

**In the exchange's format, `Public` is the parent of the foreign, domestic and
non-institutional lines — not their sibling.** For Reliance's June 2026 filing:

```
promoter 50.48 + public 49.52                                  = 100.00
public 49.52 = FII 17.20 + DII 21.19 + non-inst 11.04 + govt 0.10
```

A chart that draws promoter, FII, DII and public as four slices of one pie
double-counts about forty per cent of the company. The API is shaped so this is
hard to do by accident:

* `split` is the non-overlapping decomposition. It sums to 100 and it is what
  the UI draws.
* `public_total_pct` sits outside `split`, and the response always carries a
  note saying what it contains.
* `totals.reconciles` is false when the parts miss 100 by more than 0.15, which
  means a category this parser does not break out yet.

`test_public_total_is_the_parent_of_fii_dii_and_non_institutional` and the
browser test both guard this. Do not weaken either.

## Two format traps

**Scale.** The 2025-10-31 taxonomy files a percentage as a fraction (`0.5048`);
the 2020-09-30 one files a percent (`50.61`). Reading one as the other is a
hundredfold error on every figure and nothing raises. The scale is detected per
document from the grand total, never assumed.

**The missing split.** The older format has a single `Institutions` line — the
domestic/foreign split this feature is about did not exist in it. Where it is
absent, DII is derived as institutions minus foreign institutions (arithmetic
the document itself confirms: the remainder equals the sum of the domestic
lines it does report) and is flagged `derived: true`. The UI shows a `derived`
badge. A derived figure that is not labelled as one is a number this product
has no right to display.

## Other things the format will catch you on

* **Namespaces change, local names do not.** Five years of filings span
  multiple taxonomy URIs. Everything matches on local name.
* **A named holder is split across two contexts.** One carries the name and
  PAN, its partner the numbers. Two pairing conventions are in the wild:
  `D_Foo_Context12` ↔ `Foo_Context12`, and `Foo001D` ↔ `Foo001I`.
* **A company with no promoter omits the line; it does not file a zero.** ITC
  and HDFC Bank are the obvious cases. Read as a gap that is indistinguishable
  from a parse failure — which it is not — so it is inferred from the filing's
  own totals and stated in prose.
* **A holder absent from the previous quarter is not necessarily new.** The
  public table only names holders above 1%, so crossing that line looks
  identical to buying in. The UI says "new in table", not "new holder".
* **Revised filings.** A refiled quarter leaves two rows on the exchange. The
  latest wins, and the row is marked `revised`.

## Cost and caching

A filing is ~500KB of XML; a company has five years of them. The **parse** is
cached to disk (`$DATA_DIR/shp-cache`, ~2KB per filing), not the source — a
filed document never changes, so that cache never expires. Only the index of
filings is refetched, on a six-hour TTL. Nothing is fetched until a reader
opens the Ownership pane.

## Transport

NSE's WAF fingerprints the TLS handshake, so a plain `requests` call from a
datacenter IP gets a 403 no combination of headers survives. `curl_cffi`
impersonates a real Chrome handshake and is already a dependency (yfinance
pulls it for the same reason). Without it the module reports itself
unavailable rather than pretending to have data.

## Coverage limits

* NSE-listed symbols only. A BSE-only scrip has no index entry here.
* History goes back as far as NSE serves, which is about five years.
* The domestic/foreign split is filed only in the newer format; older quarters
  carry a derived DII, flagged as such.
* Nothing here is adjusted for pledged shares, which are a separate filing.
