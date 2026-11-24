"""
A trading holiday, and the site that said the market was open through it.

On Tuesday 24 November 2026 at 11:16 IST /market answered `status: "open"`.
NSE was shut for Guru Nanak Jayanti: its own holiday list says so, and its
market-status call that morning read "Close" with a trade date of the 23rd.

/market decided by a weekday clock, and was meant to be overruled by Dhan's
market status. Dhan has no such call (the address answers 404), so nothing
ever overruled it. market_calendar reads NSE's list instead. These pin the
list's parsing, that a request never waits for NSE, that a failed read loses
nothing, and each place that now asks the calendar: /market, the watchlist's
open flag, the bar owed for today, and how long a price is cached.
"""
import datetime as dt
import importlib.util
import json
import os
import threading
import time
import types

import pandas as pd
import pytest

import market_calendar as MC

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
GURPURB = "Prakash Gurpurb Sri Guru Nanak Dev"
READ_IN_BACKGROUND = MC._refresh_in_background

# NSE's reply, cut to four of the year's rows and two of its twelve segments.
NSE_REPLY = {
    "CM": [
        {"tradingDate": "26-Jan-2026", "weekDay": "Monday", "description": "Republic Day",
         "morning_session": None, "evening_session": None, "Sr_no": 2},
        {"tradingDate": "08-Nov-2026", "weekDay": "Sunday", "description": "Diwali Laxmi Pujan*",
         "morning_session": None, "evening_session": None, "Sr_no": 17},
        {"tradingDate": "24-Nov-2026", "weekDay": "Tuesday", "description": GURPURB,
         "morning_session": None, "evening_session": None, "Sr_no": 19},
        {"tradingDate": "25-Dec-2026", "weekDay": "Friday", "description": "Christmas",
         "morning_session": None, "evening_session": None, "Sr_no": 20},
    ],
    "CD": [
        {"tradingDate": "19-Feb-2026", "weekDay": "Thursday",
         "description": "Chhatrapati Shivaji Maharaj Jayanti",
         "morning_session": None, "evening_session": None, "Sr_no": 3},
    ],
}


def at(day, hour, minute=0, month=11):
    return dt.datetime(2026, month, day, hour, minute, tzinfo=IST)


@pytest.fixture
def cal(tmp_path, monkeypatch):
    """A calendar with its own file, nothing read yet, and an NSE that is not
    called unless the test says what it answers."""
    monkeypatch.setattr(MC, "_PATH", str(tmp_path / "nse_holidays.json"))
    MC._state.update(days={}, at=0.0, loaded=False, retry_at=0.0)
    monkeypatch.setattr(MC, "_fetch", lambda: pytest.fail("NSE was asked"))
    monkeypatch.setattr(MC, "_refresh_in_background", lambda: None)
    return MC


@pytest.fixture
def gurpurb(monkeypatch):
    monkeypatch.setitem(MC._state, "days", {"2026-11-24": GURPURB})


# ── The list ────────────────────────────────────────────────────────────────

def test_the_equity_segments_days_are_read_and_no_other_segments():
    days = MC.parse(NSE_REPLY)
    assert days == {"2026-01-26": "Republic Day", "2026-11-08": "Diwali Laxmi Pujan*",
                    "2026-11-24": GURPURB, "2026-12-25": "Christmas"}
    assert "2026-02-19" not in days                       # a currency-segment holiday


@pytest.mark.parametrize("refusal", [None, {}, [], "Access Denied", {"CM": None},
                                     {"CM": [{"tradingDate": "soon"}, "junk", None]}])
def test_a_refusal_is_not_a_year_with_no_holidays(refusal):
    assert MC.parse(refusal) == {}


