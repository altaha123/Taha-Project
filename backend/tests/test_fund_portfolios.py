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
import io
import json
import sys
import tempfile
import zipfile
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


def _serve_download(fp, monkeypatch, blob, seen=None):
    """Stand in for the file download: every URL serves `blob` (None = 404).
    Downloads stream to a temporary file, so the stub writes one too."""
    def fake(url, timeout=180, headers=None):
        if seen is not None:
            seen.append(url)
        data = blob(url) if callable(blob) else blob
        if data is None:
            return None, "HTTP 404"
        fh = tempfile.NamedTemporaryFile(suffix=".dl", delete=False)
        fh.write(data)
        fh.close()
        return fh.name, None
    monkeypatch.setattr(fp, "_download", fake)


def _stub_ingest(fp, monkeypatch, packs=None):
    _serve_download(fp, monkeypatch, b"PK\x03\x04fake")
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


def test_a_damaged_legacy_xls_is_refused_with_a_readable_reason(fp, monkeypatch):
    """The legacy format is read now (Aditya Birla Sun Life publishes it), so
    what is left to refuse is a file that only looks like one."""
    _serve_download(fp, monkeypatch, b"\xd0\xcf\x11\xe0old")
    out = fp.ingest_url("20", "X", "https://amc.test/p_31-08-2026.xls")
    assert out["ok"] is False
    assert "legacy .xls" in out["note"]


def test_a_page_that_is_not_a_workbook_is_refused_with_a_readable_reason(fp, monkeypatch):
    _serve_download(fp, monkeypatch, b"<html>Access Denied</html>")
    out = fp.ingest_url("20", "X", "https://amc.test/p_31-08-2026.xlsx")
    assert out["ok"] is False
    assert "not an xlsx workbook" in out["note"]


def test_a_download_that_fails_is_reported_not_raised(fp, monkeypatch):
    _serve_download(fp, monkeypatch, None)
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


# ---------------------------------------------------------------------------
# Why the live ledger read nothing (November 2026), and what fixed it
# ---------------------------------------------------------------------------

TODAY = dt.date(2026, 11, 11)
FIXTURES = Path(__file__).resolve().parent / "fixtures"

HDR = ("Name of the Instrument", "ISIN", "Industry / Rating", "Quantity",
       "Market/Fair Value (Rs. in Lakhs)", "% to NAV")


def _xlsx(sheets):
    """A real xlsx, as bytes: {sheet: [rows]}."""
    import openpyxl
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for title, rows in sheets.items():
        ws = wb.create_sheet(title)
        for r in rows:
            ws.append(list(r))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _scheme_book(title, holdings, as_on="Portfolio as on 31-Oct-2026"):
    return _xlsx({"S1": [(title,), (as_on,), (), HDR] + holdings})


def _zip(members):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in members.items():
            z.writestr(name, data)
    return buf.getvalue()


RELIANCE = ("Reliance Industries Limited", "INE002A01018", "Petroleum", 100, 10.0, 50.0)
HDFCBANK = ("HDFC Bank Limited", "INE040A01034", "Banks", 100, 10.0, 30.0)
LT = ("Larsen & Toubro Limited", "INE018A01030", "Construction", 10, 4.0, 20.0)


def _other(row, k=7):
    """The same holding in a different scheme: a different quantity, as two
    real schemes never hold identical books."""
    return row[:3] + (row[3] * k,) + row[4:]
MAP = {"INE002A01018": "RELIANCE", "INE040A01034": "HDFCBANK", "INE018A01030": "LT"}


def test_a_run_continues_where_the_last_slice_stopped(fp, monkeypatch):
    """THE BUG. Every nightly slice took the first `limit` AMCs of the
    directory — alphabetically 360 ONE, Abakkus, Aditya Birla, AlphaGrep —
    so fourteen slices tried those four fourteen times and the other
    fifty-one were never attempted."""
    _stub_ingest(fp, monkeypatch)
    monkeypatch.setattr(fp, "find_workbooks", lambda page: [])
    amcs = [{"amc_id": str(i), "name": "AMC %d" % i, "monthly_url": "https://a.test/%d" % i}
            for i in range(10)]
    tried = []
    for _ in range(3):
        out = fp.run(limit=4, amcs=amcs, mapping={}, today=TODAY)
        tried += [r["amc_id"] for r in out["results"]]
    assert sorted(tried) == [str(i) for i in range(10)], "each house once, none twice"
    assert out["remaining"] == 0
    again = fp.run(limit=4, amcs=amcs, mapping={}, today=TODAY)
    assert again["attempted"] == 0 and "nothing due" in again["note"]


