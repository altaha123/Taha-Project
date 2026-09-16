"""
The crawler.

A sweep of two thousand companies against a throttling exchange has one
failure mode that matters and it is not crashing: it is continuing. A crawler
that keeps asking after the exchange has started refusing collects nothing and
earns a longer ban, so the bounds below are the feature.
"""

import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _name(n, pct):
    return {"name": n, "pct": pct, "shares": None, "kind": "Other", "promoter": False}


class FakeShp:
    """Stands in for shareholding_filings."""

    def __init__(self, index_rows=None, filings=None, index_raises=False):
        self._index = index_rows if index_rows is not None else {}
        self._filings = filings or {}
        self._index_raises = index_raises
        self.index_calls, self.filing_calls = [], []

    def available(self):
        return True

    def is_quarter_end(self, iso):
        return iso[5:] in ("03-31", "06-30", "09-30", "12-31")

    def index(self, symbol):
        self.index_calls.append(symbol)
        if self._index_raises:
            raise RuntimeError("NSE said no")
        return self._index.get(symbol, [])

    def filing(self, url, period="", filed="", revised=False):
        self.filing_calls.append(url)
        return self._filings.get(url)


@pytest.fixture()
def crawl(tmp_path, monkeypatch):
    monkeypatch.setenv("ALTAHA_HOLDINGS_DB", str(tmp_path / "h.db"))
    for m in ("holdings_store", "holdings_crawl"):
        sys.modules.pop(m, None)
    import holdings_store as store
    import holdings_crawl as hc
    monkeypatch.setattr(hc, "PAUSE", 0)
    monkeypatch.setattr(hc, "universe", lambda: [])
    return hc, store


def _quarter_index(*periods):
    return [{"period": p, "quarter_end": True, "xbrl": "u/" + p,
             "filed": p, "revised": False} for p in periods]


def test_a_company_is_read_into_the_ledger(crawl):
    hc, store = crawl
    shp = FakeShp(
        index_rows={"ATULAUTO": _quarter_index("2026-06-30", "2026-03-31")},
        filings={
            "u/2026-06-30": {"period_end": "2026-06-30",
                             "names": [_name("VIJAY KEDIA", 18.2)]},
            "u/2026-03-31": {"period_end": "2026-03-31",
                             "names": [_name("VIJAY KEDIA", 18.0)]},
        })
    hc.shp = shp
    r = hc.crawl_symbol("ATULAUTO", quarters=4)
    assert r["ok"] and r["quarters"] == 2 and r["rows"] == 2
    assert len(store.positions_for_keys(["vijay kedia"])) == 2


def test_an_interim_filing_is_not_taken_for_a_quarter(crawl):
    """Regulation 31 also requires a filing within ten days of a capital
    change. It is a real document and it is not a point on a quarterly series;
    mixing the two makes a stake look like it moved when only the date did."""
    hc, store = crawl
    idx = _quarter_index("2026-06-30")
    idx.insert(0, {"period": "2026-07-14", "quarter_end": False,
                   "xbrl": "u/interim", "filed": "2026-07-14"})
    hc.shp = FakeShp(index_rows={"X": idx}, filings={
        "u/2026-06-30": {"period_end": "2026-06-30", "names": [_name("A Holder", 2.0)]},
        "u/interim": {"period_end": "2026-07-14", "names": [_name("A Holder", 9.9)]},
    })
    r = hc.crawl_symbol("X", quarters=4)
    assert r["quarters"] == 1
    assert {p["period_end"] for p in store.positions_for_keys(["a holder"])} == {"2026-06-30"}


def test_only_the_quarters_asked_for_are_fetched(crawl):
    """Each quarter is a separate document over the wire; the bound is the
    point."""
    hc, _store = crawl
    shp = FakeShp(
        index_rows={"X": _quarter_index("2026-06-30", "2026-03-31", "2025-12-31",
                                        "2025-09-30", "2025-06-30")},
        filings={"u/%s" % p: {"period_end": p, "names": [_name("A Holder", 1.0)]}
                 for p in ("2026-06-30", "2026-03-31", "2025-12-31",
                           "2025-09-30", "2025-06-30")})
    hc.shp = shp
    hc.crawl_symbol("X", quarters=2)
    assert len(shp.filing_calls) == 2


