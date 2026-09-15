"""
WOW orders: an order sized against the company that won it.

The feature is one division — order value over market capitalisation — so
everything that can go wrong is in the numerator. Three things in particular,
and there is a test for each:

  · picking the WRONG figure out of the filing. A Reg 30 disclosure routinely
    states the company's paid-up capital, last year's turnover, or its order
    book in the same breath as the order. The largest number on the page is
    frequently not the order.
  · inventing a figure the company never disclosed. Plenty of order filings
    quantify a contract in containers or megawatts and give no rupee amount at
    all — the live filing this was built against is one. That has to read as
    "not disclosed", never as zero and never as an estimate.
  · comparing a quarter against one this service was not recording for, which
    would report a collapse in order inflow that is really a gap in the ledger.
"""
import datetime as dt

import pytest

import wow_orders as W


# ---------------------------------------------------------------------------
# Getting the right number out of the filing
# ---------------------------------------------------------------------------

def test_a_labelled_order_value_is_read():
    out = W.order_value_cr(
        "The Company has received a work order. The order value is "
        "Rs. 450.75 crore, to be executed over 24 months.")
    assert out["value_cr"] == pytest.approx(450.75)
    assert out["confident"] is True


@pytest.mark.parametrize("text,want", [
    ("ABC Ltd has bagged a contract worth Rs 1,250 crore from NTPC.", 1250.0),
    ("Work order valued at Rs. 4,500 lakhs received.", 45.0),
    ("Order Value\nRs. 89.50 crore\nClient: NHAI", 89.5),
    ("The company received an order aggregating to Rs. 120 crore.", 120.0),
])
def test_the_shapes_a_filing_states_a_value_in(text, want):
    assert W.order_value_cr(text)["value_cr"] == pytest.approx(want)


def test_paid_up_capital_is_not_the_order_even_when_it_is_bigger():
    """The exact shape that makes 'largest figure in the document' wrong."""
    out = W.order_value_cr(
        "The paid-up share capital of the Company is Rs. 5,000 crore. "
        "The company received an order aggregating to Rs. 120 crore.")
    assert out["value_cr"] == pytest.approx(120.0)


@pytest.mark.parametrize("text,want", [
    ("Turnover for the year was Rs 2,000 crore. Order value: Rs 75 crore.", 75.0),
    ("Market capitalisation is Rs. 3,700 crore. The order is valued at "
     "Rs. 450 crore.", 450.0),
])
def test_other_figures_in_the_same_filing_are_not_the_order(text, want):
    assert W.order_value_cr(text)["value_cr"] == pytest.approx(want)


def test_an_order_book_alone_is_not_an_order():
    assert W.order_value_cr("The order book stands at Rs 8,000 crore as on date.") is None


def test_a_filing_that_states_no_rupee_value_yields_nothing():
    """
    The live case this was built against: a Letter of Intent quantified in
    containers. A guess here would be a fabricated figure about a real company.
    """
    assert W.order_value_cr(
        "Receipt of Letter of Intent for setting up a Container Freight Station "
        "with an annual storage capacity of approximately 80,000 containers.") is None


def test_an_unlabelled_figure_is_returned_but_marked_unconfident():
    out = W.order_value_cr("The company informed that Rs 300 crore was involved "
                           "in the transaction.")
    assert out["value_cr"] == pytest.approx(300.0)
    assert out["confident"] is False
    assert "does not label" in out["basis"]


def test_a_foreign_currency_order_says_it_was_converted():
    out = W.order_value_cr("The Company received an export order valued at USD 40 million.")
    assert out["currency_converted"] is True


def test_a_value_carries_the_words_it_was_read_from():
    out = W.order_value_cr("The order value is Rs. 450 crore for the Kandla project.")
    assert "450" in out["excerpt"]
    assert out["basis"]


def test_a_comparison_against_last_year_is_declined_rather_than_guessed():
    """
    "Rs 90 crore against Rs 400 crore in the corresponding quarter" has two
    figures and one sentence. Picking either is a coin toss, so it picks
    neither. A deliberate refusal, not an oversight.
    """
    assert W.order_value_cr(
        "Order value Rs 90 crore against Rs 400 crore in the corresponding "
        "quarter.") is None


@pytest.mark.parametrize("text", ["", None, "No numbers here at all."])
def test_empty_input_is_not_an_error(text):
    assert W.order_value_cr(text) is None


