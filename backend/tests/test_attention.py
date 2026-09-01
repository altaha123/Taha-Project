"""
Retail attention, as a risk flag.

The design claim being protected: this is a WARNING, never a buy signal, and
it never touches a score. For Indian small and mid caps a mention spike is far
more often a pump in progress than a discovery, and shipping it the usual way
round would ship the half that does not work.
"""
import attention as A
from conftest import ohlcv, ramp


def _df(volumes):
    return ohlcv([100.0] * len(volumes), volume=volumes)


def test_quiet_turnover_reads_as_normal():
    out = A.assess("ACME", df=_df([1e6] * 120))
    assert out["tier"] == "normal"
    assert out["flag"] is None


def test_a_turnover_spike_is_flagged():
    out = A.assess("ACME", df=_df([1e6] * 115 + [8e6] * 5))
    assert out["tier"] == "extreme"
    assert out["flag"]
    assert out["market"]["times_normal"] > 4


def test_the_dangerous_case_is_attention_plus_thin_liquidity():
    """The crowd is the exit liquidity. That is the sentence this module
    exists to be able to say."""
    out = A.assess("ACME", df=_df([1e6] * 115 + [8e6] * 5),
                   liquidity_tier="thin")
    assert "pump" in out["flag"].lower()


def test_it_is_never_a_buy_signal():
    out = A.assess("ACME", df=_df([1e6] * 115 + [8e6] * 5))
    assert out["direction"] == "risk"
    assert "not a direction" in out["note"].lower()
    for word in ("buy", "target", "entry"):
        assert word not in (out["flag"] or "").lower()


def test_missing_price_history_narrows_the_reading_rather_than_failing_it():
    out = A.assess("ACME", df=None, filings=[{"x": 1}], stories=[{"y": 2}])
    assert out["tier"] == "normal"
    assert out["filings_this_week"] == 1 and out["stories_this_week"] == 1
    assert out["market"]["available"] is False


def test_unavailable_sources_say_why_instead_of_returning_nothing(monkeypatch):
    """
    Reddit's free JSON answers 403 to datacenter IPs and X's read API is paid.
    A module that quietly returns nothing because it cannot authenticate is
    worse than one that says so.
    """
    for k in ("REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET",
              "X_BEARER_TOKEN", "TWITTER_BEARER_TOKEN"):
        monkeypatch.delenv(k, raising=False)
    src = A.sources_available()
    assert src["market"]["available"] and src["filings"]["available"]
    assert src["reddit"]["available"] is False
    assert "REDDIT_CLIENT_ID" in src["reddit"]["note"]
    assert src["x"]["available"] is False
    assert "X_BEARER_TOKEN" in src["x"]["note"]
    assert A.assess("ACME", df=_df([1e6] * 120))["social_configured"] is False


def test_configured_sources_are_reported_as_configured(monkeypatch):
    monkeypatch.setenv("REDDIT_CLIENT_ID", "id")
    monkeypatch.setenv("REDDIT_CLIENT_SECRET", "secret")
    assert A.sources_available()["reddit"]["available"] is True


def test_assess_never_raises():
    for df in (None, ohlcv([1.0]), _df([0] * 120), ohlcv(ramp(1, 2, 300))):
        A.assess("X", df=df, filings=None, stories=None, liquidity_tier=None)
