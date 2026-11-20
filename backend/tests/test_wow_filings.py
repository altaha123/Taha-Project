"""
WOW orders, against the shapes real order filings come in.

Every text here is cut from a filing made in one week of November 2026, with
the letterhead trimmed. They are here because of what the first reader did
with that week: it listed 58 order filings and called none of them WOW.

  · no company had a market value, because the price feeds it asked refuse
    the server's address, so no order could be sized against anything
  · fifteen orders read as "value not disclosed" although the filing states
    the value, because it is written out in rupees — "Rs.1,24,00,00,000.00" —
    which is how small companies write it, and small companies are where an
    order is largest against the company
  · the largest "order" of the week was a company's year-to-date order
    inflow, and the second largest another company's order book
  · two tax orders were listed as order wins
  · a lowest bid and the award that followed it were counted as two orders

There is a test for each, and for the table SEBI prescribes, which is where a
reader finds out what the order actually is.
"""
import datetime as dt
import sys
import time
import types

import pytest

import wow_orders as W


# ---------------------------------------------------------------------------
# An amount written out in rupees
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text,want", [
    ("has been awarded a new turnkey contract amounting to Rs.1,24,00,00,000.00 "
     "(Rupees One Hundred Twenty-Four Crore Only), inclusive of taxes", 124.0),
    ("The aggregate value of the aforesaid Purchase Order is ₹17,46,00,000 "
     "(INR Seventeen Crores Forty-Six Lakhs)", 17.46),
    ("we have received a work order of Rs. 131,10,40,131.85 (Rupees One Hundred "
     "Thirty-One Crore Ten Lakh Forty Thousand One Hundred Thirty-One)", 131.1),
    ("size of the Work order worth Rs.90740000/- (Rupees Nine Crore Seven lakhs "
     "and Forty Thousand) inclusive of Goods & Services Tax", 9.07),
    ("Letters of Award (LOA) from KRYFS Power Components Limited amounting to "
     "₹ 18,50,99,684 – Eighteen Crore Fifty Lacs", 18.51),
])
def test_an_amount_written_out_in_rupees_is_read(text, want):
    out = W.order_value_cr(text)
    assert out and out["value_cr"] == pytest.approx(want, abs=0.01)
    assert out["confident"] is True


def test_a_unit_after_the_number_still_decides_what_it_is():
    """'Rs. 26,913 Million' is 2,691 crore, not twenty-six thousand rupees and
    not twenty-six thousand crore."""
    out = W.order_value_cr("has received a Letter of Award (LOA) aggregating to "
                           "Rs. 26,913 million (Including GST) from NTPC Green Energy Limited")
    assert out["value_cr"] == pytest.approx(2691.3)
    assert W.order_value_cr("Order value is approximately Rs. 1,395.99 lakhs")["value_cr"] \
        == pytest.approx(13.96)


@pytest.mark.parametrize("text", [
    "at a tariff of Rs. 2.764 per unit for the 220 MW project",
    "The order carries a fee of Rs. 45,000 payable on signing.",
    "Ref No 2026/11/1,24,567 dated 16 November 2026",
])
def test_small_and_unlabelled_numbers_are_not_an_order(text):
    assert W.order_value_cr(text) is None


# ---------------------------------------------------------------------------
# The figure that is about the company's orders in general
# ---------------------------------------------------------------------------

KPIL = """Sub.: Press Release
We are enclosing herewith a copy of Press Release titled "KPIL SECURES NEW ORDER OF
₹ 2,610 CRORES."
PRESS RELEASE
Kalpataru Projects International Limited (KPIL) has secured notification of
award for a prestigious order worth approximately ₹2,610 crores.
The details of the aforesaid new order are as follows:
EPC project involving power transmission lines and substations in international market
Our order momentum continues to remain strong, with YTD FY27 order inflows exceeding
₹26,000 crore, registering a growth of over 50% year-on-year. In addition, we are favourably
positioned for projects worth approximately ₹5,000 crore."""

PACE = """Press Release
Pace Digitek Secures Its Largest-Ever BESS Order Worth Rs. 2,691 Crore from NTPC Green Energy
• Order win accelerates manufacturing-led growth and execution scale, driving executable order
book to Rs. 13,427 crore
Bengaluru, November 16, 2026 : Pace Digitek Limited today announced that it has secured a
landmark order worth Rs. 2,691 crore (inclusive of applicable GST) from NTPC Green Energy
Limited for the engineering, procurement and construction of the project."""


def test_a_years_order_inflow_is_not_the_order():
    out = W.order_value_cr(KPIL)
    assert out["value_cr"] == pytest.approx(2610.0)
    # And the words shown beside it are the sentence, not the letterhead.
    assert "has secured notification of award" in out["excerpt"]


def test_an_order_book_wrapped_across_two_lines_is_still_an_order_book():
    """The PDF breaks the line between 'order' and 'book'. Read a line at a
    time, the figure after it is the largest order-value figure on the page."""
    assert W.order_value_cr(PACE)["value_cr"] == pytest.approx(2691.0)


