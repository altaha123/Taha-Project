"""
Shareholding pattern parsing, against two real filings.

WHY TWO
The same company's filings from 2021 and 2026 are not the same document. SEBI
changed the format in between, and the two ways this parser can be silently
wrong are both consequences of that:

  · SCALE. The later format files a percentage as a fraction (0.5048) and the
    earlier one as a percent (50.61). Reading one as the other is a hundredfold
    error on every figure, and nothing raises.
  · THE MISSING SPLIT. The earlier format has a single Institutions line. The
    domestic/foreign split that the whole feature is about does not exist in it,
    so it is derived — and a derived figure that is not labelled as one is a
    number this product has no right to show.

A third trap is not a format change but a reading error, and it is the one that
would embarrass this page most: in the exchange's own layout `Public` is the
PARENT of the foreign, domestic and non-institutional lines. Charting the four
together double-counts about half the company. There is a test for that below
and it is the most important one in this file.

The fixtures are Reliance's own filings, cut down to the category contexts and
a sample of named holders. Everything kept is byte-for-byte what was filed.
"""
import os

import pytest

import shareholding_filings as sf

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
NEW = os.path.join(FIX, "shp_reliance_2026q1.xml")   # 2025-10-31 taxonomy
OLD = os.path.join(FIX, "shp_reliance_2021q2.xml")   # 2020-09-30 taxonomy


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


@pytest.fixture(scope="module")
def new():
    return sf.parse(_read(NEW))


@pytest.fixture(scope="module")
def old():
    return sf.parse(_read(OLD))


def pct(parsed, key):
    return parsed["categories"][key]["pct"]


# ---------------------------------------------------------------------------
# The figures themselves, against the published filing
# ---------------------------------------------------------------------------

def test_new_format_categories_match_the_filing(new):
    assert new["period_end"] == "2026-06-30"
    assert pct(new, "promoter") == pytest.approx(50.48, abs=0.01)
    assert pct(new, "fii") == pytest.approx(17.20, abs=0.01)
    assert pct(new, "dii") == pytest.approx(21.19, abs=0.01)
    assert pct(new, "public_non_institutional") == pytest.approx(11.04, abs=0.01)


def test_old_format_categories_match_the_filing(old):
    assert old["period_end"] == "2021-09-30"
    assert pct(old, "promoter") == pytest.approx(50.61, abs=0.01)
    assert pct(old, "public_non_institutional") == pytest.approx(10.60, abs=0.01)


def test_holder_counts_are_read_not_inferred(new):
    assert new["categories"]["promoter"]["holders"] == 47
    assert new["categories"]["total"]["holders"] == 4651863


# ---------------------------------------------------------------------------
# Scale — the hundredfold error
# ---------------------------------------------------------------------------

def test_scale_is_detected_per_document_not_assumed(new, old):
    """The two filings express the same quantity differently. Both must land
    on a human percentage, and the detection must be per document."""
    assert new["filed_as_percent"] is False      # filed 0.5048
    assert old["filed_as_percent"] is True       # filed 50.61
    for parsed in (new, old):
        assert 99.0 <= pct(parsed, "total") <= 101.0


def test_no_category_is_ever_a_fraction(new, old):
    for parsed in (new, old):
        for key, cat in parsed["categories"].items():
            if cat["pct"] is not None and cat["pct"] > 0:
                assert cat["pct"] >= 0.001, (key, cat["pct"])
                assert cat["pct"] <= 100.5, (key, cat["pct"])


# ---------------------------------------------------------------------------
# The overlap. The most important test here.
# ---------------------------------------------------------------------------

def test_public_total_is_the_parent_of_fii_dii_and_non_institutional(new):
    """
    If this ever passes by accident it means the categories have been flattened
    and the page is double-counting. Public is Table III; foreign, domestic and
    non-institutional holders are all inside it.
    """
    parts = (pct(new, "fii") + pct(new, "dii")
             + pct(new, "public_non_institutional") + pct(new, "government"))
    assert parts == pytest.approx(pct(new, "public_total"), abs=0.05)
    # and therefore the public total is NOT another slice alongside them
    assert pct(new, "promoter") + pct(new, "public_total") == pytest.approx(100.0, abs=0.05)


