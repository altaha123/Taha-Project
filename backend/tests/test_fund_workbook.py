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


# ---------------------------------------------------------------------------
# The layouts the largest houses actually publish (measured November 2026)
# ---------------------------------------------------------------------------

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _book(tmp_path, sheets, name="pack.xlsx"):
    """A real xlsx on disk: {sheet name: [rows]}, in order."""
    import openpyxl
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for title, rows in sheets.items():
        ws = wb.create_sheet(title)
        for r in rows:
            ws.append(list(r))
    p = tmp_path / name
    wb.save(p)
    return str(p)


def test_a_weight_headed_to_aum_is_read():
    """SBI and Aditya Birla head the column "% to AUM". Unrecognised, every
    weight in their packs came out empty while the rows themselves read."""
    header = ("Name of the Instrument / Issuer", "ISIN", "Rating / Industry^",
              "Quantity", "Market value\n(Rs. in Lakhs)", "% to AUM")
    rows = _sheet([("HDFC Bank Limited", "INE040A01034", "Banks", 100, 10.0, 0.5),
                   ("ICICI Bank Limited", "INE090A01021", "Banks", 100, 10.0, 0.3),
                   ("Larsen & Toubro Limited", "INE018A01030", "Construction", 10, 4.0, 0.2)],
                  header=header)
    out = fw.parse_sheet(rows)
    assert [r["pct_nav"] for r in out] == [50.0, 30.0, 20.0]


@pytest.mark.parametrize("row,want", [
    (("Monthly Portfolio Statement as on October 31,2026",), "October 31,2026"),
    (("Portfolio as on Oct 31,2026",), "Oct 31,2026"),
    (("PROVISIONAL AND UNAUDITED PORTFOLIO DISCLOSURE AS OF 31/10/2026",), "31/10/2026"),
    (("Portfolio as on 31-Oct-2026",), "31-Oct-2026"),
])
def test_the_date_line_is_read_in_every_wording_the_big_houses_use(row, want):
    assert fw.as_on_hint([("x",), row]) == want


def test_a_date_in_the_cell_after_the_label_is_read():
    """SBI writes "PORTFOLIO STATEMENT AS ON :" in one cell and a real date in
    the next. Read cell by cell, neither cell says anything."""
    import datetime
    rows = [("SCHEME NAME :", "SBI Large and Midcap Fund"),
            ("PORTFOLIO STATEMENT AS ON :", datetime.datetime(2026, 10, 31))]
    assert fw.as_on_hint(rows).startswith("2026-10-31")


@pytest.mark.parametrize("raw,want", [
    ("HDFC Flexi Cap Fund (An open ended equity scheme investing across large "
     "cap, mid cap & small cap stocks)", "HDFC Flexi Cap Fund"),
    ("ADITYA BIRLA SUN LIFE AGGRESSIVE HYBRID FUND (FORMERLY KNOWN AS ADITYA "
     "BIRLA SUN LIFE EQUITY HYBRID '95 FUND) ", "ADITYA BIRLA SUN LIFE AGGRESSIVE HYBRID FUND"),
    ("SBI Aggressive Hybrid Fund (Erstwhile known as SBI Equity Hybrid Fund)",
     "SBI Aggressive Hybrid Fund"),
    ("UTI - Flexi Cap Fund.", "UTI Flexi Cap Fund"),
    ("Nippon India Conservative Hybrid Fund (An Open Ended Hybrid Scheme)\n"
     "Nippon India Conservative Hybrid Fund -Segregated Portfolio 2",
     "Nippon India Conservative Hybrid Fund"),
    ("Nippon India Vision Large & Mid Cap Fund", "Nippon India Vision Large & Mid Cap Fund"),
])
def test_scheme_names_lose_the_regulatory_description(raw, want):
    assert fw.clean_scheme_name(raw) == want


@pytest.mark.parametrize("rows,want", [
    # HDFC: the name, with its description, as the first line.
    ([("HDFC Mid Cap Fund (An open ended equity scheme)",) * 3,
      ("Portfolio as on 31-Oct-2026",), ()], "HDFC Mid Cap Fund"),
    # ICICI: the house first, then the scheme.
    ([("ICICI Prudential Mutual Fund",), ("ICICI Prudential Flexi Cap Fund",),
      ("Portfolio as on Oct 31,2026",)], "ICICI Prudential Flexi Cap Fund"),
    # SBI: a labelled line, the name in the next cell.
    ([(), ("SBI Mutual Fund", "007", "Back to Index"),
      ("SCHEME NAME :", "SBI ESG Exclusionary Strategy Fund")],
     "SBI ESG Exclusionary Strategy Fund"),
    # UTI: label and name in one cell.
    ([("SCHEME CODE002STARTS",), ("UTI MUTUAL FUND",),
      ("SCHEME: UTI - Large Cap Fund",)], "UTI Large Cap Fund"),
    # Nothing that reads like a name: no guess.
    ([("Monthly Portfolio Statement as on October 31,2026",), ()], None),
])
def test_a_sheet_names_its_own_scheme(rows, want):
    assert fw.sheet_title(rows) == want