def test_a_size_band_is_not_a_size():
    """A company that tells the exchange only which band its order falls in
    has not stated a value, and the top of the band is not one."""
    text = ("we wish to inform you that the Company has received a following regular* "
            "Work Order from an Indian customer.\n"
            "*Classification of the Order size excluding taxes is as per below:\n"
            "Regular Orders Major Orders Large Orders\n"
            "Below ₹ 50 crore ₹ 50 crore to below ₹ 100\ncrore\n₹ 100 crore and above\n")
    assert W.order_value_cr(text) is None


def test_the_companys_own_conversion_beats_an_assumed_rate():
    out = W.order_value_cr("a Letter of Award for a 300 MLD Desalination Plant, worth about "
                           "USD 272 Million (SAR 1,019 Million / INR 2,332 Crores)")
    assert out["value_cr"] == pytest.approx(2332.0)
    assert out["currency_converted"] is False


def test_an_order_stated_only_in_dollars_says_what_rate_was_assumed():
    out = W.order_value_cr("The total value of the Letter of Award is USD 3.7 million "
                           "exclusive of GST.")
    assert out["value_cr"] == pytest.approx(0.37 * W.USD_INR, abs=0.01)
    assert out["currency_converted"] is True and out["fx_rate"] == W.USD_INR


# ---------------------------------------------------------------------------
# The prescribed table
# ---------------------------------------------------------------------------

TABLE = """Pursuant to Regulation 30, we wish to inform you that IVC Logistics Limited has awarded
an order of Rs. 362.85 crores for supply & manufacturing of 464 wagons.
Sl. No Particulars Details
1. Name of the entity awarding the
order(s)/contract(s)
IVC Logistics Limited
2. Significant terms and condition s of
order(s)/contract(s) awarded in brief
Supply & manufacturing of 464 wagons
3. Whether order(s) / contract(s) have
been awarded by domestic/
international entity
Domestic
4. Nature of order(s) / contract(s) Supply & manufacturing of 464 wagons comprising
Auto Car Taller wagon type ACT 3
This is for your information and record.
Yours faithfully,
For Texmaco Rail & Engineering Limited
5. Whether domestic or international Domestic
6. Time period by which the order(s) /
contract(s) is to be executed
On mutually agreed basis
7. Broad considerati on or size of the
order(s)/contract(s)
Rs. 362.85 crores (including taxes).
8. Whether the promoter/ promoter group / group companies have any interest in the
entity that awarded the order(s)/ contract(s)? If yes, nature of interest and details thereof
No
9. Whether the order(s)/contract(s) would fall within related party transactions?
No
"""


def test_the_table_says_who_awarded_it_what_for_and_by_when():
    d = W.describe(TABLE, "Texmaco Rail & Engineering Limited has informed the Exchange about "
                          "Bagging/Receiving of orders/contracts", "Texmaco Rail & Engineering Limited")
    assert d["customer"] == "IVC Logistics Limited"
    # The signature block the page break dropped into the row is not the order.
    assert d["nature"] == ("Supply & manufacturing of 464 wagons comprising "
                           "Auto Car Taller wagon type ACT 3")
    assert d["period"] == "On mutually agreed basis"
    assert d["stage"] == "order"


def test_the_size_row_of_the_table_is_the_value_and_says_so():
    out = W.order_value_cr(TABLE)
    assert out["value_cr"] == pytest.approx(362.85)
    assert out["basis"].startswith("stated as the size of the order")
    assert out["excerpt"] == "Rs. 362.85 crores (including taxes)."


@pytest.mark.parametrize("label,value,key,want", [
    ("Name of the entity awarding the Order/Contract", "Ministry of Defence, Government of India",
     "customer", "Ministry of Defence, Government of India"),
    ("Name of parties to the order(s)/contract(s);", "Saudi Water Authority",
     "customer", "Saudi Water Authority"),
    ("a. name of the entity awarding the order(s)/contract", "Awarded by -MSEDCL",
     "customer", "MSEDCL"),
    ("Name of the entity awarding the order(s) / contract(s)",
     "Rajasthan Metro Rail Corporation Ltd. Rajasthan Metro Rail Corporation Ltd.",
     "customer", "Rajasthan Metro Rail Corporation Ltd."),
    ("Time period by which the Order/Contract is to be executed", "Within 52 weeks",
     "period", "Within 52 weeks"),
    ("Time period by which the order(s)/contract(s) is to executed", "3 Months 7.",
     "period", "3 Months"),
])
def test_the_table_is_read_in_the_wordings_companies_actually_use(label, value, key, want):
    text = ("Significant terms and conditions of the order awarded, in brief As per the order\n"
            "%s %s\nNature of the order Supply of equipment\n"
            "Whether domestic or international Domestic\n"
            "Broad consideration or size of the order Rs. 12 crore\n"
            "Whether the promoter group have any interest No\n" % (label, value))
    assert W.disclosure(text)[key] == want


def test_a_row_number_is_taken_off_only_where_rows_are_numbered_that_way():
    """'60 Months 7' ends in the next row's number. 'wagon type ACT 3' does
    not, and the table it is in numbers its rows '4.'."""
    text = ("1 Name of the entity awarding the order(s)/contract(s) KRYFS Power Components Limited\n"
            "4 Nature of order(s) / contract(s) Manufacture and supply of Meter box\n"
            "6 Time period by which the order(s)/contract(s) is to be executed 60 Months\n"
            "7 Broad consideration or size of the order(s)/contract(s) Rs. 18 crore\n"
            "8 Whether the promoter group have any interest No\n")
    d = W.disclosure(text)
    assert d["customer"] == "KRYFS Power Components Limited"
    assert d["nature"] == "Manufacture and supply of Meter box" and d["period"] == "60 Months"
    assert W.disclosure(TABLE)["nature"].endswith("wagon type ACT 3")


