"""
Accounts, sign-in links and saved portfolios.

This is the first thing in the project that holds something belonging to
somebody else — their address and what they own. So the tests here are less
about features than about the ways a login can be wrong: a link that works
twice, a link that never expires, a token that a copy of the database hands
to whoever reads it, a stranger able to find out who has an account, an
unsubscribe that needs a password.

Every one of those is a bug you only hear about after it has happened.
"""
import datetime as dt
import os
import tempfile

import pytest

import accounts as A


@pytest.fixture(autouse=True)
def fresh_db():
    with tempfile.TemporaryDirectory() as d:
        A.reset_for_tests(os.path.join(d, "accounts.db"))
        yield
        A.reset_for_tests(os.path.join(d, "accounts.db"))


def login(email="reader@example.com"):
    started = A.start_login(email)
    assert "token" in started, started
    done = A.complete_login(started["token"])
    assert "session" in done, done
    return done


# ── Addresses ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("bad", ["", "   ", "reader", "reader@", "@example.com",
                                 "a b@example.com", "reader@example", "x" * 250 + "@e.com"])
def test_a_bad_address_is_refused(bad):
    assert A.valid_email(bad) == ""
    assert "error" in A.start_login(bad)


def test_addresses_are_normalised_so_one_person_gets_one_account():
    """Reader@Example.com and reader@example.com are the same inbox."""
    A.complete_login(A.start_login("Reader@Example.COM ")["token"])
    second = A.complete_login(A.start_login("reader@example.com")["token"])
    assert second["user"]["email"] == "reader@example.com"
    assert A.stats()["users"] == 1


# ── Sign-in links ────────────────────────────────────────────────────────────

def test_a_link_works_once_and_then_never_again():
    """A forwarded email, a prefetching browser and a mail scanner all follow
    links. None of them may end up holding a session."""
    started = A.start_login("reader@example.com")
    assert "session" in A.complete_login(started["token"])
    again = A.complete_login(started["token"])
    assert "error" in again and "already been used" in again["error"]


def test_an_expired_link_is_refused():
    started = A.start_login("reader@example.com")
    conn = A._connect()
    with conn:
        conn.execute("UPDATE login_tokens SET expires_at=? WHERE email=?",
                     (A._iso(A._now() - dt.timedelta(minutes=1)), "reader@example.com"))
    assert "expired" in A.complete_login(started["token"])["error"]


def test_an_invented_token_is_refused():
    assert "error" in A.complete_login("not-a-real-token")
    assert "error" in A.complete_login("")


def test_tokens_are_never_stored_in_a_form_that_can_be_used():
    """A copy of this database must not be a set of working sign-in links."""
    started = A.start_login("reader@example.com")
    session = A.complete_login(started["token"])["session"]
    conn = A._connect()
    stored = [r[0] for r in conn.execute("SELECT token_hash FROM login_tokens")]
    stored += [r[0] for r in conn.execute("SELECT token_hash FROM sessions")]
    assert started["token"] not in stored
    assert session not in stored
    assert all(len(h) == 64 for h in stored)


def test_the_same_address_cannot_be_mailed_endlessly():
    """Protects the person whose address a stranger typed in, not just us."""
    for _ in range(A.MAX_LINKS_PER_EMAIL_PER_HOUR):
        assert "token" in A.start_login("reader@example.com")
    assert "error" in A.start_login("reader@example.com")
    # A different person is unaffected by their neighbour's flood.
    assert "token" in A.start_login("other@example.com")


# ── Sessions ─────────────────────────────────────────────────────────────────

def test_a_session_identifies_its_owner_and_nobody_else():
    a = login("a@example.com")
    b = login("b@example.com")
    assert A.user_for_session(a["session"])["email"] == "a@example.com"
    assert A.user_for_session(b["session"])["email"] == "b@example.com"
    assert A.user_for_session("nonsense") is None
    assert A.user_for_session("") is None


def test_logging_out_ends_that_session_only():
    first = login()["session"]
    second = A.complete_login(A.start_login("reader@example.com")["token"])["session"]
    assert A.logout(first) is True
    assert A.user_for_session(first) is None
    assert A.user_for_session(second) is not None


def test_an_expired_session_stops_working():
    s = login()["session"]
    conn = A._connect()
    with conn:
        conn.execute("UPDATE sessions SET expires_at=?",
                     (A._iso(A._now() - dt.timedelta(days=1)),))
    assert A.user_for_session(s) is None


# ── Portfolios ───────────────────────────────────────────────────────────────

