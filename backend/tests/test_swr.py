"""Answer now, refresh behind: the rule in swr.py, one case at a time."""
import threading
import time

import pytest

import swr


@pytest.fixture(autouse=True)
def _clean():
    swr.forget()
    yield
    swr.forget()


def _wait_for(cond, seconds=3.0):
    end = time.time() + seconds
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


def test_a_fresh_answer_is_served_without_asking_again():
    calls = []
    fn = lambda: calls.append(1) or len(calls)
    assert swr.get("k", fn, ttl=60) == 1
    assert swr.get("k", fn, ttl=60) == 1
    assert len(calls) == 1


def test_a_stale_answer_is_served_at_once_and_replaced_behind(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(swr, "_now", lambda: clock[0])
    release = threading.Event()
    n = [0]

    def fn():
        n[0] += 1
        if n[0] > 1:
            release.wait(3)
        return n[0]

    assert swr.get("k", fn, ttl=10, keep=100) == 1
    clock[0] += 30                                   # stale, inside keep
    t0 = time.time()
    assert swr.get("k", fn, ttl=10, keep=100) == 1   # the old answer, now
    assert time.time() - t0 < 0.5                    # and without waiting
    assert swr.get("k", fn, ttl=10, keep=100) == 1   # one refresh, not two
    release.set()
    assert _wait_for(lambda: swr.get("k", fn, ttl=10, keep=100) == 2)
    assert n[0] == 2


def test_an_answer_past_keep_is_not_shown(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(swr, "_now", lambda: clock[0])
    n = [0]

    def fn():
        n[0] += 1
        return n[0]

    assert swr.get("k", fn, ttl=10, keep=100) == 1
    clock[0] += 500                                  # too old to show
    assert swr.get("k", fn, ttl=10, keep=100) == 2   # the caller waited for it


def test_a_failed_refresh_keeps_the_last_good_answer(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(swr, "_now", lambda: clock[0])
    n = [0]

    def fn():
        n[0] += 1
        if n[0] == 2:
            raise RuntimeError("the source is down")
        return n[0]

    assert swr.get("k", fn, ttl=10, keep=100) == 1
    clock[0] += 30
    assert swr.get("k", fn, ttl=10, keep=100) == 1
    assert _wait_for(lambda: n[0] == 2 and "k" not in swr.stats()["refreshing"])
    assert swr.get("k", fn, ttl=10, keep=100) == 1   # still the good one
    assert _wait_for(lambda: swr.get("k", fn, ttl=10, keep=100) == 3)


def test_nothing_kept_and_the_source_fails_is_the_callers_error():
    def fn():
        raise ValueError("no data")
    with pytest.raises(ValueError):
        swr.get("k", fn, ttl=10)
    # and the failure is not remembered as an answer
    assert swr.get("k", lambda: 7, ttl=10) == 7


def test_many_callers_with_nothing_kept_make_it_once():
    n = [0]
    gate = threading.Event()

    def fn():
        n[0] += 1
        gate.wait(3)
        return "made"

    out = []
    threads = [threading.Thread(target=lambda: out.append(swr.get("k", fn, ttl=60)))
               for _ in range(6)]
    for t in threads:
        t.start()
    assert _wait_for(lambda: n[0] == 1)
    time.sleep(0.05)
    gate.set()
    for t in threads:
        t.join(5)
    assert out == ["made"] * 6
    assert n[0] == 1


def test_peek_never_waits_and_fills_behind():
    gate = threading.Event()

    def fn():
        gate.wait(3)
        return "ready"

    t0 = time.time()
    assert swr.peek("k", fn, ttl=60) == (None, None)
    assert time.time() - t0 < 0.5
    gate.set()
    assert _wait_for(lambda: swr.peek("k", fn, ttl=60)[0] == "ready")
    value, age = swr.peek("k", fn, ttl=60)
    assert value == "ready" and age >= 0
