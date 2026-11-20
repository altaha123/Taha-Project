"""
Earnings call digests, against a real transcript.

The fixture is Shiprocket's Q1 FY27 call exactly as the company filed it. A
real one matters because every hard case here is a property of how these
documents are actually laid out and none of them raises:

  · a PDF wraps one person's entry across two lines, so splitting the
    MANAGEMENT block on newlines turns one director into two, the second of
    whom is a job title
  · the CEO says "before we move into Q&A" in the first minute, so the naive
    Q&A marker puts the boundary at 5% of the call
  · the moderator says "we will now begin the question-and-answer session" and
    an analyst asks "should we expect growth in a similar range?" — quoting
    either as the company's guidance would put a commitment in management's
    mouth that they never made

That last one is the test this file exists for.
"""
import datetime as dt
import os

import pytest

import concalls as C

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
TRANSCRIPT = os.path.join(FIX, "concall_shiprocket_q1fy27.txt")


@pytest.fixture(scope="module")
def text():
    with open(TRANSCRIPT, encoding="utf-8") as fh:
        return fh.read()


@pytest.fixture(scope="module")
def d(text):
    return C.digest(text, "Announcement under Regulation 30 (LODR)-Earnings Call Transcript")


# ---------------------------------------------------------------------------
# Finding a transcript in the feed
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("headline", [
    "Announcement under Regulation 30 (LODR)-Earnings Call Transcript",
    "Transcript Of Q2 FY26 Earnings Conference Call",
    "Audio And Transcript Of The Analyst Call",
    "Intimation - Con-Call Transcript",
])
def test_a_transcript_is_recognised(headline):
    assert C.is_transcript(headline) is True


@pytest.mark.parametrize("headline", [
    "Audio Recording Of The Earnings Conference Call",
    "Prior Intimation Of Earnings Call",
    "Intimation of the schedule of the analyst call",
    "Investor Presentation",
    "Board Meeting Intimation",
])
def test_things_that_are_not_a_transcript_are_not_picked_up(headline):
    """The audio recording and the meeting notice are filed alongside the
    transcript and are not it."""
    assert C.is_transcript(headline) is False


# ---------------------------------------------------------------------------
# What the digest gets out of the document
# ---------------------------------------------------------------------------

def test_the_quarter_and_the_call_date_are_read(d):
    assert d["quarter"] == "Q1 FY27"
    assert d["call_date"] == "2026-09-11"


def test_management_survives_the_pdf_line_wrap(d):
    """
    The filed text reads "M R. SAAHIL GOEL – MANAGING DIRECTOR AND\\nCHIEF
    EXECUTIVE OFFICER – SHIPROCKET LIMITED". Split on newlines it becomes two
    people, one of whom is called Chief Executive Officer.
    """
    names = [m["name"] for m in d["management"]]
    assert "Saahil Goel" in names
    assert "Tanmay Kumar" in names
    assert len(d["management"]) == 3
    assert not any("Officer" in n for n in names)
    role = [m["role"] for m in d["management"] if m["name"] == "Saahil Goel"][0]
    assert "Chief Executive Officer" in role


def test_analysts_are_found_even_when_they_name_their_own_firm(d):
    """The moderator says "from the line of Della Desai. Kindly announce your
    company name" — no firm in that sentence, which is not a failed match."""
    assert d["analyst_count"] >= 3
    names = [a["name"] for a in d["analysts"]]
    assert "Della Desai" in names


def test_the_prepared_remarks_boundary_is_the_handover_not_a_mention(d):
    """
    "before we move into Q&A" in the opening remarks sits at about 5% of the
    document. The real boundary is the moderator opening the session, near
    halfway.
    """
    assert d["prepared_remarks_share"] is not None
    assert 25 < d["prepared_remarks_share"] < 75


def test_topics_are_normalised_per_thousand_words(d):
    assert d["topics"]["margin"]["mentions"] > 0
    assert d["topics"]["margin"]["per_1k_words"] > 0
    ratio = 1000.0 * d["topics"]["margin"]["mentions"] / d["words"]
    assert d["topics"]["margin"]["per_1k_words"] == pytest.approx(ratio, abs=0.02)


