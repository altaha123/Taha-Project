"""
The weekly brief: which week, which figures, and what it may say.

The quiet failures: a week that starts on the wrong day moves Friday's close
into the next issue; a week change measured from Monday's close instead of
the Friday before misses Monday's move; a session the server never recorded
counted as zero flows; a circular from the week before filling this week's
issue; a topic added after the issue was published never reaching the page;
and a target price written into the brief, which is the site's own voice.
"""
import datetime as dt
import os
import tempfile

import pytest
from fastapi import HTTPException

import accounts
import weekly_brief as W

WEEK = "2026-W47"           # Mon 16 Nov to Sun 22 Nov 2026


@pytest.fixture(autouse=True)
def store(monkeypatch):
    with tempfile.TemporaryDirectory() as d:
        monkeypatch.setattr(W, "STORE", os.path.join(d, "weekly.json"))
        W._draft.update(week=None, at=0.0, body=None)
        accounts.reset_for_tests(os.path.join(d, "accounts.db"))
        monkeypatch.delenv("ADMIN_KEY", raising=False)
        yield d
        accounts.reset_for_tests(os.path.join(d, "accounts.db"))


SERIES = {
    "NIFTY 50": {"2026-11-12": 24800.0, "2026-11-13": 25000.0,          # the week before
                 "2026-11-16": 25100.0, "2026-11-17": 24950.0, "2026-11-18": 25200.0,
                 "2026-11-19": 25300.0, "2026-11-20": 25250.0,
                 "2026-11-23": 25400.0},                                  # the week after
    "SENSEX": {"2026-11-13": 82000.0, "2026-11-20": 81590.0},
    "INDIA VIX": {"2026-11-20": 13.1},                                    # nothing before: no change
}
FLOWS = {
    "2026-11-16": {"fii": {"net": -1200.5}, "dii": {"net": 1500.0}},
    "2026-11-17": {"fii": {"net": -800.0}, "dii": {"net": 900.0}},
    "2026-11-18": {"fii": {"net": 300.0}, "dii": {"net": -100.0}},
    # the 19th was never recorded
    "2026-11-20": {"fii": {"net": -500.0}, "dii": {"net": 700.0}},
    "2026-11-13": {"fii": {"net": 99999.0}, "dii": {"net": 99999.0}},     # last week's
}


def circular(i, first_seen, impact, importance="medium", sectors=("Banks",)):
    return {"id": f"c{i}", "source": "RBI press release", "title": f"Circular {i}", "date": first_seen,
            "first_seen": first_seen, "impact": impact, "importance": importance,
            "summary": "A rule.", "sectors": list(sectors), "link": "https://rbi.org.in/x",
            "stocks": [{"symbol": "HDFCBANK", "direction": "helped", "reason": "r"}]}


POLICY = {c["id"]: c for c in [
    circular(1, "2026-11-17", "positive", "low"),
    circular(2, "2026-11-18", "negative", "high", ("Banks", "Financial Services")),
    circular(3, "2026-11-19", "none"),
    circular(4, "2026-11-10", "positive", "high"),          # last week's
]}

FORUM = {"posts": 12, "members": 5, "new_threads": 3,
         "threads": [{"id": 9, "title": "Bank NIMs <next> quarter", "category": "stocks",
                      "category_label": "Stocks", "symbol": "HDFCBANK", "posts": 7, "replies": 6}],
         "stocks": [{"symbol": "HDFCBANK", "company": "HDFC Bank", "posts": 7, "threads": 1}]}

SOURCES = {"series": SERIES, "flows_record": FLOWS, "policy_items": POLICY, "forum_activity": FORUM, "missing": []}


# ── Weeks ──────────────────────────────────────────────────────────────────

def test_a_week_is_monday_to_sunday_and_has_a_readable_name():
    assert W.week_days(WEEK) == (dt.date(2026, 11, 16), dt.date(2026, 11, 22))
    assert W.week_id(dt.date(2026, 11, 22)) == WEEK and W.week_id(dt.date(2026, 11, 23)) == "2026-W48"
    assert W.week_label(WEEK) == "16–22 Nov 2026"
    assert W.week_label("2026-W49") == "30 Nov – 6 Dec 2026"
    for bad in ("2026-47", "2026-W60", "nonsense", ""):
        with pytest.raises(ValueError):
            W.week_days(bad)


