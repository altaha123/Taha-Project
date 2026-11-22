"""
The forum: who can post, what may be said, and what the public sees.

The failures worth testing for are the quiet ones. A member's email address
in a thread looks like any other line of text. A tip with a target and a
stop-loss reads like any other opinion. A scam posted at night that three
members reported, still up in the morning, looks like nothing at all. A
reply count that went on counting a hidden post makes a thread look busier
than it is. None of these crash.

Handlers are called directly, as test_advisors.py does.
"""
import datetime as dt
import os
import tempfile

import pytest
from fastapi import HTTPException

import accounts
import forum as F


@pytest.fixture(autouse=True)
def fresh_db(monkeypatch):
    with tempfile.TemporaryDirectory() as d:
        accounts.reset_for_tests(os.path.join(d, "accounts.db"))
        monkeypatch.delenv("ADMIN_KEY", raising=False)
        yield
        accounts.reset_for_tests(os.path.join(d, "accounts.db"))


@pytest.fixture(scope="module")
def routes():
    import forum_routes
    return forum_routes


def person(email, handle=None):
    done = accounts.complete_login(accounts.start_login(email)["token"])
    u = accounts.user_for_session(done["session"])
    if handle:
        F.set_handle(u["id"], handle)
    return done["session"], u


def bearer(tok):
    return "Bearer " + tok


OPENING = "Margins held up better than the street expected, and the order book grew."


def a_thread(u, **kw):
    args = dict(category="stocks", title="Q2 results: what changed", body=OPENING)
    args.update(kw)
    if args["category"] == "stocks":
        args.setdefault("symbol", "TCS")
    return F.start_thread(u, args.pop("category"), args.pop("title"), args.pop("body"), **args)["thread_id"]


# ── The house rules ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("text", [
    "Buy at 450, it will run.",
    "Target 520 in three months.",
    "Price target of ₹1,250 for this one.",
    "Keep a stop loss at 430.",
    "SL 430 strictly.",
    "Accumulate below 500 for the long run.",
    "Entry 450-460, exit @ 520.",
    "Tgt: 610 and 650.",
    "Buy HDFC Bank at 1650 before results.",
    "Sell Tata Motors above 1,020.",
])
def test_a_tip_is_refused_with_the_sentence_that_made_it_one(text):
    with pytest.raises(F.PostRefused) as e:
        F.check_post("Good quarter overall. " + text)
    assert e.value.sentence and e.value.sentence in text
    assert "SEBI-registered research analyst" in str(e.value)


@pytest.mark.parametrize("text", [
    "I bought at 450 in 2021 and still hold it.",
    "Would you buy at 450?",
    "I would not buy at 450 after this quarter.",
    "Use a stop-loss of 8% on every position you size.",
    "Revenue grew 18% and the dividend was 22 a share.",
    "Always use a stop loss; size positions so one mistake is survivable.",
    "Their target market is rural India.",
    "Buy and hold works if the business compounds.",
    "The promoter's exit from 2019 still weighs on the stock.",
    "Promoters plan to sell over 1,000 shares a day.",
    "I would buy more of this business if it ever fell below 300.",
])
def test_reasoning_and_facts_about_the_writer_pass(text):
    F.check_post(text)


@pytest.mark.parametrize("text,what", [
    ("DM me on 98765 43210 for the full list", "a phone number"),
    ("Join t.me/multibaggers for more", "WhatsApp or Telegram"),
    ("Pay me at ravi@okaxis for the course", "UPI"),
    ("Mail ravi@example.com", "an email address"),
])
def test_contact_details_are_refused_because_that_is_how_scams_start(text, what):
    with pytest.raises(F.PostRefused, match=what):
        F.check_post(text)


