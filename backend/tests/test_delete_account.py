"""
Deleting an account deletes the account.

The failure this guards against is a quiet one. The page says "everything has
been deleted", the person leaves, and a table nobody thought of still holds
their portfolio. Nothing errors. So the first test does not work from a list
of tables: it finds every table in the database that has a user_id column,
puts a row in each for two people, deletes one of them, and looks again. A
table added next year is covered the day it is added.
"""
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


def sign_in(email):
    """A real account with a real session, the way a reader gets one."""
    started = A.start_login(email)
    assert "token" in started, started
    done = A.complete_login(started["token"])
    assert "session" in done, done
    return done["user"], done["session"]


def conn():
    """The accounts database with every module's tables in it."""
    import advisors
    import wealth
    advisors._conn()
    wealth._conn()
    return A._connect()


def seed(c, table, uid, **fixed):
    """One row for this person in this table, whatever its columns are."""
    names, values = [], []
    for col in c.execute(f'PRAGMA table_info("{table}")').fetchall():
        name, kind = col["name"], (col["type"] or "").upper()
        if col["pk"] and kind == "INTEGER" and name != "user_id":
            continue                                # an autoincrement id
        if name in fixed:
            value = fixed[name]
        elif name == "user_id":
            value = uid
        elif "INT" in kind or "REAL" in kind:
            value = 7
        else:
            value = f"{name}-{uid}"
        names.append(name)
        values.append(value)
    marks = ",".join("?" * len(names))
    cur = c.execute(f'INSERT INTO "{table}" ({",".join(names)}) VALUES ({marks})', values)
    return cur.lastrowid


def count(c, table, where, *params):
    return c.execute(f'SELECT COUNT(*) AS n FROM "{table}" WHERE {where}', params).fetchone()["n"]


def test_every_table_that_names_the_person_is_emptied_of_them_and_nobody_else():
    gone, _ = sign_in("leaving@example.com")
    stays, _ = sign_in("staying@example.com")
    c = conn()
    tables = [t for t in A._tables_with(c, "user_id") if t != "users"]
    # The tables this was written against. If one of these is missing the test
    # is no longer looking at the real database and would pass by finding nothing.
    for expected in ("sessions", "holdings", "watchlist", "watchlist_sets", "risk_profiles",
                     "saved_screens", "send_log", "pro_waitlist", "experts", "chats",
                     "chat_messages", "wm_desks", "wm_clients", "wm_events", "wm_recs",
                     "wm_settlements", "wm_prices"):
        assert expected in tables, expected

    with c:
        for t in tables:
            for uid in (gone["id"], stays["id"]):
                if count(c, t, "user_id=?", uid) == 0 or t == "sessions":
                    seed(c, t, uid)
    before = {t: count(c, t, "user_id=?", stays["id"]) for t in tables}
    for t in tables:
        assert count(c, t, "user_id=?", gone["id"]) >= 1, t

    out = A.delete_account(gone["id"])
    assert out.get("ok") is True and out["email"] == "leaving@example.com"

    for t in tables:
        assert count(c, t, "user_id=?", gone["id"]) == 0, f"{t} still holds the deleted account"
        assert count(c, t, "user_id=?", stays["id"]) == before[t], f"{t} lost somebody else's rows"
    assert count(c, "users", "id=?", gone["id"]) == 0
    assert count(c, "users", "id=?", stays["id"]) == 1
    # Every table it emptied is named in what it reports.
    assert set(out["removed"]) >= set(tables) | {"users"}


def test_what_is_kept_under_the_address_goes_too():
    gone, _ = sign_in("leaving@example.com")
    sign_in("staying@example.com")
    A.start_login("leaving@example.com")            # an unused sign-in code, still live
    A.join_waitlist("leaving@example.com", source="test", plan="annual")
    A.join_waitlist("staying@example.com", source="test", plan="annual")
    c = conn()
    assert count(c, "login_tokens", "email=?", "leaving@example.com") >= 1

    A.delete_account(gone["id"])

    assert count(c, "login_tokens", "email=?", "leaving@example.com") == 0
    assert count(c, "pro_waitlist", "email=?", "leaving@example.com") == 0
    assert count(c, "pro_waitlist", "email=?", "staying@example.com") == 1