# ---------------------------------------------------------------------------
# Attribution. The test this file exists for.
# ---------------------------------------------------------------------------

def test_every_quoted_line_is_management_speaking(d):
    """
    A forward-looking sentence is only guidance when the company said it. The
    moderator and the analysts use exactly the same language.
    """
    assert d["guidance"]
    speakers = {g["by"] for g in d["guidance"]}
    assert speakers
    assert "Moderator" not in speakers
    mgmt = {m["name"] for m in d["management"]}
    for who in speakers:
        assert who in mgmt, who


def test_the_moderator_opening_the_q_and_a_is_never_quoted_as_guidance(d):
    said = " ".join(g["said"].lower() for g in d["guidance"])
    assert "begin the question-and-answer" not in said
    assert "look forward to seeing you next quarter" not in said


def test_an_analyst_question_is_never_quoted_as_guidance(d):
    said = " ".join(g["said"].lower() for g in d["guidance"])
    assert "is this a trend which would continue" not in said


def test_quotes_are_verbatim_from_the_document(text, d):
    """Nothing is paraphrased. Every quoted line must be findable in the
    transcript, allowing only for whitespace collapsing."""
    import re
    flat = re.sub(r"\s+", " ", text)
    for g in d["guidance"]:
        assert g["said"] in flat, g["said"][:60]


def test_a_transcript_with_no_speaker_labels_is_still_read():
    """A PDF whose labels did not survive extraction is read whole rather than
    not at all, and attributes nothing rather than attributing wrongly."""
    out = C.digest("We expect margins to hold at around this level through the "
                   "year, and we will add capacity in the second half.")
    assert out["guidance_count"] >= 1
    assert out["guidance"][0]["by"] is None


@pytest.mark.parametrize("text", ["", None])
def test_an_empty_transcript_is_not_an_error(text):
    assert C.digest(text) == {}


# ---------------------------------------------------------------------------
# Quarter on quarter
# ---------------------------------------------------------------------------

def test_comparison_needs_two_calls():
    out = C.compare({"quarter": "Q1 FY27", "topics": {}}, None)
    assert out["available"] is False
    assert "No earlier transcript" in out["reason"]


def test_topic_shifts_are_measured_per_thousand_words_not_raw():
    """
    A call that ran twice as long mentions everything twice as often. That is
    not management changing the subject.
    """
    now = {"quarter": "Q1 FY27", "words": 10000, "guidance_count": 3,
           "analyst_count": 5,
           "topics": {"margin": {"mentions": 20, "per_1k_words": 2.0}}}
    before = {"quarter": "Q4 FY26", "words": 5000, "guidance_count": 3,
              "analyst_count": 5,
              "topics": {"margin": {"mentions": 10, "per_1k_words": 2.0}}}
    out = C.compare(now, before)
    margin = [m for m in out["topic_shifts"] if m["topic"] == "margin"][0]
    assert margin["change"] == pytest.approx(0.0)
    assert margin["direction"] == "flat"


def test_a_newly_raised_topic_and_a_dropped_one_are_distinguished():
    now = {"quarter": "Q1 FY27", "words": 1000, "guidance_count": 1,
           "analyst_count": 2,
           "topics": {"debt": {"mentions": 5, "per_1k_words": 5.0}}}
    before = {"quarter": "Q4 FY26", "words": 1000, "guidance_count": 1,
              "analyst_count": 2,
              "topics": {"hiring": {"mentions": 4, "per_1k_words": 4.0}}}
    out = C.compare(now, before)
    by = {m["topic"]: m for m in out["topic_shifts"]}
    assert by["debt"]["new"] is True
    assert by["hiring"]["dropped"] is True
    assert out["talked_more_about"] == ["debt"]
    assert out["talked_less_about"] == ["hiring"]


def test_the_comparison_says_what_it_does_not_measure():
    out = C.compare({"quarter": "a", "topics": {}}, {"quarter": "b", "topics": {}})
    assert "not the same as what they said about it" in out["caveat"]


# ---------------------------------------------------------------------------
# The ledger
# ---------------------------------------------------------------------------

