"""
The three statement tables and the crawl that fills them.

The failure that matters here is not a crash, it is a table that quietly says
the wrong thing: a revision undone by a stale re-read, a quarter stored as a
year, a re-crawl that fetches thirty documents it already has, or a slice
that keeps hammering the exchange after it has started refusing.
"""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("ALTAHA_FUNDAMENTALS_DB", str(tmp_path / "f.db"))
    for m in ("fundamentals_store", "fundamentals_crawl"):
        sys.modules.pop(m, None)
    import fundamentals_store
    return fundamentals_store


def _doc(name):
    import xbrl
    return xbrl.normalise(xbrl.parse((FIXTURES / name).read_text(encoding="utf-8")))


META = {"to": "31-MAR-2026", "filed_at": "23-Apr-2026 18:00:00",
        "audited": "Audited", "xbrl": "https://x/tcs-q4fy26.xml"}


def test_one_march_filing_fills_all_three_tables(store):
    import fundamentals_crawl as fc
    built = fc.build_rows("TCS", "Tata Consultancy", "consolidated", META,
                          _doc("tcs_q4fy26.xml"))
    inc = {r["freq"]: r for r in built["income"]}
    assert inc["quarterly"]["label"] == "Q4 FY26" and inc["quarterly"]["revenue_cr"] == 70698.0
    assert inc["annual"]["label"] == "FY26" and inc["annual"]["revenue_cr"] == 267021.0
    assert inc["annual"]["months"] == 12 and inc["annual"]["opm_pct"] is not None
    (cf,) = built["cashflow"]
    assert (cf["label"], cf["months"]) == ("FY26", 12)
    assert cf["cfo_cr"] == 52094.0
    assert cf["fcf_cr"] == round(cf["cfo_cr"] - cf["capex_cr"], 2)
    (bs,) = built["balance"]
    assert bs["label"] == "Mar 2026" and bs["total_assets_cr"] == 182372.0
    assert bs["current_ratio_x"] == pytest.approx(135705 / 60914, abs=0.01)
    assert bs["filed_at"] == "2026-04-23 18:00:00"


def test_a_bank_gets_its_equity_from_capital_and_reserves(store):
    import fundamentals_crawl as fc
    built = fc.build_rows("HDFCBANK", "HDFC Bank", "consolidated",
                          {**META, "xbrl": "https://x/hdfc.xml"}, _doc("hdfcbank_q4fy26.xml"))
    (bs,) = built["balance"]
    assert bs["total_equity_cr"] == pytest.approx(1539 + 579975, abs=2)
    assert bs["deposits_cr"] > 0 and bs["debt_equity_x"] is not None


def _income(freq="quarterly", end="2026-06-30", revenue=100.0, filed="2026-07-10"):
    return {"symbol": "ACME", "company": "Acme", "basis": "consolidated",
            "freq": freq, "label": "x", "period_end": end, "months": 3,
            "filed_at": filed, "revenue_cr": revenue, "pat_cr": revenue / 10}


def test_a_revision_wins_and_an_older_filing_never_undoes_it(store):
    store.upsert("income", [_income(revenue=100.0, filed="2026-07-10")])
    store.upsert("income", [_income(revenue=110.0, filed="2026-08-02")])
    store.upsert("income", [_income(revenue=100.0, filed="2026-07-10")])
    assert store.rows("income", "ACME")[0]["revenue_cr"] == 110.0


def test_iso_dates_sort_where_nse_dates_do_not(store):
    # '14-Aug' sorts after '02-Sep' as text; compared as dates it must not win.
    assert store._iso("14-Aug-2026") < store._iso("02-Sep-2026")


def test_year_on_year_is_against_the_same_period_a_year_earlier(store):
    store.upsert("income", [_income(end="2025-06-30", revenue=100.0),
                            _income(end="2026-03-31", revenue=500.0),
                            _income(end="2026-06-30", revenue=125.0),
                            _income(freq="annual", end="2026-03-31", revenue=400.0)])
    store.recompute_yoy("ACME")
    got = {(r["freq"], r["period_end"]): r["revenue_yoy_pct"]
           for r in store.rows("income", "ACME")}
    assert got[("quarterly", "2026-06-30")] == 25.0
    assert got[("quarterly", "2026-03-31")] is None      # no year-earlier quarter
    assert got[("annual", "2026-03-31")] is None          # never against a quarter


def test_csv_has_the_header_and_the_row(store):
    store.upsert("income", [_income()])
    head, line = store.to_csv("income", store.rows("income")).strip().splitlines()
    assert head.split(",")[:4] == ["symbol", "company", "basis", "freq"]
    assert line.startswith("ACME,Acme,consolidated,quarterly")


def test_never_tried_companies_come_first(store):
    store.mark_coverage("B", "ok", ok=True)
    assert store.due_symbols(["A", "B", "C"], limit=5) == ["A", "C"]


class _FakeXbrl:
    """Stands in for xbrl: an index, and documents that answer or refuse."""

    def __init__(self, index, docs):
        self.index, self.docs, self.fetched = index, docs, []

    def filings(self, sym):
        return self.index

    def fetch(self, url, cache=True):
        self.fetched.append(url)
        return self.docs.get(url)


def _index(n):
    import datetime as dt
    out = []
    for i in range(n):
        end = dt.date(2026, 3, 31) - dt.timedelta(days=91 * i)
        out.append({"to": end.strftime("%d-%b-%Y"), "consolidated": True,
                    "company": "Acme", "filed_at": "01-Jan-2026",
                    "xbrl": "https://x/%d.xml" % i})
    return out


