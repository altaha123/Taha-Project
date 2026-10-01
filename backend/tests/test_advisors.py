"""
Advisors: who gets listed, who can say what, and who can see what.

The failures worth testing for here are the quiet ones. An unverified number
listed as SEBI-registered looks exactly like a verified one. A reader's email
leaking into the adviser's view looks like nothing at all. An educator's buy
call reads like any other message. A portfolio shown to somebody after the
reader withdrew it is invisible to the reader. None of these crash; every
one of them is the thing the feature promises not to do.

Handlers are called directly, as test_account_endpoints.py does: calling the
handler runs the same code, and avoids TestClient's worker threads holding
connections to another test's database.
"""
import json
import os
import tempfile

import pytest
from fastapi import BackgroundTasks, HTTPException

import accounts
import advisors as A


@pytest.fixture(autouse=True)
def fresh_db(monkeypatch):
    with tempfile.TemporaryDirectory() as d:
        accounts.reset_for_tests(os.path.join(d, "accounts.db"))
        monkeypatch.delenv("ADMIN_KEY", raising=False)
        yield
        accounts.reset_for_tests(os.path.join(d, "accounts.db"))


@pytest.fixture(scope="module")
def routes():
    import advisor_routes
    return advisor_routes


def person(email):
    done = accounts.complete_login(accounts.start_login(email)["token"])
    return done["session"], accounts.user_for_session(done["session"])


RIA = {"display_name": "Asha Rao", "headline": "Fee-only adviser for salaried families",
       "bio": "Fifteen years of helping households plan for school fees, homes and retirement.",
       "kind": "ria", "sebi_reg": "INA000012345", "topics": ["portfolio", "retirement"],
       "languages": ["English", "Hindi"], "experience_years": 15,
       "links": ["https://example.com/asha"]}
RA = dict(RIA, display_name="Vikram Shah", kind="ra", sebi_reg="INH000004321",
          topics=["stocks"], headline="Research analyst covering banks and NBFCs")
EDU = dict(RIA, display_name="Meera Iyer", kind="educator", sebi_reg="",
           topics=["learning", "ama"], headline="Author and long-time value investor")


def listed(profile, email):
    """An approved profile, and the session of the person behind it."""
    tok, u = person(email)
    mine = A.save_profile(u["id"], profile)
    A.review(mine["id"], "approve")
    return tok, u, A.my_profile(u["id"])


# ── Registration ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("change,why", [
    ({"sebi_reg": ""}, "registration number"),
    ({"sebi_reg": "INH000012345"}, "INA followed by nine digits"),
    ({"sebi_reg": "INA12345"}, "INA followed by nine digits"),
    ({"kind": "educator"}, "without a registration number"),
    ({"kind": "planner"}, "Choose what you are"),
    ({"topics": []}, "at least one topic"),
    ({"languages": ["<script>"]}, "does not look like a language"),
    ({"links": ["http://insecure.example.com"]}, "https://"),
    ({"bio": "Too short."}, "at least 40"),
])
def test_an_application_that_is_not_right_is_refused_with_a_reason(change, why):
    _, u = person("applicant@example.com")
    with pytest.raises(ValueError, match=why):
        A.save_profile(u["id"], dict(RIA, **change))


@pytest.mark.parametrize("change,why", [
    ({"bio": "Call me on 98765 43210 for a free consultation about your goals."}, "phone number"),
    ({"links": ["https://wa.me/919876543210"]}, "phone number|WhatsApp"),
    ({"links": ["https://t.me/asha_calls"]}, "WhatsApp or Telegram"),
    ({"headline": "Write to asha.rao@gmail.com for tips"}, "email address"),
    ({"bio": "My model portfolio gives guaranteed returns of 24% a year, every year."}, "promise returns"),
])
def test_a_profile_is_held_to_the_same_rules_as_a_message(change, why):
    _, u = person("applicant@example.com")
    with pytest.raises(ValueError, match=why):
        A.save_profile(u["id"], dict(RIA, **change))


def test_portfolio_review_is_for_registered_investment_advisers_only():
    _, u = person("ra@example.com")
    with pytest.raises(ValueError, match="investment advisers only"):
        A.save_profile(u["id"], dict(RA, topics=["portfolio", "stocks"]))
    with pytest.raises(ValueError, match="investment advisers only"):
        A.save_profile(u["id"], dict(EDU, topics=["portfolio"]))


