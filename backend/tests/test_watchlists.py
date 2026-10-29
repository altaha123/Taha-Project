"""
Named watchlists and the quotes behind them.

The document arrives from a browser, so every field in it is checked here as
if a stranger wrote it: names with control characters, a thousand lists, ids
that collide, prices that are not numbers. The quotes have the opposite
failure to guard against — a 100-name list turning one request into a
two-minute download on a 512 MB instance.
"""
import datetime as dt
import os
import re
import tempfile

import pandas as pd
import pytest

import accounts as A


@pytest.fixture(autouse=True)
def fresh_db():
    with tempfile.TemporaryDirectory() as d:
        A.reset_for_tests(os.path.join(d, "accounts.db"))
        yield
        A.reset_for_tests(os.path.join(d, "accounts.db"))


def user_id(email="reader@example.com"):
    done = A.complete_login(A.start_login(email)["token"])
    return done["user"]["id"]


def one_list(**over):
    base = {"id": "ev-bets", "name": "EV bets", "emoji": "⚡", "color": "green",
            "symbols": ["TATAMOTORS", "M&M", "exide"], "created": "2026-10-29",
            "added": {"TATAMOTORS": {"at": "2026-10-29", "px": 712.4}}}
    base.update(over)
    return base


# ── The document ─────────────────────────────────────────────────────────────

def test_lists_are_saved_and_read_back_cleaned():
    uid = user_id()
    out = A.save_watchlist_sets(uid, {"main": {"name": "Core", "emoji": "⭐"},
                                      "lists": [one_list()]})
    assert out["rejected"] == []
    back = A.get_watchlist_sets(uid)
    assert back["main"]["name"] == "Core"
    lst = back["lists"][0]
    assert lst["name"] == "EV bets" and lst["color"] == "green"
    assert lst["symbols"] == ["TATAMOTORS", "M&M", "EXIDE"]
    assert lst["added"]["TATAMOTORS"] == {"at": "2026-10-29", "px": 712.4}


def test_names_are_stripped_of_control_characters_and_cut_to_length():
    uid = user_id()
    A.save_watchlist_sets(uid, {"lists": [one_list(name="  Re\x00sults\n week " + "x" * 80)]})
    name = A.get_watchlist_sets(uid)["lists"][0]["name"]
    assert "\x00" not in name and "\n" not in name
    assert name.startswith("Results week")
    assert len(name) <= A.MAX_LIST_NAME


def test_an_empty_name_gets_a_name_and_a_bad_colour_gets_the_default():
    uid = user_id()
    A.save_watchlist_sets(uid, {"lists": [one_list(name="   ", color="url(javascript:1)")]})
    lst = A.get_watchlist_sets(uid)["lists"][0]
    assert lst["name"] == "Untitled list" and lst["color"] == "gold"


def test_duplicate_and_unreadable_ids_are_refused_not_merged():
    uid = user_id()
    out = A.save_watchlist_sets(uid, {"lists": [one_list(), one_list(name="Copy"),
                                                one_list(id="../etc"), one_list(id="main")]})
    assert [l["name"] for l in out["lists"]] == ["EV bets"]
    assert len(out["rejected"]) == 3


def test_the_list_limit_holds():
    uid = user_id()
    lists = [one_list(id=f"l{i}", name=f"List {i}") for i in range(A.MAX_LISTS + 5)]
    out = A.save_watchlist_sets(uid, {"lists": lists})
    assert len(out["lists"]) == A.MAX_LISTS
    assert any("limit" in r["why"] for r in out["rejected"])


def test_added_prices_are_kept_only_for_names_still_listed_and_only_if_numbers():
    uid = user_id()
    A.save_watchlist_sets(uid, {"lists": [one_list(
        symbols=["TCS", "INFY"],
        added={"TCS": {"at": "2026-10-01", "px": "abc"}, "INFY": {"at": "nope", "px": 1},
               "GONE": {"at": "2026-10-01", "px": 5}})]})
    added = A.get_watchlist_sets(uid)["lists"][0]["added"]
    assert added == {"TCS": {"at": "2026-10-01", "px": None}}


def test_one_persons_lists_are_not_anothers():
    a, b = user_id("a@example.com"), user_id("b@example.com")
    A.save_watchlist_sets(a, {"lists": [one_list()]})
    assert A.get_watchlist_sets(b)["lists"] == []


def test_saving_replaces_so_a_deleted_list_stays_deleted():
    uid = user_id()
    A.save_watchlist_sets(uid, {"lists": [one_list(), one_list(id="banks", name="Banks")]})
    A.save_watchlist_sets(uid, {"lists": [one_list(id="banks", name="Banks")]})
    assert [l["id"] for l in A.get_watchlist_sets(uid)["lists"]] == ["banks"]


def test_the_endpoints_need_a_session():
    import main
    from fastapi import HTTPException
    for call in (lambda: main.my_watchlists(authorization=None),
                 lambda: main.save_my_watchlists({"lists": []}, authorization=None)):
        with pytest.raises(HTTPException) as error:
            call()
        assert error.value.status_code == 401


