"""
The factor library.

The test that matters most is the lookahead one. Every other failure here is a
bug; a lookahead leak is a lie — it makes the engine look prescient in a
backtest and then lose money in production, and it is invisible unless
something asserts against it.
"""
import datetime as dt

import numpy as np
import pytest

import factors as F
from conftest import ohlcv, ramp


# ---------------------------------------------------------------------------
# Price factors
# ---------------------------------------------------------------------------

def test_momentum_skips_the_most_recent_month():
    """
    12-1 momentum must ignore the last 21 sessions.

    A stock that rose all year and then collapsed in the final month still has
    strong 12-1 momentum. If the crash leaks in, the factor is no longer 12-1 —
    it is 12-0, which mixes a positive signal with the reversal effect that
    runs the other way, and the two cancel.
    """
    rose = ramp(100, 200, 260)
    crashed = rose[:-21] + list(np.linspace(rose[-21], rose[-21] * 0.6, 21))

    a = F.momentum_12_1(ohlcv(rose))
    b = F.momentum_12_1(ohlcv(crashed))
    assert a is not None and b is not None
    assert abs(a - b) < 1e-6, "the final month leaked into 12-1 momentum"


def test_momentum_needs_a_full_year():
    assert F.momentum_12_1(ohlcv(ramp(100, 120, 120))) is None


def test_reversal_is_negated():
    """Last week's winner must score BELOW last week's loser."""
    up = ohlcv(ramp(100, 100, 40)[:-5] + ramp(100, 115, 5))
    down = ohlcv(ramp(100, 100, 40)[:-5] + ramp(100, 87, 5))
    assert F.reversal_5d(up) < 0 < F.reversal_5d(down)


def test_trend_quality_separates_a_straight_climb_from_a_gap():
    """
    Same total return, different shape. Momentum cannot tell these apart and
    is not supposed to — this is the factor that can.
    """
    straight = ohlcv(ramp(100, 140, 120))
    gap = ohlcv([100.0] * 60 + [140.0] * 60)
    assert F.trend_quality(straight) > F.trend_quality(gap)


def test_trend_quality_is_signed():
    """A perfectly straight decline is a high-quality DOWNTREND. Scoring it
    like a high-quality uptrend is the obvious way to get this backwards."""
    assert F.trend_quality(ohlcv(ramp(100, 60, 120))) < 0
    assert F.trend_quality(ohlcv(ramp(60, 100, 120))) > 0


def test_low_volatility_is_negated_so_calm_scores_higher():
    calm = ohlcv([100 + 0.05 * (i % 3) for i in range(120)])
    wild = ohlcv([100 + 9 * ((-1) ** i) for i in range(120)])
    assert F.low_volatility(calm) > F.low_volatility(wild)


def test_volume_shock_is_log_scaled():
    """A raw ratio lets one frantic session dominate a whole universe."""
    base = [1e6] * 100 + [5e6] * 5
    df = ohlcv([100.0] * 105, volume=base)
    v = F.volume_shock(df)
    assert v is not None
    assert 100 < v < 200, f"expected ~ln(5)*100, got {v}"


@pytest.mark.parametrize("fn", [F.momentum_12_1, F.reversal_5d, F.trend_quality,
                                F.low_volatility, F.volume_shock])
def test_no_factor_raises_on_junk(fn):
    for df in (None, ohlcv([1.0]), ohlcv([0.0] * 300), ohlcv([100.0] * 300)):
        try:
            fn(df)
        except Exception as e:                      # pragma: no cover
            pytest.fail(f"{fn.__name__} raised on degenerate input: {e}")


# ---------------------------------------------------------------------------
# Point-in-time discipline
# ---------------------------------------------------------------------------

def _q(period_to, filed, pat, revenue, quarter="Third Quarter",
       margin=20.0, eps=5.0, consolidated=True):
    return {"period": {"to": period_to, "from": period_to}, "filed_at": filed,
            "quarter": quarter, "pat": pat, "revenue": revenue,
            "ebitda_margin_pct": margin, "eps_basic": eps,
            "roa_annualised_pct": 8.0, "consolidated": consolidated}