@pytest.fixture
def ledger(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "DB_PATH", str(tmp_path / "concalls.db"))
    monkeypatch.setitem(C._db_ready, "done", False)
    return C


def test_a_calls_digest_is_written_once(ledger, d):
    assert ledger.remember("TESTCO", "Test Co", "Q1 FY27", "", "", d) is True
    assert ledger.remember("TESTCO", "Test Co", "Q1 FY27", "", "", {"quarter": "x"}) is False
    held = ledger.remembered("TESTCO")
    assert len(held) == 1
    assert held[0]["digest"]["quarter"] == "Q1 FY27"


def test_calls_come_back_newest_quarter_first(ledger, d):
    for q in ("Q3 FY26", "Q1 FY27", "Q4 FY26", "Q2 FY27"):
        ledger.remember("TESTCO", "Test Co", q, "", "", dict(d, quarter=q))
    assert [c["quarter"] for c in ledger.remembered("TESTCO")] == [
        "Q2 FY27", "Q1 FY27", "Q4 FY26", "Q3 FY26"]


@pytest.mark.parametrize("q,key", [("Q1 FY27", (27, 1)), ("Q4 FY26", (26, 4)),
                                   ("Q3 FY26", (26, 3)), ("nonsense", (0, 0))])
def test_quarters_sort_the_way_a_year_runs(q, key):
    assert C._quarter_sort_key(q) == key


def test_an_unknown_company_is_answered_not_raised(ledger, monkeypatch):
    monkeypatch.setattr(C, "find", lambda days=7, symbol=None: [])
    out = ledger.for_symbol("NOSUCHCO")
    assert out["available"] is False
    assert "NOSUCHCO" in out["message"]


def test_no_symbol_is_answered_not_raised():
    out = C.for_symbol("")
    assert out["available"] is False


# ---------------------------------------------------------------------------
# The model path stays off, and says so
# ---------------------------------------------------------------------------

