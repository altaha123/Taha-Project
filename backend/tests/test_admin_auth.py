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
    way to check an if-statement and a worse thing to point at an exchange from
    CI.
    """
    tmp = tmp_path_factory.mktemp("admin")
    os.environ["ADMIN_KEY"] = KEY
    os.environ["ALTAHA_HOLDINGS_DB"] = str(tmp / "h.db")
    for m in ("main", "holdings_store"):
        sys.modules.pop(m, None)
    from fastapi.testclient import TestClient
    import main

    class Inert:
        """Answers anything with something harmless and touches no network."""
        def __getattr__(self, _name):
            return lambda *a, **kw: {}

    for name in ("holdings_crawl", "holdings_job", "fund_portfolios",
                 "investors_source"):
        if getattr(main, name, None) is not None:
            setattr(main, name, Inert())
    return TestClient(main.app), main


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
