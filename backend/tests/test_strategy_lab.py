"""
The Strategy lab: the arithmetic a backtest lives or dies by.

A backtest that peeks one bar ahead, charges no costs, or quietly counts a
flat line as a strategy produces a beautiful table that means nothing, and
nothing about it looks wrong on screen. These pin the parts that would.
"""
import math
import re

import numpy as np
import pandas as pd
import pytest

import strategy_lab as sl


def walk(n=3200, seed=7, drift=0.0004, vol=0.017, start="2012-01-02"):
    """A seeded random walk with honest OHLC: opens gap, highs and lows bracket."""
    rng = np.random.default_rng(seed)
    r = rng.normal(drift, vol, n)
    close = 100 * np.exp(np.cumsum(r))
    gap = rng.normal(0, vol / 3, n)
    open_ = np.concatenate([[close[0]], close[:-1]]) * np.exp(gap)
    hi = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, vol / 2, n)))
    lo = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, vol / 2, n)))
    idx = pd.bdate_range(start=start, periods=n)
    return pd.DataFrame({"Open": open_, "High": hi, "Low": lo, "Close": close,
                         "Volume": 1e6}, index=idx)


# ── Nothing sees the future ─────────────────────────────────────────────────

@pytest.mark.parametrize("spec", sl.RULES, ids=[r["id"] for r in sl.RULES])
def test_no_rule_reads_a_bar_after_the_one_it_decides_on(spec):
    df = walk()
    cut = 2000
    later = df.copy()
    rng = np.random.default_rng(99)
    shock = np.exp(rng.normal(0, 0.05, len(df) - cut - 1))
    for col in ("Open", "High", "Low", "Close"):
        later.iloc[cut + 1:, later.columns.get_loc(col)] = later[col].iloc[cut + 1:].to_numpy() * shock
    rf = 0.06
    a = spec["fn"](df, rf).to_numpy()
    b = spec["fn"](later, rf).to_numpy()
    assert np.allclose(a[:cut + 1], b[:cut + 1]), \
        f"{spec['id']} changed a decision at or before bar {cut} when only later prices moved"


def test_a_decision_is_filled_at_the_next_open_and_charged_both_ways():
    idx = pd.bdate_range("2024-01-01", periods=5)
    df = pd.DataFrame({"Open": [100, 102, 105, 103, 110.0],
                       "Close": [101, 104, 106, 108, 111.0]}, index=idx)
    df["High"], df["Low"] = df[["Open", "Close"]].max(axis=1), df[["Open", "Close"]].min(axis=1)
    w = pd.Series([0, 1, 1, 0, 0.0], index=idx)       # in at the close of bar 1, out at bar 3
    cost = 0.002
    net, pos = sl.simulate(df, w, cost)
    assert list(pos) == [0, 0, 1, 1, 0]
    assert net.iloc[1] == pytest.approx(0.0)
    # Bar 2: bought at the open, paid to get in, earned the session.
    assert net.iloc[2] == pytest.approx((1 - cost) * (106 / 105) - 1)
    # Bar 3: held through the gap and the session.
    assert net.iloc[3] == pytest.approx((103 / 106) * (108 / 103) - 1)
    # Bar 4: the gap belongs to the position being closed, then the exit is paid.
    assert net.iloc[4] == pytest.approx((110 / 108) * (1 - cost) - 1)


def test_a_missing_open_is_treated_as_no_gap_not_a_crash():
    idx = pd.bdate_range("2024-01-01", periods=4)
    df = pd.DataFrame({"Open": [100, 0, np.nan, 103.0], "Close": [100, 101, 102, 104.0]}, index=idx)
    df["High"], df["Low"] = df["Close"], df["Close"]
    net, _ = sl.simulate(df, pd.Series(1.0, index=idx), 0.0)
    assert np.isfinite(net).all()
    assert net.iloc[2] == pytest.approx(101 / 101 * 102 / 101 - 1)


# ── The measures ────────────────────────────────────────────────────────────

def test_drawdown_counts_from_the_starting_capital():
    assert sl._max_dd([0.9, 0.95, 1.2, 0.6, 1.3]) == pytest.approx(0.6 / 1.2 - 1)
    assert sl._max_dd([0.8, 1.0]) == pytest.approx(-0.2)
    assert sl._max_dd([1.1, 1.2]) == 0.0


