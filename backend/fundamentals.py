"""
Altaha Screener — the P&L, quarter by quarter, on one basis

WHAT THIS IS
The income statement the company filed with the exchange under LODR
Regulation 33, for the last several quarters, with the ratios that follow from
it and a column saying how each line moved. Every figure is the company's own;
nothing here is estimated.

THE TRAP THIS MODULE EXISTS TO AVOID
Almost every Indian company files its quarterly results TWICE — once
standalone and once consolidated. Reliance's index carries 65 filings: 33
standalone, 32 consolidated, paired by quarter. The two are not comparable:
for the December 2025 quarter, standalone revenue is Rs 1.26 lakh crore and
consolidated is Rs 2.69 lakh crore.

`xbrl.statements()` does not filter by basis unless asked, and keys its rows by
period end, so when both exist one silently overwrites the other. A series
built that way alternates bases and reports a 114% swing that is nothing but
the difference between a parent company and a group.

So this module picks ONE basis, says which, and never mixes. Where a company
files both it prefers consolidated, because that is the group a shareholder
owns. Where it files only one, it uses that and says so.

THE OTHER TRAP: PERCENTAGES ACROSS ZERO
A company that lost 100 crore and then made 50 has not grown 150%. A
percentage change is only meaningful when the base is positive, and printing
one anyway is how a screener reports a turnaround as a decline or a collapse
as growth. Every change here carries a `kind`, and the percentage is None
whenever the base is not positive — with the move described in words and in
rupees instead.

QUARTER ON QUARTER IS NOT THE MAIN COMPARISON
Most Indian businesses are seasonal, so the previous quarter compares a festive
season with a monsoon. Year-on-year — the same quarter twelve months earlier —
is the comparison that means something, and it is the one shown first. The
sequential figure is there too, labelled, because it is what tells you about a
turn.
"""

import datetime as dt
import re

# The lines a reader actually looks for, in the order a P&L presents them.
LINES = [
    ("revenue",          "Revenue from operations",   "money"),
    ("other_income",     "Other income",              "money"),
    ("total_income",     "Total income",              "money"),
    ("materials",        "Cost of materials",         "money"),
    ("employee_cost",    "Employee cost",             "money"),
    ("finance_cost",     "Finance cost",              "money"),
    ("depreciation",     "Depreciation",              "money"),
    ("other_expenses",   "Other expenses",            "money"),
    ("total_expenses",   "Total expenses",            "money"),
    ("ebitda",           "EBITDA",                    "money"),
    ("pbt_before_exceptional", "PBT before exceptional", "money"),
    ("exceptional",      "Exceptional items",         "money"),
    ("pbt",              "Profit before tax",         "money"),
    ("tax",              "Tax",                       "money"),
    ("pat",              "Profit after tax",          "money"),
    ("eps_basic",        "EPS (basic)",               "rupees"),
]

# Ratios computed here rather than taken from the filing, so the arithmetic is
# inspectable and the same in every quarter.
RATIOS = [
    ("opm_pct",          "Operating margin",       "EBITDA ÷ revenue"),
    ("net_margin_pct",   "Net margin",             "PAT ÷ revenue"),
    ("tax_rate_pct",     "Effective tax rate",     "tax ÷ profit before tax"),
    ("other_income_share_pct", "Other income share of PBT",
     "other income ÷ profit before tax"),
    ("interest_cover_x", "Interest cover",         "EBITDA ÷ finance cost"),
    ("employee_cost_pct", "Employee cost of revenue", "employee cost ÷ revenue"),
]

CRORE = 1e7


def _f(v):
    try:
        if v is None:
            return None
        f = float(v)
        return f if f == f and f not in (float("inf"), float("-inf")) else None
    except (TypeError, ValueError):
        return None


def _div(a, b):
    """a/b as a percentage, or None. A zero or negative denominator makes the
    ratio meaningless rather than large."""
    a, b = _f(a), _f(b)
    if a is None or b is None or b <= 0:
        return None
    return round(100.0 * a / b, 2)


def _times(a, b):
    a, b = _f(a), _f(b)
    if a is None or b is None or b <= 0:
        return None
    return round(a / b, 2)


# ---------------------------------------------------------------------------
# Change, honestly
# ---------------------------------------------------------------------------

