"""
Ask AI on the query screener.

No test here reaches Claude. A fake client stands in for the SDK and records
what it was sent, because what matters is checkable without the model:

  · the routes are closed without the admin key, and closed when no admin key
    is configured at all — every question is billed;
  · the model is told the real field catalogue and a grammar the real parser
    accepts, so it cannot be taught a field or a syntax that does not exist;
  · its tools run the real parser over real rows, and every query in the
    answer is checked again afterwards — the count the page shows is the
    screener's, never the model's;
  · the tool loop is append-only, ends, and a refusal or an API failure comes
    back as a sentence rather than a 500.
"""

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import fundamentals_query as Q  # noqa: E402
import query_assistant as A  # noqa: E402

BUILT = "2026-11-06T12:00:00+00:00"
ROWS = [
    {"symbol": "ACME", "name": "Acme Chemicals Ltd", "industry": "Chemicals",
     "sector": "Chemicals", "roce": 28.4, "roe": 21.2, "pe": 24.1,
     "market_cap": 12500.0, "debt_to_equity": 0.12},
    {"symbol": "BETA", "name": "Beta Pharma Ltd", "industry": "Pharmaceuticals",
     "sector": "Healthcare", "roce": 22.0, "roe": 17.5, "pe": 31.0,
     "market_cap": 38000.0, "debt_to_equity": 0.3},
    {"symbol": "GAMMA", "name": "Gamma Pharma Ltd", "industry": "Pharmaceuticals",
     "sector": "Healthcare", "roce": 9.0, "roe": -3.0, "pe": None,
     "market_cap": 640.0, "debt_to_equity": 1.4},
    {"symbol": "DELTA", "name": "Delta Infra Ltd", "industry": "Construction",
     "sector": "Construction", "roce": 26.0, "roe": None, "pe": None,
     "market_cap": None, "debt_to_equity": None},
]


@pytest.fixture(autouse=True)
def rows(monkeypatch):
    monkeypatch.setattr(A, "_rows", lambda: (ROWS, BUILT))
    A._asked.clear()
    yield
    A._asked.clear()


# ── A stand-in for the SDK ───────────────────────────────────────────────────

def text_block(obj):
    return SimpleNamespace(type="text", text=json.dumps(obj) if not isinstance(obj, str) else obj)


def tool_block(name, args, id_="tu_1"):
    return SimpleNamespace(type="tool_use", id=id_, name=name, input=args)


def reply(*blocks, stop="end_turn", model="claude-opus-5-5"):
    return SimpleNamespace(
        content=list(blocks), stop_reason=stop, model=model,
        usage=SimpleNamespace(input_tokens=100, output_tokens=20,
                              cache_read_input_tokens=0, cache_creation_input_tokens=0))


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        # A copy of the list as it stood: ask() keeps appending to it.
        self.calls.append(dict(kw, messages=list(kw["messages"])))
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def answer(**kw):
    out = {"reply": "Here you go.", "queries": [], "follow_ups": []}
    out.update(kw)
    return out


QUESTION = [{"role": "user", "content": "Companies with ROCE above 20?"}]


# ── What the model is told ───────────────────────────────────────────────────

def test_every_field_the_parser_knows_is_in_the_prompt():
    for _id, label, *_rest in Q.FIELDS:
        assert "- %s [" % label in A.SYSTEM, label


def test_the_prompt_is_the_same_on_every_request_so_the_cache_holds():
    assert A._build_system() == A.SYSTEM


@pytest.mark.parametrize("snippet", [
    "(Sales growth 3Y > 15 OR Profit growth 3Y > 20) AND PE < 30",
    "Market cap / Sales < 3",
    "Cash > Debt",
    'Industry contains "pharma"',
    "ROE > 15",
    "Market cap > 500",
])
def test_every_syntax_example_in_the_prompt_parses(snippet):
    assert snippet in A.SYSTEM
    Q.parse(snippet)


def test_the_tools_are_strict_and_have_closed_schemas():
    for t in A.TOOLS:
        assert t["strict"] is True
        schema = t["input_schema"]
        assert schema["additionalProperties"] is False
        assert set(schema["required"]) == set(schema["properties"])


# ── The tools run the screener's code ───────────────────────────────────────

def test_check_query_counts_with_the_real_parser():
    out = A.check_query("ROCE > 20")
    assert out["ok"] is True
    assert out["count"] == 3 and out["screened"] == 4
    assert [m["symbol"] for m in out["first_matches"]] == ["ACME", "DELTA", "BETA"]
    assert out["first_matches"][0]["ROCE"] == 28.4


def test_check_query_counts_a_missing_figure_as_unknown_not_a_fail():
    out = A.check_query("ROE > 10")
    assert out["count"] == 2 and out["unknown"] == 1


def test_check_query_hands_back_the_parsers_error_and_suggestion():
    out = A.check_query("ROEE > 15")
    assert out["ok"] is False
    assert "ROEE" in out["error"]
    assert "ROE" in out["suggestions"]