def test_saturdays_run_publishes_the_week_that_just_traded():
    assert W.last_traded_week(dt.date(2026, 11, 21)) == WEEK          # Saturday
    assert W.last_traded_week(dt.date(2026, 11, 22)) == WEEK          # Sunday
    assert W.last_traded_week(dt.date(2026, 11, 25)) == WEEK          # a Wednesday after: last week


# ── The sections ───────────────────────────────────────────────────────────

def test_the_week_change_runs_from_the_last_close_before_monday():
    m = W.market_section(SERIES, WEEK)
    nifty = m["indices"][0]
    assert (nifty["index"], nifty["close"], nifty["as_of"]) == ("NIFTY 50", 25250.0, "2026-11-20")
    assert nifty["week_change_pct"] == 1.0                          # 25,000 → 25,250
    sensex = next(r for r in m["indices"] if r["index"] == "SENSEX")
    assert sensex["week_change_pct"] == -0.5
    vix = next(r for r in m["indices"] if r["index"] == "INDIA VIX")
    assert vix["week_change_pct"] is None
    assert [s["date"] for s in m["sessions"]] == ["2026-11-16", "2026-11-17", "2026-11-18", "2026-11-19", "2026-11-20"]
    assert m["sessions"][0]["change_pct"] == 0.4 and m["sessions"][0]["weekday"] == "Mon"


def test_a_session_that_was_never_recorded_is_not_counted_as_zero():
    m = W.market_section(SERIES, WEEK)
    f = W.flows_section(FLOWS, WEEK, m["sessions"])
    assert (f["recorded"], f["of"]) == (4, 5)
    assert f["fii_total"] == -2200.5 and f["dii_total"] == 3000.0
    thursday = f["sessions"][3]
    assert thursday["recorded"] is False and thursday["fii"] is None
    # No prices at all: Monday to Friday stand in, and nothing is invented.
    empty = W.flows_section({}, WEEK, [])
    assert empty["of"] == 5 and empty["recorded"] == 0 and empty["fii_total"] is None


def test_only_this_weeks_circulars_that_matter_most_important_first():
    p = W.policy_section(POLICY, WEEK)
    assert (p["read"], p["matter"]) == (3, 2)
    assert [r["title"] for r in p["items"]] == ["Circular 2", "Circular 1"]
    assert p["sectors"][0] == {"sector": "Banks", "positive": 1, "negative": 1, "mixed": 0}
    assert p["items"][0]["stocks"] == [{"symbol": "HDFCBANK", "direction": "helped"}]


def test_the_week_in_brief_is_written_from_the_figures():
    i = W.build(WEEK, SERIES, FLOWS, POLICY, FORUM)
    assert i["summary"] == [
        "Nifty rose 1.00% over the week, to 25,250.",
        "FIIs sold a net ₹2,201 crore in the cash market and DIIs bought ₹3,000 crore, "
        "across the 4 of 5 sessions on record.",
        "2 new circulars mattered for listed companies, most of all for Banks.",
        "On the forum, 12 posts from 5 members; the busiest discussion was “Bank NIMs <next> quarter”.",
    ]


def test_an_issue_with_nothing_to_say_says_nothing():
    i = W.build(WEEK)
    assert i["summary"] == [] and not W.has_content(i)
    assert i["market"]["indices"] == [] and i["policy"]["items"] == []


# ── Publishing, drafts and topics ──────────────────────────────────────────

def test_a_published_issue_is_kept_and_its_topics_are_read_live():
    out = W.publish(WEEK, SOURCES)
    assert out["published"] is True and out["topics"] == []
    W.add_topic(WEEK, "Budget season", "What to read before the budget, and what to ignore in the coverage.", "tcs, infy TCS")
    later = W.issue(WEEK, today=dt.date(2026, 11, 28))
    assert later["summary"] == out["summary"]
    assert [t["title"] for t in later["topics"]] == ["Budget season"]
    assert later["topics"][0]["symbols"] == ["TCS", "INFY"]
    assert W.issues()[0] == {"week": WEEK, "label": "16–22 Nov 2026",
                             "headline": "Nifty rose 1.00% over the week, to 25,250.", "topics": 1}


def test_this_week_is_a_draft_and_next_week_is_not_there():
    today = dt.date(2026, 11, 18)
    d = W.issue("", today=today, sources=SOURCES)
    assert d["week"] == WEEK and d["draft"] is True and d["published"] is False
    with pytest.raises(LookupError):
        W.issue("2026-W48", today=today)
    past = W.issue("2026-W40", today=today, sources={})
    assert past["draft"] is False and past["published"] is False