def test_a_house_already_read_for_the_month_is_not_downloaded_again(fp, monkeypatch):
    _stub_ingest(fp, monkeypatch)
    monkeypatch.setattr(fp, "find_workbooks",
                        lambda page: ["https://amc.test/p_31-10-2026.xlsx"])
    amcs = [{"amc_id": "1", "name": "Good AMC", "monthly_url": "https://good.test/d"}]
    first = fp.run(limit=4, amcs=amcs, mapping=MAP, today=TODAY)
    assert first["ok"] == 1
    import holdings_store as store
    # Even with the retry window over, the month is in: nothing is due.
    monkeypatch.setattr(store, "fund_tries", lambda: {})
    assert fp.run(limit=4, amcs=amcs, mapping=MAP, today=TODAY)["attempted"] == 0


def test_the_largest_houses_are_tried_first_and_the_known_gaps_last(fp, monkeypatch):
    amcs = [{"amc_id": "62", "name": "360 ONE Mutual Fund", "monthly_url": "u"},
            {"amc_id": "53", "name": "Axis Mutual Fund", "monthly_url": "u"},
            {"amc_id": "22", "name": "SBI Mutual Fund", "monthly_url": "u"},
            {"amc_id": "21", "name": "Nippon India Mutual Fund", "monthly_url": "u"}]
    order = [a["name"].split()[0] for a in fp.due_amcs(amcs, "2026-10-31")]
    assert order == ["Nippon", "SBI", "360", "Axis"]


@pytest.mark.parametrize("today,want", [
    (dt.date(2026, 11, 10), "2026-09-30"),   # October is due by the tenth...
    (dt.date(2026, 11, 11), "2026-10-31"),   # ...and expected from the eleventh
    (dt.date(2026, 1, 15), "2025-12-31"),
])
def test_the_month_every_house_owes_is_known(fp, today, want):
    assert fp.expected_month(today) == want


@pytest.mark.parametrize("text,want", [
    ("NIMF-MONTHLY-PORTFOLIO-31-Oct-26.xls", "2026-10-31"),          # Nippon India
    ("all-schemes-monthly-portfolio---as-on-31st-october-2026.xlsx", "2026-10-31"),  # SBI
    ("Monthly Portfolios as on October 31, 2026", "2026-10-31"),     # Aditya Birla
    ("31102026_abslmf_monthlydisclosure.zip", "2026-10-31"),
    ("uti_mf_scheme_portfolios_31.10.2026_1.zip", "2026-10-31"),    # UTI
    ("Oct 31,2026", "2026-10-31"),                                   # ICICI's sheet
    # HDFC names a fund after a month: the portfolio's own date must win.
    ("Monthly HDFC Nifty G-Sec Dec 2026 Index Fund - 31 October 2026.xlsx", "2026-10-31"),
    ("Smartbeta-2026.xlsx", None),       # "mar" inside a word is not March
])
def test_the_month_is_read_from_the_big_houses_own_filenames(fp, text, want):
    assert fp.month_end_from(text) == want


def test_links_with_query_strings_and_single_quotes_are_found(fp, monkeypatch):
    """SBI's links end "?sfvrsn=95fe7a7e_2". A pattern that stopped at the
    extension found none of them."""
    html = (b'<a href="https://www.sbimf.com/docs/all-schemes-monthly-portfolio---'
            b'as-on-31st-october-2026.xlsx?sfvrsn=95fe7a7e_2">x</a>'
            b"<a href='/files/Weblink-file-October-2026.zip'>y</a>"
            b'<a href="/f/a.xlsx?x=1&amp;y=2">z</a>')
    monkeypatch.setattr(fp, "_http", lambda url, timeout=40: html)
    links = fp.find_workbooks("https://amc.test/d")
    assert any(l.endswith("?sfvrsn=95fe7a7e_2") for l in links)
    assert "https://amc.test/files/Weblink-file-October-2026.zip" in links
    assert "https://amc.test/f/a.xlsx?x=1&y=2" in links


