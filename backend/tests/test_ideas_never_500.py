"""
/ideas must never answer with a bare 500, and a 500 must never be invisible.

Both halves of this were live at once and produced the same symptom: "Engine
unreachable — it may be waking from sleep" on the Ideas tab, while the ticker
strip on the same page kept updating and /scan/status answered instantly in
another tab. The engine was up the whole time.

  1. select() raised, so /ideas returned 500.

  2. Starlette's ServerErrorMiddleware sits OUTSIDE the CORS middleware, so
     that 500 carried no Access-Control-Allow-Origin header. The browser
     refused to hand the response to the page, fetch() rejected, and the only
     thing the tab could truthfully report was that it could not reach
     anything.

The second one is the expensive bug. It turns every future server-side error
into a connectivity report — a wrong answer that sends you looking in the
wrong place, and did.

No TestClient here: it needs httpx, which this suite deliberately does not
depend on. The routes are plain functions and the handler is a coroutine, so
both are called directly.
"""
import asyncio
import types

import pytest


@pytest.fixture
def with_payload():
    """A scan on the server, so /ideas gets as far as scoring it."""
    import main
    before = main._state["payload"]
    main._state["payload"] = {"scanned_at": "31 Aug 2026, 04:31", "rankings": []}
    yield main
    main._state["payload"] = before


def test_a_crash_in_scoring_is_not_a_500(with_payload, monkeypatch):
    main = with_payload

    def explode(*a, **k):
        raise KeyError("setup_fit")

    monkeypatch.setattr(main.ideas_engine, "select", explode)
    out = main.ideas(horizon="short", limit=15)
    assert out["available"] is False
    assert "KeyError" in out["error"]
    # The scan is not lost, and the answer has to say so rather than reading
    # like the ranking went missing.
    assert out["scanned_at"] == "31 Aug 2026, 04:31"
    assert "not a lost scan" in out["message"]


def test_a_bad_horizon_is_still_a_400(with_payload, monkeypatch):
    """Failing soft must not swallow a genuine client error."""
    from fastapi import HTTPException

    main = with_payload

    def bad_input(*a, **k):
        raise ValueError("horizon must be 'short' or 'medium'")

    monkeypatch.setattr(main.ideas_engine, "select", bad_input)
    with pytest.raises(HTTPException) as e:
        main.ideas(horizon="weekly")
    assert e.value.status_code == 400


def _fake_request(path="/scan/status"):
    return types.SimpleNamespace(method="GET",
                                 url=types.SimpleNamespace(path=path))


def test_an_unhandled_500_carries_cors():
    """
    The header is the whole point. Without it the browser converts a server
    error into a network error, and the page can only say it reached nothing.
    """
    import main

    resp = asyncio.run(main._unhandled_error(_fake_request(), RuntimeError("boom")))
    assert resp.status_code == 500
    assert resp.headers.get("access-control-allow-origin") == "*"


def test_the_500_body_names_the_error_and_the_path():
    import main
    import json

    resp = asyncio.run(main._unhandled_error(_fake_request("/ideas"),
                                             KeyError("setup_fit")))
    body = json.loads(bytes(resp.body).decode())
    assert body["error"] == "KeyError"
    assert body["path"] == "/ideas"
    # The one sentence that would have saved the search.
    assert "not a connectivity problem" in body["note"]


def test_a_broken_tracker_ledger_does_not_take_the_tab_down(monkeypatch):
    """
    expectancy_detail() and tracked_symbols() were the only calls in select()
    with no guard, while every feed around them already failed soft.
    """
    import ideas

    def corrupt(*a, **k):
        raise ValueError("ledger corrupt")

    monkeypatch.setattr(ideas.tracker, "expectancy_detail", corrupt)
    monkeypatch.setattr(ideas.tracker, "tracked_symbols", corrupt)
    out = ideas.select({"scanned_at": "31 Aug 2026, 04:31", "rankings": []},
                       horizon="short", limit=15)
    assert out["available"] is True


# --- an old list's name never lands on an error ------------------------------------
#
# This week and momentum were folded into the month and long-term lists in
# December 2026. Every link, bookmark and share card made before then still
# asks for them by name, on /ideas, on its CSV export and on the share card
# and page. Each must open the list that replaced it: a 404 or a 500 there is
# a dead link on someone else's page.

@pytest.fixture
def ranked_scan(monkeypatch, tmp_path):
    """A scan carrying the engine's own ranks, on the server; the feeds and
    the call log kept local."""
    import call_log
    import ideas
    import leaders
    import main
    from test_leaders import market, scan_payload
    monkeypatch.setattr(ideas, "sector_outlook", lambda: {})
    monkeypatch.setattr(ideas, "market_regime", lambda: None)
    monkeypatch.setattr(ideas, "_news_index", lambda hours: ({}, []))
    monkeypatch.setattr(ideas, "_filing_for", lambda sym, hours, cats: None)
    monkeypatch.setattr(ideas, "tracker", None)
    monkeypatch.setattr(call_log, "DB_PATH", str(tmp_path / "calls.db"))
    cands, sectors, snaps = market(120, 10)
    monkeypatch.setitem(main._state, "payload", scan_payload(leaders.rank(cands, sectors=sectors, snapshot=snaps)))
    return main


@pytest.mark.parametrize("old,new", [("week", "month"), ("trade", "month"), ("momentum", "long"),
                                     ("position", "long"), ("medium", "long"), ("invest", "long")])
def test_an_old_list_name_opens_the_list_that_replaced_it_on_every_route(ranked_scan, old, new):
    import json
    import leaders
    main = ranked_scan
    out = main.ideas(horizon=old)
    assert out["available"] is True and out["list"] == new and out["rows"]
    json.dumps(out)
    export = main.ideas_export(horizon=old)
    assert export.status_code == 200 and f"altaha-ideas-{new}.csv" in export.headers["content-disposition"]
    assert export.body.decode().splitlines()[0].startswith("symbol,name,sector")
    sym = out["rows"][0]["symbol"]
    assert main._idea_row(sym, old)["list"] == new
    card = main.og_idea(ticker=sym, horizon=old)
    assert card.status_code == 200 and card.media_type == "image/png"
    page = main.share_idea(sym, horizon=old)
    assert page.status_code == 200 and leaders.LISTS[new]["label"] in page.body.decode()


def test_a_name_no_list_ever_had_is_the_callers_error_and_never_a_500(ranked_scan):
    from fastapi import HTTPException
    main = ranked_scan
    for route in (main.ideas, main.ideas_export):
        with pytest.raises(HTTPException) as e:
            route(horizon="fortnight")
        assert e.value.status_code == 400 and "month" in e.value.detail
    assert main.share_idea("ACME", horizon="fortnight").status_code == 200