def test_a_company_with_no_filings_is_recorded_as_such(crawl):
    hc, store = crawl
    hc.shp = FakeShp(index_rows={})
    r = hc.crawl_symbol("NOSUCH")
    assert r["ok"] is False and r["status"] == "no-filings"
    conn = store._connect()
    assert conn.execute("SELECT status FROM coverage WHERE symbol='NOSUCH'"
                        ).fetchone()["status"] == "no-filings"


def test_a_raising_reader_does_not_take_the_run_with_it(crawl):
    hc, _store = crawl
    hc.shp = FakeShp(index_raises=True)
    r = hc.crawl_symbol("X")
    assert r["ok"] is False and "NSE said no" in r["note"]


def test_a_failing_company_does_not_stop_the_others(crawl):
    hc, _store = crawl
    hc.shp = FakeShp(
        index_rows={"GOOD": _quarter_index("2026-06-30"), "BAD": []},
        filings={"u/2026-06-30": {"period_end": "2026-06-30",
                                  "names": [_name("A Holder", 1.0)]}})
    out = hc.run(limit=5, symbols=["BAD", "GOOD", "BAD", "GOOD"], pause=0)
    assert out["attempted"] == 4 and out["ok"] == 2


def test_the_run_gives_up_after_a_run_of_real_failures(crawl):
    """Not after companies that simply have no filing — that is an answer about
    the company, not a refusal from the exchange."""
    hc, _store = crawl
    hc.shp = FakeShp(index_raises=True)
    out = hc.run(limit=100, symbols=["S%d" % i for i in range(50)], pause=0)
    assert out["attempted"] == hc.GIVE_UP_AFTER
    assert "hammer a rate limiter" in out["stopped_early"]


def test_companies_with_no_filings_never_trigger_the_give_up(crawl):
    hc, _store = crawl
    hc.shp = FakeShp(index_rows={})
    out = hc.run(limit=20, symbols=["S%d" % i for i in range(20)], pause=0)
    assert out["attempted"] == 20
    assert out["stopped_early"] is None


def test_a_second_run_continues_rather_than_restarting(crawl):
    """What makes a two-thousand-company sweep possible in slices at all."""
    hc, store = crawl
    hc.shp = FakeShp(
        index_rows={s: _quarter_index("2026-06-30") for s in ("A", "B", "C", "D")},
        filings={"u/2026-06-30": {"period_end": "2026-06-30",
                                  "names": [_name("A Holder", 1.0)]}})
    monkey = ["A", "B", "C", "D"]
    hc.universe = lambda: monkey
    first = hc.run(limit=2, pause=0)
    second = hc.run(limit=2, pause=0)
    done_first = {r["symbol"] for r in first["results"]}
    done_second = {r["symbol"] for r in second["results"]}
    assert len(done_first) == 2 and len(done_second) == 2
    assert not (done_first & done_second), "a run must not repeat the last one's work"


def test_a_reader_that_is_not_installed_stops_before_touching_the_network(crawl):
    hc, _store = crawl
    shp = FakeShp()
    shp.available = lambda: False
    hc.shp = shp
    out = hc.run(limit=10, symbols=["X"], pause=0)
    assert out["attempted"] == 0
    assert "curl_cffi" in out["stopped_early"]
    assert shp.index_calls == []


def test_an_unreadable_filing_is_not_silently_an_empty_company(crawl):
    hc, store = crawl
    hc.shp = FakeShp(index_rows={"X": _quarter_index("2026-06-30")}, filings={})
    r = hc.crawl_symbol("X")
    assert r["ok"] is False and r["status"] == "unreadable"
    assert store.holders_of("X") == []
