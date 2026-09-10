"""
The number under the price on a stock page, and the year it was reporting.

CAPLIPOINT printed "+26.37% today" on a session it moved +0.92%. Nothing was
wrong with the arithmetic: the page asked /chart for range=1D and read back
`change_pct`. But "1D" on that endpoint names a CANDLE SIZE — daily bars, four
hundred sessions of them — and `change_pct` is the move across everything
drawn. The headline was quoting a year and a half of return with the word
"today" after it.

These pin the two apart: `change_pct` stays the range's move (the chart legend
wants it), and `day_change_pct` is the last close against the one before.
"""
import pandas as pd
import pytest


@pytest.fixture(scope="module")
def main_mod():
    import main
    return main


def _series(closes):
    idx = pd.bdate_range("2025-01-01", periods=len(closes))
    return pd.DataFrame({"Open": closes, "High": [c * 1.01 for c in closes],
                         "Low": [c * 0.99 for c in closes], "Close": closes,
                         "Volume": [10_000] * len(closes)}, index=idx)


@pytest.fixture
def rising(monkeypatch, main_mod):
    """A name that doubles over the window and adds 1% on the closing day."""
    closes = [1000.0 + 4 * i for i in range(250)]     # 1000 -> 1996
    closes.append(round(closes[-1] * 1.01, 2))        # the last session: +1%
    df = _series(closes)
    monkeypatch.setattr(main_mod, "resolve", lambda s: (s, None, df))
    return df


def test_day_move_is_the_last_close_against_the_one_before(main_mod, rising):
    day = main_mod._day_move("TEST")
    closes = rising["Close"]
    assert day["last"] == round(float(closes.iloc[-1]), 2)
    assert day["prev_close"] == round(float(closes.iloc[-2]), 2)
    assert day["change_pct"] == pytest.approx(1.0, abs=0.01)


def test_the_day_is_not_the_window(main_mod, rising):
    """The bug, stated as a test: one number, two very different answers."""
    payload = main_mod.chart(ticker="TEST", range="1D")
    assert payload["change_pct"] > 90            # the window: it nearly doubled
    assert payload["day_change_pct"] == pytest.approx(1.0, abs=0.01)
    assert payload["prev_close"] == pytest.approx(1996.0, abs=0.01)


def test_the_day_does_not_move_when_the_range_does(main_mod, rising):
    """Switching timeframe is a browsing choice. Today's move is not."""
    day = {r: main_mod.chart(ticker="TEST", range=r)["day_change_pct"]
           for r in ("1D", "1W")}
    assert day["1D"] == day["1W"] == pytest.approx(1.0, abs=0.01)


def test_a_flat_close_reports_zero_not_none(main_mod, monkeypatch):
    monkeypatch.setattr(main_mod, "resolve",
                        lambda s: (s, None, _series([500.0] * 80)))
    assert main_mod._day_move("TEST")["change_pct"] == 0.0


def test_too_little_history_is_no_number_rather_than_a_wrong_one(main_mod, monkeypatch):
    monkeypatch.setattr(main_mod, "resolve", lambda s: (s, None, _series([500.0])))
    assert main_mod._day_move("TEST") is None


def test_a_dead_feed_does_not_take_the_chart_down_with_it(main_mod, monkeypatch):
    """The day's move is a nicety; the candles are the endpoint's job."""
    def boom(_):
        raise RuntimeError("provider down")
    monkeypatch.setattr(main_mod, "resolve", boom)
    assert main_mod._day_move("TEST") is None