def test_the_split_the_ui_draws_sums_to_one_hundred(new, old):
    for parsed in (new, old):
        total = sum(parsed["categories"][k]["pct"]
                    for k in sf.SPLIT_KEYS
                    if k in parsed["categories"]
                    and parsed["categories"][k]["pct"] is not None)
        assert total == pytest.approx(100.0, abs=0.15)


def test_public_total_is_not_in_the_split_keys():
    """A guard on the constant itself, so a later edit cannot quietly add it."""
    assert "public_total" not in sf.SPLIT_KEYS
    assert "total" not in sf.SPLIT_KEYS
    assert "institutions_total" not in sf.SPLIT_KEYS


# ---------------------------------------------------------------------------
# The derived domestic figure
# ---------------------------------------------------------------------------

def test_old_format_domestic_institutions_are_derived_and_say_so(old):
    dii = old["categories"]["dii"]
    assert dii["derived"] is True
    assert dii["pct"] == pytest.approx(13.22, abs=0.01)
    # institutions minus foreign — the document's own arithmetic
    assert (old["categories"]["institutions_total"]["pct"]
            - old["categories"]["fii"]["pct"]) == pytest.approx(dii["pct"], abs=0.01)


def test_new_format_domestic_institutions_are_filed_not_derived(new):
    assert new["categories"]["dii"]["derived"] is False
    assert "institutions_total" not in new["categories"]


# ---------------------------------------------------------------------------
# Named holders
# ---------------------------------------------------------------------------

def test_promoters_and_public_holders_are_told_apart(new):
    promoters = [n for n in new["names"] if n["promoter"]]
    public = [n for n in new["names"] if not n["promoter"]]
    assert promoters and public
    assert any("Srichakra" in n["name"] for n in promoters)
    assert any("Life Insurance" in n["name"] for n in public)
    # a promoter entity must never appear in the public list
    assert not any("Srichakra" in n["name"] for n in public)


def test_named_holders_carry_a_percentage_from_their_partner_context(new):
    """
    The name and the number live in two different contexts. If the pairing
    breaks, every holder still has a name and no value — which would render as
    a plausible-looking list of zeroes.
    """
    assert new["names"]
    for n in new["names"]:
        assert n["pct"] is not None
    top = new["names"][0]
    assert top["pct"] == pytest.approx(11.12, abs=0.01)


def test_the_older_context_naming_convention_also_pairs(old):
    """2021 pairs `Foo001D` with `Foo001I`, not `D_Foo` with `Foo`."""
    assert old["names"]
    assert any(n["pct"] and n["pct"] > 1 for n in old["names"])


def test_named_holders_are_sorted_by_size(new):
    sizes = [n["pct"] for n in new["names"]]
    assert sizes == sorted(sizes, reverse=True)


# ---------------------------------------------------------------------------
# Numbers that are not numbers
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw", ["", "  ", "-", "NA", "N.A.", "******", None, "abc"])
def test_unparseable_values_are_none_not_zero(raw):
    """A redacted PAN and a genuine zero are different facts. Treating the
    first as 0 puts a false figure on the page."""
    assert sf._fnum(raw) is None


@pytest.mark.parametrize("raw,want", [("0", 0.0), ("50.61", 50.61),
                                      ("1,23,456", 123456.0), ("-2.5", -2.5)])
def test_real_values_parse(raw, want):
    assert sf._fnum(raw) == pytest.approx(want)


def test_a_document_with_no_facts_does_not_explode():
    empty = ('<?xml version="1.0"?><xbrli:xbrl '
             'xmlns:xbrli="http://www.xbrl.org/2003/instance"></xbrli:xbrl>')
    out = sf.parse(empty)
    assert out["categories"] == {}
    assert out["names"] == []


