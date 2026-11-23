"""
Connect your broker: the rules that keep a member's money safe.

Every failure worth testing here is quiet. An order sent twice looks like two
orders the member placed. A token kept in the clear looks like any other
column. A login finished by somebody else's redirect links the wrong account
and says "Connected". An order the broker never confirmed, retried on its
own, is a second position nobody asked for. None of these crash.

The broker is a fake (FakeBroker) that records what it was asked; the Dhan
module's own requests are checked in test_broker_dhan.py.
"""
import os
import tempfile

import pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException

import accounts
import brokers as B

KEY = Fernet.generate_key().decode()


class FakeBroker:
    ID = "dhan"
    LABEL = "Dhan"

    def __init__(self):
        self.placed = []
        self.cancelled = []
        self.place_raises = None
        self.book = []
        self.by_ref = {}
        self.individual = False
        self.token = "tok-SECRET-123"

    def available(self):
        return True

    def needs_allowlist(self):
        return self.individual

    def start_login(self):
        return {"login_url": "https://broker.example/login?c=1", "ref": "c1"}

    def finish_login(self, token_id):
        return {"client_id": "1100223344", "client_name": "A MEMBER",
                "access_token": self.token, "expires_at": "2099-01-01T00:00:00+00:00"}

    def instrument(self, symbol):
        return {"TCS": "11536", "INFY": "1594"}.get(symbol)

    def place(self, sess, o):
        assert sess["token"] == self.token
        self.placed.append(o)
        if self.place_raises:
            raise self.place_raises
        return {"broker_order_id": f"9{len(self.placed)}", "status": "open", "broker_status": "PENDING"}

    def cancel(self, sess, boid):
        self.cancelled.append(boid)
        return {"broker_order_id": boid, "status": "cancelled", "broker_status": "CANCELLED"}

    def order(self, sess, boid):
        return {"broker_order_id": boid, "status": "filled", "broker_status": "TRADED",
                "filled_qty": 10, "avg_price": 3851.5}

    def order_by_ref(self, sess, ref):
        return self.by_ref.get(ref)

    def orders(self, sess):
        return list(self.book)

    def holdings(self, sess):
        return [{"symbol": "TCS", "qty": 10, "avg_price": 3500.0},
                {"symbol": "INFY", "qty": 5, "avg_price": 1400.0}]

    def positions(self, sess):
        return []

    def funds(self, sess):
        return {"available": 100000.0}


@pytest.fixture
def fake(monkeypatch):
    with tempfile.TemporaryDirectory() as d:
        accounts.reset_for_tests(os.path.join(d, "accounts.db"))
        f = FakeBroker()
        monkeypatch.setattr(B, "ADAPTERS", {"dhan": f})
        monkeypatch.setattr(B, "PRICE", None)
        monkeypatch.setenv("BROKER_TOKEN_KEY", KEY)
        monkeypatch.setenv("BROKER_TRADING", "on")
        for k in ("BROKER_MEMBERS", "BROKER_MAX_ORDER_VALUE", "BROKER_MAX_ORDERS_PER_DAY",
                  "BROKER_MAX_ORDERS_PER_MINUTE", "ADMIN_KEY"):
            monkeypatch.delenv(k, raising=False)
        yield f
        accounts.reset_for_tests(os.path.join(d, "accounts.db"))


def member(email="a@example.com"):
    done = accounts.complete_login(accounts.start_login(email)["token"])
    return accounts.user_for_session(done["session"]), done["session"]


def connected(email="a@example.com"):
    u, s = member(email)
    B.start_connect(u, "dhan")
    B.finish_connect(u, "dhan", "token-id-1")
    return u, s


_n = [0]


def ticket(**kw):
    _n[0] += 1
    o = dict(symbol="TCS", side="BUY", qty=10, type="LIMIT", price=3850, product="CNC",
             client_ref=f"ref-{_n[0]:08d}", ref_price=3850)
    o.update(kw)
    return o


# ── Connecting ──────────────────────────────────────────────────────────────

