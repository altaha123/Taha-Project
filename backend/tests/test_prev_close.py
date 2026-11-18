"""
The previous close, after the close (dhan_source._settle_prev_close).

On 18 Nov 2026 every stock on the home page read "0.00%" through the
evening while the indices beside them showed the day's real move. During a
session the quote's ohlc.close is the previous session's close; after it,
the feed rolls that field to today's close, and (ltp - close) is zero for
every stock at once.
"""
import datetime as dt
import importlib.util
import os

import pytest

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
SESSION = dt.datetime(2026, 11, 18, 11, 0, tzinfo=IST)       # a Wednesday, mid-session
EVENING = dt.datetime(2026, 11, 18, 19, 30, tzinfo=IST)
NEXT_MORNING = dt.datetime(2026, 11, 19, 8, 0, tzinfo=IST)


@pytest.fixture
def d(tmp_path):
    spec = importlib.util.spec_from_file_location("dhan_source_prev",
                                                  os.path.join(BACKEND, "dhan_source.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod._PREV_FILE = str(tmp_path / "prev_close.json")
    return mod


def quotes(n=12, ltp=101.0, prev=100.0, net=None):
    return {f"S{i}": {"ltp": ltp + i, "prev_close": prev + i, "net_change": net} for i in range(n)}


def test_during_the_session_the_close_is_left_alone(d):
    out = d._settle_prev_close(quotes(), now=SESSION)
    assert [r["prev_close"] for r in out.values()] == [100.0 + i for i in range(12)]


def test_after_the_roll_the_remembered_close_is_used(d):
    d._settle_prev_close(quotes(), now=SESSION)                       # the session teaches it
    rolled = quotes(ltp=101.0, prev=101.0)                            # close == ltp for every stock
    out = d._settle_prev_close(rolled, now=EVENING)
    assert out["S0"]["prev_close"] == 100.0 and out["S7"]["prev_close"] == 107.0
    # And still the next morning, before the new session opens.
    out = d._settle_prev_close(quotes(ltp=101.0, prev=101.0), now=NEXT_MORNING)
    assert out["S3"]["prev_close"] == 103.0


def test_the_memory_survives_a_restart(d, tmp_path):
    d._settle_prev_close(quotes(), now=SESSION)
    assert os.path.exists(d._PREV_FILE)
    d._prev.update({"day": None, "map": {}, "loaded": False})         # a fresh process
    out = d._settle_prev_close(quotes(ltp=101.0, prev=101.0), now=EVENING)
    assert out["S5"]["prev_close"] == 105.0


def test_with_nothing_remembered_the_feeds_own_change_is_used(d):
    out = d._settle_prev_close(quotes(ltp=101.0, prev=101.0, net=-2.5), now=EVENING)
    assert out["S0"]["prev_close"] == 103.5


def test_with_nothing_to_go_on_it_says_so_rather_than_zero(d):
    out = d._settle_prev_close(quotes(ltp=101.0, prev=101.0), now=EVENING)
    assert all(r["prev_close"] is None for r in out.values())


def test_a_stock_that_really_was_flat_is_not_touched(d):
    q = quotes()                                                      # eleven moved, one did not
    q["S4"]["prev_close"] = q["S4"]["ltp"]
    out = d._settle_prev_close(q, now=EVENING)
    assert out["S4"]["prev_close"] == out["S4"]["ltp"]
    assert out["S0"]["prev_close"] == 100.0


def test_one_stock_alone_uses_the_memory_after_hours(d):
    d._settle_prev_close(quotes(), now=SESSION)
    out = d._settle_prev_close({"S2": {"ltp": 103.0, "prev_close": 103.0}}, now=EVENING)
    assert out["S2"]["prev_close"] == 102.0


def test_yesterdays_memory_is_not_used_for_todays_session(d):
    d._settle_prev_close(quotes(), now=SESSION)
    thursday_evening = dt.datetime(2026, 11, 19, 19, 30, tzinfo=IST)
    out = d._settle_prev_close(quotes(ltp=101.0, prev=101.0), now=thursday_evening)
    assert all(r["prev_close"] is None for r in out.values())


def test_the_sector_board_falls_back_instead_of_printing_zero(d, monkeypatch):
    """A rolled feed with nothing remembered gives no Dhan rows at all, which
    is what sends sector_story to its daily-history source."""
    import sector_story
    rolled = d._settle_prev_close(quotes(ltp=101.0, prev=101.0), now=EVENING)
    import types
    monkeypatch.setattr(sector_story, "dhan", types.SimpleNamespace(
        configured=lambda: True, bulk_quotes=lambda syms, mode="ohlc": rolled))
    rows, bench, err = sector_story._returns_dhan([f"S{i}" for i in range(12)], 1)
    assert rows == {} and bench is None