# ── Quotes ──────────────────────────────────────────────────────────────────

def closes(vals, end="2026-10-29"):
    idx = pd.bdate_range(end=end, periods=len(vals))
    return pd.Series(vals, index=idx, dtype=float)


@pytest.fixture
def WQ(monkeypatch):
    import watchlist_quotes as W
    monkeypatch.setattr(W, "_cache", {})
    monkeypatch.setattr(W, "_live", {})
    monkeypatch.setattr(W, "_dhan_overlay", lambda syms: {})
    return W


def test_a_row_carries_the_day_week_month_and_a_sparkline(WQ):
    vals = list(range(100, 130))           # 30 closes, rising by 1
    row = WQ._row_from_closes("ABB", closes(vals))
    assert row["ltp"] == 129 and row["prev_close"] == 128
    assert row["change_pct"] == pytest.approx(0.78, abs=0.01)
    assert row["week_pct"] == pytest.approx(100 * (129 / 124 - 1), abs=0.01)
    assert row["month_pct"] == pytest.approx(100 * (129 / 108 - 1), abs=0.01)
    assert len(row["spark"]) == WQ.SPARK
    assert row["last_date"] == "2026-10-29"
    assert len(row["spark_dates"]) == WQ.SPARK and row["spark_dates"][-1] == "2026-10-29"


def test_only_a_chunk_is_fetched_and_the_rest_is_pending(WQ):
    asked = []

    def fetch(batch):
        asked.append(list(batch))
        return {s: WQ._row_from_closes(s, closes([10, 11])) for s in batch}

    syms = [f"S{i}" for i in range(WQ.CHUNK + 7)]
    out = WQ.quotes(syms, fetch=fetch)
    assert len(asked) == 1 and len(asked[0]) == WQ.CHUNK
    assert out["pending"] == syms[WQ.CHUNK:]
    again = WQ.quotes(syms, fetch=fetch)
    assert asked[1] == syms[WQ.CHUNK:]
    assert again["pending"] == []
    assert all(r["ltp"] == 11 for r in again["rows"])


def test_the_cache_answers_a_second_list_without_a_download(WQ):
    calls = []

    def fetch(batch):
        calls.append(batch)
        return {s: WQ._row_from_closes(s, closes([10, 12])) for s in batch}

    WQ.quotes(["TCS", "INFY"], fetch=fetch)
    WQ.quotes(["INFY", "TCS"], fetch=fetch)
    assert len(calls) == 1


def test_a_name_with_no_data_is_not_pending_for_ever(WQ):
    out = WQ.quotes(["NOPE"], fetch=lambda batch: {})
    assert out["pending"] == []
    assert out["rows"][0]["ltp"] is None


def test_the_scan_fills_score_name_and_a_fallback_price(WQ):
    scan = [{"symbol": "ABB", "name": "ABB India", "sector": "Capital Goods",
             "composite": 74.2, "label": "Strong", "price": 5400.0}]
    out = WQ.quotes(["ABB"], scan_rows=scan, fetch=lambda batch: {})
    r = out["rows"][0]
    assert r["name"] == "ABB India" and r["score"] == 74.2 and r["label"] == "Strong"
    assert r["ltp"] == 5400.0 and r["source"] == "Universe scan price"


def test_symbols_are_cleaned_deduped_and_capped(WQ):
    got = WQ.clean(["tcs", "TCS.NS", "<script>", "M&M"] + [f"X{i}" for i in range(200)])
    assert got[:2] == ["TCS", "M&M"]
    assert len(got) == WQ.MAX_SYMBOLS


def test_market_hours_are_read_in_ist(WQ):
    open_ = dt.datetime(2026, 10, 29, 5, 0, tzinfo=dt.timezone.utc)    # 10:30 IST, Thursday
    shut = dt.datetime(2026, 10, 29, 11, 0, tzinfo=dt.timezone.utc)    # 16:30 IST
    sunday = dt.datetime(2026, 11, 1, 5, 0, tzinfo=dt.timezone.utc)
    assert WQ.market_open(open_) and not WQ.market_open(shut) and not WQ.market_open(sunday)


def test_featured_lists_always_include_the_giants(WQ):
    out = WQ.featured(None, [])
    assert [l["id"] for l in out["lists"]] == ["f-giants"]
    scan = {"rankings": [{"symbol": "abb", "composite": 80}, {"symbol": "tcs", "composite": 60}]}
    out = WQ.featured(scan, [{"symbol": "ABB"}, {"symbol": "ABB"}, {"symbol": "TCS"}])
    ids = [l["id"] for l in out["lists"]]
    assert ids == ["f-calls", "f-top", "f-giants"]
    assert out["lists"][0]["symbols"] == ["ABB", "TCS"]
    assert out["lists"][1]["symbols"] == ["ABB", "TCS"]