def test_text_a_pdf_has_damaged_is_read_as_what_it_says():
    """Ligatures, and the glyphs some fonts print 'ti' and 'tt' as."""
    text = ("Name of the enƟty awarding the order(s)/contract(s); ChiƩaranjan Works\n"
            "Signiﬁcant terms and condiƟons of order(s)/contract(s) awarded in brief; As per LOA\n"
            "Nature of order(s) / contract(s); Propulsion equipment\n"
            "Whether domesƟc or internaƟonal; DomesƟc\n"
            "Broad consideraƟon or size of the order(s)/contract(s); Rs. 325,26,93,600 including GST\n"
            "Whether the promoter group have any interest; No\n")
    assert W.disclosure(W.tidy(text))["customer"] == "Chittaranjan Works"
    assert W.order_value_cr(text)["value_cr"] == pytest.approx(325.27, abs=0.01)


def test_an_amount_in_the_size_row_needs_no_rupee_sign():
    text = ("Name of the entity awarding the order(s)/contract(s); NHAI\n"
            "Nature of order(s) / contract(s); Toll collection\n"
            "Time period by which the order(s)/contract(s) is to be executed; 90 Days\n"
            "Broad consideration or size of the order(s)/contract(s); 10,99,79,910 (Rupees Ten "
            "Crore Ninety-Nine Lakh Seventy-Nine Thousand Nine Hundred and Ten Only)\n"
            "Whether the promoter group have any interest; No\n")
    assert W.order_value_cr(text)["value_cr"] == pytest.approx(11.0, abs=0.01)


def _table(customer, size):
    return ("Name of the entity awarding the order(s) / contract(s) %s\n"
            "Nature of order(s) / contract(s) Road works\n"
            "Whether domestic or international Domestic\n"
            "Time period by which the order(s) / contract(s) is to be executed 18 months\n"
            "Broad consideration or size of the order(s) / contract(s) %s\n"
            "Whether the promoter / promoter group have any interest No\n" % (customer, size))


def test_a_filing_for_several_orders_is_worth_all_of_them():
    text = ("has received Letters of Award / Work Orders. The details are below:\n"
            + _table("RKEC Projects Limited", "₹1,20,28,26,390/- including applicable GST")
            + _table("NHAI", "₹57,83,93,010/- including applicable GST")
            + _table("NHAI", "₹56,71,15,344/- including applicable GST"))
    out = W.order_value_cr(text)
    assert out["value_cr"] == pytest.approx(120.28 + 57.84 + 56.71, abs=0.02)
    assert out["basis"] == "the sum of the 3 orders this filing discloses"
    assert W.describe(text)["customer"] == "RKEC Projects Limited and 1 more"


def test_the_same_table_printed_twice_is_one_order():
    """An annexure repeated for the second exchange is not a second order."""
    text = "Receipt of order.\n" + _table("NHAI", "Rs. 40 crore") + _table("NHAI", "Rs. 40 crore")
    assert W.order_value_cr(text)["value_cr"] == pytest.approx(40.0)


def test_two_projects_in_one_table_take_the_total_the_filing_states():
    text = ("has been declared as the Lowest Bidder (L-1) for the said Projects. The quoted EPC "
            "Price for the Project aggregating to Rs.2,758.31 Crore, Incl. GST.\n"
            + _table("Rajasthan Metro Rail Corporation Ltd.",
                     "Quoted Project Price Rs.1130.31 Crore including GST Quoted Project Price "
                     "Rs.1628.00 Crore including GST"))
    out = W.order_value_cr(text)
    assert out["value_cr"] == pytest.approx(2758.31)
    assert "total of the orders" in out["basis"]


def test_a_breakdown_inside_one_order_is_not_added_to_it():
    text = "Receipt of order.\n" + _table(
        "CMK Projects", "approximately ₹48 Crores, comprising approximately ₹25 Crores for "
                        "NMDC works and ₹23 Crores for HAL works")
    assert W.order_value_cr(text)["value_cr"] == pytest.approx(48.0)


def test_a_customer_is_found_in_a_letter_that_has_no_table():
    d = W.describe("Sub: Intimation of workorder from M/S Hindalco Industries Limited worth "
                   "Rs.136.29 crores", "has informed the Exchange about Bagging/Receiving of "
                   "orders/contracts", "HEC Infra Projects Limited")
    assert d["customer"] == "Hindalco Industries Limited" and d["kind"] == "Work order"
    # The exchange the letter is addressed to is not who awarded the order.
    d = W.describe("To, BSE Limited, Dalal Street. We have received an order from National "
                   "Stock Exchange of India Limited.", "", "X Ltd")
    assert d["customer"] is None


