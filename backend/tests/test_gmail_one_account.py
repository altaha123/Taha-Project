"""One Gmail inbox is one account, however the address is spelled."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))

import accounts  # noqa: E402


def _fresh(tmp_path):
    accounts.reset_for_tests(str(tmp_path / "a.db"))


def test_spellings_of_one_gmail_inbox_share_a_key():
    k = accounts.gmail_key
    assert k("First.Last@gmail.com") == k("firstlast@gmail.com") == k("first.last+x@googlemail.com")
    assert k("firstlast@gmail.com") != k("firstlast2@gmail.com")
    assert k("first.last@outlook.com") == ""          # dots matter everywhere else


def test_google_with_dots_and_a_typed_address_without_them_are_one_account(tmp_path):
    _fresh(tmp_path)
    a = accounts.complete_oauth_login("first.last@gmail.com")["user"]
    accounts.save_holdings(accounts.user_for_session(
        accounts.complete_oauth_login("first.last@gmail.com")["session"])["id"],
        [{"symbol": "TCS", "qty": 1}])
    b = accounts.complete_oauth_login("firstlast@gmail.com")
    user = accounts.user_for_session(b["session"])
    assert user["email"] == a["email"]
    assert accounts.get_holdings(user["id"])[0]["symbol"] == "TCS"


def test_where_two_accounts_already_exist_the_one_with_the_work_wins(tmp_path):
    _fresh(tmp_path)
    conn = accounts._connect()
    with conn:
        for e in ("firstlast@gmail.com", "first.last@gmail.com"):       # made before the fix
            conn.execute("INSERT INTO users(email,created_at,unsub_token) VALUES(?,?,?)", (e, "2026-01-01", e))
    ids = {r["email"]: r["id"] for r in conn.execute("SELECT * FROM users")}
    accounts.save_holdings(ids["first.last@gmail.com"], [{"symbol": "INFY", "qty": 2}])
    for typed in ("firstlast@gmail.com", "first.last@gmail.com", "First.Last+a@googlemail.com"):
        u = accounts.user_for_session(accounts.complete_oauth_login(typed)["session"])
        assert u["id"] == ids["first.last@gmail.com"], typed


def test_other_domains_are_left_exactly_as_typed(tmp_path):
    _fresh(tmp_path)
    a = accounts.user_for_session(accounts.complete_oauth_login("a.b@example.com")["session"])
    b = accounts.user_for_session(accounts.complete_oauth_login("ab@example.com")["session"])
    assert a["id"] != b["id"]