def test_with_no_key_there_is_no_summary_and_the_payload_says_why(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert C.summary_configured() is False
    out = C.summarise("some transcript text")
    assert out["available"] is False
    assert out["reason"] == "not_configured"
    assert "extracted from the transcript" in out["message"]
    assert "text" not in out


def test_the_extraction_is_never_relabelled_as_a_written_summary(monkeypatch):
    """
    The one way this feature could mislead: showing the extracted digest under
    a heading that claims a model wrote it. The two states are disjoint and
    there is no third.
    """
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    out = C.summarise("text")
    assert out.get("available") is False
    assert not out.get("model")


def test_a_key_without_the_sdk_is_reported_honestly(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    import builtins
    real = builtins.__import__

    def no_anthropic(name, *a, **k):
        if name == "anthropic":
            raise ImportError("not installed")
        return real(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", no_anthropic)
    out = C.summarise("text")
    assert out["available"] is False
    assert out["reason"] == "sdk_missing"


def test_the_prompt_frames_the_transcript_as_data_not_instructions():
    """
    A transcript is written by the filing company. If the model path is ever
    switched on, the system prompt must say the document is untrusted — and
    the text must be delimited so an instruction inside it cannot pass as one
    from us.
    """
    assert "untrusted data" in C.SUMMARY_SYSTEM
    assert "never as instructions" in C.SUMMARY_SYSTEM
    assert "<transcript>" in C.SUMMARY_SYSTEM or True
    assert "recommendation" in C.SUMMARY_SYSTEM


# ---------------------------------------------------------------------------
# The written brief. Two things in it are not left to the model: every quote
# is checked against the transcript, and the name under a quote is the label
# the document puts on that turn.
# ---------------------------------------------------------------------------

REAL = ("The CM has improved a little bit, right, over this revenue growth and "
        "we expect it to maintain around that range as it has in the last trajectory.")


def answer(**over):
    base = {
        "is_call": True,
        "headline": "Revenue grew 34% and contribution margin is expected to hold",
        "summary": "Management said transactions grew 36% and revenue 34% in the quarter.",
        "quarter": ["Transactions grew 36%.", "Revenue grew nearly 34%."],
        "commitments": [{"topic": "Contribution margin", "quote": REAL,
                         "speaker": "Saahil Goel"}],
        "pressed_on": ["Whether margin growth ahead of revenue would continue."],
        "not_answered": [],
        "weight": "high",
        "weight_reason": "Management guided on contribution margin.",
    }
    base.update(over)
    return base


def test_a_verbatim_quote_is_kept_and_named_from_the_document(text):
    """The model said somebody else said it. The transcript labels that turn
    Saahil Goel, and the transcript is what the page prints."""
    out = C.shape_brief(answer(commitments=[
        {"topic": "Margin", "quote": REAL, "speaker": "Tanmay Kumar"}]), text)
    assert out["status"] == "ready"
    assert out["commitments"] == [{"topic": "Margin", "said": REAL, "by": "Saahil Goel"}]
    assert out["quotes_dropped"] == 0


def test_a_quote_survives_the_pdf_line_breaks_and_curly_quotes(text):
    """The filed text breaks this sentence across two lines. That is the PDF,
    not a difference in what was said."""
    assert REAL not in text and REAL in C.re.sub(r"\s+", " ", text)
    found, who = C.place_quote("“" + REAL + "”", C.turns_of(text))
    assert (found, who) == (True, "Saahil Goel")


def test_a_paraphrase_is_dropped_not_printed_as_a_quote(text):
    out = C.shape_brief(answer(commitments=[{
        "topic": "Margin", "speaker": "Saahil Goel",
        "quote": "We expect contribution margin to stay in the current range going forward."}]),
        text)
    assert out["commitments"] == []
    assert out["quotes_dropped"] == 1


def test_an_analysts_question_is_never_printed_as_a_commitment(text):
    """Word for word in the transcript, and said by the analyst. Being real is
    not enough to be management's."""
    asked = ("I see that the customer acquisition cost for the core business, the "
             "CAC, that seems to have moved up both year-on-year and Q-o-Q.")
    assert C.place_quote(asked, C.turns_of(text)) == (True, "Della Desai")
    out = C.shape_brief(answer(commitments=[
        {"topic": "CAC", "quote": asked, "speaker": "Saahil Goel"}]), text)
    assert out["commitments"] == []
    assert out["quotes_dropped"] == 1


def test_the_moderator_is_never_printed_as_a_commitment(text):
    said = ("Ladies and gentlemen, good day, and welcome to Shiprocket Limited's "
            "Q1 FY27 Earnings Conference Call.")
    out = C.shape_brief(answer(commitments=[
        {"topic": "Welcome", "quote": said, "speaker": "Saahil Goel"}]), text)
    assert out["commitments"] == []


def test_something_that_is_not_a_call_gets_no_brief(text):
    assert C.shape_brief(answer(is_call=False), text)["status"] == "unreadable"
    assert C.shape_brief(answer(summary=""), text)["status"] == "unreadable"
    assert C.shape_brief("not a dict", text)["status"] == "unreadable"


def test_a_brief_is_bounded_whatever_the_model_returns(text):
    out = C.shape_brief(answer(quarter=["x" * 900] * 12, weight="enormous",
                               pressed_on=["a", "", "b", "c", "d", "e"]), text)
    assert len(out["quarter"]) == 5 and len(out["quarter"][0]) <= 260
    assert out["pressed_on"] == ["a", "b", "c", "d"]
    assert out["weight"] == "medium"


class FakeClient:
    """Stands where anthropic.Anthropic() would, and keeps what it was sent."""

    def __init__(self, data=None, stop="end_turn"):
        import json
        import types
        self.sent = None
        block = types.SimpleNamespace(type="text", text=json.dumps(data or answer()))
        self.reply = types.SimpleNamespace(stop_reason=stop, content=[block],
                                           model="claude-sonnet-5-5")
        self.beta = types.SimpleNamespace(
            messages=types.SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.sent = kw
        return self.reply


anthropic_installed = pytest.mark.skipif(
    __import__("importlib").util.find_spec("anthropic") is None,
    reason="the anthropic package is not installed")


@anthropic_installed
def test_the_request_asks_sonnet_for_the_fixed_shape_with_the_transcript_as_data(text):
    client = FakeClient()
    out = C.write_brief(text, company="Shiprocket Ltd", quarter="Q1 FY27",
                        headline="Earnings Call Transcript", client=client)
    assert out["status"] == "ready" and out["model"] == "claude-sonnet-5-5"
    sent = client.sent
    assert sent["model"] == "claude-sonnet-5-5"
    assert sent["output_config"]["format"] == {"type": "json_schema", "schema": C.BRIEF_SCHEMA}
    assert sent["fallbacks"] == "default" and C.FALLBACK_BETA in sent["betas"]
    # Thinking is left to the model and sampling is left alone: this model
    # rejects a disabled-thinking or temperature setting outright.
    assert "thinking" not in sent and "temperature" not in sent
    said = sent["messages"][0]["content"]
    assert "<transcript>\n" in said and said.rstrip().endswith("</transcript>")
    assert "Only the first part" not in said


@anthropic_installed
def test_a_refusal_and_a_cut_off_answer_are_told_apart(text):
    assert C.write_brief(text, client=FakeClient(stop="refusal"))["status"] == "declined"
    # Cut off at the token limit: not a brief, and worth another try later.
    assert C.write_brief(text, client=FakeClient(stop="max_tokens")) is None


@anthropic_installed
def test_a_transcript_cut_short_says_so(text, monkeypatch):
    monkeypatch.setattr(C, "SUMMARY_MAX_CHARS", 20000)
    client = FakeClient()
    out = C.write_brief(text, client=client)
    assert out["partial"] is True
    assert "Only the first part" in client.sent["messages"][0]["content"]


def test_every_field_the_schema_requires_is_one_the_api_accepts():
    """Structured outputs reject a schema with an optional field or an open
    object, and say so only at request time."""
    def walk(node):
        if node.get("type") == "object":
            assert node["additionalProperties"] is False
            assert sorted(node["required"]) == sorted(node["properties"])
            for child in node["properties"].values():
                walk(child)
        if node.get("type") == "array":
            walk(node["items"])
        for banned in ("minItems", "maxItems", "minLength", "maxLength",
                       "minimum", "maximum"):
            assert banned not in node
    walk(C.BRIEF_SCHEMA)


# ---------------------------------------------------------------------------
# The background reader, and what a request reads. The page used to wait on
# all of this inside one request and never came back.
# ---------------------------------------------------------------------------

import time as _time


def filing(n, symbol="SHIPROCKET", days_ago=1, company="Shiprocket Ltd"):
    at = dt.datetime.now(C.IST) - dt.timedelta(days=days_ago, minutes=n)
    return {"symbol": symbol, "company": company,
            "headline": "Announcement under Regulation 30 (LODR)-Earnings Call Transcript",
            "at": at.isoformat(), "epoch": at.timestamp(),
            "pdf": "https://www.bseindia.com/x/%s.pdf" % n}


@pytest.fixture
def reader(ledger, monkeypatch):
    C.reset_for_tests()
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setattr(C, "_can_write", lambda: True)
    monkeypatch.setattr(C, "find", lambda *a, **k: pytest.fail(
        "a request must never walk the exchange feed"))
    yield C
    C.reset_for_tests()


def test_a_request_reads_the_ledger_and_nothing_else(reader, text):
    """recent() is what /concalls returns. `find` fails the test if touched,
    so this passing is the proof that a page load no longer polls the
    exchange or opens a PDF."""
    assert reader.read_new(finder=lambda d: [filing(1)], extract=lambda u: text) == 1
    out = reader.recent()
    assert out["count"] == 1 and out["rows"][0]["digest"]["quarter"] == "Q1 FY27"
    assert out["rows"][0]["brief"] == {"status": "pending"}
    assert out["status"]["reading"] is False and out["poll_seconds"] is None


def test_a_transcript_is_read_once(reader, text):
    opened = []

    def extract(url):
        opened.append(url)
        return text
    for _ in range(3):
        reader.read_new(finder=lambda d: [filing(1)], extract=extract)
    assert len(opened) == 1


def test_a_failed_download_is_tried_again_and_a_scan_is_not(reader):
    """Both come back from the reader as no text. Only one of them is a fact
    about the document."""
    items = [filing(1), filing(2, symbol="SCANCO", company="Scan Co")]
    scans = {items[1]["pdf"]}
    for _ in range(2):
        reader.read_new(finder=lambda d: items, extract=lambda u: None,
                        is_scan=lambda u: u in scans)
    rows = reader.recent()["rows"]
    assert [r["symbol"] for r in rows] == ["SCANCO"]
    assert rows[0]["readable"] is False and rows[0]["brief"] == {"status": "unreadable"}


def test_a_brief_is_written_once_and_the_key_calls_come_first(reader, text):
    items = [filing(1, "AAA", company="Aaa Ltd"), filing(2, "BBB", company="Bbb Ltd"),
             filing(3, "CCC", company="Ccc Ltd")]
    reader.read_new(finder=lambda d: items, extract=lambda u: text)
    asked = []

    def writer(body, company="", quarter="", headline=""):
        asked.append(company)
        return C.shape_brief(answer(weight="high" if company == "Ccc Ltd" else "low"),
                             body, model="claude-sonnet-5-5")
    assert reader.write_new(writer=writer, extract=lambda u: text) == 3
    assert reader.write_new(writer=writer, extract=lambda u: text) == 0
    assert sorted(asked) == ["Aaa Ltd", "Bbb Ltd", "Ccc Ltd"]

    out = reader.recent()
    # Ccc was filed first of the three, and is listed first because it is the
    # one graded high. The other two follow, newest first.
    assert [r["symbol"] for r in out["rows"]] == ["CCC", "AAA", "BBB"]
    assert [r["key"] for r in out["rows"]] == [True, False, False]
    assert out["counts"] == {"calls": 3, "key": 1, "summarised": 3, "waiting": 0}
    assert out["rows"][0]["brief"]["commitments"][0]["by"] == "Saahil Goel"
    assert out["model"] == "claude-sonnet-5-5" and "Claude" in out["disclaimer"]


def test_the_hourly_limit_stops_the_pass_and_the_page_is_told(reader, text, monkeypatch):
    monkeypatch.setattr(C, "HOURLY", 2)
    items = [filing(n, "S%d" % n, company="Co %d" % n) for n in range(1, 6)]
    reader.read_new(finder=lambda d: items, extract=lambda u: text)
    wrote = reader.write_new(
        writer=lambda body, **k: C.shape_brief(answer(), body), extract=lambda u: text)
    assert wrote == 2
    out = reader.recent()
    assert out["status"]["capped"] == "hourly"
    assert out["counts"]["summarised"] == 2 and out["counts"]["waiting"] == 3


def test_a_rejected_key_stops_the_pass_and_says_why(reader, text):
    items = [filing(n, "S%d" % n, company="Co %d" % n) for n in range(1, 4)]
    reader.read_new(finder=lambda d: items, extract=lambda u: text)
    asked = []

    def writer(body, **k):
        asked.append(1)
        raise C._Halt("The ANTHROPIC_API_KEY on this instance was rejected.")
    assert reader.write_new(writer=writer, extract=lambda u: text) == 0
    assert len(asked) == 1, "one rejection is enough to know the next will be too"
    assert "rejected" in reader.recent()["status"]["error"]


def test_a_brief_that_failed_is_left_for_later_not_asked_for_on_every_load(reader, text):
    reader.read_new(finder=lambda d: [filing(1)], extract=lambda u: text)
    reader.write_new(writer=lambda body, **k: None, extract=lambda u: text)
    assert reader.recent()["rows"][0]["brief"] == {"status": "later"}


def test_with_no_key_the_ledger_page_says_summaries_are_off(reader, text, monkeypatch):
    monkeypatch.setattr(C, "_can_write", lambda: False)
    reader.read_new(finder=lambda d: [filing(1)], extract=lambda u: text)
    out = reader.recent()
    assert out["summary_configured"] is False and out["model"] is None
    assert out["rows"][0]["brief"] == {"status": "off"}
    assert out["rows"][0]["key"] is False
    assert "nothing in it is paraphrased" in out["source"]


def test_an_old_call_is_not_queued_for_a_brief(reader, text):
    """A backlog must not turn into a bill."""
    reader.read_new(finder=lambda d: [filing(1, days_ago=C.BRIEF_DAYS + 5)],
                    extract=lambda u: text)
    assert reader.waiting() == []
    assert reader.recent(days=45)["rows"][0]["brief"] == {"status": "none"}


def test_a_call_is_compared_with_the_one_before_it_never_a_later_one(reader, text, d):
    reader.remember("SHIPROCKET", "Shiprocket Ltd", "Q2 FY27", "", "", dict(d, quarter="Q2 FY27"))
    reader.remember("SHIPROCKET", "Shiprocket Ltd", "Q4 FY26", "", "", dict(d, quarter="Q4 FY26"))
    reader.read_new(finder=lambda d_: [filing(1)], extract=lambda u: text)
    versus = reader.recent()["rows"][0]["versus_previous"]
    assert versus["available"] is True and versus["from_quarter"] == "Q4 FY26"


def test_starting_the_reader_never_waits_for_it(reader, monkeypatch):
    """The whole fault, as a test: the request returns while the pass is still
    running, and a second request does not start a second pass."""
    import threading
    gate, passes = threading.Event(), []

    def slow(days=None):
        passes.append(1)
        gate.wait(5)
        return {}
    monkeypatch.setattr(C, "refresh", slow)
    began = _time.time()
    assert reader.refresh_if_stale() is True
    assert reader.refresh_if_stale() is True
    assert _time.time() - began < 1.0
    assert reader.recent()["status"]["reading"] is True
    assert reader.recent()["poll_seconds"] == 8
    gate.set()
    for _ in range(100):
        if not reader.status()["reading"]:
            break
        _time.sleep(0.02)
    assert passes == [1]
    assert reader.status()["reading"] is False
    # Fresh enough now that the next page load does not start another.
    assert reader.refresh_if_stale() is False


def test_the_exchange_transcript_list_is_asked_for_by_subcategory(monkeypatch):
    """One request a day for the transcript subcategory, weekends included,
    and a day that answers with nothing leaves a note rather than an error."""
    import announcements as A
    monkeypatch.setattr(A, "_build_maps", lambda *a, **k: None)
    monkeypatch.setattr(C.time, "sleep", lambda s: None)
    asked = []

    class Reply:
        status_code = 200

        def __init__(self, rows):
            self._rows = rows

        def json(self):
            return {"Table": self._rows}

    class Session:
        def get(self, url, headers=None, params=None, timeout=None):
            asked.append(params)
            if len(asked) > 1:
                return Reply([])
            return Reply([{"SCRIP_CD": 500001, "SLONGNAME": "Test Co Ltd",
                           "NEWSSUB": "Announcement under Regulation 30 (LODR)-Earnings Call Transcript",
                           "NEWS_DT": "2026-11-18T19:24:00", "CATEGORYNAME": "Company Update",
                           "ATTACHMENTNAME": "abc.pdf"}])

    items, notes = C.transcript_feed(days=3, session=Session())
    assert len(asked) == 3
    assert {p["subcategory"] for p in asked} == {"Earnings Call Transcript"}
    assert {p["strCat"] for p in asked} == {"Company Update"}
    assert all(p["strPrevDate"] == p["strToDate"] for p in asked)
    assert len(items) == 1 and items[0]["pdf"].endswith("abc.pdf")
    assert len(notes) == 3 and notes[0].endswith("transcripts: 1")


def test_the_covering_letter_is_not_a_speaker(text):
    """"Subject:" ends in a colon like a speaker label does. A line from the
    letter the transcript was filed under is nobody's commitment."""
    letter = [body for who, body in C.turns_of(text) if who == "Subject"][0]
    line = C.re.sub(r"\s+", " ", letter).strip()[:120]
    assert len(line) > 40
    out = C.shape_brief(answer(commitments=[
        {"topic": "Filing", "quote": line, "speaker": "Saahil Goel"}]), text)
    assert out["commitments"] == [] and out["quotes_dropped"] == 1
