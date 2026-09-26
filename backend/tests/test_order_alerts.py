"""
WOW order alerts: one Telegram message per order worth at least WOW_MIN_PCT of
the company, and nothing else.

Each test below is a way the alert could be wrong on a real phone:
  · a running total or a bid pipeline read as the order (Kalpataru, 24 Sep:
    "orders worth Rs 13,219 crore so far" and "L1 for orders exceeding
    Rs 12,000 crore" around an order of Rs 2,025 crore);
  · the company PLACING an order read as winning one (RCF, 25 Sep);
  · the same order alerted twice, or an afternoon replayed after a restart;
  · no market cap, because every source for it had silently failed.
"""
import time

import pytest

import nse_mcap
import order_alerts as O
import wow_orders as W


# ---------------------------------------------------------------------------
# Reading the right number
# ---------------------------------------------------------------------------

KPIL = (
    "KPIL Announces New Order Wins of ₹2,025 Crores\n"
    "Kalpataru Projects International Limited has secured new orders and "
    "notifications of awards totalling approx. ₹2,025 Crores.\n"
    "We have secured orders worth ₹13,219 crore so far in the current fiscal "
    "year (YTD FY27). Additionally, we are favorably placed / L1 for orders "
    "exceeding ₹12,000 crore, giving us strong confidence.")


def test_running_totals_and_bids_are_not_the_order():
    assert W.order_value_cr(KPIL)["value_cr"] == pytest.approx(2025.0)


def test_placing_an_order_is_not_winning_one():
    assert W.placed_by_company(
        "the Board has accorded its approval for Placement of the \n"
        "Purchase Order, on M/s. Larsen and Toubro Limited for Rs.797 Crores")
    assert not W.placed_by_company(
        "The Company has received a Purchase Order from NTPC for Rs 450 crore")


# ---------------------------------------------------------------------------
# Market cap from NSE's daily file
# ---------------------------------------------------------------------------

MCAP_CSV = (
    "Trade Date,Symbol,Series,Security Name,Category,Last Trade Date,"
    "Face Value(Rs.),Issue Size,Close Price/Paid up value(Rs.),Market Cap(Rs.)\n"
    "25 SEP 2026,KPIL,EQ,KALPATARU PROJECT INT LTD,Listed    ,25 SEP 2026,"
    "   2.00,   170772546,   1391.20,   237578765995.20      \n"
    "25 SEP 2026,DUPE,BE,DUPE LTD,Listed,25 SEP 2026,1,10,5,999999999\n"
    "25 SEP 2026,DUPE,EQ,DUPE LTD,Listed,25 SEP 2026,1,10,5,100000000\n")


def test_the_market_cap_file_is_read_in_crore_and_prefers_eq():
    caps = nse_mcap.parse(MCAP_CSV)
    assert caps["KPIL"] == pytest.approx(23757.88)
    assert caps["DUPE"] == pytest.approx(10.0)


# ---------------------------------------------------------------------------
# Deciding and sending
# ---------------------------------------------------------------------------

@pytest.fixture
def harness(monkeypatch, tmp_path):
    monkeypatch.setattr(W, "DB_PATH", str(tmp_path / "wow.db"))
    monkeypatch.setitem(W._db_ready, "done", False)
    monkeypatch.setattr(O, "_done", set())
    monkeypatch.setattr(O, "_tries", {})
    sent = []
    monkeypatch.setattr(O, "_send", lambda text: (sent.append(text) or (True, "sent")))
    texts = {}
    import filings_text
    monkeypatch.setattr(filings_text, "available", lambda: True)
    monkeypatch.setattr(filings_text, "extract", lambda url: texts.get(url))
    caps = {"BIG": 1000.0, "SMALL": 100000.0}
    monkeypatch.setattr(W, "market_cap_cr", lambda s: caps.get(s))
    return sent, texts


def _item(sym, pdf, age_s=20):
    return {"symbol": sym, "company": sym + " Ltd", "headline": "order", "pdf": pdf,
            "category": "Order win", "epoch": time.time() - age_s,
            "at": "2026-09-25T10:00:00+05:30"}


def test_a_wow_order_is_alerted_once(harness):
    sent, texts = harness
    texts["p1"] = "The Company has received an order valued at Rs. 250 crore."
    item = _item("BIG", "p1")
    O._handle(item)
    O._handle(item)
    assert len(sent) == 1
    assert "25.0%" in sent[0] and "BIG" in sent[0]


def test_small_undisclosed_and_placed_orders_are_not_alerted(harness):
    sent, texts = harness
    texts["p2"] = "The Company has received an order valued at Rs. 250 crore."
    texts["p3"] = "Letter of Intent for supply of 400 containers."
    texts["p4"] = "Approval for placement of purchase order on M/s ABC for Rs 500 crore."
    O._handle(_item("SMALL", "p2"))
    O._handle(_item("BIG", "p3"))
    O._handle(_item("BIG", "p4"))
    assert sent == []
    assert {r["outcome"] for r in O.recent()} == {
        "below threshold", "value not disclosed", "placed by the company"}


def test_old_filings_are_not_replayed_after_a_restart(harness):
    sent, texts = harness
    texts["p5"] = "The Company has received an order valued at Rs. 250 crore."
    O._handle(_item("BIG", "p5", age_s=O.MAX_AGE_MIN * 60 + 60))
    assert sent == []


def test_an_unreadable_pdf_is_retried_then_given_up(harness):
    sent, texts = harness
    item = _item("BIG", "missing")
    for _ in range(O.MAX_TRIES - 1):
        O._handle(item)
    assert O.recent() == []
    texts["missing"] = "order valued at Rs. 250 crore"
    O._handle(item)
    assert len(sent) == 1


def test_the_message_says_what_was_measured():
    msg = O.format_alert({"symbol": "BIG", "company": "Big & Co", "headline": "<b>x</b>",
                          "at": "2026-09-25T10:00:00+05:30", "pdf": "https://x/y.pdf",
                          "value_cr": 250.0, "market_cap_cr": 1000.0,
                          "pct_of_market_cap": 25.0, "value_confident": True},
                         lag_s=21, close_date="2026-09-24")
    assert "25.0%" in msg and "₹250 cr" in msg and "₹1,000 cr" in msg
    assert "close 24 Sep" in msg and "21s after NSE" in msg
    assert "Big &amp; Co" in msg and "&lt;b&gt;x" in msg
