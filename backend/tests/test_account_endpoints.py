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


def test_console_delivery_is_not_reported_as_sent(main_mod, fresh, monkeypatch):
    import mailer
    from fastapi import HTTPException
    monkeypatch.setattr(mailer, 'provider', lambda: 'console')
    with pytest.raises(HTTPException) as error:
        main_mod.auth_request_link({'email': 'reader@example.com'})
    assert error.value.status_code == 503
    assert fresh == []


def test_failed_delivery_can_be_retried_without_exhausting_quota(main_mod, fresh, monkeypatch):
    import mailer
    from fastapi import HTTPException
    monkeypatch.setattr(mailer, 'send', lambda *args: (False, 'provider rejected'))
    for _ in range(7):
        with pytest.raises(HTTPException) as error:
            main_mod.auth_request_link({'email': 'reader@example.com'})
        assert error.value.status_code == 503
    assert A._connect().execute('SELECT COUNT(*) FROM login_tokens').fetchone()[0] == 0


def test_unconfigured_provider_does_not_mint_links(main_mod, fresh, monkeypatch):
    import mailer
    from fastapi import HTTPException
    monkeypatch.setattr(mailer, 'configured', lambda: False)
    with pytest.raises(HTTPException) as error:
        main_mod.auth_request_link({'email': 'reader@example.com'})
    assert error.value.status_code == 503
    assert fresh == []


# ── The watchlist ────────────────────────────────────────────────────────────

def test_a_watchlist_needs_a_session(main_mod, fresh):
    from fastapi import HTTPException
    for call in (lambda: main_mod.my_watchlist(authorization=None),
                 lambda: main_mod.save_my_watchlist({"symbols": ["INFY"]}, authorization=None),
                 lambda: main_mod.merge_my_watchlist({"symbols": ["INFY"]}, authorization=None)):
        with pytest.raises(HTTPException) as error:
            call()
        assert error.value.status_code == 401


def test_a_watchlist_saved_on_one_device_is_there_on_the_next(main_mod, fresh):
    """The whole point: the list is not a property of the browser that made it."""
    phone = sign_in(main_mod, fresh)
    main_mod.save_my_watchlist({"symbols": ["INFY", "TCS"]}, authorization=auth(phone))
    laptop = sign_in(main_mod, fresh)
    assert main_mod.my_watchlist(authorization=auth(laptop))["symbols"] == ["INFY", "TCS"]


def test_signing_in_keeps_the_list_built_before_signing_in(main_mod, fresh):
    token = sign_in(main_mod, fresh)
    main_mod.save_my_watchlist({"symbols": ["INFY", "TCS"]}, authorization=auth(token))
    out = main_mod.merge_my_watchlist({"symbols": ["DMART", "INFY"]}, authorization=auth(token))
    assert out["symbols"] == ["INFY", "TCS", "DMART"]


def test_a_removal_survives_a_reload(main_mod, fresh):
    token = sign_in(main_mod, fresh)
    main_mod.save_my_watchlist({"symbols": ["INFY", "TCS"]}, authorization=auth(token))
    main_mod.save_my_watchlist({"symbols": ["INFY"]}, authorization=auth(token))
    assert main_mod.my_watchlist(authorization=auth(token))["symbols"] == ["INFY"]


def test_a_malformed_payload_is_refused_rather_than_emptying_the_list(main_mod, fresh):
    from fastapi import HTTPException
    token = sign_in(main_mod, fresh)
    main_mod.save_my_watchlist({"symbols": ["INFY"]}, authorization=auth(token))
    with pytest.raises(HTTPException) as error:
        main_mod.save_my_watchlist({"symbols": "INFY"}, authorization=auth(token))
    assert error.value.status_code == 400
    assert main_mod.my_watchlist(authorization=auth(token))["symbols"] == ["INFY"]


def test_the_session_reports_what_is_saved(main_mod, fresh):
    token = sign_in(main_mod, fresh)
    main_mod.save_my_watchlist({"symbols": ["INFY", "TCS"]}, authorization=auth(token))
    me = main_mod.auth_me(authorization=auth(token))
    assert me["watchlist"] == 2
    assert me["holdings"] == 0


# ── Signing in with a typed code ─────────────────────────────────────────────

def code_from(sent) -> str:
    m = re.search(r"\b(\d{6})\b", sent[-1]["text"])
    assert m, sent[-1]["text"]
    return m.group(1)


def test_the_email_carries_a_code_and_a_link(main_mod, fresh):
    main_mod.auth_request_link({"email": "reader@example.com"})
    body = fresh[-1]["text"]
    assert re.search(r"\b\d{6}\b", body), "no code in the email"
    assert "token=" in body, "the link was dropped when the code arrived"
    assert re.search(r"\b\d{6}\b", fresh[-1]["subject"]), \
        "the code belongs in the subject, where a phone shows it without opening anything"


