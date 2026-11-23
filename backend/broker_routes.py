"""
broker_routes.py — every route for Connect your broker, in one router.

The rules live in brokers.py; this file turns them into HTTP. Errors arrive
as exceptions and leave as status codes:

  ValueError        400  something typed is not acceptable, with a sentence
  PermissionError   403  signed in, but not allowed (not on the list, paused)
  LookupError       404  no broker connected, no such order
  NeedsReconnect    409  the broker session ended: {"reconnect": true}. Never
                         401, which the site reads as "signed out of Altaha"
  RateLimited       429
  BrokerError       502  the broker said no, with its reason
  NotSwitchedOn     503  the owner has not turned this on
  BrokerUnreachable 504  the broker did not answer
  sqlite3.Error     503

Every write is a POST, as in forum_routes.py.

Routes
  GET  /broker/config                 what is switched on, the limits, the disclaimer
  GET  /me/broker                     my connection, or null
  POST /me/broker/connect             {broker} -> {login_url}
  POST /me/broker/complete            {broker, token_id} -> my connection
  POST /me/broker/disconnect
  POST /me/broker/pause               {paused}
  GET  /me/broker/funds
  GET  /me/broker/holdings
  GET  /me/broker/positions
  GET  /me/broker/orders              today's order book
  POST /me/broker/orders              place one order
  GET  /me/broker/orders/{order_id}   one order Altaha sent, refreshed
  POST /me/broker/orders/cancel       {broker_order_id}
  POST /me/broker/holdings/copy       the broker's holdings become my Altaha portfolio
  GET  /admin/broker                  counts (ADMIN_KEY)
  POST /admin/broker/halt             {halted} stop or restart every order (ADMIN_KEY)
"""
from __future__ import annotations

import os
import sqlite3
from typing import Optional

from fastapi import APIRouter, Body, Header, HTTPException

import accounts
import brokers

router = APIRouter(tags=["broker"])


def _bearer(authorization: Optional[str]) -> str:
    if not authorization:
        return ""
    parts = authorization.split(None, 1)
    return parts[1].strip() if len(parts) == 2 and parts[0].lower() == "bearer" else ""


def _do(fn, *a, **k):
    try:
        return fn(*a, **k)
    except brokers.NeedsReconnect as e:
        raise HTTPException(409, {"message": str(e), "reconnect": True})
    except brokers.NotSwitchedOn as e:
        raise HTTPException(503, str(e))
    except brokers.RateLimited as e:
        raise HTTPException(429, str(e))
    except brokers.BrokerError as e:
        raise HTTPException(502, {"message": str(e), "code": e.code})
    except brokers.BrokerUnreachable:
        raise HTTPException(504, "The broker did not answer. Try again in a moment.")
    except PermissionError as e:
        raise HTTPException(403, str(e))
    except LookupError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    except sqlite3.Error as e:
        print(f"[broker] database: {type(e).__name__}: {e}", flush=True)
        raise HTTPException(503, "This is unavailable just now. Try again in a minute.")


def _user(authorization: Optional[str]) -> dict:
    user = _do(accounts.user_for_session, _bearer(authorization))
    if not user:
        raise HTTPException(401, "Sign in to connect your broker.")
    return user


def _viewer(authorization: Optional[str]):
    tok = _bearer(authorization)
    if not tok:
        return None
    try:
        return accounts.user_for_session(tok)
    except Exception:
        return None


def _admin(key: str, header: Optional[str]) -> None:
    expected = os.environ.get("ADMIN_KEY", "").strip()
    if not expected or (header or key) != expected:
        raise HTTPException(401, "This needs the admin key (X-Admin-Key, or ?key=).")


@router.get("/broker/config")
def broker_config(authorization: Optional[str] = Header(None)):
    return _do(brokers.config, _viewer(authorization))


@router.get("/me/broker")
def broker_me(authorization: Optional[str] = Header(None)):
    user = _user(authorization)
    return {"link": _do(brokers.link, user["id"]), "config": _do(brokers.config, user)}


@router.post("/me/broker/connect")
def broker_connect(body: dict = Body(default={}), authorization: Optional[str] = Header(None)):
    user = _user(authorization)
    return _do(brokers.start_connect, user, (body or {}).get("broker") or "dhan")


@router.post("/me/broker/complete")
def broker_complete(body: dict = Body(default={}), authorization: Optional[str] = Header(None)):
    user = _user(authorization)
    body = body or {}
    return {"link": _do(brokers.finish_connect, user, body.get("broker") or "dhan",
                        body.get("token_id"))}


@router.post("/me/broker/disconnect")
def broker_disconnect(authorization: Optional[str] = Header(None)):
    user = _user(authorization)
    return {"disconnected": _do(brokers.disconnect, user["id"])}


@router.post("/me/broker/pause")
def broker_pause(body: dict = Body(default={}), authorization: Optional[str] = Header(None)):
    user = _user(authorization)
    return {"link": _do(brokers.set_paused, user["id"], bool((body or {}).get("paused")))}


@router.get("/me/broker/funds")
def broker_funds(authorization: Optional[str] = Header(None)):
    user = _user(authorization)
    return {"funds": _do(brokers.funds, user["id"])}


@router.get("/me/broker/holdings")
def broker_holdings(authorization: Optional[str] = Header(None)):
    user = _user(authorization)
    return {"holdings": _do(brokers.holdings, user["id"])}


@router.get("/me/broker/positions")
def broker_positions(authorization: Optional[str] = Header(None)):
    user = _user(authorization)
    return {"positions": _do(brokers.positions, user["id"])}


@router.get("/me/broker/orders")
def broker_orders(authorization: Optional[str] = Header(None)):
    user = _user(authorization)
    return _do(brokers.orders, user["id"])


@router.post("/me/broker/orders")
def broker_place(body: dict = Body(default={}), authorization: Optional[str] = Header(None)):
    user = _user(authorization)
    return {"order": _do(brokers.place_order, user, body or {})}


@router.post("/me/broker/orders/cancel")
def broker_cancel(body: dict = Body(default={}), authorization: Optional[str] = Header(None)):
    user = _user(authorization)
    return {"order": _do(brokers.cancel_order, user["id"], (body or {}).get("broker_order_id"))}


@router.get("/me/broker/orders/{order_id}")
def broker_order(order_id: int, authorization: Optional[str] = Header(None)):
    user = _user(authorization)
    return {"order": _do(brokers.order, user["id"], order_id)}


@router.post("/me/broker/holdings/copy")
def broker_copy(authorization: Optional[str] = Header(None)):
    user = _user(authorization)
    return _do(brokers.copy_holdings, user["id"])


@router.get("/admin/broker")
def admin_broker(key: str = "", x_admin_key: Optional[str] = Header(None)):
    _admin(key, x_admin_key)
    return _do(brokers.summary)


@router.post("/admin/broker/halt")
def admin_broker_halt(body: dict = Body(default={}), key: str = "",
                      x_admin_key: Optional[str] = Header(None)):
    _admin(key, x_admin_key)
    return {"halted": _do(brokers.set_halt, bool((body or {}).get("halted", True)))}