def test_sharpe_is_measured_above_the_risk_free_rate():
    rng = np.random.default_rng(1)
    r = rng.normal(0.0005, 0.01, 2000)
    rf_d = (1.06) ** (1 / 252) - 1
    s = sl._sharpe(r, rf_d)
    assert s == pytest.approx((r - rf_d).mean() / r.std(ddof=1) * math.sqrt(252))
    assert s < sl._sharpe(r, 0.0)
    assert sl._sharpe(np.zeros(100), 0.0) is None


def test_trades_win_rate_and_profit_factor_are_in_money_not_in_percent():
    idx = pd.bdate_range("2024-01-01", periods=10)
    pos = np.array([0, 1, 1, 0, 0, 1, 0, 1, 1, 1], float)
    net = np.array([0, 0.10, 0.0, 0.0, 0, -0.05, 0.0, 0.02, 0.0, 0.0])
    closed, open_runs = sl._trades(net, pos, idx)
    assert open_runs == 1                        # the last run never closed
    assert [round(t["ret"], 4) for t in closed] == [0.10, -0.05]
    stats = sl._trade_stats(closed)
    assert stats["trades"] == 2 and stats["win_rate_pct"] == 50.0
    # 0.10 on 1.00 is 0.10; then −5% on 1.10 is −0.055.
    assert stats["profit_factor"] == pytest.approx(round(0.10 / 0.055, 2))
    assert stats["few_trades"] is True


def test_a_record_with_no_losing_trade_says_so_instead_of_infinity():
    idx = pd.bdate_range("2024-01-01", periods=4)
    closed, _ = sl._trades(np.array([0, 0.1, 0, 0]), np.array([0, 1, 0, 0.0]), idx)
    stats = sl._trade_stats(closed)
    assert stats["profit_factor"] is None and stats["profit_factor_note"] == "no losing trade"


# ── Tax ─────────────────────────────────────────────────────────────────────

def _one_trade(held_sessions, gain, start="2023-04-03", n=None):
    n = n or held_sessions + 40
    idx = pd.bdate_range(start, periods=n)
    pos = np.zeros(n)
    pos[5:5 + held_sessions] = 1.0
    net = np.zeros(n)
    net[10] = gain
    return idx, pos, net


def test_a_short_term_gain_pays_twenty_percent():
    idx, pos, net = _one_trade(30, 0.10)
    closed, _ = sl._trades(net, pos, idx)
    years = (idx[-1] - idx[0]).days / 365.25
    at = sl._after_tax(net, pos, idx, closed, 0.0, years)
    assert (1 + at) ** years == pytest.approx(1.10 - 0.20 * 0.10)


def test_a_long_term_gain_pays_twelve_and_a_half():
    idx, pos, net = _one_trade(300, 0.20)          # 300 sessions is more than a year
    closed, _ = sl._trades(net, pos, idx)
    years = (idx[-1] - idx[0]).days / 365.25
    at = sl._after_tax(net, pos, idx, closed, 0.0, years)
    assert (1 + at) ** years == pytest.approx(1.20 - 0.125 * 0.20)


def test_a_short_term_loss_offsets_a_long_term_gain_in_the_same_year():
    idx = pd.bdate_range("2023-04-03", periods=330)
    pos = np.zeros(330)
    net = np.zeros(330)
    pos[2:302] = 1.0
    net[20] = 0.30                                 # long-term winner, exits on bar 302
    pos[305:315] = 1.0
    net[307] = -0.10                               # short-term loser, exits on bar 315
    closed, _ = sl._trades(net, pos, idx)
    assert len(closed) == 2
    years = (idx[-1] - idx[0]).days / 365.25
    at = sl._after_tax(net, pos, idx, closed, 0.0, years)
    loss = 1.30 * 0.10
    expected = 1.30 * 0.90 - 0.125 * (0.30 - loss)
    assert (1 + at) ** years == pytest.approx(expected)


def test_tax_is_for_rupee_stocks_only():
    r_in = sl.run(walk(), "TEST.NS", years=5)
    r_us = sl.run(walk(), "TEST", years=5)
    assert r_in["currency"] == "INR" and r_us["currency"] == "USD"
    assert r_in["hold"]["metrics"]["after_tax_cagr_pct"] is not None
    assert r_us["hold"]["metrics"]["after_tax_cagr_pct"] is None
    assert r_in["assumptions"]["tax"] and r_us["assumptions"]["tax"] is None
    assert sl.currency_of("^NSEI") == "INR" and sl.currency_of("^GSPC") == "USD"