def test_a_value_the_company_calls_confidential_is_said_to_be():
    text = ("Name of the entity awarding the order(s)/contract(s); Overseas customer\n"
            "Nature of order(s) / contract(s); Wire harness\n"
            "Time period by which the order(s)/contract(s) is to be executed; 4-6 months\n"
            "Broad consideration or size of the order(s)/contract(s); This cannot be disclosed "
            "being confidential in nature\nWhether the promoter group have any interest; No\n")
    row = W.read_filing({"symbol": "X", "company": "X Ltd", "headline": "Receipt of order",
                         "at": "2026-11-20T12:00:00+05:30", "pdf": "https://x/a.pdf"}, text)
    assert row["value_cr"] is None and row["value_state"] == "confidential"


# ---------------------------------------------------------------------------
# What kind of filing it is
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("headline", [
    "Protean eGov Technologies Limited has informed the Exchange about Receipt of "
    "Order-In-Appeal from the Office of the Commissioner of Central Tax (Appeals)",
    "DCM Nouvelle Limited has informed the Exchange regarding Rectification order received "
    "from Income Tax Department",
    "Receipt of show cause notice and demand order",
    "Order of the Hon'ble High Court in the matter of the Company",
])
def test_a_tax_or_court_order_is_not_an_order_win(headline):
    assert W.NOT_A_WIN.search(headline)


@pytest.mark.parametrize("headline", [
    "has received a Letter of Award (LOA) aggregating to Rs. 26,913 million (Including GST)",
    "Receipt of work order for construction of District Court Complex",
    "Receipt of Letter of Acceptance from the Municipal Commissioner, Pune",
    "Bagging/Receiving of orders/contracts",
])
def test_an_order_win_is_not_mistaken_for_a_tax_order(headline):
    assert not W.NOT_A_WIN.search(headline)


@pytest.mark.parametrize("headline,body,stage,kind", [
    ("Ashoka Buildcon Limited has informed the Exchange about L1 for NHAI Project",
     "the Company has been declared as the Lowest Bidder (L-1) for the said Project.",
     "l1", "Lowest bidder (L1)"),
    ("Ashoka Buildcon Limited has informed the Exchange about Receipt of LOA for NHAI Project",
     "Further to our earlier intimation dated November 17, 2026 the Company has received "
     "Letter of Acceptance for the said Project, for which it was declared L-1.",
     "order", "Letter of award"),
    ("ArMee Infotech Limited has informed the Exchange about Bagging/Receiving of orders",
     "Sub: Signing of Memorandum of Understanding (MoU) for a 135 MW Power Project",
     "mou", "Memorandum of understanding"),
    ("Update on our earlier intimation dated July 24, 2025 titled WABAG receives a Letter "
     "of Award", "worth about USD 272 Million", "update", "Letter of award"),
    ("X has informed the Exchange about Bagging/Receiving of orders/contracts",
     "we have received a purchase order from ABC Limited.", "order", "Purchase order"),
])
def test_a_bid_a_memorandum_and_an_update_are_told_from_an_order(headline, body, stage, kind):
    d = W.describe(body, headline, "")
    assert (d["stage"], d["kind"]) == (stage, kind)


# ---------------------------------------------------------------------------
# One row, sized against the company
# ---------------------------------------------------------------------------

def _item(symbol="SMALLCO", headline="Bagging/Receiving of orders/contracts", n=1, day=20):
    at = "2026-11-%02dT12:%02d:00+05:30" % (day, n)
    return {"symbol": symbol, "company": symbol.title() + " Limited", "headline": headline,
            "at": at, "pdf": "https://x/%s-%d.pdf" % (symbol, n)}


@pytest.fixture
def facts(monkeypatch):
    table = {"SMALLCO": {"market_cap_cr": 100.0, "sales_cr": 240.0, "sales_year": "FY26"},
             "BIGCO": {"market_cap_cr": 50000.0, "sales_cr": 30000.0, "sales_year": "FY26"},
             "NOSALES": {"market_cap_cr": 400.0, "sales_cr": None, "sales_year": None}}
    monkeypatch.setattr(W, "company_facts", lambda s: table.get(s, {}))
    monkeypatch.setattr(W, "market_cap_cr", lambda s: None)
    return table


def test_an_order_is_set_against_market_cap_and_a_year_of_sales(facts):
    row = W.size_up(W.read_filing(_item(), "We have received an order worth Rs. 60 crore."))
    assert row["market_cap_cr"] == 100.0 and row["pct_of_market_cap"] == 60.0
    assert row["wow"] is True and row["outsized"] is False
    assert row["pct_of_sales"] == 25.0 and row["months_of_sales"] == 3.0
    assert row["sales_year"] == "FY26"


def test_the_same_order_is_routine_for_a_large_company(facts):
    row = W.size_up(W.read_filing(_item("BIGCO"), "We have received an order worth Rs. 60 crore."))
    assert row["wow"] is False and row["pct_of_market_cap"] == pytest.approx(0.12)


def test_an_order_larger_than_the_company_is_flagged_to_be_checked(facts):
    row = W.size_up(W.read_filing(_item(), "Work order worth Rs.136.29 crores."))
    assert row["wow"] is True and row["outsized"] is True


def test_no_sales_on_file_means_no_sales_comparison(facts):
    row = W.size_up(W.read_filing(_item("NOSALES"), "Order worth Rs. 60 crore."))
    assert row["wow"] is True and row["months_of_sales"] is None