QUARTERS = [
    _q("2025-12-31", "10-Feb-2026", 130.0, 1300.0, margin=22.0),
    _q("2025-09-30", "20-Oct-2025", 120.0, 1200.0, margin=21.0, quarter="Second Quarter"),
    _q("2024-12-31", "08-Feb-2025", 100.0, 1000.0, margin=18.0),
    _q("2024-09-30", "18-Oct-2024", 95.0, 950.0, margin=17.0, quarter="Second Quarter"),
]


def test_a_filing_is_invisible_until_the_day_it_was_filed():
    """
    THE lookahead test.

    The December-2025 quarter ended on 31 Dec but was filed on 10 Feb. On
    31 Jan the market had not seen it. Selecting on period end instead of
    filing date would hand the engine six weeks of foresight — the single most
    common way a backtest flatters itself, and completely invisible in the
    output.
    """
    on_31_jan = F.known_quarters(QUARTERS, dt.date(2026, 1, 31))
    ends = [q["period"]["to"] for q in on_31_jan]
    assert "2025-12-31" not in ends, "an unfiled quarter was visible to the engine"
    assert "2025-09-30" in ends

    on_28_feb = F.known_quarters(QUARTERS, dt.date(2026, 2, 28))
    assert "2025-12-31" in [q["period"]["to"] for q in on_28_feb]


def test_known_quarters_is_newest_first():
    ks = F.known_quarters(QUARTERS, dt.date(2026, 6, 1))
    assert ks[0]["period"]["to"] == "2025-12-31"


def test_growth_compares_the_same_quarter_a_year_earlier():
    """Not "four filings back" — a company that missed or restated a quarter
    would otherwise be compared against the wrong one, silently."""
    out = F.fundamental_factors(QUARTERS, price=100.0, as_of=dt.date(2026, 6, 1))
    assert out["earnings_growth"] == pytest.approx(30.0)     # 130 vs 100
    assert out["revenue_growth"] == pytest.approx(30.0)      # 1300 vs 1000
    assert out["margin_trend"] == pytest.approx(4.0)         # 22 vs 18


def test_growth_refuses_to_report_across_a_sign_change():
    """A company that lost 100 and now loses 10 is not a 90% grower, and a
    company that lost 10 and now earns 10 is not a 200% one."""
    qs = [_q("2025-12-31", "10-Feb-2026", 10.0, 1300.0),
          _q("2024-12-31", "08-Feb-2025", -50.0, 1000.0)]
    out = F.fundamental_factors(qs, price=100.0, as_of=dt.date(2026, 6, 1))
    assert out["earnings_growth"] is None


def test_earnings_yield_needs_four_quarters_or_none():
    """Annualising one quarter ranks a seasonal business on whichever quarter
    it last happened to report."""
    three = QUARTERS[:3]
    assert F.fundamental_factors(three, price=100.0,
                                 as_of=dt.date(2026, 6, 1))["earnings_yield"] is None
    out = F.fundamental_factors(QUARTERS, price=100.0, as_of=dt.date(2026, 6, 1))
    # Four quarters at 5.0 EPS each against a price of 100 = a 20% yield.
    assert out["earnings_yield"] == pytest.approx(20.0)


def test_standalone_and_consolidated_are_not_mixed():
    mixed = QUARTERS + [_q("2025-12-31", "10-Feb-2026", 999.0, 9999.0,
                           consolidated=False)]
    ks = F.known_quarters(mixed, dt.date(2026, 6, 1), consolidated=True)
    assert all(q["consolidated"] for q in ks)


# ---------------------------------------------------------------------------
# The whole block
# ---------------------------------------------------------------------------

def test_compute_returns_every_registered_factor():
    """
    The registry in full, plus exactly two diagnostics and nothing else.

    Both halves matter. A missing factor silently drops a family from the
    ranking; an unexpected key would be walked as though it were a signal.
    """
    out = F.compute(ohlcv(ramp(100, 180, 300)), quarters=QUARTERS, price=150.0,
                    as_of=dt.date(2026, 6, 1))
    assert set(F.REGISTRY) <= set(out)
    assert set(out) - set(F.REGISTRY) == {"_fundamentals_stale", "_fundamentals_note"}


