"""
broker_dhan.py: what goes to Dhan, and how Dhan's answers are read.

The requests are checked against DhanHQ v2's documentation: the header is
`access-token`, the order body's field names and enums are Dhan's, an
expired session (DH-901) is a reconnect and not an error, and Dhan's own
spelling `availabelBalance` is the field that holds the money.
"""
import pytest

import broker_dhan as D
import brokers as B

SESS = {"client_id": "1100223344", "token": "member-token"}


@pytest.fixture
def wire(monkeypatch):
    calls = []
    answers = []

    def fake(method, url, headers, json=None, timeout=None):
        calls.append({"method": method, "url": url, "headers": headers, "json": json})
        status, body = answers.pop(0) if answers else (200, {})
        if isinstance(status, Exception):
            raise status
        return status, body

    monkeypatch.setattr(D, "_http", fake)
    for k in ("DHAN_PARTNER_ID", "DHAN_PARTNER_SECRET", "DHAN_API_KEY", "DHAN_API_SECRET",
              "DHAN_CLIENT_ID"):
        monkeypatch.delenv(k, raising=False)
    return calls, answers


def order(**kw):
    o = dict(symbol="TCS", side="BUY", qty=10, type="LIMIT", product="CNC", validity="DAY",
             price=3850.0, trigger=None, security_id="11536", correlation_id="alt-1-abc123")
    o.update(kw)
    return o


def test_a_partner_login_sends_the_member_to_dhans_page(wire, monkeypatch):
    calls, answers = wire
    monkeypatch.setenv("DHAN_PARTNER_ID", "pid")
    monkeypatch.setenv("DHAN_PARTNER_SECRET", "psec")
    answers.append((200, {"consentId": "cons-9", "consentStatus": "GENERATED"}))
    out = D.start_login()
    assert out["login_url"] == "https://auth.dhan.co/consent-login?consentId=cons-9"
    assert calls[0]["url"] == "https://auth.dhan.co/partner/generate-consent"
    assert calls[0]["headers"] == {"partner_id": "pid", "partner_secret": "psec"}


def test_a_405_on_the_consent_call_is_retried_with_the_other_method(wire, monkeypatch):
    calls, answers = wire
    monkeypatch.setenv("DHAN_PARTNER_ID", "pid")
    monkeypatch.setenv("DHAN_PARTNER_SECRET", "psec")
    answers.extend([(405, {}), (200, {"consentId": "c"})])
    D.start_login()
    assert [c["method"] for c in calls] == ["POST", "GET"]


def test_finishing_a_login_reads_dhans_answer(wire, monkeypatch):
    calls, answers = wire
    monkeypatch.setenv("DHAN_PARTNER_ID", "pid")
    monkeypatch.setenv("DHAN_PARTNER_SECRET", "psec")
    answers.append((200, {"dhanClientId": "1000000001", "dhanClientName": "JOHN DOE",
                          "accessToken": "jwt", "expiryTime": "2025-09-23T12:37:23"}))
    out = D.finish_login("tok-1")
    assert calls[0]["url"] == "https://auth.dhan.co/partner/consume-consent?tokenId=tok-1"
    assert out["client_id"] == "1000000001" and out["access_token"] == "jwt"
    assert out["expires_at"] == "2025-09-23T07:07:23+00:00"      # IST -> UTC


def test_the_individual_key_logs_in_one_named_account(wire, monkeypatch):
    calls, answers = wire
    monkeypatch.setenv("DHAN_API_KEY", "k")
    monkeypatch.setenv("DHAN_API_SECRET", "s")
    monkeypatch.setenv("DHAN_CLIENT_ID", "1100")
    assert D.mode() == "individual" and D.needs_allowlist()
    answers.append((200, {"consentAppId": "app-1"}))
    out = D.start_login()
    assert calls[0]["url"].endswith("/app/generate-consent?client_id=1100")
    assert calls[0]["headers"] == {"app_id": "k", "app_secret": "s"}
    assert out["login_url"].endswith("consentApp-login?consentAppId=app-1")


def test_nothing_configured_means_not_available(wire):
    assert D.available() is False


