"""
forum_routes.py — every route for the forum, in one router.

All the rules live in forum.py; this file turns them into HTTP and nothing
else. Errors arrive as exceptions and leave as status codes, as in
advisor_routes.py:

  ValueError       400  something typed is not acceptable, with a sentence
  PostRefused      422  a post that breaks a house rule; carries the sentence
                        that tripped the check, so the writer can rephrase it
  PermissionError  403  signed in, but not allowed to do that
  LookupError      404  not there, or not yours
  RateLimited      429  too much, too fast
  sqlite3.Error    503  the accounts database cannot be reached

Every write is a POST, including removals: the browser's CORS preflight only
has to know the methods the site already sends.

Routes
  GET  /forum                          categories, rules, and a page of threads
  GET  /forum/threads/{thread_id}      one discussion and its posts
  GET  /forum/stock/{symbol}           what the stock page shows
  GET  /forum/me                       my forum name and whether I can post
  POST /forum/me/handle                choose or change my forum name
  POST /forum/threads                  start a discussion
  POST /forum/threads/{thread_id}/posts  reply
  POST /forum/posts/{post_id}/remove   remove my own post
  POST /forum/posts/{post_id}/helpful  mark helpful, or take it back
  POST /forum/posts/{post_id}/report   report a post to the owner
  GET  /admin/forum                    reports, hidden posts, counts (ADMIN_KEY)
  POST /admin/forum/moderate           hide, restore, lock, pin, ban (ADMIN_KEY)
"""
from __future__ import annotations

import os
import sqlite3
from typing import Optional

from fastapi import APIRouter, Body, Header, HTTPException

import accounts
import forum

router = APIRouter(tags=["forum"])

# main.py points this at its own record of companies (_known_company), so a
# stock discussion can only be opened for a company the server knows. Left
# as None, any well-formed symbol is accepted (the tests run that way).
KNOWN_COMPANY = None


def _bearer(authorization: Optional[str]) -> str:
    if not authorization:
        return ""
    parts = authorization.split(None, 1)
    return parts[1].strip() if len(parts) == 2 and parts[0].lower() == "bearer" else ""


def _do(fn, *a, **k):
    try:
        return fn(*a, **k)
    except forum.PostRefused as e:
        raise HTTPException(422, {"message": str(e), "sentence": e.sentence, "rule": e.rule})
    except forum.RateLimited as e:
        raise HTTPException(429, str(e))
    except PermissionError as e:
        raise HTTPException(403, str(e))
    except LookupError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    except sqlite3.Error as e:
        print(f"[forum] database: {type(e).__name__}: {e}", flush=True)
        raise HTTPException(503, "The forum is unavailable just now. Try again in a minute.")


def _viewer(authorization: Optional[str]):
    """The signed-in reader, or None. Reading never needs an account, so a
    stale token reads as signed out rather than failing the page."""
    tok = _bearer(authorization)
    if not tok:
        return None
    try:
        return accounts.user_for_session(tok)
    except Exception:
        return None


def _user(authorization: Optional[str]) -> dict:
    user = _do(accounts.user_for_session, _bearer(authorization))
    if not user:
        raise HTTPException(401, "Sign in to post on the forum.")
    return user


def _admin(key: str, header: Optional[str]) -> None:
    """Closed when ADMIN_KEY is unset: the queue carries members' posts and
    the accounts behind them."""
    expected = os.environ.get("ADMIN_KEY", "").strip()
    if not expected or (header or key) != expected:
        raise HTTPException(401, "This needs the admin key (X-Admin-Key, or ?key=).")


def _id(raw, what: str) -> int:
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise HTTPException(400, f"{what} is required.")


# ── Reading, open to everyone ───────────────────────────────────────────────

@router.get("/forum")
def forum_front(category: str = "", symbol: str = "", q: str = "", sort: str = "latest",
                page: int = 1):
    out = _do(forum.overview)
    out.update(_do(forum.threads, category=category, symbol=symbol, q=q, sort=sort, page=page))
    return out


@router.get("/forum/threads/{thread_id}")
def forum_thread(thread_id: int, authorization: Optional[str] = Header(None)):
    return _do(forum.thread, thread_id, _viewer(authorization))


@router.get("/forum/stock/{symbol}")
def forum_stock(symbol: str):
    return _do(forum.for_stock, symbol)


# ── Signed in ───────────────────────────────────────────────────────────────

@router.get("/forum/me")
def forum_me(authorization: Optional[str] = Header(None)):
    user = _user(authorization)
    m = _do(forum.member, user["id"])
    return {"member": m, "can_post": bool(m and m["status"] == "active")}


@router.post("/forum/me/handle")
def forum_set_handle(payload: dict = Body(...), authorization: Optional[str] = Header(None)):
    user = _user(authorization)
    return {"member": _do(forum.set_handle, user["id"], payload.get("handle"))}


@router.post("/forum/threads")
def forum_start(payload: dict = Body(...), authorization: Optional[str] = Header(None)):
    user = _user(authorization)
    started = _do(forum.start_thread, user, payload.get("category"), payload.get("title"),
                  payload.get("body"), symbol=payload.get("symbol"), known=KNOWN_COMPANY)
    return _do(forum.thread, started["thread_id"], user)


@router.post("/forum/threads/{thread_id}/posts")
def forum_reply(thread_id: int, payload: dict = Body(...),
                authorization: Optional[str] = Header(None)):
    return _do(forum.reply, _user(authorization), thread_id, payload.get("body"))


@router.post("/forum/posts/{post_id}/remove")
def forum_remove(post_id: int, authorization: Optional[str] = Header(None)):
    return _do(forum.remove_own, _user(authorization), post_id)


@router.post("/forum/posts/{post_id}/helpful")
def forum_helpful(post_id: int, payload: Optional[dict] = Body(None),
                  authorization: Optional[str] = Header(None)):
    on = True if payload is None or "on" not in payload else bool(payload.get("on"))
    return _do(forum.set_helpful, _user(authorization), post_id, on)


@router.post("/forum/posts/{post_id}/report")
def forum_report(post_id: int, payload: dict = Body(...),
                 authorization: Optional[str] = Header(None)):
    return _do(forum.report, _user(authorization), post_id, payload.get("reason"))


# ── The owner ───────────────────────────────────────────────────────────────

@router.get("/admin/forum")
def admin_forum(key: str = "", x_admin_key: Optional[str] = Header(None, alias="X-Admin-Key")):
    _admin(key, x_admin_key)
    return _do(forum.moderation_queue)


@router.post("/admin/forum/moderate")
def admin_forum_moderate(payload: Optional[dict] = Body(None), key: str = "",
                         x_admin_key: Optional[str] = Header(None, alias="X-Admin-Key")):
    # The body is optional in the signature so a request with no key and no
    # body is refused as unauthorised, not as malformed.
    _admin(key, x_admin_key)
    p = payload or {}
    return _do(forum.moderate, str(p.get("action") or ""), _id(p.get("target"), "target"),
               p.get("note") or "")
