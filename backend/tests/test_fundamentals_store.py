"""
The fundamentals table and the crawl that fills it.

The failure that matters here is not a crash, it is a table that quietly says
the wrong thing: a revision undone by a stale re-read, two bases overwriting
each other, or a slice that keeps hammering the exchange after it has started
refusing.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _series(sym="ACME", basis="consolidated", filed="14-Aug-2026 18:00:00",
            revenue=1.5e9, period_end="2026-06-30"):
    return {
        "available": True, "symbol": sym, "company": "Acme Ltd", "basis": basis,
        "rows": [{
            "period_end": period_end, "label": "Q1 FY27", "from": "2026-04-01",
            "filed_at": filed, "audited": "Un-Audited", "source": "https://x/1.xml",
            "values": {"revenue": revenue, "pat": 2e8, "ebitda": 3e8, "eps_basic": 4.25},
            "ratios": {"opm_pct": 20.0, "net_margin_pct": 13.33},
            "yoy": {"revenue": {"pct": 12.5}, "pat": {"pct": None}},
        }],
    }


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("ALTAHA_FUNDAMENTALS_DB", str(tmp_path / "f.db"))
    for m in ("fundamentals_store", "fundamentals_crawl"):
        sys.modules.pop(m, None)
    import fundamentals_store
    return fundamentals_store


def test_a_series_lands_as_one_row_per_quarter_in_crore(store):
    assert store.record_series(_series()) == 1
    (r,) = store.rows("ACME")
    assert r["revenue_cr"] == 150.0 and r["pat_cr"] == 20.0
    assert r["eps_basic"] == 4.25            # rupees per share, not crore
    assert r["revenue_yoy_pct"] == 12.5 and r["pat_yoy_pct"] is None
    assert r["filed_at"] == "2026-08-14 18:00:00"
    assert r["quarter"] == "Q1 FY27" and r["basis"] == "consolidated"


def test_a_revision_wins_and_an_older_filing_never_undoes_it(store):
    store.record_series(_series(filed="14-Aug-2026", revenue=1.5e9))
    store.record_series(_series(filed="02-Sep-2026", revenue=1.6e9))
    assert store.rows("ACME")[0]["revenue_cr"] == 160.0
    # '14-Aug' sorts after '02-Sep' as text; compared as dates it must not win.
    store.record_series(_series(filed="14-Aug-2026", revenue=1.5e9))
    assert store.rows("ACME")[0]["revenue_cr"] == 160.0


def test_the_two_bases_never_overwrite_each_other(store):
    store.record_series(_series(basis="consolidated", revenue=2.69e12))
    store.record_series(_series(basis="standalone", revenue=1.26e12))
    got = {r["basis"]: r["revenue_cr"] for r in store.rows("ACME")}
    assert got == {"consolidated": 269000.0, "standalone": 126000.0}


def test_an_unavailable_series_writes_nothing(store):
    assert store.record_series({"available": False, "symbol": "ACME"}) == 0
    assert store.rows() == []


def test_csv_has_the_header_and_the_row(store):
    store.record_series(_series())
    text = store.to_csv(store.rows())
    head, line = text.strip().splitlines()
    assert head.split(",")[:3] == ["symbol", "company", "basis"]
    assert line.startswith("ACME,Acme Ltd,consolidated")


def test_never_tried_companies_come_first(store):
    store.mark_coverage("B", "ok", ok=True)
    assert store.due_symbols(["A", "B", "C"], limit=5) == ["A", "C"]


class _FakeFundamentals:
    def __init__(self, answers):
        self.answers, self.calls = answers, []

    def series(self, sym, quarters=8):
        self.calls.append(sym)
        a = self.answers.get(sym)
        if isinstance(a, Exception):
            raise a
        return a or {"available": False, "symbol": sym,
                     "message": "No quarterly results filing could be read for %s right now." % sym}


def _crawl(store, monkeypatch, answers, universe):
    import fundamentals_crawl as fc
    fake = _FakeFundamentals(answers)
    monkeypatch.setattr(fc, "fundamentals", fake)
    monkeypatch.setattr(fc, "universe", lambda: universe)
    monkeypatch.setitem(sys.modules, "xbrl", type(sys)("xbrl"))
    sys.modules["xbrl"].available = lambda: True
    return fc, fake


def test_a_slice_reads_what_is_due_and_records_coverage(store, monkeypatch):
    fc, fake = _crawl(store, monkeypatch, {"ACME": _series()}, ["ACME", "NOFILE"])
    out = fc.run(limit=10, pause=0)
    assert out["attempted"] == 2 and out["ok"] == 1 and out["rows"] == 1
    assert out["store"]["coverage"] == {"ok": 1, "no-filings": 1}
    # Both were tried, so neither is due again today.
    assert fc.run(limit=10, pause=0)["stopped_early"] == "nothing due"


def test_a_run_of_refusals_stops_the_slice(store, monkeypatch):
    universe = ["S%02d" % i for i in range(20)]
    fc, fake = _crawl(store, monkeypatch,
                      {s: RuntimeError("403") for s in universe}, universe)
    out = fc.run(limit=20, pause=0)
    assert out["attempted"] == fc.GIVE_UP_AFTER
    assert "stopping" in out["stopped_early"]
