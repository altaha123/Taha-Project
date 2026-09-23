"""
The balance sheet, the cash flow and the full year, from real filings.

Every March and September results filing carries three statements, not one:
the quarter's P&L, the balance sheet at the reporting date, and the cash flow
for the year to date. Reading them means choosing contexts correctly, and
eight years of real NSE filings get their contexts wrong in four different
ways. Each fixture below is one of those, exactly as NSE serves it, and each
failure is silent — a missing year, or a quarter wearing a year's name.

Figures are checkable against TCS's and HDFC Bank's published results.
"""
import os

import pytest

import xbrl

HERE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def load(name):
    with open(os.path.join(HERE, name), encoding="utf-8") as fh:
        return xbrl.normalise(xbrl.parse(fh.read()))


def cr(v):
    return None if v is None else round(v / 1e7)


def test_a_march_filing_carries_all_three_statements():
    d = load("tcs_q4fy26.xml")
    assert cr(d["revenue"]) == 70698                 # the quarter
    y = d["ytd"]
    assert (y["from"], y["months"]) == ("2025-04-01", 12)
    assert cr(y["revenue"]) == 267021                # the year
    assert cr(y["pat"]) == 49454
    assert cr(y["cfo"]) == 52094
    assert cr(y["capex_ppe"]) == 3670                # payments filed positive
    b = d["balance_sheet"]
    assert cr(b["total_assets"]) == 182372
    assert cr(b["total_equity"]) == 108478


def test_undefined_contexts_are_rebuilt_from_the_periods_they_state():
    """TCS's FY20 filing references OneD, FourD and OneI and defines none of
    them. Every figure in it used to be discarded."""
    d = load("tcs_q4fy20.xml")
    assert d["period"]["from"] == "2020-01-01"
    assert cr(d["revenue"]) == 39946
    assert cr(d["ytd"]["revenue"]) == 156949


def test_a_context_defined_with_the_wrong_dates_is_corrected_by_its_own_facts():
    """TCS's FY24 filing defines FourD as January to March; the facts inside
    it say April to March. Believing the definition made the year a second
    copy of the quarter."""
    d = load("tcs_q4fy24.xml")
    assert cr(d["revenue"]) == 61237
    assert d["ytd"]["months"] == 12
    assert cr(d["ytd"]["revenue"]) == 240893
    assert cr(d["ytd"]["cfo"]) == 44338


def test_a_cash_flow_filed_against_the_quarter_is_the_year_to_date():
    """No quarterly cash flow is ever required, so one tagged OneD is the
    year's — TCS's FY21 operating cash flow was ₹38,802 crore."""
    d = load("tcs_q4fy21.xml")
    assert cr(d["ytd"]["cfo"]) == 38802
    assert cr(d["revenue"]) < cr(d["ytd"]["revenue"])


def test_a_filing_that_states_only_period_ends_is_read_by_convention():
    """HDFC Bank's FY21 filing gives no start date anywhere: One is the
    quarter and Four the year from the stated start of the financial year."""
    d = load("hdfcbank_q4fy21.xml")
    assert d["period"]["from"] == "2021-01-01"
    assert cr(d["revenue"]) == 32607                 # interest earned, the quarter
    assert (d["ytd"]["from"], d["ytd"]["months"]) == ("2020-04-01", 12)
    assert cr(d["ytd"]["pat"]) == 31857


def test_a_bank_reads_through_the_banking_format():
    d = load("hdfcbank_q4fy26.xml")
    assert cr(d["revenue"]) == 87182                 # InterestEarned
    assert cr(d["finance_cost"]) == 45220            # InterestExpended
    assert cr(d["provisions"]) == 3440
    assert cr(d["pat"]) == 20351
    b = d["balance_sheet"]
    assert cr(b["deposits"]) == 3099638
    assert cr(b["loans"]) == 3050783                 # Advances
    assert "total_equity" not in b                   # a bank files Capital + Reserves


def test_a_cached_parse_from_before_the_schema_is_read_again(tmp_path, monkeypatch):
    import json
    monkeypatch.setattr(xbrl, "CACHE_DIR", str(tmp_path))
    url = "https://example/old.xml"
    with open(xbrl._cache_path(url), "w") as fh:
        json.dump({"revenue": 1, "period": {"to": "2020-03-31"}}, fh)   # schema 4
    calls = []
    monkeypatch.setattr(xbrl.nse_http, "get",
                        lambda u, referer=None: calls.append(u) or None)
    xbrl.fetch(url)
    assert calls == [url]
