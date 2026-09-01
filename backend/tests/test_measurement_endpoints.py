"""
Wiring for the measurement stack.

Every one of these endpoints is new, and the failure mode for all of them is
the same: the module is correct, the route calls it with the wrong argument,
and nothing notices until a page is blank. That has happened repeatedly in
this project, so the seams get their own test.
"""
import pytest

from conftest import ohlcv, arc, ramp


@pytest.fixture(scope="module")
def app():
    import data_source
    import main

    frame = ohlcv(arc(150, 100, 200) + ramp(150, 168, 120))

    def fake_resolve(raw):
        return raw.upper() + ".NS", None, frame

    data_source.resolve = fake_resolve
    main.resolve = fake_resolve
    return main


def _err(fn, *a, **k):
    from fastapi import HTTPException
    try:
        return fn(*a, **k), None
    except HTTPException as e:
        return None, e


def test_the_measurement_modules_all_imported(app):
    """An optional import that silently failed would make every endpoint below
    answer 503 while looking deliberate."""
    for name in ("fwd_labels", "factor_lab", "factor_lib", "multifactor",
                 "attention_mod"):
        assert getattr(app, name) is not None, f"{name} failed to import"


def test_pit_coverage_answers_200_even_when_empty(app):
    out = app.pit_coverage()
    assert out["available"] is True
    assert "diagnostics" in out
    assert out["diagnostics"]["active_path"]


def test_pit_ic_sweeps_without_data(app):
    out = app.pit_ic(horizon=21)
    assert out["available"] is True
    assert isinstance(out["factors"], list)


def test_pit_ic_for_an_unknown_factor_says_so(app):
    out = app.pit_ic(horizon=21, factor="not_a_factor")
    assert out["available"] is False


def test_factors_endpoint_returns_every_registered_factor(app):
    out = app.factors_for(ticker="RELIANCE")
    assert out["symbol"] == "RELIANCE"
    # Every registered factor, plus the staleness diagnostics the endpoint
    # surfaces so a caller can tell "no value" from "value withheld".
    assert set(app.factor_lib.REGISTRY) <= set(out["factors"])
    assert set(out["factors"]) - set(app.factor_lib.REGISTRY) == {
        "_fundamentals_stale", "_fundamentals_note"}
    assert "fundamentals" in out
    # Families are surfaced so the reader can see the grouping, not just the
    # numbers.
    assert all("family" in v for v in out["families"].values())


def test_factors_rank_without_a_scan_says_so_rather_than_erroring(app):
    saved = app._state["payload"]
    app._state["payload"] = None
    try:
        out = app.factors_rank()
        assert out["available"] is False
        assert "scan" in out["message"].lower()
    finally:
        app._state["payload"] = saved


def test_factors_rank_ranks_a_scan(app):
    saved = app._state["payload"]
    app._state["payload"] = {"scanned_at": "01 Sep 2026", "rankings": [
        {"symbol": f"S{i:02d}", "name": f"Co {i}", "composite": 60 + i % 7,
         "price": 100.0 + i, "sector": "Industrials",
         "factors": {"momentum_12_1": float(i), "trend_quality": float(i),
                     "reversal_5d": float(-i), "low_volatility": float(i % 5),
                     "volume_shock": float(i % 3),
                     "earnings_yield": float(30 - i),
                     "earnings_growth": float(i % 4),
                     "revenue_growth": float(i % 6),
                     "margin_trend": float(i % 2),
                     "return_on_assets": float(i % 8)}}
        for i in range(30)]}
    try:
        out = app.factors_rank(horizon="short", limit=10)
        assert out["available"] is True
        assert len(out["rows"]) == 10
        scores = [r["factor_score"] for r in out["rows"]]
        assert scores == sorted(scores, reverse=True)
        assert out["rows"][0]["factor_rank"] == 1
        # The caveat about the weights being priors must survive to the API.
        assert "prior" in out["caveat"].lower()
    finally:
        app._state["payload"] = saved


def test_an_unknown_horizon_falls_back_rather_than_erroring(app):
    saved = app._state["payload"]
    app._state["payload"] = {"rankings": [
        {"symbol": f"S{i}", "factors": {"momentum_12_1": float(i),
                                        "reversal_5d": float(i),
                                        "low_volatility": float(i),
                                        "volume_shock": float(i),
                                        "earnings_yield": float(i),
                                        "margin_trend": float(i)}}
        for i in range(20)]}
    try:
        assert app.factors_rank(horizon="nonsense")["horizon"] == "short"
    finally:
        app._state["payload"] = saved


def test_attention_endpoint_is_a_risk_flag(app):
    out = app.attention_for(ticker="RELIANCE")
    assert out["symbol"] == "RELIANCE"
    assert out["direction"] == "risk"
    assert out["tier"] in ("normal", "elevated", "extreme")
    assert "sources" in out


def test_label_run_is_safe_with_nothing_to_do(app):
    out = app.pit_label()
    assert out["ok"] in (True, False)


@pytest.mark.parametrize("bad", ["", "x" * 40])
def test_factor_endpoints_reject_a_bad_ticker(app, bad):
    _out, err = _err(app.factors_for, ticker=bad)
    _out2, err2 = _err(app.attention_for, ticker=bad)
    # Either a clean rejection or a clean 404 — never a 500.
    for e in (err, err2):
        if e is not None:
            assert e.status_code in (400, 404, 503)