def test_the_monthly_pack_is_told_apart_from_its_neighbours(fp):
    """Nippon India's page interleaves monthly packs with fortnightly ones,
    risk parameters and a zip of additional disclosures — and the newest
    dated file on it is a fortnightly pack."""
    base = "https://mf.nipponindiaim.com/InvestorServices/FactsheetsDocuments/"
    links = [base + n for n in (
        "NIMF-FORTNIGHTLY-PORTFOLIO-31-Oct-26.xls",
        "Risk-Parameter-Sep-2026.xls",
        "NIMF-MONTHLY-PORTFOLIO-31-Oct-26.xls",
        "Weblink-file-October-2026.zip",
        "NIMF-MONTHLY-PORTFOLIO-30-Sep-26.xls")]
    groups = fp.month_candidates(links)
    assert groups[0]["as_of"] == "2026-10-31"
    assert [s["url"] for s in groups[0]["sources"]] == [base + "NIMF-MONTHLY-PORTFOLIO-31-Oct-26.xls"]
    assert groups[1]["as_of"] == "2026-09-30"


def test_an_all_schemes_pack_is_preferred_over_a_file_per_scheme(fp):
    links = ["https://x.test/sbi-arbitrage-fund-monthly-portfolio---october-2026.xlsx",
             "https://x.test/all-schemes-monthly-portfolio---as-on-31st-october-2026.xlsx",
             "https://x.test/sbi-magnum-fund-monthly-portfolio---october-2026.xlsx"]
    g = fp.month_candidates(links)[0]
    assert [s["url"] for s in g["sources"]] == [links[1]]


def test_a_blocked_page_is_reported_as_blocked_not_as_javascript(fp, monkeypatch):
    """HDFC's and Edelweiss's CDNs answer 403; Kotak serves a bot challenge.
    "Most likely builds its list in JavaScript" sent people to the wrong fix."""
    pages = {"https://blocked.test/": None,
             "https://captcha.test/": b'<script src="https://cdn.perfdrive.com/aperture/aperture.js"></script>'}

    def http(url, timeout=40, data=None, headers=None):
        if url == "https://blocked.test/":
            fp._LAST_ERROR[url] = "HTTP 403"
        return pages.get(url)

    monkeypatch.setattr(fp, "_http", http)
    a = fp.ingest_amc({"amc_id": "47", "name": "Edelweiss Mutual Fund",
                       "monthly_url": "https://blocked.test/"})
    b = fp.ingest_amc({"amc_id": "99", "name": "Some Mutual Fund",
                       "monthly_url": "https://captcha.test/"})
    assert "HTTP 403" in a["note"] and "JavaScript" not in a["note"]
    assert "bot challenge" in b["note"]


def test_a_known_gap_says_why(fp, monkeypatch):
    monkeypatch.setattr(fp, "_http", lambda url, timeout=40, data=None, headers=None: b"<div></div>")
    r = fp.ingest_amc({"amc_id": "53", "name": "Axis Mutual Fund", "monthly_url": "https://x.test/"})
    assert r["ok"] is False and "session token" in r["note"]


# --- the per-AMC sources ----------------------------------------------------