@pytest.mark.parametrize("text", [
    "This is a sure shot multibagger.",
    "Guaranteed 20% returns in a year.",
    "Returns are guaranteed if you hold.",
    "Assured returns, every quarter.",
    "Double your money by Diwali.",
    "A risk-free trade into results.",
])
def test_nobody_may_promise_returns(text):
    with pytest.raises(F.PostRefused) as e:
        F.check_post(text)
    assert e.value.rule == "promise" and e.value.sentence == text


@pytest.mark.parametrize("text", [
    "Nothing in the market is guaranteed.",
    "The credit guarantee scheme for MSMEs was widened.",
    "Use the risk-free rate from the 10-year bond.",
    "No fund can promise guaranteed returns.",
])
def test_policy_and_finance_words_are_not_promises(text):
    F.check_post(text)


def test_too_many_links_is_refused():
    F.check_post("See https://a.example and https://b.example")
    with pytest.raises(F.PostRefused, match="3 links"):
        F.check_post(" ".join(f"https://x{i}.example" for i in range(4)))


def test_a_refused_post_is_not_saved():
    _, u = person("a@example.com", "Asha")
    with pytest.raises(F.PostRefused):
        a_thread(u, body="Strong numbers all round. Buy at 3400 with a stop loss at 3300.")
    assert F.threads()["threads"] == []


# ── Members and their names ────────────────────────────────────────────────

def test_a_member_needs_a_forum_name_before_posting_and_the_email_never_shows():
    _, u = person("ravi.kumar@example.com")
    with pytest.raises(PermissionError, match="forum name"):
        a_thread(u)
    F.set_handle(u["id"], "Value Hunter")
    tid = a_thread(u)
    blob = repr(F.thread(tid)) + repr(F.threads()) + repr(F.for_stock("TCS"))
    assert "ravi.kumar" not in blob and "example.com" not in blob
    assert F.thread(tid)["posts"][0]["author"] == "Value Hunter"


@pytest.mark.parametrize("name,why", [
    ("ab", "3 to 24"),
    ("ravi@example.com", "letters, numbers"),
    ("Altaha Team", "mistaken for Altaha"),
    ("SEBI desk", "mistaken for Altaha"),
    ("Call 9876543210", "phone number"),
    ("-dash-", "letters, numbers"),
])
def test_a_name_that_could_mislead_is_refused(name, why):
    _, u = person("b@example.com")
    with pytest.raises(ValueError, match=why):
        F.set_handle(u["id"], name)


def test_names_are_unique_however_they_are_spaced_or_cased():
    _, a = person("a@example.com", "Value Hunter")
    _, b = person("b@example.com")
    with pytest.raises(ValueError, match="already uses"):
        F.set_handle(b["id"], "value.hunter")
    # The same person can respell their own name.
    assert F.set_handle(a["id"], "Value-Hunter")["handle"] == "Value-Hunter"


# ── Threads and replies ────────────────────────────────────────────────────

def test_a_stock_thread_needs_a_company_the_server_knows():
    _, u = person("a@example.com", "Asha")
    known = lambda s: {"name": "Tata Consultancy Services"} if s == "TCS" else None   # noqa: E731
    with pytest.raises(ValueError, match="symbol"):
        a_thread(u, symbol="")
    with pytest.raises(ValueError, match="not a company Altaha knows"):
        a_thread(u, symbol="NOTREAL", known=known)
    tid = a_thread(u, symbol="tcs.ns", known=known)
    t = F.thread(tid)["thread"]
    assert (t["symbol"], t["company"]) == ("TCS", "Tata Consultancy Services")


def test_a_general_thread_may_name_a_stock_and_drops_one_it_does_not_know():
    _, u = person("a@example.com", "Asha")
    known = lambda s: {"name": "Infosys"} if s == "INFY" else None   # noqa: E731
    t1 = a_thread(u, category="market", symbol="INFY", known=known)
    t2 = a_thread(u, category="market", title="Rates and the rupee", symbol="ZZZZ", known=known)
    assert F.thread(t1)["thread"]["symbol"] == "INFY"
    assert F.thread(t2)["thread"]["symbol"] is None