def test_a_topic_is_held_to_the_rules_on_tips_and_promises():
    import forum
    with pytest.raises(forum.PostRefused) as e:
        W.add_topic(WEEK, "Banks into results", "Loan growth is steady. Buy HDFC Bank at 1650 before results.")
    assert e.value.sentence.startswith("Buy HDFC Bank at 1650")
    with pytest.raises(forum.PostRefused):
        W.add_topic(WEEK, "Fixed deposits", "Corporate FDs are a sure shot way to beat inflation this year.")
    with pytest.raises(ValueError, match="at least 20"):
        W.add_topic(WEEK, "Short", "Too short.")
    t = W.add_topic(WEEK, "How to read a concall", "Start with the questions analysts asked twice, not the opening remarks.")
    assert W.delete_topic(WEEK, t["id"]) is True
    with pytest.raises(LookupError):
        W.delete_topic(WEEK, t["id"])


def test_the_email_carries_the_week_and_escapes_what_members_wrote():
    i = W.publish(WEEK, SOURCES)
    W.add_topic(WEEK, "Tax-loss season", "Harvest losses before March.\n\nCheck the grandfathering date first.")
    i = W.with_topics(i)
    html = W.email_html(i, site="https://altahascreener.in", unsubscribe_url="https://x/unsub")
    text = W.email_text(i, site="https://altahascreener.in", unsubscribe_url="https://x/unsub")
    assert W.email_subject(i) == "The week in brief, 16–22 Nov 2026"
    assert "Bank NIMs &lt;next&gt; quarter" in html and "<next>" not in html
    assert "forum.html#t/9" in html and "Tax-loss season" in html and "Unsubscribe" in html
    assert "Nifty rose 1.00%" in text and "FII -2,201 · DII +3,000" in text and "TAX-LOSS SEASON" in text
    assert "weekly.html?w=2026-W47&from=email" in text


# ── Over HTTP ──────────────────────────────────────────────────────────────

def test_topics_route_is_closed_without_the_key(monkeypatch):
    import main
    monkeypatch.setattr(main, "ADMIN_KEY", "")
    with pytest.raises(HTTPException) as e:
        main.admin_weekly_topics({"action": "add", "title": "x", "body": "y"}, key="")
    assert e.value.status_code == 401
    monkeypatch.setattr(main, "ADMIN_KEY", "k")
    with pytest.raises(HTTPException) as e:
        main.admin_weekly_topics({"action": "add", "week": WEEK, "title": "Results week",
                                  "body": "Banks report this week. Target 1800 on the leader."}, x_admin_key="k")
    assert e.value.status_code == 422 and e.value.detail["rule"] == "tip"
    out = main.admin_weekly_topics({"action": "add", "week": WEEK, "title": "Results week",
                                    "body": "Banks report this week; watch deposit growth more than loans."}, x_admin_key="k")
    assert [t["title"] for t in out["topics"]] == ["Results week"]


def test_the_job_mails_each_subscriber_once_a_week(monkeypatch):
    import main
    import mailer
    monkeypatch.setattr(main, "ADMIN_KEY", "k")
    monkeypatch.setattr(W, "live_sources", lambda week: dict(SOURCES))
    sent = []
    monkeypatch.setattr(mailer, "send", lambda to, subj, html, text, **kw: (sent.append((to, subj)) or (True, "ok")))
    done = accounts.complete_login(accounts.start_login("reader@example.com")["token"])
    u = accounts.user_for_session(done["session"])
    accounts.save_holdings(u["id"], [{"symbol": "TCS", "qty": 1}])
    with pytest.raises(HTTPException):
        main.run_weekly_brief(x_admin_key="wrong", week=WEEK)
    out = main.run_weekly_brief(x_admin_key="k", week=WEEK, send=True)
    assert (out["sent"], out["skipped"]) == (1, 0) and sent == [("reader@example.com", "The week in brief, 16–22 Nov 2026")]
    again = main.run_weekly_brief(x_admin_key="k", week=WEEK, send=True)
    assert (again["sent"], again["skipped"]) == (0, 1) and len(sent) == 1
    assert main.weekly_brief_issue(week=WEEK)["published"] is True
    assert main.weekly_brief_issues()["issues"][0]["week"] == WEEK
