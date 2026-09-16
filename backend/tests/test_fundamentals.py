"""
The quarterly P&L: one basis, and no percentage that crosses zero.

Two bugs are worth a test file of their own here, because neither of them
crashes and both of them produce a plausible-looking number:

  · MIXING BASES. Almost every Indian company files its results twice, once
    standalone and once consolidated, and `xbrl.statements()` keys rows by
    period end. For Reliance the two differ by more than a factor of two, so a
    series that alternates reports a 114% swing that is nothing but the
    difference between a parent company and a group.

  · A PERCENTAGE ACROSS ZERO. A company that lost 100 crore and then made 50
    has not grown 150%, and -50 against -100 is not a 50% fall. Printing one
    anyway is how a screener reports a turnaround as a collapse.
"""

import datetime as dt
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import fundamentals  # noqa: E402


# ---------------------------------------------------------------------------
# change()
# ---------------------------------------------------------------------------

def test_growth_is_a_percentage_of_a_positive_base():
    c = fundamentals.change(110.0, 100.0)
    assert c["kind"] == "grew"
    assert c["pct"] == pytest.approx(10.0)
    assert c["abs"] == pytest.approx(10.0)


def test_a_fall_is_negative_not_absolute():
    c = fundamentals.change(90.0, 100.0)
    assert c["kind"] == "shrank"
    assert c["pct"] == pytest.approx(-10.0)


def test_loss_to_profit_carries_no_percentage():
    c = fundamentals.change(50.0, -100.0)
    assert c["kind"] == "loss_to_profit"
    assert c["pct"] is None            # 150% would be nonsense
    assert c["abs"] == pytest.approx(150.0)


def test_profit_to_loss_carries_no_percentage():
    c = fundamentals.change(-50.0, 100.0)
    assert c["kind"] == "profit_to_loss"
    assert c["pct"] is None


def test_a_narrowing_loss_is_not_a_fall():
    """-50 against -100 is an improvement. A naive percentage reads -50%, i.e.
    exactly backwards, which is why there is no percentage here at all."""
    c = fundamentals.change(-50.0, -100.0)
    assert c["kind"] == "loss_narrowed"
    assert c["pct"] is None
    assert c["abs"] == pytest.approx(50.0)


def test_a_widening_loss_says_so():
    c = fundamentals.change(-150.0, -100.0)
    assert c["kind"] == "loss_widened"
    assert c["abs"] == pytest.approx(-50.0)


def test_a_missing_figure_is_unavailable_not_zero():
    for c in (fundamentals.change(None, 100.0), fundamentals.change(100.0, None)):
        assert c["kind"] == "unavailable"
        assert c["pct"] is None
        assert c["abs"] is None


def test_zero_base_with_zero_now_is_flat_with_no_percentage():
    c = fundamentals.change(0.0, 0.0)
    assert c["pct"] is None
    assert c["abs"] == 0


def test_a_percentage_is_never_produced_from_a_non_positive_base():
    """The invariant, stated once over the whole space rather than case by
    case: no base at or below zero ever yields a percentage."""
    for base in (-1000.0, -1.0, 0.0):
        for now in (-500.0, 0.0, 500.0):
            assert fundamentals.change(now, base)["pct"] is None


# ---------------------------------------------------------------------------
# Ratios
# ---------------------------------------------------------------------------

def test_a_ratio_on_a_negative_denominator_is_blank_not_large():
    """An effective tax rate against a loss before tax is not a rate. Left
    blank rather than shown as a number a reader would act on."""
    assert fundamentals._div(100.0, -400.0) is None
    assert fundamentals._div(100.0, 0.0) is None
    assert fundamentals._div(100.0, 400.0) == pytest.approx(25.0)


def test_interest_cover_needs_a_real_interest_bill():
    assert fundamentals._times(1000.0, 0.0) is None
    assert fundamentals._times(1000.0, 100.0) == pytest.approx(10.0)


