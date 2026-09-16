"""
The NSE transport.

Worth its own tests because the failure it exists to prevent is silent: a call
that returns nothing reads downstream as a company with no filings, not as a
network that refused us. Every path here must end in either rows or None —
never an empty list dressed up as an answer.
"""

import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import nse_http  # noqa: E402


class FakeResponse:
    def __init__(self, status=200, body=None, text=""):
        self.status_code = status
        self._body = body
        self.text = text

    def json(self):
        if self._body is None:
            raise ValueError("not json")
        return self._body


class FakeSession:
    """Answers with a scripted sequence, and records what it was asked."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def get(self, url, **kw):
        self.calls.append((url, kw))
        nxt = self.script.pop(0) if self.script else FakeResponse(200, [])
        if isinstance(nxt, Exception):
            raise nxt
        return nxt


@pytest.fixture(autouse=True)
def _clean_state(monkeypatch):
    """Sessions are cached per referer for the life of the process."""
    monkeypatch.setattr(nse_http, "_sessions", {})
    monkeypatch.setattr(nse_http, "BACKOFF", 0.0)   # no real sleeping
    yield


def _install(monkeypatch, script):
    fake = FakeSession(script)
    monkeypatch.setattr(nse_http, "session", lambda referer=nse_http.NSE_HOME: fake)
    monkeypatch.setattr(nse_http, "warm", lambda referer=nse_http.NSE_HOME, force=False: None)
    return fake


# ---------------------------------------------------------------------------
# rows()
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("body,want", [
    ([1, 2], [1, 2]),
    ({"data": [1]}, [1]),
    ({"resultBody": [1, 2]}, [1, 2]),
    ({"records": []}, []),
    ({"nothing": [1]}, []),
    (None, []),
    ("a string", []),
])
def test_rows_finds_the_list_whatever_key_it_arrived_under(body, want):
    assert nse_http.rows(body) == want


# ---------------------------------------------------------------------------
# get()
# ---------------------------------------------------------------------------

def test_a_200_is_returned_as_is(monkeypatch):
    fake = _install(monkeypatch, [FakeResponse(200, [{"a": 1}])])
    r = nse_http.get("https://nse.test/api")
    assert r is not None and r.status_code == 200
    assert len(fake.calls) == 1


def test_a_refusal_is_retried_once_the_cookie_has_been_refreshed(monkeypatch):
    """403 from NSE is usually a stale cookie or a burst limit, and the
    identical call seconds later is answered in full."""
    fake = _install(monkeypatch, [FakeResponse(403), FakeResponse(200, [{"a": 1}])])
    warmed = []
    monkeypatch.setattr(nse_http, "warm",
                        lambda referer=nse_http.NSE_HOME, force=False: warmed.append(force))
    r = nse_http.get("https://nse.test/api")
    assert r is not None and r.status_code == 200
    assert True in warmed, "the session must be re-warmed before the retry"


@pytest.mark.parametrize("status", [401, 403, 429])
def test_retries_are_bounded(monkeypatch, status):
    """A retry loop against a rate limiter earns a longer ban, and the caller
    gets None rather than a wait that outlives a page load."""
    fake = _install(monkeypatch, [FakeResponse(status)] * 10)
    assert nse_http.get("https://nse.test/api") is None
    assert len(fake.calls) == nse_http.RETRIES + 1


def test_a_status_that_will_not_improve_is_not_retried(monkeypatch):
    fake = _install(monkeypatch, [FakeResponse(404), FakeResponse(200, [])])
    assert nse_http.get("https://nse.test/api") is None
    assert len(fake.calls) == 1, "404 is an answer, not a refusal"


def test_a_transport_error_is_retried_then_given_up_on(monkeypatch):
    fake = _install(monkeypatch, [OSError("reset")] * 10)
    assert nse_http.get("https://nse.test/api") is None
    assert len(fake.calls) == nse_http.RETRIES + 1


def test_a_transport_error_that_clears_is_not_a_failure(monkeypatch):
    _install(monkeypatch, [OSError("reset"), FakeResponse(200, [{"a": 1}])])
    assert nse_http.get("https://nse.test/api") is not None


def test_the_referer_is_sent_because_nse_checks_it(monkeypatch):
    fake = _install(monkeypatch, [FakeResponse(200, [])])
    nse_http.get("https://nse.test/api", referer="https://nse.test/page")
    assert fake.calls[0][1]["headers"]["Referer"] == "https://nse.test/page"


def test_without_curl_cffi_the_answer_is_none_not_an_empty_list(monkeypatch):
    """The distinction the whole module turns on: "we could not ask" must not
    reach a caller looking like "the company has filed nothing"."""
    monkeypatch.setattr(nse_http, "_curl", lambda: None)
    assert nse_http.available() is False
    assert nse_http.session() is None
    assert nse_http.get("https://nse.test/api") is None
    assert nse_http.get_json("https://nse.test/api") is None


# ---------------------------------------------------------------------------
# get_json()
# ---------------------------------------------------------------------------

def test_get_json_returns_the_body(monkeypatch):
    _install(monkeypatch, [FakeResponse(200, {"data": [1, 2]})])
    assert nse_http.get_json("https://nse.test/api") == {"data": [1, 2]}


def test_a_body_that_is_not_json_is_none_not_a_crash(monkeypatch):
    _install(monkeypatch, [FakeResponse(200, None, text="<html>blocked</html>")])
    assert nse_http.get_json("https://nse.test/api") is None


# ---------------------------------------------------------------------------
# warm() / session()
# ---------------------------------------------------------------------------

def test_warming_is_skipped_inside_its_ttl(monkeypatch):
    fake = FakeSession([FakeResponse(200)] * 20)
    monkeypatch.setattr(nse_http, "session", lambda referer=nse_http.NSE_HOME: fake)
    nse_http.warm("https://nse.test/page")
    first = len(fake.calls)
    assert first >= 1, "a cold session must collect cookies"
    nse_http.warm("https://nse.test/page")
    assert len(fake.calls) == first, "a warm session must not re-fetch"
    nse_http.warm("https://nse.test/page", force=True)
    assert len(fake.calls) > first, "force must re-fetch"


def test_a_session_is_built_once_per_referer(monkeypatch):
    built = []

    class Fake:
        def __init__(self, **kw):
            built.append(kw)

    mod = types.SimpleNamespace(Session=Fake)
    monkeypatch.setattr(nse_http, "_curl", lambda: mod)
    a1 = nse_http.session("https://nse.test/one")
    a2 = nse_http.session("https://nse.test/one")
    b = nse_http.session("https://nse.test/two")
    assert a1 is a2 and a1 is not b
    assert len(built) == 2
    # The whole point: a real Chrome TLS handshake, not a header string.
    assert all(k.get("impersonate") == "chrome" for k in built)
