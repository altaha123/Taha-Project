"""
The account endpoints, end to end.

test_accounts.py proves the store. This proves the wiring: that a sign-in link
actually reaches the mailer, that the token it carries turns into a session,
that a bearer token is required where one should be, and that the daily job
does not mail the same person twice.

Handlers are called directly, as test_share_endpoints.py does — Starlette's
TestClient needs httpx, which this project does not otherwise depend on, and
calling the handler runs the same code with the same validation.
"""
import os
import re
import tempfile

import pytest

import accounts as A


@pytest.fixture(scope="module")
def main_mod():
    import main
    return main


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    """A clean database and a mailer that records instead of sending."""
    sent = []
    with tempfile.TemporaryDirectory() as d:
        A.reset_for_tests(os.path.join(d, "accounts.db"))
        import mailer
        monkeypatch.setattr(mailer, "send",
                            lambda to, subject, html, text="", unsubscribe_url="":
                            (sent.append({"to": to, "subject": subject, "html": html,
                                          "text": text, "unsub": unsubscribe_url}), (True, "test"))[1])
        monkeypatch.setattr(mailer, "provider", lambda: "test")
        yield sent


def link_token(sent) -> str:
    m = re.search(r"token=([A-Za-z0-9_\-]+)", sent[-1]["text"])
    assert m, sent[-1]["text"]
    return m.group(1)


def sign_in(main_mod, sent, email="reader@example.com") -> str:
    main_mod.auth_request_link({"email": email})
    out = main_mod.auth_verify({"token": link_token(sent)})
    return out["token"]


def auth(token: str) -> str:
    return f"Bearer {token}"


# ── Signing in ───────────────────────────────────────────────────────────────

def test_requesting_a_link_sends_exactly_one_email(main_mod, fresh):
    out = main_mod.auth_request_link({"email": "reader@example.com"})
    assert out["sent"] is True
    assert len(fresh) == 1
    assert fresh[0]["to"] == "reader@example.com"
    assert "sign-in" in fresh[0]["subject"].lower()


def test_the_answer_does_not_reveal_who_has_an_account(main_mod, fresh):
    """This endpoint is public. A different reply for a known address would
    turn it into a way to test whether somebody has signed up."""
    first = main_mod.auth_request_link({"email": "new@example.com"})
    main_mod.auth_verify({"token": link_token(fresh)})
    second = main_mod.auth_request_link({"email": "new@example.com"})
    assert first["message"] == second["message"]


def test_a_bad_address_is_refused_before_anything_is_sent(main_mod, fresh):
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as e:
        main_mod.auth_request_link({"email": "not-an-address"})
    assert e.value.status_code == 400
    assert fresh == []


def test_the_emailed_link_signs_you_in(main_mod, fresh):
    token = sign_in(main_mod, fresh)
    me = main_mod.auth_me(authorization=auth(token))
    assert me["email"] == "reader@example.com"
    assert me["holdings"] == 0


def test_the_link_cannot_be_spent_twice(main_mod, fresh):
    from fastapi import HTTPException
    main_mod.auth_request_link({"email": "reader@example.com"})
    tok = link_token(fresh)
    main_mod.auth_verify({"token": tok})
    with pytest.raises(HTTPException):
        main_mod.auth_verify({"token": tok})


# ── Who may call what ────────────────────────────────────────────────────────

@pytest.mark.parametrize("header", [None, "", "Bearer", "Bearer nonsense",
                                    "Basic abc", "nonsense"])
def test_the_portfolio_endpoints_need_a_real_session(main_mod, fresh, header):
    from fastapi import HTTPException
    for call in (lambda: main_mod.my_portfolio(authorization=header),
                 lambda: main_mod.save_my_portfolio({"holdings": []}, authorization=header),
                 lambda: main_mod.send_my_digest_now(authorization=header)):
        with pytest.raises(HTTPException) as e:
            call()
        assert e.value.status_code == 401


def test_one_session_cannot_read_anothers_portfolio(main_mod, fresh):
    a = sign_in(main_mod, fresh, "a@example.com")
    b = sign_in(main_mod, fresh, "b@example.com")
    main_mod.save_my_portfolio({"holdings": [{"symbol": "INFY", "qty": 10}]},
                               authorization=auth(a))
    assert main_mod.my_portfolio(authorization=auth(b))["holdings"] == []


def test_signing_out_ends_the_session(main_mod, fresh):
    from fastapi import HTTPException
    token = sign_in(main_mod, fresh)
    assert main_mod.auth_logout(authorization=auth(token))["ok"] is True
    with pytest.raises(HTTPException):
        main_mod.auth_me(authorization=auth(token))


# ── The portfolio ────────────────────────────────────────────────────────────

def test_a_portfolio_round_trips(main_mod, fresh):
    token = sign_in(main_mod, fresh)
    out = main_mod.save_my_portfolio(
        {"holdings": [{"symbol": "infy", "qty": 10, "avg_price": 1400},
                      {"symbol": "TCS", "qty": 5}]}, authorization=auth(token))
    assert out["saved"] == 2
    assert [h["symbol"] for h in main_mod.my_portfolio(authorization=auth(token))["holdings"]] \
        == ["INFY", "TCS"]


def test_a_malformed_body_is_a_400_not_a_500(main_mod, fresh):
    from fastapi import HTTPException
    token = sign_in(main_mod, fresh)
    for body in ({}, {"holdings": "INFY"}, {"holdings": None}):
        with pytest.raises(HTTPException) as e:
            main_mod.save_my_portfolio(body, authorization=auth(token))
        assert e.value.status_code == 400


