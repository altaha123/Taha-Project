"""
Altaha Screener — answer now, refresh behind

The home page asks for fifteen things. Most are quick. A few are not: the
sector map took nine to thirteen seconds on every visit because nothing kept
its answer, so each visitor paid for a fresh market-wide quote, and while it
ran it held one of the server's few request threads.

This is the one place that fixes that for any route. An answer is kept with the
time it was made, and a request is served by one rule:

  fresh        (younger than `ttl`)        -> the kept answer, nothing else
  stale        (older, but within `keep`)  -> the kept answer NOW, and one
                                              background thread makes a new one
  none / dead  (nothing kept, or too old)  -> made while the caller waits

So after the first visitor nobody waits for a slow source again, and a figure
that is too old to show is never shown: `keep` is the limit, and past it the
caller waits for the real thing rather than being handed yesterday's market.

Only one refresh per key runs at a time. A failed refresh keeps the previous
answer (it is still inside `keep`, or it would not have been served) and is
retried by the next request.

`peek` never waits. It is for the combined /boot answer, which must not be as
slow as its slowest part: a part that is not ready is simply left out, and the
page asks for that one part the ordinary way.
"""

import threading
import time

_LOCK = threading.Lock()
_STORE = {}          # key -> {"at": float, "value": object}
_BUSY = {}           # key -> threading.Event, set when the running refresh ends
_STATS = {"hit": 0, "stale": 0, "wait": 0, "refresh_ok": 0, "refresh_fail": 0}

# How many background refreshes may run together. The server has few threads
# and little memory; a burst of stale keys must not turn into a burst of work.
_SLOTS = threading.BoundedSemaphore(2)


def _now():
    return time.time()


def _refresh(key, fn):
    """Make a new answer for `key`. Always releases the key's busy flag."""
    try:
        value = fn()
        with _LOCK:
            _STORE[key] = {"at": _now(), "value": value}
            _STATS["refresh_ok"] += 1
        return value
    except Exception:
        with _LOCK:
            _STATS["refresh_fail"] += 1
        raise
    finally:
        with _LOCK:
            ev = _BUSY.pop(key, None)
        if ev is not None:
            ev.set()


def _background(key, fn):
    def run():
        with _SLOTS:
            try:
                _refresh(key, fn)
            except Exception:
                pass                       # the kept answer stands
    threading.Thread(target=run, daemon=True, name=f"swr:{key[:40]}").start()


def _claim(key):
    """Mark `key` as being refreshed. Returns (mine, event)."""
    with _LOCK:
        ev = _BUSY.get(key)
        if ev is not None:
            return False, ev
        ev = threading.Event()
        _BUSY[key] = ev
        return True, ev


def get(key, fn, ttl, keep=None, wait=60.0):
    """The answer for `key`, by the rule at the top of this file.

    `fn` takes no arguments and returns the answer; it may raise, and when
    there is nothing usable kept the caller sees that exception.
    """
    keep = max(ttl, keep if keep is not None else ttl * 20)
    with _LOCK:
        hit = _STORE.get(key)
    age = None if hit is None else _now() - hit["at"]

    if hit is not None and age <= ttl:
        with _LOCK:
            _STATS["hit"] += 1
        return hit["value"]

    if hit is not None and age <= keep:
        mine, _ = _claim(key)
        if mine:
            _background(key, fn)
        with _LOCK:
            _STATS["stale"] += 1
        return hit["value"]

    # Nothing usable. Make it here, or wait for whoever is already making it.
    with _LOCK:
        _STATS["wait"] += 1
    mine, ev = _claim(key)
    if mine:
        return _refresh(key, fn)
    ev.wait(wait)
    with _LOCK:
        hit = _STORE.get(key)
    if hit is not None and _now() - hit["at"] <= keep:
        return hit["value"]
    # The other caller failed or is still going. Try once ourselves.
    mine, _ = _claim(key)
    if mine:
        return _refresh(key, fn)
    raise TimeoutError(f"{key} is still being prepared")


def peek(key, fn, ttl, keep=None):
    """Like `get`, but never waits: (value, age_seconds) or (None, None).

    A stale or missing answer starts a background refresh, so the next caller
    finds it ready.
    """
    keep = max(ttl, keep if keep is not None else ttl * 20)
    with _LOCK:
        hit = _STORE.get(key)
    age = None if hit is None else _now() - hit["at"]
    if hit is not None and age <= ttl:
        return hit["value"], age
    mine, _ = _claim(key)
    if mine:
        _background(key, fn)
    if hit is not None and age <= keep:
        return hit["value"], age
    return None, None


def forget(key=None):
    """Drop one kept answer, or all of them. For tests and for admin use."""
    with _LOCK:
        if key is None:
            _STORE.clear()
        else:
            _STORE.pop(key, None)


def stats():
    with _LOCK:
        now = _now()
        return {"counts": dict(_STATS),
                "keys": {k: round(now - v["at"], 1) for k, v in _STORE.items()},
                "refreshing": sorted(_BUSY)}
