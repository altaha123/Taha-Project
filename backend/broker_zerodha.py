"""
Zerodha, as brokers.py needs it: a member's login, their orders, holdings,
positions and funds, through Kite Connect v3 (https://kite.trade/docs/connect/v3/).

THE APP AND WHO MAY USE IT
Kite Connect works through an app made at developers.kite.trade, which gives
an API key and secret (KITE_API_KEY, KITE_API_SECRET) and takes a redirect
URL (https://altahascreener.in/broker). Whether Zerodha lets clients other
than the app's owner log in to it, and on what terms, is Zerodha's to say,
so until KITE_ALL_MEMBERS=on it is treated like Dhan's individual key: closed
unless BROKER_MEMBERS names who it is for (brokers.allowed_for).

LOGGING A MEMBER IN
  1. Send them to kite.zerodha.com/connect/login?v=3&api_key=<key>.
  2. Zerodha sends them back to the redirect URL with
     ?request_token=…&action=login&status=success.
  3. POST /session/token with the key, that request_token and a checksum,
     SHA-256 of api_key + request_token + api_secret, and get an access
     token. The secret never leaves the server; the checksum is why.

The access token lasts until Zerodha flushes every session at 6 AM India
time the next day; there is no refresh, so the member logs in again daily.

HOW KITE IS SPOKEN
Every call carries `X-Kite-Version: 3` and `Authorization: token
<api_key>:<access_token>`. Request bodies are form fields, not JSON. Every
answer is {"status": "success", "data": …} or {"status": "error",
"message": …, "error_type": …}; a TokenException is an ended session.

ORDERS NEED A FIXED IP
As at Dhan, SEBI's 2025 rules mean Kite accepts order placement,
modification and cancellation only from a static IP registered on the app.
Reading does not need it (see BROKER.md).
"""
from __future__ import annotations

import datetime as dt
import hashlib
import os
import re
import urllib.parse

import brokers

try:
    import requests
except Exception:                                             # pragma: no cover
    requests = None

ID = "zerodha"
LABEL = "Zerodha"
API = "https://api.kite.trade"
LOGIN = "https://kite.zerodha.com/connect/login"
TIMEOUT = 15
ORDER_TIMEOUT = 20

PRODUCT_OUT = {"CNC": "CNC", "INTRADAY": "MIS"}
PRODUCT_IN = {"CNC": "CNC", "MIS": "INTRADAY", "NRML": "NRML"}
FINAL_IN = {"COMPLETE": "filled", "REJECTED": "rejected", "CANCELLED": "cancelled"}
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))


def _env(name: str) -> str:
    return os.environ.get(name, "").strip()


def available() -> bool:
    return bool(_env("KITE_API_KEY") and _env("KITE_API_SECRET"))


def needs_allowlist() -> bool:
    return _env("KITE_ALL_MEMBERS").lower() != "on"


# ---------------------------------------------------------------------------
# HTTP. One function, so the tests replace exactly this.
# ---------------------------------------------------------------------------

def _http(method: str, url: str, headers: dict, data=None, timeout=TIMEOUT):
    """(status, body). Kite takes form fields and answers JSON."""
    if requests is None:
        raise brokers.BrokerUnreachable("No HTTP client.")
    try:
        r = requests.request(method, url, headers=headers, data=data, timeout=timeout)
    except Exception as e:
        raise brokers.BrokerUnreachable(f"{type(e).__name__}") from None
    try:
        body = r.json()
    except Exception:
        body = {}
    return r.status_code, body


def _fail(status: int, body) -> None:
    b = body if isinstance(body, dict) else {}
    kind = str(b.get("error_type") or "")
    msg = str(b.get("message") or "").strip()
    if kind == "TokenException" or (status == 403 and not kind):
        raise brokers.NeedsReconnect("Your Zerodha session has ended. Log in to Zerodha again to continue.")
    if status == 429:
        raise brokers.BrokerError("Zerodha is limiting requests just now. Wait a moment and try again.", kind)
    if kind == "NetworkException" or status >= 500:
        raise brokers.BrokerUnreachable(msg or f"Zerodha answered {status}")
    raise brokers.BrokerError(msg or f"Zerodha refused this ({kind or status}).", kind)