# ---------------------------------------------------------------------------
# Period handling
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw,want", [
    ("30-JUN-2026", "2026-06-30"),
    ("16-JUL-2026 19:24:44", "2026-07-16"),
])
def test_exchange_dates_parse(raw, want):
    assert sf._parse_nse_date(raw).isoformat() == want


@pytest.mark.parametrize("raw", ["", None, "not a date", "2026-06-30"])
def test_unparseable_dates_are_none_rather_than_today(raw):
    assert sf._parse_nse_date(raw) is None


# ---------------------------------------------------------------------------
# summary() — assembled without touching the network
# ---------------------------------------------------------------------------

def _stub_source(monkeypatch, periods):
    """Serve the fixtures as if they were a run of quarters."""
    rows = [{"period": p, "filed": f, "xbrl": "https://nsearchives.nseindia.com/corporate/xbrl/%s" % p,
             "record_id": p, "revised": False} for p, f in periods]
    monkeypatch.setattr(sf, "available", lambda: True)
    monkeypatch.setattr(sf, "index", lambda sym, force=False: rows)

    bodies = {}
    for i, (p, _f) in enumerate(periods):
        parsed = sf.parse(_read(NEW if i % 2 == 0 else NEW))
        # shift one line so a change is measurable
        parsed = dict(parsed)
        cats = {k: dict(v) for k, v in parsed["categories"].items()}
        if cats.get("fii", {}).get("pct") is not None:
            cats["fii"]["pct"] = round(cats["fii"]["pct"] + i * 0.5, 4)
        parsed["categories"] = cats
        parsed["period"], parsed["filed"] = p, _f
        parsed["source"] = "https://nsearchives.nseindia.com/corporate/xbrl/%s" % p
        parsed["revised"] = False
        bodies["https://nsearchives.nseindia.com/corporate/xbrl/%s" % p] = parsed

    monkeypatch.setattr(sf, "filing",
                        lambda url, period="", filed="", revised=False: bodies.get(url))
    return rows


QUARTERS = [("2026-06-30", "2026-07-16"), ("2026-03-31", "2026-04-21"),
            ("2025-12-31", "2026-01-21"), ("2025-09-30", "2025-10-17"),
            ("2025-06-30", "2025-07-21"), ("2025-03-31", "2025-04-21")]


def test_summary_reports_quarter_on_quarter_change(monkeypatch):
    _stub_source(monkeypatch, QUARTERS)
    out = sf.summary("RELIANCE", quarters=6)
    assert out["available"] is True
    fii = [s for s in out["split"] if s["key"] == "fii"][0]
    # the stub moves FII by 0.5pp per quarter back in time
    assert fii["change_qoq"] == pytest.approx(-0.5, abs=0.001)


def test_year_on_year_needs_a_gap_that_is_really_a_year(monkeypatch):
    """Four rows back is only a year if the company filed every quarter. A
    skipped filing must not have a fifteen-month gap labelled 'year'."""
    gappy = [("2026-06-30", "2026-07-16"), ("2026-03-31", "2026-04-21"),
             ("2025-12-31", "2026-01-21"), ("2025-09-30", "2025-10-17"),
             ("2023-06-30", "2023-07-21"), ("2023-03-31", "2023-04-21")]
    _stub_source(monkeypatch, gappy)
    out = sf.summary("RELIANCE", quarters=6)
    for row in out["split"]:
        assert row["change_yoy"] is None

    _stub_source(monkeypatch, QUARTERS)
    ok = sf.summary("RELIANCE", quarters=6)
    assert any(r["change_yoy"] is not None for r in ok["split"])


def test_summary_history_is_oldest_first_and_carries_its_source(monkeypatch):
    _stub_source(monkeypatch, QUARTERS)
    out = sf.summary("RELIANCE", quarters=6)
    periods = [h["period"] for h in out["history"]]
    assert periods == sorted(periods)
    assert all(h["source"] for h in out["history"])
    assert all(h["filed"] for h in out["history"])


