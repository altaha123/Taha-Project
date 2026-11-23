"""
Today's bar on the daily series, and what happens when it cannot be built.

On Monday 23 Nov 2026 at 15:53 IST the WELSPUNLIV page read Rs 268.78 and
"+6.18% today": Friday's close and Friday's move. Dhan's daily history ends at
the last completed session, so today's bar is built from a live quote
(dhan_source._append_today). That quote came back empty, the series went out
without today, and data_source.resolve kept it for the full thirty minutes it
keeps a good one. RELIANCE, TCS and every other name fetched that afternoon
had today's bar.

These pin three things: a frame missing its bar for today says so, resolve
keeps such a frame for a minute and not half an hour, and the quote throttle
makes concurrent callers take turns rather than share a slot.
"""
import datetime as dt
import importlib.util
import os
import threading
import time
import types

import pandas as pd
import pytest

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
MONDAY_AFTER_CLOSE = dt.datetime(2026, 11, 23, 15, 53, tzinfo=IST)
MONDAY_MIDDAY = dt.datetime(2026, 11, 23, 11, 0, tzinfo=IST)
SATURDAY = dt.datetime(2026, 11, 21, 12, 0, tzinfo=IST)


@pytest.fixture
def d(tmp_path):
    spec = importlib.util.spec_from_file_location("dhan_source_today",
                                                  os.path.join(BACKEND, "dhan_source.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod._PREV_FILE = str(tmp_path / "prev_close.json")
    return mod


def at(mod, monkeypatch, when):
    class Frozen(dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return when
    monkeypatch.setattr(mod, "dt", types.SimpleNamespace(
        datetime=Frozen, date=dt.date, timedelta=dt.timedelta, timezone=dt.timezone))


def through_friday():
    idx = pd.bdate_range(end="2026-11-20", periods=80)
    closes = [250.0] * 79 + [268.78]
    return pd.DataFrame({"Open": closes, "High": closes, "Low": closes,
                         "Close": closes, "Volume": [1_000_000] * 80}, index=idx)


def test_an_empty_quote_leaves_the_frame_marked(d, monkeypatch):
    at(d, monkeypatch, MONDAY_AFTER_CLOSE)
    monkeypatch.setattr(d, "bulk_quotes", lambda *a, **k: {})
    df = d._append_today("WELSPUNLIV", through_friday())
    assert df.index[-1] == pd.Timestamp("2026-11-20")
    assert df.attrs.get("today_missing") is True


def test_a_quote_adds_today_and_clears_the_mark(d, monkeypatch):
    at(d, monkeypatch, MONDAY_AFTER_CLOSE)
    monkeypatch.setattr(d, "bulk_quotes", lambda *a, **k: {"WELSPUNLIV": {
        "ltp": 270.76, "open": 267.0, "high": 274.0, "low": 262.0, "volume": 5_000_000}})
    df = d._append_today("WELSPUNLIV", through_friday())
    assert df.index[-1] == pd.Timestamp("2026-11-23")
    assert df["Close"].iloc[-1] == 270.76
    assert "today_missing" not in df.attrs


def test_no_bar_is_owed_at_the_weekend(d, monkeypatch):
    at(d, monkeypatch, SATURDAY)
    monkeypatch.setattr(d, "bulk_quotes", lambda *a, **k: pytest.fail("no quote at the weekend"))
    df = d._append_today("WELSPUNLIV", through_friday())
    assert df.index[-1] == pd.Timestamp("2026-11-20")
    assert "today_missing" not in df.attrs


@pytest.fixture
def ds(monkeypatch):
    # A copy of its own: other test files replace data_source.resolve in place.
    spec = importlib.util.spec_from_file_location("data_source_today",
                                                  os.path.join(BACKEND, "data_source.py"))
    data_source = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(data_source)
    clock = {"t": 1_000_000.0}
    monkeypatch.setattr(data_source, "time", types.SimpleNamespace(time=lambda: clock["t"]))
    return data_source, clock


def feed(frames):
    calls = []

    def daily_ohlcv(base):
        calls.append(base)
        return frames[min(len(calls), len(frames)) - 1].copy()
    return types.SimpleNamespace(configured=lambda: True, daily_ohlcv=daily_ohlcv), calls


def test_a_frame_missing_today_is_kept_for_a_minute(ds, monkeypatch):
    data_source, clock = ds
    stale = through_friday()
    stale.attrs["today_missing"] = True
    fresh = through_friday()
    fresh.loc[pd.Timestamp("2026-11-23")] = [267.0, 274.0, 262.0, 270.76, 5_000_000]
    fake, calls = feed([stale, fresh])
    monkeypatch.setattr(data_source, "dhan", fake)

    assert data_source.resolve("WELSPUNLIV")[2]["Close"].iloc[-1] == 268.78
    clock["t"] += 30
    assert data_source.resolve("WELSPUNLIV")[2]["Close"].iloc[-1] == 268.78
    assert len(calls) == 1                     # a burst does not refetch
    clock["t"] += data_source.MISSING_TODAY_TTL
    assert data_source.resolve("WELSPUNLIV")[2]["Close"].iloc[-1] == 270.76
    assert len(calls) == 2


def test_a_complete_frame_is_still_kept_for_half_an_hour(ds, monkeypatch):
    data_source, clock = ds
    fake, calls = feed([through_friday()])
    monkeypatch.setattr(data_source, "dhan", fake)
    monkeypatch.setattr(data_source, "_px_ttl", lambda now=None: data_source._TTL)  # an evening
    data_source.resolve("TCS")
    clock["t"] += data_source._TTL - 1
    data_source.resolve("TCS")
    assert len(calls) == 1
    clock["t"] += 2
    data_source.resolve("TCS")
    assert len(calls) == 2


def test_concurrent_quote_callers_take_turns(d, monkeypatch):
    monkeypatch.setattr(d, "QUOTE_GAP", 0.05)
    d._last_quote["at"] = 0.0
    stamps, go = [], threading.Barrier(6)

    def caller():
        go.wait()
        d._throttle_quote()
        stamps.append(time.time())

    threads = [threading.Thread(target=caller) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    stamps.sort()
    gaps = [b - a for a, b in zip(stamps, stamps[1:])]
    assert min(gaps) >= 0.04, gaps


def test_a_complete_frame_is_kept_for_five_minutes_while_the_market_trades(ds, monkeypatch):
    data_source, clock = ds
    fake, calls = feed([through_friday()])
    monkeypatch.setattr(data_source, "dhan", fake)
    real = data_source._px_ttl
    monkeypatch.setattr(data_source, "_px_ttl", lambda now=None: real(MONDAY_MIDDAY))
    data_source.resolve("TCS")
    clock["t"] += data_source.SESSION_TTL - 1
    data_source.resolve("TCS")
    assert len(calls) == 1
    clock["t"] += 2
    data_source.resolve("TCS")
    assert len(calls) == 2
