"""
The daily portfolio digest.

Two things are being protected here. The first is arithmetic: a digest that
misstates somebody's day is worse than no digest, and this project has already
shipped one number that meant something other than what it said.

The second is the line the product must not cross. Nothing in a digest may
read as advice — no buy, no sell, no target, no "strong". India requires SEBI
registration for that, and this project does not have it. There is a test at
the bottom that reads the rendered output and fails on those words, because
the risk is not that somebody decides to add advice; it is that a helpful
phrase creeps into a template one afternoon and nobody notices.
"""
import datetime as dt

import pandas as pd
import pytest

import digest as D
import email_render as R


def frame(closes, volumes=None, opens=None):
    n = len(closes)
    return pd.DataFrame(
        {"Open": opens or closes,
         "High": [c * 1.01 for c in closes],
         "Low": [c * 0.99 for c in closes],
         "Close": closes,
         "Volume": volumes or [10_000] * n},
        index=pd.bdate_range("2024-01-01", periods=n))


def resolver(mapping):
    def resolve(sym):
        sym = sym.upper().replace(".NS", "")
        if sym not in mapping:
            raise KeyError(sym)
        return sym, None, mapping[sym]
    return resolve


@pytest.fixture
def two_stocks():
    #                      yesterday   today
    up = frame([100.0] * 60 + [200.0, 220.0])      # +10%
    down = frame([500.0] * 60 + [400.0, 380.0])    # -5%
    return resolver({"AAA": up, "BBB": down})


def test_the_day_is_priced_per_holding(two_stocks):
    d = D.build_digest([{"symbol": "AAA", "qty": 10}], resolve=two_stocks)
    row = d["rows"][0]
    assert row["price"] == 220.0
    assert row["value"] == 2200.0
    assert row["day_change"] == 200.0            # 10 × (220 − 200)
    assert row["day_change_pct"] == 10.0


def test_the_totals_are_the_sum_of_the_parts(two_stocks):
    d = D.build_digest([{"symbol": "AAA", "qty": 10}, {"symbol": "BBB", "qty": 2}],
                       resolve=two_stocks)
    t = d["totals"]
    assert t["value"] == 2200.0 + 760.0
    assert t["day_change"] == 200.0 + (2 * -20.0)
    # Percent is measured against what the portfolio was worth at the OPEN,
    # not what it is worth now — dividing by the closing value understates
    # every gain and overstates every loss.
    opening = t["value"] - t["day_change"]
    assert t["day_change_pct"] == pytest.approx(round(100 * t["day_change"] / opening, 2))


def test_movers_are_ranked_by_rupees_not_percent():
    """The whole point: a big slip in a big position outranks a small pop."""
    small = frame([100.0] * 60 + [100.0, 120.0])   # +20%, tiny holding
    large = frame([100.0] * 60 + [100.0, 99.0])    # −1%, huge holding
    d = D.build_digest([{"symbol": "SMALL", "qty": 1}, {"symbol": "LARGE", "qty": 10_000}],
                       resolve=resolver({"SMALL": small, "LARGE": large}))
    assert d["movers"]["down"][0]["symbol"] == "LARGE"
    assert d["movers"]["down"][0]["day_change"] == -10_000.0
    assert d["movers"]["up"][0]["symbol"] == "SMALL"


def test_a_holding_with_no_cost_basis_still_works(two_stocks):
    """Plenty of people know what they hold and not what they paid."""
    d = D.build_digest([{"symbol": "AAA", "qty": 10}], resolve=two_stocks)
    assert d["totals"]["value"] == 2200.0
    assert d["totals"]["pnl"] is None
    assert d["rows"][0]["day_change"] == 200.0


def test_cost_basis_produces_overall_pnl(two_stocks):
    d = D.build_digest([{"symbol": "AAA", "qty": 10, "avg_price": 100.0}],
                       resolve=two_stocks)
    assert d["totals"]["cost"] == 1000.0
    assert d["totals"]["pnl"] == 1200.0
    assert d["totals"]["pnl_pct"] == 120.0


def test_one_dead_symbol_does_not_kill_the_digest(two_stocks):
    d = D.build_digest([{"symbol": "AAA", "qty": 10}, {"symbol": "NOSUCH", "qty": 5}],
                       resolve=two_stocks)
    assert d["holdings_counted"] == 1
    assert d["missing"][0]["symbol"] == "NOSUCH"


def test_a_symbol_held_twice_is_fetched_once():
    calls = []

    def resolve(sym):
        calls.append(sym)
        return sym, None, frame([100.0] * 60 + [100.0, 101.0])

    D.build_digest([{"symbol": "AAA", "qty": 1}, {"symbol": "AAA", "qty": 2},
                    {"symbol": "aaa.ns", "qty": 3}], resolve=resolve)
    assert calls == ["AAA"], "the fan-out cache is what keeps the daily job affordable"


# ── Observations ─────────────────────────────────────────────────────────────

def test_a_moving_average_crossing_is_reported():
    closes = [100.0] * 60 + [90.0] * 60 + [80.0, 130.0]
    d = D.build_digest([{"symbol": "AAA", "qty": 1}],
                       resolve=resolver({"AAA": frame(closes)}))
    assert any("50-day average" in o["line"] for o in d["observations"])