# ---------------------------------------------------------------------------
# Periods
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("end,label", [
    (dt.date(2026, 6, 30), "Q1 FY27"),
    (dt.date(2026, 9, 30), "Q2 FY27"),
    (dt.date(2025, 12, 31), "Q3 FY26"),
    (dt.date(2026, 3, 31), "Q4 FY26"),
])
def test_indian_fiscal_quarter_labels(end, label):
    assert fundamentals.quarter_label(end) == label


def test_a_year_to_date_filing_is_not_a_quarter():
    """A Reg 33 filing carries several periods. A nine-month cumulative row in
    a quarterly series overstates every line in it."""
    assert fundamentals._is_quarterly({"from": "2025-04-01", "to": "2025-06-30"})
    assert not fundamentals._is_quarterly({"from": "2025-04-01", "to": "2025-12-31"})
    assert not fundamentals._is_quarterly({"from": "2025-04-01", "to": "2026-03-31"})


# ---------------------------------------------------------------------------
# Basis selection
# ---------------------------------------------------------------------------

def test_consolidated_is_preferred_where_both_are_filed():
    rows = [{"consolidated": True}, {"consolidated": False}]
    con, label, _why = fundamentals._pick_basis(rows)
    assert (con, label) == (True, "consolidated")


def test_a_standalone_only_filer_gets_standalone_and_is_told_why():
    con, label, why = fundamentals._pick_basis([{"consolidated": False}])
    assert (con, label) == (False, "standalone")
    assert "standalone" in why


def test_an_explicit_request_wins_where_that_basis_exists():
    rows = [{"consolidated": True}, {"consolidated": False}]
    assert fundamentals._pick_basis(rows, want="standalone")[0] is False


def test_an_explicit_request_for_a_basis_not_filed_falls_back():
    assert fundamentals._pick_basis([{"consolidated": True}],
                                    want="standalone")[0] is True


# ---------------------------------------------------------------------------
# series(), against a stubbed reader
# ---------------------------------------------------------------------------

def _quarter(end, start, con, revenue, pat, **extra):
    row = {
        "to": end, "from": start, "consolidated": con,
        "filed_at": "2026-07-20", "source_url": "https://example.test/%s-%s" % (end, con),
        "revenue": revenue, "other_income": revenue * 0.02,
        "total_income": revenue * 1.02, "materials": revenue * 0.4,
        "employee_cost": revenue * 0.03, "finance_cost": revenue * 0.02,
        "depreciation": revenue * 0.05, "other_expenses": revenue * 0.16,
        "total_expenses": revenue * 0.9, "ebitda": revenue * 0.17,
        "pbt": pat / 0.75 if pat > 0 else pat, "tax": pat / 3 if pat > 0 else 0.0,
        "pat": pat, "eps_basic": 10.0,
    }
    row.update(extra)
    return row


ENDS = ["2026-06-30", "2026-03-31", "2025-12-31", "2025-09-30",
        "2025-06-30", "2025-03-31"]
STARTS = ["2026-04-01", "2026-01-01", "2025-10-01", "2025-07-01",
          "2025-04-01", "2025-01-01"]


def _stub_xbrl(monkeypatch, quarters, index=None):
    """A reader that hands back exactly what it is given, and — as the real one
    does — falls back to the other basis when the requested one is absent."""
    mod = types.ModuleType("xbrl")
    mod.available = lambda: True
    mod.filings = lambda sym: (index if index is not None else quarters)

    def statements(sym, limit=8, consolidated=None):
        want = [r for r in quarters if consolidated is None
                or r.get("consolidated") is consolidated]
        return (want or quarters)[:limit]

    mod.statements = statements
    monkeypatch.setitem(sys.modules, "xbrl", mod)
    return mod