def test_a_whole_house_in_one_sheet_is_split_into_its_schemes(tmp_path):
    """UTI publishes every scheme in one sheet, each block opened by a
    "SCHEME:" line. Read as one table, ninety schemes become one and a company
    held by forty of them is one position."""
    hdr = ("NAME OF THE INSTRUMENT ", "RATING/INDUSTRY", "QUANTITY",
           "MARKET-VALUE", "% TO NAV", "ISIN")

    def block(scheme, holdings):
        return ([("SCHEME CODE001STARTS",), ("UTI MUTUAL FUND",),
                 ("SCHEME: %s" % scheme,),
                 ("PROVISIONAL AND UNAUDITED PORTFOLIO DISCLOSURE AS OF 31/10/2026",),
                 (), hdr, ("EQUITY AND EQUITY RELATED",)] + holdings)

    rows = (block("UTI - Large Cap Fund", [
                ("EQ - HDFC BANK LIMITED", "Banks", 1000, 100.0, 60.0, "INE040A01034"),
                ("EQ - ICICI BANK LIMITED", "Banks", 500, 66.6, 40.0, "INE090A01021")]) +
            block("UTI - Mid Cap Fund", [
                ("EQ - HDFC BANK LIMITED", "Banks", 10, 1.0, 50.0, "INE040A01034"),
                ("EQ - LARSEN & TOUBRO LIMITED", "Construction", 10, 1.0, 50.0,
                 "INE018A01030")]))
    path = _book(tmp_path, {"exposure": rows})
    packs = fw.parse_workbook(path)
    assert [p["title"] for p in packs] == ["UTI Large Cap Fund", "UTI Mid Cap Fund"]
    assert [len(p["holdings"]) for p in packs] == [2, 2]
    assert packs[0]["holdings"][0]["name"] == "HDFC BANK LIMITED", "the EQ - prefix goes"
    assert packs[1]["as_on"] == "31/10/2026"
    assert len({p["sheet"] for p in packs}) == 2, "each block is its own scheme"


def test_a_long_sheet_is_read_to_the_end(tmp_path):
    """UTI's single sheet runs to about 9,400 rows. The old cap of 6,000 cut
    the house off a third of the way down with nothing saying so."""
    hdr = ("Name of the Instrument", "ISIN", "Industry", "Quantity",
           "Market value", "% to NAV")
    first = [("Early Holding %d" % i, "INE040A01034", "X", 10, 1.0, 1.0) for i in range(5)]
    filler = [("",)] * 7000
    rows = [("Some Fund",), hdr] + first + filler + [
        ("Late Holding Limited", "INE002A01018", "X", 10, 1.0, 1.0)]
    out = fw.parse_workbook(_book(tmp_path, {"S1": rows}))
    assert out and out[0]["holdings"][-1]["name"] == "Late Holding Limited"


@pytest.mark.parametrize("index_rows", [
    # SBI / Aditya Birla: "Scheme Code | Scheme Short code | Scheme Name"
    [("Index",), (), ("Scheme Code", "Scheme Short code", "Scheme Name"),
     ("007", "SMEEF", "SBI ESG Exclusionary Strategy Fund"),
     ("017", "SLMF", "SBI Large and Midcap Fund")],
    # Nippon India: two bare columns, no header at all.
    [("INDEX",),
     ("SMEEF", "SBI ESG Exclusionary Strategy Fund (An open ended scheme)"),
     ("SLMF", "SBI Large and Midcap Fund")],
])
def test_the_index_sheet_is_found_whatever_its_header_says(tmp_path, index_rows):
    hdr = ("Name of the Instrument", "ISIN", "Industry", "Quantity", "Market value", "% to NAV")
    sheet = [("x",), hdr, ("HDFC Bank Limited", "INE040A01034", "Banks", 1, 1.0, 100.0)]
    path = _book(tmp_path, {"Index": index_rows, "SMEEF": sheet, "SLMF": sheet})
    assert fw.scheme_names(path) == {
        "SMEEF": "SBI ESG Exclusionary Strategy Fund",
        "SLMF": "SBI Large and Midcap Fund"}


def test_one_coincidental_match_is_not_an_index(tmp_path):
    """ICICI's per-scheme workbooks have a "Derivative" sheet, and a holdings
    row elsewhere can contain that word. One match must not name the scheme
    after a company."""
    hdr = ("Company/Issuer/Instrument Name", "ISIN", "Industry/Rating", "Quantity",
           "Exposure/Market Value(Rs.Lakh)", "% to Nav")
    main = [("ICICI Prudential Mutual Fund",), ("ICICI Prudential Flexi Cap Fund",), hdr,
            ("Derivative", "KAYNES TECHNOLOGY INDIA LIMITED")]
    path = _book(tmp_path, {"FLEXCAP": main, "Derivative": [("x",)]})
    assert fw.scheme_names(path) == {}


def test_a_legacy_xls_pack_is_read():
    """Aditya Birla Sun Life's monthly pack is the legacy binary format inside
    a zip. It used to be refused outright; one of the largest houses in the
    industry was unreadable for that reason alone."""
    pytest.importorskip("xlrd")
    path = str(FIXTURES / "funds_legacy_pack.xls")
    assert fw.book_kind(path) == "xls"
    packs = fw.parse_workbook(path)
    names = fw.scheme_names(path)
    assert [p["sheet"] for p in packs] == ["BSL95F", "ADVG"]
    assert names["BSL95F"] == "ADITYA BIRLA SUN LIFE AGGRESSIVE HYBRID FUND"
    first = packs[0]["holdings"][0]
    # The row carries an internal code before the name: the header is one
    # column off its data, and the ISIN anchor still lines it up.
    assert first["name"] == "ICICI Bank Ltd." and first["isin"] == "INE090A01021"
    assert first["pct_nav"] == pytest.approx(6.21)
    assert packs[0]["as_on"] == "October 31, 2026"
