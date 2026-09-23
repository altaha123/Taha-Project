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


# ---------------------------------------------------------------------------
# Yahoo statements
# ---------------------------------------------------------------------------

def test_a_yahoo_statement_pivots_items_by_period_in_crore(store):
    store.record_yf("TCS", "balance", "annual", {
        ("2026-03-31", "Total Assets"): 1.82e12,
        ("2025-03-31", "Total Assets"): 1.60e12,
        ("2026-03-31", "Ordinary Shares Number"): 3.6e9,
        ("2025-03-31", "Inventory"): float("nan"),   # padding, not zero
    })
    t = store.yf_statement("TCS", "balance", "annual", crore=True)
    assert t["periods"] == ["2026-03-31", "2025-03-31"]
    rows = {r["item"]: r for r in t["rows"]}
    assert rows["Total Assets"]["2026-03-31"] == 182000.0
    assert rows["Ordinary Shares Number"]["2026-03-31"] == 3.6e9   # a count, left alone
    assert "Inventory" not in rows
    head = store.yf_statement_csv(t).splitlines()[0]
    assert head == "item,2026-03-31,2025-03-31"


def test_a_yahoo_restatement_replaces_the_old_value(store):
    store.record_yf("TCS", "income", "annual", {("2026-03-31", "Total Revenue"): 1.0e12})
    store.record_yf("TCS", "income", "annual", {("2026-03-31", "Total Revenue"): 1.1e12})
    t = store.yf_statement("TCS", "income", "annual")
    assert t["rows"] == [{"item": "Total Revenue", "2026-03-31": 1.1e12}]


class _Frame:
    """The slice of a pandas frame the crawler touches."""

    def __init__(self, data):
        import pandas as pd
        self._df = pd.DataFrame(data)
        self._df.columns = pd.to_datetime(self._df.columns)

    def __getattr__(self, name):
        return getattr(self._df, name)

    def __getitem__(self, k):
        return self._df[k]


def test_the_yahoo_crawl_stores_all_six_frames_and_its_own_coverage(store, monkeypatch):
    import fundamentals_crawl as fc
    frame = _Frame({"2026-03-31": {"Total Assets": 5e9}})

    class T:
        pass
    t = T()
    for attr, _s, _f in fc.YF_FRAMES:
        setattr(t, attr, frame)
    monkeypatch.setattr(fc, "_ticker", lambda sym: t)
    out = fc.run(symbols=["ACME"], pause=0, source="yfinance")
    assert out["results"][0]["statements"] == 6
    assert out["store"]["yfinance"]["coverage"] == {"ok": 1}
    # The exchange sweep has its own queue and has not been touched.
    assert store.due_symbols(["ACME"], source="nse") == ["ACME"]


def test_a_run_of_empty_yahoo_answers_is_treated_as_throttling(store, monkeypatch):
    import fundamentals_crawl as fc
    import pandas as pd

    class T:
        pass
    t = T()
    for attr, _s, _f in fc.YF_FRAMES:
        setattr(t, attr, pd.DataFrame())
    monkeypatch.setattr(fc, "_ticker", lambda sym: t)
    monkeypatch.setattr(fc, "universe", lambda: ["S%02d" % i for i in range(20)])
    out = fc.run(limit=20, pause=0, source="yfinance")
    assert out["attempted"] == fc.GIVE_UP_AFTER
