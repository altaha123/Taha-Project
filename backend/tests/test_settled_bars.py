"""
A feed that goes back a session, and the memory that puts it back.

On the night of Monday 23 November 2026 the Nifty's daily history, read from
Yahoo every five minutes, ended on Monday (25,349.65, down 1.75%) until 23:57
IST and on Friday (25,800.60) from 00:02. The price cache held Monday's frame
a few minutes longer; from 00:07 the site served Friday's close and Friday's
+1.12% as the latest session, and did until the morning.

settled_bars.keep() is what every fetched history now passes through. These
pin what it promises: a session the feed has dropped is put back, the feed's
own bar wins the moment it carries that session again, a bar still forming is
never kept, a kept bar is trusted for a few days and no longer, and a restart
in the middle of the gap loses nothing.
"""
import datetime as dt

import pandas as pd
import pytest

import market_calendar
import settled_bars as SB

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
KOLKATA = "Asia/Kolkata"

THU, FRI, MON = "2026-11-19", "2026-11-20", "2026-11-23"
# What the feed said, as observed.
NIFTY = {THU: 25514.30, FRI: 25800.60, MON: 25349.65}


def at(day, hour, minute=0, month=11):
    return dt.datetime(2026, month, day, hour, minute, tzinfo=IST)


def history(last, tz=KOLKATA, quiet=80):
    """A daily frame the way a feed returns one: `quiet` flat sessions, then
    the dated closes in `last`. tz=None is Dhan's shape, a zone is Yahoo's."""
    days = sorted(last)
    before = pd.bdate_range(end=pd.Timestamp(days[0]) - pd.Timedelta(days=1), periods=quiet)
    idx = before.append(pd.DatetimeIndex(days))
    closes = [25000.0] * quiet + [last[d] for d in days]
    frame = pd.DataFrame({"Open": closes, "High": closes, "Low": closes, "Close": closes,
                          "Volume": [300_000] * len(closes)},
                         index=idx.tz_localize(tz) if tz else idx)
    if tz:                                   # Yahoo sends these two as well
        frame["Dividends"], frame["Stock Splits"] = 0.0, 0.0
    frame.index.name = "Date"
    return frame


def through(day, **kw):
    """The Nifty's history ending on `day`."""
    return history({d: c for d, c in NIFTY.items() if d <= day}, **kw)


def last(frame):
    return str(frame.index[-1])[:10], round(float(frame["Close"].iloc[-1]), 2)


# ── The night it was found on ───────────────────────────────────────────────

def test_a_feed_that_goes_back_a_session_is_given_it_back():
    evening = SB.keep("^NSEI", through(MON), now=at(23, 23, 57))
    assert last(evening) == (MON, 25349.65)
    assert "kept_sessions" not in evening.attrs          # nothing was missing

    after_midnight = SB.keep("^NSEI", through(FRI), now=at(24, 0, 7))
    assert last(after_midnight) == (MON, 25349.65)
    assert after_midnight.attrs["kept_sessions"] == [MON]
    # The move is Monday's against Friday's close, not Friday's against Thursday's.
    closes = after_midnight["Close"]
    assert round(100 * (closes.iloc[-1] / closes.iloc[-2] - 1), 2) == -1.75


def test_when_the_feed_catches_up_its_own_bar_is_served():
    SB.keep("^NSEI", through(MON), now=at(23, 23, 57))
    SB.keep("^NSEI", through(FRI), now=at(24, 0, 7))

    morning = SB.keep("^NSEI", through(MON), now=at(24, 11, 16))
    assert last(morning) == (MON, 25349.65)
    assert "kept_sessions" not in morning.attrs
    assert len(morning) == len(through(MON))             # no bar twice


def test_a_correction_from_the_feed_wins_and_replaces_what_was_kept():
    SB.keep("^NSEI", through(MON), now=at(23, 20))
    corrected = history({**NIFTY, MON: 25351.10})        # same date, different close
    assert last(SB.keep("^NSEI", corrected, now=at(23, 21))) == (MON, 25351.10)

    # The feed goes back after midnight: what comes back is the corrected bar.
    assert last(SB.keep("^NSEI", through(FRI), now=at(24, 0, 30))) == (MON, 25351.10)


def test_the_bar_put_back_is_the_whole_bar_in_the_feeds_own_shape():
    full = through(MON)
    full.loc[full.index[-1], ["Open", "High", "Low", "Volume"]] = [25929.15, 25992.60,
                                                                  25343.85, 519_100]
    SB.keep("^NSEI", full, now=at(23, 20))
    short = through(FRI)
    out = SB.keep("^NSEI", short, now=at(24, 1))

    bar = out.iloc[-1]
    assert (bar["Open"], bar["High"], bar["Low"], bar["Close"]) == (25929.15, 25992.60,
                                                                   25343.85, 25349.65)
    assert bar["Volume"] == 519_100 and bar["Dividends"] == 0 and bar["Stock Splits"] == 0
    assert out.index[-1] == pd.Timestamp(MON, tz=KOLKATA)       # a midnight in India
    assert list(out.columns) == list(short.columns) and out.index.name == "Date"
    assert out.index.is_monotonic_increasing and out.index.is_unique
    assert len(short) == len(through(FRI))               # the feed's frame is not edited


