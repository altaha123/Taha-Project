"""
Industry classification when NSE's quote API cannot be read.

What must hold: one classifier for the whole market (a half-NSE, half-Yahoo
market splits every real industry into two groups), Yahoo filling share
counts and prices only where NSE left them empty, an empty Yahoo answer never
erasing a good profile, and the backfill queue putting unprofiled companies
first.
"""

import sys

import pytest


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("ALTAHA_FUNDAMENTALS_DB", str(tmp_path / "f.db"))
    for m in ("fundamentals_store", "fundamentals_crawl", "industry"):
        sys.modules.pop(m, None)
    import fundamentals_store
    return fundamentals_store


YAHOO = {"TCS": {"industry": "Information Technology Services", "sector": "Technology",
                 "shares": 3.6e9, "price": 3100.0, "company": "Tata Consultancy"},
         "INFY": {"industry": "Information Technology Services", "sector": "Technology",
                  "shares": 4.1e9, "price": 1500.0},
         "HDFCBANK": {"industry": "Banks - Regional", "sector": "Financial Services",
                      "shares": 7.6e9, "price": 950.0}}


def test_nse_is_used_only_when_it_covers_most_of_the_market():
    import industry as I
    src, by = I.choose({}, YAHOO)
    assert src == I.YAHOO and by["TCS"] == by["INFY"] == "Information Technology Services"
    # One NSE industry out of three is not a classification of the market:
    # mixing it in would put TCS and INFY in different groups.
    src, by = I.choose({"TCS": {"industry": "IT - Software"}}, YAHOO)
    assert src == I.YAHOO and by["TCS"] == "Information Technology Services"
    nse = {s: {"industry": "X"} for s in YAHOO}
    assert I.choose(nse, YAHOO)[0] == I.NSE
    assert I.choose({}, {}) == (None, {})


def test_lens_profiles_fill_gaps_without_overwriting_nse():
    import industry as I
    nse = {"TCS": {"symbol": "TCS", "issued_shares": 3.61e9, "last_price": None,
                   "industry": None, "macro": None, "basic_industry": None}}
    out = I.merge(nse, YAHOO)
    assert out["TCS"]["issued_shares"] == 3.61e9          # NSE's own count kept
    assert out["TCS"]["last_price"] == 3100.0             # Yahoo fills the gap
    assert out["TCS"]["industry"] == "Information Technology Services"
    assert out["TCS"]["industry_source"] == I.YAHOO
    assert out["HDFCBANK"]["issued_shares"] == 7.6e9
    assert out["INFY"].get("company") is None       # nothing to fill from


def test_a_profile_is_stored_and_an_empty_one_never_replaces_it(store):
    info = {"longName": "Tata Consultancy Services Limited", "sector": "Technology",
            "industry": "Information Technology Services", "sharesOutstanding": 3618087518,
            "currentPrice": 3102.5, "marketCap": 1.12e13, "currency": "INR"}
    assert store.record_yf_profile("tcs", info)
    assert not store.record_yf_profile("TCS", {})           # throttled answer
    p = store.yf_profiles()["TCS"]
    assert p["industry"] == "Information Technology Services" and p["shares"] == 3618087518
    assert store.stats()["yfinance"]["profiles_with_industry"] == 1


def test_the_backfill_queue_and_crawl(store, monkeypatch):
    import fundamentals_crawl as fc
    store.record_yf_profile("TCS", {"industry": "IT"})
    assert store.profile_due(["TCS", "INFY", "HDFCBANK"], limit=5) == ["INFY", "HDFCBANK"]

    class T:
        def __init__(self, sym):
            self.info = {"industry": "Banks - Regional"} if sym == "HDFCBANK" else {}
    monkeypatch.setattr(fc, "_ticker", T)
    monkeypatch.setattr(fc, "universe", lambda: ["TCS", "INFY", "HDFCBANK"])
    out = fc.run(limit=5, pause=0, source="yfinance-profile")
    assert out["attempted"] == 2 and out["ok"] == 1
    assert "HDFCBANK" in store.yf_profiles()
    # INFY had no profile: it waits a week rather than heading the next slice.
    assert store.profile_due(["TCS", "INFY", "HDFCBANK"]) == []


def test_peers_name_their_classifier(store):
    import fundamentals as F
    out = F.peers_from_store("TCS", None, [], classifier="Yahoo Finance")
    assert out["classifier"] == "Yahoo Finance" and not out["available"]
    assert "industry for TCS is not held" in out["message"]


def test_companies_yahoo_has_nothing_for_never_block_the_queue(store, monkeypatch):
    """The production failure: six unprofilable companies at the head of the
    queue tripped the give-up rule on every slice, so nobody behind them was
    ever reached and the backfill sat at the same count for days."""
    import fundamentals_crawl as fc
    dead = ["DEAD%d" % i for i in range(6)]
    live = ["TCS", "SUNPHARMA"]
    universe = dead + live

    class T:
        def __init__(self, sym):
            self.info = {"industry": "Something"} if sym in live else {}
    monkeypatch.setattr(fc, "_ticker", T)
    monkeypatch.setattr(fc, "universe", lambda: universe)
    first = fc.run(limit=60, pause=0, source="yfinance-profile")
    assert first["attempted"] == 6 and first["ok"] == 0 and first["stopped_early"]
    # The next slice starts where the last one gave up, not at the same six.
    second = fc.run(limit=60, pause=0, source="yfinance-profile")
    assert second["ok"] == 2
    assert set(store.yf_profiles()) == set(live)
    # And the dead ones are retried weekly, not on every slice.
    assert store.profile_due(universe) == []
    assert fc.run(limit=60, pause=0, source="yfinance-profile")["stopped_early"] == "nothing due"