def test_a_registration_number_is_normalised_and_languages_can_be_any_script():
    _, u = person("asha@example.com")
    saved = A.save_profile(u["id"], dict(RIA, sebi_reg=" ina-000 012 345 ",
                                         languages=["English", "हिन्दी", "english"]))
    assert saved["sebi_reg"] == "INA000012345"
    assert saved["languages"] == ["English", "हिन्दी"]
    assert saved["status"] == "pending"


def test_nobody_is_listed_until_the_owner_has_checked_them():
    _, u = person("asha@example.com")
    mine = A.save_profile(u["id"], RIA)
    assert A.directory() == []
    assert A.profile(mine["slug"]) is None
    A.review(mine["id"], "approve")
    assert [e["slug"] for e in A.directory()] == [mine["slug"]]
    assert A.profile(mine["slug"])["sebi_reg"] == "INA000012345"


def test_changing_the_registration_on_a_live_profile_takes_it_off_the_list():
    _, u, mine = listed(RIA, "asha@example.com")
    A.save_profile(u["id"], dict(RIA, headline="Fee-only adviser, now also for NRIs"))
    assert A.my_profile(u["id"])["status"] == "approved", "a wording edit stays live"
    A.save_profile(u["id"], dict(RIA, sebi_reg="INA000099999"))
    assert A.my_profile(u["id"])["status"] == "pending"
    assert A.directory() == []


def test_the_link_survives_a_rename_and_two_people_never_share_one():
    _, u1, one = listed(RIA, "asha@example.com")
    _, u2, two = listed(dict(RIA, sebi_reg="INA000054321"), "other-asha@example.com")
    assert one["slug"] == "asha-rao" and two["slug"] == "asha-rao-2"
    A.save_profile(u1["id"], dict(RIA, display_name="Dr Asha Rao"))
    assert A.my_profile(u1["id"])["slug"] == "asha-rao"


def test_the_directory_filters_and_puts_featured_people_first():
    listed(RIA, "asha@example.com")
    listed(RA, "vikram@example.com")
    _, _, edu = listed(EDU, "meera@example.com")
    A.review(edu["id"], "feature")
    assert A.directory()[0]["slug"] == edu["slug"]
    assert {e["kind"] for e in A.directory(kind="registered")} == {"ria", "ra"}
    assert [e["kind"] for e in A.directory(topic="portfolio")] == ["ria"]
    assert [e["display_name"] for e in A.directory(q="vikram")] == ["Vikram Shah"]


def test_no_star_ratings_only_facts():
    _, _, mine = listed(RIA, "asha@example.com")
    shown = A.profile(mine["slug"])
    assert not {"rating", "stars", "reviews", "testimonials"} & set(shown)
    assert {"answered", "reply_minutes", "experience_years", "sebi_reg"} <= set(shown)


# ── Chats ────────────────────────────────────────────────────────────────

def test_a_chat_reaches_the_adviser_and_unread_counts_follow_it():
    _, adviser, mine = listed(RIA, "asha@example.com")
    _, reader = person("reader@example.com")
    started = A.start_chat(reader, mine["slug"], "retirement", "Can I retire at 55?", name="Ravi")
    assert A.my_chats(adviser)["unread"] == 1
    view = A.chat_view(adviser, started["chat_id"])
    assert view["role"] == "expert" and view["seeker_name"] == "Ravi"
    assert A.my_chats(adviser)["unread"] == 0, "reading it clears it"
    A.send_message(adviser, started["chat_id"], "Probably — let us look at your savings rate.")
    seen = A.chat_view(reader, started["chat_id"])
    assert [m["sender"] for m in seen["messages"]] == ["seeker", "expert"]
    poll = A.chat_view(reader, started["chat_id"], after=seen["messages"][-1]["id"])
    assert poll["messages"] == [], "a poll with nothing new returns nothing"


