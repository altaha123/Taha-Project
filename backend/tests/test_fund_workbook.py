"""
Reading an AMC's monthly portfolio workbook.

One parser stands in for fifty-three websites, which only works because SEBI
fixes the CONTENT of these disclosures even though every AMC lays the file out
differently. The tests below are the layout variations that actually occur in
the packs, and each one produces a wrong table rather than an error if it is
handled naively.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import fund_workbook as fw  # noqa: E402


HEADER = ("Name of the Instrument", "ISIN", "Industry / Rating", "Quantity",
          "Market/Fair Value\n (Rs. in Lakhs)", "% to Net\n Assets")


def _sheet(rows, header=HEADER, preamble=2):
    """A sheet shaped like the real ones: a title, a blank line, then the
    header, then the holdings."""
    out = [("Some Scheme Name",)] + [()] * preamble + [header]
    return out + list(rows)


# ---------------------------------------------------------------------------
# Finding the table
# ---------------------------------------------------------------------------

def test_a_plain_sheet_is_read():
    rows = _sheet([
        ("Reliance Industries Limited", "INE002A01018", "Petroleum", 1000, 250.5, 3.33),
        ("HDFC Bank Limited", "INE040A01034", "Banks", 2000, 400.0, 5.31),
    ])
    out = fw.parse_sheet(rows)
    assert len(out) == 2
    assert out[0]["isin"] == "INE002A01018"
    assert out[0]["name"] == "Reliance Industries Limited"
    assert out[0]["quantity"] == 1000
    assert out[0]["value_lakh"] == pytest.approx(250.5)


def test_the_header_is_found_wherever_it_sits():
    """The packs put a title, blank lines and a "Monthly Portfolio Statement as
    on ..." line above the header, and how many varies by AMC."""
    for pad in (0, 1, 5, 9):
        rows = _sheet([("A Limited", "INE001A01010", "X", 10, 1.0, 100.0)],
                      preamble=pad)
        assert len(fw.parse_sheet(rows)) == 1, "failed with %d preamble rows" % pad


def test_a_sheet_that_is_not_a_portfolio_yields_nothing():
    for rows in ([("Index",), ("1", "T0ME02", "Some Fund")],
                 [("Disclaimer",), ("Mutual fund investments are subject...",)],
                 []):
        assert fw.parse_sheet(rows) == []


def test_a_debt_only_sheet_with_no_isins_yields_nothing():
    rows = _sheet([("Net Current Assets", None, None, None, 500.0, 2.0),
                   ("TOTAL", None, None, None, 25000.0, 100.0)])
    assert fw.parse_sheet(rows) == []


# ---------------------------------------------------------------------------
# THE OFF-BY-ONE
# ---------------------------------------------------------------------------

def test_a_header_offset_against_its_own_data_is_handled():
    """
    Baroda BNP's real pack: the header starts at "Name of the Instrument" but
    every data row starts with an internal scrip code and THEN the name, so the
    header describes column N and the data is in column N+1.

    Parsed by position this yields a table where every name is a scrip code and
    every ISIN is a company name — entirely plausible-looking and wrong in
    every row. Anchoring on the ISIN column, found from the data, is what
    prevents it.
    """
    rows = _sheet([
        ("BHAH02", "Bharat Heavy Electricals Limited", "INE257A01026",
         "Electrical Equipment", 2000000, 8853.0, 3.33),
        ("ALLI02", "GE Vernova T&D India Limited", "INE200A01026",
         "Electrical Equipment", 165000, 7334.58, 2.76),
    ])
    out = fw.parse_sheet(rows)
    assert len(out) == 2
    assert out[0]["name"] == "Bharat Heavy Electricals Limited"
    assert out[0]["isin"] == "INE257A01026"
    assert out[0]["quantity"] == 2000000
    assert out[0]["value_lakh"] == pytest.approx(8853.0)
    assert out[0]["industry"] == "Electrical Equipment"


def test_the_isin_column_is_found_from_the_data_not_the_header():
    """The header says ISIN is column 1; the data has it in column 2. The
    column used is the one the ISINs are actually in."""
    header = ("Name of the Instrument", "ISIN", "Industry", "Quantity",
              "Market Value", "% to Net Assets")
    rows = [("Title",), (), header,
            ("code", "A Limited", "INE001A01010", "X", 10, 1.0, 100.0)]
    out = fw.parse_sheet(rows)
    assert len(out) == 1
    assert out[0]["isin"] == "INE001A01010"
    assert out[0]["name"] == "A Limited"


