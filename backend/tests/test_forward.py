"""
The forward projections are arithmetic, so they can be checked by inversion:
feed the solved price back through the real indicator and see whether it lands
on the number it promised. That is a stronger test than comparing against a
recorded value, because it cannot go stale.
"""
import numpy as np
import pandas as pd
import pytest

from conftest import ohlcv, ramp

import forward
from engine import rsi


@pytest.fixture
def frame():
    rng = np.random.default_rng(11)
    return ohlcv(100 + np.cumsum(rng.normal(0.05, 1.1, 300)))


@pytest.mark.parametrize("target", [30, 50, 70])
def test_rsi_trigger_price_inverts(frame, target):
    close = frame["Close"]
    out = forward.rsi_trigger_prices(close)
    px = out["prices"].get(target)
    assert px is not None
    nxt = close.index[-1] + pd.Timedelta(days=1)
    got = float(rsi(pd.concat([close, pd.Series([px], index=[nxt])]), 14).iloc[-1])
    assert abs(got - target) < 0.6, f"solved {px} for RSI {target}, recomputed {got}"


def test_supertrend_reports_a_band_and_a_direction(frame):
    st = forward.supertrend_flip_price(frame)
    assert st["direction"] in ("bullish", "bearish")
    assert st["flip_price"] > 0
    # The flip level must sit on the correct side of the current price.
    last = float(frame["Close"].iloc[-1])
    if st["direction"] == "bullish":
        assert st["flip_price"] < last
    else:
        assert st["flip_price"] > last


def test_ma_cross_projection_is_bounded_and_labelled(frame):
    x = forward.ma_cross_projection(frame["Close"], 20, 50)
    assert x["assumption"] == "price holds at today's close"
    if x["sessions_to_cross"] is not None:
        assert 1 <= x["sessions_to_cross"] <= 60
        assert x["cross_direction"] in ("golden cross", "death cross")


def test_expected_range_widens_with_the_square_root_of_time(frame):
    er = forward.expected_range(frame)
    b = er["bands"]
    one, four = b[1]["band"], b[10]["band"]
    # sqrt(10)/sqrt(1) ≈ 3.16
    assert 2.9 < four / one < 3.4


def test_build_is_honest_about_short_history():
    out = forward.build(ohlcv(ramp(10, 20, 30)))
    assert out["available"] is False
    assert "history" in out["message"].lower()


def test_bollinger_percentile_is_a_percentile(frame):
    b = forward.bollinger_state(frame["Close"])
    assert 0 <= b["percentile"] <= 100
    assert b["state"] in ("squeeze", "normal", "expanded")
    assert b["lower"] < b["upper"]