def test_the_adviser_never_sees_the_readers_email_address():
    _, adviser, mine = listed(RIA, "asha@example.com")
    _, reader = person("private.reader@example.com")
    chat = A.start_chat(reader, mine["slug"], "retirement", "Hello there.")["chat_id"]
    everything = json.dumps([A.chat_view(adviser, chat), A.my_chats(adviser)])
    assert "private.reader" not in everything
    assert "Altaha reader" in everything, "a reader who gives no name gets a neutral one"


def test_a_chat_that_is_not_yours_does_not_exist():
    _, _, mine = listed(RIA, "asha@example.com")
    _, reader = person("reader@example.com")
    _, stranger = person("stranger@example.com")
    chat = A.start_chat(reader, mine["slug"], "retirement", "Hello there.")["chat_id"]
    for fn in (lambda: A.chat_view(stranger, chat),
               lambda: A.send_message(stranger, chat, "hi"),
               lambda: A.close_chat(stranger, chat),
               lambda: A.report_chat(stranger, chat, "spam spam")):
        with pytest.raises(LookupError, match="does not exist"):
            fn()


def test_writing_again_continues_the_open_chat():
    _, _, mine = listed(RIA, "asha@example.com")
    _, reader = person("reader@example.com")
    first = A.start_chat(reader, mine["slug"], "retirement", "First question.")
    again = A.start_chat(reader, mine["slug"], "portfolio", "Second question.")
    assert again["existing"] and again["chat_id"] == first["chat_id"]
    assert len(A.my_chats(reader)["as_seeker"]) == 1


def test_you_cannot_chat_with_yourself_or_about_a_topic_they_do_not_take():
    _, adviser, mine = listed(RIA, "asha@example.com")
    with pytest.raises(ValueError, match="your own profile"):
        A.start_chat(adviser, mine["slug"], "retirement", "Hello me.")
    _, reader = person("reader@example.com")
    with pytest.raises(ValueError, match="topics this person takes"):
        A.start_chat(reader, mine["slug"], "career", "How do I become an analyst?")


def test_an_adviser_who_is_not_taking_chats_gets_none_and_unlisted_people_get_none():
    _, adviser, mine = listed(RIA, "asha@example.com")
    _, reader = person("reader@example.com")
    A.set_accepting(adviser["id"], False)
    with pytest.raises(PermissionError, match="not taking new chats"):
        A.start_chat(reader, mine["slug"], "retirement", "Hello.")
    _, other = person("pending@example.com")
    pending = A.save_profile(other["id"], RA)
    with pytest.raises(LookupError):
        A.start_chat(reader, pending["slug"], "stocks", "Hello.")


def test_new_chats_and_messages_are_rate_limited(monkeypatch):
    _, _, mine = listed(RIA, "asha@example.com")
    _, reader = person("reader@example.com")
    monkeypatch.setattr(A, "NEW_CHATS_PER_DAY", 1)
    chat = A.start_chat(reader, mine["slug"], "retirement", "One.")["chat_id"]
    A.close_chat(reader, chat)
    with pytest.raises(A.RateLimited, match="1 new chats a day"):
        A.start_chat(reader, mine["slug"], "retirement", "Two.")
    monkeypatch.setattr(A, "NEW_CHATS_PER_DAY", 5)
    chat = A.start_chat(reader, mine["slug"], "retirement", "Three.")["chat_id"]
    with pytest.raises(A.RateLimited, match="a lot of messages"):
        for i in range(A.MESSAGES_PER_MINUTE + 1):
            A.send_message(reader, chat, f"message {i}")


def test_a_message_has_to_have_something_in_it_and_not_too_much():
    _, _, mine = listed(RIA, "asha@example.com")
    _, reader = person("reader@example.com")
    with pytest.raises(ValueError, match="Write a message"):
        A.start_chat(reader, mine["slug"], "retirement", "   ")
    with pytest.raises(ValueError, match="under 2000"):
        A.start_chat(reader, mine["slug"], "retirement", "x" * 2001)


# ── What may be said ─────────────────────────────────────────────────────

def test_an_educator_cannot_send_a_buy_call_and_is_shown_which_sentence():
    _, edu, mine = listed(EDU, "meera@example.com")
    _, reader = person("reader@example.com")
    chat = A.start_chat(reader, mine["slug"], "ama", "Should I buy HDFC Bank now?")["chat_id"]
    with pytest.raises(A.MessageRefused) as refused:
        A.send_message(edu, chat, "Good question. Buy it below 1500 with a stop-loss at 1400.")
    assert refused.value.sentence.startswith("Buy it below 1500")
    A.send_message(edu, chat, "I never tell anyone to buy or sell. Here is how I would "
                              "read its balance sheet instead.")


