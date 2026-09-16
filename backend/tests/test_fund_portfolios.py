"""
The fund-house pipeline: AMFI's directory, the ISIN map, and ingest.

Two things here are load-bearing and neither is obvious:

  · the month a pack describes. A file called ...31-08-2026.xls is the August
    portfolio, and filing it under any other month puts one AMC's positions
    beside another's from a different date and calls the difference a change.

  · the ISIN map. It is the ONLY thing separating listed equity from the debt,
    government securities and trust units in the same workbook, and it is
    fetched from an exchange that throttles. A stale map is fine and is said to
    be stale; an empty one silently turns every holding into an unmatched row.
"""

import datetime as dt
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture()
def fp(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ALTAHA_HOLDINGS_DB", str(tmp_path / "h.db"))
    for m in ("holdings_store", "fund_portfolios"):
        sys.modules.pop(m, None)
    import fund_portfolios as mod
    return mod


# ---------------------------------------------------------------------------
# Which month a pack describes
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text,want", [
    ("BOBBNPMF_Monthly_Portfolio_31-08-2026_19961.xls", "2026-08-31"),
    ("Monthly-Portfolio-August-2026.xlsx", "2026-08-31"),
    ("2026-07-31_pack.xlsx", "2026-07-31"),
    ("portfolio_30-06-2026.xlsx", "2026-06-30"),
    ("Monthly Portfolio Feb 2024.xlsx", "2024-02-29"),     # a leap February
    ("Monthly Portfolio Feb 2026.xlsx", "2026-02-28"),
    ("Portfolio-December-2025.xlsx", "2025-12-31"),        # rolls the year
    ("some-file-with-no-date.xlsx", None),
])
def test_the_month_is_read_and_normalised_to_its_last_day(fp, text, want):
    """Whatever day the file is named for, a monthly portfolio is as at month
    end — and every AMC has to land on the same date or a comparison across
    houses compares different days."""
    assert fp.month_end_from(text) == want


def test_an_impossible_date_is_refused_rather_than_coerced(fp):
    assert fp.month_end_from("portfolio_31-13-2026.xlsx") is None
    assert fp.month_end_from("portfolio_31-00-2026.xlsx") is None


# ---------------------------------------------------------------------------
# The AMFI directory
# ---------------------------------------------------------------------------

def test_the_directory_is_read_out_of_the_streamed_payload(fp, monkeypatch):
    """AMFI's page is a JavaScript app: there is no rendered table in the HTML,
    only escaped chunks the framework streams. Scraping the table would find
    nothing."""
    record = {
        "mf_id": "20", "mf_name": "Baroda BNP Paribas Mutual Fund",
        "amc_name": "BNP Paribas Asset Management India Private Limited",
        "amc_website": "www.barodabnpparibasmf.in",
        "amc_monthly_portfolio_disclosure":
            "https://www.barodabnpparibasmf.in/downloads/monthly-portfolio-scheme",
        "icons": [],
    }
    inner = json.dumps(record).replace('"', '\\"')
    html = 'x<script>self.__next_f.push([1,"%s"])</script>y' % inner
    monkeypatch.setattr(fp, "_http", lambda url, timeout=40: html.encode())
    out = fp.amc_directory()
    assert len(out) == 1
    assert out[0]["amc_id"] == "20"
    assert out[0]["name"] == "Baroda BNP Paribas Mutual Fund"
    assert out[0]["monthly_url"].endswith("monthly-portfolio-scheme")


def test_an_unreachable_directory_is_empty_not_an_exception(fp, monkeypatch):
    monkeypatch.setattr(fp, "_http", lambda url, timeout=40: None)
    assert fp.amc_directory() == []


def test_a_directory_with_no_payload_is_empty(fp, monkeypatch):
    monkeypatch.setattr(fp, "_http", lambda url, timeout=40: b"<html>nothing</html>")
    assert fp.amc_directory() == []


# ---------------------------------------------------------------------------
# Finding a workbook on an AMC's own page
# ---------------------------------------------------------------------------

def test_workbook_links_are_found_and_made_absolute(fp, monkeypatch):
    html = b'''<a href="/files/other.pdf">x</a>
               <a href="/files/Scheme_Details.xlsx">x</a>
               <a href="/files/Monthly_Portfolio_31-08-2026.xls">x</a>'''
    monkeypatch.setattr(fp, "_http", lambda url, timeout=40: html)
    links = fp.find_workbooks("https://amc.test/downloads/disclosures")
    assert all(l.startswith("https://amc.test/") for l in links)
    # The monthly pack is ranked above a scheme-details workbook.
    assert "Monthly_Portfolio" in links[0]


def test_a_javascript_built_page_yields_nothing_rather_than_a_wrong_guess(fp, monkeypatch):
    """Roughly two fifths of AMCs build their download list client-side. That
    is a coverage gap, reported as one — not a fund house that published
    nothing."""
    monkeypatch.setattr(fp, "_http",
                        lambda url, timeout=40: b'<div id="root"></div>')
    assert fp.find_workbooks("https://amc.test/downloads") == []