def test_missing_is_none_and_never_zero():
    """A factor scored zero ranks the stock at the bottom of it, which is a
    claim the data does not support."""
    out = F.compute(ohlcv(ramp(100, 110, 40)), quarters=[], price=110.0)
    assert out["momentum_12_1"] is None
    assert out["earnings_yield"] is None
    assert not any(v == 0 for k, v in out.items() if v is not None and "growth" in k)


def test_every_factor_belongs_to_a_family():
    for name, (family, label) in F.REGISTRY.items():
        assert family in F.FAMILIES and label


# ---------------------------------------------------------------------------
# Staleness
#
# NSE's XBRL results index is frozen at the December 2024 quarter — queried for
# the whole equities universe it returns 3,816 rows whose newest period end is
# 31-Dec-2024, and no parameter produces anything newer. Nothing here can fix
# that. What these tests protect is that it can never again be silent.
# ---------------------------------------------------------------------------

def test_fundamentals_are_withheld_when_the_newest_filing_is_ancient():
    """
    The consequential guard.

    Without it, a growth factor computed from a twenty-month-old filing is fed
    into the ranking as though it were current. The numbers are well-formed and
    the arithmetic is right, which is exactly why nobody would notice: the
    answer simply describes a company that has since reported six more times.
    """
    out = F.fundamental_factors(QUARTERS, price=100.0, as_of=dt.date(2027, 6, 1))
    assert out["stale"] is True
    assert "superseded" in out["stale_reason"]
    for k in ("earnings_growth", "revenue_growth", "margin_trend",
              "return_on_assets", "earnings_yield"):
        assert out[k] is None, f"{k} was computed from a stale filing"


def test_fresh_filings_are_not_withheld():
    out = F.fundamental_factors(QUARTERS, price=100.0, as_of=dt.date(2026, 3, 1))
    assert not out.get("stale")
    assert out["earnings_growth"] is not None


def test_the_cutoff_allows_a_normal_reporting_lag():
    """
    A quarterly filer owes a result within 45 days of the quarter end, and
    there is always a gap between the last period end and the next filing. A
    cutoff that fired inside that gap would withhold fundamentals for every
    company for part of every quarter.
    """
    assert F.STALE_AFTER_DAYS >= 135
    # Four and a half months after the newest period end is routine, not stale.
    routine = F.fundamental_factors(QUARTERS, price=100.0,
                                    as_of=dt.date(2026, 5, 15))
    assert not routine.get("stale")


def test_compute_reports_staleness_without_polluting_the_factor_block():
    """The ranker iterates the registry; a diagnostic key leaking into it
    would be ranked as though it were a factor."""
    out = F.compute(ohlcv(ramp(100, 180, 300)), quarters=QUARTERS, price=150.0,
                    as_of=dt.date(2027, 6, 1))
    assert out["_fundamentals_stale"] is True
    assert out["_fundamentals_note"]
    assert set(out) - set(F.REGISTRY) == {"_fundamentals_stale", "_fundamentals_note"}
    for name in F.REGISTRY:
        if F.REGISTRY[name][0] in ("value", "growth", "quality"):
            assert out[name] is None


def test_a_stock_with_stale_fundamentals_still_ranks_on_its_price_factors():
    """
    Withholding must degrade the reading, not delete the stock. The ranker
    already scores on the families that are present and renormalises — this
    asserts the two halves actually meet.
    """
    import multifactor as M
    rows = []
    for i in range(30):
        f = F.compute(ohlcv(ramp(100, 130 + i, 300)), quarters=QUARTERS,
                      price=100.0 + i, as_of=dt.date(2027, 6, 1))
        rows.append({"symbol": f"S{i:02d}", "factors": f})
    out = M.rank(rows, horizon="short")
    assert out["available"]
    scored = [r for r in out["rows"] if r["factor_score"] is not None]
    assert len(scored) == 30, "stale fundamentals removed the stocks entirely"
    assert all("value" not in r["families"] for r in scored)
    assert all("momentum" in r["families"] for r in scored)
