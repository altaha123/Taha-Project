"""
lens_runner.py — the Run button on the Lenses page

WHAT PRESSING RUN DOES
One background job on the API, in three steps:

  1  compute every live lens straight away from what is already held, so the
     page has fresh results within seconds;
  2  read the next companies' NSE industry, share count, price and
     shareholding (lens_data_crawl), a slice at a time, until every company
     has been read or the exchange starts refusing;
  3  recompute every few slices while it goes, and once more at the end, so
     the counts on the page grow as the inputs fill in.

WHY A BACKGROUND JOB AND NOT THE REQUEST ITSELF
Reading two thousand companies from an exchange that throttles bursts takes
hours. A request that long is cut off by every proxy in between, and driving it
from the browser would need the tab left open. So the button starts the job
and the page polls /api/lenses/run for progress: press Run, close the tab,
come back.

One job at a time, guarded by a lock; a second press while one is running
reports the running job instead of starting another. Nothing runs on a
schedule: the lenses are recomputed when someone presses Run.
"""

import threading
import time
from datetime import datetime, timezone

COMPUTE_EVERY = 4          # slices between recomputes while the crawl runs
SLICE = 25                 # companies per crawl slice
PAUSE_ON_REFUSAL = 90      # seconds to back off when the exchange refuses a slice
MAX_REFUSALS = 3           # refused slices in a row before the job stops

_lock = threading.Lock()
_stop = threading.Event()
_state = {
    "running": False, "phase": "idle", "started_utc": None, "finished_utc": None,
    "companies_read": 0, "companies_ok": 0, "slices": 0, "computes": 0,
    "last_run_id": None, "last_counts": None, "message": None, "error": None,
}


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def status():
    out = dict(_state)
    try:
        import lens_store
        st = lens_store.stats()
        out["profiled"] = st.get("companies_profiled")
        out["with_shareholding"] = st.get("companies_with_shareholding")
    except Exception:
        pass
    try:
        import lens_data_crawl
        out["universe"] = len(lens_data_crawl.universe())
    except Exception:
        out["universe"] = None
    return out


def _compute():
    import lens_job
    _state["phase"] = "computing"
    res = lens_job.compute()
    _state["computes"] += 1
    _state["last_run_id"] = res.get("run_id")
    _state["last_counts"] = res.get("counts")
    return res


def _job(read_inputs, max_slices):
    try:
        _compute()
        if read_inputs:
            import lens_data_crawl
            refusals, since = 0, 0
            while not _stop.is_set() and (max_slices is None or _state["slices"] < max_slices):
                _state["phase"] = "reading"
                out = lens_data_crawl.run(limit=SLICE)
                _state["slices"] += 1
                _state["companies_read"] += out.get("attempted", 0)
                _state["companies_ok"] += out.get("ok", 0)
                early = out.get("stopped_early")
                if not out.get("attempted"):
                    _state["message"] = early or "Every company has been read."
                    break
                if early:
                    refusals += 1
                    if refusals >= MAX_REFUSALS:
                        _state["message"] = ("Stopped: the exchange refused %d slices in a row. "
                                             "Press Run again later to continue." % refusals)
                        break
                    _state["phase"] = "waiting"
                    _stop.wait(PAUSE_ON_REFUSAL)
                    continue
                refusals = 0
                since += 1
                if since >= COMPUTE_EVERY:
                    _compute()
                    since = 0
            if _stop.is_set():
                _state["message"] = "Stopped on request."
        _compute()
        _state["phase"] = "done"
    except Exception as e:           # reported on the page, never swallowed
        _state["error"] = "%s: %s" % (type(e).__name__, str(e)[:200])
        _state["phase"] = "error"
    finally:
        _state["running"] = False
        _state["finished_utc"] = _now()
        _lock.release()


def start(read_inputs=True, max_slices=None):
    """Start the job. Returns the status, with started=False if one was running."""
    if not _lock.acquire(blocking=False):
        return dict(status(), started=False)
    _stop.clear()
    _state.update({"running": True, "phase": "starting", "started_utc": _now(),
                   "finished_utc": None, "companies_read": 0, "companies_ok": 0,
                   "slices": 0, "computes": 0, "message": None, "error": None})
    threading.Thread(None, _job, "lens-run", (read_inputs, max_slices), daemon=True).start()
    return dict(status(), started=True)


def stop():
    _stop.set()
    return status()


def wait(timeout=30):
    """For tests: block until the job finishes."""
    t0 = time.time()
    while _state["running"] and time.time() - t0 < timeout:
        time.sleep(0.05)
    return status()
