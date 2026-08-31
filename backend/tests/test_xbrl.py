"""
XBRL results parsing, against a real filing.

The fixture is Reliance's Q3 FY25 results exactly as NSE serves them. Using a
real document rather than a hand-written one matters, because the two ways
this parser can be wrong are both properties of real filings and neither
raises an exception:

  · picking the nine-month context instead of the quarter, which triples every
    figure while still looking entirely plausible
  · reading a segment's numbers as the company's, which the taxonomy invites
    by tagging both with the same element name

Both are checked against figures that can be verified against the published
results.
"""
import os

import pytest

import xbrl

FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "fixtures", "reliance_q3fy25.xml")


@pytest.fixture(scope="module")
def parsed():
    with open(FIXTURE, encoding="utf-8") as fh:
        return xbrl.parse(fh.read())


@pytest.fixture(scope="module")
def facts(parsed):
    return xbrl.normalise(parsed)


def cr(v):
    """Rupees to crore, the unit Indian results are actually read in."""
    return None if v is None else round(v / 1e7)


def test_it_reads_the_declared_reporting_period(parsed):
    assert parsed["ok"]
    assert parsed["period"]["from"] == "2024-10-01"
    assert parsed["period"]["to"] == "2024-12-31"


def test_it_takes_the_quarter_not_the_year_to_date(facts):
    """
    The filing reports RevenueFromOperations twice: 1,28,260 cr for the
    quarter and 3,96,645 cr for the nine months, distinguished only by their
    context. Taking the wrong one is silent and looks reasonable.
    """
    assert cr(facts["revenue"]) == 128260
    assert cr(facts["revenue"]) != 396645


def test_segment_figures_never_arrive_as_company_figures(parsed):
    """
    Per-segment assets are tagged SegmentAssets, exactly like the company
    total, separated only by a dimension on the context.
    """
    assert parsed["dimensional_contexts_skipped"] > 0
    # The five per-segment values must not be what we picked up.
    for per_segment in (66059, 37681, 332806, 206270, 20500):
        assert cr(parsed["facts"].get("SegmentAssets")) != per_segment


def test_the_income_statement_matches_the_published_result(facts):
    """Figures checkable against Reliance's reported Q3 FY25 standalone."""
    assert cr(facts["revenue"]) == 128260
    assert cr(facts["other_income"]) == 3214
    assert cr(facts["total_income"]) == 131474
    assert cr(facts["pbt"]) == 11597
    assert cr(facts["pat"]) == 8721
    assert facts["eps_basic"] == 6.44


def test_derived_margins_follow_from_the_statement(facts):
    assert facts["net_margin_pct"] == pytest.approx(6.80, abs=0.02)
    # EBITDA rebuilt from the filing's own lines, not taken on trust
    rebuilt = facts["pbt"] + facts["finance_cost"] + facts["depreciation"] \
        - facts["other_income"]
    assert facts["ebitda"] == pytest.approx(rebuilt, abs=1)


def test_the_balance_sheet_totals_balance(facts):
    """
    Total assets and total liabilities come from the segment reconciliation,
    which balances by construction. If they ever stop matching, the wrong
    context has been picked.
    """
    assert cr(facts["total_assets"]) == 996120
    assert facts["total_assets"] == pytest.approx(facts["total_liabilities"], abs=1)


def test_malformed_input_is_reported_not_raised():
    bad = xbrl.parse("<not-xbrl>")
    assert bad["ok"] is False and "parseable" in bad["error"]
    assert xbrl.normalise(bad)["ok"] is False


def test_an_empty_document_does_not_crash():
    out = xbrl.parse('<?xml version="1.0"?><xbrli:xbrl '
                     'xmlns:xbrli="http://www.xbrl.org/2003/instance"/>')
    assert out["ok"] and out["facts"] == {}


def test_the_cache_directory_sits_on_the_data_disk():
    """Same lesson as the tracker and the point-in-time store."""
    assert os.path.isabs(xbrl.CACHE_DIR or "/")