def change(now, before):
    """
    How a line moved, with a percentage only where one means something.

    `kind` says what happened so the UI never has to infer it from a sign:
      grew / shrank          - a positive base, so a percentage is valid
      loss_to_profit         - crossed zero upwards
      profit_to_loss         - crossed zero downwards
      loss_widened / loss_narrowed - both negative; the percentage would
                               describe a magnitude and read backwards
      flat, unavailable
    """
    n, b = _f(now), _f(before)
    if n is None or b is None:
        return {"pct": None, "abs": None, "kind": "unavailable"}
    delta = n - b
    if b > 0 and n > 0:
        kind = "flat" if abs(delta) < 1e-9 else ("grew" if delta > 0 else "shrank")
        return {"pct": round(100.0 * delta / b, 2), "abs": delta, "kind": kind}
    if b <= 0 < n:
        return {"pct": None, "abs": delta, "kind": "loss_to_profit"}
    if n <= 0 < b:
        return {"pct": None, "abs": delta, "kind": "profit_to_loss"}
    if b < 0 and n < 0:
        return {"pct": None, "abs": delta,
                "kind": "loss_narrowed" if delta > 0 else "loss_widened"}
    return {"pct": None, "abs": delta, "kind": "flat" if abs(delta) < 1e-9 else "changed"}


# ---------------------------------------------------------------------------
# Periods
# ---------------------------------------------------------------------------

def _end(row):
    raw = row.get("to") or (row.get("period") or {}).get("to")
    if not raw:
        return None
    for fmt in ("%Y-%m-%d", "%d-%b-%Y", "%d-%B-%Y"):
        try:
            return dt.datetime.strptime(str(raw).strip(), fmt).date()
        except ValueError:
            continue
    return None


def quarter_label(end: dt.date):
    """'Q1 FY27' for the Indian fiscal year the quarter ends in."""
    if not end:
        return None
    q = {3: 4, 6: 1, 9: 2, 12: 3}.get(end.month)
    if not q:
        return end.isoformat()
    fy = end.year + 1 if end.month >= 4 else end.year
    return "Q%d FY%02d" % (q, fy % 100)


def _is_quarterly(row):
    """
    A quarter, not a year-to-date or a full year.

    A Reg 33 filing carries several periods and the index does not always say
    which one a row is. Three months give or take a fortnight is a quarter;
    anything longer is a cumulative figure, and putting one in a quarterly
    series overstates every line in it.
    """
    start = row.get("from") or (row.get("period") or {}).get("from")
    end = _end(row)
    if not end or not start:
        return True          # a filing that does not say is taken at its word
    for fmt in ("%Y-%m-%d", "%d-%b-%Y", "%d-%B-%Y"):
        try:
            s = dt.datetime.strptime(str(start).strip(), fmt).date()
            break
        except ValueError:
            s = None
    if s is None:
        return True
    return 60 <= (end - s).days <= 130


# ---------------------------------------------------------------------------
# The series
# ---------------------------------------------------------------------------

def _pick_basis(rows, want=None):
    """
    One accounting basis for the whole series, and the reason for it.

    Consolidated where the company files it, because that is the group a
    shareholder owns. Never a mix: standalone and consolidated differ by more
    than a factor of two for a holding company, and alternating between them
    manufactures growth that did not happen.
    """
    has_con = any(r.get("consolidated") is True for r in rows)
    has_std = any(r.get("consolidated") is False for r in rows)
    if want == "standalone" and has_std:
        return False, "standalone", "as requested"
    if want == "consolidated" and has_con:
        return True, "consolidated", "as requested"
    if has_con:
        return True, "consolidated", "the company files consolidated results"
    if has_std:
        return False, "standalone", "the company files standalone results only"
    return None, None, "no filing declares an accounting basis"


