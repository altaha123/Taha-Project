"""
The plain-English score explanation (score_explain.py, GET /explain).

The provider is never called here: `_post` is replaced by a fake that records
what it was sent. What is under test is everything around the model — that it
stays off without a key, that it only ever sees the engine's numbers, that one
stock costs one call a day, that the free allowance is rationed, and that a
reply reading as advice is never shown.
"""
import json

import pytest

import score_explain as SE


class _Resp:
    def __init__(self, status=200, body=None, headers=None):
        self.status_code = status
        self._body = body
        self.headers = headers or {}

    def json(self):
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


def _reply(text, tokens=1800):
    return _Resp(200, {"choices": [{"message": {"content": text}}],
                       "usage": {"total_tokens": tokens}})


GOOD = ("RELIANCE scores 68 out of 100, labelled CONSTRUCTIVE.\n\n"
        "Its ROCE (profit on the money invested in the business) of 18% is "
        "lifting the score; a P/E dearer than 70% of peers holds it back.\n\n"
        "Some factors were missing, so confidence is 74%. This explains the "
        "score; it is not a recommendation.")


def _analysis(score=68):
    return {
        "ticker": "RELIANCE.NS", "name": "Reliance Industries", "currency": "INR",
        "profile": {"sector": "Energy", "industry": "Oil & Gas"},
        "scoring": {"score": score, "label": "CONSTRUCTIVE", "horizon_label": "Position",
                    "model": {"name": "Corporate"}, "confidence": 74.0,
                    "confidence_notes": "2 applicable factors unavailable",
                    "pillars": {"quality": 71.2, "value": 38.9},
                    "coverage": {"present": 18, "total": 20}},
        "altaha_score_v4": {
            "what_helped": [{"label": "ROCE", "value": 0.18, "percentile": 81.4, "peer_count": 40}],
            "what_hurt": [{"label": "Earnings yield", "value": 0.03, "percentile": 22.0, "peer_count": 40}],
        },
        "ratios": {"pe": 27.1, "roce": 18.0, "dividend_yield": None},
        "peers": {"pe": {"phrase": "dearer than 70%"}},
        "fundamental": {"f_score": 7, "checks": [
            {"name": "ROCE", "points": 10, "max": 10, "value": "18%", "formula": "x", "explain": "y"}]},
        "technical": {"checks": [
            {"name": "Trend structure", "points": 24, "max": 30, "value": "Price 2,900",
             "formula": "x", "explain": "y"}]},
        # Present on the real payload and must never reach the model.
        "levels": {"support": [2800], "resistance": [3000]},
        "plan": {"entry": 2850, "stop": 2700},
    }


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.setattr(SE, "DB_PATH", str(tmp_path / "explanations.db"))
    monkeypatch.setattr(SE, "_visitors", {"day": None, "counts": {}})
    monkeypatch.setattr(SE, "_cooldown", {"until": 0.0})
    calls = []

    def install(*responses):
        queue = list(responses)

        def fake(url, headers, body, timeout):
            calls.append({"url": url, "headers": headers, "body": body})
            return queue.pop(0)
        monkeypatch.setattr(SE, "_post", fake)
    return calls, install


def test_off_without_a_key(monkeypatch, tmp_path):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setattr(SE, "DB_PATH", str(tmp_path / "e.db"))
    monkeypatch.setattr(SE, "_post", lambda *a, **k: pytest.fail("network called"))
    out = SE.explain("RELIANCE", "position", _analysis())
    assert out["available"] is False and out["reason"] == "not_configured"


def test_facts_carry_the_score_and_never_the_plan():
    facts = SE.build_facts(_analysis())
    assert facts["altaha_score"]["score_out_of_100"] == 68
    assert facts["helped_most"][0]["factor"] == "ROCE"
    assert facts["hurt_most"][0]["percentile_vs_peers"] == 22
    assert "dividend_yield" not in facts["key_ratios"]   # unknown is omitted, not zero
    blob = json.dumps(facts)
    assert "entry" not in blob and "stop" not in blob and "support" not in blob