def test_a_volume_spike_is_reported():
    closes = [100.0] * 40 + [101.0]
    vols = [1000] * 40 + [9000]
    d = D.build_digest([{"symbol": "AAA", "qty": 1}],
                       resolve=resolver({"AAA": frame(closes, volumes=vols)}))
    assert any("usual volume" in o["line"] for o in d["observations"])


def test_a_quiet_day_says_nothing_rather_than_inventing_something():
    closes = [100.0] * 300
    d = D.build_digest([{"symbol": "AAA", "qty": 1}],
                       resolve=resolver({"AAA": frame(closes)}))
    assert d["observations"] == []


def test_filings_ride_along_and_sort_by_importance_then_size(two_stocks):
    filings = {
        "AAA": [{"category": "Board Meeting", "importance": "low",
                 "headline": "Intimation", "pdf": "http://x/1.pdf"}],
        "BBB": [{"category": "Order Win", "importance": "high",
                 "headline": "Order received", "pdf": "http://x/2.pdf"}],
    }
    d = D.build_digest([{"symbol": "AAA", "qty": 10}, {"symbol": "BBB", "qty": 2}],
                       resolve=two_stocks, filings_for=lambda s: filings.get(s, []))
    assert [e["symbol"] for e in d["events"]] == ["BBB", "AAA"]


def test_a_broken_filing_feed_does_not_break_the_email(two_stocks):
    def boom(_):
        raise RuntimeError("feed down")
    d = D.build_digest([{"symbol": "AAA", "qty": 10}], resolve=two_stocks, filings_for=boom)
    assert d["events"] == [] and d["holdings_counted"] == 1


# ── Rendering ────────────────────────────────────────────────────────────────

def test_rupees_use_indian_grouping():
    """A reader checks this against their broker app. 12,34,567 — not 1,234,567."""
    assert R.rupees(1234567) == "₹12,34,567"
    assert R.rupees(-4500, signed=True) == "-₹4,500"
    assert R.rupees(4500, signed=True) == "+₹4,500"
    assert R.rupees(None) == "—"


def test_the_subject_line_leads_with_the_number(two_stocks):
    d = D.build_digest([{"symbol": "AAA", "qty": 10}], resolve=two_stocks)
    s = R.subject(d)
    assert s.startswith("Portfolio up ₹200")


def test_the_email_renders_without_a_cost_basis_or_a_filing(two_stocks):
    d = D.build_digest([{"symbol": "AAA", "qty": 10}], resolve=two_stocks)
    html = R.render_html(d)
    assert "AAA" in html and "₹2,200" in html
    assert "None" not in html, "a missing value must render as — , never as None"
    assert R.render_text(d).startswith("ALTAHA SCREENER")


def test_the_email_carries_no_javascript_and_no_remote_images(two_stocks):
    """Images are blocked by default in most clients; scripts are stripped."""
    html = R.render_html(D.build_digest([{"symbol": "AAA", "qty": 10}], resolve=two_stocks))
    assert "<script" not in html.lower()
    assert "<img" not in html.lower()


def test_the_email_never_tells_anybody_what_to_do(two_stocks):
    """The SEBI line. A helpful phrase creeping into a template is the risk."""
    filings = {"AAA": [{"category": "Results", "importance": "high",
                        "headline": "Q2 results filed", "pdf": "http://x/1.pdf"}]}
    d = D.build_digest([{"symbol": "AAA", "qty": 10, "avg_price": 100.0}],
                       resolve=two_stocks, filings_for=lambda s: filings.get(s, []))
    html, text = R.render_html(d), R.render_text(d)

    # The disclaimer is the one place those words are allowed — it exists to
    # say the email is NOT that. Scan everything else.
    disclaimer = "never a recommendation to buy or sell"
    assert disclaimer in html.lower() and disclaimer in text.lower()
    body = (html + " " + text).lower().replace(disclaimer, "")

    for word in (" buy ", " sell ", "target price", "recommend", "strong buy",
                 "book profit", "accumulate", "must-own"):
        assert word not in body, f"advice language in the digest: {word!r}"


def test_an_empty_portfolio_is_not_worth_sending():
    assert D.is_worth_sending({"holdings_counted": 0}) is False


def test_a_flat_uneventful_day_can_be_held_back(two_stocks):
    d = D.build_digest([{"symbol": "AAA", "qty": 10}], resolve=two_stocks)
    d["observations"], d["events"] = [], []
    d["totals"]["day_change_pct"] = 0.1
    assert D.is_worth_sending(d, min_move_pct=0.0) is True
    assert D.is_worth_sending(d, min_move_pct=0.5) is False


def test_an_empty_digest_falls_back_to_the_wall_clock():
    now = dt.datetime(2026, 9, 10, 16, 30, tzinfo=D.IST)
    d = D.build_digest([], resolve=resolver({}), now=now)
    assert d["date"] == "2026-09-10" and d["data_date"] is None


def test_the_digest_is_dated_by_the_market_not_the_clock(two_stocks):
    """The feed settles after the close and lags at times. A card headed with
    today's date over yesterday's closes is the 26%-bug shape all over again."""
    now = dt.datetime(2026, 9, 10, 16, 30, tzinfo=D.IST)
    d = D.build_digest([{"symbol": "AAA", "qty": 1}], resolve=two_stocks, now=now)
    last_session = str(two_stocks("AAA")[2].index[-1])[:10]
    assert d["data_date"] == last_session
    assert d["date"] == last_session != "2026-09-10"
