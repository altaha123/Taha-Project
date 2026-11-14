"""The closing note to the public Telegram channel: once, only after a real
session, and never yesterday's close under today's date."""
import datetime as dt
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

NOW = dt.datetime(2026, 11, 13, 16, 5, tzinfo=dt.timezone(dt.timedelta(hours=5, minutes=30)))


@pytest.fixture()
def world(monkeypatch, tmp_path):
    import main
    import swr
    swr.forget()
    sent = []
    monkeypatch.setattr(main, "_DAILY_POST_FILE", str(tmp_path / "daily_post.json"))
    monkeypatch.setattr(main.notify, "TG_PUBLIC", "@altaha_test", raising=False)
    monkeypatch.setattr(main.notify, "_post", lambda chat, text: (sent.append((chat, text)) or (True, "sent")))
    state = {"status": "closed", "session": "2026-11-13"}
    monkeypatch.setattr(main, "market_week_route", lambda: {"sessions": [
        {"date": "2026-11-12", "flows": {}}, {"date": state["session"], "flows": {}}]})
    monkeypatch.setattr(main, "daily_route", lambda: {
        "date": "2026-11-13", "day": "13 Nov 2026", "status": state["status"], "headline": "Markets fell",
        "url": "https://altahascreener.in/today",
        "lines": [{"key": "market", "text": "Nifty 50 closed at 25,144, down 0.61%."},
                  {"key": "movers", "text": "M&M <b> gained most."}]})
    yield main, sent, state
    swr.forget()


def test_it_posts_once_and_escapes_what_it_sends(world):
    main, sent, _ = world
    out = main._post_daily(now=NOW)
    assert out == {"sent": True, "why": "sent"}
    chat, text = sent[0]
    assert chat == "@altaha_test"
    assert text.startswith("<b>Markets fell</b> · 13 Nov 2026\n\n• Nifty 50 closed at 25,144, down 0.61%.")
    assert "M&amp;M &lt;b&gt; gained most." in text
    assert text.endswith("https://altahascreener.in/today")
    assert main._post_daily(now=NOW) == {"sent": False, "why": "already posted today"}
    assert len(sent) == 1
    main._post_daily(now=NOW, force=True)
    assert len(sent) == 2


def test_nothing_without_a_channel(world, monkeypatch):
    main, sent, _ = world
    monkeypatch.setattr(main.notify, "TG_PUBLIC", "", raising=False)
    assert main._post_daily(now=NOW)["sent"] is False and not sent


def test_nothing_on_a_holiday_or_before_the_close_is_in(world):
    main, sent, state = world
    state["session"] = "2026-11-12"                   # the record still ends yesterday
    out = main._post_daily(now=NOW)
    assert out["sent"] is False and "no session recorded for today" in out["why"] and not sent


def test_nothing_while_the_market_is_open(world):
    main, sent, state = world
    state["status"] = "open"
    assert main._post_daily(now=NOW) == {"sent": False, "why": "the market is still open"}
    assert not sent


def test_a_failed_send_is_tried_again(world, monkeypatch):
    main, sent, _ = world
    monkeypatch.setattr(main.notify, "_post", lambda chat, text: (False, "HTTP 400: chat not found"))
    assert main._post_daily(now=NOW) == {"sent": False, "why": "HTTP 400: chat not found"}
    assert main._daily_posted_on() is None


def test_a_dry_run_shows_the_text_and_sends_nothing(world):
    main, sent, _ = world
    out = main._post_daily(now=NOW, dry_run=True)
    assert out["sent"] is False and out["text"].startswith("<b>Markets fell</b>") and not sent


def test_the_job_is_guarded(world, monkeypatch):
    from fastapi.testclient import TestClient
    main, sent, _ = world
    monkeypatch.setattr(main, "ADMIN_KEY", "k")
    client = TestClient(main.app)
    assert client.post("/jobs/daily-post").status_code == 403
    assert client.post("/jobs/daily-post", headers={"X-Admin-Key": "k"}, params={"dry_run": "true"}).status_code == 200