def test_a_sheet_with_no_isin_column_is_not_guessed_at():
    """The regulation requires the column, so its absence means this is not a
    portfolio sheet. Guessing at a table with no anchor is how an index sheet
    becomes holdings."""
    header = ("Wrong", "Labels", "Entirely", "Quantity", "Market Value",
              "% to Net Assets")
    rows = [("Title",), (), header,
            ("code", "A Limited", "INE001A01010", "X", 10, 1.0, 100.0)]
    assert fw.parse_sheet(rows) == []


# ---------------------------------------------------------------------------
# THE SCALE TRAP
# ---------------------------------------------------------------------------

def test_a_weight_written_as_a_fraction_is_converted():
    """Some AMCs write 0.0333 and some write 3.33 for the same holding.
    Taking either at face value is a hundredfold error in the column readers
    compare across funds."""
    rows = _sheet([
        ("A Limited", "INE001A01010", "X", 10, 3330.0, 0.333),
        ("B Limited", "INE002A01018", "X", 10, 3330.0, 0.333),
        ("C Limited", "INE003A01016", "X", 10, 3340.0, 0.334),
    ])
    out = fw.parse_sheet(rows)
    assert [r["pct_nav"] for r in out] == pytest.approx([33.3, 33.3, 33.4])


def test_a_weight_already_a_percentage_is_left_alone():
    rows = _sheet([
        ("A Limited", "INE001A01010", "X", 10, 3330.0, 33.3),
        ("B Limited", "INE002A01018", "X", 10, 3330.0, 33.3),
        ("C Limited", "INE003A01016", "X", 10, 3340.0, 33.4),
    ])
    out = fw.parse_sheet(rows)
    assert [r["pct_nav"] for r in out] == pytest.approx([33.3, 33.3, 33.4])


def test_the_scale_is_decided_per_sheet_not_per_row():
    """A single small holding must not be mistaken for a fraction because it
    happens to be below 1."""
    rows = _sheet([("A Limited", "INE00%dA01010" % i, "X", 10, 100.0,
                    0.5 if i == 1 else 20.0) for i in range(1, 6)])
    out = fw.parse_sheet(rows)
    assert out[0]["pct_nav"] == pytest.approx(0.5), \
        "a 0.5% holding on a sheet summing to ~80 is 0.5%, not 50%"


# ---------------------------------------------------------------------------
# What is and is not a holding
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("heading", [
    "Equity & Equity related", "(a) Listed / awaiting listing",
    "Total", "Sub Total", "Grand Total", "Net Current Assets",
    "Money Market Instruments", "TREPS", "Cash & Cash Equivalents",
])
def test_section_headings_and_totals_are_not_holdings(heading):
    rows = _sheet([
        (heading, "INE001A01010", None, 100, 1.0, 1.0),
        ("A Real Company Limited", "INE002A01018", "X", 100, 1.0, 1.0),
    ])
    names = [r["name"] for r in fw.parse_sheet(rows)]
    assert heading not in names
    assert "A Real Company Limited" in names


def test_a_row_with_no_quantity_is_not_a_position():
    rows = _sheet([
        ("Exited Limited", "INE001A01010", "X", None, None, None),
        ("Zero Limited", "INE002A01018", "X", 0, 0.0, 0.0),
        ("Held Limited", "INE003A01016", "X", 100, 5.0, 1.0),
    ])
    assert [r["name"] for r in fw.parse_sheet(rows)] == ["Held Limited"]


def test_numbers_arriving_as_formatted_strings_are_read():
    rows = _sheet([("A Limited", "INE001A01010", "X", "1,00,000", "2,503.45", "6.56")])
    out = fw.parse_sheet(rows)
    assert out[0]["quantity"] == pytest.approx(100000)
    assert out[0]["value_lakh"] == pytest.approx(2503.45)


@pytest.mark.parametrize("code,ok", [
    ("INE002A01018", True),     # equity
    ("INE557F08FY4", True),     # a debenture — a valid ISIN, filtered later
    ("IN0020250075", True),     # a government security
    ("INE002A0101", False),     # too short
    ("XX002A01018", False),     # not an Indian ISIN
    ("Reliance Industries", False),
])
def test_only_well_formed_isins_anchor_a_row(code, ok):
    assert bool(fw.ISIN.match(code)) is ok


def test_an_xlsx_served_under_an_xls_name_is_recognised():
    """Baroda BNP's monthly pack is a real xlsx called .xls. Trusting the
    extension gets an opaque failure from the reader."""
    assert fw.looks_like_xlsx(b"PK\x03\x04rest of a zip") is True
    assert fw.looks_like_xlsx(b"\xd0\xcf\x11\xe0legacy xls") is False


def test_a_non_workbook_is_refused_clearly(tmp_path):
    p = tmp_path / "not.xlsx"
    p.write_bytes(b"<html>a login page</html>")
    with pytest.raises(ValueError, match="not an xlsx"):
        fw.parse_workbook(str(p))
