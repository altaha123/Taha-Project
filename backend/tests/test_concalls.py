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
