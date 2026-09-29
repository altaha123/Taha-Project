"""
Pro: the waitlist, saved screens, and the watchlist in the daily email.

The waitlist is the only public form here that writes a row per request, and
it holds addresses — so the tests are about the ways a form like that goes
wrong: a second join that counts twice, a flood from one address, a listing
of everyone's email left open because nobody set a key.

Saved screens belong to one person; the tests make sure they stay that way.

The watchlist section earns its place in an inbox only when something
happened, so the tests pin what counts as something.
"""
import os
import tempfile
import types

import numpy as np
import pandas as pd
import pytest

import accounts as A
from conftest import ohlcv, ramp


@pytest.fixture(autouse=True)
def fresh_db():
    with tempfile.TemporaryDirectory() as d:
        A.reset_for_tests(os.path.join(d, "accounts.db"))
        yield
        A.reset_for_tests(os.path.join(d, "accounts.db"))


def login(email="reader@example.com"):
    done = A.complete_login(A.start_login(email)["token"])
    return done["session"], A.user_for_session(done["session"])


@pytest.fixture(scope="module")
def main_mod():
    import main
    return main


def req(ip="203.0.113.7"):
    return types.SimpleNamespace(headers={"x-forwarded-for": ip}, client=None)


# ── Saved screens ─────────────────────────────────────────────────────────

def test_a_screen_saves_updates_by_name_and_lists_newest_first():
    _, u = login()
    A.save_screen(u["id"], "Cheap compounders", "roce > 20 and pe < 15")
    A.save_screen(u["id"], "Debt free", "debt_equity < 0.1")
    again = A.save_screen(u["id"], "  Cheap   compounders ", "roce > 25 and pe < 15")
    screens = A.list_screens(u["id"])
    assert [s["name"] for s in screens] == ["Cheap compounders", "Debt free"]
    assert again["query"] == "roce > 25 and pe < 15"
    assert len(screens) == 2, "same name updates, never duplicates"


@pytest.mark.parametrize("name,query,why", [
    ("", "pe < 10", "name"), ("x" * 61, "pe < 10", "60"), ("Fine", "", "no query"),
    ("Fine", "x" * 2001, "2000"),
])
def test_a_bad_screen_is_refused_with_a_reason(name, query, why):
    _, u = login()
    with pytest.raises(ValueError, match=why):
        A.save_screen(u["id"], name, query)


def test_the_screen_limit_holds_but_updating_an_existing_one_does_not_count():
    _, u = login()
    for i in range(A.MAX_SCREENS):
        A.save_screen(u["id"], f"S{i}", "pe < 10")
    with pytest.raises(ValueError, match="delete one"):
        A.save_screen(u["id"], "One too many", "pe < 10")
    A.save_screen(u["id"], "S3", "pe < 12")          # an update still works


def test_screens_belong_to_one_person(main_mod):
    tok_a, ua = login("a@example.com")
    tok_b, ub = login("b@example.com")
    saved = main_mod.save_my_screen({"name": "Mine", "query": "pe < 10"}, authorization="Bearer " + tok_a)
    sid = saved["screen"]["id"]
    assert main_mod.my_screens(authorization="Bearer " + tok_b)["screens"] == []
    with pytest.raises(Exception) as e:
        main_mod.delete_my_screen(sid, authorization="Bearer " + tok_b)
    assert getattr(e.value, "status_code", None) == 404
    assert len(main_mod.my_screens(authorization="Bearer " + tok_a)["screens"]) == 1
    with pytest.raises(Exception) as e:
        main_mod.my_screens(authorization=None)
    assert getattr(e.value, "status_code", None) == 401


def test_a_bad_screen_is_a_400_not_a_500(main_mod):
    tok, _ = login()
    with pytest.raises(Exception) as e:
        main_mod.save_my_screen({"name": "", "query": "pe < 10"}, authorization="Bearer " + tok)
    assert getattr(e.value, "status_code", None) == 400


# ── The waitlist ──────────────────────────────────────────────────────────

def test_joining_twice_is_one_row_and_keeps_the_first_source():
    assert A.join_waitlist("Reader@Example.com", source="story_end", plan="annual") == {"joined": True, "already": False}
    assert A.join_waitlist("reader@example.com", source="pricing", plan="monthly")["already"] is True
    s = A.waitlist_summary()
    assert s["count"] == 1
    assert s["by_source"] == {"story_end": 1} and s["by_plan"] == {"annual": 1}


