"""
The Factor Lab.

This is the one module in the project that must not lie, because everything
else will be judged by what it reports. Two classes of failure matter: getting
the arithmetic wrong, and — far more dangerous — publishing a confident number
from a sample that cannot support one.
"""
import math

import pytest

import factor_lab as L
import pit_store


def test_spearman_matches_known_values():
    xs = [1, 2, 3, 4, 5]
    assert L._spearman(xs, [1, 2, 3, 4, 5]) == pytest.approx(1.0)
    assert L._spearman(xs, [5, 4, 3, 2, 1]) == pytest.approx(-1.0)
    # Monotone but not linear: Spearman is 1, Pearson would not be.
    assert L._spearman(xs, [1, 4, 9, 16, 25]) == pytest.approx(1.0)


def test_ties_share_a_rank():
    """A check scored 0 or 10 for everyone must not have an ordering invented
    for it out of array position."""
    r = L._ranks(__import__("numpy").array([5.0, 5.0, 5.0, 9.0]))
    assert r[0] == r[1] == r[2]
    assert r[3] > r[0]


def test_a_constant_factor_has_no_correlation():
    assert L._spearman([3, 3, 3, 3], [1, 2, 3, 4]) is None


@pytest.fixture
def lab_db(tmp_path, monkeypatch):
    """A private store, so the test can never see or touch a real ledger."""
    monkeypatch.setattr(pit_store, "DB_PATH", str(tmp_path / "t.db"))
    pit_store._state["active_path"] = str(tmp_path / "t.db")
    if hasattr(pit_store._local, "conn"):
        del pit_store._local.conn
    pit_store.init_db()
    yield
    if hasattr(pit_store._local, "conn"):
        pit_store._local.conn.close()
        del pit_store._local.conn


def _plant(dates, n=40, signal=1.0):
    """Bank a factor whose rank matches its forward return by `signal`."""
    for d in dates:
        recs = {}
        for i in range(n):
            recs[f"S{i:02d}"] = {"good": float(i)}
        pit_store.snapshot_many(recs, as_of=d)
        for i in range(n):
            # signal=1 -> perfectly ordered; signal=0 -> deliberately reversed
            y = float(i) if signal > 0 else float(n - i)
            pit_store.record_forward_return(d, f"S{i:02d}", 21, y, 0.0)


def test_a_perfect_factor_measures_as_perfect(lab_db):
    dates = [f"2026-0{m}-01" for m in range(1, 10)]
    _plant(dates)
    out = L.evaluate("good", 21)
    assert out["available"] and out["reliable"]
    assert out["mean_ic"] == pytest.approx(1.0)
    assert out["hit_rate_pct"] == 100.0
    assert out["quintile_spread_pct"] > 0


def test_a_backwards_factor_reports_negative(lab_db):
    dates = [f"2026-0{m}-01" for m in range(1, 10)]
    _plant(dates, signal=-1.0)
    out = L.evaluate("good", 21)
    assert out["mean_ic"] == pytest.approx(-1.0)
    assert "backwards" in out["verdict"].lower()


def test_no_average_is_published_from_too_few_dates(lab_db):
    """
    The guard that matters most. A mean IC built from three overlapping
    fortnights is noise with a decimal point, and it would be quoted forever
    and caveated once. So it is withheld, not annotated.
    """
    _plant(["2026-01-01", "2026-02-01", "2026-03-01"])
    out = L.evaluate("good", 21)
    assert out["available"] is True
    assert out["reliable"] is False
    assert "mean_ic" not in out
    assert str(L.MIN_DATES) in out["message"]


def test_a_thin_cross_section_is_dropped_not_averaged(lab_db):
    """Ranking eight stocks produces an IC that swings between +1 and -1 on
    noise and would average in as though it were an observation."""
    _plant([f"2026-0{m}-01" for m in range(1, 10)], n=8)
    out = L.evaluate("good", 21)
    assert out["dates_measured"] == 0


def test_an_unmeasured_factor_says_so_rather_than_returning_zero(lab_db):
    out = L.evaluate("never_recorded", 21)
    assert out["available"] is False
    assert "No labelled observations" in out["message"]


def test_the_summary_always_carries_its_caveat(lab_db):
    """
    A realistic factor: mostly right, not always. A perfect one has zero
    variance across dates and therefore no t-statistic at all, which is
    correct and useless as a fixture.
    """
    import random
    rng = random.Random(11)
    dates = [f"2026-0{m}-01" for m in range(1, 10)]
    for d in dates:
        pit_store.snapshot_many({f"S{i:02d}": {"good": float(i)} for i in range(40)},
                                as_of=d)
        for i in range(40):
            pit_store.record_forward_return(d, f"S{i:02d}", 21,
                                            float(i) + rng.uniform(-12, 12), 0.0)
    out = L.evaluate("good", 21)
    assert "overlap" in out["caveat"].lower()
    assert out["ic_sd"] > 0
    assert out["t_stat"] is not None


def test_sweep_ranks_factors_by_measured_ic(lab_db):
    dates = [f"2026-0{m}-01" for m in range(1, 10)]
    for d in dates:
        recs = {f"S{i:02d}": {"good": float(i), "bad": float(-i), "flat": 1.0}
                for i in range(40)}
        pit_store.snapshot_many(recs, as_of=d)
        for i in range(40):
            pit_store.record_forward_return(d, f"S{i:02d}", 21, float(i), 0.0)
    out = L.sweep(21)
    names = [f["factor"] for f in out["factors"]]
    assert names.index("good") < names.index("bad")
    flat = [f for f in out["factors"] if f["factor"] == "flat"]
    # A constant factor produces no correlation on any date, so it is reported
    # as unmeasurable rather than as a zero.
    assert not flat or flat[0]["mean_ic"] is None or flat[0]["dates"] == 0


def test_the_verdict_language_is_calibrated_to_reality():
    """0.03 is a real factor, not a weak one. The wording has to say so, or
    every honest result reads as a failure."""
    assert "real equity factor" in L._verdict(0.04, 20)
    assert "No measurable signal" in L._verdict(0.0, 20)
    assert "Negative" in L._verdict(-0.05, 20)