def test_summary_keeps_period_and_filing_date_apart(monkeypatch):
    _stub_source(monkeypatch, QUARTERS)
    out = sf.summary("RELIANCE", quarters=6)
    assert out["period"] == "2026-06-30"
    assert out["filed"] == "2026-07-16"
    assert out["period"] != out["filed"]


def test_summary_always_explains_the_public_overlap(monkeypatch):
    _stub_source(monkeypatch, QUARTERS)
    out = sf.summary("RELIANCE", quarters=6)
    assert any("do not overlap" in n for n in out["notes"])


def test_summary_reconciles_and_says_when_it_does_not(monkeypatch):
    _stub_source(monkeypatch, QUARTERS)
    out = sf.summary("RELIANCE", quarters=6)
    assert out["totals"]["reconciles"] is True
    assert out["totals"]["split_sums_to"] == pytest.approx(100.0, abs=0.15)


def test_a_company_with_no_promoter_is_stated_not_omitted(monkeypatch):
    """ITC and HDFC Bank file no promoter line at all. A missing line and a
    zero holding must not look the same to a reader."""
    parsed = sf.parse(_read(NEW))
    cats = {k: dict(v) for k, v in parsed["categories"].items()}
    cats.pop("promoter")
    cats["public_total"] = dict(cats["public_total"], pct=100.0)
    cats["total"] = dict(cats["total"], pct=100.0)
    parsed = dict(parsed, categories=cats, period="2026-06-30",
                  filed="2026-07-16", source="https://nsearchives.nseindia.com/corporate/xbrl/a", revised=False)

    monkeypatch.setattr(sf, "available", lambda: True)
    monkeypatch.setattr(sf, "index", lambda s, force=False: [
        {"period": "2026-06-30", "filed": "2026-07-16", "xbrl": "https://nsearchives.nseindia.com/corporate/xbrl/a",
         "record_id": "1", "revised": False}])
    monkeypatch.setattr(sf, "filing",
                        lambda url, period="", filed="", revised=False: parsed)

    out = sf.summary("ITC", quarters=2)
    promoter = [s for s in out["split"] if s["key"] == "promoter"]
    assert promoter and promoter[0]["pct"] == 0.0
    assert promoter[0]["reported_absent"] is True
    assert any("no promoter holding" in n for n in out["notes"])


# ---------------------------------------------------------------------------
# Degrading rather than lying
# ---------------------------------------------------------------------------

def test_no_symbol_is_reported_not_raised():
    out = sf.summary("")
    assert out["available"] is False
    assert out["message"]


def test_unreachable_source_reports_unavailable(monkeypatch):
    monkeypatch.setattr(sf, "available", lambda: True)
    monkeypatch.setattr(sf, "index", lambda s, force=False: [])
    out = sf.summary("RELIANCE")
    assert out["available"] is False
    assert out["split"] == []
    assert "RELIANCE" in out["message"]


def test_missing_transport_is_reported_not_faked(monkeypatch):
    monkeypatch.setattr(sf, "available", lambda: False)
    out = sf.summary("RELIANCE")
    assert out["available"] is False
    assert "curl_cffi" in out["message"]


def test_a_filing_that_fails_to_parse_is_skipped_not_fatal(monkeypatch):
    monkeypatch.setattr(sf, "available", lambda: True)
    monkeypatch.setattr(sf, "index", lambda s, force=False: [
        {"period": "2026-06-30", "filed": "2026-07-16", "xbrl": "https://nsearchives.nseindia.com/corporate/xbrl/bad",
         "record_id": "1", "revised": False}])
    monkeypatch.setattr(sf, "filing",
                        lambda url, period="", filed="", revised=False: None)
    out = sf.summary("RELIANCE")
    assert out["available"] is False
    assert "could not be read" in out["message"]


# ---------------------------------------------------------------------------
# The index — duplicates, revisions and the order they arrive in
# ---------------------------------------------------------------------------

class _Resp:
    def __init__(self, body):
        self._body = body
        self.status_code = 200

    def json(self):
        return self._body


