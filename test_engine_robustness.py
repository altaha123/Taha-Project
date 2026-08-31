"""
The analysis functions must not raise on bad data.

Every one of these inputs has a real-world cause: a resample that drops a
column, a feed that returns a frame in reverse order, a holiday row with no
volume, a symbol whose history is shorter than an indicator's period. A
raised exception here becomes a 500 on /analyze or a blank chart, and the
bugs this project has actually shipped were all of exactly this shape.
"""
import numpy as np
import pandas as pd
import pytest

from conftest import ohlcv, ramp

import engine
import levels
import patterns
import forward
import tradeplan


def _cases():
    def base(n=260):
        return ohlcv(ramp(80, 160, n))
    c = {}
    c["flat line"] = ohlcv([100.0] * 260)
    c["zero volume"] = ohlcv(ramp(50, 150, 260), volume=[0.0] * 260)
    c["gap up"] = ohlcv([100.0] * 130 + [1000.0] * 130)
    c["decline to near zero"] = ohlcv(ramp(500, 0.01, 260))
    c["tz-aware index"] = ohlcv(ramp(50, 150, 260), tz="Asia/Kolkata")
    c["penny prices"] = ohlcv(ramp(0.05, 0.09, 260))
    c["60 bars"] = base(60)
    c["30 bars"] = base(30)
    d = base(); d.index = [d.index[0]] * len(d);            c["duplicate index"] = d
    d = base(); c["reverse sorted"] = d.iloc[::-1]
    d = base(); c["no Volume column"] = d.drop(columns=["Volume"])
    d = base(); d["High"], d["Low"] = d["Low"].copy(), d["High"].copy()
    c["High below Low"] = d
    d = base(); d[["Open", "High", "Low", "Close"]] *= -1;   c["negative prices"] = d
    d = base(); d.iloc[-1, d.columns.get_loc("Close")] = np.nan
    c["last close NaN"] = d
    d = base(); d["Volume"] = np.nan;                       c["all-NaN volume"] = d
    d = base(); d.index = pd.RangeIndex(len(d));            c["undated index"] = d
    d = base(); d[["Open", "High", "Low", "Close"]] = 0.0;  c["all zeros"] = d
    return c


CASES = _cases()


def _targets():
    return {
        "technical_score": lambda d: engine.technical_score(d),
        "rsi": lambda d: engine.rsi(d["Close"]),
        "macd": lambda d: engine.macd(d["Close"]),
        "adx": lambda d: engine.adx(d),
        "atr": lambda d: engine.atr(d),
        "supertrend": lambda d: engine.supertrend(d),
        "bollinger": lambda d: engine.bollinger(d["Close"]),
        "hma": lambda d: engine.hma(d["Close"]),
        "compute_levels": lambda d: levels.compute_levels(d),
        "build_plan": lambda d: tradeplan.build_plan(d, levels.compute_levels(d)),
        "compact_plan": lambda d: tradeplan.compact_plan(d, levels.compute_levels(d)),
        "patterns.analyse": lambda d: patterns.analyse(d, with_base_rates=False),
        "forward.build": lambda d: forward.build(d),
    }


TARGETS = _targets()


@pytest.mark.parametrize("case", sorted(CASES))
@pytest.mark.parametrize("target", sorted(TARGETS))
def test_never_raises(case, target):
    TARGETS[target](CASES[case].copy())


def test_indicators_stay_finite_on_a_real_shape(uptrend):
    """A NaN leaking out of an indicator silently zeroes a score."""
    close = uptrend["Close"]
    for name, series in (("rsi", engine.rsi(close)), ("adx", engine.adx(uptrend)),
                         ("atr", engine.atr(uptrend))):
        last = float(series.iloc[-1])
        assert np.isfinite(last), f"{name} produced {last}"


def test_supertrend_returns_a_direction_not_a_price(uptrend):
    """
    Regression: callers compared a rupee price against this and the test
    never fired, because the function returns +1 / -1. Anything that starts
    returning a band here breaks those comparisons silently, so pin it.
    """
    st = engine.supertrend(uptrend)
    assert set(np.unique(st.values)) <= {-1, 1}
