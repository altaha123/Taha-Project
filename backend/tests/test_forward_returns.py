"""
Forward-return labelling.

The half of the ledger that turns a diary into evidence. Three things can go
wrong quietly here and each would corrupt every measurement built on top:
labelling before the horizon has elapsed, measuring the benchmark over a
different window than the stock, and counting calendar days as though they
were trading sessions.
"""
import datetime as dt

import pandas as pd
import pytest

import forward_returns as FR
import pit_store
from conftest import ohlcv, ramp


def test_a_horizon_that_has_not_finished_is_not_labelled():
    """
    A 63-day return written from a snapshot taken yesterday is not wrong so
    much as meaningless — and once written it is never revisited.
    """
    today = dt.date(2026, 3, 1)
    assert FR._elapsed("2026-02-27", 63, today) is False
    assert FR._elapsed("2026-02-27", 5, today) is False   # 2 days < 5 sessions
    assert FR._elapsed("2025-06-01", 63, today) is True
    assert FR._elapsed("2026-02-01", 5, today) is True


def test_a_malformed_date_is_never_treated_as_elapsed():
    assert FR._elapsed("not-a-date", 21, dt.date(2026, 3, 1)) is False
    assert FR._elapsed(None, 21, dt.date(2026, 3, 1)) is False


def test_the_horizon_counts_sessions_not_calendar_days():
    """A long holiday must not quietly shorten the window being measured."""
    closes = ramp(100, 200, 120)
    s = ohlcv(closes)["Close"]
    ret, end = FR._forward(s, s.index[10], 21)
    assert ret is not None
    expected = (float(s.iloc[31]) / float(s.iloc[10]) - 1) * 100
    assert ret == pytest.approx(expected)
    assert end == s.index[31]


def test_no_label_is_produced_past_the_end_of_history():
    s = ohlcv(ramp(100, 120, 40))["Close"]
    ret, end = FR._forward(s, s.index[35], 21)
    assert ret is None and end is None


def test_a_snapshot_before_the_first_bar_is_refused():
    s = ohlcv(ramp(100, 120, 40))["Close"]
    assert FR._forward(s, dt.date(2000, 1, 1), 5) == (None, None)


def test_at_or_before_never_looks_forward():
    """The whole point-in-time guarantee in one function: asking for a price
    on a holiday must return the last close BEFORE it, never the next one."""
    s = ohlcv(ramp(100, 200, 60))["Close"]
    target = s.index[30] + pd.Timedelta(days=1)
    px, when = FR._at_or_before(s, target)
    assert when <= target
    assert px == float(s.loc[when])


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(pit_store, "DB_PATH", str(tmp_path / "t.db"))
    pit_store._state["active_path"] = str(tmp_path / "t.db")
    if hasattr(pit_store._local, "conn"):
        del pit_store._local.conn
    pit_store.init_db()
    yield
    if hasattr(pit_store._local, "conn"):
        pit_store._local.conn.close()
        del pit_store._local.conn


def test_the_benchmark_is_measured_between_the_same_two_dates(store, monkeypatch):
    """
    Alpha is only alpha if both legs cover the identical window. A stock that
    did not trade on some days must not be compared against a longer benchmark
    window than it actually had.
    """
    stock = ohlcv(ramp(100, 130, 200))["Close"]          # +30% over the frame
    bench = ohlcv(ramp(100, 110, 200))["Close"]          # +10%

    monkeypatch.setattr(FR, "_history",
                        lambda sym: bench if sym == FR.BENCHMARK else stock)

    as_of = str(stock.index[100].date())
    pit_store.snapshot_many({"ACME": {"composite": 70}}, as_of=as_of)

    out = FR.run(horizons=(21,), today=stock.index[-1].date())
    assert out["ok"] and out["written"] == 1

    rows = pit_store.training_set("composite", 21)
    assert len(rows) == 1
    _d, sym, x, excess = rows[0]
    assert sym == "ACME" and x == 70

    px0, px1 = float(stock.iloc[100]), float(stock.iloc[121])
    b0, b1 = float(bench.iloc[100]), float(bench.iloc[121])
    want = (px1 / px0 - 1) * 100 - (b1 / b0 - 1) * 100
    assert excess == pytest.approx(want, abs=1e-3)


def test_running_twice_changes_nothing(store, monkeypatch):
    stock = ohlcv(ramp(100, 130, 200))["Close"]
    bench = ohlcv(ramp(100, 110, 200))["Close"]
    monkeypatch.setattr(FR, "_history",
                        lambda sym: bench if sym == FR.BENCHMARK else stock)
    pit_store.snapshot_many({"ACME": {"composite": 70}},
                            as_of=str(stock.index[100].date()))
    today = stock.index[-1].date()

    first = FR.run(horizons=(21,), today=today)
    second = FR.run(horizons=(21,), today=today)
    assert first["written"] == 1
    assert second["written"] == 0, "a second run rewrote labels that already existed"
    assert pit_store.label_counts()[21] == 1


def test_no_benchmark_means_no_labels_rather_than_bare_returns(store, monkeypatch):
    """
    Without the index leg these would be returns, not alpha — and a return
    banked in the alpha column would silently flatter every measurement built
    on it afterwards.
    """
    stock = ohlcv(ramp(100, 130, 200))["Close"]
    monkeypatch.setattr(FR, "_history",
                        lambda sym: None if sym == FR.BENCHMARK else stock)
    pit_store.snapshot_many({"ACME": {"composite": 70}},
                            as_of=str(stock.index[100].date()))
    out = FR.run(horizons=(21,), today=stock.index[-1].date())
    assert out["ok"] is False
    assert "benchmark" in out["error"].lower()
    assert pit_store.label_counts() == {}


def test_a_symbol_with_no_history_is_counted_not_crashed_on(store, monkeypatch):
    bench = ohlcv(ramp(100, 110, 200))["Close"]
    monkeypatch.setattr(FR, "_history",
                        lambda sym: bench if sym == FR.BENCHMARK else None)
    pit_store.snapshot_many({"GONE": {"composite": 70}},
                            as_of=str(bench.index[100].date()))
    out = FR.run(horizons=(21,), today=bench.index[-1].date())
    assert out["ok"] and out["no_history"] == 1 and out["written"] == 0


def test_nothing_ready_is_a_clean_answer_not_an_error(store):
    out = FR.run(horizons=(21,), today=dt.date(2026, 1, 1))
    assert out["ok"] is True and out["written"] == 0