def test_the_token_is_never_stored_in_the_clear(fake):
    u, _ = connected()
    raw = accounts._connect().execute("SELECT token_enc FROM broker_links").fetchone()["token_enc"]
    assert fake.token not in raw
    link = B.link(u["id"])
    assert fake.token not in repr(link)
    assert link["client_id"].endswith("3344") and "1100" not in link["client_id"]


def test_a_login_must_have_been_started_here_by_this_member(fake):
    u, _ = member()
    with pytest.raises(ValueError):
        B.finish_connect(u, "dhan", "token-id-from-somewhere")
    other, _ = member("b@example.com")
    B.start_connect(other, "dhan")
    with pytest.raises(ValueError):            # b started it; a cannot finish it
        B.finish_connect(u, "dhan", "token-id")
    assert B.link(u["id"]) is None


def test_a_started_login_finishes_once(fake):
    u, _ = member()
    B.start_connect(u, "dhan")
    B.finish_connect(u, "dhan", "t1")
    with pytest.raises(ValueError):
        B.finish_connect(u, "dhan", "t1")


def test_no_key_means_no_connections(fake, monkeypatch):
    monkeypatch.delenv("BROKER_TOKEN_KEY")
    u, _ = member()
    assert B.config(u)["connect"] is False
    with pytest.raises(B.NotSwitchedOn):
        B.start_connect(u, "dhan")


def test_a_rotated_key_asks_for_a_reconnect_not_a_crash(fake, monkeypatch):
    u, _ = connected()
    monkeypatch.setenv("BROKER_TOKEN_KEY", Fernet.generate_key().decode())
    with pytest.raises(B.NeedsReconnect):
        B.funds(u["id"])


def test_an_individual_api_key_is_closed_without_a_member_list(fake, monkeypatch):
    fake.individual = True
    u, _ = member("owner@example.com")
    with pytest.raises(PermissionError):
        B.start_connect(u, "dhan")
    monkeypatch.setenv("BROKER_MEMBERS", "Owner@Example.com")
    assert B.start_connect(u, "dhan")["login_url"]
    stranger, _ = member("someone@example.com")
    with pytest.raises(PermissionError):
        B.start_connect(stranger, "dhan")


def test_disconnect_forgets_the_token(fake):
    u, _ = connected()
    assert B.disconnect(u["id"]) is True
    assert accounts._connect().execute("SELECT COUNT(*) c FROM broker_links").fetchone()["c"] == 0
    with pytest.raises(LookupError):
        B.funds(u["id"])


# ── The order ticket's rules ────────────────────────────────────────────────

@pytest.mark.parametrize("change, words", [
    (dict(qty=0), "at least 1"),
    (dict(qty=2.5), "whole number"),
    (dict(qty=-3), "whole number"),
    (dict(side="HOLD"), "Buy or Sell"),
    (dict(type="LIMIT", price=None), "price"),
    (dict(type="SL", price=3900, trigger=None), "trigger"),
    (dict(type="SL", side="BUY", price=3800, trigger=3850), "at or above the trigger"),
    (dict(type="SL", side="SELL", price=3900, trigger=3850), "at or below the trigger"),
    (dict(price=385), "typo"),                       # 3850 typed as 385
    (dict(price=38500), "typo"),
    (dict(qty=1000), "limited to"),                  # ₹38.5 lakh
    (dict(client_ref="x"), "reference"),
    (dict(product="MTF"), "Delivery or Intraday"),
])
def test_the_ticket_refuses_with_a_sentence(change, words):
    with pytest.raises(ValueError) as e:
        B.clean_order(ticket(**change))
    assert words.lower() in str(e.value).lower()


def test_a_market_order_is_valued_at_the_servers_price_not_the_pages(fake):
    # The page says ₹10; the market says ₹3,850. 200 shares is ₹7.7 lakh.
    with pytest.raises(ValueError, match="limited to"):
        B.clean_order(ticket(type="MARKET", price=None, qty=200, ref_price=10), market_price=3850)


def test_a_market_order_with_no_price_anywhere_is_refused():
    with pytest.raises(ValueError, match="Could not check the price"):
        B.clean_order(ticket(type="MARKET", price=None, ref_price=None))


def test_market_and_sl_m_send_no_limit_price():
    o = B.clean_order(ticket(type="SL-M", price=9999, trigger=3800))
    assert o["price"] is None and o["trigger"] == 3800