def test_the_waitlist_refuses_a_bad_address_and_cleans_what_it_stores():
    with pytest.raises(ValueError):
        A.join_waitlist("not an email")
    A.join_waitlist("x@example.com", source="<script>alert(1)</script>", plan="lifetime")
    row = A.waitlist_summary()["people"][0]
    assert row["source"] == "scriptalert1script" and row["plan"] == "unknown"


def test_signed_in_joins_use_the_account_address(main_mod):
    tok, u = login("member@example.com")
    out = main_mod.join_pro_waitlist(req(), {"source": "pricing"}, authorization="Bearer " + tok)
    assert out["signed_in"] is True and out["already"] is False
    assert main_mod.my_waitlist_status(authorization="Bearer " + tok) == {"on_waitlist": True}
    assert A.waitlist_summary()["people"][0]["user_id"] == u["id"]


def test_one_visitor_cannot_flood_the_waitlist(main_mod, monkeypatch):
    monkeypatch.setattr(main_mod, "_waitlist_hits", {})
    for i in range(main_mod.WAITLIST_PER_HOUR):
        main_mod.join_pro_waitlist(req("198.51.100.9"), {"email": f"p{i}@example.com"})
    with pytest.raises(Exception) as e:
        main_mod.join_pro_waitlist(req("198.51.100.9"), {"email": "one.more@example.com"})
    assert getattr(e.value, "status_code", None) == 429
    # Somebody else is unaffected.
    assert main_mod.join_pro_waitlist(req("198.51.100.10"), {"email": "other@example.com"})["joined"]


def test_the_address_list_is_closed_without_an_admin_key(main_mod, monkeypatch):
    A.join_waitlist("private@example.com")
    monkeypatch.setattr(main_mod, "ADMIN_KEY", "")
    with pytest.raises(Exception) as e:
        main_mod.admin_pro_waitlist(key="")
    assert getattr(e.value, "status_code", None) == 401
    monkeypatch.setattr(main_mod, "ADMIN_KEY", "s3cret")
    with pytest.raises(Exception):
        main_mod.admin_pro_waitlist(key="wrong")
    assert main_mod.admin_pro_waitlist(x_admin_key="s3cret")["count"] == 1


# ── The watchlist in the daily email ──────────────────────────────────────

def _resolver(moves):
    """resolve() over synthetic frames; counts calls per symbol."""
    calls = {}

    def resolve(sym):
        calls[sym] = calls.get(sym, 0) + 1
        closes = ramp(100, 120, 260)
        closes[-1] = closes[-2] * (1 + moves.get(sym, 0.0))
        return sym + ".NS", None, ohlcv(closes)
    return resolve, calls


def test_only_watched_stocks_that_did_something_are_mentioned():
    import digest as D
    resolve, calls = _resolver({"INFY": 0.045, "TCS": 0.004, "ITC": -0.036, "HDFCBANK": 0.05})
    filings = {"TCS": [{"category": "Results", "importance": "high", "headline": "Q2 results", "pdf": "https://x/t.pdf"}]}
    d = D.build_digest([{"symbol": "HDFCBANK", "qty": 10}], resolve=resolve,
                       filings_for=lambda s: filings.get(s, []),
                       watchlist=["INFY", "TCS", "ITC", "WIPRO", "HDFCBANK"])
    names = [w["symbol"] for w in d["watchlist"]]
    assert names[0] == "TCS", "a filing comes first"
    assert set(names) == {"TCS", "INFY", "ITC"}, "WIPRO moved under 3% with no filing; HDFCBANK is held"
    assert d["watchlist"][0]["filing"]["headline"] == "Q2 results"
    assert calls["HDFCBANK"] == 1, "a stock both held and watched is fetched once"


def test_the_watchlist_reaches_the_email_and_counts_as_news():
    import digest as D
    import email_render as E
    resolve, _ = _resolver({"INFY": 0.06})
    d = D.build_digest([{"symbol": "HDFCBANK", "qty": 1}], resolve=resolve, watchlist=["INFY"])
    html, text = E.render_html(d), E.render_text(d)
    assert "On your watchlist" in html and "INFY" in html
    assert "ON YOUR WATCHLIST" in text and "INFY" in text
    quiet = dict(d, events=[], observations=[], totals=dict(d["totals"], day_change_pct=0.0))
    assert D.is_worth_sending(quiet, min_move_pct=1.0), "a watchlist item alone earns the email"
    assert not D.is_worth_sending(dict(quiet, watchlist=[]), min_move_pct=1.0)


def test_no_watchlist_changes_nothing():
    import digest as D
    resolve, _ = _resolver({})
    d = D.build_digest([{"symbol": "HDFCBANK", "qty": 1}], resolve=resolve)
    assert d["watchlist"] == []