def test_a_revised_filing_supersedes_the_original_for_that_quarter(monkeypatch):
    """
    A company that refiles a quarter leaves two rows on the exchange for the
    same period. Showing both would put the same quarter on the chart twice,
    and showing the wrong one would show a figure the company has corrected.
    """
    body = [
        {"date": "30-JUN-2026", "submissionDate": "05-AUG-2026",
         "xbrl": "https://nsearchives.nseindia.com/corporate/xbrl/revised", "recordId": "2", "revisedStatus": "true"},
        {"date": "30-JUN-2026", "submissionDate": "16-JUL-2026",
         "xbrl": "https://nsearchives.nseindia.com/corporate/xbrl/original", "recordId": "1", "revisedStatus": "false"},
        {"date": "31-MAR-2026", "submissionDate": "21-APR-2026",
         "xbrl": "https://nsearchives.nseindia.com/corporate/xbrl/march", "recordId": "0", "revisedStatus": "false"},
    ]
    monkeypatch.setattr(sf, "_get", lambda *a, **k: _Resp(body))
    sf._index_cache.pop("TEST", None)
    rows = sf.index("TEST")

    assert [r["period"] for r in rows] == ["2026-06-30", "2026-03-31"]
    assert rows[0]["xbrl"] == "https://nsearchives.nseindia.com/corporate/xbrl/revised"
    assert rows[0]["revised"] is True


def test_index_drops_rows_with_no_document_or_no_period(monkeypatch):
    body = [
        {"date": "30-JUN-2026", "xbrl": "", "recordId": "1"},
        {"date": "", "xbrl": "https://nsearchives.nseindia.com/corporate/xbrl/a", "recordId": "2"},
        {"date": "31-MAR-2026", "xbrl": "https://nsearchives.nseindia.com/corporate/xbrl/b", "recordId": "3"},
        "not a dict",
    ]
    monkeypatch.setattr(sf, "_get", lambda *a, **k: _Resp(body))
    sf._index_cache.pop("TEST2", None)
    rows = sf.index("TEST2")
    assert [r["period"] for r in rows] == ["2026-03-31"]


def test_index_is_newest_first(monkeypatch):
    body = [{"date": d, "xbrl": "https://nsearchives.nseindia.com/corporate/xbrl/" + d, "recordId": d}
            for d in ("31-MAR-2025", "30-JUN-2026", "31-DEC-2025")]
    monkeypatch.setattr(sf, "_get", lambda *a, **k: _Resp(body))
    sf._index_cache.pop("TEST3", None)
    rows = sf.index("TEST3")
    assert [r["period"] for r in rows] == ["2026-06-30", "2025-12-31", "2025-03-31"]


def test_a_dead_index_call_keeps_the_last_good_answer(monkeypatch):
    """Serving a stale list beats serving an empty page when NSE blinks."""
    body = [{"date": "30-JUN-2026", "xbrl": "https://nsearchives.nseindia.com/corporate/xbrl/a", "recordId": "1"}]
    monkeypatch.setattr(sf, "_get", lambda *a, **k: _Resp(body))
    sf._index_cache.pop("TEST4", None)
    assert len(sf.index("TEST4")) == 1

    monkeypatch.setattr(sf, "_get", lambda *a, **k: None)
    assert len(sf.index("TEST4", force=True)) == 1


@pytest.mark.parametrize("sym,want", [("reliance", "RELIANCE"),
                                      ("RELIANCE.NS", "RELIANCE"),
                                      ("  tcs.bo ", "TCS")])
def test_symbols_are_normalised_the_same_way_as_the_rest_of_the_app(sym, want):
    assert sf._clean_symbol(sym) == want


def test_named_context_pairing_handles_both_conventions():
    assert sf._pair_key("D_Foo_Context12") == "Foo_Context12"
    assert sf._pair_key("DetailsOfSharesHeldByMutualFundsOrUti001D") == \
        "DetailsOfSharesHeldByMutualFundsOrUti001I"
    assert sf._pair_key("MainI") is None