def _call(method: str, path: str, sess: dict, data=None, timeout=TIMEOUT):
    headers = {"X-Kite-Version": "3",
               "Authorization": f"token {_env('KITE_API_KEY')}:{sess['token']}"}
    status, body = _http(method, API + path, headers, data=data, timeout=timeout)
    if status >= 300 or (isinstance(body, dict) and body.get("status") == "error"):
        _fail(status, body)
    return body.get("data") if isinstance(body, dict) else None


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------

def start_login() -> dict:
    if not available():
        raise brokers.NotSwitchedOn("Zerodha connections are not switched on yet.")
    q = urllib.parse.urlencode({"v": "3", "api_key": _env("KITE_API_KEY")})
    return {"login_url": f"{LOGIN}?{q}", "ref": ""}


def _next_flush_utc(now=None) -> str:
    """Kite ends every session at 6 AM India time."""
    now = (now or dt.datetime.now(dt.timezone.utc)).astimezone(IST)
    flush = now.replace(hour=6, minute=0, second=0, microsecond=0)
    if flush <= now:
        flush += dt.timedelta(days=1)
    return flush.astimezone(dt.timezone.utc).isoformat()


def finish_login(request_token: str) -> dict:
    if not available():
        raise brokers.NotSwitchedOn("Zerodha connections are not switched on yet.")
    key, secret = _env("KITE_API_KEY"), _env("KITE_API_SECRET")
    checksum = hashlib.sha256((key + request_token + secret).encode()).hexdigest()
    status, body = _http("POST", API + "/session/token", {"X-Kite-Version": "3"},
                         data={"api_key": key, "request_token": request_token,
                               "checksum": checksum})
    if status >= 300 or not isinstance(body, dict) or body.get("status") == "error":
        b = body if isinstance(body, dict) else {}
        raise brokers.BrokerError(str(b.get("message") or "")
                                  or "Zerodha did not accept that login. Press Connect again.")
    d = body.get("data") or {}
    return {"client_id": str(d.get("user_id") or ""),
            "client_name": str(d.get("user_name") or d.get("user_shortname") or ""),
            "access_token": str(d.get("access_token") or ""),
            "expires_at": _next_flush_utc()}


# ---------------------------------------------------------------------------
# Instruments: Kite names an equity by exchange and trading symbol, which is
# the NSE symbol this site already uses. No instrument file is needed.
# ---------------------------------------------------------------------------

def instrument(symbol: str):
    s = str(symbol or "").strip().upper()
    return s if re.fullmatch(r"[A-Z0-9&\-]{1,30}", s) else None


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


def _status(o: dict) -> str:
    raw = str(o.get("status") or "").upper()
    if raw in FINAL_IN:
        return FINAL_IN[raw]
    if not raw:
        return "unknown"
    return "part_filled" if (_i(o.get("filled_quantity")) or 0) > 0 else "open"


def _row(o: dict) -> dict:
    raw = str(o.get("status") or "").upper()
    return {
        "broker_order_id": str(o.get("order_id") or "") or None,
        "ref": o.get("tag") or None,
        "symbol": str(o.get("tradingsymbol") or "").upper(),
        "side": str(o.get("transaction_type") or "").upper(),
        "qty": _i(o.get("quantity")),
        "filled_qty": _i(o.get("filled_quantity")),
        "avg_price": _f(o.get("average_price")) or None,
        "price": _f(o.get("price")) or None,
        "trigger": _f(o.get("trigger_price")) or None,
        "type": o.get("order_type"),
        "product": PRODUCT_IN.get(str(o.get("product") or "").upper(), o.get("product")),
        "segment": o.get("exchange"),
        "status": _status(o),
        "broker_status": raw or None,
        "message": (o.get("status_message") or None) if raw == "REJECTED" else None,
        "time": o.get("order_timestamp") or o.get("exchange_timestamp"),
    }


