"""
fundamentals_crawl.py — filling the three statement tables, a slice at a time

Every listed company files its results with NSE under Regulation 33: the
quarter's P&L every quarter, and in March and September also the balance sheet
at that date and the cash flow for the year to date. So the whole market's
statements are there to be read — but only one document at a time, from an
exchange that throttles bursts, on a 512 MB instance. Same shape of problem as
the holdings ledger and the same answer: bounded slices, driven by a scheduled
workflow, with a coverage table so each slice continues the last rather than
starting again. See holdings_crawl for the longer argument.

WHAT ONE COMPANY COSTS
The first read is every filing back to 2018 on one basis — about thirty-four
documents. After that `docs` knows what has been read, so a re-read costs the
index call and a document only for a new or revised period. Documents are not
cached on disk here: the tables are the durable copy.

YAHOO FOR A SECOND OPINION
`source="yfinance"` reads Yahoo's income statement, balance sheet and cash
flow into their own tables with their own coverage, so the two sweeps advance
independently and a Yahoo outage never stalls the exchange one. Yahoo is a
secondary source and the tables say so.
"""

import datetime as dt
import time

try:
    import fundamentals
except Exception:                                   # pragma: no cover
    fundamentals = None

try:
    import fundamentals_store as store
except Exception:                                   # pragma: no cover
    store = None


DEFAULT_LIMIT = 8            # companies per call: ~34 documents each at first
MAX_DOCS = 34                # quarters back to September 2018, on one basis
DOC_PAUSE = 0.8              # seconds between documents
DOC_GIVE_UP = 5              # consecutive failed documents that end a company
PAUSE = 1.5                  # seconds between companies
GIVE_UP_AFTER = 6            # consecutive failed companies that end a run


def universe():
    """The NSE EQ list, via the scanner that already maintains it."""
    try:
        import scan
        return [s for s in scan.universe() if s]
    except Exception:
        return []


def _d(raw):
    for fmt in ("%Y-%m-%d", "%d-%b-%Y", "%d-%B-%Y"):
        try:
            return dt.datetime.strptime(str(raw).strip()[:11].title(), fmt).date()
        except (TypeError, ValueError):
            continue
    try:
        return dt.date.fromisoformat(str(raw)[:10])
    except (TypeError, ValueError):
        return None


def _fy(end):
    """'FY26' for the Indian financial year a date falls in."""
    return "FY%02d" % ((end.year + 1 if end.month >= 4 else end.year) % 100)


def _income_values(v):
    """P&L lines plus the six ratios, computed as the pane computes them."""
    out = dict(v)
    rev, pbt, ebitda = v.get("revenue"), v.get("pbt"), v.get("ebitda")
    out.update({
        "opm_pct": fundamentals._div(ebitda, rev),
        "net_margin_pct": fundamentals._div(v.get("pat"), rev),
        "tax_rate_pct": fundamentals._div(v.get("tax"), pbt),
        "other_income_share_pct": fundamentals._div(v.get("other_income"), pbt),
        "interest_cover_x": fundamentals._times(ebitda, v.get("finance_cost")),
        "employee_cost_pct": fundamentals._div(v.get("employee_cost"), rev),
    })
    return out


def _balance_values(b):
    out = dict(b)
    parts = [b.get(k) for k in ("borrowings_non_current", "borrowings_current")]
    if any(p is not None for p in parts):
        debt = sum(p or 0 for p in parts)
    else:
        # Banks and NBFCs file one Borrowings line, and an NBFC's bonds and
        # subordinated debt sit beside it rather than inside it.
        parts = [b.get(k) for k in ("borrowings", "debt_securities", "subordinated_liabilities")]
        debt = sum(p or 0 for p in parts) if any(p is not None for p in parts) else None
    equity = b.get("total_equity")
    if equity is None and b.get("equity_capital") is not None and b.get("other_equity") is not None:
        equity = b["equity_capital"] + b["other_equity"]      # a bank's Capital + Reserves
        out["total_equity"] = equity
    out["total_borrowings"] = debt
    if debt is not None:
        out["net_debt"] = debt - (b.get("cash_and_equivalents") or 0) \
            - (b.get("current_investments") or 0)
    out["debt_equity_x"] = fundamentals._times(debt, equity) if debt is not None else None
    out["current_ratio_x"] = fundamentals._times(b.get("current_assets"),
                                                 b.get("current_liabilities"))
    return out


def _cashflow_values(y):
    out = dict(y)
    parts = [y.get("capex_ppe"), y.get("capex_intangibles")]
    if any(p is not None for p in parts):
        out["capex"] = sum(p or 0 for p in parts)
        if y.get("cfo") is not None:
            out["fcf"] = y["cfo"] - out["capex"]      # payments are filed positive
    return out


