"""
Every admin endpoint must accept the key in the X-Admin-Key header.

This exists because one of them did not, and nothing noticed.

/admin/funds/ingest was given the header parameter in its signature and kept
`_require_admin(key)` in its body — a half-applied edit. FastAPI accepted the
header, parsed it, bound it, and the guard ignored it. The endpoint was
reachable with the key in the query string, so a manual check passed; the
nightly job sends the header, so every fund slice got 401 and the fund-house
page stayed empty for a day while the crawl step beside it worked perfectly.

Enumerated from the app's own routing table rather than written out by hand,
so an admin endpoint added later is covered without anybody remembering to
come back here.
"""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

KEY = "test-admin-key"


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    """
    The app, with everything an admin route would actually DO replaced.

    Only the guard is under test. Left alone, a request that gets past it runs
    the thing it guards — the first version of this file spent a minute
    crawling NSE and downloading AMC workbooks on every run, which is a poor
    way to check an if-statement and a worse thing to point at an exchange
    from CI.

    EVERYTHING IS PUT BACK, AND PUT BACK EVEN WHEN SETUP FAILS. `main` is a
    module the whole suite shares, and the first version of this fixture set
    two environment variables, re-imported main, and left four of its
    attributes stubbed — which passed here and broke five tests in
    test_scan_memory_guard.py, a file that has nothing to do with admin keys
    and only fails when this one has run first. A test that leaves the process
    different from how it found it is a test that breaks its neighbours.

    That restore then sat after the yield, where it is skipped entirely if
    anything above the yield raises — so the fixture kept the exact leak its
    own docstring warns about, waiting for a setup failure to spring it. One
    duly arrived: TestClient needs httpx, CI did not install it, and the
    ImportError landed after the environment had been rewritten and main
    evicted. The five scan-memory-guard tests imported a main carrying this
    file's ADMIN_KEY and got 401 from a function they call directly, so a
    missing test dependency reported itself as ten failures, five of them in
    a file that does not import this one. The restore is in a finally now,
    and nothing global is touched until the import that can fail has.
    """
    # Before anything global is touched: this is the import that raises when
    # httpx is absent, and it must not take the environment down with it.
    from fastapi.testclient import TestClient

    tmp = tmp_path_factory.mktemp("admin")
    saved_env = {k: os.environ.get(k)
                 for k in ("ADMIN_KEY", "ALTAHA_HOLDINGS_DB")}
    saved_modules = {k: sys.modules.get(k) for k in ("main", "holdings_store")}
    stubbed = {}
    mod = None

    try:
        os.environ["ADMIN_KEY"] = KEY
        os.environ["ALTAHA_HOLDINGS_DB"] = str(tmp / "h.db")
        for m in ("main", "holdings_store"):
            sys.modules.pop(m, None)
        import main as mod

        class Inert:
            """Answers anything with something harmless, touches no network."""
            def __getattr__(self, _name):
                return lambda *a, **kw: {}

        for name in ("holdings_crawl", "holdings_job", "fund_portfolios",
                     "investors_source", "lens_data_crawl", "lens_job"):
            if getattr(mod, name, None) is not None:
                stubbed[name] = getattr(mod, name)
                setattr(mod, name, Inert())

        yield TestClient(mod.app), mod
    finally:
        if mod is not None:
            for name, original in stubbed.items():
                setattr(mod, name, original)
        for k, v in saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        # The module this test re-imported carries the admin key it was built
        # with. Dropping it means the next importer builds a fresh one from the
        # restored environment rather than inheriting this file's.
        for k, original in saved_modules.items():
            if original is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = original


def _admin_routes(app):
    out = []
    for r in app.routes:
        path = getattr(r, "path", "") or ""
        if not path.startswith("/admin/"):
            continue
        for method in sorted(getattr(r, "methods", set()) or set()):
            if method in ("GET", "POST"):
                out.append((method, path))
    return sorted(set(out))


def test_there_are_admin_routes_to_check(client):
    _c, main = client
    assert len(_admin_routes(main.app)) >= 4


def test_every_admin_route_refuses_a_request_with_no_key(client):
    c, main = client
    for method, path in _admin_routes(main.app):
        r = c.request(method, path)
        assert r.status_code == 401, "%s %s is not guarded at all" % (method, path)


def test_every_admin_route_accepts_the_key_in_the_header(client):
    """
    The failure that motivated this file. A route can bind the header, look
    entirely correct in its signature, and still check only the query string —
    and the difference shows up nowhere except in a scheduled job that sends
    headers.
    """
    c, main = client
    bad = []
    for method, path in _admin_routes(main.app):
        r = c.request(method, path, headers={"X-Admin-Key": KEY})
        if r.status_code == 401:
            bad.append("%s %s" % (method, path))
    assert not bad, (
        "these admin routes ignore X-Admin-Key and accept only ?key= — the "
        "scheduled jobs send the header, so they are unreachable to them: %s"
        % bad)


def test_every_admin_route_still_accepts_the_key_in_the_query(client):
    """The panel and the older callers use it; the header did not replace it."""
    c, main = client
    bad = []
    for method, path in _admin_routes(main.app):
        r = c.request(method, path, params={"key": KEY})
        if r.status_code == 401:
            bad.append("%s %s" % (method, path))
    assert not bad, bad


def test_a_wrong_key_is_refused_however_it_arrives(client):
    c, main = client
    for method, path in _admin_routes(main.app):
        assert c.request(method, path, headers={"X-Admin-Key": "nope"}
                         ).status_code == 401
        assert c.request(method, path, params={"key": "nope"}
                         ).status_code == 401