def test_duplicate_links_are_collapsed(fp, monkeypatch):
    html = b'<a href="/a.xlsx">1</a><a href="/a.xlsx">2</a><a href="/a.xlsx">3</a>'
    monkeypatch.setattr(fp, "_http", lambda url, timeout=40: html)
    assert len(fp.find_workbooks("https://amc.test/d")) == 1


# ---------------------------------------------------------------------------
# The ISIN map
# ---------------------------------------------------------------------------

CSV = ("SYMBOL,NAME OF COMPANY, SERIES, DATE OF LISTING, PAID UP VALUE,"
       " MARKET LOT, ISIN NUMBER, FACE VALUE\n"
       "RELIANCE,Reliance Industries Limited,EQ,29-NOV-1995,10,1,INE002A01018,10\n"
       "HDFCBANK,HDFC Bank Limited,EQ,08-NOV-1995,1,1,INE040A01034,1\n"
       "SOMEBOND,Some Debt Thing,N1,01-JAN-2020,10,1,INE999Z08011,10\n")


def _serve(fp, monkeypatch, text):
    monkeypatch.setattr(fp, "nse_http", None)
    monkeypatch.setattr(fp, "_http",
                        lambda url, timeout=40: text.encode() if text else None)


def test_the_equity_list_is_parsed_into_a_map(fp, monkeypatch):
    _serve(fp, monkeypatch, CSV)
    m, meta = fp.isin_map(refresh=True)
    assert m["INE002A01018"] == "RELIANCE"
    assert m["INE040A01034"] == "HDFCBANK"
    assert meta["stale"] is False


def test_non_equity_series_are_left_out(fp, monkeypatch):
    """The map is what separates shares from the debt in the same workbook, so
    a debt series in it would defeat the filter."""
    _serve(fp, monkeypatch, CSV)
    m, _meta = fp.isin_map(refresh=True)
    assert "INE999Z08011" not in m


def test_the_map_is_cached_and_reused(fp, monkeypatch):
    calls = []

    def once(url, timeout=40):
        calls.append(url)
        return CSV.encode()

    monkeypatch.setattr(fp, "nse_http", None)
    monkeypatch.setattr(fp, "_http", once)
    fp.isin_map(refresh=True)
    fp.isin_map()
    fp.isin_map()
    assert len(calls) == 1, "the exchange throttles; the map changes weekly"


def test_a_failed_refresh_falls_back_to_the_cache_and_says_it_is_stale(fp, monkeypatch):
    """A map from last month maps essentially every holding correctly. Mapping
    nothing because it could not be refreshed would be far worse — every
    position would land in the unmatched pile."""
    _serve(fp, monkeypatch, CSV)
    fp.isin_map(refresh=True)
    _serve(fp, monkeypatch, None)
    m, meta = fp.isin_map(refresh=True)
    assert m["INE002A01018"] == "RELIANCE"
    assert meta["stale"] is True
    assert "could not be refreshed" in meta["note"]


def test_with_no_cache_and_no_fetch_the_map_is_empty_and_says_so(fp, monkeypatch):
    _serve(fp, monkeypatch, None)
    m, meta = fp.isin_map(refresh=True)
    assert m == {} and meta["stale"] is True and meta["note"]


def test_a_stale_cache_is_refreshed(fp, monkeypatch, tmp_path):
    old = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=90))
    Path(fp.ISIN_CACHE).write_text(json.dumps({
        "fetched_utc": old.isoformat(timespec="seconds"),
        "map": {"INEOLD0A01010": "OLD"}}))
    _serve(fp, monkeypatch, CSV)
    m, meta = fp.isin_map()
    assert "INE002A01018" in m and meta["stale"] is False


# ---------------------------------------------------------------------------
# Ingest
# ---------------------------------------------------------------------------

def _pack():
    return [{"sheet": "T0ME02", "holdings": [
        {"isin": "INE002A01018", "name": "Reliance Industries Limited",
         "industry": "Petroleum", "quantity": 1000, "value_lakh": 250.5,
         "pct_nav": 3.33, "scheme": "T0ME02"},
        {"isin": "INE999Z08011", "name": "Some Debenture",
         "industry": "AAA", "quantity": 50, "value_lakh": 500.0,
         "pct_nav": 6.6, "scheme": "T0ME02"},
        {"isin": "INE777Y01011", "name": "An Unlisted Company",
         "industry": "X", "quantity": 10, "value_lakh": 1.0,
         "pct_nav": 0.01, "scheme": "T0ME02"},
    ]}]


def _stub_ingest(fp, monkeypatch, packs=None):
    monkeypatch.setattr(fp, "_http", lambda url, timeout=40: b"PK\x03\x04fake")
    monkeypatch.setattr(fp.fund_workbook, "looks_like_xlsx", lambda b: True)
    monkeypatch.setattr(fp.fund_workbook, "parse_workbook",
                        lambda path, **kw: packs if packs is not None else _pack())
    monkeypatch.setattr(fp.fund_workbook, "scheme_names",
                        lambda path: {"T0ME02": "Baroda BNP Paribas Mid Cap Fund"})