def test_sbi_is_read_from_the_list_its_page_posts_for(fp, monkeypatch):
    """SBI's page has no links in its HTML; it POSTs for the table. The
    response is plain HTML with the all-schemes pack in it."""
    calls = []
    table = (b'<tr><td><a href="https://www.sbimf.com/docs/default-source/scheme-portfolios/'
             b'all-schemes-monthly-portfolio---as-on-31st-october-2026.xlsx?sfvrsn=95fe7a7e_2">'
             b'All Schemes Monthly Portfolio - as on 31st October 2026</a></td></tr>'
             b'<tr><td><a href="https://www.sbimf.com/docs/default-source/scheme-portfolios/'
             b'sbi-arbitrage-opportunities-fund-monthly-portfolio---october-2026.xlsx?sfvrsn=1">'
             b'x</a></td></tr>')

    def http(url, timeout=40, data=None, headers=None):
        calls.append((url, json.loads(data) if data else None))
        return table if data and b"October" in data else b""

    monkeypatch.setattr(fp, "_http", http)
    groups = fp._src_sbi({"amc_id": "22"}, today=TODAY)
    assert calls[0][0] == fp.SBI_SHEETS
    assert calls[0][1] == {"FundId": "0", "PSYear": "2026", "PSMonth": "October",
                           "PSFrequency": "Monthly"}
    assert groups[0]["as_of"] == "2026-10-31"
    assert len(groups[0]["sources"]) == 1
    assert "all-schemes" in groups[0]["sources"][0]["url"]


def test_icici_is_read_from_its_fixed_monthly_zip(fp):
    g = fp._src_icici({"amc_id": "20"}, today=TODAY)
    assert g[0]["as_of"] == "2026-10-31"
    assert g[0]["sources"][0]["url"] == (
        "https://www.icicipruamc.com/blob/downloads/Files/Monthly%20Portfolio%20"
        "Disclosures/2026/Oct/Monthly-Portfolio-Disclosure-October-2026.zip")
    assert g[1]["as_of"] == "2026-09-30", "last month's, if this month's is not up yet"


def test_a_zip_of_per_scheme_workbooks_is_one_pack(fp, monkeypatch):
    """ICICI Prudential's month is a zip of 151 workbooks, one per scheme,
    each with its name in a title row. All of it is one house's month."""
    blob = _zip({
        "ICICI Prudential Flexi Cap Fund.xlsx": _xlsx({"FLEXCAP": [
            ("ICICI Prudential Mutual Fund",), ("ICICI Prudential Flexi Cap Fund",),
            ("Portfolio as on Oct 31,2026",), HDR, RELIANCE, HDFCBANK, LT]}),
        "ICICI Prudential Bluechip Fund.xlsx": _xlsx({"BLUECHIP": [
            ("ICICI Prudential Mutual Fund",), ("ICICI Prudential Large Cap Fund",),
            ("Portfolio as on Oct 31,2026",), HDR, _other(HDFCBANK), _other(LT), _other(RELIANCE)]}),
        "readme.txt": b"not a workbook",
    })
    _serve_download(fp, monkeypatch, blob)
    out = fp.ingest_month("20", "ICICI Prudential Mutual Fund",
                          fp._src_icici({}, today=TODAY)[0], mapping=MAP)
    assert out["ok"] and out["as_of"] == "2026-10-31"
    assert out["schemes"] == 2 and out["rows"] == 6
    import holdings_store as store
    schemes = {r["scheme"] for r in store.fund_positions("20")}
    assert schemes == {"ICICI Prudential Flexi Cap Fund", "ICICI Prudential Large Cap Fund"}


def test_hdfc_files_are_asked_for_by_name_when_its_page_is_refused(fp, monkeypatch):
    """HDFC's site answers 403 to cloud addresses, even for robots.txt; its
    file host does not, and names each scheme's file by scheme and date."""
    monkeypatch.setattr(fp, "_http", lambda url, timeout=40, data=None, headers=None: None)
    g = fp._src_hdfc({"amc_id": "9", "name": "HDFC Mutual Fund",
                      "monthly_url": "https://www.hdfcfund.com/x"}, today=TODAY)[0]
    assert g["as_of"] == "2026-10-31" and g["optional"] is True
    urls = [s["url"] for s in g["sources"]]
    assert ("https://files.hdfcfund.com/s3fs-public/2026-11/"
            "Monthly%20HDFC%20Flexi%20Cap%20Fund%20-%2031%20October%202026.xlsx") in urls
    assert len(urls) == len(fp.HDFC_EQUITY_SCHEMES)