def test_the_code_signs_you_in_without_leaving_the_page(main_mod, fresh):
    main_mod.auth_request_link({"email": "reader@example.com"})
    out = main_mod.auth_verify_code({"email": "reader@example.com", "code": code_from(fresh)})
    assert out["user"]["email"] == "reader@example.com"
    assert main_mod.auth_me(authorization=auth(out["token"]))["email"] == "reader@example.com"


def test_a_wrong_code_is_refused(main_mod, fresh):
    from fastapi import HTTPException
    main_mod.auth_request_link({"email": "reader@example.com"})
    wrong = "000000" if code_from(fresh) != "000000" else "111111"
    with pytest.raises(HTTPException) as error:
        main_mod.auth_verify_code({"email": "reader@example.com", "code": wrong})
    assert error.value.status_code == 400


# ── Signing in with Google ───────────────────────────────────────────────────
#
# The browser hands over an ID token. Everything here is about refusing to
# believe it until Google has vouched for it: without the audience check, a
# token minted for any other site that uses Google sign-in would be accepted.

CLIENT_ID = "1234.apps.googleusercontent.com"


class _Answer:
    def __init__(self, status, payload):
        self.status_code = status
        self._payload = payload

    def json(self):
        return self._payload


def google_says(monkeypatch, payload, status=200):
    import requests
    monkeypatch.setattr(requests, "get",
                        lambda *a, **k: _Answer(status, payload))


def good_claims(**over):
    import time
    claims = {"aud": CLIENT_ID, "iss": "https://accounts.google.com",
              "email": "reader@example.com", "email_verified": "true",
              "exp": int(time.time()) + 600}
    claims.update(over)
    return claims


def test_google_sign_in_is_off_until_it_is_configured(main_mod, fresh, monkeypatch):
    from fastapi import HTTPException
    monkeypatch.setattr(main_mod, "GOOGLE_CLIENT_ID", "")
    with pytest.raises(HTTPException) as error:
        main_mod.auth_google({"credential": "anything"})
    assert error.value.status_code == 503
    assert main_mod.auth_config()["google_client_id"] == ""


def test_a_verified_google_account_signs_in(main_mod, fresh, monkeypatch):
    monkeypatch.setattr(main_mod, "GOOGLE_CLIENT_ID", CLIENT_ID)
    google_says(monkeypatch, good_claims())
    out = main_mod.auth_google({"credential": "an.id.token"})
    assert out["user"]["email"] == "reader@example.com"
    assert main_mod.auth_me(authorization=auth(out["token"]))["email"] == "reader@example.com"


def test_a_token_minted_for_another_site_is_refused(main_mod, fresh, monkeypatch):
    """Without this check, anyone running any site with Google sign-in could
    mint a token and present it here."""
    from fastapi import HTTPException
    monkeypatch.setattr(main_mod, "GOOGLE_CLIENT_ID", CLIENT_ID)
    google_says(monkeypatch, good_claims(aud="9999.apps.googleusercontent.com"))
    with pytest.raises(HTTPException) as error:
        main_mod.auth_google({"credential": "an.id.token"})
    assert error.value.status_code == 401
    assert A.stats()["users"] == 0


def test_an_unverified_google_address_is_refused(main_mod, fresh, monkeypatch):
    """An address Google has not confirmed is a claim, and this project mails
    people at the address they sign in with."""
    from fastapi import HTTPException
    monkeypatch.setattr(main_mod, "GOOGLE_CLIENT_ID", CLIENT_ID)
    google_says(monkeypatch, good_claims(email_verified="false"))
    with pytest.raises(HTTPException) as error:
        main_mod.auth_google({"credential": "an.id.token"})
    assert error.value.status_code == 401
    assert A.stats()["users"] == 0


def test_a_token_from_somewhere_other_than_google_is_refused(main_mod, fresh, monkeypatch):
    from fastapi import HTTPException
    monkeypatch.setattr(main_mod, "GOOGLE_CLIENT_ID", CLIENT_ID)
    google_says(monkeypatch, good_claims(iss="https://evil.example"))
    with pytest.raises(HTTPException) as error:
        main_mod.auth_google({"credential": "an.id.token"})
    assert error.value.status_code == 401


def test_an_expired_google_token_is_refused(main_mod, fresh, monkeypatch):
    import time
    from fastapi import HTTPException
    monkeypatch.setattr(main_mod, "GOOGLE_CLIENT_ID", CLIENT_ID)
    google_says(monkeypatch, good_claims(exp=int(time.time()) - 60))
    with pytest.raises(HTTPException) as error:
        main_mod.auth_google({"credential": "an.id.token"})
    assert error.value.status_code == 401


def test_a_token_google_rejects_is_refused(main_mod, fresh, monkeypatch):
    from fastapi import HTTPException
    monkeypatch.setattr(main_mod, "GOOGLE_CLIENT_ID", CLIENT_ID)
    google_says(monkeypatch, {"error": "invalid_token"}, status=400)
    with pytest.raises(HTTPException) as error:
        main_mod.auth_google({"credential": "forged"})
    assert error.value.status_code == 401