def test_a_portfolio_is_saved_and_read_back():
    u = login()["user"]
    A.save_holdings(u["id"], [{"symbol": "infy", "qty": 10, "avg_price": 1400},
                              {"symbol": "TCS.NS", "qty": 5}])
    got = A.get_holdings(u["id"])
    assert [h["symbol"] for h in got] == ["INFY", "TCS"]
    assert got[0]["avg_price"] == 1400 and got[1]["avg_price"] is None


def test_saving_replaces_rather_than_merges():
    """A row somebody deleted must not come back. Nothing frightens a user
    off a portfolio page faster."""
    u = login()["user"]
    A.save_holdings(u["id"], [{"symbol": "INFY", "qty": 10},
                              {"symbol": "TCS", "qty": 5}])
    A.save_holdings(u["id"], [{"symbol": "INFY", "qty": 12}])
    got = A.get_holdings(u["id"])
    assert [h["symbol"] for h in got] == ["INFY"] and got[0]["qty"] == 12


def test_bad_rows_are_rejected_and_named_without_losing_the_good_ones():
    u = login()["user"]
    r = A.save_holdings(u["id"], [
        {"symbol": "INFY", "qty": 10},
        {"symbol": "BAD SYMBOL!", "qty": 1},
        {"symbol": "TCS", "qty": 0},
        {"symbol": "WIPRO", "qty": -5},
        {"symbol": "HDFCBANK", "qty": "not a number"},
    ])
    assert r["saved"] == 1
    assert {x["symbol"] for x in r["rejected"]} == {"BAD SYMBOL!", "TCS", "WIPRO", "HDFCBANK"}


def test_a_duplicated_scrip_keeps_one_line():
    """Pasting a broker CSV twice should not fail the whole import."""
    u = login()["user"]
    r = A.save_holdings(u["id"], [{"symbol": "INFY", "qty": 10},
                                  {"symbol": "INFY", "qty": 25}])
    assert r["saved"] == 1
    assert A.get_holdings(u["id"])[0]["qty"] == 25


def test_the_holding_limit_holds():
    u = login()["user"]
    r = A.save_holdings(u["id"], [{"symbol": f"SYM{i}", "qty": 1} for i in range(150)])
    assert r["saved"] == A.MAX_HOLDINGS


def test_one_persons_portfolio_is_not_anothers():
    a, b = login("a@example.com")["user"], login("b@example.com")["user"]
    A.save_holdings(a["id"], [{"symbol": "INFY", "qty": 10}])
    assert A.get_holdings(b["id"]) == []


# ── The daily send ───────────────────────────────────────────────────────────

def test_only_opted_in_people_holding_something_are_recipients():
    empty = login("empty@example.com")["user"]
    holder = login("holder@example.com")["user"]
    out = login("out@example.com")["user"]
    A.save_holdings(holder["id"], [{"symbol": "INFY", "qty": 1}])
    A.save_holdings(out["id"], [{"symbol": "TCS", "qty": 1}])
    A.set_digest_opt_in(out["id"], False)

    emails = {r["email"] for r in A.digest_recipients()}
    assert emails == {"holder@example.com"}
    assert empty["email"] not in emails


def test_a_rerun_does_not_mail_the_same_person_twice():
    """The job is not transactional, so this table is what makes a retry safe."""
    u = login()["user"]
    assert A.already_sent(u["id"], "daily", "2026-09-10") is False
    A.record_send(u["id"], "daily", "2026-09-10", True, "ok")
    assert A.already_sent(u["id"], "daily", "2026-09-10") is True
    assert A.already_sent(u["id"], "daily", "2026-09-11") is False


def test_a_failed_send_is_retried_rather_than_counted_as_done():
    u = login()["user"]
    A.record_send(u["id"], "daily", "2026-09-10", False, "provider 500")
    assert A.already_sent(u["id"], "daily", "2026-09-10") is False


def test_unsubscribe_needs_no_login_and_keeps_the_account():
    """Anything harder and people press the spam button instead."""
    u = login()["user"]
    A.save_holdings(u["id"], [{"symbol": "INFY", "qty": 1}])
    assert A.unsubscribe_by_token(u["unsub_token"]) is True
    assert A.digest_recipients() == []
    assert A.user_for_session  # account intact
    assert A.get_holdings(u["id"]) != []


def test_a_wrong_unsubscribe_token_changes_nothing():
    u = login()["user"]
    A.save_holdings(u["id"], [{"symbol": "INFY", "qty": 1}])
    assert A.unsubscribe_by_token("guessed") is False
    assert A.unsubscribe_by_token("") is False
    assert len(A.digest_recipients()) == 1


def test_housekeeping_removes_only_dead_rows():
    live = login()["session"]
    spent = A.start_login("other@example.com")["token"]
    A.complete_login(spent)
    removed = A.purge_expired()
    assert removed["login_tokens_removed"] >= 1
    assert A.user_for_session(live) is not None