def test_writes_once_then_serves_the_stored_copy(env):
    calls, install = env
    install(_reply(GOOD))
    first = SE.explain("RELIANCE", "position", _analysis(), visitor="1.1.1.1")
    assert first["available"] is True and first["cached"] is False
    assert len(first["paragraphs"]) == 3
    assert "not advice" in first["disclaimer"]

    second = SE.explain("RELIANCE", "position", _analysis(), visitor="2.2.2.2")
    assert second["available"] is True and second["cached"] is True
    assert second["paragraphs"] == first["paragraphs"]
    assert len(calls) == 1
    assert SE.tokens_used_today() == 1800


def test_request_is_shaped_for_the_free_model(env):
    calls, install = env
    install(_reply(GOOD))
    SE.explain("RELIANCE", "position", _analysis())
    body = calls[0]["body"]
    assert calls[0]["url"] == SE.GROQ_URL
    assert calls[0]["headers"]["Authorization"] == "Bearer test-key"
    assert body["model"] == "openai/gpt-oss-120b"
    assert body["reasoning_effort"] == "low" and body["include_reasoning"] is False
    user = body["messages"][1]["content"]
    assert "<facts>" in user and "</facts>" in user
    assert "entry" not in user


def test_each_horizon_is_its_own_explanation(env):
    calls, install = env
    install(_reply(GOOD), _reply(GOOD))
    SE.explain("RELIANCE", "position", _analysis())
    SE.explain("RELIANCE", "swing", _analysis())
    assert len(calls) == 2


@pytest.mark.parametrize("text", [
    "The score is strong, so you should buy it.",
    "Investors could accumulate on dips.",
    "A stop-loss near 2,700 limits risk.",
    "We recommend this stock.",
    "Our target price is 3,400.",
])
def test_advice_is_withheld_not_shown(env, text):
    calls, install = env
    install(_reply(text))
    out = SE.explain("RELIANCE", "position", _analysis())
    assert out["available"] is False and out["reason"] == "withheld"
    assert "paragraphs" not in out
    # Stored, so the same stock does not spend the allowance again today.
    again = SE.explain("RELIANCE", "position", _analysis())
    assert again["reason"] == "withheld" and len(calls) == 1


@pytest.mark.parametrize("text", [
    "Selling expenses rose, which weighs on margins.",
    "The company completed a buyback last year.",
    "Promoters hold 50% of the shares.",
    "This explains the score; it is not a recommendation.",
    "It is not a recommendation to buy or sell.",
    "The score does not tell you whether to buy or sell the share.",
    "It is never a buy or sell signal.",
    # Wordings the first version of the check withheld in production.
    "This is not a buy or sell recommendation.",
    "This should not be taken as a recommendation.",
    "It is not investment advice or a recommendation.",
    "The score is not intended to be a recommendation to buy or sell.",
    "It does not suggest whether you should buy or sell.",
    "Remember, this is not a recommendation to buy, sell or hold the stock.",
    "Nothing here is a recommendation.",
    "It doesn't tell you to buy or sell.",
])
def test_ordinary_words_are_not_mistaken_for_advice(text):
    assert not SE.advice_like(text)


@pytest.mark.parametrize("text", [
    "You should buy this. This is not a recommendation.",
    "Buy it now, there is no downside.",
    "Investors should accumulate. Nothing here is advice.",
])
def test_a_disclaimer_does_not_excuse_advice_elsewhere(text):
    assert SE.advice_like(text)


def test_an_answer_withheld_by_an_older_check_is_written_again(env):
    calls, install = env
    install(_reply(GOOD))
    old = {"available": False, "reason": "withheld", "message": "withheld"}   # no filter version
    SE._store("ARROWGREEN", "position", old)
    out = SE.explain("ARROWGREEN", "position", _analysis())
    assert out["available"] is True and len(calls) == 1


def test_a_withheld_answer_records_the_check_that_withheld_it(env):
    calls, install = env
    install(_reply("You should buy this stock."))
    SE.explain("RELIANCE", "position", _analysis())
    assert SE.cached("RELIANCE", "position")["filter"] == SE.FILTER_VERSION