def test_replies_count_and_move_the_thread_to_the_top():
    _, a = person("a@example.com", "Asha")
    _, b = person("b@example.com", "Bala")
    old = a_thread(a, title="An older discussion", category="market")
    new = a_thread(a, title="A newer discussion", category="market")
    assert [t["id"] for t in F.threads()["threads"]] == [new, old]
    F.reply(b, old, "Agreed on the order book.")
    listing = F.threads()["threads"]
    assert [t["id"] for t in listing] == [old, new]
    assert listing[0]["replies"] == 1 and listing[0]["excerpt"].startswith("Margins held up")


def test_a_category_a_stock_and_a_search_each_narrow_the_list():
    _, u = person("a@example.com", "Asha")
    s = a_thread(u, symbol="TCS")
    m = a_thread(u, category="market", title="Rates and the rupee this week")
    assert [t["id"] for t in F.threads(category="market")["threads"]] == [m]
    assert [t["id"] for t in F.threads(symbol="TCS")["threads"]] == [s]
    assert [t["id"] for t in F.threads(q="rupee")["threads"]] == [m]
    assert [t["id"] for t in F.threads(q="tcs")["threads"]] == [s]
    # A search term is text, not a pattern.
    assert F.threads(q="%")["threads"] == []
    with pytest.raises(ValueError):
        F.threads(category="gossip")


def test_the_stock_page_summary():
    _, u = person("a@example.com", "Asha")
    a_thread(u, symbol="TCS")
    a_thread(u, symbol="TCS", title="Is the deal pipeline real?")
    a_thread(u, symbol="INFY", title="Infosys guidance cut, again")
    s = F.for_stock("TCS")
    assert s["count"] == 2 and s["posts_this_week"] == 2 and len(s["threads"]) == 2
    assert all(t["symbol"] == "TCS" for t in s["threads"])


def test_a_locked_thread_takes_no_replies_and_a_hidden_one_is_gone():
    _, a = person("a@example.com", "Asha")
    _, b = person("b@example.com", "Bala")
    tid = a_thread(a)
    F.moderate("lock_thread", tid)
    with pytest.raises(PermissionError, match="closed"):
        F.reply(b, tid, "Late to this.")
    F.moderate("hide_thread", tid)
    with pytest.raises(LookupError):
        F.thread(tid)
    assert F.threads()["threads"] == [] and F.for_stock("TCS")["count"] == 0


def test_removing_my_post_keeps_the_row_but_not_the_words():
    _, a = person("a@example.com", "Asha")
    _, b = person("b@example.com", "Bala")
    tid = a_thread(a)
    pid = F.reply(b, tid, "On reflection, I was wrong about this.")["post"]["id"]
    with pytest.raises(LookupError):
        F.remove_own(a, pid)            # not Asha's to remove
    F.remove_own(b, pid)
    post = F.thread(tid)["posts"][1]
    assert post["status"] == "removed" and post["body"] is None
    assert F.thread(tid)["thread"]["replies"] == 0
    row = F._post_row(pid)
    assert row["body"].startswith("On reflection")      # kept for review


def test_helpful_once_per_member_and_never_on_your_own():
    _, a = person("a@example.com", "Asha")
    _, b = person("b@example.com", "Bala")
    _, c = person("c@example.com", "Chitra")
    tid = a_thread(a)
    pid = F.thread(tid)["posts"][0]["id"]
    with pytest.raises(PermissionError):
        F.set_helpful(a, pid, True)
    F.set_helpful(b, pid, True)
    F.set_helpful(b, pid, True)
    assert F.set_helpful(c, pid, True)["helpful"] == 2
    assert F.set_helpful(c, pid, False)["helpful"] == 1
    assert F.thread(tid, viewer=b)["posts"][0]["voted"] is True
    assert F.thread(tid, viewer=c)["posts"][0]["voted"] is False