def test_per_scheme_files_are_recorded_as_one_pack_and_misses_are_counted(fp, monkeypatch):
    """Recorded together: the pack row is per house and month, and a second
    write for the same month replaces the first one's counts."""
    files = {"Flexi": _scheme_book("HDFC Flexi Cap Fund (An open ended equity scheme)",
                                   [RELIANCE, HDFCBANK, LT]),
             "Mid": _scheme_book("HDFC Mid Cap Fund (An open ended equity scheme)",
                                 [_other(HDFCBANK), _other(LT), _other(RELIANCE)])}

    def serve(url):
        return next((b for k, b in files.items() if "%20" + k in url), None)

    _serve_download(fp, monkeypatch, serve)
    group = {"as_of": "2026-10-31", "optional": True, "sources": [
        {"url": "https://f.test/Monthly%20HDFC%20Flexi%20Cap%20Fund.xlsx", "title": "HDFC Flexi Cap Fund"},
        {"url": "https://f.test/Monthly%20HDFC%20Closed%20Fund.xlsx", "title": "HDFC Closed Fund"},
        {"url": "https://f.test/Monthly%20HDFC%20Mid%20Cap%20Fund.xlsx", "title": "HDFC Mid Cap Fund"}]}
    out = fp.ingest_month("9", "HDFC Mutual Fund", group, mapping=MAP)
    assert out["ok"] and out["schemes"] == 2 and out["rows"] == 6
    assert out["files_read"] == 2 and "1 not found" in out["note"]
    import holdings_store as store
    pack = store.fund_packs("2026-10-31")[0]
    assert pack["schemes"] == 2 and pack["rows"] == 6


def test_an_unpublished_month_is_abandoned_after_three_misses(fp, monkeypatch):
    seen = []
    _serve_download(fp, monkeypatch, None, seen=seen)
    group = {"as_of": "2026-10-31", "optional": True,
             "sources": [{"url": "https://f.test/%d.xlsx" % i} for i in range(50)]}
    out = fp.ingest_month("9", "HDFC", group, mapping=MAP)
    assert out["ok"] is False and len(seen) == 3


def test_uti_reads_only_the_portfolio_out_of_its_zip(fp, monkeypatch):
    """UTI's API returns a zip holding futures exposure, a dividend master and
    a risk-o-meter beside the portfolio — and the portfolio is every scheme in
    one sheet."""
    api = json.dumps({"rows": [{"name": "Consolidated Portfolio October 2026", "type": "Zip",
                                "url": "https://cdn.test/uti_mf_scheme_portfolios_31.10.2026_1.zip"}]})
    monkeypatch.setattr(fp, "_http", lambda url, timeout=40, data=None, headers=None:
                        api.encode() if "month=October" in url else None)
    groups = fp._src_uti({"amc_id": "28"}, today=TODAY)
    assert groups[0]["as_of"] == "2026-10-31"

    def block(scheme, rows):
        return [("SCHEME: %s" % scheme,), ("PORTFOLIO DISCLOSURE AS OF 31/10/2026",),
                ("NAME OF THE INSTRUMENT", "RATING/INDUSTRY", "QUANTITY", "MARKET-VALUE",
                 "% TO NAV", "ISIN")] + rows

    def row(r):
        return ("EQ - " + r[0], r[2], r[3], r[4], r[5], r[1])

    portfolio = _xlsx({"exposure": block("UTI - Large Cap Fund", [row(RELIANCE), row(HDFCBANK), row(LT)]) +
                                   block("UTI - Mid Cap Fund", [row(_other(LT)), row(_other(HDFCBANK)),
                                                                row(_other(RELIANCE))])})
    decoy = _xlsx({"fut": [(), HDR, RELIANCE, HDFCBANK, LT]})
    _serve_download(fp, monkeypatch, _zip({
        "Sebi Exposure as on 31 Oct 2026_FINAL.xlsx": portfolio,
        "Fut Disclo-Fut Exposure Sebi Format-01-Oct-2026-31-Oct-2026_FINAL.xlsx": decoy,
        "Risk-o-meter_Funds and Benchmark_Oct2026.xlsx": decoy}))
    out = fp.ingest_month("28", "UTI Mutual Fund", groups[0], mapping=MAP)
    assert out["ok"] and out["schemes"] == 2 and out["rows"] == 6
    import holdings_store as store
    assert {r["scheme"] for r in store.fund_positions("28")} == {
        "UTI Large Cap Fund", "UTI Mid Cap Fund"}