def test_an_order_body_is_dhans_shape(wire):
    calls, answers = wire
    answers.append((200, {"orderId": "112111182198", "orderStatus": "PENDING"}))
    out = D.place(SESS, order(type="SL", price=3860.0, trigger=3855.0, product="INTRADAY"))
    c = calls[0]
    assert c["method"] == "POST" and c["url"] == "https://api.dhan.co/v2/orders"
    assert c["headers"]["access-token"] == "member-token"
    b = c["json"]
    assert b["dhanClientId"] == "1100223344" and b["correlationId"] == "alt-1-abc123"
    assert b["transactionType"] == "BUY" and b["exchangeSegment"] == "NSE_EQ"
    assert b["orderType"] == "STOP_LOSS" and b["productType"] == "INTRADAY"
    assert b["securityId"] == "11536" and b["quantity"] == 10
    assert b["price"] == 3860.0 and b["triggerPrice"] == 3855.0
    assert out == {"broker_order_id": "112111182198", "broker_status": "PENDING", "status": "open"}


def test_a_market_order_sends_price_zero(wire):
    calls, answers = wire
    answers.append((200, {"orderId": "1", "orderStatus": "TRANSIT"}))
    D.place(SESS, order(type="MARKET", price=None))
    assert calls[0]["json"]["orderType"] == "MARKET" and calls[0]["json"]["price"] == 0.0


def test_an_expired_session_is_a_reconnect(wire):
    _, answers = wire
    answers.append((401, {"errorType": "Invalid_Authentication", "errorCode": "DH-901",
                          "errorMessage": "Client ID or user generated access token is invalid or expired."}))
    with pytest.raises(B.NeedsReconnect):
        D.funds(SESS)


def test_a_refused_order_carries_dhans_reason(wire):
    _, answers = wire
    answers.append((400, {"errorCode": "DH-906", "errorMessage": "Order rejected: margin shortfall"}))
    with pytest.raises(B.BrokerError, match="margin shortfall"):
        D.place(SESS, order())


def test_a_server_error_on_an_order_is_unknown_not_refused(wire):
    _, answers = wire
    answers.append((502, {}))
    with pytest.raises(B.BrokerUnreachable):
        D.place(SESS, order())


def test_the_order_book_is_read_into_one_shape(wire):
    _, answers = wire
    answers.append((200, [
        {"orderId": "1", "correlationId": "alt-1-x", "orderStatus": "PART_TRADED",
         "transactionType": "SELL", "tradingSymbol": "TCS", "quantity": 10, "filledQty": 4,
         "averageTradedPrice": 3851.5, "price": 3850, "orderType": "STOP_LOSS_MARKET",
         "productType": "CNC", "createTime": "2026-11-23 10:01:02"},
        {"orderId": "2", "orderStatus": "REJECTED", "omsErrorDescription": "RMS: no holdings",
         "tradingSymbol": "INFY", "createTime": "2026-11-23 10:05:00"}]))
    rows = D.orders(SESS)
    assert rows[0]["broker_order_id"] == "2" and rows[0]["message"] == "RMS: no holdings"
    r = rows[1]
    assert (r["status"], r["type"], r["filled_qty"], r["ref"]) == ("part_filled", "SL-M", 4, "alt-1-x")


def test_funds_read_dhans_spelling(wire):
    _, answers = wire
    answers.append((200, {"dhanClientId": "1", "availabelBalance": 98440.0, "sodLimit": 113642,
                          "utilizedAmount": 15202.0, "withdrawableBalance": 98310.0}))
    f = D.funds(SESS)
    assert f["available"] == 98440.0 and f["used"] == 15202.0


def test_holdings(wire):
    _, answers = wire
    answers.append((200, [{"tradingSymbol": "HDFC", "totalQty": 1000, "availableQty": 1000,
                           "avgCostPrice": 2655.0, "isin": "INE001A01036"},
                          {"tradingSymbol": "ZERO", "totalQty": 0}]))
    assert D.holdings(SESS) == [{"symbol": "HDFC", "qty": 1000, "available_qty": 1000, "t1_qty": None,
                                 "avg_price": 2655.0, "isin": "INE001A01036"}]


def test_cancel_uses_delete(wire):
    calls, answers = wire
    answers.append((202, {"orderId": "9", "orderStatus": "CANCELLED"}))
    assert D.cancel(SESS, "9")["status"] == "cancelled"
    assert calls[0]["method"] == "DELETE" and calls[0]["url"].endswith("/orders/9")