def test_limits_on_how_fast_a_member_posts(monkeypatch):
    _, a = person("a@example.com", "Asha")
    monkeypatch.setattr(F, "THREADS_PER_DAY", 2)
    a_thread(a, title="First of the day")
    a_thread(a, title="Second of the day")
    with pytest.raises(F.RateLimited, match="2 new discussions"):
        a_thread(a, title="Third of the day")
    monkeypatch.setattr(F, "POSTS_PER_MINUTE", 3)
    tid = F.threads()["threads"][0]["id"]
    F.reply(a, tid, "One more thing.")
    with pytest.raises(F.RateLimited, match="minute"):
        F.reply(a, tid, "And another.")


# ── Reports and the owner ──────────────────────────────────────────────────

def test_enough_reports_hide_a_post_until_the_owner_looks():
    _, a = person("a@example.com", "Asha")
    tid = a_thread(a)
    _, spam = person("s@example.com", "Spammer")
    pid = F.reply(spam, tid, "Great company, my course explains everything.")["post"]["id"]
    reporters = [person(f"r{i}@example.com", f"Reader {i}")[1] for i in range(F.HIDE_AFTER_REPORTS)]
    for r in reporters[:-1]:
        assert F.report(r, pid, "Selling a course")["hidden"] is False
    assert F.report(reporters[0], pid, "again")["already"] is True       # once per member
    assert F.report(reporters[-1], pid, "Selling a course")["hidden"] is True
    shown = F.thread(tid)["posts"][1]
    assert shown["status"] == "hidden" and shown["body"] is None
    assert F.thread(tid)["thread"]["replies"] == 0
    q = F.moderation_queue()
    assert q["queue"][0]["post_id"] == pid and q["queue"][0]["reasons"][0] == "Selling a course"
    assert q["counts"]["open_reports"] == F.HIDE_AFTER_REPORTS
    # The owner disagrees: it comes back, and the reports are closed.
    F.moderate("restore_post", pid)
    assert F.thread(tid)["posts"][1]["body"].startswith("Great company")
    assert F.moderation_queue()["queue"] == []


def test_a_reported_opening_post_takes_its_thread_down_with_it():
    _, a = person("a@example.com", "Asha")
    tid = a_thread(a)
    pid = F.thread(tid)["posts"][0]["id"]
    for i in range(F.HIDE_AFTER_REPORTS):
        F.report(person(f"r{i}@example.com", f"Reader {i}")[1], pid, "Pump and dump")
    assert F.threads()["threads"] == []
    F.moderate("restore_post", pid)
    assert [t["id"] for t in F.threads()["threads"]] == [tid]


def test_a_banned_member_reads_but_cannot_post():
    _, a = person("a@example.com", "Asha")
    tid = a_thread(a)
    F.moderate("ban_member", a["id"], "Repeated tips")
    with pytest.raises(PermissionError, match="no longer post"):
        F.reply(a, tid, "Let me back in.")
    assert F.thread(tid)["thread"]["id"] == tid
    F.moderate("unban_member", a["id"])
    F.reply(a, tid, "Thank you.")


def test_a_pinned_thread_leads_the_front_page_only():
    _, a = person("a@example.com", "Asha")
    pinned = a_thread(a, category="altaha", title="House rules, please read")
    later = a_thread(a, category="market", title="Something newer")
    F.moderate("pin_thread", pinned)
    assert F.threads()["threads"][0]["id"] == pinned
    assert F.threads(sort="new")["threads"][0]["id"] == later