def test_a_bid_or_a_memorandum_is_never_wow_however_large(facts):
    bid = W.size_up(W.read_filing(
        _item(headline="has informed the Exchange about L1 for NHAI Project"),
        "declared as the Lowest Bidder (L-1). The quoted EPC Price is Rs. 90 Crore."))
    mou = W.size_up(W.read_filing(
        _item(), "Sub: Signing of Memorandum of Understanding (MoU). Aggregate order value "
                 "of Rs.16,29,03,15,000.00/-"))
    assert (bid["stage"], bid["wow"], bid["pct_of_market_cap"]) == ("l1", False, 90.0)
    assert (mou["stage"], mou["wow"]) == ("mou", False) and mou["outsized"] is True


def test_a_filing_that_was_not_read_says_so_and_is_not_called_undisclosed():
    row = W.read_filing(_item(), None)
    assert row["read"] is False and row["value_state"] == "unread" and row["value_cr"] is None


def test_an_amount_in_the_exchange_headline_is_used_when_the_document_gives_none():
    head = ("Viviana Power Tech Limited has informed the Exchange about Receiving of a new "
            "turnkey contract amounting to Rs.1,24,00,00,000.00")
    row = W.read_filing(_item(headline=head), None)
    assert row["value_cr"] == pytest.approx(124.0) and row["value_state"] == "stated"
    assert "headline" in row["value_basis"]


def test_a_bid_and_the_award_that_followed_are_one_order(facts):
    bid = W.size_up(W.read_filing(
        _item(headline="has informed the Exchange about L1 for NHAI Project", n=1, day=17),
        "declared as the Lowest Bidder (L-1). The quoted EPC Price for the Project is "
        "Rs.1465 Crore."))
    won = W.size_up(W.read_filing(
        _item(headline="has informed the Exchange about Receipt of LOA for NHAI Project",
              n=2, day=20),
        "the Company has received Letter of Acceptance. The accepted EPC Price for the "
        "Project is Rs.1,465.00 Crore."))
    other = W.size_up(W.read_filing(_item(n=3), "Order worth Rs. 12 crore."))
    rows = W.merge_repeats([bid, other, won])
    assert len(rows) == 2
    kept = next(r for r in rows if r["value_cr"] == pytest.approx(1465.0))
    assert kept["stage"] == "order" and kept["filings"] == 2
    assert kept["at"].startswith("2026-11-20")


def test_two_companies_with_the_same_order_value_are_two_orders(facts):
    a = W.size_up(W.read_filing(_item("SMALLCO"), "Order worth Rs. 60 crore."))
    b = W.size_up(W.read_filing(_item("BIGCO"), "Order worth Rs. 60 crore."))
    assert len(W.merge_repeats([a, b])) == 2


def test_wow_orders_lead_and_a_bid_never_outranks_an_order(facts):
    rows = [
        W.size_up(W.read_filing(_item("BIGCO"), "Order worth Rs. 600 crore.")),
        W.size_up(W.read_filing(_item(n=2), None)),
        W.size_up(W.read_filing(_item(headline="about L1 for a Project", n=3),
                                "Lowest Bidder (L-1). Quoted price Rs. 95 Crore.")),
        W.size_up(W.read_filing(_item(n=4), "Order worth Rs. 30 crore.")),
    ]
    order = [(r["stage"], r["wow"], r["value_cr"]) for r in W._order(rows)]
    assert order == [("order", True, 30.0), ("order", False, 600.0),
                     ("order", False, None), ("l1", False, 95.0)]
    counts = W._payload(rows, "")["counts"]
    assert counts["wow"] == 1 and counts["not_firm"] == 1 and counts["unread"] == 1
    assert counts["value_not_disclosed"] == 0


# ---------------------------------------------------------------------------
# Where the company's size comes from
# ---------------------------------------------------------------------------

def test_market_cap_comes_from_the_stored_tables_first(monkeypatch):
    """The price feeds are refused from the server's address. The screener's
    own tables are not, and they were never asked."""
    snap = types.ModuleType("fundamentals_query")
    snap.snapshot = lambda: ([{"symbol": "SMALLCO", "market_cap": 106.7, "sales": 0, "fy": "FY26"},
                              {"symbol": "OTHER", "market_cap": None, "sales": 500.0}], "now")
    monkeypatch.setitem(sys.modules, "fundamentals_query", snap)
    monkeypatch.setitem(W._facts, "at", 0.0)
    monkeypatch.setitem(W._facts, "by", {})
    monkeypatch.setattr(W, "_mcap_cache", {})
    assert W.company_facts("smallco") == {"market_cap_cr": 106.7, "sales_cr": None,
                                          "sales_year": "FY26"}
    assert W.market_cap_cr("SMALLCO") == 106.7
    assert W.company_facts("OTHER")["market_cap_cr"] is None
    assert W.company_facts("") == {} and W.company_facts("NEVERHEARD")["market_cap_cr"] is None


def test_tables_that_cannot_be_read_cost_the_size_and_not_the_page(monkeypatch):
    broken = types.ModuleType("fundamentals_query")

    def boom():
        raise RuntimeError("no tables on this instance")
    broken.snapshot = boom
    monkeypatch.setitem(sys.modules, "fundamentals_query", broken)
    monkeypatch.setitem(W._facts, "at", 0.0)
    monkeypatch.setitem(W._facts, "by", {})
    assert W.company_facts("SMALLCO")["market_cap_cr"] is None