def test_nothing_from_altaha_rides_along_on_an_order(fake):
    """The order is what the member typed: symbol, side, quantity, price. A
    score, a pick or a target field from the page is not passed on."""
    u, _ = connected()
    B.place_order(u, ticket(target=4200, stop=3700, score=88, pick="momentum"))
    sent = fake.placed[0]
    assert not {"target", "stop", "score", "pick"} & set(sent)


# ── Sending ─────────────────────────────────────────────────────────────────

def test_an_order_is_sent_once_however_many_times_it_arrives(fake):
    u, _ = connected()
    t = ticket()
    first = B.place_order(u, t)
    again = B.place_order(u, dict(t))
    assert len(fake.placed) == 1
    assert again["duplicate"] is True and again["id"] == first["id"]
    assert first["status"] == "open" and first["broker_order_id"] == "91"


def test_an_unconfirmed_order_is_unknown_and_never_retried(fake):
    u, _ = connected()
    fake.place_raises = B.BrokerUnreachable("timeout")
    o = B.place_order(u, ticket())
    assert o["status"] == "unknown" and "check" in o["message"].lower()
    assert len(fake.placed) == 1
    # The broker did get it: the next look finds it by our correlation id.
    corr = fake.placed[0]["correlation_id"]
    fake.by_ref[corr] = {"broker_order_id": "777", "status": "filled", "broker_status": "TRADED"}
    after = B.order(u["id"], o["id"])
    assert after["status"] == "filled" and after["broker_order_id"] == "777"
    assert len(fake.placed) == 1


def test_a_refusal_is_recorded_with_the_brokers_reason(fake):
    u, _ = connected()
    fake.place_raises = B.BrokerError("Insufficient funds", "DH-906")
    o = B.place_order(u, ticket())
    assert o["status"] == "rejected" and o["message"] == "Insufficient funds"


def test_an_ended_broker_session_asks_for_a_reconnect(fake):
    u, _ = connected()
    fake.place_raises = B.NeedsReconnect("ended")
    with pytest.raises(B.NeedsReconnect):
        B.place_order(u, ticket())
    assert B.link(u["id"])["expired"] is True
    with pytest.raises(B.NeedsReconnect):
        B.funds(u["id"])


def test_orders_stay_off_until_switched_on(fake, monkeypatch):
    u, _ = connected()
    monkeypatch.setenv("BROKER_TRADING", "")
    with pytest.raises(B.NotSwitchedOn):
        B.place_order(u, ticket())
    assert fake.placed == []
    assert B.funds(u["id"])["available"] == 100000.0      # reading still works


def test_the_owners_halt_stops_every_order_at_once(fake):
    u, _ = connected()
    B.set_halt(True)
    with pytest.raises(B.NotSwitchedOn, match="paused"):
        B.place_order(u, ticket())
    B.set_halt(False)
    assert B.place_order(u, ticket())["status"] == "open"


def test_a_member_can_pause_their_own_account(fake):
    u, _ = connected()
    B.set_paused(u["id"], True)
    with pytest.raises(PermissionError):
        B.place_order(u, ticket())
    B.set_paused(u["id"], False)
    assert B.place_order(u, ticket())["status"] == "open"


def test_orders_per_day_and_per_minute_are_capped(fake, monkeypatch):
    u, _ = connected()
    monkeypatch.setenv("BROKER_MAX_ORDERS_PER_MINUTE", "3")
    for _ in range(3):
        B.place_order(u, ticket())
    with pytest.raises(B.RateLimited):
        B.place_order(u, ticket())
    monkeypatch.setenv("BROKER_MAX_ORDERS_PER_MINUTE", "100")
    monkeypatch.setenv("BROKER_MAX_ORDERS_PER_DAY", "4")
    B.place_order(u, ticket())
    with pytest.raises(B.RateLimited, match="today"):
        B.place_order(u, ticket())
    assert len(fake.placed) == 4


def test_a_stock_the_broker_cannot_trade_is_refused_before_sending(fake):
    u, _ = connected()
    with pytest.raises(ValueError, match="cannot be traded"):
        B.place_order(u, ticket(symbol="NOSUCH"))
    assert fake.placed == []


