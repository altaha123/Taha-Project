"""
broker_zerodha.py: what goes to Kite Connect, and how its answers are read.

Checked against Kite Connect v3: form fields not JSON, `X-Kite-Version: 3`
and `Authorization: token key:access_token` on every call, the session
checksum is SHA-256 of key + request_token + secret (the secret itself is
never sent), a TokenException is an ended session, and Kite's own order
names (MIS for intraday, SL-M) go out as Kite spells them.
"""
import datetime as dt
import hashlib

import pytest

import broker_zerodha as Z
import brokers as B

SESS = {"client_id": "AB1234", "token": "member-token"}


@pytest.fixture
def wire(monkeypatch):
    calls, answers = [], []

    def fake(method, url, headers, data=None, timeout=None):
        calls.append({"method": method, "url": url, "headers": headers, "data": data})
        status, body = answers.pop(0) if answers else (200, {"status": "success", "data": {}})
        return status, body

    monkeypatch.setattr(Z, "_http", fake)
    monkeypatch.setenv("KITE_API_KEY", "kkey")
    monkeypatch.setenv("KITE_API_SECRET", "ksecret")
    monkeypatch.delenv("KITE_ALL_MEMBERS", raising=False)
    return calls, answers


def ok(data):
    return 200, {"status": "success", "data": data}


def order(**kw):
    o = dict(symbol="TCS", side="BUY", qty=10, type="LIMIT", product="CNC", validity="DAY",
             price=3850.0, trigger=None, security_id="TCS", correlation_id="alt12x3f9a1b")
    o.update(kw)
    return o


def test_the_login_page_is_kites_with_the_apps_key(wire):
    out = Z.start_login()
    assert out["login_url"] == "https://kite.zerodha.com/connect/login?v=3&api_key=kkey"


def test_finishing_a_login_sends_a_checksum_never_the_secret(wire):
    calls, answers = wire
    answers.append(ok({"user_id": "AB1234", "user_name": "A Member", "access_token": "at-1"}))
    out = Z.finish_login("req-9")
    c = calls[0]
    assert c["method"] == "POST" and c["url"] == "https://api.kite.trade/session/token"
    assert c["data"]["checksum"] == hashlib.sha256(b"kkeyreq-9ksecret").hexdigest()
    assert "ksecret" not in repr(c)
    assert out["client_id"] == "AB1234" and out["access_token"] == "at-1"


def test_a_session_ends_at_six_in_the_morning_india_time():
    at = dt.datetime(2026, 11, 23, 10, 0, tzinfo=dt.timezone.utc)          # 15:30 IST
    assert Z._next_flush_utc(at) == "2026-11-24T00:30:00+00:00"            # 06:00 IST next day
    early = dt.datetime(2026, 11, 23, 0, 0, tzinfo=dt.timezone.utc)        # 05:30 IST
    assert Z._next_flush_utc(early) == "2026-11-23T00:30:00+00:00"


def test_an_app_not_cleared_for_other_clients_is_closed_by_default(wire, monkeypatch):
    assert Z.needs_allowlist() is True
    monkeypatch.setenv("KITE_ALL_MEMBERS", "on")
    assert Z.needs_allowlist() is False


def test_an_order_is_form_fields_in_kites_names(wire):
    calls, answers = wire
    answers.append(ok({"order_id": "151220000000000"}))
    out = Z.place(SESS, order(type="SL-M", price=None, trigger=3800.0, product="INTRADAY", side="SELL"))
    c = calls[0]
    assert c["url"] == "https://api.kite.trade/orders/regular"
    assert c["headers"]["Authorization"] == "token kkey:member-token"
    assert c["headers"]["X-Kite-Version"] == "3"
    d = c["data"]
    assert d["tradingsymbol"] == "TCS" and d["exchange"] == "NSE"
    assert d["transaction_type"] == "SELL" and d["order_type"] == "SL-M" and d["product"] == "MIS"
    assert d["trigger_price"] == "3800.0" and "price" not in d
    assert d["tag"] == "alt12x3f9a1b"
    assert out == {"broker_order_id": "151220000000000", "status": "open"}