# ---------------------------------------------------------------------------
# The ledger, and a better reader
# ---------------------------------------------------------------------------

@pytest.fixture
def ledger(tmp_path, monkeypatch):
    monkeypatch.setattr(W, "DB_PATH", str(tmp_path / "wow.db"))
    monkeypatch.setitem(W._db_ready, "done", False)
    return W


def _seen(day, value, reader, symbol="TESTCO", pdf=None, headline="Order win", stage="order"):
    return {"symbol": symbol, "company": symbol, "headline": headline,
            "at": day.isoformat() + "T10:00:00+05:30", "date": day.isoformat(),
            "pdf": pdf or "https://x/%s-%s.pdf" % (symbol, day.isoformat()),
            "value_cr": value, "value_confident": True, "currency_converted": False,
            "market_cap_cr": None, "pct_of_market_cap": None, "reader": reader, "stage": stage}


def test_a_newer_reader_corrects_a_row_and_the_same_reader_cannot(ledger):
    day = dt.date(2026, 11, 16)
    assert ledger.record([_seen(day, 26000.0, reader=1)]) == 1
    assert ledger.record([_seen(day, 2610.0, reader=W.READER)]) == 1
    assert ledger.history(day, day)[0]["value_cr"] == 2610.0
    # Read again by the same reader, whatever it now says, changes nothing.
    assert ledger.record([_seen(day, 9999.0, reader=W.READER)]) == 0
    assert ledger.history(day, day)[0]["value_cr"] == 2610.0


def test_a_ledger_written_before_readers_were_numbered_still_opens(ledger, tmp_path):
    import sqlite3
    conn = sqlite3.connect(ledger.DB_PATH)
    conn.execute("""CREATE TABLE orders (key TEXT PRIMARY KEY, seen_at TEXT NOT NULL,
        date TEXT, at TEXT, symbol TEXT, company TEXT, headline TEXT, pdf TEXT,
        value_cr REAL, value_confident INTEGER, currency_converted INTEGER,
        market_cap_cr REAL, pct_of_market_cap REAL)""")
    conn.execute("INSERT INTO orders VALUES ('k','t','2026-10-05','2026-10-05T10:00:00+05:30',"
                 "'LT','Larsen','Order win','https://x/lt.pdf',278400.0,1,0,NULL,NULL)")
    conn.commit(); conn.close()
    rows = ledger.history(dt.date(2026, 10, 1), dt.date(2026, 10, 31))
    assert len(rows) == 1 and rows[0]["reader"] == 1 and rows[0]["stage"] is None


def test_a_value_from_the_old_reader_is_not_added_up_until_it_is_read_again(ledger, monkeypatch):
    """The quarter's total was 22 lakh crore, most of it one company's order
    book read as an order. An unchecked figure is left out and counted as
    waiting, not added in."""
    today = dt.date(2026, 11, 20)
    start = dt.date(2026, 10, 1)
    ledger.mark_covered([start + dt.timedelta(days=i) for i in range(60)])
    ledger.record([_seen(dt.date(2026, 10, 5), 278400.0, reader=1, symbol="LT"),
                   _seen(dt.date(2026, 11, 16), 2610.0, reader=W.READER, symbol="KPIL"),
                   _seen(dt.date(2026, 11, 17), 1465.0, reader=W.READER, symbol="ASHOKA", stage="l1"),
                   _seen(dt.date(2026, 11, 18), 41.0, reader=W.READER, symbol="TAX",
                         stage="not_order")])
    q = ledger.quarter_comparison(today)["this_quarter"]
    assert q["total_cr"] == 2610.0 and q["biggest"]["symbol"] == "KPIL"
    assert q["awaiting_reread"] == 1
    assert q["orders"] == 3, "a tax order is not an order; a bid and an unread row are listed"
    assert "still to be read again" in ledger.quarter_comparison(today)["caveat"]

    # Its filing is on disk, so the next pass reads it again without fetching.
    ft = types.ModuleType("filings_text")
    ft.cached = lambda url: ("We have secured orders worth Rs. 1,200 crore. Our order book "
                             "stands at Rs. 2,78,400 crore." if "LT" in url else None)
    monkeypatch.setitem(sys.modules, "filings_text", ft)
    monkeypatch.setattr(W, "company_facts", lambda s: {})
    monkeypatch.setattr(W, "market_cap_cr", lambda s: None)
    assert ledger.reread() == 1
    q = ledger.quarter_comparison(today)["this_quarter"]
    assert q["total_cr"] == 2610.0 + 1200.0 and q["awaiting_reread"] == 0


def test_rereading_takes_a_tax_order_out_of_the_ledgers_count(ledger, monkeypatch):
    day = dt.date(2026, 11, 18)
    ledger.record([_seen(day, 5.65, reader=1, headline="Receipt of Order-In-Appeal from the "
                         "Office of the Commissioner of Central Tax")])
    ft = types.ModuleType("filings_text")
    ft.cached = lambda url: None
    monkeypatch.setitem(sys.modules, "filings_text", ft)
    assert ledger.reread() == 1
    row = ledger.history(day, day)[0]
    assert row["stage"] == "not_order" and row["value_cr"] is None