def test_simultaneous_verification_creates_only_one_session():
    from concurrent.futures import ThreadPoolExecutor
    import threading
    token = A.start_login('reader@example.com')['token']
    barrier = threading.Barrier(4)

    def verify(_):
        A._connect()
        barrier.wait()
        try:
            return A.complete_login(token)
        finally:
            A._local.conn.close()
            A._local.conn = None

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(verify, range(4)))
    assert sum('session' in r for r in results) == 1
    assert A._connect().execute('SELECT COUNT(*) FROM sessions').fetchone()[0] == 1


# ── The watchlist ────────────────────────────────────────────────────────────
#
# The portfolio is what somebody owns; the watchlist is what they are thinking
# about. It lived in one browser's localStorage, which meant a cleared browser
# or a new phone started an empty list — the single easiest way to lose a
# reader who had already done the work of building one.

def test_a_watchlist_is_saved_and_read_back():
    me = login()["user"]["id"]
    A.save_watchlist(me, ["INFY", "reliance", "TCS.NS"])
    assert A.get_watchlist(me) == ["INFY", "RELIANCE", "TCS"]


def test_the_order_a_reader_built_the_list_in_survives():
    """Alphabetical would quietly reshuffle the list on every addition."""
    me = login()["user"]["id"]
    A.save_watchlist(me, ["ZOMATO", "INFY"])
    A.merge_watchlist(me, ["ADANIENT"])
    assert A.get_watchlist(me) == ["ZOMATO", "INFY", "ADANIENT"]


def test_saving_replaces_so_a_removal_sticks():
    me = login()["user"]["id"]
    A.save_watchlist(me, ["INFY", "TCS", "WIPRO"])
    A.save_watchlist(me, ["INFY", "WIPRO"])
    assert A.get_watchlist(me) == ["INFY", "WIPRO"]


def test_merging_keeps_both_lists_and_the_account_order():
    """Six names saved signed out meet forty saved on the account. Neither
    list may be the one that loses."""
    me = login()["user"]["id"]
    A.save_watchlist(me, ["INFY", "TCS"])
    out = A.merge_watchlist(me, ["TCS", "DMART"])
    assert out["added"] == 1
    assert A.get_watchlist(me) == ["INFY", "TCS", "DMART"]


def test_resaving_an_unchanged_list_does_not_reorder_it():
    me = login()["user"]["id"]
    A.save_watchlist(me, ["ZOMATO", "INFY", "TCS"])
    A.save_watchlist(me, ["ZOMATO", "INFY", "TCS"])
    assert A.get_watchlist(me) == ["ZOMATO", "INFY", "TCS"]


def test_unreadable_symbols_are_named_without_losing_the_good_ones():
    me = login()["user"]["id"]
    out = A.save_watchlist(me, ["INFY", "<script>", "", "TCS"])
    assert out["saved"] == 2
    assert A.get_watchlist(me) == ["INFY", "TCS"]
    assert [r["why"] for r in out["rejected"]] == ["unreadable symbol"] * 2


def test_a_duplicate_keeps_one_row():
    me = login()["user"]["id"]
    assert A.save_watchlist(me, ["INFY", "infy", "INFY.NS"])["saved"] == 1
    assert A.get_watchlist(me) == ["INFY"]


def test_the_watchlist_limit_holds_on_both_paths():
    me = login()["user"]["id"]
    assert A.save_watchlist(me, [f"S{i}" for i in range(A.MAX_WATCHLIST + 20)])["saved"] \
        == A.MAX_WATCHLIST
    out = A.merge_watchlist(me, ["EXTRA1", "EXTRA2"])
    assert out["added"] == 0
    assert len(A.get_watchlist(me)) == A.MAX_WATCHLIST


def test_one_persons_watchlist_is_not_anothers():
    mine = login("a@example.com")["user"]["id"]
    theirs = login("b@example.com")["user"]["id"]
    A.save_watchlist(mine, ["INFY"])
    A.save_watchlist(theirs, ["TCS"])
    assert A.get_watchlist(mine) == ["INFY"]
    assert A.get_watchlist(theirs) == ["TCS"]


def test_the_watchlist_and_the_portfolio_are_separate_lists():
    """Following a stock is not owning it, and the daily email must not start
    reporting on money somebody does not have."""
    me = login()["user"]["id"]
    A.save_watchlist(me, ["INFY"])
    A.save_holdings(me, [{"symbol": "TCS", "qty": 5}])
    assert A.get_watchlist(me) == ["INFY"]
    assert [h["symbol"] for h in A.get_holdings(me)] == ["TCS"]
    assert A.digest_recipients()[0]["id"] == me
