"""
holdings_job.py — running the sweep in the background, so a button can start it

WHY THIS EXISTS RATHER THAN A LONGER REQUEST
Filling the ledger is about two thousand documents and well over an hour. A
request that does it would be cut off by every proxy between the browser and
the instance long before it finished, and a button that drives it in slices
from the page needs the tab left open for the whole time — on a phone, that is
not a thing anybody can actually do.

So the sweep runs in a thread on the API and the page polls it. Start it,
close the tab, come back. It is the same bounded crawl the scheduled workflow
drives; the only difference is who is asking for the next slice.

WHAT KEEPS THIS SAFE ON A 512 MB INSTANCE
  · ONE at a time. A second start while one is running is refused, not queued —
    two sweeps would double the request rate at NSE, which is the surest way to
    get the instance blocked, and double the memory while doing it.
  · The crawl's own bounds still apply: a slice at a time, a pause between
    companies, and it gives up after a run of consecutive failures rather than
    hammering a rate limiter.
  · It stops on its own when nothing is due, and it can be stopped by hand.
  · Progress is kept in memory only. It is a view of a job, not a record —
    the ledger is the record, and it is on disk.

WHAT HAPPENS IF THE WORKER RESTARTS
The thread dies with it, and the job simply stops. Nothing is corrupted: the
ledger is append-only and the coverage table means the next run continues from
where this one reached rather than starting again. `state()` reports a job that
was interrupted as stopped rather than leaving it looking like it is still
going.
"""

import threading
import time

try:
    import holdings_crawl
except Exception:                                   # pragma: no cover
    holdings_crawl = None

try:
    import holdings_store as store
except Exception:                                   # pragma: no cover
    store = None


_lock = threading.Lock()
_job = {
    "running": False,
    "started_utc": None,
    "finished_utc": None,
    "attempted": 0,
    "read": 0,
    "rows": 0,
    "slices": 0,
    "last_symbol": None,
    "stopping": False,
    "note": None,
    "error": None,
}
_thread = {"t": None}

SLICE = 25            # companies per slice
MAX_SLICES = 400      # a hard ceiling, so a bug cannot run for ever


def _now():
    import datetime as dt
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def running() -> bool:
    t = _thread["t"]
    return bool(_job["running"] and t is not None and t.is_alive())


def state():
    """What the job is doing, plus what the ledger now holds."""
    out = dict(_job)
    # A thread that died with the worker leaves the flag set. Report what is
    # true rather than what was last written.
    if out["running"] and not running():
        out["running"] = False
        out["note"] = out["note"] or ("the job stopped before finishing — most "
                                      "likely the instance restarted. Start it "
                                      "again and it will continue from where "
                                      "it reached.")
    out["alive"] = running()
    if store is not None:
        try:
            st = store.stats()
            out["ledger"] = {
                "companies": st["companies"], "rows": st["rows"],
                "attempted": st["tried"], "latest_period": st["latest_period"],
                "persistent": st["persistent"],
            }
        except Exception:
            pass
    try:
        out["universe"] = len(holdings_crawl.universe()) if holdings_crawl else None
    except Exception:
        out["universe"] = None
    return out


def _sweep(quarters, max_slices):
    try:
        for i in range(max_slices):
            if _job["stopping"]:
                _job["note"] = "stopped by hand"
                break
            r = holdings_crawl.run(limit=SLICE, quarters=quarters)
            _job["slices"] += 1
            _job["attempted"] += r.get("attempted", 0)
            _job["read"] += r.get("ok", 0)
            _job["rows"] += r.get("rows", 0)
            results = r.get("results") or []
            if results:
                _job["last_symbol"] = results[-1].get("symbol")
            if r.get("attempted", 0) == 0:
                _job["note"] = ("every company in the universe has been read — "
                                "the ledger is current.")
                break
            if r.get("stopped_early"):
                # The crawler says the exchange started refusing. Backing off
                # is the entire point of it saying so.
                _job["note"] = r["stopped_early"]
                time.sleep(60)
    except Exception as e:
        _job["error"] = ("%s: %s" % (type(e).__name__, e))[:200]
    finally:
        _job["running"] = False
        _job["stopping"] = False
        _job["finished_utc"] = _now()


def start(quarters=2, max_slices=MAX_SLICES):
    """
    Begin a sweep, or say why not.

    Refuses rather than queues while one is running: two sweeps would double
    the request rate at NSE and the memory on a 512 MB box, and neither would
    finish sooner.
    """
    if holdings_crawl is None or store is None:
        return {"started": False, "reason": "the crawler is not available."}
    with _lock:
        if running():
            return {"started": False, "reason": "a sweep is already running.",
                    "state": state()}
        for k in ("attempted", "read", "rows", "slices"):
            _job[k] = 0
        _job.update({"running": True, "stopping": False, "note": None,
                     "error": None, "last_symbol": None,
                     "started_utc": _now(), "finished_utc": None})
        t = threading.Thread(target=_sweep, args=(quarters, max_slices),
                             daemon=True, name="holdings-sweep")
        _thread["t"] = t
        t.start()
    return {"started": True, "state": state()}


def stop():
    """Ask the sweep to finish its current slice and stop."""
    if not running():
        return {"stopping": False, "reason": "nothing is running."}
    _job["stopping"] = True
    return {"stopping": True,
            "note": "the sweep will stop after the slice it is on."}
