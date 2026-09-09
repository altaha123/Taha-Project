"""
The universe scan and the memory it is allowed to use.

Both regressions covered here produced the same visible symptom — "Engine
unreachable — it may be waking from sleep" on the Ideas tab, every time the
user pressed Refresh universe scan — for the same underlying reason: a scan
started on an instance with no room for it, the instance was killed part-way
through, and every request failed until Render brought the process back. The
browser cannot tell that apart from a sleeping server, so the message it
showed sent the user straight back to the button that caused it.

  1. /scan/start read ONE flag for two different overrides. Refresh has to
     send force=true to get past the 12-hour cache, and force also switched
     off the headroom check — so the only press anyone ever made was the one
     press the safety valve could never see.

  2. The scan itself had no way to stop. It ran until the kernel stopped it.
"""
import pytest


@pytest.fixture(scope="module")
def main_mod():
    import main
    return main


# ---------------------------------------------------------------------------
# 1. force ignores the cache. It does not ignore the memory guard.
# ---------------------------------------------------------------------------

@pytest.fixture
def cramped(main_mod, monkeypatch):
    """An instance holding all but 10 MB of its limit."""
    monkeypatch.setattr(main_mod, "_reclaim",
                        lambda: (main_mod.MEM_LIMIT_MB - 10, main_mod.MEM_LIMIT_MB - 10))
    monkeypatch.setattr(main_mod, "_rss_mb", lambda: main_mod.MEM_LIMIT_MB - 10)
    started = []
    monkeypatch.setattr(main_mod.threading, "Thread",
                        lambda *a, **k: started.append(k) or _NoThread())
    return started


class _NoThread:
    def start(self):
        pass


def test_refresh_does_not_bypass_the_memory_guard(main_mod, cramped):
    r = main_mod.scan_start(force=True)
    assert r["started"] is False
    assert r["reason"] == "low_memory"
    assert not cramped, "a scan was started with no headroom"


def test_the_refusal_states_the_numbers_behind_it(main_mod, cramped):
    r = main_mod.scan_start(force=True)
    assert r["headroom_mb"] == pytest.approx(10, abs=0.5)
    assert r["limit_mb"] == main_mod.MEM_LIMIT_MB
    assert str(main_mod.MEM_LIMIT_MB) in r["message"]
    # The override has to be nameable, or the refusal is a dead end.
    assert "ignore_memory" in r["message"]


def test_ignore_memory_is_the_explicit_override(main_mod, cramped):
    r = main_mod.scan_start(force=True, ignore_memory=True)
    assert r.get("reason") != "low_memory"


def test_force_memory_still_works_for_an_existing_caller(main_mod, cramped):
    r = main_mod.scan_start(force=True, force_memory=True)
    assert r.get("reason") != "low_memory"


def test_a_roomy_instance_is_never_refused(main_mod, monkeypatch):
    monkeypatch.setattr(main_mod, "_reclaim", lambda: (100.0, 100.0))
    monkeypatch.setattr(main_mod, "_rss_mb", lambda: 100.0)
    monkeypatch.setattr(main_mod.threading, "Thread", lambda *a, **k: _NoThread())
    r = main_mod.scan_start(force=True)
    assert r.get("reason") != "low_memory"


# ---------------------------------------------------------------------------
# 2. The scan stops itself rather than being stopped by the kernel.
# ---------------------------------------------------------------------------

def test_phase1_stops_when_the_headroom_runs_out(monkeypatch):
    import scan

    monkeypatch.setattr(scan, "_should_stop", lambda: True)
    cands, ill, nod, stopped = scan.phase1(["AAA", "BBB"], None, {"done": 0, "total": 2})
    assert cands == []
    assert stopped and "limit" in stopped
    # Symbols that were never looked at are not recorded as having had no data.
    assert nod == 0


def test_phase1_reports_nothing_when_there_is_room(monkeypatch):
    import scan

    monkeypatch.setattr(scan, "_should_stop", lambda: False)
    monkeypatch.setattr(scan, "yf", _NoDownload())
    cands, ill, nod, stopped = scan.phase1(["AAA"], None, {"done": 0, "total": 1})
    assert stopped is None


class _NoDownload:
    @staticmethod
    def download(*a, **k):
        return None


