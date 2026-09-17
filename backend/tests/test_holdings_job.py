"""
The background sweep.

A button that starts an hour of work has one failure mode worth guarding: more
than one of them running. Two sweeps double the request rate at NSE — the
surest way to get the instance blocked — and double the memory on a box with
512 MB, and neither finishes sooner for it.
"""

import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture()
def job(tmp_path, monkeypatch):
    monkeypatch.setenv("ALTAHA_HOLDINGS_DB", str(tmp_path / "h.db"))
    for m in ("holdings_store", "holdings_crawl", "holdings_job"):
        sys.modules.pop(m, None)
    import holdings_job as j
    monkeypatch.setattr(j.holdings_crawl, "universe", lambda: ["A", "B", "C"])
    return j


def _slices(job, script):
    """Make holdings_crawl.run() return a scripted sequence."""
    calls = {"n": 0}

    def fake_run(limit=None, quarters=None, **kw):
        i = min(calls["n"], len(script) - 1)
        calls["n"] += 1
        time.sleep(0.02)
        return script[i]

    job.holdings_crawl.run = fake_run
    return calls


def _wait(job, timeout=5.0):
    end = time.time() + timeout
    while job.running() and time.time() < end:
        time.sleep(0.02)
    assert not job.running(), "the sweep did not finish"


def test_a_sweep_runs_and_totals_what_it_read(job):
    _slices(job, [{"attempted": 25, "ok": 20, "rows": 400, "results": [{"symbol": "ZZZ"}]},
                  {"attempted": 0, "ok": 0, "rows": 0, "results": []}])
    assert job.start()["started"] is True
    _wait(job)
    s = job.state()
    assert s["read"] == 20 and s["rows"] == 400 and s["slices"] == 2
    assert s["last_symbol"] == "ZZZ"
    assert "ledger is current" in s["note"]


def test_only_one_sweep_at_a_time(job):
    _slices(job, [{"attempted": 25, "ok": 1, "rows": 1, "results": []}] * 50)
    assert job.start()["started"] is True
    second = job.start()
    assert second["started"] is False
    assert "already running" in second["reason"]
    job.stop()
    _wait(job)


def test_stopping_ends_it_and_says_so(job):
    _slices(job, [{"attempted": 25, "ok": 1, "rows": 1, "results": []}] * 500)
    job.start()
    assert job.stop()["stopping"] is True
    _wait(job)
    assert job.state()["note"] == "stopped by hand"


def test_stopping_nothing_is_not_an_error(job):
    assert job.stop()["stopping"] is False


def test_a_sweep_that_raises_is_reported_not_swallowed(job):
    def boom(**kw):
        raise RuntimeError("NSE said no")
    job.holdings_crawl.run = boom
    job.start()
    _wait(job)
    s = job.state()
    assert s["running"] is False
    assert "NSE said no" in s["error"]


def test_the_ceiling_stops_a_sweep_that_would_never_end(job):
    """A crawl that keeps reporting work left, for ever, must still stop."""
    _slices(job, [{"attempted": 25, "ok": 1, "rows": 1, "results": []}] * 10)
    job.start(max_slices=3)
    _wait(job)
    assert job.state()["slices"] == 3


def test_a_job_killed_with_its_worker_does_not_look_alive(job):
    """The thread dies with the instance and the flag is left set. Reporting
    that as "still running" would have somebody waiting on nothing."""
    job._job.update({"running": True})
    job._thread["t"] = None
    s = job.state()
    assert s["running"] is False and s["alive"] is False
    assert "instance restarted" in s["note"]


def test_state_carries_the_ledger_and_the_universe(job):
    s = job.state()
    assert s["universe"] == 3
    assert s["ledger"]["companies"] == 0