def test_a_document_url_that_is_not_the_exchange_archive_is_refused():
    """
    The URL comes out of a response body and is both fetched by the server and
    rendered as a link on the page. Anything but https on NSE's own archive is
    dropped rather than followed.
    """
    good = "https://nsearchives.nseindia.com/corporate/xbrl/SHP_1.xml"
    assert sf._safe_doc_url(good) == good
    for bad in ("http://nsearchives.nseindia.com/a.xml",      # not https
                "https://evil.example.com/a.xml",             # not the exchange
                "https://nseindia.com.evil.test/a.xml",       # lookalike host
                "javascript:alert(1)",
                "https://user:pw@nsearchives.nseindia.com/a.xml",
                "", None):
        assert sf._safe_doc_url(bad) is None, bad


def test_index_drops_a_row_whose_document_url_is_not_the_exchange(monkeypatch):
    body = [
        {"date": "30-JUN-2026", "xbrl": "https://evil.example.com/a.xml", "recordId": "1"},
        {"date": "31-MAR-2026",
         "xbrl": "https://nsearchives.nseindia.com/corporate/xbrl/ok.xml", "recordId": "2"},
    ]
    monkeypatch.setattr(sf, "_get", lambda *a, **k: _Resp(body))
    sf._index_cache.pop("TEST5", None)
    rows = sf.index("TEST5")
    assert [r["period"] for r in rows] == ["2026-03-31"]


def test_the_index_cache_is_bounded(monkeypatch):
    """A few thousand symbols must not accumulate in a 512MB process."""
    body = [{"date": "30-JUN-2026",
             "xbrl": "https://nsearchives.nseindia.com/corporate/xbrl/a.xml",
             "recordId": "1"}]
    monkeypatch.setattr(sf, "_get", lambda *a, **k: _Resp(body))
    monkeypatch.setattr(sf, "MAX_INDEXED", 10)
    sf._index_cache.clear()
    for i in range(40):
        sf.index("SYM%d" % i)
    assert len(sf._index_cache) <= 10
    sf._index_cache.clear()


# ---------------------------------------------------------------------------
# Quarter-ends versus interim filings
#
# Regulation 31 requires a filing each quarter AND one within ten days of a
# capital change, so a company's list interleaves the two. Fatchem's real list
# carries 2025-11-03, 2025-11-21 and 2026-01-17 between the quarter-ends.
#
# Reading that list as "quarters" broke the page twice: the chart plotted a
# fortnight at the same width as a quarter, and the year-on-year comparison
# counted four rows back, landed six months back, failed its own gap check and
# returned nothing — so every YoY cell rendered as an em-dash.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("day", ["2026-03-31", "2026-06-30", "2026-09-30",
                                 "2025-12-31", "2024-03-31"])
def test_quarter_ends_are_recognised(day):
    assert sf.is_quarter_end(day) is True


@pytest.mark.parametrize("day", ["2025-11-03", "2025-11-21", "2026-01-17",
                                 "2026-06-29", "2026-02-28", "", "nonsense", None])
def test_an_interim_filing_is_not_a_quarter_end(day):
    assert sf.is_quarter_end(day) is False


def _fcl_shaped(monkeypatch, periods):
    """A filing list shaped like the real one: quarter-ends with interim
    filings interleaved, and a different promoter figure at each."""
    rows = [{"period": p, "filed": p, "xbrl": "https://nsearchives.nseindia.com/x/%s" % p,
             "record_id": p, "revised": False,
             "quarter_end": sf.is_quarter_end(p)} for p in periods]
    monkeypatch.setattr(sf, "available", lambda: True)
    monkeypatch.setattr(sf, "index", lambda s, force=False: rows)

    base = sf.parse(_read(NEW))
    bodies = {}
    for i, p in enumerate(periods):
        cats = {k: dict(v) for k, v in base["categories"].items()}
        # Promoter falls one point per entry, so any wrong pairing shows up as
        # a wrong delta rather than as no delta at all.
        cats["promoter"] = dict(cats["promoter"], pct=60.0 - i)
        bodies["https://nsearchives.nseindia.com/x/%s" % p] = dict(
            base, categories=cats, period=p, filed=p,
            source="https://nsearchives.nseindia.com/x/%s" % p, revised=False)
    monkeypatch.setattr(sf, "filing",
                        lambda url, period="", filed="", revised=False: bodies.get(url))