def test_dhans_history_has_no_zone_and_is_kept_the_same_way():
    SB.keep("RELIANCE.NS", through(MON, tz=None), now=at(23, 20))
    out = SB.keep("RELIANCE.NS", through(FRI, tz=None), now=at(24, 0, 7))
    assert last(out) == (MON, 25349.65)
    assert out.index.tz is None and out.index[-1] == pd.Timestamp(MON)


def test_two_sessions_short_gets_both_back():
    SB.keep("^NSEI", through(MON), now=at(23, 20))
    out = SB.keep("^NSEI", through(THU), now=at(24, 1))
    assert out.attrs["kept_sessions"] == [FRI, MON]
    assert [round(c, 2) for c in out["Close"].iloc[-3:]] == [25514.30, 25800.60, 25349.65]


def test_the_next_session_arriving_first_does_not_hide_the_missing_one():
    """The feed loses Monday at midnight and still has not got it back when
    Tuesday's first bar arrives. Without Monday in between, Tuesday's move
    would be measured from Friday."""
    SB.keep("^NSEI", through(MON), now=at(23, 20))
    tuesday = history({THU: NIFTY[THU], FRI: NIFTY[FRI], "2026-11-24": 25400.00})
    out = SB.keep("^NSEI", tuesday, now=at(24, 9, 20))
    assert [str(i)[:10] for i in out.index[-3:]] == [FRI, MON, "2026-11-24"]
    assert round(float(out["Close"].iloc[-2]), 2) == 25349.65
    assert out.attrs["kept_sessions"] == [MON]


# ── What is kept, and for how long ──────────────────────────────────────────

def test_a_bar_still_forming_is_never_kept():
    """11:00 on Monday: the last bar is a price, not a close. Had it been
    kept, a later frame without today would be given 11:00's price back as
    Monday's bar."""
    SB.keep("^NSEI", history({**NIFTY, MON: 25900.00}), now=at(23, 11))
    out = SB.keep("^NSEI", through(FRI), now=at(23, 11, 5))
    assert last(out) == (FRI, 25800.60) and "kept_sessions" not in out.attrs


def test_todays_bar_is_kept_once_the_close_has_settled():
    assert SB.settled_through(at(23, 15, 59)) == dt.date(2026, 11, 22)   # not yet today
    assert SB.settled_through(at(23, 16, 0)) == dt.date(2026, 11, 23)
    SB.keep("^NSEI", through(MON), now=at(23, 16, 0))
    assert last(SB.keep("^NSEI", through(FRI), now=at(23, 16, 30))) == (MON, 25349.65)


def test_a_kept_bar_is_trusted_for_four_days_and_no_longer():
    """Friday's close stands in through a three-day weekend. After that a feed
    with no bar for the date is believed: there was none."""
    SB.keep("^NSEI", through(MON), now=at(23, 20))
    assert SB.TRUST_DAYS == 4
    assert last(SB.keep("^NSEI", through(FRI), now=at(27, 23, 59))) == (MON, 25349.65)

    late = SB.keep("^NSEI", through(FRI), now=at(28, 0, 1))
    assert last(late) == (FRI, 25800.60) and "kept_sessions" not in late.attrs


def test_a_bar_on_a_trading_holiday_is_not_kept(monkeypatch):
    """A feed that shows a bar on a day the exchange was shut, then withdraws
    it, was right to withdraw it."""
    monkeypatch.setitem(market_calendar._state, "days",
                        {"2026-11-24": "Prakash Gurpurb Sri Guru Nanak Dev"})
    phantom = history({**NIFTY, "2026-11-24": 25349.65})
    SB.keep("^NSEI", phantom, now=at(24, 20))
    out = SB.keep("^NSEI", through(MON), now=at(25, 1))
    assert last(out) == (MON, 25349.65) and "kept_sessions" not in out.attrs


def test_a_bar_kept_before_the_holiday_list_was_read_is_not_put_back_after(monkeypatch):
    """A first deploy: the feed shows a bar on the holiday before NSE's list
    has arrived, and it is kept. Once the list is in, it stays out."""
    SB.keep("^NSEI", history({**NIFTY, "2026-11-24": 25349.65}), now=at(24, 20))
    assert SB._bars()["^NSEI"][-1][0] == "2026-11-24"

    monkeypatch.setitem(market_calendar._state, "days",
                        {"2026-11-24": "Prakash Gurpurb Sri Guru Nanak Dev"})
    out = SB.keep("^NSEI", through(MON), now=at(25, 1))
    assert last(out) == (MON, 25349.65) and "kept_sessions" not in out.attrs
    assert SB._bars()["^NSEI"][-1][0] == MON             # and it is forgotten


