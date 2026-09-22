"""
One company's delivery record, session by session.

What these guard, in order of how badly each would mislead a reader:

  1. A missing figure must never render as a delivered zero. "0% delivered"
     is a dramatic claim about a company; "no reading for that session" is
     the truth, and the two look nothing alike to somebody deciding whether
     to buy.
  2. Delivered quantity is DERIVED — traded quantity times the published
     share — because the panel does not store NSE's DELIV_QTY column. It has
     to be arithmetically exact against the definition, and it has to arrive
     flagged, or the page would present a computed figure as a filed one.
  3. A stock the store does not carry is not an error. Somebody who searched
     a small cap, or a US ticker, has done nothing wrong and should be told
     which of those it was.
  4. Rows come back newest first, because that is the order the page reads
     them and a silent reversal would put the oldest session under "Latest".
"""
import numpy as np
import pandas as pd
import pytest

import special


SYMS = ["RELIANCE", "TCS"]


@pytest.fixture
def panel(monkeypatch):
    """A 300-session panel in the shape _to_panels produces."""
    days = pd.bdate_range(end="2026-09-18", periods=300)
    rng = np.random.default_rng(11)
    frame = lambda lo, hi: pd.DataFrame(
        rng.uniform(lo, hi, (len(days), len(SYMS))),
        index=days, columns=SYMS).astype("float32")
    P = {"deliv": frame(30, 70), "qty": frame(1e6, 5e6), "vwap": frame(1000, 1200),
         "close": frame(1000, 1200), "high": frame(1200, 1300), "low": frame(900, 1000)}
    monkeypatch.setattr(special, "_load_cache", lambda: P)
    return P


def test_delivered_quantity_matches_the_exchange_definition(panel):
    # NSE defines DELIV_PER as DELIV_QTY / TTL_TRD_QNTY x 100, so this is the
    # identity the derivation has to satisfy — not an approximation of it.
    panel["deliv"].iloc[-1, 0] = 66.0
    panel["qty"].iloc[-1, 0] = 2_000_000

    out = special.daily_delivery("RELIANCE", days=5)
    latest = out["rows"][0]

    assert out["available"] is True
    assert latest["deliv_pct"] == 66.0
    assert latest["traded_qty"] == 2_000_000
    assert latest["delivered_qty"] == 1_320_000
    # The flag travels with the payload; the page prints the caveat from it.
    assert out["delivered_qty_derived"] is True


def test_a_missing_reading_is_never_a_delivered_zero(panel):
    panel["qty"].iloc[-1, 1] = np.nan        # no traded quantity that session
    out = special.daily_delivery("TCS", days=5)
    latest = out["rows"][0]

    assert latest["traded_qty"] is None
    assert latest["delivered_qty"] is None
    assert latest["turnover_cr"] is None
    assert latest["deliv_pct"] is not None   # the share itself was published


def test_a_session_with_no_published_share_is_dropped_not_zeroed(panel):
    panel["deliv"].iloc[-1, 1] = np.nan
    out = special.daily_delivery("TCS", days=5)

    assert out["as_of"] == str(panel["deliv"].index[-2].date())
    assert all(r["deliv_pct"] is not None for r in out["rows"])


def test_rows_are_newest_first(panel):
    dates = [r["date"] for r in special.daily_delivery("RELIANCE", days=10)["rows"]]
    assert dates == sorted(dates, reverse=True)


def test_summary_windows_are_plain_means_over_what_is_held(panel):
    series = panel["deliv"]["RELIANCE"]
    out = special.daily_delivery("RELIANCE", days=30)["summary"]

    assert out["latest"] == pytest.approx(float(series.iloc[-1]), abs=0.01)
    assert out["avg_5"] == pytest.approx(float(series.tail(5).mean()), abs=0.01)
    assert out["avg_20"] == pytest.approx(float(series.tail(20).mean()), abs=0.01)
    # The year is whatever is held, and the payload says how much that was, so
    # the page never implies 252 sessions it does not have.
    assert out["year_sessions"] == special.LOOKBACK
    assert out["trend_pp"] == pytest.approx(out["avg_20"] - out["avg_year"], abs=0.01)


def test_the_window_high_and_low_come_from_the_window_returned(panel):
    out = special.daily_delivery("RELIANCE", days=30)
    shown = [r["deliv_pct"] for r in out["rows"]]
    assert out["summary"]["high"]["deliv_pct"] == pytest.approx(max(shown), abs=0.01)
    assert out["summary"]["low"]["deliv_pct"] == pytest.approx(min(shown), abs=0.01)


def test_a_stock_outside_the_store_is_explained_not_errored(panel):
    out = special.daily_delivery("NVDA")
    assert out["available"] is False
    assert out["reason"] == "not_covered"
    # The reader is told which of the three things happened.
    assert "NSE equity" in out["message"]
    assert out["covered_symbols"] == len(SYMS)


def test_exchange_suffixes_are_stripped(panel):
    for given in ("RELIANCE.NS", "reliance", " Reliance.BO "):
        out = special.daily_delivery(given, days=5)
        assert out["available"] is True, given
        assert out["symbol"] == "RELIANCE"


@pytest.mark.parametrize("days,expected", [
    (9999, special.DAILY_MAX), (1, 5), ("abc", special.DAILY_DEFAULT),
    (None, special.DAILY_DEFAULT),
])
def test_the_row_count_is_bounded(panel, days, expected):
    # A request for 9,999 sessions must not be a request to serialise the
    # whole panel down a 512 MB instance's network.
    assert special.daily_delivery("RELIANCE", days=days)["sessions_returned"] == expected


def test_an_empty_symbol_says_so(panel):
    assert special.daily_delivery("")["reason"] == "no_symbol"


def test_an_unbuilt_cache_reports_building_rather_than_failing(monkeypatch):
    monkeypatch.setattr(special, "_load_cache", lambda: None)
    monkeypatch.setattr(special, "ensure_building", lambda *a, **k: None)
    out = special.daily_delivery("RELIANCE")

    assert out["available"] is False
    assert out["reason"] == "building"
    assert out["building"] is True
    # The status echoed back must not carry the panel itself: it is tens of
    # megabytes of float32 and this is a JSON response.
    assert "panel" not in out.get("status", {})