def build_rows(symbol, company, basis, meta, data):
    """
    Everything one filing contributes, as {"income": [...], "balance": [...],
    "cashflow": [...]}. Pure: no network, no disk, so it can be tested on a
    parsed document alone.
    """
    out = {"income": [], "balance": [], "cashflow": []}
    period = data.get("period") or {}
    end = _d(meta.get("to")) or _d(period.get("to"))
    if not end:
        return out
    base = {"symbol": symbol, "company": company, "basis": basis,
            "filed_at": meta.get("filed_at"), "audited": meta.get("audited"),
            "source_url": meta.get("xbrl")}

    start = _d(period.get("from"))
    if data.get("revenue") is not None or data.get("pat") is not None:
        span = (end - start).days if start else 90
        if 60 <= span <= 130:
            out["income"].append(store.to_row("income", {
                **base, "freq": "quarterly", "label": fundamentals.quarter_label(end),
                "period_from": start.isoformat() if start else None,
                "period_end": end.isoformat(), "months": 3},
                _income_values(data)))

    y = data.get("ytd") or {}
    months = y.get("months")
    if months == 12 and (y.get("revenue") is not None or y.get("pat") is not None):
        out["income"].append(store.to_row("income", {
            **base, "freq": "annual", "label": _fy(end),
            "period_from": y.get("from"), "period_end": end.isoformat(),
            "months": 12}, _income_values(y)))
    if months in (6, 12) and y.get("cfo") is not None:
        out["cashflow"].append(store.to_row("cashflow", {
            **base, "label": _fy(end) if months == 12 else "H1 " + _fy(end),
            "period_from": y.get("from"), "period_end": end.isoformat(),
            "months": months}, _cashflow_values(y)))

    b = data.get("balance_sheet") or {}
    if b.get("total_assets") is not None:
        out["balance"].append(store.to_row("balance", {
            **base, "label": end.strftime("%b %Y"), "period_end": end.isoformat()},
            _balance_values(b)))
    return out


def crawl_symbol(symbol, max_docs=MAX_DOCS, **_kw):
    """One company into the three tables. Never raises."""
    sym = (symbol or "").strip().upper()
    res = {"symbol": sym, "ok": False, "rows": 0, "documents": 0,
           "status": "error", "note": ""}
    if not sym or fundamentals is None or store is None:
        res["note"] = "reader unavailable"
        return res
    try:
        import xbrl
        idx = xbrl.filings(sym)
    except Exception as e:
        res["note"] = ("index: %s" % e)[:180]
        store.mark_coverage(sym, "error", note=res["note"])
        return res
    if not idx:
        res["status"] = "no-filings"
        res["note"] = "no results filing indexed"
        store.mark_coverage(sym, res["status"], note=res["note"])
        return res

    con, basis, _why = fundamentals._pick_basis(idx)
    if con is None:
        res["status"] = "no-filings"
        res["note"] = "no filing declares an accounting basis"
        store.mark_coverage(sym, res["status"], note=res["note"])
        return res
    picks = [f for f in idx if f.get("consolidated") is con and f.get("xbrl")]
    picks.sort(key=lambda f: (_d(f.get("to")) or dt.date.min), reverse=True)
    picks = picks[: max(1, int(max_docs))]
    done = store.read_docs(sym)
    company = next((f.get("company") for f in picks if f.get("company")), None)

    wrote, read, fails = 0, 0, 0
    for f in picks:
        if f["xbrl"] in done:
            continue
        data = xbrl.fetch(f["xbrl"], cache=False)
        if not data or data.get("ok") is False:
            # NSE refuses in bursts; one retry after a pause gets most back.
            time.sleep(DOC_PAUSE * 5)
            data = xbrl.fetch(f["xbrl"], cache=False)
        if not data or data.get("ok") is False:
            fails += 1
            if fails >= DOC_GIVE_UP:
                res["note"] = "%d documents in a row refused" % fails
                break
            continue
        fails = 0
        built = build_rows(sym, company, basis, f, data)
        for table, recs in built.items():
            wrote += store.upsert(table, recs)
        end = _d(f.get("to"))
        store.mark_doc(sym, f["xbrl"], end.isoformat() if end else None)
        read += 1
        if DOC_PAUSE:
            time.sleep(DOC_PAUSE)
    if read:
        store.recompute_yoy(sym)

    have = store.read_docs(sym)
    outstanding = sum(1 for f in picks if f["xbrl"] not in have)
    latest = max((_d(f.get("to")) for f in picks if f["xbrl"] in have),
                 default=None)
    res.update({"rows": wrote, "documents": read, "basis": basis,
                "outstanding": outstanding})
    if have and not (fails >= DOC_GIVE_UP and read == 0):
        res["ok"], res["status"] = True, "ok" if not outstanding else "partial"
        store.mark_coverage(sym, res["status"], ok=True, basis=basis,
                            latest_period=latest.isoformat() if latest else None,
                            quarters=len(picks) - outstanding, note=res["note"])
    else:
        res["status"] = "unreadable"
        res["note"] = res["note"] or "filings indexed but none could be read"
        store.mark_coverage(sym, res["status"], note=res["note"])
    return res