def test_an_absurd_figure_is_rejected():
    assert W.order_value_cr("Order value of Rs 99,00,00,000 crore.") is None


# ---------------------------------------------------------------------------
# Indian fiscal quarters
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("day,label,prev", [
    ("2026-04-01", "Q1 FY27", "Q4 FY26"),
    ("2026-06-30", "Q1 FY27", "Q4 FY26"),
    ("2026-07-01", "Q2 FY27", "Q1 FY27"),
    ("2026-09-30", "Q2 FY27", "Q1 FY27"),
    ("2026-10-01", "Q3 FY27", "Q2 FY27"),
    ("2026-12-31", "Q3 FY27", "Q2 FY27"),
    ("2026-01-01", "Q4 FY26", "Q3 FY26"),
    ("2026-03-31", "Q4 FY26", "Q3 FY26"),
])
def test_the_indian_fiscal_year_not_the_calendar_one(day, label, prev):
    d = dt.date.fromisoformat(day)
    assert W.fiscal_quarter(d)[0] == label
    assert W.previous_quarter(d)[0] == prev


def test_a_quarter_covers_exactly_three_months():
    label, start, end = W.fiscal_quarter(dt.date(2026, 5, 15))
    assert start == dt.date(2026, 4, 1)
    assert end == dt.date(2026, 6, 30)


def test_the_year_boundary_does_not_lose_a_quarter():
    """Q4 of one FY must hand over to Q1 of the next, not to Q1 of the same."""
    assert W.previous_quarter(dt.date(2026, 4, 5))[0] == "Q4 FY26"
    assert W.fiscal_quarter(dt.date(2026, 3, 25))[0] == "Q4 FY26"


# ---------------------------------------------------------------------------
# The ledger and the comparison
# ---------------------------------------------------------------------------

@pytest.fixture
def ledger(tmp_path, monkeypatch):
    monkeypatch.setattr(W, "DB_PATH", str(tmp_path / "orders.db"))
    monkeypatch.setitem(W._db_ready, "done", False)
    return W


def _order(day, value=None, symbol="TESTCO", pdf=None):
    return {"symbol": symbol, "company": "Test Co", "headline": "order win",
            "date": day, "at": day + "T10:00:00+05:30",
            "pdf": pdf or ("https://x/%s%s" % (symbol, day)),
            "value_cr": value, "value_confident": True,
            "currency_converted": False,
            "market_cap_cr": 1000.0 if value else None,
            "pct_of_market_cap": round(100 * value / 1000.0, 2) if value else None}


def test_the_ledger_never_restates_an_event(ledger):
    first = _order("2026-08-01", 250.0)
    assert ledger.record([first]) == 1
    # the same filing seen again, now with a different number attached
    again = dict(first, value_cr=999.0)
    assert ledger.record([again]) == 0
    rows = ledger.history(dt.date(2026, 7, 1), dt.date(2026, 9, 30))
    assert len(rows) == 1
    assert rows[0]["value_cr"] == pytest.approx(250.0)


def test_an_event_with_no_date_is_not_recorded(ledger):
    assert ledger.record([dict(_order("2026-08-01", 10.0), date=None)]) == 0


def _cover(ledger, start, end):
    """Mark every trading day in a range as looked at."""
    days, day = [], start
    while day <= end:
        if day.weekday() < 5:
            days.append(day)
        day += dt.timedelta(days=1)
    ledger.mark_covered(days)


def test_quarter_on_quarter_counts_only_disclosed_values(ledger):
    _cover(ledger, dt.date(2026, 4, 1), dt.date(2026, 9, 15))
    ledger.record([
        _order("2026-05-05", 100.0), _order("2026-05-06", 50.0, symbol="B"),
        _order("2026-05-07", None, symbol="C"),          # not disclosed
        _order("2026-08-05", 300.0), _order("2026-08-06", None, symbol="D"),
    ])
    out = ledger.quarter_comparison(today=dt.date(2026, 9, 15))
    assert out["this_quarter"]["label"] == "Q2 FY27"
    assert out["this_quarter"]["total_cr"] == pytest.approx(300.0)
    assert out["this_quarter"]["value_not_disclosed"] == 1
    assert out["previous_quarter"]["label"] == "Q1 FY27"
    assert out["previous_quarter"]["total_cr"] == pytest.approx(150.0)
    assert out["previous_quarter"]["value_not_disclosed"] == 1
    assert out["change_pct"] == pytest.approx(100.0)
    assert out["comparable"] is True