def test_a_registered_adviser_may_give_a_call_but_nobody_may_promise_returns():
    _, adviser, mine = listed(RIA, "asha@example.com")
    _, reader = person("reader@example.com")
    chat = A.start_chat(reader, mine["slug"], "portfolio", "What should I do with ITC?")["chat_id"]
    A.send_message(adviser, chat, "Given your profile, I recommend trimming ITC to 10%.")
    with pytest.raises(A.MessageRefused, match="promise returns"):
        A.send_message(adviser, chat, "This fund gives guaranteed returns of 15%.")
    A.send_message(adviser, chat, "Nothing in equities is guaranteed.")


@pytest.mark.parametrize("text", [
    "WhatsApp me on 98765 43210", "Pay the fee to asha@okicici",
    "Join https://t.me/asha_calls", "Email me at asha.rao@gmail.com",
])
def test_nobody_can_move_the_conversation_off_altaha(text):
    _, adviser, mine = listed(RIA, "asha@example.com")
    _, reader = person("reader@example.com")
    chat = A.start_chat(reader, mine["slug"], "retirement", "Hello.")["chat_id"]
    for who in (adviser, reader):
        with pytest.raises(A.MessageRefused, match="Keep the conversation on Altaha"):
            A.send_message(who, chat, text)


# ── Sharing a portfolio ──────────────────────────────────────────────────

def test_a_shared_portfolio_is_seen_by_the_adviser_until_it_is_withdrawn():
    _, adviser, mine = listed(RIA, "asha@example.com")
    _, reader = person("reader@example.com")
    accounts.save_holdings(reader["id"], [{"symbol": "TCS", "qty": 10, "avg_price": 3500}])
    chat = A.start_chat(reader, mine["slug"], "portfolio", "Please look at my book.",
                        share_portfolio=True)["chat_id"]
    shared = A.chat_view(adviser, chat)["shared"]
    assert shared["holdings"] == [{"symbol": "TCS", "qty": 10.0, "avg_price": 3500.0}]
    assert "shared" not in A.chat_view(reader, chat), "the reader's own view does not echo it"
    A.set_share(reader, chat, False)
    assert "shared" not in A.chat_view(adviser, chat)
    lines = [m["body"] for m in A.chat_view(reader, chat)["messages"] if m["sender"] == "system"]
    assert any("stopped sharing" in s for s in lines), "both sides are told"


def test_only_a_registered_investment_adviser_can_be_shown_a_portfolio():
    _, _, ra = listed(RA, "vikram@example.com")
    _, reader = person("reader@example.com")
    with pytest.raises(ValueError, match="investment adviser"):
        A.start_chat(reader, ra["slug"], "stocks", "Hello.", share_portfolio=True)
    chat = A.start_chat(reader, ra["slug"], "stocks", "Hello.")["chat_id"]
    with pytest.raises(ValueError, match="investment adviser"):
        A.set_share(reader, chat, True)


def test_only_the_reader_decides_what_is_shared():
    _, adviser, mine = listed(RIA, "asha@example.com")
    _, reader = person("reader@example.com")
    chat = A.start_chat(reader, mine["slug"], "portfolio", "Hello.")["chat_id"]
    with pytest.raises(PermissionError):
        A.set_share(adviser, chat, True)


# ── Ending a chat ────────────────────────────────────────────────────────

def test_a_blocked_reader_cannot_start_again_but_a_closed_chat_can_be_restarted():
    _, adviser, mine = listed(RIA, "asha@example.com")
    _, reader = person("reader@example.com")
    chat = A.start_chat(reader, mine["slug"], "retirement", "Hello.")["chat_id"]
    A.close_chat(reader, chat)
    with pytest.raises(PermissionError, match="closed"):
        A.send_message(reader, chat, "Wait, one more thing.")
    chat2 = A.start_chat(reader, mine["slug"], "retirement", "Starting over.")["chat_id"]
    assert chat2 != chat
    with pytest.raises(PermissionError, match="Only the adviser"):
        A.close_chat(reader, chat2, block=True)
    A.close_chat(adviser, chat2, block=True)
    with pytest.raises(PermissionError, match="not taking messages from you"):
        A.start_chat(reader, mine["slug"], "retirement", "Hello again.")


