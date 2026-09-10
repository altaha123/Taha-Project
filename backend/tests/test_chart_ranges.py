"""
The range control on a stock page, and the three ways it was broken.

`range=` carried two different questions on one parameter. The charting
workspace asks for a CANDLE SIZE ("1H", and "1D" meaning daily bars). A stock
page's range buttons ask for a WINDOW: six months of history, at whatever
resolution. Only the first set existed, so of the five buttons on the stock
page:

  * "6M" and "1Y" were not keys at all and came back 400 — and 6M is the
    range that page opens on, so its chart drew nothing at all;
  * "1M" matched the one-MINUTE timeframe, because the lookup was
    case-insensitive and took the first hit, so a month of history returned
    minute bars (or 503, minute bars needing the live feed);
  * "1D" and "1W" worked, and drew four hundred and twelve hundred sessions
    under labels reading "1 day" and "1 week".

These pin the windows, and pin the one place where case now carries meaning.
"""
import pandas as pd
import pytest


@pytest.fixture(scope="module")
def main_mod():
    import main
    return main


@pytest.fixture
def history(monkeypatch, main_mod):
    """Six years of daily closes — enough to fill the longest window."""
    n = 1500
    closes = [100.0 + i * 0.5 for i in range(n)]
    df = pd.DataFrame({"Open": closes, "High": [c * 1.01 for c in closes],
                       "Low": [c * 0.99 for c in closes], "Close": closes,
                       "Volume": [10_000] * n},
                      index=pd.bdate_range("2020-01-01", periods=n))
    monkeypatch.setattr(main_mod, "resolve", lambda s: (s, None, df))
    return df


@pytest.mark.parametrize("key,sessions,label", [
    ("1M", 22, "1 month"), ("3M", 63, "3 months"), ("6M", 126, "6 months"),
    ("1Y", 252, "1 year"), ("5Y", 1260, "5 years"),
])
def test_every_button_on_the_stock_page_answers(main_mod, history, key, sessions, label):
    payload = main_mod.chart(ticker="TEST", range=key)
    assert payload["label"] == label
    assert len(payload["candles"]) == sessions


def test_a_month_is_not_a_minute(main_mod, history):
    """The silent one: "1M" used to match "1m" and return intraday bars."""
    assert main_mod._pick_range("1M")[0] == "1M"
    assert main_mod._pick_range("1m")[0] == "1m"
    assert main_mod.RANGES["1M"]["mode"] == "daily"
    assert main_mod.RANGES["1m"]["mode"] == "intraday"


def test_the_windows_need_no_live_feed(main_mod, history, monkeypatch):
    """A stock page must draw for a reader who has no Dhan credentials."""
    monkeypatch.setattr(main_mod, "dhan", None)
    assert main_mod.chart(ticker="TEST", range="6M")["source"] == "daily feed"


def test_the_candle_sizes_still_mean_what_they_meant(main_mod, history):
    """The workspace and the share cards ask in these keys. Don't move them."""
    assert len(main_mod.chart(ticker="TEST", range="1D")["candles"]) == 400
    assert main_mod.RANGES["1D"]["label"] == "1 day"
    assert main_mod.RANGES["1W"]["resample_w"] is True


def test_lowercase_still_resolves_where_it_is_unambiguous(main_mod):
    """Callers have always sent "1d". Only the 1m/1M pair needs its case."""
    assert main_mod._pick_range("1d")[0] == "1D"
    assert main_mod._pick_range("1w")[0] == "1W"
    assert main_mod._pick_range("  6m  ")[0] == "6M"


def test_an_unknown_range_is_still_refused(main_mod):
    assert main_mod._pick_range("zz") == (None, None)
    with pytest.raises(Exception):
        main_mod.chart(ticker="TEST", range="zz")


def test_a_card_falls_back_rather_than_refusing(main_mod, history):
    """_og_frame must never raise on a bad range: a broken image is worse."""
    key, label, df = main_mod._og_frame("TEST", "zz")
    assert (key, label) == ("1D", "1 day")
    assert len(df) == 400
    assert main_mod._og_frame("TEST", "6M")[0] == "6M"


def test_a_short_window_still_carries_the_days_move(main_mod, history):
    """The headline asks for the smallest window; it must still be answered."""
    payload = main_mod.chart(ticker="TEST", range="1M")
    assert payload["day_change_pct"] is not None
    assert payload["day_change_pct"] == main_mod.chart(ticker="TEST",
                                                       range="5Y")["day_change_pct"]