def test_aditya_birla_is_read_from_the_api_its_page_names(fp, monkeypatch):
    """The list comes from an accordion API named in the page's HTML; its
    links point at an Azure CDN host that no longer resolves, and the same
    path is served from the main site."""
    page = (b'<li data-accordian-api="/postlogin/CustomApi/Resources/FactsheetAccordionById?'
            b'id=NEW-ID&amp;ctype=x"><h3>Monthly Portfolio </h3></li>'
            b'<li data-accordian-api="/other?id=HALF"><h3>Half Yearly Portfolio</h3></li>')
    api = json.dumps({"ReturnCode": "1", "AccordionList": [
        {"ResourceLink": "Monthly Portfolios as on October 31, 2026",
         "pdfUrl": "https://abcscprod.azureedge.net/-/media/bsl/files/resources/"
                   "monthly-portfolio/2026/31102026_abslmf_monthlydisclosure.zip"}]})
    asked = []

    def http(url, timeout=40, data=None, headers=None):
        asked.append(url)
        return page if url == "https://absl.test/portfolio" else api.encode()

    monkeypatch.setattr(fp, "_http", http)
    g = fp._src_absl({"amc_id": "3", "monthly_url": "https://absl.test/portfolio"}, today=TODAY)
    assert "id=NEW-ID&ctype=x" in asked[1] and asked[1].endswith("&month=%20&year=0")
    assert g[0]["as_of"] == "2026-10-31"
    assert g[0]["sources"][0]["url"] == (
        "https://mutualfund.adityabirlacapital.com/-/media/bsl/files/resources/"
        "monthly-portfolio/2026/31102026_abslmf_monthlydisclosure.zip")


def test_a_legacy_xls_inside_a_zip_is_read(fp, monkeypatch):
    """Aditya Birla Sun Life: a zip holding one legacy-format workbook with an
    index sheet. Refused outright before, for the format alone."""
    pytest.importorskip("xlrd")
    _serve_download(fp, monkeypatch, _zip({
        "31102026_ABSLMF_MonthlyDisclosure.xls": (FIXTURES / "funds_legacy_pack.xls").read_bytes()}))
    out = fp.ingest_url("3", "Aditya Birla Sun Life Mutual Fund",
                        "https://x.test/31102026_abslmf_monthlydisclosure.zip", mapping=MAP)
    assert out["ok"] and out["as_of"] == "2026-10-31"
    assert out["schemes"] == 2 and out["rows"] == 4, "the government security is not equity"
    import holdings_store as store
    rows = store.fund_positions("3")
    assert {r["scheme"] for r in rows} == {"ADITYA BIRLA SUN LIFE AGGRESSIVE HYBRID FUND",
                                           "ADITYA BIRLA SUN LIFE LARGE & MID CAP FUND"}
    icici = next(r for r in rows if r["symbol"] is None or r["isin"] == "INE090A01021")
    assert icici["pct_nav"] is not None and icici["pct_nav"] > 1, "a fraction becomes a percentage"


def test_a_date_in_the_query_string_is_not_the_portfolios_month(fp):
    """PPFAS appends the upload date to its links ("?09112026"). Read as a
    date, October's pack was filed under November — a month that had not
    ended."""
    links = ["https://amc.ppfas.com/schemes/PPFCF_PPFAS_Monthly_Portfolio_Report_"
             "October_31_2026.xlsx?09112026",
             "https://amc.ppfas.com/x/undated-pack.xlsx?09112026"]
    groups = fp.month_candidates(links, today=TODAY)
    assert groups[0]["as_of"] == "2026-10-31"
    assert groups[1]["as_of"] is None, "the query string says nothing about the month"


def test_a_month_that_has_not_ended_is_never_recorded(fp, monkeypatch):
    _stub_ingest(fp, monkeypatch)
    nxt = fp.recent_month_ends(dt.date.today(), 1)[0] + dt.timedelta(days=40)
    future = fp._month_end(nxt.year, nxt.month)
    out = fp.ingest_month("20", "X", {"as_of": future,
                                      "sources": [{"url": "https://amc.test/p.xlsx"}]},
                          mapping={"INE002A01018": "RELIANCE"})
    assert out["ok"] is False and "has not" in out["note"]
    assert fp.month_candidates(["https://a.test/Portfolio-%s.xlsx" % future]) == []


