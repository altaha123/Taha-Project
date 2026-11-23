"""
Dhan, as brokers.py needs it: a member's login, their orders, holdings,
positions and funds, through DhanHQ v2 (https://dhanhq.co/docs/v2/).

THIS IS NOT dhan_source.py
dhan_source.py is the owner's own Dhan session, used for market data: one
token, from the environment, shared by the whole site. This module never
touches that token. Every call here carries the token of the member it is
for, handed in by brokers.py, so an order can only ever reach the account of
the member who placed it.

TWO WAYS TO LOG A MEMBER IN
  partner     DHAN_PARTNER_ID + DHAN_PARTNER_SECRET, issued by Dhan to a
              platform. Any Dhan customer can connect. This is the one to
              launch with.
  individual  DHAN_API_KEY + DHAN_API_SECRET, the key a Dhan customer makes
              for themselves, with DHAN_CLIENT_ID. Only that one Dhan account
              can ever log in, so it is for the owner to test with while a
              partner application is pending, and brokers.allowed() keeps it
              closed unless BROKER_MEMBERS names who it is for.

Both are three steps: ask Dhan for a consent id, send the member to Dhan's
login page with it, and exchange the tokenId Dhan sends them back with for an
access token. Dhan's page shows each call as a curl without a method, so the
consent call is POSTed (as the individual flow's example is) and retried as a
GET on 405, and the exchange the other way round.

ORDERS NEED A FIXED IP
Dhan, under SEBI's 2025 rules, accepts order placement, modification and
cancellation only from a whitelisted static IP. Reads do not need it. If
orders come back refused for the address, that is the setting to fix (see
BROKER.md), not this code.
"""
from __future__ import annotations

import datetime as dt
import os

import brokers

try:
    import requests
except Exception:                                             # pragma: no cover
    requests = None

ID = "dhan"
LABEL = "Dhan"
API = "https://api.dhan.co/v2"
AUTH = "https://auth.dhan.co"
TIMEOUT = 15
ORDER_TIMEOUT = 20

TYPE_OUT = {"MARKET": "MARKET", "LIMIT": "LIMIT", "SL": "STOP_LOSS", "SL-M": "STOP_LOSS_MARKET"}
TYPE_IN = {v: k for k, v in TYPE_OUT.items()}
STATUS_IN = {
    "TRANSIT": "open", "PENDING": "open", "TRIGGERED": "open",
    "PART_TRADED": "part_filled", "TRADED": "filled", "CLOSED": "filled",
    "REJECTED": "rejected", "CANCELLED": "cancelled", "EXPIRED": "expired",
}

# Tests point this at a fake: symbol -> Dhan securityId.
SECURITY_ID = None


def _env(name: str) -> str:
    return os.environ.get(name, "").strip()


def mode():
    if _env("DHAN_PARTNER_ID") and _env("DHAN_PARTNER_SECRET"):
        return "partner"
    if _env("DHAN_API_KEY") and _env("DHAN_API_SECRET") and _env("DHAN_CLIENT_ID"):
        return "individual"
    return None


def available() -> bool:
    return mode() is not None


def needs_allowlist() -> bool:
    return mode() == "individual"


# ---------------------------------------------------------------------------
# HTTP. One function, so the tests replace exactly this.
# ---------------------------------------------------------------------------

def _http(method: str, url: str, headers: dict, json=None, timeout=TIMEOUT):
    """(status, body) — body parsed as JSON where it is JSON, else {}."""
    if requests is None:
        raise brokers.BrokerUnreachable("No HTTP client.")
    try:
        r = requests.request(method, url, headers=headers, json=json, timeout=timeout)
    except Exception as e:
        raise brokers.BrokerUnreachable(f"{type(e).__name__}") from None
    try:
        body = r.json()
    except Exception:
        body = {}
    return r.status_code, body


def _fail(status: int, body) -> None:
    """Turn a Dhan error into the exception brokers.py understands."""
    b = body if isinstance(body, dict) else {}
    code = str(b.get("errorCode") or b.get("code") or "")
    msg = str(b.get("errorMessage") or b.get("message") or b.get("remarks") or "").strip()
    # DH-902 (no access to the Trading APIs) is an account setting, not an
    # ended session, so it falls through to the message below.
    if code == "DH-901" or (status == 401 and not code):
        raise brokers.NeedsReconnect("Your Dhan session has ended. Log in to Dhan again to continue.")
    if code == "DH-904" or status == 429:
        raise brokers.BrokerError("Dhan is limiting requests just now. Wait a moment and try again.", code)
    if code in ("DH-908", "DH-909") or status >= 500:
        raise brokers.BrokerUnreachable(msg or f"Dhan answered {status}")
    raise brokers.BrokerError(msg or f"Dhan refused this ({code or status}).", code)