# ---------------------------------------------------------------------------
# What a share card reads
# ---------------------------------------------------------------------------

@pytest.fixture
def shelf(ledger, monkeypatch):
    """A ledger and an empty list in memory, with nothing behind them: the
    exchange and the filing reader both fail the test if a card asks."""
    monkeypatch.setattr(W, "_cache", {"at": 0.0, "rows": [], "note": ""})
    monkeypatch.setattr(W, "company_facts", lambda s: {"market_cap_cr": 100.0, "sales_cr": 240.0,
                                                       "sales_year": "FY26"})
    monkeypatch.setattr(W, "market_cap_cr", lambda s: 100.0)
    monkeypatch.setattr(W, "_order_items", lambda days: pytest.fail("a card walked the feed"))
    monkeypatch.setattr(W, "scan", lambda *a, **k: pytest.fail("a card started a scan"))
    return W


def _won(n=1, day=20, text="We have received an order worth Rs. 60 crore.", **item):
    row = W.size_up(W.read_filing(_item(n=n, day=day, **item), text))
    return row


def test_every_row_carries_the_handle_a_link_names_it_by():
    a, b = _won(n=1), _won(n=2)
    assert len(a["key"]) == W.KEY_LEN and a["key"] != b["key"]
    assert all(c in "0123456789abcdef" for c in a["key"])
    # The same filing is the same order, whenever it is read.
    assert _won(n=1)["key"] == a["key"]


def test_a_card_is_drawn_from_the_list_on_the_page(shelf):
    a, b = _won(n=1), _won(n=2, text="Order worth Rs. 25 crore from ABC Limited.")
    shelf._cache["rows"] = [a, b]
    got = shelf.for_card("smallco", b["key"])
    assert got["value_cr"] == 25.0 and got["customer"] == "ABC Limited"
    # However the handle is spelled, and with only its start.
    assert shelf.for_card("SMALLCO", b["key"][:8].upper())["key"] == b["key"]


def test_a_card_outlives_the_week_it_was_shared_in(shelf):
    """The list keeps a week. The ledger keeps the row as the page showed it,
    so the card drawn next month is the card that was shared."""
    text = ("Name of the entity awarding the order(s)/contract(s); NTPC Green Energy Limited\n"
            "Nature of order(s) / contract(s); BESS system supply\n"
            "Time period by which the order(s)/contract(s) is to be executed; By September 2027\n"
            "Broad consideration or size of the order(s)/contract(s); Rs. 60 crore\n"
            "Whether the promoter group have any interest; No\n")
    row = _won(n=7, day=3, text=text)
    assert shelf.record([row]) == 1
    got = shelf.for_card("SMALLCO", row["key"])
    for k in ("value_cr", "pct_of_market_cap", "market_cap_cr", "customer", "nature", "period",
              "months_of_sales", "sales_year", "wow", "key", "at"):
        assert got[k] == row[k], k
    assert got["kind"] == row["kind"] and got["stage"] == "order"


def test_a_link_with_no_handle_or_a_stale_one_is_the_newest_order(shelf):
    old = _won(n=1, day=3, text="Order worth Rs. 20 crore.")
    new = _won(n=2, day=18, text="Order worth Rs. 45 crore.")
    shelf.record([old, new])
    assert shelf.for_card("SMALLCO")["value_cr"] == 45.0
    assert shelf.for_card("SMALLCO", "ffffffffffff")["value_cr"] == 45.0
    assert shelf.for_card("SMALLCO", old["key"])["value_cr"] == 20.0


def test_there_is_no_card_for_what_the_page_would_not_stand_behind(shelf, monkeypatch):
    bid = _won(n=1, headline="has informed the Exchange about L1 for NHAI Project",
               text="declared as the Lowest Bidder (L-1). The quoted EPC Price is Rs. 90 Crore.")
    mou = _won(n=2, text="Sub: Signing of Memorandum of Understanding (MoU). Aggregate order "
                         "value of Rs.16,29,03,15,000.00/-")
    loose = _won(n=3, text="Reference 2026. The figure Rs. 75 crore appears here.")
    blank = W.size_up(W.read_filing(_item(n=4), "We have received an order."))
    assert (bid["stage"], mou["stage"], loose["value_confident"], blank["value_cr"]) == \
        ("l1", "mou", False, None)
    shelf._cache["rows"] = [bid, mou, loose, blank]
    shelf.record([bid, mou, loose, blank])
    assert shelf.for_card("SMALLCO") is None
    for row in (bid, mou, loose, blank):
        assert shelf.for_card("SMALLCO", row["key"]) is None
    # No market cap, no card: the percentage is the card.
    monkeypatch.setattr(W, "company_facts", lambda s: {})
    monkeypatch.setattr(W, "market_cap_cr", lambda s: None)
    unsized = W.size_up(W.read_filing(_item("NOCAP"), "Order worth Rs. 60 crore."))
    shelf.record([unsized])
    assert shelf.for_card("NOCAP") is None
    assert shelf.for_card("") is None and shelf.for_card("NEVERFILED") is None