def test_markdown_is_stripped_and_lines_become_paragraphs(env):
    calls, install = env
    install(_reply("**ROCE** of 18% helps.\nThe P/E holds it back.\n# Note\nConfidence is 74%."))
    out = SE.explain("RELIANCE", "position", _analysis())
    assert out["paragraphs"] == ["ROCE of 18% helps.", "The P/E holds it back.",
                                 "Note", "Confidence is 74%."]


def test_a_cut_off_reply_is_not_stored(env):
    calls, install = env
    cut = _reply("RELIANCE scores 68 out of 100 and its")
    cut._body["choices"][0]["finish_reason"] = "length"
    install(cut, _reply(GOOD))
    assert SE.explain("RELIANCE", "position", _analysis())["reason"] == "error"
    assert SE.explain("RELIANCE", "position", _analysis())["available"] is True
    assert len(calls) == 2


def test_unscored_stock_costs_nothing(env):
    calls, install = env
    install()
    out = SE.explain("NEWCO", "position", _analysis(score=None))
    assert out["reason"] == "not_scored" and calls == []


def test_daily_budget_stops_fresh_calls(env, monkeypatch):
    calls, install = env
    install(_reply(GOOD, tokens=SE.DAILY_TOKENS))
    SE.explain("RELIANCE", "position", _analysis())
    out = SE.explain("TCS", "position", _analysis())
    assert out["reason"] == "daily_budget" and len(calls) == 1
    # A stock already written today still opens.
    assert SE.explain("RELIANCE", "position", _analysis())["available"] is True


def test_one_visitor_cannot_spend_everyones_allowance(env, monkeypatch):
    calls, install = env
    monkeypatch.setattr(SE, "PER_VISITOR", 2)
    install(_reply(GOOD), _reply(GOOD), _reply(GOOD))
    SE.explain("A", "position", _analysis(), visitor="9.9.9.9")
    SE.explain("B", "position", _analysis(), visitor="9.9.9.9")
    out = SE.explain("C", "position", _analysis(), visitor="9.9.9.9")
    assert out["reason"] == "visitor_limit"
    assert SE.explain("C", "position", _analysis(), visitor="8.8.8.8")["available"]
    assert len(calls) == 3


def test_rate_limit_backs_off(env):
    calls, install = env
    install(_Resp(429, {}, {"retry-after": "30"}))
    out = SE.explain("RELIANCE", "position", _analysis())
    assert out["reason"] == "busy"
    # Inside the cooldown nothing is sent at all.
    assert SE.explain("TCS", "position", _analysis())["reason"] == "busy"
    assert len(calls) == 1


@pytest.mark.parametrize("resp", [
    _Resp(500, {}),
    _Resp(200, ValueError("not json")),
    _Resp(200, {"choices": []}),
])
def test_provider_failures_never_raise(env, resp):
    calls, install = env
    install(resp)
    out = SE.explain("RELIANCE", "position", _analysis())
    assert out["available"] is False and out["reason"] == "error"


def test_endpoint_reads_the_stored_copy_without_analysing(env, monkeypatch):
    import main
    from starlette.requests import Request
    calls, install = env
    install(_reply(GOOD))
    seen = []
    monkeypatch.setattr(main, "analyze", lambda t, h="position": seen.append(t) or _analysis())
    req = Request({"type": "http", "headers": [(b"x-forwarded-for", b"5.5.5.5, 10.0.0.1")],
                   "client": ("10.0.0.1", 1)})

    first = main.explain_score("reliance.ns", req)
    assert first["available"] is True and seen == ["reliance.ns"]
    # A different spelling of the same stock shares the stored copy.
    second = main.explain_score("RELIANCE", req)
    assert second["cached"] is True and len(seen) == 1 and len(calls) == 1


def test_endpoint_is_off_without_a_key(monkeypatch):
    import main
    from starlette.requests import Request
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setattr(main, "analyze", lambda *a, **k: pytest.fail("analysed while off"))
    out = main.explain_score("RELIANCE", Request({"type": "http", "headers": []}))
    assert out["reason"] == "not_configured"