def _quarter_doc(rev=1e9):
    return {"revenue": rev, "pat": rev / 10, "period": {}}


def _crawl(store, monkeypatch, fake):
    import fundamentals_crawl as fc
    monkeypatch.setitem(sys.modules, "xbrl", fake)
    monkeypatch.setattr(fc, "DOC_PAUSE", 0)
    return fc


def test_a_re_crawl_fetches_only_what_it_has_not_read(store, monkeypatch):
    idx = _index(6)
    fake = _FakeXbrl(idx, {f["xbrl"]: _quarter_doc() for f in idx})
    fc = _crawl(store, monkeypatch, fake)
    r = fc.crawl_symbol("ACME")
    assert r["status"] == "ok" and r["documents"] == 6
    assert len(store.rows("income", "ACME")) == 6
    fake.fetched.clear()
    assert fc.crawl_symbol("ACME")["documents"] == 0
    assert fake.fetched == []


def test_a_run_of_refused_documents_leaves_the_company_half_read(store, monkeypatch):
    idx = _index(12)
    fake = _FakeXbrl(idx, {idx[0]["xbrl"]: _quarter_doc()})    # the rest refuse
    fc = _crawl(store, monkeypatch, fake)
    r = fc.crawl_symbol("ACME")
    assert r["status"] == "partial" and r["documents"] == 1
    assert r["outstanding"] == 11
    assert len(fake.fetched) == 1 + 2 * fc.DOC_GIVE_UP     # one retry each, then stop


def test_a_run_of_refusing_companies_stops_the_slice(store, monkeypatch):
    import fundamentals_crawl as fc

    def boom(sym, **kw):
        store.mark_coverage(sym, "error")
        return {"symbol": sym, "ok": False, "rows": 0, "status": "error", "note": "403"}
    monkeypatch.setattr(fc, "crawl_symbol", boom)
    monkeypatch.setattr(fc, "universe", lambda: ["S%02d" % i for i in range(20)])
    monkeypatch.setitem(sys.modules, "xbrl", type(sys)("xbrl"))
    sys.modules["xbrl"].available = lambda: True
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


# ---------------------------------------------------------------------------
# Upgrading a database built by an earlier version
# ---------------------------------------------------------------------------

def test_an_old_database_gains_the_new_columns_and_its_filings_come_due(tmp_path, monkeypatch):
    """The live disk holds tables from before the profit-reconciliation lines
    and before docs had a version. Opening it must add both, keep every row,
    and put the companies read by the old parser back in the queue — ahead of
    the merely stale, behind the never-tried."""
    import sqlite3
    db = tmp_path / "old.db"
    c = sqlite3.connect(db)
    c.executescript("""
      CREATE TABLE income_statement (symbol TEXT NOT NULL, company TEXT, basis TEXT NOT NULL,
        freq TEXT NOT NULL, label TEXT, period_from TEXT, period_end TEXT NOT NULL,
        months INTEGER NOT NULL DEFAULT 0, filed_at TEXT, audited TEXT, revenue_cr REAL,
        pat_cr REAL, source_url TEXT, updated_utc TEXT NOT NULL, first_seen_utc TEXT NOT NULL,
        PRIMARY KEY (symbol, basis, freq, period_end));
      CREATE TABLE docs (symbol TEXT NOT NULL, source_url TEXT NOT NULL, period_end TEXT,
        read_utc TEXT NOT NULL, PRIMARY KEY (symbol, source_url)) WITHOUT ROWID;
      CREATE TABLE coverage (symbol TEXT PRIMARY KEY, last_try_utc TEXT, last_ok_utc TEXT,
        latest_period TEXT, quarters INTEGER NOT NULL DEFAULT 0, basis TEXT, status TEXT, note TEXT);
      INSERT INTO income_statement VALUES ('OLD','Old','consolidated','annual','FY26',
        '2025-04-01','2026-03-31',12,'2026-05-01',NULL,100,10,'u','2026-05-02','2026-05-02');
      INSERT INTO docs VALUES ('OLD','https://x/1.xml','2026-03-31','2026-09-24T00:00:00+00:00');
      INSERT INTO coverage VALUES ('OLD','2099-01-01T00:00:00+00:00',NULL,NULL,1,'consolidated','ok','');
      INSERT INTO coverage VALUES ('STALE','2000-01-01T00:00:00+00:00',NULL,NULL,1,'consolidated','ok','');
    """)
    c.commit(); c.close()
    monkeypatch.setenv("ALTAHA_FUNDAMENTALS_DB", str(db))
    for m in ("fundamentals_store", "fundamentals_crawl"):
        sys.modules.pop(m, None)
    import fundamentals_store as fs

    (row,) = fs.rows("income", "OLD")
    assert row["revenue_cr"] == 100 and row["pat_owners_cr"] is None     # kept; new column there
    assert fs.read_docs("OLD") == set()                                  # read by the old parser
    # Both were read by the old parser, so both are due — OLD although it was
    # "tried" in the future — never-tried first, then oldest attempt first.
    assert fs.due_symbols(["OLD", "STALE", "NEW"], limit=5) == ["NEW", "STALE", "OLD"]
    fs.mark_doc("OLD", "https://x/1.xml", "2026-03-31")
    fs.mark_coverage("OLD", "ok", ok=True)
    assert fs.read_docs("OLD") == {"https://x/1.xml"}
    assert "OLD" not in fs.due_symbols(["OLD"], limit=5)