def test_a_company_filing_both_bases_never_mixes_them(monkeypatch):
    """The bug this module exists for. Consolidated revenue is twice
    standalone; a series that takes whichever row happened to land last reports
    the difference between a parent and a group as growth."""
    quarters = []
    for end, start in zip(ENDS, STARTS):
        quarters.append(_quarter(end, start, True, 2_60_000e7, 20_000e7))
        quarters.append(_quarter(end, start, False, 1_20_000e7, 9_000e7))
    _stub_xbrl(monkeypatch, quarters)

    d = fundamentals.series("RELIANCE", quarters=6)
    assert d["available"] is True
    assert d["basis"] == "consolidated"
    assert d["count"] == 6
    revenues = [r["values"]["revenue"] for r in d["rows"]]
    assert len(set(revenues)) == 1, "a mixed basis would show two distinct levels"
    assert all(v == pytest.approx(2_60_000e7) for v in revenues)
    # And every change is therefore honest: no quarter moved.
    assert all(abs(r["yoy"]["revenue"]["pct"]) < 0.01
               for r in d["rows"] if r.get("yoy"))


def test_the_other_basis_is_named_as_available(monkeypatch):
    quarters = []
    for end, start in zip(ENDS, STARTS):
        quarters.append(_quarter(end, start, True, 2_60_000e7, 20_000e7))
        quarters.append(_quarter(end, start, False, 1_20_000e7, 9_000e7))
    _stub_xbrl(monkeypatch, quarters)
    d = fundamentals.series("RELIANCE", quarters=6)
    assert d["basis_alternatives"] == ["consolidated", "standalone"]


def test_alternatives_come_from_the_index_not_the_filtered_set(monkeypatch):
    """Read back from the rows actually used, this would always claim the
    company files only the basis on screen."""
    quarters = [_quarter(e, s, True, 100e7, 10e7) for e, s in zip(ENDS, STARTS)]
    index = quarters + [_quarter(ENDS[0], STARTS[0], False, 50e7, 5e7)]
    _stub_xbrl(monkeypatch, quarters, index=index)
    d = fundamentals.series("X", quarters=4)
    assert d["basis_alternatives"] == ["consolidated", "standalone"]


def test_a_standalone_only_company_is_served_standalone(monkeypatch):
    quarters = [_quarter(e, s, False, 100e7, 10e7) for e, s in zip(ENDS, STARTS)]
    _stub_xbrl(monkeypatch, quarters)
    d = fundamentals.series("SMALLCO", quarters=6)
    assert d["basis"] == "standalone"
    assert d["basis_alternatives"] == ["standalone"]


def test_year_on_year_pairs_the_same_quarter_twelve_months_back(monkeypatch):
    quarters = [_quarter(e, s, True, 100e7, 10e7) for e, s in zip(ENDS, STARTS)]
    _stub_xbrl(monkeypatch, quarters)
    d = fundamentals.series("X", quarters=6)
    latest = d["rows"][0]
    assert latest["label"] == "Q1 FY27"
    assert latest["yoy_against"] == "Q1 FY26"      # not Q4, not Q2
    assert latest["qoq_against"] == "Q4 FY26"
    # The oldest quarter has nothing a year before it, and says nothing rather
    # than comparing itself with the quarter beside it.
    assert d["rows"][-1]["yoy"] == {}


def test_a_cumulative_filing_is_kept_out_of_the_series(monkeypatch):
    quarters = [_quarter(e, s, True, 100e7, 10e7) for e, s in zip(ENDS, STARTS)]
    quarters.append(_quarter("2026-03-31", "2025-04-01", True, 400e7, 40e7))
    _stub_xbrl(monkeypatch, quarters)
    d = fundamentals.series("X", quarters=6)
    assert all(r["values"]["revenue"] == pytest.approx(100e7) for r in d["rows"])