# newest first, exactly as the exchange serves it
FCL_SHAPED = ["2026-06-30", "2026-03-31", "2026-01-17", "2025-12-31",
              "2025-11-21", "2025-11-03", "2025-09-30", "2025-06-30"]


def test_quarter_on_quarter_skips_an_interim_filing(monkeypatch):
    """
    The row before 2026-03-31 in the raw list is 2026-01-17, a fortnight
    earlier. Comparing against it reports a quarter of drift that did not
    happen.
    """
    _fcl_shaped(monkeypatch, FCL_SHAPED)
    out = sf.summary("FCL", quarters=12)
    promoter = [s for s in out["split"] if s["key"] == "promoter"][0]
    # 2026-06-30 is index 0 (60.0); the previous QUARTER-END is 2026-03-31 at
    # index 1 (59.0). One step, not two.
    assert promoter["change_qoq"] == pytest.approx(1.0)


def test_year_on_year_survives_interleaved_interim_filings(monkeypatch):
    """The regression that produced a column of em-dashes on the live page."""
    _fcl_shaped(monkeypatch, FCL_SHAPED)
    out = sf.summary("FCL", quarters=12)
    for row in out["split"]:
        assert row["change_yoy"] is not None, row["key"]
    promoter = [s for s in out["split"] if s["key"] == "promoter"][0]
    # 2025-06-30 is index 7 (53.0) against 2026-06-30 at 60.0.
    assert promoter["change_yoy"] == pytest.approx(7.0)


def test_quarters_and_filings_are_counted_separately(monkeypatch):
    _fcl_shaped(monkeypatch, FCL_SHAPED)
    out = sf.summary("FCL", quarters=12)
    assert out["filings_read"] == 8
    assert out["quarters_read"] == 5
    assert out["interim_filings"] == 3
    assert out["basis_period"] == "2026-06-30"


def test_the_presence_of_interim_filings_is_stated(monkeypatch):
    _fcl_shaped(monkeypatch, FCL_SHAPED)
    out = sf.summary("FCL", quarters=12)
    assert any("interim disclosures" in n for n in out["notes"])


def test_history_marks_which_rows_are_quarter_ends(monkeypatch):
    """The chart plots quarter-ends only; it needs to be able to tell."""
    _fcl_shaped(monkeypatch, FCL_SHAPED)
    out = sf.summary("FCL", quarters=12)
    marked = {h["period"]: h["quarter_end"] for h in out["history"]}
    assert marked["2026-03-31"] is True
    assert marked["2026-01-17"] is False
    assert marked["2025-11-21"] is False


def test_a_company_filing_only_quarter_ends_is_unaffected(monkeypatch):
    """The common case must not pay for the awkward one."""
    _fcl_shaped(monkeypatch, ["2026-06-30", "2026-03-31", "2025-12-31",
                              "2025-09-30", "2025-06-30"])
    out = sf.summary("CLEAN", quarters=12)
    assert out["interim_filings"] == 0
    assert out["quarters_read"] == 5
    promoter = [s for s in out["split"] if s["key"] == "promoter"][0]
    assert promoter["change_qoq"] == pytest.approx(1.0)
    assert promoter["change_yoy"] == pytest.approx(4.0)
    assert not any("interim disclosures" in n for n in out["notes"])


def test_a_gap_in_the_quarter_series_yields_no_year_figure(monkeypatch):
    """A company that stopped filing for a year gets nothing, not a guess."""
    _fcl_shaped(monkeypatch, ["2026-06-30", "2026-03-31", "2023-12-31"])
    out = sf.summary("GAPPY", quarters=12)
    for row in out["split"]:
        assert row["change_yoy"] is None
