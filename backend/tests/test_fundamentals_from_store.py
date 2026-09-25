"""
The Fundamentals pane served from altaha_fundamentals.db.

What must hold: a stored company comes back in exactly the shape the live
reader produces, the store never answers for a basis it does not keep, and an
overdue series goes to the exchange rather than being served as current.
"""

import datetime as dt
import sys

import pytest


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("ALTAHA_FUNDAMENTALS_DB", str(tmp_path / "f.db"))
    sys.modules.pop("fundamentals_store", None)
    import fundamentals_store
    return fundamentals_store


def _q(store, end, rev_cr, pat_cr, basis="consolidated", sym="ACME"):
    import fundamentals as F
    e = dt.date.fromisoformat(end)
    return store.to_row("income", {
        "symbol": sym, "company": "Acme Ltd", "basis": basis, "freq": "quarterly",
        "label": F.quarter_label(e), "period_from": None, "period_end": end,
        "months": 3, "filed_at": "01-Aug-2026 18:00:00", "audited": "Unaudited",
        "source_url": "https://x/%s.xml" % end,
    }, {"revenue": rev_cr * 1e7, "pat": pat_cr * 1e7, "ebitda": rev_cr * 0.2e7,
        "pbt": pat_cr * 1.3e7, "tax": pat_cr * 0.3e7, "eps_basic": 12.5})


ENDS = ["2026-06-30", "2026-03-31", "2025-12-31", "2025-09-30", "2025-06-30",
        "2025-03-31"]
TODAY = dt.date(2026, 9, 25)


def test_a_stored_company_comes_back_in_the_pane_shape(store):
    import fundamentals as F
    store.upsert("income", [_q(store, e, 1000 + i * -50, 100 - i * 10)
                            for i, e in enumerate(ENDS)])
    out = F.series_from_store("ACME", quarters=6, today=TODAY)
    assert out["available"] and out["served_from"] == "store"
    assert out["basis"] == "consolidated" and out["count"] == 6
    assert not out["partial"]
    top = out["rows"][0]
    assert top["label"] == "Q1 FY27" and top["values"]["revenue"] == 1000 * 1e7
    assert top["values"]["eps_basic"] == 12.5
    assert top["ratios"]["opm_pct"] == 20.0
    # Same quarter a year earlier, found by date, with a real percentage.
    assert top["yoy_against"] == "Q1 FY26"
    assert top["yoy"]["revenue"]["kind"] == "grew"
    assert top["yoy"]["revenue"]["pct"] == pytest.approx(25.0)
    assert top["qoq_against"] == "Q4 FY26"
    assert [l["key"] for l in out["lines"]] == [k for k, _l, _u in F.LINES]


def test_the_store_never_answers_for_a_basis_it_does_not_keep(store):
    import fundamentals as F
    store.upsert("income", [_q(store, ENDS[0], 1000, 100)])
    assert F.series_from_store("ACME", basis="standalone", today=TODAY) is None
    assert F.series_from_store("ACME", basis="consolidated", today=TODAY)["available"]


def test_an_uncrawled_company_goes_to_the_exchange(store):
    import fundamentals as F
    assert F.series_from_store("NOBODY", today=TODAY) is None


def test_an_overdue_series_is_not_served_as_current(store):
    import fundamentals as F
    store.upsert("income", [_q(store, "2025-12-31", 1000, 100)])
    assert F.series_from_store("ACME", today=TODAY) is None
    held = F.series_from_store("ACME", today=TODAY, allow_stale=True)
    assert held["available"] and held["stale"]
    assert "Q3 FY26" in held["notes"][0]


def test_a_short_history_says_so(store):
    import fundamentals as F
    store.upsert("income", [_q(store, e, 1000, 100) for e in ENDS[:3]])
    out = F.series_from_store("ACME", quarters=6, today=TODAY)
    assert out["partial"] and out["count"] == 3
    assert any("held for this company" in n for n in out["notes"])