def test_a_conversation_goes_whole_whichever_side_the_person_was_on():
    seeker, _ = sign_in("asked@example.com")
    adviser, _ = sign_in("adviser@example.com")
    other, _ = sign_in("other@example.com")
    c = conn()
    with c:
        expert_id = seed(c, "experts", adviser["id"])
        chat = seed(c, "chats", seeker["id"], expert_id=expert_id)
        seed(c, "chat_messages", seeker["id"], chat_id=chat, sender="seeker")
        seed(c, "chat_messages", adviser["id"], chat_id=chat, sender="expert")
        seed(c, "chat_messages", None, chat_id=chat, sender="system")
        seed(c, "chat_reports", 0, chat_id=chat, reporter="seeker")
        kept = seed(c, "chats", other["id"], expert_id=expert_id)
        seed(c, "chat_messages", adviser["id"], chat_id=kept, sender="expert")

    A.delete_account(seeker["id"])

    # The whole conversation, including what the adviser and the system wrote in it.
    assert count(c, "chats", "id=?", chat) == 0
    assert count(c, "chat_messages", "chat_id=?", chat) == 0
    assert count(c, "chat_reports", "chat_id=?", chat) == 0
    # The adviser, and the adviser's conversation with somebody else, are untouched.
    assert count(c, "experts", "id=?", expert_id) == 1
    assert count(c, "chats", "id=?", kept) == 1
    assert count(c, "chat_messages", "chat_id=?", kept) == 1

    A.delete_account(adviser["id"])

    # An adviser who leaves takes the profile and the conversations held with them.
    assert count(c, "experts", "id=?", expert_id) == 0
    assert count(c, "chats", "id=?", kept) == 0
    assert count(c, "chat_messages", "chat_id=?", kept) == 0
    assert count(c, "users", "id=?", other["id"]) == 1


def test_a_client_record_on_somebody_elses_desk_is_theirs_and_stays():
    client, _ = sign_in("client@example.com")
    manager, _ = sign_in("manager@example.com")
    c = conn()
    with c:
        seed(c, "wm_clients", manager["id"], email="client@example.com")

    A.delete_account(client["id"])

    assert count(c, "wm_clients", "user_id=? AND email=?", manager["id"], "client@example.com") == 1


def test_the_session_dies_and_the_address_starts_again_from_nothing():
    user, session = sign_in("leaving@example.com")
    A.save_holdings(user["id"], [{"symbol": "TCS", "qty": 10, "avg_price": 3000}])
    assert A.user_for_session(session)["id"] == user["id"]

    A.delete_account(user["id"])

    assert A.user_for_session(session) is None
    again, _ = sign_in("leaving@example.com")
    assert again["id"] != user["id"]
    assert A.get_holdings(again["id"]) == []


def test_an_account_that_is_not_there_deletes_nothing():
    user, _ = sign_in("staying@example.com")
    for missing in (user["id"] + 999, None, "x"):
        assert "error" in A.delete_account(missing)
    assert count(conn(), "users", "id=?", user["id"]) == 1
    # And a second deletion of the same account is an error, not a second pass.
    assert A.delete_account(user["id"]).get("ok") is True
    assert "error" in A.delete_account(user["id"])


# ── the endpoint ───────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def main_mod():
    import main
    return main


def test_the_endpoint_wants_a_session_and_the_address_typed_again(main_mod):
    from fastapi import HTTPException
    user, session = sign_in("leaving@example.com")
    bearer = f"Bearer {session}"

    with pytest.raises(HTTPException) as nobody:
        main_mod.delete_my_account({"confirm": "leaving@example.com"}, None)
    assert nobody.value.status_code == 401

    for wrong in ({}, {"confirm": ""}, {"confirm": "DELETE"}, {"confirm": "someone@example.com"}):
        with pytest.raises(HTTPException) as refused:
            main_mod.delete_my_account(wrong, bearer)
        assert refused.value.status_code == 400
    assert A.user_for_session(session)["id"] == user["id"]      # still here

    # Typed the way a phone types it: a capital letter and a trailing space.
    assert main_mod.delete_my_account({"confirm": " Leaving@Example.com "}, bearer) == \
        {"ok": True, "deleted": True}

    with pytest.raises(HTTPException) as after:
        main_mod.delete_my_account({"confirm": "leaving@example.com"}, bearer)
    assert after.value.status_code == 401


def test_the_browser_is_allowed_to_send_it(main_mod):
    # An Authorization header makes this a request the browser asks about
    # first. test_cors.py is the reason this is checked: a method missing
    # from that list is a button that looks like it worked.
    assert "POST" in main_mod.ALLOWED_METHODS