def test_a_block_on_an_older_chat_still_holds():
    _, adviser, mine = listed(RIA, "asha@example.com")
    _, reader = person("reader@example.com")
    old = A.start_chat(reader, mine["slug"], "retirement", "First.")["chat_id"]
    A.close_chat(reader, old)
    A.start_chat(reader, mine["slug"], "retirement", "Second.")
    A.close_chat(adviser, old, block=True)            # blocks from the earlier chat
    with pytest.raises(PermissionError, match="not taking messages from you"):
        A.start_chat(reader, mine["slug"], "retirement", "Third.")


def test_a_suspended_adviser_disappears_and_their_chats_go_read_only():
    _, adviser, mine = listed(RIA, "asha@example.com")
    _, reader = person("reader@example.com")
    chat = A.start_chat(reader, mine["slug"], "retirement", "Hello.")["chat_id"]
    A.review(mine["id"], "suspend", "registration lapsed")
    assert A.directory() == []
    assert A.chat_view(reader, chat)["read_only"] is True
    with pytest.raises(PermissionError, match="read-only"):
        A.send_message(adviser, chat, "Still here.")
    assert len(A.chat_view(reader, chat)["messages"]) == 1, "the record stays"


# ── Notifications ────────────────────────────────────────────────────────

def _age(chat_id, role, minutes):
    """Pretend `role` last looked at the chat this many minutes ago. Any
    email they were sent moves back with it, so the order of the two stays
    what it was in real time."""
    import datetime as dt
    seen = accounts._iso(accounts._now() - dt.timedelta(minutes=minutes))
    told = accounts._iso(accounts._now() - dt.timedelta(minutes=minutes + 1))
    conn = A._conn()
    with conn:
        conn.execute(f"UPDATE chats SET {role}_seen_at=?, {role}_notified_at="
                     f"CASE WHEN {role}_notified_at IS NULL THEN NULL ELSE ? END WHERE id=?",
                     (seen, told, chat_id))


def test_one_email_per_unread_stretch_and_none_while_they_are_looking():
    _, adviser, mine = listed(RIA, "asha@example.com")
    _, reader = person("reader@example.com")
    started = A.start_chat(reader, mine["slug"], "retirement", "Hello.")
    assert started["notify"]["email"] == "asha@example.com"
    assert started["notify"]["new_chat"] is True
    chat = started["chat_id"]
    assert A.send_message(reader, chat, "Are you there?")["notify"] is None, \
        "already told about this stretch"

    _age(chat, "seeker", 10)                         # the reader wanders off
    A.chat_view(adviser, chat)                       # the adviser reads it...
    reply = A.send_message(adviser, chat, "Yes, here.")
    assert reply["notify"]["email"] == "reader@example.com"
    _age(chat, "expert", 10)                         # ...and left
    again = A.send_message(reader, chat, "Thanks!")
    assert again["notify"]["email"] == "asha@example.com"
    assert again["notify"]["new_chat"] is False

    A.chat_view(adviser, chat)                       # looking right now
    assert A.send_message(reader, chat, "One more.")["notify"] is None


def test_the_email_says_who_wrote_and_never_what_they_wrote():
    _, _, mine = listed(RIA, "asha@example.com")
    _, reader = person("reader@example.com")
    secret = "My salary is 42 lakh and my PAN is ABCDE1234F"
    notice = A.start_chat(reader, mine["slug"], "retirement", secret, name="Ravi")["notify"]
    subject, html, text = A.notice_email(notice, "https://altahascreener.in")
    assert "Ravi" in subject
    for part in (subject, html, text):
        assert "42 lakh" not in part and "ABCDE1234F" not in part
    assert f"advisors.html#chat/{notice['chat_id']}" in text


# ── The routes ───────────────────────────────────────────────────────────

