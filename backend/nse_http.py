"""
Altaha Screener — talking to NSE from a datacenter

THE PROBLEM THIS SOLVES, ONCE
NSE's WAF rejects a plain `requests` call from a datacenter IP with a 403 that
no combination of headers gets past. It fingerprints the TLS handshake, not the
request. Measured from this project's own host: the results endpoint answers
403 to `requests` and 200 with nineteen rows to curl_cffi against the identical
URL, params and headers.

That is not a theoretical concern. `xbrl.py` shipped with plain requests, so on
Render — which is a datacenter IP — every call returned 403, `summary()`
reported "no XBRL results filing found for this symbol", and the whole
primary-source fundamentals path fell back to the provider without anything
logging an error. It looked like a coverage gap and was a transport failure.

curl_cffi impersonates a real Chrome handshake. It is already a dependency
(yfinance pulls it for the same reason), so this costs nothing new.

WHY A MODULE RATHER THAN A COPY
`shareholding_filings.py` had already worked this out and grown its own copy;
`xbrl.py` had not, and silently returned nothing for it. Session construction,
the cookie warm-up and the 401/403 re-warm are the parts that are easy to get
subtly wrong, so the next caller gets them from here instead of from a paste.
(shareholding_filings still carries its own and should be moved onto this.)

NSE hands out cookies on its public pages and expects them on /api. A cold
call gets 401 or an empty body, so the session is warmed against the home page
and the caller's own referer page first, and re-warmed once on a 401/403 before
the call is given up on.
"""

import threading
import time

NSE_HOME = "https://www.nseindia.com/"
TIMEOUT = int(__import__("os").environ.get("NSE_TIMEOUT", "30") or 30)
WARM_TTL = 1800

_lock = threading.Lock()
_sessions = {}          # referer -> {"s": session, "warm": ts}


def _curl():
    try:
        from curl_cffi import requests as cr
        return cr
    except Exception:
        return None


def available() -> bool:
    """False when curl_cffi is missing. Callers say so rather than reporting
    an empty result as though the exchange had no data."""
    return _curl() is not None


def session(referer: str = NSE_HOME):
    """
    One session per referer, built on first use.

    Per referer because the cookie a page hands out is scoped to the section
    it came from, and because importing this module must not open a connection
    pool — parsing needs no network and a small instance pays for every object
    created at import whether or not it is used.
    """
    cr = _curl()
    if cr is None:
        return None
    with _lock:
        slot = _sessions.setdefault(referer, {"s": None, "warm": 0.0})
        if slot["s"] is None:
            slot["s"] = cr.Session(impersonate="chrome")
        return slot["s"]


def warm(referer: str = NSE_HOME, force: bool = False):
    """Collect the cookies /api expects. Cheap, and skipped inside the TTL."""
    slot = _sessions.get(referer)
    if slot and not force and time.time() - slot["warm"] < WARM_TTL:
        return
    s = session(referer)
    if s is None:
        return
    for url in (NSE_HOME, referer):
        if not url:
            continue
        try:
            s.get(url, timeout=TIMEOUT)
        except Exception:
            pass
    # setdefault, not indexing: this must not depend on session() having
    # created the slot as a side effect. Without it a warm that reaches a
    # session from anywhere else raises KeyError after doing the work.
    _sessions.setdefault(referer, {"s": s, "warm": 0.0})["warm"] = time.time()


# NSE throttles bursts: a call can be refused and the identical call a few
# seconds later answered in full. Observed directly while building this —
# first attempt blocked, second returned nineteen rows. Bounded, because a
# retry loop against a rate limiter is how you earn a longer ban, and the
# caller gets None rather than a wait that outlives a page load.
RETRIES = int(__import__("os").environ.get("NSE_RETRIES", "2") or 2)
BACKOFF = float(__import__("os").environ.get("NSE_BACKOFF", "1.5") or 1.5)


def get(url, params=None, referer: str = NSE_HOME, timeout: int = None):
    """
    One authenticated NSE call. Returns the response, or None.

    None rather than an exception, and never a partial: every caller renders
    "could not be read" rather than an empty dataset that looks like a company
    with no filings.
    """
    s = session(referer)
    if s is None:
        return None
    warm(referer)
    for attempt in range(RETRIES + 1):
        try:
            r = s.get(url, timeout=timeout or TIMEOUT, params=params,
                      headers={"Referer": referer})
            if r.status_code == 200:
                return r
            # A refusal is usually the cookie going stale or a burst limit.
            # Re-warm and back off rather than hammering the same handshake.
            if r.status_code in (401, 403, 429) and attempt < RETRIES:
                warm(referer, force=True)
                time.sleep(BACKOFF * (attempt + 1))
                continue
            return None
        except Exception:
            if attempt < RETRIES:
                time.sleep(BACKOFF * (attempt + 1))
                continue
            return None
    return None


def get_json(url, params=None, referer: str = NSE_HOME):
    """The JSON body of one call, or None. NSE wraps lists in several shapes."""
    r = get(url, params=params, referer=referer)
    if r is None:
        return None
    try:
        return r.json()
    except Exception:
        return None


def rows(body):
    """The list inside an NSE response, whatever key it arrived under."""
    if isinstance(body, list):
        return body
    if isinstance(body, dict):
        for key in ("data", "resultBody", "records", "Table", "table"):
            v = body.get(key)
            if isinstance(v, list):
                return v
    return []