def series(symbol, quarters: int = 8, basis: str = None) -> dict:
    """
    Quarterly P&L, ratios and change, on one basis.

    `basis` may be 'consolidated' or 'standalone'; by default the company's
    consolidated results are used where it files them.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "").replace(".BO", "")
    out = {"symbol": sym, "available": False, "rows": [], "lines": [],
           "source": "NSE corporate filings (XBRL, LODR Reg 33)",
           "served_from": "exchange"}
    if not sym:
        out["message"] = "No symbol was given."
        return out

    try:
        import xbrl
    except Exception:
        out["message"] = "The filings reader is not available."
        return out
    if not getattr(xbrl, "available", lambda: True)():
        out["message"] = ("The filings reader is not installed on this instance "
                          "(curl_cffi is required to reach NSE).")
        return out

    want = max(2, min(int(quarters or 8), 16))

    # Choose the basis from the INDEX, which is one cheap call, before any
    # document is fetched. Asking xbrl.statements for both bases and throwing
    # half away doubles the number of documents pulled over the wire for a
    # page that will only ever show one of them — and NSE throttles bursts, so
    # the wasted half is what makes the wanted half fail.
    try:
        idx = xbrl.filings(sym)
    except Exception as e:
        out["message"] = "Could not read the filing index: %s" % str(e)[:110]
        return out
    if not idx:
        out["message"] = ("No quarterly results filing could be read for %s "
                          "right now." % sym)
        return out

    con, label, why = _pick_basis(idx, want=basis if basis in
                                  ("consolidated", "standalone") else None)
    if con is None:
        out["message"] = "No filing for %s declares an accounting basis." % sym
        return out

    try:
        raw = xbrl.statements(sym, limit=want + 2, consolidated=con)
    except Exception as e:
        out["message"] = "Could not read the filings: %s" % str(e)[:110]
        return out
    if not raw:
        out["message"] = ("The %s results for %s could not be read right now."
                          % (label, sym))
        return out

    # statements() falls back to the other basis when a company files only one,
    # so confirm what actually came back rather than trusting the request.
    got = {r.get("consolidated") for r in raw}
    if con not in got:
        con = True if True in got else False
        label = "consolidated" if con else "standalone"
        why = "the company does not file the other basis"

    picked = [r for r in raw if r.get("consolidated") is con and _is_quarterly(r)]
    # Newest first, one row per period end. A revised filing for a quarter
    # arrives later, so the latest filing of a period wins.
    picked.sort(key=lambda r: (_end(r) or dt.date.min,
                               str(r.get("filed_at") or "")), reverse=True)
    seen, rows = set(), []
    for r in picked:
        end = _end(r)
        if not end or end in seen:
            continue
        seen.add(end)
        rows.append(r)
    rows = rows[:want]
    if not rows:
        out["message"] = ("No quarterly %s results could be read for %s."
                          % (label, sym))
        return out

    alternatives = sorted({("consolidated" if f.get("consolidated")
                            else "standalone") for f in idx})
    return _assemble(out, rows, want, label, why, alternatives)


_SHORT_LIVE = ("Only %d of the %d quarters asked for could be read on this view. "
               "Each quarter is a separate document on the exchange and they are "
               "fetched as they are needed; filings already read are kept, so the "
               "history fills in rather than being re-fetched.")


def _assemble(out, rows, want, label, why, alternatives, short_note=_SHORT_LIVE):
    """
    The payload the pane reads, from rows newest first, one per quarter, each
    carrying `to`, `from`, `filed_at`, `audited`, `source_url`, `company` and
    the LINES keys in rupees. Shared by the live reader and the stored one, so
    the two can never disagree on a ratio or a change.
    """
    by_end = {_end(r): r for r in rows}

    def _year_before(end):
        """The same quarter a year earlier, within a fortnight either way."""
        for cand_end, cand in by_end.items():
            if cand_end and 350 <= (end - cand_end).days <= 380:
                return cand
        return None

    built = []
    for i, r in enumerate(rows):
        end = _end(r)
        prev = rows[i + 1] if i + 1 < len(rows) else None
        year = _year_before(end) if end else None

        values = {}
        for key, _lbl, _unit in LINES:
            values[key] = _f(r.get(key))

        rev, pbt = values.get("revenue"), values.get("pbt")
        ratios = {
            "opm_pct": _div(values.get("ebitda"), rev),
            "net_margin_pct": _div(values.get("pat"), rev),
            "tax_rate_pct": _div(values.get("tax"), pbt),
            "other_income_share_pct": _div(values.get("other_income"), pbt),
            "interest_cover_x": _times(values.get("ebitda"), values.get("finance_cost")),
            "employee_cost_pct": _div(values.get("employee_cost"), rev),
        }

        built.append({
            "period_end": end.isoformat() if end else None,
            "label": quarter_label(end),
            "from": r.get("from"),
            "filed_at": r.get("filed_at"),
            "audited": r.get("audited"),
            "source": r.get("source_url"),
            "values": values,
            "ratios": ratios,
            # Change against the same quarter a year earlier is the headline;
            # the sequential one is kept but labelled, because for a seasonal
            # business it compares a festive quarter with a monsoon.
            "yoy": {k: change(values.get(k), _f((year or {}).get(k)))
                    for k, _l, _u in LINES} if year else {},
            "qoq": {k: change(values.get(k), _f((prev or {}).get(k)))
                    for k, _l, _u in LINES} if prev else {},
            "yoy_against": quarter_label(_end(year)) if year else None,
            "qoq_against": quarter_label(_end(prev)) if prev else None,
        })

    out.update({
        "available": True,
        "company": rows[0].get("company"),
        "basis": label,
        "basis_reason": why,
        # From the INDEX, not the filtered set: the filtered set only ever
        # contains the basis in use, so reading it back would always claim the
        # other one does not exist.
        "basis_alternatives": alternatives,
        "rows": built,
        "count": len(built),
        "latest": built[0]["label"] if built else None,
        "requested": want,
        # A cold company needs one network fetch per quarter and NSE throttles
        # bursts, so a first view can legitimately come back short. Saying so
        # beats presenting four quarters as though that were the whole history.
        "partial": len(built) < want,
        "lines": [{"key": k, "label": l, "unit": u} for k, l, u in LINES],
        "ratio_defs": [{"key": k, "label": l, "formula": f} for k, l, f in RATIOS],
        "unit": "crore",
        "unit_divisor": CRORE,
        "notes": [
            "Figures are as filed with the exchange under Regulation 33, on a "
            "%s basis. Standalone and consolidated results are never mixed: "
            "for a group they differ by more than a factor of two, and "
            "alternating between them would report that difference as growth."
            % label,
            "Year-on-year compares the same quarter twelve months earlier. "
            "The sequential change is shown alongside, but for a seasonal "
            "business it compares a festive quarter with a monsoon.",
            "A percentage change is shown only where the earlier figure was "
            "positive. A company that lost money and then made money has not "
            "grown by a percentage, and the move is described instead.",
        ] + ([
            short_note % (len(built), want)
        ] if len(built) < want else []),
    })
    return out


# ---------------------------------------------------------------------------
# From the stored tables
# ---------------------------------------------------------------------------

# A quarter's results are due 45 days after it ends, the March quarter 60.
# A stored series whose newest quarter ended longer ago than this has probably
# missed a filing, so the caller should look at the exchange before serving it.
STORE_FRESH_DAYS = 92 + 62

_SHORT_STORE = ("Only %d of the %d quarters asked for are held for this company "
                "so far. The market-wide crawl reads every company's filings "
                "back to 2018 and fills the history in as it goes.")


def series_from_store(symbol, quarters: int = 8, basis: str = None,
                      today: dt.date = None, allow_stale: bool = False) -> dict:
    """
    The same payload as series(), read from altaha_fundamentals.db instead of
    the exchange: no index call, no document fetch, a few milliseconds.

    Returns None whenever the store cannot answer honestly, so the caller goes
    to the exchange instead:
      * the company has not been crawled yet;
      * the other basis was asked for — the crawl keeps one per company;
      * the newest stored quarter is older than STORE_FRESH_DAYS, so a newer
        filing has probably been made since the last crawl.
    `allow_stale` skips that last check, for when the exchange has just failed
    and an older stored series beats an error.
    """
    try:
        import fundamentals_store as store
    except Exception:
        return None
    sym = (symbol or "").strip().upper().replace(".NS", "").replace(".BO", "")
    if not sym:
        return None
    try:
        recs = store.rows("income", symbol=sym, freq="quarterly")
    except Exception:
        return None
    if not recs:
        return None

    # The crawl keeps one basis per company, but a basis change (a company
    # starting to file consolidated) can leave rows of both; never mix them.
    held = {r.get("basis") for r in recs if r.get("basis")}
    if basis in ("consolidated", "standalone"):
        if basis not in held:
            return None
        label, why = basis, "as requested"
    else:
        label = "consolidated" if "consolidated" in held else \
            ("standalone" if "standalone" in held else None)
        if label is None:
            return None
        why = ("the company files consolidated results" if label == "consolidated"
               else "the company files standalone results only")

    want = max(2, min(int(quarters or 8), 16))
    picked = [r for r in recs if r.get("basis") == label]
    picked.sort(key=lambda r: str(r.get("period_end") or ""), reverse=True)

    newest = None
    try:
        newest = dt.date.fromisoformat(str(picked[0]["period_end"])[:10])
    except (TypeError, ValueError, IndexError, KeyError):
        pass
    today = today or dt.date.today()
    if newest is None:
        return None
    stale = (today - newest).days > STORE_FRESH_DAYS
    if stale and not allow_stale:
        return None

    rows = []
    for r in picked[:want]:
        row = {"to": r.get("period_end"), "from": r.get("period_from"),
               "filed_at": r.get("filed_at"), "audited": r.get("audited"),
               "source_url": r.get("source_url"), "company": r.get("company")}
        for key, _lbl, unit in LINES:
            if unit == "money":
                v = _f(r.get("%s_cr" % key))
                row[key] = None if v is None else v * CRORE
            else:
                row[key] = _f(r.get(key))
        rows.append(row)

    out = {"symbol": sym, "available": False, "rows": [], "lines": [],
           "source": "NSE corporate filings (XBRL, LODR Reg 33), "
                     "as stored by the market-wide crawl",
           "served_from": "store",
           "store_updated": max((str(r.get("updated_utc") or "") for r in picked),
                                default=None) or None}
    # The crawl reads one basis, so the store cannot say whether the company
    # also files the other; the pane then simply does not offer it.
    res = _assemble(out, rows, want, label, why, sorted(held),
                    short_note=_SHORT_STORE)
    if stale:
        res["stale"] = True
        res["notes"] = ["The exchange could not be reached, so this is the "
                        "stored history; its newest quarter is %s and a later "
                        "one may have been filed since." % res.get("latest")] \
            + res.get("notes", [])
    return res
