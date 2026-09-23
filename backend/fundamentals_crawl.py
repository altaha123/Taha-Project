"""
fundamentals_crawl.py — filling the fundamentals table, a slice at a time

Every listed company files its quarterly results with NSE under Regulation 33,
so the whole market's P&L is there to be read — but only one company at a
time, from an exchange that throttles bursts, on a 512 MB instance. Same shape
of problem as the holdings ledger and the same answer: bounded slices, driven
by a scheduled workflow, with a coverage table so each slice continues the
last rather than starting again. See holdings_crawl for the longer argument.

Each company is read through fundamentals.series(), the same path the pane
uses, so the table and the page can never disagree about basis, period or
ratio. Filed documents are cached for good by xbrl.fetch(), so after the first
sweep a re-read costs an index call and a document only for a new quarter.
"""

import time

try:
    import fundamentals
except Exception:                                   # pragma: no cover
    fundamentals = None

try:
    import fundamentals_store as store
except Exception:                                   # pragma: no cover
    store = None


DEFAULT_LIMIT = 30
DEFAULT_QUARTERS = 8
PAUSE = 1.5                  # seconds between companies
GIVE_UP_AFTER = 8            # consecutive failures that end a run early


def universe():
    """The NSE EQ list, via the scanner that already maintains it."""
    try:
        import scan
        return [s for s in scan.universe() if s]
    except Exception:
        return []


def crawl_symbol(symbol, quarters=DEFAULT_QUARTERS):
    """One company into the table. Never raises."""
    sym = (symbol or "").strip().upper()
    res = {"symbol": sym, "ok": False, "rows": 0, "quarters": 0,
           "status": "error", "note": ""}
    if not sym or fundamentals is None or store is None:
        res["note"] = "reader unavailable"
        return res
    try:
        s = fundamentals.series(sym, quarters=quarters)
    except Exception as e:
        res["note"] = ("series: %s" % e)[:180]
        store.mark_coverage(sym, "error", note=res["note"])
        return res
    if not s.get("available"):
        msg = s.get("message") or ""
        # "No filing" is an answer about the company — an SME or a newly
        # listed name — and must not be mistaken for the exchange refusing.
        res["status"] = "no-filings" if "No quarterly results filing" in msg \
            or "declares an accounting basis" in msg else "unreadable"
        res["note"] = msg[:180]
        store.mark_coverage(sym, res["status"], note=res["note"])
        return res
    wrote = store.record_series(s)
    got = s.get("rows") or []
    res.update({"ok": True, "rows": wrote, "quarters": len(got),
                "status": "ok", "basis": s.get("basis")})
    store.mark_coverage(sym, "ok", latest_period=got[0].get("period_end") if got else None,
                        quarters=len(got), basis=s.get("basis"),
                        note="partial" if s.get("partial") else "", ok=True)
    return res


def run(limit=DEFAULT_LIMIT, quarters=DEFAULT_QUARTERS, symbols=None,
        pause=PAUSE):
    """One slice of the sweep. `symbols` overrides the queue."""
    started = time.time()
    out = {"attempted": 0, "ok": 0, "rows": 0, "failed": 0,
           "stopped_early": None, "results": []}
    if store is None or fundamentals is None:
        out["stopped_early"] = "the fundamentals reader is not available"
        return out
    try:
        import xbrl
        if not xbrl.available():
            out["stopped_early"] = ("the filings reader is not installed on this "
                                    "instance (curl_cffi is required to reach NSE)")
            return out
    except Exception:
        pass

    queue = [s.strip().upper() for s in symbols if s] if symbols else \
        store.due_symbols(universe(), limit=limit)
    if not queue:
        out["stopped_early"] = "nothing due"
        return out

    misses = 0
    for sym in queue[: max(1, int(limit))]:
        r = crawl_symbol(sym, quarters=quarters)
        out["attempted"] += 1
        out["results"].append(r)
        if r["ok"]:
            out["ok"] += 1
            out["rows"] += r["rows"]
            misses = 0
        else:
            out["failed"] += 1
            if r["status"] in ("error", "unreadable"):
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