def test_the_same_book_listed_twice_is_recorded_once(fp, monkeypatch):
    """A whole-house file beside the per-scheme files it was built from would
    put every position in twice, and the house view sums across schemes."""
    book = _scheme_book("Parag Parikh Flexi Cap Fund ( An open ended dynamic equity scheme)",
                        [RELIANCE, HDFCBANK, LT])
    _serve_download(fp, monkeypatch, book)
    out = fp.ingest_month("64", "PPFAS Mutual Fund", {"as_of": "2026-10-31", "sources": [
        {"url": "https://a.test/PPFAS_Monthly_Portfolio_Report_October_31_2026.xlsx"},
        {"url": "https://a.test/PPFCF_PPFAS_Monthly_Portfolio_Report_October_31_2026.xlsx"}]},
        mapping=MAP)
    assert out["ok"] and out["schemes"] == 1 and out["rows"] == 3
    import holdings_store as store
    assert {r["scheme"] for r in store.fund_positions("64")} == {"Parag Parikh Flexi Cap Fund"}


def test_undated_files_are_dated_by_their_sheets_and_the_newest_month_wins(fp, monkeypatch):
    """Quantum names its files by UUID. Each file's month comes from its own
    date line — "for the period ended October 31, 2026" — and an older file on
    the same page must not drag the house back a month."""
    books = {"a1": _scheme_book("Quantum Value Fund", [RELIANCE, HDFCBANK, LT],
                                as_on="Monthly Portfolio Statement of the Quantum Value "
                                      "Fund for the period ended September 30, 2026"),
             "b2": _scheme_book("Quantum Value Fund", [_other(RELIANCE), _other(LT), _other(HDFCBANK)],
                                as_on="Monthly Portfolio Statement of the Quantum Value "
                                      "Fund for the period ended October 31, 2026")}
    _serve_download(fp, monkeypatch, lambda url: books[url.rsplit("/", 1)[-1][:2]])
    groups = fp.month_candidates(["https://q.test/a1-5065.xlsx", "https://q.test/b2-417e.xlsx"],
                                 today=TODAY)
    assert len(groups) == 1 and groups[0]["as_of"] is None
    out = fp.ingest_month("41", "Quantum Mutual Fund", groups[0], mapping=MAP)
    assert out["ok"] and out["as_of"] == "2026-10-31" and out["rows"] == 3


def test_files_that_are_not_portfolios_are_named_as_such(fp, monkeypatch):
    """Abakkus links one workbook per scheme — and each is a scheme summary
    document, not a portfolio. "Could not tell which month" was the wrong
    reason to give."""
    summary = _xlsx({"Sheet1": [("Fields", "SCHEME SUMMARY DOCUMENT"),
                                (1, "Fund Name", "Abakkus Flexi Cap Fund")]})
    _serve_download(fp, monkeypatch, summary)
    out = fp.ingest_month("85", "Abakkus Mutual Fund",
                          {"as_of": None, "sources": [{"url": "https://a.test/Abakkus_Flexi_Cap_Fund.xlsx"}]},
                          mapping=MAP)
    assert out["ok"] is False and "none is a portfolio" in out["note"]


@pytest.mark.parametrize("name", [
    "Monthly%20AAUM%20Disclosure%20Report%20-%20October%202026.xlsx",          # Zerodha
    "Debt%20Index%20Replication%20Factor%20as%20on%2031st%20October%202026.xlsx",  # Tata
    "Daily-Tracking-Error-on-rolling-basis.xlsx",                                # LIC
    "1792042594-LIC-MF-Dashboard-as-on-30-September-2026.xlsx",
    "Performance-update-_as-a-part-of-portfolio-30th_Sep_2026_Final.xlsx",       # Bajaj
    "NIMF-FORTNIGHTLY-PORTFOLIO-31-Oct-26.xls",
    "Half_Yearly_Portfolio_March_26_Final_dbce7a92f6.xls",
    "Portfolio_Overlap_31_Oct_2026_AOD_All_d1afbfafda.xlsx",
])
def test_workbooks_that_are_not_the_monthly_portfolio_are_not_taken_for_it(fp, name):
    assert fp.month_candidates(["https://x.test/" + name], today=TODAY) == []