def test_check_query_still_validates_when_the_tables_are_down(monkeypatch):
    def down():
        raise RuntimeError("no tables")
    monkeypatch.setattr(A, "_rows", down)
    out = A.check_query("ROE > 15")
    assert out["ok"] is True and out["count"] is None
    assert A.check_query("ROEE > 15")["ok"] is False


def test_list_industries_narrows_by_a_word_and_counts():
    out = A.list_industries("pharma")
    assert out["industry_names"] == [{"name": "Pharmaceuticals", "companies": 2}]
    assert len(A.list_industries("")["industry_names"]) == 3


def test_a_tool_that_fails_is_an_error_result_not_a_crash(monkeypatch):
    monkeypatch.setattr(A, "list_industries", lambda contains="": 1 / 0)
    text, is_error = A._run_tool("list_industries", {"contains": ""})
    assert is_error and "failed" in text
    assert A._run_tool("rm_rf", {})[1] is True


# ── The conversation the page sends ──────────────────────────────────────────

@pytest.mark.parametrize("messages,words", [
    (None, "Ask a question"),
    ([], "Ask a question"),
    ([{"role": "system", "content": "hi"}], "role"),
    ([{"role": "user", "content": 5}], "string"),
    ([{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}], "last message"),
    ([{"role": "user", "content": "x" * 2001}], "under 2,000"),
])
def test_a_conversation_that_cannot_be_sent_is_refused_with_a_reason(messages, words):
    with pytest.raises(A.AskError) as e:
        A._clean_history(messages)
    assert words in str(e.value)


def test_a_long_conversation_keeps_its_latest_turns_and_starts_with_the_reader():
    msgs = []
    for i in range(20):
        msgs += [{"role": "user", "content": "q%d" % i}, {"role": "assistant", "content": "a%d" % i}]
    msgs.append({"role": "user", "content": "last"})
    turns = A._clean_history(msgs)
    assert len(turns) <= A.MAX_TURNS
    assert turns[0]["role"] == "user" and turns[-1]["content"] == "last"


# ── One question, end to end ─────────────────────────────────────────────────

def test_a_question_runs_the_tool_loop_and_the_counts_are_the_screeners():
    tool_turn = reply(tool_block("check_query", {"query": "ROCE > 20"}), stop="tool_use")
    client = FakeClient([
        tool_turn,
        reply(text_block(answer(
            reply="Three companies clear a 20% ROCE.",
            queries=[{"title": "High ROCE", "query": "ROCE > 20", "explanation": "Return on capital above 20%."}],
            follow_ups=["Add a debt limit"]))),
    ])
    out = A.ask(QUESTION, current_query="PE < 15", client=client)
    assert out["available"] is True
    assert out["reply"] == "Three companies clear a 20% ROCE."
    q = out["queries"][0]
    assert q["valid"] is True and q["count"] == 3 and q["screened"] == 4
    assert q["sample"] == ["ACME", "DELTA", "BETA"]
    assert out["follow_ups"] == ["Add a debt limit"]
    assert out["checks"] == 1
    assert out["usage"]["input_tokens"] == 200

    first, second = client.calls
    # What every request carries.
    for call in client.calls:
        assert call["model"] == A.MODEL
        assert call["system"] == A.SYSTEM and call["tools"] == A.TOOLS
        assert call["fallbacks"] == "default" and A.FALLBACK_BETA in call["betas"]
        assert call["output_config"]["format"]["schema"] == A.ANSWER_SCHEMA
        assert "tool_choice" not in call
    # The editor's query rides along with the question, as data.
    last = first["messages"][-1]["content"]
    assert last[0]["text"] == QUESTION[0]["content"]
    assert "<screener_state>" in last[1]["text"] and "PE < 15" in last[1]["text"]
    # Append-only: the second request starts with the first one's messages,
    # then the assistant turn as returned, then the tool result.
    assert second["messages"][:len(first["messages"])] == first["messages"]
    assistant, results = second["messages"][-2:]
    assert assistant == {"role": "assistant", "content": tool_turn.content}
    assert assistant["content"] is tool_turn.content     # unchanged, thinking and all
    assert results["role"] == "user"
    assert results["content"][0]["tool_use_id"] == "tu_1"
    assert json.loads(results["content"][0]["content"])["count"] == 3


def test_a_proposed_query_that_does_not_parse_is_marked_not_passed_off():
    client = FakeClient([reply(text_block(answer(queries=[
        {"title": "Typo", "query": "ROEE > 15", "explanation": "x"}])))])
    q = A.ask(QUESTION, client=client)["queries"][0]
    assert q["valid"] is False and "ROEE" in q["error"] and "ROE" in q["suggestions"]
    assert "count" not in q


def test_no_more_than_four_queries_are_shown():
    many = [{"title": str(i), "query": "ROE > %d" % i, "explanation": ""} for i in range(9)]
    out = A.ask(QUESTION, client=FakeClient([reply(text_block(answer(queries=many)))]))
    assert len(out["queries"]) == A.MAX_QUERIES