def place(sess: dict, o: dict) -> dict:
    data = {
        "tradingsymbol": o["security_id"],
        "exchange": "NSE",
        "transaction_type": o["side"],
        "order_type": o["type"],              # MARKET, LIMIT, SL, SL-M: Kite's own names
        "quantity": str(int(o["qty"])),
        "product": PRODUCT_OUT[o["product"]],
        "validity": o["validity"],
        "tag": o["correlation_id"][:20],
    }
    if o.get("price"):
        data["price"] = str(o["price"])
    if o.get("trigger"):
        data["trigger_price"] = str(o["trigger"])
    got = _call("POST", "/orders/regular", sess, data=data, timeout=ORDER_TIMEOUT) or {}
    if not got.get("order_id"):
        raise brokers.BrokerUnreachable("Zerodha returned no order id")
    return {"broker_order_id": str(got["order_id"]), "status": "open"}


def cancel(sess: dict, broker_order_id: str) -> dict:
    _call("DELETE", f"/orders/regular/{broker_order_id}", sess, timeout=ORDER_TIMEOUT)
    return {"broker_order_id": broker_order_id, "status": "cancelled", "broker_status": "CANCELLED"}


def order(sess: dict, broker_order_id: str) -> dict:
    """An order's history, oldest first; the last entry is where it stands."""
    got = _call("GET", f"/orders/{broker_order_id}", sess)
    last = got[-1] if isinstance(got, list) and got else (got if isinstance(got, dict) else {})
    return _row(last)


def orders(sess: dict) -> list:
    got = _call("GET", "/orders", sess)
    rows = [_row(o) for o in (got if isinstance(got, list) else []) if isinstance(o, dict)]
    rows.sort(key=lambda r: str(r.get("time") or ""), reverse=True)
    return rows


def order_by_ref(sess: dict, ref: str):
    """Kite has no lookup by tag, so today's book is searched for it."""
    for r in orders(sess):
        if r.get("ref") == ref:
            return r
    return None


# ---------------------------------------------------------------------------
# Holdings, positions, funds
# ---------------------------------------------------------------------------

def holdings(sess: dict) -> list:
    got = _call("GET", "/portfolio/holdings", sess)
    out = []
    for h in (got if isinstance(got, list) else []):
        if not isinstance(h, dict):
            continue
        sym = str(h.get("tradingsymbol") or "").upper()
        settled, t1 = _i(h.get("quantity")) or 0, _i(h.get("t1_quantity")) or 0
        if not sym or settled + t1 <= 0:
            continue
        out.append({"symbol": sym, "qty": settled + t1, "available_qty": settled, "t1_qty": t1,
                    "avg_price": _f(h.get("average_price")), "isin": h.get("isin")})
    out.sort(key=lambda r: r["symbol"])
    return out


def positions(sess: dict) -> list:
    got = _call("GET", "/portfolio/positions", sess) or {}
    out = []
    for p in (got.get("net") or []) if isinstance(got, dict) else []:
        if not isinstance(p, dict):
            continue
        q = _i(p.get("quantity"))
        out.append({"symbol": str(p.get("tradingsymbol") or "").upper(),
                    "product": PRODUCT_IN.get(str(p.get("product") or "").upper(), p.get("product")),
                    "segment": p.get("exchange"),
                    "side": "LONG" if (q or 0) > 0 else "SHORT" if (q or 0) < 0 else "CLOSED",
                    "net_qty": q, "buy_avg": _f(p.get("buy_price")), "sell_avg": _f(p.get("sell_price")),
                    "realized": _f(p.get("realised")), "unrealized": _f(p.get("unrealised"))})
    return out


def funds(sess: dict) -> dict:
    got = _call("GET", "/user/margins", sess) or {}
    eq = got.get("equity") or {} if isinstance(got, dict) else {}
    avail, used = eq.get("available") or {}, eq.get("utilised") or {}
    return {"available": _f(eq.get("net")),
            "opening": _f(avail.get("opening_balance")),
            "used": _f(used.get("debits")),
            "collateral": _f(avail.get("collateral")),
            "withdrawable": None}