def test_the_week_in_the_forum_counts_visible_posts_in_the_window():
    _, a = person("a@example.com", "Asha")
    _, b = person("b@example.com", "Bala")
    busy = a_thread(a)
    quiet = a_thread(a, category="market", title="A quiet discussion")
    for i in range(3):
        F.reply(b, busy, f"Point number {i}.")
    now = accounts._now()
    w = F.activity(now - dt.timedelta(days=7), now + dt.timedelta(minutes=1))
    assert w["posts"] == 5 and w["members"] == 2 and w["new_threads"] == 2
    assert w["threads"][0]["id"] == busy and w["threads"][0]["posts"] == 4
    assert w["stocks"] == [{"symbol": "TCS", "company": None, "posts": 4, "threads": 1}]
    assert {t["id"] for t in w["threads"]} == {busy, quiet}
    old = F.activity(now - dt.timedelta(days=30), now - dt.timedelta(days=20))
    assert old["posts"] == 0 and old["threads"] == []


# ── Over HTTP ──────────────────────────────────────────────────────────────

def test_reading_needs_no_account_and_posting_does(routes):
    tok, u = person("a@example.com")
    with pytest.raises(HTTPException) as e:
        routes.forum_start({"category": "market", "title": "A fair title", "body": OPENING}, authorization=None)
    assert e.value.status_code == 401
    with pytest.raises(HTTPException) as e:
        routes.forum_start({"category": "market", "title": "A fair title", "body": OPENING},
                           authorization=bearer(tok))
    assert e.value.status_code == 403            # no forum name yet
    assert routes.forum_set_handle({"handle": "Asha"}, authorization=bearer(tok))["member"]["handle"] == "Asha"
    out = routes.forum_start({"category": "market", "title": "A fair title", "body": OPENING},
                             authorization=bearer(tok))
    tid = out["thread"]["id"]
    front = routes.forum_front()
    assert front["threads"][0]["id"] == tid and front["rules"] and front["disclaimer"]
    assert {c["id"] for c in front["categories"]} >= {"stocks", "market", "beginners"}
    assert routes.forum_thread(tid, authorization=None)["posts"][0]["mine"] is False
    assert routes.forum_thread(tid, authorization=bearer(tok))["posts"][0]["mine"] is True
    # A stale token reads as signed out, not as an error.
    assert routes.forum_thread(tid, authorization="Bearer nonsense")["thread"]["id"] == tid


def test_a_refused_post_answers_422_with_the_sentence(routes):
    tok, _ = person("a@example.com", "Asha")
    with pytest.raises(HTTPException) as e:
        routes.forum_start({"category": "market", "title": "Nifty this week",
                            "body": "Strong breadth all week. Buy at 24500 for a quick move."},
                           authorization=bearer(tok))
    assert e.value.status_code == 422
    assert e.value.detail["sentence"] == "Buy at 24500 for a quick move."
    assert e.value.detail["rule"] == "tip"


def test_the_stock_route_uses_the_servers_record_of_companies(routes, monkeypatch):
    tok, _ = person("a@example.com", "Asha")
    monkeypatch.setattr(routes, "KNOWN_COMPANY", lambda s: {"name": "Reliance Industries"} if s == "RELIANCE" else None)
    body = {"category": "stocks", "title": "Retail demerger timing", "body": OPENING}
    with pytest.raises(HTTPException) as e:
        routes.forum_start(dict(body, symbol="FAKECO"), authorization=bearer(tok))
    assert e.value.status_code == 400
    out = routes.forum_start(dict(body, symbol="RELIANCE"), authorization=bearer(tok))
    assert out["thread"]["company"] == "Reliance Industries"
    assert routes.forum_stock("RELIANCE")["count"] == 1


def test_the_admin_routes_are_closed_without_a_key(routes, monkeypatch):
    with pytest.raises(HTTPException) as e:
        routes.admin_forum(key="")
    assert e.value.status_code == 401
    monkeypatch.setenv("ADMIN_KEY", "k")
    with pytest.raises(HTTPException):
        routes.admin_forum(key="wrong")
    assert "queue" in routes.admin_forum(key="", x_admin_key="k")
    with pytest.raises(HTTPException) as e:
        routes.admin_forum_moderate({"action": "explode", "target": 1}, x_admin_key="k")
    assert e.value.status_code == 400