def _call(method: str, path: str, sess: dict, json=None, timeout=TIMEOUT):
    headers = {"access-token": sess["token"], "Content-Type": "application/json",
               "Accept": "application/json"}
    status, body = _http(method, API + path, headers, json=json, timeout=timeout)
    if status >= 300:
        _fail(status, body)
    return body


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------

def _auth_headers() -> dict:
    if mode() == "partner":
        return {"partner_id": _env("DHAN_PARTNER_ID"), "partner_secret": _env("DHAN_PARTNER_SECRET")}
    return {"app_id": _env("DHAN_API_KEY"), "app_secret": _env("DHAN_API_SECRET")}


def _auth(methods, url):
    status, body = None, {}
    for m in methods:
        status, body = _http(m, url, _auth_headers())
        if status != 405:
            break
    if status is None or status >= 300:
        b = body if isinstance(body, dict) else {}
        msg = str(b.get("errorMessage") or b.get("message") or "").strip()
        raise brokers.BrokerError(msg or f"Dhan login is unavailable just now ({status}).")
    return body if isinstance(body, dict) else {}


def start_login() -> dict:
    m = mode()
    if m == "partner":
        body = _auth(("POST", "GET"), f"{AUTH}/partner/generate-consent")
        cid = str(body.get("consentId") or "")
        url = f"{AUTH}/consent-login?consentId={cid}"
    elif m == "individual":
        body = _auth(("POST", "GET"), f"{AUTH}/app/generate-consent?client_id={_env('DHAN_CLIENT_ID')}")
        cid = str(body.get("consentAppId") or "")
        url = f"{AUTH}/login/consentApp-login?consentAppId={cid}"
    else:
        raise brokers.NotSwitchedOn("Dhan connections are not switched on yet.")
    if not cid:
        raise brokers.BrokerError("Dhan did not start a login. Try again in a minute.")
    return {"login_url": url, "ref": cid}


def _expiry_utc(raw):
    """Dhan's expiryTime is India time without a zone: "2025-09-23T12:37:23"."""
    s = str(raw or "").strip()
    if not s:
        return None
    try:
        t = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=dt.timezone(dt.timedelta(hours=5, minutes=30)))
    return t.astimezone(dt.timezone.utc).replace(microsecond=0).isoformat()


def finish_login(token_id: str) -> dict:
    m = mode()
    if m == "partner":
        url = f"{AUTH}/partner/consume-consent?tokenId={token_id}"
    elif m == "individual":
        url = f"{AUTH}/app/consumeApp-consent?tokenId={token_id}"
    else:
        raise brokers.NotSwitchedOn("Dhan connections are not switched on yet.")
    body = _auth(("GET", "POST"), url)
    return {"client_id": str(body.get("dhanClientId") or ""),
            "client_name": str(body.get("dhanClientName") or ""),
            "access_token": str(body.get("accessToken") or ""),
            "expires_at": _expiry_utc(body.get("expiryTime"))}


# ---------------------------------------------------------------------------
# Instruments
# ---------------------------------------------------------------------------

def instrument(symbol: str):
    """Dhan's securityId for an NSE equity symbol, from the instrument master
    dhan_source.py already keeps (the file is public; no token is used)."""
    if SECURITY_ID is not None:
        return SECURITY_ID(symbol)
    try:
        import dhan_source
        return dhan_source.security_id(symbol)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------

def _f(v):
    try:
        f = float(v)
        return f if f == f else None
    except (TypeError, ValueError):
        return None


def _i(v):
    f = _f(v)
    return int(f) if f is not None else None


def _row(o: dict) -> dict:
    raw = str(o.get("orderStatus") or "").upper()
    return {
        "broker_order_id": str(o.get("orderId") or "") or None,
        "ref": o.get("correlationId") or None,
        "symbol": str(o.get("tradingSymbol") or "").upper(),
        "side": str(o.get("transactionType") or "").upper(),
        "qty": _i(o.get("quantity")),
        "filled_qty": _i(o.get("filledQty")),
        "avg_price": _f(o.get("averageTradedPrice")) or None,
        "price": _f(o.get("price")) or None,
        "trigger": _f(o.get("triggerPrice")) or None,
        "type": TYPE_IN.get(str(o.get("orderType") or "").upper(), o.get("orderType")),
        "product": o.get("productType"),
        "segment": o.get("exchangeSegment"),
        "status": STATUS_IN.get(raw, "open" if raw else "unknown"),
        "broker_status": raw or None,
        "message": (o.get("omsErrorDescription") or None) if raw == "REJECTED" else None,
        "time": o.get("createTime") or o.get("updateTime"),
    }