# ── The report ──────────────────────────────────────────────────────────────

def test_every_rule_and_holding_start_on_the_same_day_in_cash():
    r = sl.run(walk(), "TEST.NS", years=5)
    n = len(r["curve_dates"])
    assert r["hold"]["curve"][0] < 1.0 + 0.2           # paid its way in on day one
    for s in r["strategies"]:
        assert len(s["curve"]) == n
    assert r["start"] == r["curve_dates"][0]
    assert 4.5 < r["years"] <= 5.01


def test_costs_cost_something():
    df = walk()
    free = sl.run(df, "TEST.NS", years=10, cost_round_trip_pct=0.0)
    dear = sl.run(df, "TEST.NS", years=10, cost_round_trip_pct=1.0)
    f = {s["id"]: s["metrics"] for s in free["strategies"]}
    d = {s["id"]: s["metrics"] for s in dear["strategies"]}
    for k in f:
        if f[k]["trades"] >= 5:
            assert d[k]["total_return_pct"] < f[k]["total_return_pct"], k
    assert dear["assumptions"]["cost_round_trip_pct"] == 1.0
    assert free["hold"]["metrics"]["total_return_pct"] > dear["hold"]["metrics"]["total_return_pct"]


def test_positions_never_lever_or_short():
    df = walk()
    for spec in sl.RULES:
        w = spec["fn"](df, 0.06).fillna(0)
        assert w.min() >= 0.0 and w.max() <= 1.0, spec["id"]


def test_the_summary_counts_match_the_rows():
    r = sl.run(walk(seed=3), "TEST.NS", years=10)
    rows = r["strategies"]
    assert r["summary"]["of"] == len(sl.RULES) == len(rows)
    assert r["summary"]["shallower_drawdown"] == sum(1 for s in rows if s["vs_hold"]["drawdown_pts"] > 0)
    assert r["summary"]["beat_hold_cagr"] == sum(1 for s in rows if (s["vs_hold"]["cagr_pts"] or 0) > 0)


def test_too_little_history_is_refused_with_a_sentence():
    with pytest.raises(ValueError, match="Not enough price history"):
        sl.run(walk(n=600), "TEST.NS", years=3)


def test_a_short_history_is_tested_in_full_and_flagged():
    r = sl.run(walk(n=sl.WARMUP + 4 * 252), "TEST.NS", years=10)
    assert r["short_history"] is True and r["years"] < 5


def test_an_unadjusted_corporate_action_is_flagged():
    df = walk()
    df.iloc[-300:, :4] = df.iloc[-300:, :4] * 0.45   # a demerger the feed missed
    r = sl.run(df, "TEST.NS", years=5)
    assert r["warnings"] and "corporate action" in r["warnings"][0]


# ── The luck bar ────────────────────────────────────────────────────────────

def test_copies_of_one_rule_are_one_try():
    rng = np.random.default_rng(5)
    base = rng.normal(0, 0.01, 2500)
    rows = [{"id": str(i), "name": str(i), "metrics": {"sharpe": 0.3}} for i in range(6)]
    luck = sl._luck([base] * 6, 10.0, rows, 0.2)
    assert luck["effective_rules"] == pytest.approx(1.0, abs=0.05)
    assert luck["luck_bar_sharpe"] == 0.0


def test_unrelated_rules_are_separate_tries_and_raise_the_bar():
    rng = np.random.default_rng(6)
    rets = [rng.normal(0, 0.01, 2500) for _ in range(8)]
    rows = [{"id": str(i), "name": str(i), "metrics": {"sharpe": 0.1 * i}} for i in range(8)]
    luck = sl._luck(rets, 10.0, rows, 0.0)
    assert luck["effective_rules"] > 7
    # Expected best of 8 zero-skill Sharpe ratios over ten years: about 0.45.
    assert 0.35 < luck["luck_bar_sharpe"] < 0.55
    assert luck["best_id"] == "7" and luck["verdict"] == "clears_luck"


