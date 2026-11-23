"""
A stock's price while the market trades.

The stock page opened with the price from the cached daily history, and that
history was kept for thirty minutes whatever the hour, so a page opened at
11:00 could show 10:31's price. These pin how long a history may be served
(data_source._px_ttl), and that the live feed's REST fallback (used when
Dhan's WebSocket will not connect) actually asks Dhan for prices: it looked
for four functions dhan_source does not have, and so asked nobody.
"""
import datetime as dt
import importlib.util
import os
import types

import pytest

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))


def _load(name, file):
    spec = importlib.util.spec_from_file_location(name, os.path.join(BACKEND, file))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def ds():
    return _load("data_source_live", "data_source.py")


@pytest.fixture
def lf():
    return _load("livefeed_live", "livefeed.py")


def at(h, m, s=0, day=23):          # 23 Nov 2026 is a Monday, 21 a Saturday
    return dt.datetime(2026, 11, day, h, m, s, tzinfo=IST)


@pytest.mark.parametrize("when", [at(9, 15), at(11, 0), at(15, 29), at(15, 45), at(15, 59)])
def test_while_the_market_trades_a_price_is_kept_five_minutes(ds, when):
    assert ds._px_ttl(when) == ds.SESSION_TTL == 300


@pytest.mark.parametrize("when", [at(16, 0), at(20, 30), at(11, 0, day=21), at(11, 0, day=22)])
def test_after_the_close_and_at_the_weekend_half_an_hour(ds, when):
    assert ds._px_ttl(when) == ds._TTL == 1800


def test_before_the_open_never_past_the_open(ds):
    assert ds._px_ttl(at(9, 10)) == 300                # five minutes to 09:15
    assert ds._px_ttl(at(9, 14, 30)) == 30
    assert ds._px_ttl(at(7, 0)) == ds._TTL             # far off: the usual half hour


def test_the_clock_is_read_in_india_whatever_the_server_says(ds):
    """Render runs in UTC. 05:30 UTC is 11:00 in Mumbai, mid-session."""
    utc = dt.datetime(2026, 11, 23, 5, 30, tzinfo=dt.timezone.utc)
    assert ds._px_ttl(utc) == ds.SESSION_TTL


def test_the_rest_fallback_asks_dhan_for_last_prices(lf):
    asked = []

    def bulk_quotes(symbols, mode="ohlc"):
        asked.append((list(symbols), mode))
        return {"TCS": {"ltp": 2460.0}, "INFY": {"ltp": None}, "SBIN": {"ltp": "1132.65"}}

    lf.D = types.SimpleNamespace(bulk_quotes=bulk_quotes)
    out = lf.FEED._rest_batch(["TCS", "INFY", "SBIN"])
    assert asked == [(["TCS", "INFY", "SBIN"], "ltp")]
    assert out == {"TCS": 2460.0, "SBIN": 1132.65}       # no price is no row, not a zero


def test_a_failing_fallback_is_an_empty_answer_not_an_error(lf):
    def boom(*a, **k):
        raise RuntimeError("feed down")
    lf.D = types.SimpleNamespace(bulk_quotes=boom)
    assert lf.FEED._rest_batch(["TCS"]) == {}