def test_only_listed_equity_is_kept_and_the_rest_is_counted(fp, monkeypatch):
    """A pack carries the whole book. The debenture must not become an equity
    position, and the unlisted holding must be kept and counted rather than
    dropped — otherwise the weights on screen add up to less than the fund
    holds with nothing saying why."""
    _stub_ingest(fp, monkeypatch)
    import holdings_store as store
    out = fp.ingest_url("20", "Baroda BNP Paribas Mutual Fund",
                        "https://amc.test/Monthly_Portfolio_31-08-2026.xlsx",
                        mapping={"INE002A01018": "RELIANCE"})
    assert out["ok"] is True
    assert out["as_of"] == "2026-08-31"
    rows = store.fund_positions("20")
    names = {r["name"] for r in rows}
    assert "Reliance Industries Limited" in names
    assert "Some Debenture" not in names, "a debenture is not an equity position"
    assert "An Unlisted Company" in names
    assert out["unmapped"] == 1
    assert next(r for r in rows if r["name"].startswith("Reliance"))["symbol"] == "RELIANCE"
    assert next(r for r in rows if r["name"].startswith("An Unlisted"))["symbol"] is None


def test_the_sheet_code_is_replaced_with_the_scheme_name(fp, monkeypatch):
    """Sheet names are internal codes. "T0ME02" on a page is useless."""
    _stub_ingest(fp, monkeypatch)
    import holdings_store as store
    fp.ingest_url("20", "X", "https://amc.test/p_31-08-2026.xlsx",
                  mapping={"INE002A01018": "RELIANCE"})
    assert store.fund_positions("20")[0]["scheme"] == "Baroda BNP Paribas Mid Cap Fund"


def test_reingesting_the_same_pack_writes_nothing(fp, monkeypatch):
    _stub_ingest(fp, monkeypatch)
    url = "https://amc.test/p_31-08-2026.xlsx"
    first = fp.ingest_url("20", "X", url, mapping={"INE002A01018": "RELIANCE"})
    again = fp.ingest_url("20", "X", url, mapping={"INE002A01018": "RELIANCE"})
    assert first["rows"] > 0
    assert again["rows"] == 0, "the ledger is append-only"


def test_a_pack_whose_month_cannot_be_read_is_refused(fp, monkeypatch):
    """Filing August's portfolio under the wrong month puts one AMC's positions
    beside another's from a different date and calls the difference a change."""
    _stub_ingest(fp, monkeypatch)
    out = fp.ingest_url("20", "X", "https://amc.test/portfolio.xlsx",
                        mapping={"INE002A01018": "RELIANCE"})
    assert out["ok"] is False
    assert "which month" in out["note"]


def test_a_legacy_xls_is_refused_with_a_readable_reason(fp, monkeypatch):
    monkeypatch.setattr(fp, "_http", lambda url, timeout=40: b"\xd0\xcf\x11\xe0old")
    out = fp.ingest_url("20", "X", "https://amc.test/p_31-08-2026.xls")
    assert out["ok"] is False
    assert "legacy .xls" in out["note"]


def test_a_download_that_fails_is_reported_not_raised(fp, monkeypatch):
    monkeypatch.setattr(fp, "_http", lambda url, timeout=40: None)
    out = fp.ingest_url("20", "X", "https://amc.test/p_31-08-2026.xlsx")
    assert out["ok"] is False and "could not download" in out["note"]


def test_an_amc_with_no_disclosure_page_is_skipped_with_a_reason(fp):
    out = fp.ingest_amc({"amc_id": "91", "name": "Carnelian Mutual Fund",
                         "monthly_url": ""})
    assert out["ok"] is False
    assert "no monthly disclosure page" in out["note"]


def test_a_run_reports_per_amc_rather_than_only_a_total(fp, monkeypatch):
    """Coverage is part of the answer here: a page showing 22 fund houses while
    looking like it shows the industry is the failure mode."""
    _stub_ingest(fp, monkeypatch)
    monkeypatch.setattr(fp, "find_workbooks",
                        lambda page: ["https://amc.test/p_31-08-2026.xlsx"]
                        if "good" in page else [])
    amcs = [{"amc_id": "1", "name": "Good AMC", "monthly_url": "https://good.test/d"},
            {"amc_id": "2", "name": "JS AMC", "monthly_url": "https://js.test/d"}]
    out = fp.run(limit=5, amcs=amcs, mapping={"INE002A01018": "RELIANCE"})
    assert out["attempted"] == 2 and out["ok"] == 1
    bad = next(r for r in out["results"] if r["amc_id"] == "2")
    assert "JavaScript" in bad["note"]


def test_a_run_is_bounded(fp, monkeypatch):
    _stub_ingest(fp, monkeypatch)
    monkeypatch.setattr(fp, "find_workbooks", lambda page: [])
    amcs = [{"amc_id": str(i), "name": "A%d" % i, "monthly_url": "https://a.test/d"}
            for i in range(30)]
    out = fp.run(limit=4, amcs=amcs, mapping={})
    assert out["attempted"] == 4, "each pack is a 15 MB download on a 512 MB box"