def test_one_members_order_is_not_anothers(fake):
    u, _ = connected()
    o = B.place_order(u, ticket())
    v, _ = connected("b@example.com")
    with pytest.raises(LookupError):
        B.order(v["id"], o["id"])


def test_the_order_book_marks_what_was_placed_here(fake):
    u, _ = connected()
    o = B.place_order(u, ticket())
    fake.book = [
        {"broker_order_id": "91", "symbol": "TCS", "status": "filled", "broker_status": "TRADED"},
        {"broker_order_id": "55", "symbol": "INFY", "status": "open", "broker_status": "PENDING"},
    ]
    rows = B.orders(u["id"])["orders"]
    assert [r["via_altaha"] for r in rows] == [True, False]
    assert B.order(u["id"], o["id"])["status"] == "filled"     # reconciled from the book


def test_copying_holdings_replaces_the_altaha_portfolio(fake):
    u, _ = connected()
    accounts.save_holdings(u["id"], [{"symbol": "WIPRO", "qty": 1}])
    out = B.copy_holdings(u["id"])
    assert out["saved"] == 2
    assert [h["symbol"] for h in accounts.get_holdings(u["id"])] == ["INFY", "TCS"]


# ── HTTP ────────────────────────────────────────────────────────────────────

def test_an_ended_broker_session_is_409_never_401(fake):
    """401 tells the site the Altaha session is over and signs the member
    out. A broker session ending is not that."""
    import broker_routes as R
    u, s = connected()
    fake.place_raises = B.NeedsReconnect("ended")
    with pytest.raises(HTTPException) as e:
        R.broker_place(ticket(), authorization="Bearer " + s)
    assert e.value.status_code == 409 and e.value.detail["reconnect"] is True


def test_the_routes_need_a_signed_in_member(fake):
    import broker_routes as R
    with pytest.raises(HTTPException) as e:
        R.broker_me(authorization=None)
    assert e.value.status_code == 401
    assert R.broker_config(authorization=None)["connect"] is True


def test_the_admin_routes_are_closed_without_a_key(fake, monkeypatch):
    import broker_routes as R
    with pytest.raises(HTTPException):
        R.admin_broker_halt({"halted": True}, key="", x_admin_key=None)
    monkeypatch.setenv("ADMIN_KEY", "k")
    assert R.admin_broker_halt({"halted": True}, key="k", x_admin_key=None)["halted"] is True
    assert R.admin_broker(key="k", x_admin_key=None)["halted"] is True


def test_an_order_cut_off_mid_send_is_settled_not_left_sending(fake):
    """The instance can die between writing the row and hearing from the
    broker. Ten minutes on, with no record at the broker, it was not placed."""
    import datetime as dt
    u, _ = connected()
    o = B.place_order(u, ticket())
    old = (accounts._now() - dt.timedelta(minutes=11)).isoformat()
    conn = accounts._connect()
    with conn:
        conn.execute("UPDATE broker_orders SET status='sending', broker_order_id=NULL, created_at=? "
                     "WHERE id=?", (old, o["id"]))
    after = B.order(u["id"], o["id"])
    assert after["status"] == "rejected" and "no record" in after["message"]


def test_one_brokers_test_key_does_not_close_another(fake, monkeypatch):
    """Zerodha on its owner-only app must not lock members out of a Dhan
    partner connection that is open to everyone."""
    closed = FakeBroker()
    closed.ID, closed.LABEL, closed.individual = "zerodha", "Zerodha", True
    monkeypatch.setattr(B, "ADAPTERS", {"dhan": fake, "zerodha": closed})
    u, _ = member()
    cfg = {b["id"]: b["allowed"] for b in B.config(u)["brokers"]}
    assert cfg == {"dhan": True, "zerodha": False}
    assert B.start_connect(u, "dhan")["login_url"]
    with pytest.raises(PermissionError):
        B.start_connect(u, "zerodha")


def test_the_correlation_id_is_letters_and_digits_under_twenty(fake):
    import re
    u, _ = connected()
    B.place_order(u, ticket())
    corr = fake.placed[0]["correlation_id"]
    assert re.fullmatch(r"[A-Za-z0-9]{1,20}", corr)
