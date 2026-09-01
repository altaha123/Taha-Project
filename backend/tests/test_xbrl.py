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


# ---------------------------------------------------------------------------
# Freshness
#
# Discovered the hard way: this module reported the December 2024 quarter as
# current twenty months later, in silence. The parser was right — NSE's
# results index is itself frozen. Queried for the WHOLE equities universe it
# returns 3,816 rows whose newest period end is 31-Dec-2024, and no symbol,
# period or date-range parameter produces anything newer.
#
# Nothing in this codebase can fix that. These tests protect the part that was
# ours: that it can never be silent again.
# ---------------------------------------------------------------------------
import datetime as _dt


def _rows(latest_end, filed=None):
    return [{"to": latest_end, "filed_at": filed or "10-Feb-2025"}]


def test_a_current_filing_is_not_flagged():
    f = xbrl.freshness(_rows("31-Dec-2025"), today=_dt.date(2026, 2, 20))
    assert f["stale"] is False
    assert f["age_days"] == 51
    assert "current" in f["note"]


def test_the_frozen_source_is_flagged_with_its_age():
    f = xbrl.freshness(_rows("31-Dec-2024"), today=_dt.date(2026, 9, 1))
    assert f["stale"] is True
    assert f["age_days"] > 600
    assert "31-Dec-2024" in f["note"]
    # It must say the problem is the source, not this one company — otherwise
    # the reader concludes the company stopped filing.
    assert "not just this one" in f["note"]


def test_a_normal_reporting_lag_is_not_staleness():
    """There is always a gap between a period ending and the next filing. A
    threshold inside that gap would flag every company for part of every
    quarter and the warning would be ignored within a week."""
    assert xbrl.STALE_AFTER_DAYS >= 135
    f = xbrl.freshness(_rows("31-Mar-2026"), today=_dt.date(2026, 6, 30))
    assert f["stale"] is False


def test_freshness_always_returns_a_verdict():
    for rows in ([], [{}], [{"to": "not-a-date"}]):
        f = xbrl.freshness(rows)
        assert "stale" in f and "note" in f
        assert f["stale"] is False          # unknown is not the same as stale