# ── Unsubscribing ────────────────────────────────────────────────────────────

def test_unsubscribe_works_from_the_link_alone(main_mod, fresh):
    """No login, one click. Anything harder and people press spam instead."""
    token = sign_in(main_mod, fresh)
    main_mod.save_my_portfolio({"holdings": [{"symbol": "INFY", "qty": 1}]},
                               authorization=auth(token))
    unsub = A.user_for_session(token)["unsub_token"]
    assert A.digest_recipients()
    assert main_mod.unsubscribe_post(token=unsub)["ok"] is True
    assert A.digest_recipients() == []
    # The account and the holdings survive; only the email stops.
    assert main_mod.my_portfolio(authorization=auth(token))["holdings"]


def test_a_bad_unsubscribe_link_says_so_without_erroring(main_mod, fresh):
    page = main_mod.unsubscribe(token="guessed")
    assert page.status_code == 200
    assert b"not valid" in page.body


# ── The daily job ────────────────────────────────────────────────────────────

@pytest.fixture
def one_subscriber(main_mod, fresh, monkeypatch):
    import pandas as pd
    token = sign_in(main_mod, fresh, "holder@example.com")
    main_mod.save_my_portfolio({"holdings": [{"symbol": "AAA", "qty": 10}]},
                               authorization=auth(token))
    closes = [100.0] * 60 + [100.0, 110.0]
    df = pd.DataFrame({"Open": closes, "High": closes, "Low": closes, "Close": closes,
                       "Volume": [1000] * len(closes)},
                      index=pd.bdate_range("2025-01-01", periods=len(closes)))
    monkeypatch.setattr(main_mod, "resolve", lambda s: (s, None, df))
    fresh.clear()
    return token


def test_the_job_sends_one_email_per_subscriber(main_mod, fresh, one_subscriber, monkeypatch):
    monkeypatch.setattr(main_mod, "ADMIN_KEY", "")
    out = main_mod.run_daily_digest()
    assert out["sent"] == 1 and out["failed"] == 0
    assert fresh[0]["to"] == "holder@example.com"
    assert "Portfolio up" in fresh[0]["subject"]
    assert fresh[0]["unsub"], "every bulk email needs a working unsubscribe"


def test_running_the_job_twice_does_not_mail_twice(main_mod, fresh, one_subscriber, monkeypatch):
    """Webhooks retry, schedulers double-fire, and a crashed job gets re-run."""
    monkeypatch.setattr(main_mod, "ADMIN_KEY", "")
    main_mod.run_daily_digest()
    again = main_mod.run_daily_digest()
    assert again["sent"] == 0 and again["skipped"] == 1
    assert len(fresh) == 1


def test_a_holiday_run_does_not_repeat_the_last_session(main_mod, fresh,
                                                       one_subscriber, monkeypatch):
    """The market is shut, the job still fires, and the feed still ends on
    Friday's close. Nobody may be mailed Friday's numbers twice."""
    monkeypatch.setattr(main_mod, "ADMIN_KEY", "")
    first = main_mod.run_daily_digest()
    assert first["sent"] == 1

    holiday = main_mod.run_daily_digest()          # same data, next calendar day
    assert holiday["session"] == first["session"]
    assert holiday["sent"] == 0 and holiday["skipped"] == 1
    assert len(fresh) == 1


def test_a_dry_run_sends_nothing(main_mod, fresh, one_subscriber, monkeypatch):
    monkeypatch.setattr(main_mod, "ADMIN_KEY", "")
    out = main_mod.run_daily_digest(dry_run=True)
    assert out["sent"] == 1 and fresh == []
    # And having counted nobody as mailed, a real run still goes out.
    assert main_mod.run_daily_digest()["sent"] == 1


def test_the_job_is_guarded_by_the_admin_key(main_mod, fresh, one_subscriber, monkeypatch):
    from fastapi import HTTPException
    monkeypatch.setattr(main_mod, "ADMIN_KEY", "s3cret")
    with pytest.raises(HTTPException) as e:
        main_mod.run_daily_digest()
    assert e.value.status_code == 403
    assert main_mod.run_daily_digest(x_admin_key="s3cret")["sent"] == 1


def test_somebody_who_opted_out_is_not_mailed(main_mod, fresh, one_subscriber, monkeypatch):
    monkeypatch.setattr(main_mod, "ADMIN_KEY", "")
    A.unsubscribe_by_token(A.user_for_session(one_subscriber)["unsub_token"])
    assert main_mod.run_daily_digest()["recipients"] == 0
    assert fresh == []


def test_a_broken_symbol_fails_one_email_not_the_run(main_mod, fresh, one_subscriber, monkeypatch):
    monkeypatch.setattr(main_mod, "ADMIN_KEY", "")

    def boom(_):
        raise RuntimeError("provider down")
    monkeypatch.setattr(main_mod, "resolve", boom)

    out = main_mod.run_daily_digest()
    assert out["sent"] == 0
    assert fresh == []
    # Nothing was recorded as delivered, so tomorrow's run tries again.
    assert out["skipped"] + out["failed"] == 1


def test_send_test_mails_the_signed_in_reader(main_mod, fresh, one_subscriber):
    out = main_mod.send_my_digest_now(authorization=auth(one_subscriber))
    assert out["sent"] is True
    assert fresh[-1]["to"] == "holder@example.com"


def test_send_test_needs_a_saved_portfolio(main_mod, fresh):
    from fastapi import HTTPException
    token = sign_in(main_mod, fresh, "empty@example.com")
    with pytest.raises(HTTPException) as e:
        main_mod.send_my_digest_now(authorization=auth(token))
    assert e.value.status_code == 400
