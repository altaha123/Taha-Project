"""
Cross-sectional ranking.

Two properties are being protected, and both are things the existing engine
got wrong rather than hypothetical risks.
"""
import pytest

import multifactor as M


def _rows(n=40):
    """A universe where momentum and trend_quality agree perfectly (they are
    the same idea) and value disagrees with both."""
    out = []
    for i in range(n):
        out.append({"symbol": f"S{i:02d}", "factors": {
            "momentum_12_1": float(i),
            "trend_quality": float(i),          # correlated 1.0 with momentum
            "reversal_5d": float(-i),
            "low_volatility": float(i % 7),
            "volume_shock": float((i * 3) % 11),
            "earnings_yield": float(n - i),     # disagrees with momentum
            "earnings_growth": float(i % 5),
            "revenue_growth": float(i % 4),
            "margin_trend": float(i % 3),
            "return_on_assets": float(i % 6),
        }})
    return out


def test_scores_use_the_full_range_instead_of_saturating():
    """
    The defect this layer exists for. A live short-term list scored eight names
    inside 3.4 points with an exact tie in it, because an absolute 0-100 scale
    saturates once everything that survives a scan already sits in the high
    eighties. A percentile cannot do that.

    Two cases, because the honest threshold depends on the universe. When the
    families AGREE the spread should approach the whole scale; when they
    disagree it compresses toward the middle, and that compression is correct —
    a stock that is top on momentum and bottom on value genuinely is a middling
    name. What must never happen in either case is the live engine's failure:
    everything bunched inside a few points with ties.
    """
    # Families disagree by construction in this fixture.
    out = M.rank(_rows(), horizon="short")
    assert out["available"]
    scores = [r["factor_score"] for r in out["rows"] if r["factor_score"] is not None]
    assert len(scores) == 40
    assert max(scores) - min(scores) > 25, (
        f"scores span only {max(scores) - min(scores):.1f} points — still saturated")
    assert len(set(scores)) > 30, "too many ties to be a ranking"

    # Families agree: every factor ordered the same way.
    agree = [{"symbol": f"A{i:02d}",
              "factors": {n: float(i) for n in M.F.REGISTRY}} for i in range(40)]
    a = [r["factor_score"] for r in M.rank(agree, "short")["rows"]]
    assert max(a) - min(a) > 90, (
        f"with every family agreeing the scale should be nearly full, got "
        f"{max(a) - min(a):.1f}")


def test_a_family_votes_once_however_many_factors_are_in_it():
    """
    Trend structure and 52-week position correlate at 0.86 in the live engine
    and between them carry 40 of 132 points. Correlated inputs given separate
    weights do not add information, they add confidence.

    Here momentum_12_1 and trend_quality are identical by construction. Adding
    the second must not move the momentum family's contribution at all.
    """
    rows = _rows()
    one = M.rank([{**r, "factors": {**r["factors"], "trend_quality": None}}
                  for r in rows], horizon="medium")
    two = M.rank(rows, horizon="medium")
    a = [r["families"]["momentum"] for r in one["rows"]]
    b = [r["families"]["momentum"] for r in two["rows"]]
    assert a == pytest.approx(b), "a duplicated factor changed its family's vote"


def test_a_stock_missing_most_families_gets_no_score():
    """A row ranked on two of seven families sitting beside one ranked on all
    seven, with nothing to tell them apart, is the quiet failure to avoid."""
    rows = _rows()
    rows.append({"symbol": "SPARSE",
                 "factors": {"momentum_12_1": 500.0, "trend_quality": 500.0}})
    out = M.rank(rows, horizon="short")
    sparse = [r for r in out["rows"] if r["symbol"] == "SPARSE"][0]
    assert sparse["factor_score"] is None
    assert "families" in sparse["factor_score_note"]
    assert sparse["family_coverage_pct"] < 50


def test_a_missing_family_does_not_silently_push_a_stock_down():
    """
    Renormalisation. A stock with no fundamentals should be ranked on what it
    does have, not penalised by the weight of what it does not.
    """
    rows = _rows()
    # Strong on every price family, no fundamentals at all — but still over
    # the coverage floor.
    rows.append({"symbol": "PRICEONLY", "factors": {
        "momentum_12_1": 999.0, "trend_quality": 999.0, "reversal_5d": 999.0,
        "low_volatility": 999.0, "volume_shock": 999.0}})
    out = M.rank(rows, horizon="short")
    p = [r for r in out["rows"] if r["symbol"] == "PRICEONLY"][0]
    assert p["factor_score"] is not None
    assert p["factor_score"] > 80, (
        "a stock best-in-class on every family it HAS was dragged down by the "
        f"families it lacks (scored {p['factor_score']})")


def test_none_is_never_treated_as_zero():
    rows = _rows(30)
    rows[0]["factors"]["earnings_yield"] = None
    out = M.rank(rows, horizon="medium")
    led = {e["factor"]: e for e in out["rows"][0]["factor_ledger"]} \
        if out["rows"][0]["symbol"] == rows[0]["symbol"] else None
    target = [r for r in out["rows"] if r["symbol"] == "S00"][0]
    entry = {e["factor"]: e for e in target["factor_ledger"]}["earnings_yield"]
    assert entry["percentile"] is None and entry["value"] is None


def test_short_and_medium_weight_different_things():
    """Over one to four weeks stocks reverse; over six to twelve months they
    trend. One score across both mixes a positive signal with a negative one."""
    assert M.WEIGHTS["short"]["reversal"] > M.WEIGHTS["medium"]["reversal"]
    assert M.WEIGHTS["medium"]["momentum"] > M.WEIGHTS["short"]["momentum"]
    for h, w in M.WEIGHTS.items():
        assert sum(w.values()) == 100, f"{h} weights sum to {sum(w.values())}"


def test_the_two_horizons_actually_produce_different_orders():
    rows = _rows()
    s = [r["symbol"] for r in sorted(
        [x for x in M.rank(rows, "short")["rows"] if x["factor_score"] is not None],
        key=lambda r: -r["factor_score"])]
    m = [r["symbol"] for r in sorted(
        [x for x in M.rank(rows, "medium")["rows"] if x["factor_score"] is not None],
        key=lambda r: -r["factor_score"])]
    assert s != m, "the horizons are weighted differently but ranked identically"


def test_a_tiny_universe_is_refused_rather_than_ranked():
    assert M.rank([{"symbol": "A", "factors": {}}], "short")["available"] is False


def test_ranking_never_raises_on_junk():
    for bad in ([], None, [{"symbol": None}], [{"no_symbol": 1}] * 10,
                [{"symbol": f"X{i}", "factors": None} for i in range(10)]):
        try:
            M.rank(bad, "short")
        except Exception as e:                      # pragma: no cover
            pytest.fail(f"rank raised on {bad!r}: {e}")