def test_a_read_is_kept_on_the_data_disk_and_survives_a_restart(cal, monkeypatch):
    monkeypatch.setattr(cal, "_fetch", lambda: MC.parse(NSE_REPLY))
    assert cal.refresh() is True
    assert cal.holiday(dt.date(2026, 11, 24)) == GURPURB

    cal._state.update(days={}, at=0.0, loaded=False)      # a new process
    monkeypatch.setattr(cal, "_fetch", lambda: pytest.fail("the disk had it"))
    assert cal.holiday(dt.date(2026, 11, 24)) == GURPURB
    with open(cal._PATH) as fh:
        assert json.load(fh)["days"]["2026-12-25"] == "Christmas"


def test_a_failed_read_keeps_what_was_held_and_waits_before_asking_again(cal, monkeypatch):
    monkeypatch.setattr(cal, "_fetch", lambda: MC.parse(NSE_REPLY))
    cal.refresh()

    def refused():
        raise RuntimeError("403")
    monkeypatch.setattr(cal, "_fetch", refused)
    assert cal.refresh() is False
    assert cal.holiday(dt.date(2026, 11, 24)) == GURPURB
    assert cal._state["retry_at"] > 0


def test_a_holiday_the_exchange_withdraws_is_withdrawn(cal, monkeypatch):
    monkeypatch.setattr(cal, "_fetch", lambda: {"2025-12-25": "Christmas",
                                                "2026-03-20": "A holiday later moved"})
    cal.refresh()
    monkeypatch.setattr(cal, "_fetch", lambda: MC.parse(NSE_REPLY))    # 2026, re-read
    cal.refresh()
    assert cal.holiday(dt.date(2026, 3, 20)) is None
    assert cal.holiday(dt.date(2025, 12, 25)) == "Christmas"           # last year's stays


def test_a_request_never_waits_for_nse(cal, monkeypatch):
    """Nothing held and nothing on disk: the answer is "not a holiday" at
    once, and the list is fetched on another thread."""
    started = []
    monkeypatch.setattr(cal, "_refresh_in_background", lambda: started.append(1))
    assert cal.holiday(dt.date(2026, 11, 24)) is None
    assert started == [1]

    cal._state.update(days={"2026-11-24": GURPURB}, at=time.time())
    assert cal.holiday(dt.date(2026, 11, 24)) == GURPURB
    assert started == [1]                                 # fresh: not asked again


def test_the_background_read_fills_the_list(cal, monkeypatch):
    asked, answer = threading.Event(), threading.Event()

    def fetch():
        asked.set()
        answer.wait(5)
        return MC.parse(NSE_REPLY)
    monkeypatch.setattr(cal, "_fetch", fetch)
    monkeypatch.setattr(cal, "_refresh_in_background", READ_IN_BACKGROUND)

    assert cal.holiday(dt.date(2026, 11, 24)) is None     # answered while NSE is still out
    assert asked.wait(5)
    cal.holiday(dt.date(2026, 11, 24))                    # a second caller starts no second read
    answer.set()
    assert cal._busy.acquire(timeout=5)                   # the read has finished
    cal._busy.release()
    assert cal.holiday(dt.date(2026, 11, 24)) == GURPURB
    assert os.path.exists(cal._PATH)


# ── The session ─────────────────────────────────────────────────────────────

def test_the_holiday_is_closed_all_day_and_says_why(gurpurb):
    for hour, minute in [(8, 0), (9, 15), (11, 16), (15, 29), (20, 0)]:
        assert MC.session(at(24, hour, minute)) == ("closed", GURPURB)
    assert MC.trading_day(dt.date(2026, 11, 24)) is False


def test_the_days_either_side_trade_as_usual(gurpurb):
    assert MC.session(at(23, 11, 16)) == ("open", None)
    assert MC.session(at(25, 9, 14)) == ("pre", None)
    assert MC.session(at(25, 9, 15)) == ("open", None)
    assert MC.session(at(25, 15, 30)) == ("closed", None)
    assert MC.trading_day(dt.date(2026, 11, 25)) is True


def test_a_weekend_is_closed_without_a_holidays_name(gurpurb):
    assert MC.session(at(28, 11, 0)) == ("closed", None)
    assert MC.trading_day(dt.date(2026, 11, 28)) is False