def test_a_weekend_bar_is_not_kept():
    saturday = history({THU: NIFTY[THU], FRI: NIFTY[FRI], "2026-11-21": 25800.60})
    SB.keep("^NSEI", saturday, now=at(22, 12))
    out = SB.keep("^NSEI", through(FRI), now=at(22, 13))
    assert last(out) == (FRI, 25800.60) and "kept_sessions" not in out.attrs


def test_one_symbols_bar_is_never_put_into_anothers():
    SB.keep("^NSEI", through(MON), now=at(23, 20))
    other = SB.keep("^NSEBANK", through(FRI), now=at(24, 1))
    assert last(other) == (FRI, 25800.60)


# ── The data disk ───────────────────────────────────────────────────────────

def test_a_restart_during_the_gap_does_not_lose_the_session():
    SB.keep("^NSEI", through(MON), now=at(23, 23, 57))
    SB._mem["bars"] = None                               # the process is new; the disk is not
    out = SB.keep("^NSEI", through(FRI), now=at(24, 0, 7))
    assert last(out) == (MON, 25349.65)


def test_the_file_holds_three_sessions_a_symbol_and_drops_what_is_too_old():
    import json
    SB.keep("^NSEI", through(MON), now=at(23, 20))
    SB.keep("OLD.NS", history({"2026-10-01": 100.0, "2026-10-02": 101.0}), now=at(23, 20))
    with open(SB._PATH) as fh:
        bars = json.load(fh)["bars"]
    assert [r[0] for r in bars["^NSEI"]] == [THU, FRI, MON]
    assert bars["^NSEI"][-1][4] == 25349.65
    assert "OLD.NS" not in bars                          # past trusting: nothing to put back


def test_a_damaged_file_is_read_as_far_as_it_can_be_used():
    import json
    SB.keep("^NSEI", through(MON), now=at(23, 20))
    with open(SB._PATH) as fh:
        blob = json.load(fh)
    blob["bars"]["BAD.NS"] = [["2026-11-23", 1.0]]         # a row cut short
    blob["bars"]["WORSE.NS"] = "not rows"
    with open(SB._PATH, "w") as fh:
        json.dump(blob, fh)

    SB._mem["bars"] = None
    assert list(SB._bars()) == ["^NSEI"]
    assert last(SB.keep("^NSEI", through(FRI), now=at(24, 1))) == (MON, 25349.65)

    with open(SB._PATH, "w") as fh:
        fh.write("{ not json")
    SB._mem["bars"] = None
    assert last(SB.keep("^NSEI", through(FRI), now=at(24, 1))) == (FRI, 25800.60)


def test_the_memory_is_bounded(monkeypatch):
    monkeypatch.setattr(SB, "MAX_SYMBOLS", 3)
    for i in range(5):
        SB.keep(f"S{i}.NS", through(MON, tz=None), now=at(23, 20))
    assert list(SB._bars()) == ["S2.NS", "S3.NS", "S4.NS"]


def test_an_unwritable_disk_costs_nothing_but_the_restart(monkeypatch):
    monkeypatch.setattr(SB, "_PATH", "/nonexistent-directory/settled_bars.json")
    SB.keep("^NSEI", through(MON), now=at(23, 20))
    assert last(SB.keep("^NSEI", through(FRI), now=at(24, 1))) == (MON, 25349.65)


# ── What is left alone ──────────────────────────────────────────────────────

def test_a_new_york_history_is_left_alone():
    """16:00 IST says nothing about whether a New York bar has settled."""
    us = through(MON, tz="America/New_York")
    SB.keep("AAPL", us, now=at(23, 20))
    assert SB._bars() == {}
    out = SB.keep("AAPL", through(FRI, tz="America/New_York"), now=at(24, 1))
    assert last(out) == (FRI, 25800.60)


@pytest.mark.parametrize("odd", [
    None,
    pd.DataFrame(),
    pd.DataFrame({"Close": [1.0, 2.0]}),                         # no dates
    pd.DataFrame({"Open": [1.0]}, index=pd.DatetimeIndex(["2026-11-23"])),   # no closes
])
def test_anything_that_is_not_a_dated_history_comes_back_untouched(odd):
    assert SB.keep("X", odd, now=at(23, 20)) is odd


def test_a_fault_in_the_memory_never_costs_the_price(monkeypatch):
    SB.keep("^NSEI", through(MON), now=at(23, 20))
    monkeypatch.setattr(SB, "_settled_rows", lambda *a, **k: 1 / 0)
    out = SB.keep("^NSEI", through(FRI), now=at(24, 1))          # does not raise
    assert len(out) >= len(through(FRI)) and float(out["Close"].iloc[-1]) > 0