def test_the_routes_turn_refusals_into_status_codes_and_send_mail_later(routes):
    tok, _, mine = listed(EDU, "meera@example.com")
    rtok, _ = person("reader@example.com")
    bg = BackgroundTasks()
    view = routes.advisor_start_chat(mine["slug"], bg, {"topic": "ama", "message": "Hello!"},
                                     authorization=f"Bearer {rtok}")
    assert view["role"] == "seeker" and len(bg.tasks) == 1, "the email waits for the response"
    with pytest.raises(HTTPException) as e:
        routes.advisor_send(view["id"], BackgroundTasks(), {"body": "Sell it all tomorrow."},
                            authorization=f"Bearer {tok}")
    assert e.value.status_code == 422
    assert e.value.detail["sentence"] == "Sell it all tomorrow."
    with pytest.raises(HTTPException) as e:
        routes.advisor_chat(view["id"] + 99, authorization=f"Bearer {rtok}")
    assert e.value.status_code == 404
    with pytest.raises(HTTPException) as e:
        routes.advisor_chats(authorization=None)
    assert e.value.status_code == 401


def test_the_directory_carries_what_the_page_needs_to_explain_itself(routes):
    out = routes.advisor_directory()
    assert {k["id"] for k in out["kinds"]} == {"ria", "ra", "educator"}
    portfolio = [t for t in out["topics"] if t["id"] == "portfolio"][0]
    assert portfolio["kinds"] == ["ria"]
    assert "not registered" in out["disclaimer"] and "Never pay" in out["disclaimer"]


def test_the_owners_view_is_closed_without_a_key_and_shows_addresses_with_one(routes, monkeypatch):
    _, u = person("asha@example.com")
    mine = A.save_profile(u["id"], RIA)
    with pytest.raises(HTTPException) as e:
        routes.admin_advisors(key="", x_admin_key=None)
    assert e.value.status_code == 401, "closed when ADMIN_KEY is unset"
    monkeypatch.setenv("ADMIN_KEY", "k")
    out = routes.admin_advisors(key="k", x_admin_key=None)
    assert out["counts"]["pending"] == 1 and out["experts"][0]["email"] == "asha@example.com"
    done = routes.admin_advisor_review({"expert_id": mine["id"], "action": "approve"},
                                       key="", x_admin_key="k")
    assert done["expert"]["status"] == "approved"
    with pytest.raises(HTTPException) as e:
        routes.admin_advisor_review({"expert_id": mine["id"], "action": "delete"},
                                    key="k", x_admin_key=None)
    assert e.value.status_code == 400


def test_a_report_reaches_the_owner_with_the_conversation(routes, monkeypatch):
    _, adviser, mine = listed(RIA, "asha@example.com")
    _, reader = person("reader@example.com")
    chat = A.start_chat(reader, mine["slug"], "retirement", "Hello.")["chat_id"]
    A.send_message(adviser, chat, "Let us talk about your goals.")
    A.report_chat(reader, chat, "Asked me for money")
    A.report_chat(reader, chat, "Asked me for money twice")
    monkeypatch.setenv("ADMIN_KEY", "k")
    reports = routes.admin_advisor_reports(key="k", x_admin_key=None)["reports"]
    assert len(reports) == 1, "one report per side per chat, the latest reason kept"
    assert reports[0]["reason"] == "Asked me for money twice"
    assert [m["sender"] for m in reports[0]["messages"]] == ["seeker", "expert"]


def test_nothing_said_can_be_deleted():
    """An adviser must be able to produce the record of what was said; a
    report must be judged on what actually happened."""
    import main
    deletes = [r.path for r in main.app.routes
               if r.path.startswith("/advisors") and "DELETE" in (getattr(r, "methods", None) or ())]
    assert deletes == []


def test_a_database_that_cannot_be_reached_is_a_503_that_says_so(routes, monkeypatch):
    """Not a bare 500: the page shows the sentence, and a 500 reads as a bug
    in the app rather than a disk that is briefly unavailable."""
    import sqlite3

    def broken(*a, **k):
        raise sqlite3.OperationalError("unable to open database file")
    monkeypatch.setattr(A, "directory", broken)
    with pytest.raises(HTTPException) as e:
        routes.advisor_directory()
    assert e.value.status_code == 503 and "unavailable" in e.value.detail
