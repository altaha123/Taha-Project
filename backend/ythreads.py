"""
yfinance's thread fan-out, bounded — and the memory it leaves behind, reclaimed.

WHY THIS FILE EXISTS
--------------------
`yf.download(tickers, threads=True)` does not use a thread pool. Read
yfinance/multi.py::_download_impl:

    if threads:
        if threads is True:
            threads = min([len(tickers), _multitasking.cpu_count() * 2])
        _multitasking.set_max_threads(threads)
        for i, ticker in enumerate(tickers):
            _download_one_threaded(ctx, ticker, ...)   # @multitasking.task

`_download_one_threaded` is decorated with `@multitasking.task`, and that
decorator starts a NEW OS THREAD PER CALL. set_max_threads() does not cap
thread creation — multitasking acquires its semaphore *inside* the thread
body (multitasking/__init__.py::_run_via_pool), so all N threads are created
and started immediately and merely queue on the semaphore once running.

So scan.phase1, which downloads in chunks of CHUNK symbols, was creating one
OS thread per symbol per chunk: 40 threads a chunk, ~1,200 over a full
universe pass. Measured on the live instance mid-scan: 436 live threads, and
multitasking's internal counter running 2293 -> 2839 in thirty seconds.

Worse, every one of those threads is appended to multitasking's module-level
`config["TASKS"]` list and never removed. That list is only ever *read* --
wait_for_tasks() and killall() filter it into throwaway locals; nothing
assigns back. Demonstrated with a standalone script: five rounds of sixty
tasks each leaves TASKS at 300 with zero of them alive, after
wait_for_tasks() and gc.collect().

The instance has ~45 MB of headroom over its idle baseline. Forty concurrent
downloads, each parsing a year of daily OHLCV, does not fit in that, which is
why no universe scan had completed since 31 Aug: they were being started and
then OOM-killed part-way, leaving the cached payload from the last one that
finished.

WHAT THIS DOES
--------------
serial_downloads()  makes threads=False the default for yf.download, which
                    takes the `else` branch above -- a plain sequential loop
                    that never touches multitasking. Callers that genuinely
                    want fan-out can still pass threads= explicitly.
reap()              drops finished threads from multitasking's TASKS list, as
                    a safety net for any yfinance path we do not control.

Both are no-ops if the libraries are missing or change shape, because a
memory guard that can break the app it protects is not a guard.
"""

import functools

__all__ = ["serial_downloads", "reap", "tracked_tasks"]

_applied = {"download": False, "reason": ""}


def tracked_tasks():
    """How many task objects multitasking is still holding, or None."""
    try:
        import multitasking
        return len(multitasking.config["TASKS"])
    except Exception:
        return None


def reap():
    """
    Drop finished threads from multitasking's TASKS list.

    Returns the number removed, or 0. multitasking never shrinks this list
    itself, so without this it grows for the life of the process — one entry
    per ticker per download, forever.
    """
    try:
        import multitasking
        tasks = multitasking.config.get("TASKS")
        if not tasks:
            return 0
        before = len(tasks)
        # Rebuild in place: other module-level code holds a reference to this
        # exact list object, so rebinding config["TASKS"] would orphan it.
        alive = [t for t in tasks if t is not None and t.is_alive()]
        tasks[:] = alive
        return before - len(alive)
    except Exception:
        return 0


def serial_downloads():
    """
    Default yf.download to threads=False.

    Wraps rather than edits: an explicit threads= from a caller still wins, so
    this changes the default and nothing else. Idempotent.
    """
    if _applied["download"]:
        return True
    try:
        import yfinance as yf
    except Exception as e:                       # yfinance absent (tests)
        _applied["reason"] = f"yfinance not importable: {e}"
        return False
    try:
        original = yf.download

        @functools.wraps(original)
        def download(*args, **kwargs):
            kwargs.setdefault("threads", False)
            return original(*args, **kwargs)

        yf.download = download
        _applied["download"] = True
        return True
    except Exception as e:
        _applied["reason"] = f"could not wrap yf.download: {e}"
        return False


def status():
    """For /health/memory, so this is visible rather than assumed."""
    return {"serial_downloads": _applied["download"],
            "multitasking_tasks_held": tracked_tasks(),
            "error": _applied["reason"] or None}