def test_a_link_with_spaces_is_requested_escaped(fp, monkeypatch):
    """Zerodha's hrefs carry raw spaces, which urllib refuses outright."""
    monkeypatch.setattr(fp, "_http", lambda url, timeout=40:
                        b'<a href="/reports/ZN250 - Monthly Portfolio October 2026.xlsx">x</a>')
    assert fp.find_workbooks("https://z.test/d") == [
        "https://z.test/reports/ZN250%20-%20Monthly%20Portfolio%20October%202026.xlsx"]


def test_a_file_served_through_a_script_is_named_by_its_file_parameter(fp):
    """NJ's links are "viewfile.php?file=NJ-MF-Monthly-Portfolio-...xlsx": the
    path names a script, and the month is in the file parameter."""
    links = ["https://downloads.njmutualfund.com/viewfile.php?file="
             "NJ-MF-Monthly-Portfolio-NJFCP-October-2026-20261107.xlsx",
             "https://downloads.njmutualfund.com/viewfile.php?file="
             "Monthly-Portfolio-March-31-2022-20220411.xlsx"]
    groups = fp.month_candidates(links, today=TODAY)
    assert groups[0]["as_of"] == "2026-10-31" and len(groups[0]["sources"]) == 1


def test_mid_month_and_daily_files_are_not_the_month_end_portfolio(fp):
    """Old Bridge posts an "IR_" file every working day beside its monthly
    portfolios ("..._Portfolio_Oct_26", no day at all); HSBC's month has an
    FMP statement dated the 15th."""
    daily = ["https://ob.test/IR_Old_Bridge_Mutual_Fund_%02d102026_x.xlsx" % d
             for d in range(13, 31)]
    monthly = ["https://ob.test/OBMF_Flexi_Cap_Portfolio_Oct_26_394d44fbd0.xlsx",
               "https://ob.test/OBMF_Focused_Portfolio_Oct_26_5fbc27763f.xlsx"]
    mid = ["https://h.test/hsbc-equity-fund-oct-15-2026.xlsx"]
    g = fp.month_candidates(daily + monthly + mid, today=TODAY)[0]
    names = [fp._filename(s["url"]) for s in g["sources"]]
    assert g["as_of"] == "2026-10-31"
    assert set(names) == {"IR_Old_Bridge_Mutual_Fund_30102026_x.xlsx",
                          "OBMF_Flexi_Cap_Portfolio_Oct_26_394d44fbd0.xlsx",
                          "OBMF_Focused_Portfolio_Oct_26_5fbc27763f.xlsx"}


@pytest.mark.parametrize("name", ["hsbc-fmp-series-xiv-october-30-2026.xlsx",
                                  "investor-complaints-october-2026.xlsx",
                                  "top-07-issuer-sectorwise-breakup-sep-30-2026.xlsx"])
def test_debt_plans_and_other_statements_are_skipped(fp, name):
    assert fp.month_candidates(["https://h.test/" + name], today=TODAY) == []


def test_a_stale_month_is_not_recorded_as_a_houses_latest(fp, monkeypatch):
    """The newest pack NJ's page let this date, before its links were read
    properly, was March 2024. Recorded, it would sit in the ledger as that
    house's current month."""
    _stub_ingest(fp, monkeypatch)
    monkeypatch.setattr(fp, "find_workbooks",
                        lambda page: ["https://amc.test/Monthly-Portfolio-March-31-2024.xlsx"])
    r = fp.ingest_amc({"amc_id": "73", "name": "NJ Mutual Fund",
                       "monthly_url": "https://nj.test/"}, mapping=MAP, today=TODAY)
    assert r["ok"] is False and "too old" in r["note"]
    assert fp.oldest_current_month(TODAY) == "2026-07-31"