def test_a_value_the_old_reader_wrote_down_is_never_put_on_a_card(shelf):
    day = dt.date(2026, 10, 5)
    row = dict(_seen(day, 278400.0, reader=1, symbol="LT"), market_cap_cr=500000.0,
               pct_of_market_cap=55.7)
    shelf.record([row])
    assert shelf.for_card("LT") is None


def test_a_row_written_before_details_were_kept_gets_them_on_the_next_read(shelf):
    row = _won(n=9, text="Order worth Rs. 25 crore from ABC Limited.")
    bare = {k: v for k, v in row.items() if k not in W._DETAIL}
    assert shelf.record([bare]) == 1
    assert shelf.for_card("SMALLCO", row["key"])["customer"] is None
    assert shelf.record([row]) == 0, "the same reader does not restate a row"
    got = shelf.for_card("SMALLCO", row["key"])
    assert got["customer"] == "ABC Limited" and got["value_cr"] == 25.0


# ---------------------------------------------------------------------------
# A page is answered at once
# ---------------------------------------------------------------------------

@pytest.fixture
def quiet(ledger, monkeypatch):
    monkeypatch.setattr(W, "_cache", {"at": 0.0, "rows": [], "note": ""})
    monkeypatch.setattr(W, "_reading", {"on": False, "started": 0.0, "error": ""})
    monkeypatch.setattr(W, "company_facts", lambda s: {"market_cap_cr": 100.0})
    monkeypatch.setattr(W, "market_cap_cr", lambda s: 100.0)
    ft = types.ModuleType("filings_text")
    ft.available = lambda: True
    ft.cached = lambda url: None
    ft.extract = lambda url: "We have received an order worth Rs. 60 crore."
    monkeypatch.setitem(sys.modules, "filings_text", ft)
    return W


def _until(done, seconds=5.0):
    stop = time.time() + seconds
    while time.time() < stop:
        if done():
            return True
        time.sleep(0.02)
    return False


def test_the_page_is_answered_before_a_single_filing_is_read(quiet, monkeypatch):
    gate = {"open": False}

    def slow(days):
        _until(lambda: gate["open"])
        return ([_item()], "")
    monkeypatch.setattr(W, "_order_items", slow)

    began = time.time()
    first = W.feed(days=7)
    assert time.time() - began < 1.0, "the answer waited for the exchange"
    assert first["rows"] == [] and first["reading"] is True and first["poll_seconds"]
    # Asked again while it reads: still an answer, and not a second reader.
    assert W.feed(days=7)["reading"] is True

    gate["open"] = True
    assert _until(lambda: not W._reading["on"])
    done = W.feed(days=7)
    assert done["reading"] is False and done["poll_seconds"] is None
    assert [r["symbol"] for r in done["rows"]] == ["SMALLCO"] and done["rows"][0]["wow"] is True
    assert done["read_at"]


def test_a_stale_list_is_shown_while_a_fresh_one_is_read(quiet, monkeypatch):
    monkeypatch.setattr(W, "_order_items", lambda days: ([_item()], ""))
    W.scan(days=7, force=True)
    W._cache["at"] = time.time() - W.CACHE_TTL - 5
    gate = {"open": False}

    def slow(days):
        _until(lambda: gate["open"])
        return ([_item(), _item("BIGCO", n=2)], "")
    monkeypatch.setattr(W, "_order_items", slow)
    stale = W.feed(days=7)
    assert len(stale["rows"]) == 1 and stale["reading"] is True
    gate["open"] = True
    assert _until(lambda: not W._reading["on"])
    assert len(W.feed(days=7)["rows"]) == 2


def test_a_read_that_fails_leaves_the_list_and_says_why(quiet, monkeypatch):
    def broken(days):
        raise RuntimeError("exchange is down")
    monkeypatch.setattr(W, "_order_items", broken)
    W.feed(days=7)
    assert _until(lambda: not W._reading["on"])
    assert "could not be read" in W._reading["error"]


def test_a_week_with_no_orders_is_not_read_again_on_every_visit(quiet, monkeypatch):
    calls = []
    monkeypatch.setattr(W, "_order_items", lambda days: (calls.append(1), ([], ""))[1])
    W.feed(days=7)
    assert _until(lambda: not W._reading["on"])
    for _ in range(3):
        out = W.feed(days=7)
        assert out["reading"] is False and out["rows"] == []
    assert len(calls) == 1


def test_a_failed_read_is_not_retried_by_every_page_that_asks(quiet, monkeypatch):
    calls = []

    def broken(days):
        calls.append(1)
        raise RuntimeError("exchange is down")
    monkeypatch.setattr(W, "_order_items", broken)
    W.feed(days=7)
    assert _until(lambda: not W._reading["on"])
    out = W.feed(days=7)
    assert out["reading"] is False and "could not be read" in out["note"]
    assert len(calls) == 1


def test_a_scan_drops_tax_orders_and_merges_repeats(quiet, monkeypatch):
    items = [_item(n=1), _item(n=2),
             _item("TAXCO", "Receipt of Order-In-Appeal from the Commissioner of Central Tax", n=3)]
    monkeypatch.setattr(W, "_order_items", lambda days: (items, ""))
    out = W.scan(days=7, force=True)
    assert [r["symbol"] for r in out["rows"]] == ["SMALLCO"]
    assert out["rows"][0]["filings"] == 2 and out["counts"]["orders"] == 1