def test_the_loop_ends_and_the_last_call_may_not_use_tools():
    loop = [reply(tool_block("check_query", {"query": "ROE > 1"}), stop="tool_use")
            for _ in range(A.MAX_STEPS - 1)]
    client = FakeClient(loop + [reply(text_block(answer()))])
    out = A.ask(QUESTION, client=client)
    assert out["available"] is True
    assert len(client.calls) == A.MAX_STEPS
    assert client.calls[-1]["tool_choice"] == {"type": "none"}
    assert all("tool_choice" not in c for c in client.calls[:-1])


def test_past_the_time_budget_the_next_call_must_answer_and_the_loop_stops(monkeypatch):
    monkeypatch.setattr(A, "BUDGET_SECONDS", -1)
    client = FakeClient([reply(tool_block("check_query", {"query": "ROE > 1"}), stop="tool_use")])
    out = A.ask(QUESTION, client=client)
    assert len(client.calls) == 1
    assert client.calls[0]["tool_choice"] == {"type": "none"}
    assert out["available"] is False and out["reason"] == "empty"


def test_a_refusal_is_said_in_words():
    out = A.ask(QUESTION, client=FakeClient([reply(stop="refusal")]))
    assert out == {"available": False, "reason": "refused", "message": out["message"]}
    assert "declined" in out["message"]


def test_an_api_failure_is_a_sentence_not_a_500():
    out = A.ask(QUESTION, client=FakeClient([RuntimeError("boom")]))
    assert out["available"] is False and "boom" in out["message"]


def test_an_answer_cut_off_at_the_length_limit_is_not_shown_half_parsed():
    out = A.ask(QUESTION, client=FakeClient([reply(text_block('{"reply": "Part'), stop="max_tokens")]))
    assert out["reason"] == "too_long"


def test_text_that_is_not_json_is_still_shown_as_the_reply():
    out = A.ask(QUESTION, client=FakeClient([reply(text_block("Just words."))]))
    assert out["reply"] == "Just words." and out["queries"] == []


def test_with_no_api_key_nothing_is_called_and_the_payload_says_why(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(A, "_client", lambda: pytest.fail("must not build a client"))
    out = A.ask(QUESTION)
    assert out["available"] is False and out["reason"] == "not_configured"
    assert "ANTHROPIC_API_KEY" in out["message"]


def test_the_hourly_ceiling_stops_questions_before_they_are_billed(monkeypatch):
    monkeypatch.setattr(A, "HOURLY_LIMIT", 1)
    assert A.ask(QUESTION, client=FakeClient([reply(text_block(answer()))]))["available"]
    client = FakeClient([])
    out = A.ask(QUESTION, client=client)
    assert out["reason"] == "hourly_limit" and client.calls == []


# ── The routes ───────────────────────────────────────────────────────────────

@pytest.fixture
def api(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import query_ai_routes
    app = FastAPI()
    app.include_router(query_ai_routes.router)
    return TestClient(app)


def test_the_routes_are_closed_when_no_admin_key_is_configured(api, monkeypatch):
    monkeypatch.delenv("ADMIN_KEY", raising=False)
    assert api.get("/admin/query/ai").status_code == 401
    assert api.get("/admin/query/ai", headers={"X-Admin-Key": ""}).status_code == 401
    assert api.post("/admin/query/ai", json={"messages": QUESTION}).status_code == 401


def test_the_routes_need_the_right_key(api, monkeypatch):
    monkeypatch.setenv("ADMIN_KEY", "s3cret")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert api.get("/admin/query/ai", headers={"X-Admin-Key": "nope"}).status_code == 401
    r = api.get("/admin/query/ai", headers={"X-Admin-Key": "s3cret"})
    assert r.status_code == 200 and r.json()["reason"] == "not_configured"


def test_a_question_goes_through_with_the_key_and_a_bad_body_is_a_400(api, monkeypatch):
    monkeypatch.setenv("ADMIN_KEY", "s3cret")
    seen = {}

    def fake_ask(messages, current_query="", current_error=""):
        seen.update(messages=messages, query=current_query, error=current_error)
        return {"available": True, "reply": "ok", "queries": [], "follow_ups": []}

    monkeypatch.setattr(A, "ask", fake_ask)
    h = {"X-Admin-Key": "s3cret"}
    r = api.post("/admin/query/ai", headers=h,
                 json={"messages": QUESTION, "query": "ROE > 15", "error": ""})
    assert r.status_code == 200 and r.json()["reply"] == "ok"
    assert seen == {"messages": QUESTION, "query": "ROE > 15", "error": ""}

    monkeypatch.setattr(A, "ask", lambda *a, **k: (_ for _ in ()).throw(A.AskError("Ask a question first.")))
    r = api.post("/admin/query/ai", headers=h)
    assert r.status_code == 400 and "Ask a question" in r.json()["detail"]