def test_a_quarter_the_service_did_not_watch_is_not_compared(ledger):
    """
    Recording that started mid-quarter would otherwise report a jump in order
    inflow that is really the ledger filling up. Only the second quarter was
    watched here, so the two are not comparable and no percentage is offered.
    """
    _cover(ledger, dt.date(2026, 7, 1), dt.date(2026, 9, 15))
    ledger.record([_order("2026-05-20", 100.0), _order("2026-08-05", 300.0)])
    out = ledger.quarter_comparison(today=dt.date(2026, 9, 15))
    assert out["previous_quarter"]["partial"] is True
    assert out["this_quarter"]["partial"] is False
    assert out["comparable"] is False
    assert out["change_pct"] is None
    assert "not yet comparable" in out["caveat"]


def test_a_quiet_quarter_is_not_mistaken_for_an_unwatched_one(ledger):
    """
    The distinction the coverage table exists for. Both quarters were watched;
    the earlier one simply had no orders in it. That is a real zero and the
    comparison must stand rather than refusing.
    """
    _cover(ledger, dt.date(2026, 4, 1), dt.date(2026, 9, 15))
    ledger.record([_order("2026-08-05", 300.0)])
    out = ledger.quarter_comparison(today=dt.date(2026, 9, 15))
    assert out["previous_quarter"]["orders"] == 0
    assert out["previous_quarter"]["partial"] is False
    assert out["comparable"] is True
    # No percentage change from a base of zero, but the quarters are comparable
    # and the rupee difference is real.
    assert out["change_cr"] == pytest.approx(300.0)


def test_a_few_missing_days_do_not_void_a_quarter(ledger):
    """Exchange holidays are not gaps in the record."""
    _cover(ledger, dt.date(2026, 4, 1), dt.date(2026, 9, 15))
    out = ledger.quarter_comparison(today=dt.date(2026, 9, 15))
    assert out["previous_quarter"]["days_not_recorded"] == 0
    assert out["previous_quarter"]["partial"] is False


def test_the_biggest_order_of_a_quarter_is_named(ledger):
    _cover(ledger, dt.date(2026, 7, 1), dt.date(2026, 9, 15))
    ledger.record([_order("2026-08-05", 300.0), _order("2026-08-09", 900.0, symbol="BIG")])
    out = ledger.quarter_comparison(today=dt.date(2026, 9, 15))
    assert out["this_quarter"]["biggest"]["symbol"] == "BIG"
    assert out["this_quarter"]["biggest"]["value_cr"] == pytest.approx(900.0)


def test_an_empty_ledger_answers_rather_than_raising(ledger):
    out = ledger.quarter_comparison(today=dt.date(2026, 9, 15))
    assert out["this_quarter"]["orders"] == 0
    assert out["change_pct"] is None
    assert out["recording_since"] is None


# ---------------------------------------------------------------------------
# The payload the page renders
# ---------------------------------------------------------------------------

def test_orders_without_a_value_are_listed_but_never_ranked_first():
    rows = [
        {"value_cr": None, "pct_of_market_cap": None, "wow": False, "at": "a"},
        {"value_cr": 10.0, "pct_of_market_cap": 4.0, "wow": False, "at": "b"},
        {"value_cr": 90.0, "pct_of_market_cap": 42.0, "wow": True, "at": "c"},
    ]
    rows.sort(key=lambda r: (r["pct_of_market_cap"] is None,
                             -(r["pct_of_market_cap"] or 0),
                             -(r["value_cr"] or 0), r["at"] or ""))
    assert [r["pct_of_market_cap"] for r in rows] == [42.0, 4.0, None]


def test_the_payload_states_the_threshold_it_judged_on():
    out = W._payload([], "")
    assert out["threshold_pct"] == W.WOW_MIN_PCT
    assert "%g" % W.WOW_MIN_PCT in out["explain"] or str(W.WOW_MIN_PCT) in out["explain"]
    assert "never given an assumed figure" in out["explain"]


def test_the_payload_counts_disclosure_separately_from_size():
    rows = [
        {"value_cr": None, "wow": False}, {"value_cr": 5.0, "wow": False},
        {"value_cr": 900.0, "wow": True},
    ]
    c = W._payload(rows, "")["counts"]
    assert c == {"orders": 3, "with_value": 2, "value_not_disclosed": 1, "wow": 1}
