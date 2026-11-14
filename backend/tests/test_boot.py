"""
/boot is the home page's fifteen questions answered in one reply.

What is checked here is what would otherwise go wrong quietly:

  - a key that is not a real route (a typo would simply never be used);
  - a part that differs from what its own route returns;
  - a slow or broken part making the whole reply slow or broken;
  - a failed sector read being kept and shown as an empty market.
"""
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit, parse_qsl

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _settle(swr, seconds=5.0):
    end = time.time() + seconds
    while time.time() < end and swr.stats()["refreshing"]:
        time.sleep(0.02)


@pytest.fixture()
def app_client(monkeypatch):
    from fastapi.testclient import TestClient
    import main
    import swr
    swr.forget()
    monkeypatch.setenv("BOOT_WARM", "0")
    yield main, TestClient(main.app)
    _settle(swr)          # a fill still running would land in the next test
    swr.forget()


def test_every_boot_key_is_a_route_the_page_can_ask_for(app_client):
    main, _ = app_client
    paths = {r.path for r in main.app.routes if "GET" in getattr(r, "methods", ())}
    for key in main._boot_parts():
        assert urlsplit(key).path in paths, key


def test_boot_answers_at_once_when_nothing_is_ready(app_client, monkeypatch):
    main, client = app_client

    def slow():
        time.sleep(2)
        return {"indices": []}
    monkeypatch.setattr(main, "_boot_parts", lambda: {"/market": (slow, 20, 300)})
    t0 = time.time()
    r = client.get("/boot")
    assert r.status_code == 200
    assert time.time() - t0 < 1.0
    assert r.json()["data"] == {}                 # not ready: left out
    assert r.headers["cache-control"] == "no-store"


def test_a_part_is_exactly_what_its_route_returns(app_client, monkeypatch):
    main, client = app_client
    import swr
    sectors = {"window": "1D", "source": "test", "rows": [
        {"sector": "Energy", "change_pct": 1.2, "up": 3, "down": 1, "total": 4,
         "stocks": [{"symbol": "RELIANCE", "change_pct": 1.5, "ltp": 1340.0}]}]}
    monkeypatch.setattr(main.SS, "overview", lambda window, with_stocks=False: dict(sectors))
    monkeypatch.setattr(main, "_market_now",
                        lambda: {"indices": [{"label": "NIFTY 50", "level": 25144.3,
                                              "change": -155.05, "change_pct": -0.61}],
                                 "status": "closed", "ist": "14 Nov 2026, 13:50 IST"})
    keys = ["/market", "/sector/overview?window=1D&stocks=1", "/planner/questions"]
    parts = main._boot_parts()
    monkeypatch.setattr(main, "_boot_parts", lambda: {k: parts[k] for k in keys})

    client.get("/boot")                           # starts the fill
    _settle(swr)
    body = client.get("/boot").json()
    assert sorted(body["data"]) == sorted(keys)
    for key in keys:
        split = urlsplit(key)
        direct = client.get(split.path, params=dict(parse_qsl(split.query)))
        assert direct.status_code == 200, key
        assert body["data"][key] == direct.json(), key
        assert body["age"][key] >= 0


def test_one_broken_part_does_not_break_the_reply(app_client, monkeypatch):
    main, client = app_client
    import swr

    def broken():
        raise RuntimeError("the exchange is not answering")
    monkeypatch.setattr(main, "_boot_parts", lambda: {
        "/market": (broken, 20, 300),
        "/planner/questions": (main.planner_questions, 3600, 3600)})
    client.get("/boot")
    _settle(swr)
    body = client.get("/boot").json()
    assert "/planner/questions" in body["data"]
    assert "/market" not in body["data"]


def test_an_empty_sector_read_is_an_error_and_is_not_kept(app_client, monkeypatch):
    main, client = app_client
    calls = []

    def overview(window, with_stocks=False):
        calls.append(window)
        rows = [] if len(calls) == 1 else [{"sector": "Energy", "change_pct": 0.4}]
        return {"window": window, "rows": rows}
    monkeypatch.setattr(main.SS, "overview", overview)
    assert client.get("/sector/overview?window=1D&stocks=1").status_code == 503
    r = client.get("/sector/overview?window=1D&stocks=1")
    assert r.status_code == 200 and r.json()["rows"][0]["sector"] == "Energy"
    # and the good answer is kept: a third request does not read the market again
    client.get("/sector/overview?window=1D&stocks=1")
    assert len(calls) == 2


def test_the_market_strip_is_read_once_for_many_visitors(app_client, monkeypatch):
    main, client = app_client
    calls = []
    monkeypatch.setattr(main, "_market_now",
                        lambda: calls.append(1) or {"indices": [], "status": "closed", "ist": ""})
    for _ in range(5):
        assert client.get("/market").status_code == 200
    assert len(calls) == 1


def test_the_page_and_the_server_agree_on_what_boot_answers(app_client):
    """frontend/boot.js only uses the keys it lists; the server only fills the
    keys it lists. A key in one and not the other is a request that silently
    goes back to being slow."""
    import re
    main, _ = app_client
    js = (Path(__file__).resolve().parents[2] / "frontend" / "boot.js").read_text()
    block = js[js.index("var KEYS = ["):js.index("];", js.index("var KEYS = ["))]
    page_keys = re.findall(r"'([^']+)'", block)
    assert sorted(page_keys) == sorted(main._boot_parts())


def test_the_daily_summary_is_built_from_the_kept_answers(app_client, monkeypatch):
    main, client = app_client
    monkeypatch.setattr(main, "_market_now", lambda: {
        "indices": [{"label": "NIFTY 50", "level": 25144.3, "change": -155.05, "change_pct": -0.61}],
        "status": "closed", "ist": ""})

    def refuse(*a, **k):
        raise RuntimeError("down")
    monkeypatch.setattr(main.SS, "overview", refuse)
    monkeypatch.setattr(main, "market_week_route", refuse)
    monkeypatch.setattr(main, "results_calendar_view", refuse)
    monkeypatch.setattr(main, "policy_brief_today", refuse)
    r = client.get("/daily")
    assert r.status_code == 200
    body = r.json()
    assert [l["key"] for l in body["lines"]] == ["market"]
    assert body["lines"][0]["text"].startswith("Nifty 50 closed at 25,144, down 0.61%.")


def test_no_summary_is_an_honest_503_and_is_not_kept(app_client, monkeypatch):
    main, client = app_client

    def refuse(*a, **k):
        raise RuntimeError("down")
    for name in ("market", "market_week_route", "results_calendar_view", "policy_brief_today"):
        monkeypatch.setattr(main, name, refuse)
    monkeypatch.setattr(main.SS, "overview", refuse)
    assert client.get("/daily").status_code == 503
    monkeypatch.setattr(main, "market", lambda: {
        "indices": [{"label": "NIFTY 50", "level": 100.0, "change": 1.0, "change_pct": 1.0}],
        "status": "open"})
    assert client.get("/daily").status_code == 200
