"""
The parsers Money Flow reads NSDL and NSE with.

The fixtures in tests/fixtures/moneyflow/ are the real files, trimmed:

  nsdl_index.html              the dropdown on FPI_Fortnightly_Selection.aspx:
                               its newest eight entries, its oldest four, and
                               the two whose file names are spelled unlike the
                               rest ("June302026", "FIIInvestSecor_").
  nsdl_report_2026-11-15.html  the report table as published, with Excel's
  nsdl_report_2026-10-31.html  styling attributes stripped and every colspan
  nsdl_report_2024-01-15.html  kept. The 2024 page is the layout before
                               Debt-FAR, mutual funds and AIFs were added: a
                               block is 5 columns wide there and 12 in 2026.
  ind_close_all_20112026.csv   NSE's daily index file, 27 of its rows.
  bulk.csv, block.csv          the large-deal files for 23 November 2026.

Every figure asserted below was read off NSDL's or NSE's own page. No network.
"""
import datetime as dt
import os

import pytest

import money_flow_sources as S

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "moneyflow")


def read(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as fh:
        return fh.read()


def by(rows, sector, period_end):
    got = [r for r in rows if r["sector"] == sector and r["period_end"] == period_end]
    assert len(got) == 1, (sector, period_end, len(got))
    return got[0]


# --- numbers and dates -------------------------------------------------------

@pytest.mark.parametrize("text, want", [
    ("4,77,593", 477593.0), ("-6,533", -6533.0), ("(6,533)", -6533.0), (" 12.5 ", 12.5),
    ("0", 0.0), ("", None), ("-", None), ("NA", None), ("abc", None), (None, None),
    ("\xa01,234\xa0", 1234.0),
])
def test_a_figure_is_read_as_nsdl_prints_it(text, want):
    assert S.number(text) == want


def test_a_blank_cell_is_not_zero():
    """Zero is a flow; blank is no figure. The store keeps an earlier figure
    over a blank and would not over a zero."""
    assert S.number("") is None and S.number("0") == 0.0


@pytest.mark.parametrize("text, want", [
    ("NOV 15, 2026", dt.date(2026, 11, 15)), ("March 15, 2012 ", dt.date(2012, 3, 15)),
    ("October 31, 2026", dt.date(2026, 10, 31)), ("Sept. 30, 2025", dt.date(2025, 9, 30)),
    ("February 30, 2026", None), ("Select", None),
])
def test_a_date_is_read_however_the_month_is_written(text, want):
    assert S.loose_date(text) == want


# --- the list of reports -----------------------------------------------------

def test_the_report_list_is_read_newest_first_with_full_addresses():
    got = S.parse_nsdl_index(read("nsdl_index.html"))
    assert got[0] == {
        "url": "https://www.fpi.nsdl.co.in/web/StaticReports/"
               "Fortnightly_Sector_wise_FII_Investment_Data/FIIInvestSector_Nov152026.html",
        "label": "NOV 15, 2026", "report_date": "2026-11-15"}
    assert [r["report_date"] for r in got] == sorted((r["report_date"] for r in got), reverse=True)
    assert got[-1]["report_date"] == "2012-01-31"


def test_an_address_is_taken_from_the_list_never_built_from_the_date():
    """Two of NSDL's file names do not follow the pattern the others do. A URL
    built from the date would 404 for both."""
    urls = {r["report_date"]: r["url"] for r in S.parse_nsdl_index(read("nsdl_index.html"))}
    assert urls["2026-06-30"].endswith("FIIInvestSector_June302026.html")
    assert urls["2012-01-31"].endswith("FIIInvestSecor_Jan312012.html")


def test_the_placeholder_option_is_not_a_report():
    got = S.parse_nsdl_index(read("nsdl_index.html"))
    assert all(r["url"].endswith(".html") for r in got)
    assert len(got) == 13


def test_a_page_with_no_report_in_it_is_an_error_not_an_empty_list():
    with pytest.raises(S.ParseError):
        S.parse_nsdl_index("<html><body><select><option value='0'>Select</option></select></body></html>")


# --- one report --------------------------------------------------------------

def test_a_report_carries_two_fortnights_oldest_first():
    got = S.parse_nsdl_report(read("nsdl_report_2026-11-15.html"))
    assert [(p["start"], p["end"]) for p in got["periods"]] == [
        ("2026-10-16", "2026-10-31"), ("2026-11-01", "2026-11-15")]
    assert got["warnings"] == []


def test_equity_net_investment_is_read_from_the_inr_equity_column():
    rows = S.parse_nsdl_report(read("nsdl_report_2026-11-15.html"))["rows"]
    it = by(rows, "Information Technology", "2026-11-15")
    assert it["equity_net_inr_cr"] == 5080.0
    assert it["equity_net_usd_mn"] == 539.0
    assert it["period_start"] == "2026-11-01"
    # Total is equity plus debt, hybrid and funds: a different column, and for
    # this fortnight a different number.
    assert it["total_net_inr_cr"] == 5130.0
    assert it["equity_auc_inr_cr"] == 424889.0


def test_all_24_rows_are_read_for_each_fortnight():
    got = S.parse_nsdl_report(read("nsdl_report_2026-11-15.html"))
    sectors = {r["sector"] for r in got["rows"]}
    assert len(sectors) == 24 and len(got["rows"]) == 48
    assert {"Financial Services", "Oil, Gas & Consumable Fuels", "Sovereign", "Others"} <= sectors
    assert "Grand Total" not in sectors


def test_the_sectors_add_up_to_the_pages_own_total():
    """The check that the right column was read: the page prints a total."""
    got = S.parse_nsdl_report(read("nsdl_report_2026-11-15.html"))
    for end, total in got["grand_total"].items():
        summed = sum(r["equity_net_inr_cr"] for r in got["rows"] if r["period_end"] == end)
        assert abs(summed - total) <= 30, (end, summed, total)
    assert got["grand_total"] == {"2026-10-31": 13112.0, "2026-11-15": 84291.0}


def test_a_fortnight_reads_the_same_from_both_reports_that_carry_it():
    """16-31 October is the later half of the 31 October report and the
    earlier half of the 15 November one."""
    a = S.parse_nsdl_report(read("nsdl_report_2026-10-31.html"))["rows"]
    b = S.parse_nsdl_report(read("nsdl_report_2026-11-15.html"))["rows"]
    for sector in ("Information Technology", "Financial Services", "Telecommunication", "Realty"):
        x, y = by(a, sector, "2026-10-31"), by(b, sector, "2026-10-31")
        assert x["equity_net_inr_cr"] == y["equity_net_inr_cr"], sector
        assert x["equity_auc_inr_cr"] == y["equity_auc_inr_cr"], sector
    assert by(a, "Information Technology", "2026-10-31")["equity_net_inr_cr"] == 10915.0
    assert by(a, "Automobile and Auto Components", "2026-10-15")["equity_net_inr_cr"] == -6533.0


def test_the_layout_before_august_2024_reads_by_the_same_rule():
    """A block was 5 columns then and is 12 now. Nothing in the parser counts."""
    got = S.parse_nsdl_report(read("nsdl_report_2024-01-15.html"))
    assert [(p["start"], p["end"]) for p in got["periods"]] == [
        ("2023-12-16", "2023-12-31"), ("2024-01-01", "2024-01-15")]
    it = by(got["rows"], "Information Technology", "2024-01-15")
    assert it["equity_net_inr_cr"] == -492.0 and it["equity_auc_inr_cr"] == 628455.0
    assert got["grand_total"] == {"2023-12-31": 23401.0, "2024-01-15": 3433.0}
    assert got["warnings"] == []


def test_a_period_that_crosses_a_year_end_is_dated_correctly():
    assert S._period("Net Investment December 16-31, 2023") == (dt.date(2023, 12, 16), dt.date(2023, 12, 31))
    assert S._period("Net Investment December 16 - January 15, 2024") == (
        dt.date(2023, 12, 16), dt.date(2024, 1, 15))
    assert S._period("AUC as on October 31, 2026") is None


def test_a_report_whose_header_changed_fails_loudly():
    html = read("nsdl_report_2026-11-15.html").replace("Net Investment", "Net Flows")
    with pytest.raises(S.ParseError):
        S.parse_nsdl_report(html)


def test_a_report_with_no_equity_column_fails_rather_than_reading_debt():
    html = read("nsdl_report_2026-11-15.html").replace("<td>Equity</td>", "<td>Shares</td>")
    with pytest.raises(S.ParseError):
        S.parse_nsdl_report(html)


def test_an_error_page_is_not_a_report():
    with pytest.raises(S.ParseError):
        S.parse_nsdl_report("<html><body><h1>Service Unavailable</h1></body></html>")


def test_a_column_read_wrongly_shows_up_as_a_warning():
    """Corrupt one sector's figure: the sectors no longer add up to the total
    the page prints, and the report says so instead of passing quietly."""
    html = read("nsdl_report_2026-11-15.html").replace("<td>5,080</td>", "<td>95,080</td>", 1)
    got = S.parse_nsdl_report(html)
    assert any("2026-11-15" in w for w in got["warnings"])


def test_spans_are_expanded_so_every_column_knows_its_headers():
    g = S.grid([[("A", 2, 2), ("B", 1, 1)], [("C", 1, 1)], [("x", 1, 1), ("y", 1, 1), ("z", 1, 1)]])
    assert g == [["A", "A", "B"], ["A", "A", "C"], ["x", "y", "z"]]


# --- NSE index closes --------------------------------------------------------

def test_the_index_file_gives_one_date_and_a_close_per_index():
    day, closes = S.parse_index_csv(read("ind_close_all_20112026.csv"))
    assert day == dt.date(2026, 11, 20)
    assert closes["NIFTY 50"] == 25800.6
    assert "NIFTY MIDCAP 100" in closes          # NSE writes this one "NIFTY Midcap 100"
    assert "NIFTY OIL & GAS" in closes and "NIFTY HEALTHCARE INDEX" in closes
    assert all(v > 0 for v in closes.values())


def test_an_html_error_page_is_not_an_index_file():
    with pytest.raises(S.ParseError):
        S.parse_index_csv("<html><body>Not Found</body></html>")


def test_an_index_file_with_two_dates_is_refused():
    text = read("ind_close_all_20112026.csv").replace("20-11-2026", "19-11-2026", 1)
    with pytest.raises(S.ParseError):
        S.parse_index_csv(text)


def test_a_zero_close_is_dropped_not_stored():
    text = ("Index Name,Index Date,Closing Index Value\n"
            "Nifty 50,20-11-2026,25800.6\nNifty Dud,20-11-2026,0\nNifty Dash,20-11-2026,-\n")
    _day, closes = S.parse_index_csv(text)
    assert closes == {"NIFTY 50": 25800.6}


# --- deals -------------------------------------------------------------------

def test_bulk_deals_are_read_with_an_iso_date_and_a_side():
    rows = S.parse_deals_csv(read("bulk.csv"), "bulk")
    assert len(rows) == 15
    first = rows[0]
    assert first == {"date": "2026-11-23", "symbol": "AJMERA", "name": "Ajmera Realty & Inf I Ltd",
                     "client": "MICROCURVES TRADING PRIVATE LIMITED", "side": "BUY",
                     "qty": 1015117.0, "price": 163.94, "kind": "bulk", "remarks": None}
    assert {r["side"] for r in rows} <= {"BUY", "SELL"}


def test_block_deals_have_no_remarks_column_and_still_read():
    rows = S.parse_deals_csv(read("block.csv"), "block")
    assert len(rows) == 5 and all(r["kind"] == "block" for r in rows)
    assert rows[0]["symbol"] == "LENSKART" and rows[0]["price"] == 725.0


def test_a_session_with_no_block_deal_is_an_empty_list():
    text = ("Date,Symbol,Security Name,Client Name,Buy/Sell,Quantity Traded,"
            "Trade Price / Wght. Avg. Price\nNO RECORDS\n")
    assert S.parse_deals_csv(text, "block") == []


def test_a_deals_file_missing_a_column_is_refused():
    with pytest.raises(S.ParseError):
        S.parse_deals_csv("Date,Symbol,Client Name\n23-NOV-2026,X,Y\n", "bulk")


def test_a_deal_with_no_quantity_is_left_out():
    assert S.deal_row("23-NOV-2026", "X", "X Ltd", "SOMEBODY", "BUY", "", "10", "bulk") is None
    assert S.deal_row("not a date", "X", "X Ltd", "SOMEBODY", "BUY", "5", "10", "bulk") is None


def test_the_history_download_reads_into_the_same_shape():
    """NSE's history download quotes every field, pads the headers with a
    space and writes quantities with Indian commas."""
    text = ('\ufeff"Date ","Symbol ","Security Name ","Client Name ","Buy / Sell ",'
            '"Quantity Traded ","Trade Price / Wght. Avg. Price ","Remarks "\n'
            '"26-OCT-2026","APOLLO","Apollo Micro Systems Ltd","JUMP TRADING FINANCIAL INDIA '
            'PRIVATE LIMITED","SELL","26,41,960","411.55","-"\n')
    assert S.parse_deals_csv(text, "bulk") == [{
        "date": "2026-10-26", "symbol": "APOLLO", "name": "Apollo Micro Systems Ltd",
        "client": "JUMP TRADING FINANCIAL INDIA PRIVATE LIMITED", "side": "SELL",
        "qty": 2641960.0, "price": 411.55, "kind": "bulk", "remarks": None}]


# --- fetching: retries, and telling a holiday from a refusal -----------------

def _ways(monkeypatch, answers):
    """Replace the transports with one that plays back `answers` in order."""
    calls = []

    def way(url, referer):
        calls.append(url)
        a = answers[min(len(calls) - 1, len(answers) - 1)]
        if isinstance(a, Exception):
            raise a
        return a
    monkeypatch.setattr(S, "_transports", lambda: [way])
    return calls


def test_a_refusal_is_retried_and_the_retry_can_succeed(monkeypatch):
    calls = _ways(monkeypatch, [(403, b""), RuntimeError("reset"), (200, b"body")])
    slept = []
    assert S.http_get("https://x/y", sleep=slept.append) == (S.OK, b"body")
    assert len(calls) == 3 and len(slept) == 2 and slept[1] > slept[0]


def test_three_refusals_are_reported_as_blocked_not_absent(monkeypatch):
    _ways(monkeypatch, [(403, b"")])
    assert S.http_get("https://x/y", sleep=lambda s: None) == (S.BLOCKED, b"")


def test_a_404_is_asked_twice_and_then_believed_without_waiting(monkeypatch):
    calls = _ways(monkeypatch, [(404, b"")])
    slept = []
    assert S.http_get("https://x/y", sleep=slept.append) == (S.ABSENT, b"")
    assert len(calls) == 2 and slept == []


def test_a_day_with_no_file_is_absent_and_a_refused_day_is_blocked():
    csv = read("ind_close_all_20112026.csv").encode()
    assert S.fetch_index_day(dt.date(2026, 11, 20), get=lambda u, referer=None: (S.OK, csv))[0] == S.OK
    assert S.fetch_index_day(dt.date(2026, 11, 21), get=lambda u, referer=None: (S.ABSENT, b"")) == (S.ABSENT, {})
    assert S.fetch_index_day(dt.date(2026, 11, 20), get=lambda u, referer=None: (S.BLOCKED, b"")) == (S.BLOCKED, {})


def test_a_file_for_the_wrong_day_is_not_stored_under_the_day_asked_for():
    """NSE's edge has served a cached neighbour's file before. Storing it
    would write Friday's closes as Monday's."""
    csv = read("ind_close_all_20112026.csv").encode()
    state, closes = S.fetch_index_day(dt.date(2026, 11, 23), get=lambda u, referer=None: (S.OK, csv))
    assert state == S.BLOCKED and closes == {}


def test_one_deals_file_failing_does_not_lose_the_other():
    bulk = read("bulk.csv").encode()

    def get(url, referer=None):
        return (S.OK, bulk) if url.endswith("bulk.csv") else (S.BLOCKED, b"")
    rows, errors = S.fetch_deals_latest(get=get)
    assert len(rows) == 15 and errors == ["block deals file did not answer"]