def test_a_rule_that_never_traded_is_not_a_try():
    rng = np.random.default_rng(8)
    live = rng.normal(0, 0.01, 2500)
    rows = [{"id": "a", "name": "a", "metrics": {"sharpe": 0.1}},
            {"id": "b", "name": "b", "metrics": {"sharpe": None}}]
    luck = sl._luck([live, np.zeros(2500)], 10.0, rows, 0.0)
    assert luck["effective_rules"] == 1.0 and luck["luck_bar_sharpe"] == 0.0


# ── The line this project does not cross ────────────────────────────────────

DIRECTIVE = re.compile(r"\b(buy|sell|recommend\w*|should (?:buy|sell|enter|exit))\b", re.I)


def test_the_rules_are_described_not_recommended():
    for spec in sl.RULES:
        for field in ("name", "rule", "idea"):
            assert not DIRECTIVE.search(spec[field]), (spec["id"], field, spec[field])


def test_the_report_never_says_what_a_rule_is_doing_today():
    r = sl.run(walk(), "TEST.NS", years=5)
    banned = {"signal", "current_position", "position_today", "in_market_now", "action", "call"}

    def keys(o):
        if isinstance(o, dict):
            for k, v in o.items():
                yield k
                yield from keys(v)
        elif isinstance(o, list):
            for v in o:
                yield from keys(v)

    assert not banned & set(keys(r))
    assert "not a recommendation" in r["disclaimer"]


# ── The browser fixture ─────────────────────────────────────────────────────

def test_the_browser_fixture_has_the_shape_the_server_sends():
    """strategy-lab-browser.cjs draws a committed report. If the report's
    shape moves on and the fixture does not, the browser test goes on passing
    against a page nobody will ever see. Rebuild it with
    backend/tests/make_strategy_lab_fixture.py."""
    import json
    import os
    from make_strategy_lab_fixture import OUT, build

    with open(OUT, encoding="utf-8") as fh:
        committed = json.load(fh)
    fresh = build()

    def shape(o):
        if isinstance(o, dict):
            return {k: shape(v) for k, v in sorted(o.items()) if k not in ("curve", "years", "curve_dates", "halves", "warnings")}
        if isinstance(o, list):
            return [shape(o[0])] if o and isinstance(o[0], (dict, list)) else "list"
        return "value"

    assert shape(committed) == shape(fresh), "rebuild frontend/tests/fixtures/strategy-lab-demo.json"
    assert [s["id"] for s in committed["strategies"]] == [r["id"] for r in sl.RULES]
    assert os.path.getsize(OUT) < 80_000


# ── The endpoint ────────────────────────────────────────────────────────────

class _FakeTicker:
    def __init__(self, df):
        self.df = df

    def history(self, period="1y", auto_adjust=True):
        return self.df


@pytest.fixture
def client(monkeypatch):
    from fastapi.testclient import TestClient
    import main
    from data_source import NotFound
    sl._HIST.clear()
    sl._REPORTS.clear()
    frames = {"GOOD": walk(), "YOUNG": walk(n=500)}

    def fake_resolve(raw):
        key = raw.upper().replace(".NS", "")
        if key not in frames:
            raise NotFound(raw)
        return f"{key}.NS", _FakeTicker(frames[key]), frames[key].tail(250)

    monkeypatch.setattr(main, "resolve", fake_resolve)
    yield TestClient(main.app)
    sl._HIST.clear()
    sl._REPORTS.clear()


def test_the_endpoint_returns_the_report(client):
    r = client.get("/strategies", params={"ticker": "good", "years": 5})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["ticker"] == "GOOD" and j["currency"] == "INR"
    assert len(j["strategies"]) == len(sl.RULES)
    assert {"total_return_pct", "cagr_pct", "sharpe", "max_drawdown_pct",
            "win_rate_pct", "profit_factor"} <= set(j["strategies"][0]["metrics"])
    assert j["source"]["url"] == "https://quants.md/"


def test_the_endpoint_refuses_what_it_cannot_answer(client):
    assert client.get("/strategies", params={"ticker": "GOOD", "years": 7}).status_code == 400
    assert client.get("/strategies", params={"ticker": "GOOD", "cost": 9}).status_code == 400
    assert client.get("/strategies", params={"ticker": "NOPE"}).status_code == 404
    young = client.get("/strategies", params={"ticker": "YOUNG"})
    assert young.status_code == 422 and "Not enough price history" in young.json()["detail"]
