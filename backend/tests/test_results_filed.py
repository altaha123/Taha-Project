"""
The results card, read from the exchange filing.

The card used to come from Yahoo's quarterly statements, which arrive days
after the company files: TARIL filed its September 2026 quarter on NSE on
13 October and the card still showed June the next day. What must hold now:
the exchange filing is read first and the card names the quarter it filed,
Yahoo answers only what the exchange cannot, and a quarter the index lists
but could not be read is never passed off as absent.
"""

import datetime as dt
import sys

import pandas as pd
import pytest

from conftest import ohlcv, arc, ramp


def _row(end, rev_cr, pat_cr, filed="13-Oct-2026 16:34:09"):
    import fundamentals as F
    e = dt.date.fromisoformat(end)
    return {"period_end": end, "label": F.quarter_label(e), "filed_at": filed,
            "audited": "Un-Audited", "source": "https://nse/%s.xml" % end,
            "values": {"revenue": rev_cr * 1e7, "pat": pat_cr * 1e7}}


# TARIL as filed: the September 2026 quarter and the four before it.
TARIL = {
    "available": True, "symbol": "TARIL", "basis": "consolidated",
    "company": "Transformers And Rectifiers (India) Limited",
    "filed_latest": "2026-09-30",
    "rows": [_row("2026-09-30", 739.44, 81.38),
             _row("2026-06-30", 572.34, 64.29, "20-Jul-2026 18:21:16"),
             _row("2026-03-31", 782.67, 91.39, "21-Apr-2026 18:43:16"),
             _row("2025-12-31", 736.76, 75.97, "31-Jan-2026 10:45:48"),
             _row("2025-09-30", 460.03, 37.35, "30-Dec-2025 10:27:25")],
}


def test_the_card_shows_the_quarter_just_filed():
    from results import filed_results
    out = filed_results(TARIL, sym="TARIL")
    assert out["available"]
    assert out["quarter"] == "Q2 FY27" and out["as_of"] == "2026-09-30"
    assert out["filed_at"] == "13-Oct-2026 16:34:09"
    assert out["pat_cr"] == 81.38 and out["revenue_cr"] == 739.44
    # Year on year against the same quarter a year earlier, not the last one.
    assert out["pat_yoy_base_cr"] == 37.35
    assert out["pat_yoy_pct"] == pytest.approx(117.9)
    assert out["revenue_yoy_pct"] == pytest.approx(60.7)
    assert out["pat_qoq_base_cr"] == 64.29
    assert [p["period"] for p in out["revenue_series"]][:2] == ["Q2 FY27", "Q1 FY27"]
    assert out["basis"] == "consolidated"
    assert out["pat_label"].startswith("Consolidated")
    assert "NSE" in out["source"] and "newer_filing" not in out
    assert any("rose" in b for b in out["bullets"])


def test_a_listed_quarter_that_could_not_be_read_is_said_out_loud():
    from results import filed_results
    behind = dict(TARIL, rows=TARIL["rows"][1:])
    out = filed_results(behind, sym="TARIL")
    assert out["quarter"] == "Q1 FY27"
    assert out["newer_filing"] == "2026-09-30"
    assert "2026-09-30" in out["note"] and "could not be read" in out["note"]


def test_nothing_filed_is_unavailable_not_empty():
    from results import filed_results
    out = filed_results({"available": False, "message": "No filing."})
    assert out == {"available": False, "message": "No filing."}
    assert filed_results(dict(TARIL, rows=[]))["available"] is False


def test_the_yahoo_card_is_unchanged():
    """The fallback still builds the same card from a statements frame."""
    from results import quarterly_results
    cols = [pd.Timestamp(d) for d in ("2026-06-30", "2026-03-31", "2025-12-31",
                                      "2025-09-30", "2025-06-30")]
    frame = pd.DataFrame([[600e7, 780e7, 730e7, 460e7, 500e7],
                          [61.52e7, 90e7, 75e7, 37e7, 67.35e7]],
                         index=["Total Revenue", "Net Income"], columns=cols)
    out = quarterly_results(frame, "Acme", "ACME.NS")
    assert out["quarter"] == "Q1 FY27" and out["as_of"] == "2026-06-30"
    assert out["pat_yoy_base_cr"] == 67.35
    assert out["pat_yoy_pct"] == pytest.approx(-8.7)
    assert "Yahoo" in out["source"] and "lag" in out["note"]
    assert "filed_at" not in out


# ---------------------------------------------------------------------------
# The endpoint
# ---------------------------------------------------------------------------

