"""
holdings_crawl.py — filling the holdings ledger, a slice at a time

THE SHAPE OF THE PROBLEM
An investor's portfolio is spread across every company they hold, and the only
place it is written down is each company's own shareholding filing. There are
about two thousand of them. Each needs an index call and a document fetch, from
an exchange that throttles bursts, on an instance with 512 MB of memory and one
worker. A full sweep is hours of wall-clock time and cannot happen inside a
request — so it happens in slices, and the coverage table is what makes each
slice continue the last one rather than start it again.

WHY IT RUNS FROM A SCHEDULED WORKFLOW
Same reasoning as the daily digest: Render's cron is a paid add-on and an
in-process timer dies with the worker. A GitHub workflow is versioned, its
history is visible, and a failed run is an email rather than silence.

WHAT ONE RUN COSTS, DELIBERATELY BOUNDED
`limit` companies per run, a pause between each, and it stops early on a run of
consecutive failures. A crawler that keeps hammering a rate limiter after it
has started refusing does not collect more data; it earns a longer ban. Better
to take the next slice in an hour.

QUARTERS, NOT JUST THE LATEST
Each company is read for several quarters at once, because the expensive part
is reaching NSE at all and a portfolio is far more useful with a quarter to
compare against. The ledger is append-only, so a re-crawl of a quarter already
held writes nothing and costs only the fetch.
"""

import time

try:
    import shareholding_filings as shp
except Exception:                                   # pragma: no cover
    shp = None

try:
    import holdings_store as store
except Exception:                                   # pragma: no cover
    store = None


DEFAULT_LIMIT = 40
DEFAULT_QUARTERS = 4
PAUSE = 1.2                  # seconds between companies
GIVE_UP_AFTER = 8            # consecutive failures that end a run early


def universe():
    """The NSE EQ list, via the scanner that already maintains it."""
    try:
        import scan
        syms = scan.universe()
        return [s for s in syms if s]
    except Exception:
        return []


def crawl_symbol(symbol, quarters=DEFAULT_QUARTERS):
    """
    One company, several quarters, into the ledger.

    Returns a dict describing what happened. Never raises: a crawler that dies
    on one bad symbol stops collecting for every other one.
    """
    sym = (symbol or "").strip().upper()
    res = {"symbol": sym, "ok": False, "rows": 0, "quarters": 0,
           "status": "error", "note": ""}
    if not sym or shp is None or store is None:
        res["note"] = "reader unavailable"
        return res
    try:
        idx = shp.index(sym)
    except Exception as e:
        res["note"] = ("index: %s" % e)[:180]
        store.mark_coverage(sym, "error", note=res["note"])
        return res
    if not idx:
        res["status"] = "no-filings"
        res["note"] = "no shareholding filing indexed"
        store.mark_coverage(sym, res["status"], note=res["note"])
        return res

    # Quarter ends only. An interim filing — one made within ten days of a
    # capital change, as Regulation 31 requires — is a real document but it is
    # not a quarter, and mixing the two makes a position look like it moved
    # when only the filing date did. index() already returns one row per period,
    # newest first, with the flag on it.
    picks = [f for f in idx if f.get("quarter_end") and f.get("xbrl")]
    picks = picks[: max(1, int(quarters))]
    if not picks:
        res["status"] = "no-quarter-ends"
        res["note"] = "indexed filings are all interim"
        store.mark_coverage(sym, res["status"], note=res["note"])
        return res

    wrote, done, last_period = 0, 0, None
    for f in picks:
        url = f.get("xbrl")
        if not url:
            continue
        try:
            parsed = shp.filing(url, period=f.get("period") or "",
                                filed=f.get("filed") or "",
                                revised=bool(f.get("revised")))
        except Exception as e:
            res["note"] = ("filing: %s" % e)[:180]
            continue
        if not parsed or not parsed.get("names"):
            continue
        period_end = parsed.get("period_end") or f.get("period")
        if not period_end:
            continue
        # The index said this was a quarter end; the DOCUMENT gets the final
        # say, and the two can disagree. Ram Bhajo's filing was indexed at a
        # quarter end and dated itself 1 July — which, stored, became the
        # newest period in the whole ledger and made every "current quarter"
        # question return a period one company had filed for.
        if not store.is_quarter_end(period_end):
            res["note"] = "a filing dated %s is not a quarter end" % period_end
            continue
        wrote += store.record_filing(sym, period_end, parsed["names"],
                                     filed=f.get("filed"), source_url=url)
        done += 1
        last_period = max(last_period or "", period_end)

    if done:
        res.update({"ok": True, "rows": wrote, "quarters": done,
                    "status": "ok", "note": ""})
        store.mark_coverage(sym, "ok", latest_period=last_period, quarters=done,
                            rows_written=wrote, ok=True)
    else:
        res["status"] = "unreadable"
        res["note"] = res["note"] or "filings indexed but none could be read"
        store.mark_coverage(sym, res["status"], note=res["note"])
    return res


def run(limit=DEFAULT_LIMIT, quarters=DEFAULT_QUARTERS, symbols=None,
        pause=PAUSE, progress=None):
    """
    One slice of the sweep.

    `symbols` overrides the queue, for backfilling a company on demand. Without
    it the store decides what is due — never-tried companies first, then the
    ones tried longest ago.
    """
    started = time.time()
    out = {"attempted": 0, "ok": 0, "rows": 0, "failed": 0,
           "stopped_early": None, "results": []}
    if store is None or shp is None:
        out["stopped_early"] = "the filings reader is not available"
        return out
    if not getattr(shp, "available", lambda: True)():
        out["stopped_early"] = ("the filings reader is not installed on this "
                                "instance (curl_cffi is required to reach NSE)")
        return out

    queue = [s.strip().upper() for s in symbols if s] if symbols else \
        store.due_symbols(universe(), limit=limit)
    if not queue:
        out["stopped_early"] = "nothing due"
        return out

    misses = 0
    for i, sym in enumerate(queue[: max(1, int(limit))]):
        r = crawl_symbol(sym, quarters=quarters)
        out["attempted"] += 1
        out["results"].append(r)
        if r["ok"]:
            out["ok"] += 1
            out["rows"] += r["rows"]
            misses = 0
        else:
            out["failed"] += 1
            # "no filings" is an answer about the company, not a refusal from
            # the exchange, and must not count towards giving up.
            if r["status"] in ("error", "unreadable"):
                misses += 1
        if progress:
            try:
                progress(i + 1, len(queue), r)
            except Exception:
                pass
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