def test_an_ended_session_is_a_reconnect(wire):
    _, answers = wire
    answers.append((403, {"status": "error", "error_type": "TokenException",
                          "message": "Incorrect `api_key` or `access_token`."}))
    with pytest.raises(B.NeedsReconnect):
        Z.funds(SESS)


def test_a_refused_order_carries_kites_reason(wire):
    _, answers = wire
    answers.append((400, {"status": "error", "error_type": "InputException",
                          "message": "Insufficient funds. Required margin is 38512.00"}))
    with pytest.raises(B.BrokerError, match="Insufficient funds"):
        Z.place(SESS, order())


def test_a_server_error_on_an_order_is_unknown_not_refused(wire):
    _, answers = wire
    answers.append((503, {"status": "error", "error_type": "NetworkException", "message": "upstream"}))
    with pytest.raises(B.BrokerUnreachable):
        Z.place(SESS, order())


def test_the_order_book(wire):
    _, answers = wire
    answers.append(ok([
        {"order_id": "1", "tag": "alt12x3f9a1b", "status": "OPEN", "tradingsymbol": "TCS",
         "transaction_type": "BUY", "quantity": 10, "filled_quantity": 4, "order_type": "LIMIT",
         "product": "MIS", "price": 3850, "order_timestamp": "2026-11-23 10:01:02"},
        {"order_id": "2", "status": "REJECTED", "status_message": "RMS: margin exceeds",
         "tradingsymbol": "INFY", "order_timestamp": "2026-11-23 10:05:00"},
        {"order_id": "3", "status": "TRIGGER PENDING", "tradingsymbol": "WIPRO",
         "order_timestamp": "2026-11-23 09:20:00"}]))
    rows = Z.orders(SESS)
    assert [r["broker_order_id"] for r in rows] == ["2", "1", "3"]
    assert rows[0]["status"] == "rejected" and rows[0]["message"] == "RMS: margin exceeds"
    assert (rows[1]["status"], rows[1]["product"], rows[1]["ref"]) == ("part_filled", "INTRADAY", "alt12x3f9a1b")
    assert rows[2]["status"] == "open"


def test_one_orders_history_reads_its_last_state(wire):
    _, answers = wire
    answers.append(ok([{"order_id": "1", "status": "OPEN"},
                       {"order_id": "1", "status": "COMPLETE", "filled_quantity": 10, "average_price": 3849.5}]))
    r = Z.order(SESS, "1")
    assert r["status"] == "filled" and r["avg_price"] == 3849.5


def test_holdings_count_shares_still_settling(wire):
    _, answers = wire
    answers.append(ok([{"tradingsymbol": "HDFCBANK", "quantity": 30, "t1_quantity": 10,
                        "average_price": 1520.2, "isin": "INE040A01034"},
                       {"tradingsymbol": "SOLD", "quantity": 0, "t1_quantity": 0}]))
    assert Z.holdings(SESS) == [{"symbol": "HDFCBANK", "qty": 40, "available_qty": 30, "t1_qty": 10,
                                 "avg_price": 1520.2, "isin": "INE040A01034"}]


def test_funds_and_positions(wire):
    _, answers = wire
    answers.append(ok({"equity": {"net": 98440.0, "available": {"opening_balance": 113642.0},
                                  "utilised": {"debits": 15202.0}}}))
    f = Z.funds(SESS)
    assert (f["available"], f["opening"], f["used"]) == (98440.0, 113642.0, 15202.0)
    answers.append(ok({"net": [{"tradingsymbol": "TCS", "product": "CNC", "quantity": -5,
                                "sell_price": 3900, "realised": 0, "unrealised": 120}], "day": []}))
    p = Z.positions(SESS)[0]
    assert (p["side"], p["net_qty"], p["sell_avg"]) == ("SHORT", -5, 3900.0)


def test_cancel_uses_delete_on_the_regular_variety(wire):
    calls, answers = wire
    answers.append(ok({"order_id": "9"}))
    assert Z.cancel(SESS, "9")["status"] == "cancelled"
    assert calls[0]["method"] == "DELETE" and calls[0]["url"].endswith("/orders/regular/9")