# yfinance attribute -> (statement, freq)
YF_FRAMES = [
    ("financials", "income", "annual"),
    ("balance_sheet", "balance", "annual"),
    ("cashflow", "cashflow", "annual"),
    ("quarterly_financials", "income", "quarterly"),
    ("quarterly_balance_sheet", "balance", "quarterly"),
    ("quarterly_cashflow", "cashflow", "quarterly"),
]


def _ticker(sym):
    import yfinance as yf
    return yf.Ticker("%s.NS" % sym)


def crawl_yf_symbol(symbol, **_kw):
    """One company's six Yahoo statements into the table. Never raises."""
    sym = (symbol or "").strip().upper()
    res = {"symbol": sym, "ok": False, "rows": 0, "statements": 0,
           "status": "error", "note": ""}
    if not sym or store is None:
        res["note"] = "store unavailable"
        return res
    try:
        t = _ticker(sym)
    except Exception as e:
        res["note"] = ("ticker: %s" % e)[:180]
        store.mark_coverage(sym, "error", note=res["note"], source="yfinance")
        return res
    wrote, got, latest, errors = 0, 0, None, []
    for attr, statement, freq in YF_FRAMES:
        try:
            df = getattr(t, attr)
        except Exception as e:
            errors.append("%s: %s" % (attr, str(e)[:60]))
            continue
        if df is None or getattr(df, "empty", True):
            continue
        values = {}
        for col in df.columns:
            try:
                period = col.date().isoformat()
            except Exception:
                period = str(col)[:10]
            for item, v in df[col].items():
                values[(period, str(item))] = v
        n = store.record_yf(sym, statement, freq, values)
        if n or values:
            got += 1
        wrote += n
        latest = max([latest or ""] + [p for p, _i in values]) or None
    if got:
        res.update({"ok": True, "rows": wrote, "statements": got, "status": "ok"})
        store.mark_coverage(sym, "ok", latest_period=latest, quarters=got,
                            note="; ".join(errors)[:180], ok=True, source="yfinance")
    else:
        # Every frame raising is Yahoo refusing; every frame empty is Yahoo
        # having nothing for this name, which is an answer about the company.
        res["status"] = "error" if errors else "no-data"
        res["note"] = "; ".join(errors)[:180] or "Yahoo returned no statements"
        store.mark_coverage(sym, res["status"], note=res["note"], source="yfinance")
    return res


def run(limit=DEFAULT_LIMIT, symbols=None, pause=PAUSE, source="nse"):
    """One slice of the sweep. `symbols` overrides the queue."""
    started = time.time()
    out = {"source": source, "attempted": 0, "ok": 0, "rows": 0, "failed": 0,
           "stopped_early": None, "results": []}
    if store is None or (source == "nse" and fundamentals is None):
        out["stopped_early"] = "the fundamentals reader is not available"
        return out
    if source == "nse":
        try:
            import xbrl
            if not xbrl.available():
                out["stopped_early"] = ("the filings reader is not installed on this "
                                        "instance (curl_cffi is required to reach NSE)")
                return out
        except Exception:
            pass
    crawl = crawl_yf_symbol if source == "yfinance" else crawl_symbol

    queue = [s.strip().upper() for s in symbols if s] if symbols else \
        store.due_symbols(universe(), limit=limit, source=source)
    if not queue:
        out["stopped_early"] = "nothing due"
        return out

    misses = 0
    for sym in queue[: max(1, int(limit))]:
        r = crawl(sym)
        out["attempted"] += 1
        out["results"].append(r)
        if r["ok"]:
            out["ok"] += 1
            out["rows"] += r["rows"]
            misses = 0
        else:
            out["failed"] += 1
            # Yahoo throttles by returning empty frames rather than an error,
            # so for it a run of "no data" is the refusal to back off from.
            if r["status"] in ("error", "unreadable") or \
                    (source == "yfinance" and r["status"] == "no-data"):
                misses += 1
        if misses >= GIVE_UP_AFTER:
            out["stopped_early"] = (
                "%d companies in a row could not be read — stopping rather "
                "than continuing to hammer a rate limiter" % misses)
            break
        if pause:
            time.sleep(pause)

    out["seconds"] = round(time.time() - started, 1)
    out["store"] = store.stats()
    return out