def test_google_being_unreachable_is_a_retry_not_a_rejection(main_mod, fresh, monkeypatch):
    from fastapi import HTTPException
    import requests
    monkeypatch.setattr(main_mod, "GOOGLE_CLIENT_ID", CLIENT_ID)

    def boom(*a, **k):
        raise OSError("network down")
    monkeypatch.setattr(requests, "get", boom)
    with pytest.raises(HTTPException) as error:
        main_mod.auth_google({"credential": "an.id.token"})
    assert error.value.status_code == 503


def test_signing_in_by_google_then_by_code_is_one_account(main_mod, fresh, monkeypatch):
    monkeypatch.setattr(main_mod, "GOOGLE_CLIENT_ID", CLIENT_ID)
    google_says(monkeypatch, good_claims())
    main_mod.auth_google({"credential": "an.id.token"})
    main_mod.auth_request_link({"email": "reader@example.com"})
    main_mod.auth_verify_code({"email": "reader@example.com", "code": code_from(fresh)})
    assert A.stats()["users"] == 1


# ── The planner, and who is signing it ───────────────────────────────────────

def profile_answers(**over):
    base = {"age": "25_34", "horizon": "10plus", "surplus": "25_40",
            "emergency": "6_12", "emi": "under20", "dependents": "0",
            "drawdown_action": "hold_plan", "max_fall": "30",
            "priority": "mostly_grow", "experience": "3_10",
            "purpose": "retirement", "mode": "sip", "amount": 25000}
    base.update(over)
    return base


def test_the_questionnaire_is_served_rather_than_kept_in_the_page(main_mod, fresh):
    """One source of truth for what was asked, so an answer recorded today
    still resolves to the same question in five years."""
    out = main_mod.planner_questions()
    ids = [q["id"] for q in out["questions"]]
    assert "horizon" in ids and "drawdown_action" in ids
    for q in out["questions"]:
        assert q["label"] and q["why"], q["id"]
        if q["kind"] == "choice":
            assert q["options"], q["id"]
    assert out["bands"][0]["band"] == "Conservative"


def test_a_profile_needs_a_session(main_mod, fresh):
    from fastapi import HTTPException
    for call in (lambda: main_mod.save_my_risk_profile({"answers": profile_answers()},
                                                       authorization=None),
                 lambda: main_mod.my_risk_profile(authorization=None)):
        with pytest.raises(HTTPException) as error:
            call()
        assert error.value.status_code == 401


def test_a_profile_is_assessed_recorded_and_handed_back(main_mod, fresh):
    token = sign_in(main_mod, fresh)
    out = main_mod.save_my_risk_profile({"answers": profile_answers()},
                                        authorization=auth(token))
    p = out["profile"]
    assert p["score"] == min(p["capacity"], p["tolerance"])
    assert p["band"] and p["binding_note"]
    assert main_mod.my_risk_profile(authorization=auth(token))["profile"]["band"] == p["band"]


def test_an_incomplete_questionnaire_is_refused_by_name(main_mod, fresh):
    from fastapi import HTTPException
    token = sign_in(main_mod, fresh)
    with pytest.raises(HTTPException) as error:
        main_mod.save_my_risk_profile({"answers": {"age": "25_34"}},
                                      authorization=auth(token))
    assert error.value.status_code == 400
    assert "horizon" in error.value.detail


def test_reassessing_keeps_the_earlier_basis(main_mod, fresh):
    token = sign_in(main_mod, fresh)
    main_mod.save_my_risk_profile({"answers": profile_answers()}, authorization=auth(token))
    main_mod.save_my_risk_profile(
        {"answers": profile_answers(drawdown_action="sell_all", max_fall="any")},
        authorization=auth(token))
    out = main_mod.my_risk_profile(history=True, authorization=auth(token))
    assert len(out["history"]) == 2
    assert out["profile"]["score"] < out["history"][1]["score"]


def test_the_page_says_who_is_advising_and_under_what_number(main_mod, monkeypatch):
    """A registration number a reader cannot see is a registration number they
    cannot check."""
    monkeypatch.setitem(main_mod.ADVISER, "name", "Example Advisers")
    monkeypatch.setitem(main_mod.ADVISER, "registration", "INA000000000")
    out = main_mod.adviser_details()
    assert out["configured"] is True
    assert out["registration"] == "INA000000000"


def test_an_unconfigured_deploy_says_so_rather_than_implying_a_registration(main_mod, monkeypatch):
    monkeypatch.setitem(main_mod.ADVISER, "name", "")
    monkeypatch.setitem(main_mod.ADVISER, "registration", "")
    assert main_mod.adviser_details()["configured"] is False
    # And the reader is still told to go and find an adviser, which is the
    # right advice from a page nobody has signed.
    assert "SEBI-registered adviser" in main_mod.disclaimer()


def test_a_signed_page_stops_telling_readers_to_find_an_adviser(main_mod, monkeypatch):
    monkeypatch.setitem(main_mod.ADVISER, "name", "Example Advisers")
    monkeypatch.setitem(main_mod.ADVISER, "registration", "INA000000000")
    text = main_mod.disclaimer()
    assert "consult a SEBI-registered adviser" not in text
    assert "market risk" in text.lower()