def test_should_stop_is_false_when_rss_is_unreadable(monkeypatch):
    """Off Linux there is no /proc, and an unknown RSS must not abort a scan."""
    import scan

    monkeypatch.setattr(scan, "rss_mb", lambda: None)
    assert scan._should_stop() is False


def test_should_stop_trims_before_giving_up(monkeypatch):
    """
    A first reading below the threshold is not the answer. glibc holds freed
    arenas, so the check that matters is the one taken after handing them back
    — otherwise the scan aborts over memory nothing is still using.
    """
    import scan

    readings = iter([scan.MEM_LIMIT_MB - 5, 100.0])
    monkeypatch.setattr(scan, "rss_mb", lambda: next(readings))
    trimmed = []
    monkeypatch.setattr(scan, "trim", lambda: trimmed.append(1))
    assert scan._should_stop() is False
    assert trimmed, "gave up without trimming first"


def test_payload_says_when_a_scan_stopped_early():
    import scan

    p = scan._build_payload([], "test", 10, 0, 0, 0, 0, 0, [],
                            partial=False, stopped="ran out of room")
    assert p["stopped_early"] is True
    assert p["stopped_reason"] == "ran out of room"


def test_a_completed_scan_is_not_marked_stopped():
    import scan

    p = scan._build_payload([], "test", 10, 0, 0, 0, 0, 0, [])
    assert p["stopped_early"] is False
    assert p["stopped_reason"] is None


def test_scan_status_carries_the_stop_reason_to_the_browser(main_mod):
    before = main_mod._state["payload"]
    main_mod._state["payload"] = {"scanned_at": "09 Sep 2026, 10:00",
                                  "stopped_early": True,
                                  "stopped_reason": "Depth pass stopped."}
    try:
        s = main_mod.scan_status()
        assert s["stopped_early"] is True
        assert s["stopped_reason"] == "Depth pass stopped."
    finally:
        main_mod._state["payload"] = before


def test_scan_status_is_silent_about_stopping_when_nothing_stopped(main_mod):
    before = main_mod._state["payload"]
    main_mod._state["payload"] = {"scanned_at": "09 Sep 2026, 10:00"}
    try:
        assert "stopped_early" not in main_mod.scan_status()
    finally:
        main_mod._state["payload"] = before


# ---------------------------------------------------------------------------
# 3. The scan sizes itself to the room it has.
# ---------------------------------------------------------------------------

def test_a_roomy_instance_keeps_the_fast_settings(monkeypatch):
    import scan

    monkeypatch.setattr(scan, "headroom_mb", lambda: 300.0)
    assert scan.plan_footprint() == (scan.CHUNK, scan.PHASE2_WORKERS)


def test_unknown_headroom_keeps_the_fast_settings(monkeypatch):
    """Off Linux there is no RSS to read, and a local run must not be crippled."""
    import scan

    monkeypatch.setattr(scan, "headroom_mb", lambda: None)
    assert scan.plan_footprint() == (scan.CHUNK, scan.PHASE2_WORKERS)


def test_a_cramped_instance_scans_smaller_and_alone(monkeypatch):
    import scan

    monkeypatch.setattr(scan, "headroom_mb", lambda: 60.0)
    chunk, workers = scan.plan_footprint()
    assert chunk < scan.CHUNK
    assert workers == 1


def test_the_middle_band_narrows_the_chunk_only(monkeypatch):
    import scan

    monkeypatch.setattr(scan, "headroom_mb", lambda: 100.0)
    chunk, workers = scan.plan_footprint()
    assert chunk < scan.CHUNK
    assert workers == scan.PHASE2_WORKERS


def test_phase1_honours_the_chunk_it_is_given(monkeypatch):
    """The dial has to reach the loop, not just be computed and dropped."""
    import scan

    monkeypatch.setattr(scan, "_should_stop", lambda: False)
    sizes = []

    class _Recording:
        @staticmethod
        def download(tickers, **k):
            sizes.append(len(tickers.split()))
            return None

    monkeypatch.setattr(scan, "yf", _Recording())
    scan.phase1(["S%d" % i for i in range(25)], None,
                {"done": 0, "total": 25}, chunk_size=10)
    assert sizes == [10, 10, 5]
