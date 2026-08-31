"""
Tracker marking and the ledger.

Each test here corresponds to a bug that shipped and was invisible from the
outside: a row that silently read 0.00% for ever, a Refresh button that
stopped after one batch, a dead symbol that blocked the queue behind it, and
statistics describing a different population from the list under them.
"""
import datetime as dt

import numpy as np
import pandas as pd
import pytest

from conftest import ohlcv, ramp


@pytest.fixture
def feed(monkeypatch):
    """A tz-aware daily feed — the shape Yahoo actually returns."""
    import tracker

    def resolve(sym):
        if str(sym).upper().startswith("DEAD"):
            raise RuntimeError("no such symbol")
        return sym, None, ohlcv(ramp(100, 200, 300), tz="Asia/Kolkata")

    monkeypatch.setattr(tracker, "_resolve", resolve)
    return tracker


def _idea(sym="ACME", price=100.0, **kw):
    row = {"symbol": sym, "name": f"{sym} Ltd", "price": price,
           "setup_key": "momentum_breakout", "setup": "Momentum Breakout",
           "sector": "Energy", "composite": 75, "setup_fit": 80,
           "avg_turnover_cr": 12.0}
    row.update(kw)
    return row


def test_window_handles_a_tz_aware_index(feed):
    """
    The bug that blanked every price column. Yahoo returns a tz-aware daily
    index; comparing it against a tz-naive Timestamp raises in pandas, the
    caller swallowed it, and every row read "0.00%, no best, no worst" for
    ever — indistinguishable from a tracker that had never been marked.
    """
    df = ohlcv(ramp(100, 200, 300), tz="Asia/Kolkata")
    since = (dt.date.today() - dt.timedelta(days=40)).isoformat()
    win = feed._window(df, since)
    assert win is not None and len(win) > 0


def test_undated_index_is_reported_not_silently_zeroed(feed):
    df = ohlcv(ramp(100, 200, 300))
    df.index = pd.RangeIndex(len(df))
    assert feed._dated_index(df) is None


def test_marking_fills_every_column(feed, clean_tracker):
    t = feed
    t.add(_idea(), source="manual")
    row = t._load()[0]
    row["added_on"] = (dt.date.today() - dt.timedelta(days=40)).isoformat()
    row["added_price"] = 150.0
    t._save()

    out = t.update_all(limit=5, force=True)
    assert "remaining" in out, "the Refresh loop needs this field to advance"
    r = t._load()[0]
    assert r["last_price"] is not None
    assert r["return_pct"] not in (None, 0.0)
    assert r["bench_return_pct"] is not None
    assert r["max_gain_pct"] >= 0 >= r["max_drawdown_pct"]


def test_a_dead_symbol_does_not_block_the_queue(feed, clean_tracker):
    t = feed
    t.add(_idea("DEADCO"), source="manual")
    for i in range(4):
        t.add(_idea(f"SYM{i}", 100.0 + i), source="manual")
    rounds, remaining = 0, None
    while rounds < 15:
        rounds += 1
        remaining = t.update_all(limit=2, force=True)["remaining"]
        if not remaining:
            break
    assert remaining == 0, "a row that cannot be priced is starving the ones behind it"


def test_manual_add_anchors_on_a_fresh_close(feed, clean_tracker):
    """A cached scan price can be days old; the entry must not be."""
    res = feed.add(_idea(price=100.0), source="manual")
    assert res["added"]
    r = feed._load()[0]
    assert r["scan_price"] == 100.0
    assert r["added_price"] != 100.0
    assert r["added_price_source"] == "latest close"


def test_target_and_stop_resolve_in_chronological_order(feed, clean_tracker, monkeypatch):
    """
    "Hit the target, then fell through the stop" and "stopped out, then
    rallied past the target" are opposite outcomes and identical in a max and
    a min. Only the order tells them apart.
    """
    t = feed
    n = 40
    close = np.full(n, 100.0)
    close[5] = 88.0
    close[20:] = np.linspace(115, 130, n - 20)

    def make(target_first):
        d = ohlcv(close, tz="Asia/Kolkata")
        if target_first:
            d.iloc[2, d.columns.get_loc("High")] = 121.0
        return d

    for target_first, expect in ((False, "STOP"), (True, "TARGET")):
        monkeypatch.setattr(t, "_resolve",
                            lambda s, tf=target_first: (s, None, make(tf)))
        t._cache["rows"] = []
        t._save()
        t.add(_idea("PLANCO", plan={"entry": 102.0, "stop": 90.0, "t1": 120.0, "rr": 2}),
              source="manual")
        r = t._load()[0]
        # Older than the whole 40-bar frame, so the measurement window covers
        # every bar — including the early one that breaks the stop. A shorter
        # anchor starts the window after it and the order under test is lost.
        r["added_on"] = (dt.date.today() - dt.timedelta(days=200)).isoformat()
        r["added_price"] = 100.0
        t._save()
        t.update_all(limit=3, force=True)
        assert t._load()[0]["outcome"] == expect


def test_list_and_stats_describe_the_same_population(feed, clean_tracker):
    t = feed
    t.add(_idea("MINE"), source="manual")
    t.add(_idea("AUTOONLY"), source="auto", force=True)
    assert t.listing(source="manual")["count"] == t.stats(source="manual")["total_tracked"]
    assert t.tracked_symbols() == {"MINE"}, "the Ideas button must reflect YOUR list"