def place(sess: dict, o: dict) -> dict:
    body = {
        "dhanClientId": sess["client_id"],
        "correlationId": o["correlation_id"],
        "transactionType": o["side"],
        "exchangeSegment": "NSE_EQ",
        "productType": o["product"],
        "orderType": TYPE_OUT[o["type"]],
        "validity": o["validity"],
        "securityId": str(o["security_id"]),
        "quantity": int(o["qty"]),
        "disclosedQuantity": 0,
        "price": float(o["price"] or 0),
        "triggerPrice": float(o["trigger"] or 0),
        "afterMarketOrder": False,
    }
    got = _call("POST", "/orders", sess, json=body, timeout=ORDER_TIMEOUT)
    raw = str(got.get("orderStatus") or "").upper()
    if not got.get("orderId"):
        raise brokers.BrokerUnreachable("Dhan returned no order id")
    return {"broker_order_id": str(got["orderId"]), "broker_status": raw or None,
            "status": STATUS_IN.get(raw, "open")}


def cancel(sess: dict, broker_order_id: str) -> dict:
    got = _call("DELETE", f"/orders/{broker_order_id}", sess, timeout=ORDER_TIMEOUT) or {}
    raw = str(got.get("orderStatus") or "CANCELLED").upper()
    return {"broker_order_id": broker_order_id, "broker_status": raw,
            "status": STATUS_IN.get(raw, "cancelled")}


def order(sess: dict, broker_order_id: str) -> dict:
    got = _call("GET", f"/orders/{broker_order_id}", sess)
    if isinstance(got, list):
        got = got[0] if got else {}
    return _row(got or {})


def order_by_ref(sess: dict, ref: str):
    try:
        got = _call("GET", f"/orders/external/{ref}", sess)
    except brokers.BrokerError:
        return None
    if isinstance(got, list):
        got = got[0] if got else None
    return _row(got) if got else None


def orders(sess: dict) -> list:
    got = _call("GET", "/orders", sess)
    rows = [_row(o) for o in (got if isinstance(got, list) else []) if isinstance(o, dict)]
    rows.sort(key=lambda r: str(r.get("time") or ""), reverse=True)
    return rows


# ---------------------------------------------------------------------------
# Holdings, positions, funds
# ---------------------------------------------------------------------------

def holdings(sess: dict) -> list:
    try:
        got = _call("GET", "/holdings", sess)
    except brokers.BrokerError as e:
        # An account with no holdings answers with an error, not an empty list.
        if "no holding" in str(e).lower() or e.code in ("DH-907",):
            return []
        raise
    out = []
    for h in (got if isinstance(got, list) else []):
        if not isinstance(h, dict):
            continue
        sym = str(h.get("tradingSymbol") or "").upper()
        qty = _i(h.get("totalQty"))
        if not sym or not qty:
            continue
        out.append({"symbol": sym, "qty": qty, "available_qty": _i(h.get("availableQty")),
                    "t1_qty": _i(h.get("t1Qty")), "avg_price": _f(h.get("avgCostPrice")),
                    "isin": h.get("isin")})
    out.sort(key=lambda r: r["symbol"])
    return out


def positions(sess: dict) -> list:
    got = _call("GET", "/positions", sess)
    out = []
    for p in (got if isinstance(got, list) else []):
        if not isinstance(p, dict):
            continue
        out.append({"symbol": str(p.get("tradingSymbol") or "").upper(),
                    "product": p.get("productType"), "segment": p.get("exchangeSegment"),
                    "side": p.get("positionType"), "net_qty": _i(p.get("netQty")),
                    "buy_avg": _f(p.get("buyAvg")), "sell_avg": _f(p.get("sellAvg")),
                    "realized": _f(p.get("realizedProfit")),
                    "unrealized": _f(p.get("unrealizedProfit"))})
    return out


def funds(sess: dict) -> dict:
    got = _call("GET", "/fundlimit", sess) or {}
    # "availabelBalance" is Dhan's spelling; the corrected one is read too in
    # case they fix it.
    return {"available": _f(got.get("availabelBalance", got.get("availableBalance"))),
            "opening": _f(got.get("sodLimit")),
            "used": _f(got.get("utilizedAmount")),
            "collateral": _f(got.get("collateralAmount")),
            "withdrawable": _f(got.get("withdrawableBalance"))}