def test_the_bse_cross_check_never_breaks_the_payload(monkeypatch):
    """
    BSE's announcement feed is live where NSE's XBRL index is not, so the gap
    between them dates the staleness. It is a footnote, not a dependency —
    a failure there must not cost the caller its filings.
    """
    monkeypatch.setattr(xbrl, "latest_bse_result",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")))
    try:
        f = xbrl.freshness(_rows("31-Dec-2024"), symbol="RELIANCE",
                           today=_dt.date(2026, 9, 1))
    except Exception as e:                              # pragma: no cover
        raise AssertionError(f"a BSE failure broke freshness(): {e}")
    assert f["stale"] is True


def test_the_cross_check_dates_the_gap_when_bse_answers(monkeypatch):
    monkeypatch.setattr(xbrl, "latest_bse_result", lambda *a, **k: "2026-08-14")
    f = xbrl.freshness(_rows("31-Dec-2024"), symbol="RELIANCE",
                       today=_dt.date(2026, 9, 1))
    assert f["bse_last_result_seen"] == "2026-08-14"
    assert "2026-08-14" in f["note"]


# ---------------------------------------------------------------------------
# Two filing regimes
#
# SEBI's Integrated Filing replaced the standalone results filing from the
# quarter ending December 2024. Companies stopped filing under the old
# mechanism at exactly that point — which is why the legacy endpoint appeared
# "frozen at 31-Dec-2024" for every symbol in the universe. It was not stale,
# it was finished, and reading only it made this module report a twenty-month-
# old quarter as current.
#
# The legacy endpoint is still needed: the year-earlier comparatives for the
# first integrated quarters live there and nowhere else.
# ---------------------------------------------------------------------------

INTEGRATED = [
    {"type": "Integrated Filing- Financials/Original", "qe_Date": "30-JUN-2026",
     "broadcast_Date": "17-Jul-2026 19:50:03", "consolidated": "Consolidated",
     "audited": "Un-Audited", "cmName": "Acme Ltd",
     "xbrl": "https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1.xml"},
    {"type": "Integrated Filing- Financials/Original", "qe_Date": "30-JUN-2026",
     "broadcast_Date": "17-Jul-2026 19:49:04", "consolidated": "Standalone",
     "audited": "Un-Audited", "cmName": "Acme Ltd",
     "xbrl": "https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_2.xml"},
    # Governance filings ride the same feed and carry no income statement.
    {"type": "Integrated Filing- Governance/New", "qe_Date": "30-JUN-2026",
     "broadcast_Date": "28-Jul-2026 18:43:22", "consolidated": None,
     "cmName": "Acme Ltd",
     "xbrl": "https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_GOVERNANCE_9.xml"},
    # No XBRL document: nothing to parse, so nothing to offer.
    {"type": "Integrated Filing- Financials/Original", "qe_Date": "31-MAR-2026",
     "broadcast_Date": "24-Apr-2026 22:57:12", "consolidated": "Consolidated",
     "cmName": "Acme Ltd", "xbrl": ""},
]

LEGACY = [
    {"symbol": "ACME", "companyName": "Acme Ltd", "fromDate": "01-Oct-2024",
     "toDate": "31-Dec-2024", "period": "Quarterly", "relatingTo": "Third Quarter",
     "financialYear": "01-Apr-2024 To 31-Mar-2025", "consolidated": "Consolidated",
     "filingDate": "16-Jan-2025 20:15",
     "xbrl": "https://nsearchives.nseindia.com/corporate/xbrl/OLD_1.xml"},
    # Also present in the integrated feed — the newer regime must win.
    {"symbol": "ACME", "companyName": "Acme Ltd", "fromDate": "01-Apr-2026",
     "toDate": "30-Jun-2026", "period": "Quarterly", "relatingTo": "First Quarter",
     "consolidated": "Consolidated", "filingDate": "01-Jan-1990",
     "xbrl": "https://nsearchives.nseindia.com/corporate/xbrl/DUPLICATE.xml"},
]


@pytest.fixture
def two_regimes(monkeypatch):
    def fake_api(url, params):
        return INTEGRATED if "integrated" in url else LEGACY
    monkeypatch.setattr(xbrl, "_api", fake_api)


def test_recent_filings_come_from_the_integrated_regime(two_regimes):
    rows = xbrl.filings("ACME")
    assert rows[0]["to"] == "30-JUN-2026"
    assert rows[0]["regime"] == "integrated"
    assert rows[0]["filed_at"].startswith("17-Jul-2026")


def test_governance_filings_are_excluded(two_regimes):
    """They ride the same feed and have no income statement in them."""
    assert all("GOVERNANCE" not in r["xbrl"] for r in xbrl.filings("ACME"))


def test_a_filing_with_no_xbrl_document_is_skipped(two_regimes):
    assert all(r["xbrl"].lower().endswith(".xml") for r in xbrl.filings("ACME"))
    assert not any(r["to"] == "31-MAR-2026" for r in xbrl.filings("ACME"))


def test_history_still_reaches_back_through_the_legacy_regime(two_regimes):
    """
    The comparatives for the first integrated quarters exist only in the old
    feed. Dropping it would silently remove every year-on-year growth figure
    for the newest quarters.
    """
    rows = xbrl.filings("ACME")
    assert any(r["regime"] == "legacy" and r["to"] == "31-Dec-2024" for r in rows)


def test_the_newer_regime_wins_where_the_two_overlap(two_regimes):
    """A quarter present in both must appear once, from the integrated feed."""
    rows = [r for r in xbrl.filings("ACME")
            if xbrl._dparse(r["to"]) == _dt.date(2026, 6, 30) and r["consolidated"]]
    assert len(rows) == 1
    assert rows[0]["regime"] == "integrated"
    assert "DUPLICATE" not in rows[0]["xbrl"]


def test_standalone_and_consolidated_both_survive(two_regimes):
    june = [r for r in xbrl.filings("ACME")
            if xbrl._dparse(r["to"]) == _dt.date(2026, 6, 30)]
    assert sorted(r["consolidated"] for r in june) == [False, True]


def test_the_quarter_label_is_derived_when_the_feed_omits_it():
    """
    The integrated feed labels a filing by quarter-end date alone. Growth is
    matched on the quarter label, so without deriving one every integrated
    filing would fail to find its year-earlier comparative.
    """
    assert xbrl._quarter_of("30-JUN-2026") == "First Quarter"
    assert xbrl._quarter_of("30-SEP-2025") == "Second Quarter"
    assert xbrl._quarter_of("31-DEC-2025") == "Third Quarter"
    assert xbrl._quarter_of("31-MAR-2026") == "Fourth Quarter"
    assert xbrl._quarter_of("nonsense") is None


def test_a_dead_endpoint_does_not_take_the_other_one_down(monkeypatch):
    """One regime failing must degrade the history, not empty it."""
    def half_dead(url, params):
        if "integrated" in url:
            raise RuntimeError("down")
        return LEGACY
    monkeypatch.setattr(xbrl, "_api", half_dead)
    try:
        rows = xbrl.filings("ACME")
    except Exception as e:                                  # pragma: no cover
        raise AssertionError(f"a dead integrated feed broke filings(): {e}")
    assert rows and all(r["regime"] == "legacy" for r in rows)