@pytest.fixture()
def app(monkeypatch):
    import main
    calls = {"series": [], "resolve": []}

    def fake_series(sym, quarters=8, basis=None):
        calls["series"].append(sym)
        if sym == "TARIL":
            return TARIL
        if sym == "BEHIND":
            return dict(TARIL, rows=TARIL["rows"][1:])
        return {"available": False, "message": "No filing for %s." % sym}

    frame = ohlcv(arc(150, 100, 200) + ramp(150, 168, 120))

    class _Ticker:
        quarterly_financials = pd.DataFrame(
            [[100e7, 90e7], [10e7, 9e7]], index=["Total Revenue", "Net Income"],
            columns=[pd.Timestamp("2026-06-30"), pd.Timestamp("2026-03-31")])
        info = {"longName": "Apple Inc."}

    def fake_resolve(raw):
        calls["resolve"].append(raw)
        return raw.upper(), _Ticker(), frame

    monkeypatch.setattr(main.fundamentals_source, "series", fake_series)
    monkeypatch.setattr(main, "resolve", fake_resolve)
    monkeypatch.setattr(main, "_filed_memo", {})
    main._calls = calls
    return main


def test_an_nse_stock_is_answered_from_its_filing(app):
    out = app.results(ticker="taril")
    assert out["quarter"] == "Q2 FY27" and out["filed_at"]
    assert out["disclaimer"]
    assert app._calls["resolve"] == []           # Yahoo was never asked


def test_dot_ns_reads_the_filing_too(app):
    out = app.results(ticker="TARIL.NS")
    assert out["quarter"] == "Q2 FY27" and out["symbol"] == "TARIL"


def test_what_the_exchange_cannot_answer_falls_back_to_yahoo(app):
    out = app.results(ticker="AAPL")
    assert app._calls["series"] == ["AAPL"] and app._calls["resolve"] == ["AAPL"]
    assert out["available"] and "Yahoo" in out["source"]


def test_an_explicit_other_listing_never_goes_to_nse(app):
    app.results(ticker="TARIL.BO")
    app.results(ticker="^NSEI")
    assert app._calls["series"] == []


def test_the_filing_is_held_briefly_and_only_when_it_was_read(app):
    app.results(ticker="TARIL")
    app.results(ticker="TARIL")
    assert app._calls["series"] == ["TARIL"]
    app.results(ticker="AAPL")
    app.results(ticker="AAPL")
    assert app._calls["series"].count("AAPL") == 2   # a miss is not remembered


def test_a_read_missing_the_newest_quarter_is_not_held(app):
    """The card says 'try again in a minute'; the memo must not make that a
    lie by serving the same short read for five."""
    first = app.results(ticker="BEHIND")
    assert first["newer_filing"] == "2026-09-30"
    app.results(ticker="BEHIND")
    assert app._calls["series"].count("BEHIND") == 2


# ---------------------------------------------------------------------------
# The card and the link a post carries
# ---------------------------------------------------------------------------

def test_the_results_card_renders_from_the_filing(app):
    r = app.og_results(ticker="TARIL", period="Q2-FY27")
    assert r.media_type == "image/png" and r.body[:8] == b"\x89PNG\r\n\x1a\n"
    assert (int.from_bytes(r.body[16:20], "big"),
            int.from_bytes(r.body[20:24], "big")) == (1200, 630)
    assert app._calls["resolve"] == []


def test_a_stock_with_no_results_has_no_card(app, monkeypatch):
    from fastapi import HTTPException

    class _Empty:
        quarterly_financials = pd.DataFrame()
        info = {}

    monkeypatch.setattr(app, "resolve", lambda raw: (raw, _Empty(), None))
    with pytest.raises(HTTPException) as e:
        app.og_results(ticker="NOPE")
    assert e.value.status_code == 404


def test_the_share_page_unfurls_into_the_card_and_opens_the_results(app):
    html = app.share_results("TARIL", period="Q2-FY27").body.decode()
    assert "Q2 FY27 results" in html
    assert "Profit after tax ₹81.38 Cr (+117.9% YoY)" in html
    assert "As filed with NSE on 13-Oct-2026" in html
    assert "/og/results.png?ticker=TARIL&amp;period=Q2-FY27" in html
    assert 'name="twitter:card" content="summary_large_image"' in html
    # Opens the results view on that stock, not the analysis page.
    assert "/?go=results&amp;q=TARIL" in html
    assert "onrender.com" not in html