def test_a_revised_filing_replaces_the_quarter_rather_than_duplicating_it(monkeypatch):
    quarters = [_quarter(e, s, True, 100e7, 10e7) for e, s in zip(ENDS, STARTS)]
    revised = _quarter(ENDS[0], STARTS[0], True, 111e7, 11e7)
    revised["filed_at"] = "2026-09-01"
    quarters.insert(0, revised)
    _stub_xbrl(monkeypatch, quarters)
    d = fundamentals.series("X", quarters=6)
    ends = [r["period_end"] for r in d["rows"]]
    assert len(ends) == len(set(ends))
    assert d["rows"][0]["values"]["revenue"] == pytest.approx(111e7)


def test_a_short_history_says_it_is_short_instead_of_padding(monkeypatch):
    quarters = [_quarter(e, s, True, 100e7, 10e7)
                for e, s in zip(ENDS[:3], STARTS[:3])]
    _stub_xbrl(monkeypatch, quarters)
    d = fundamentals.series("X", quarters=6)
    assert d["count"] == 3
    assert d["partial"] is True
    assert d["requested"] == 6
    assert any("3 of the 6" in n for n in d["notes"])


def test_a_turnaround_reaches_the_payload_as_words_not_a_number(monkeypatch):
    """End to end: a loss a year ago and a profit now must not produce a
    percentage anywhere in the payload the page renders."""
    quarters = []
    for i, (end, start) in enumerate(zip(ENDS, STARTS)):
        pat = 10e7 if i < 4 else -20e7
        quarters.append(_quarter(end, start, True, 100e7, pat))
    _stub_xbrl(monkeypatch, quarters)
    d = fundamentals.series("X", quarters=6)
    yoy = d["rows"][0]["yoy"]["pat"]
    assert yoy["kind"] == "loss_to_profit"
    assert yoy["pct"] is None
    assert yoy["abs"] == pytest.approx(30e7)


def test_no_symbol_is_answered_not_raised():
    d = fundamentals.series("")
    assert d["available"] is False and d["message"]


def test_an_empty_index_is_answered_not_raised(monkeypatch):
    _stub_xbrl(monkeypatch, [], index=[])
    d = fundamentals.series("NOSUCH", quarters=6)
    assert d["available"] is False
    assert "NOSUCH" in d["message"]


def test_a_reader_that_raises_does_not_take_the_endpoint_with_it(monkeypatch):
    mod = types.ModuleType("xbrl")
    mod.available = lambda: True
    mod.filings = lambda sym: (_ for _ in ()).throw(RuntimeError("NSE said no"))
    monkeypatch.setitem(sys.modules, "xbrl", mod)
    d = fundamentals.series("X", quarters=6)
    assert d["available"] is False
    assert "NSE said no" in d["message"]


def test_every_row_carries_a_label_a_source_and_the_ratio_keys(monkeypatch):
    """What the page indexes into. A missing key here is a blank column, not
    an error, which is exactly the kind of failure this project keeps
    shipping."""
    quarters = [_quarter(e, s, True, 100e7, 10e7) for e, s in zip(ENDS, STARTS)]
    _stub_xbrl(monkeypatch, quarters)
    d = fundamentals.series("X", quarters=6)
    line_keys = {l["key"] for l in d["lines"]}
    ratio_keys = {r["key"] for r in d["ratio_defs"]}
    assert line_keys and ratio_keys
    for row in d["rows"]:
        assert row["label"] and row["source"]
        assert line_keys <= set(row["values"])
        assert ratio_keys <= set(row["ratios"])
    for r in d["ratio_defs"]:
        assert r["label"] and r["formula"]


def test_quarters_asked_for_is_clamped(monkeypatch):
    quarters = [_quarter(e, s, True, 100e7, 10e7) for e, s in zip(ENDS, STARTS)]
    _stub_xbrl(monkeypatch, quarters)
    assert fundamentals.series("X", quarters=900)["requested"] == 16
    assert fundamentals.series("X", quarters=1)["requested"] == 2
    # 0 and None both mean "unspecified", so they get the default, not two.
    assert fundamentals.series("X", quarters=0)["requested"] == 8