def test_without_the_list_a_weekday_is_a_trading_day():
    """What the clock always assumed. A day is a holiday only on NSE's word."""
    assert MC.session(at(24, 11, 16)) == ("open", None)


def test_the_session_is_read_in_india_whatever_zone_the_time_arrives_in(gurpurb):
    utc = dt.datetime(2026, 11, 23, 18, 45, tzinfo=dt.timezone.utc)    # 00:15 IST on the 24th
    assert MC.session(utc) == ("closed", GURPURB)


# ── Everything that now asks ────────────────────────────────────────────────

@pytest.fixture(scope="module")
def main_mod():
    import main
    return main


def test_market_says_closed_on_the_holiday_and_names_it(main_mod, gurpurb, monkeypatch):
    monkeypatch.setattr(main_mod, "resolve", lambda sym: (_ for _ in ()).throw(RuntimeError()))
    monkeypatch.setattr(MC, "now", lambda: at(24, 11, 16))
    out = main_mod.market()
    assert out["status"] == "closed" and out["holiday"] == GURPURB
    assert out["ist"] == "24 Nov 2026, 11:16 IST"


def test_market_says_open_on_a_trading_morning(main_mod, gurpurb, monkeypatch):
    monkeypatch.setattr(main_mod, "resolve", lambda sym: (_ for _ in ()).throw(RuntimeError()))
    monkeypatch.setattr(MC, "now", lambda: at(25, 11, 16))
    out = main_mod.market()
    assert out["status"] == "open" and out["holiday"] is None


def test_market_no_longer_asks_dhan_for_a_status_it_does_not_have(main_mod):
    with open(os.path.join(BACKEND, "dhan_source.py")) as fh:
        assert "marketstatus" not in fh.read()
    with open(os.path.join(BACKEND, "main.py")) as fh:
        assert "market_status" not in fh.read()


def test_datasource_says_what_the_calendar_holds(main_mod, gurpurb):
    out = main_mod.datasource()
    assert out["calendar"]["holidays"] == 1 and out["calendar"]["read_at"] is None


def test_the_watchlist_does_not_call_the_holiday_open(gurpurb):
    import watchlist_quotes as W
    assert W.market_open(at(23, 11, 16)) is True
    assert W.market_open(at(24, 11, 16)) is False
    assert W._ttl(at(24, 11, 16)) == W.TTL_SHUT


def _load(name, file):
    spec = importlib.util.spec_from_file_location(name, os.path.join(BACKEND, file))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_no_bar_is_owed_for_a_holiday(gurpurb, monkeypatch, tmp_path):
    """The quote on a holiday is the last session's. A bar built from it would
    be Monday again under Tuesday's date, and a day's move of exactly zero."""
    d = _load("dhan_source_holiday", "dhan_source.py")

    class Clock(dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return at(24, 13, 0)
    monkeypatch.setattr(d, "dt", types.SimpleNamespace(
        datetime=Clock, date=dt.date, timedelta=dt.timedelta, timezone=dt.timezone))
    monkeypatch.setattr(d, "bulk_quotes", lambda *a, **k: pytest.fail("no quote on a holiday"))

    idx = pd.bdate_range(end="2026-11-23", periods=80)
    closes = [1377.5] * 79 + [1351.0]
    through_monday = pd.DataFrame({"Open": closes, "High": closes, "Low": closes,
                                   "Close": closes, "Volume": [1_000_000] * 80}, index=idx)
    df = d._append_today("RELIANCE", through_monday)
    assert df.index[-1] == pd.Timestamp("2026-11-23")
    assert "today_missing" not in df.attrs                # so it is cached for half an hour


def test_a_price_is_cached_for_half_an_hour_on_a_holiday(gurpurb):
    ds = _load("data_source_holiday", "data_source.py")
    assert ds._px_ttl(at(23, 11, 0)) == ds.SESSION_TTL    # Monday, mid-session
    assert ds._px_ttl(at(24, 11, 0)) == ds._TTL           # the holiday
    assert ds._px_ttl(at(24, 9, 10)) == ds._TTL           # no open to stop short of
