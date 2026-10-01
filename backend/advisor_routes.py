"""
advisor_routes.py — every route for Advisors, in one router.

All the rules live in advisors.py; this file turns them into HTTP and nothing
else. Errors arrive as exceptions and leave as status codes:

  ValueError       400  something typed is not acceptable, with a sentence
  MessageRefused   422  a message that cannot be sent as written; carries the
                        sentence that tripped the check, so the sender can see
                        what to rephrase
  PermissionError  403  allowed to see it, not to do that
  LookupError      404  not there — or not yours, which is answered the same
  RateLimited      429  too much, too fast
  sqlite3.Error    503  the accounts database cannot be reached — said as
                        much, rather than a bare 500 that reads as a bug

Routes
  GET  /advisors                          the directory (public)
  GET  /advisors/profile/{slug}           one listed profile (public)
  GET  /advisors/me                       my adviser profile if any, unread count
  PUT  /advisors/me/profile               apply, or edit my profile
  POST /advisors/me/accepting             take new chats, or stop
  GET  /advisors/chats                    both my inboxes
  POST /advisors/profile/{slug}/chat      start a chat, or continue the open one
  GET  /advisors/chats/{chat_id}          one chat; ?after=<message id> to poll
  POST /advisors/chats/{chat_id}/messages send
  POST /advisors/chats/{chat_id}/close    end it (the adviser may also block)
  POST /advisors/chats/{chat_id}/share    the reader shares or withdraws a portfolio
  POST /advisors/chats/{chat_id}/report   report a chat to the owner
  GET  /admin/advisors                    applications and counts (ADMIN_KEY)
  POST /admin/advisors/review             approve, reject, suspend, feature (ADMIN_KEY)
  GET  /admin/advisors/reports            reported chats, with the conversation (ADMIN_KEY)
"""
from __future__ import annotations

import os
import sqlite3
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Body, Header, HTTPException, Query

import accounts
import advisors

router = APIRouter(tags=["advisors"])


def _bearer(authorization: Optional[str]) -> str:
    if not authorization:
        return ""
    parts = authorization.split(None, 1)
    return parts[1].strip() if len(parts) == 2 and parts[0].lower() == "bearer" else ""


def _user(authorization: Optional[str]) -> dict:
    user = _do(accounts.user_for_session, _bearer(authorization))
    if not user:
        raise HTTPException(401, "Sign in to use this.")
    return user


def _admin(key: str, header: Optional[str]) -> None:
    """Closed when ADMIN_KEY is unset, unlike the control endpoints: these
    answers carry applicants' email addresses and other people's chats."""
    expected = os.environ.get("ADMIN_KEY", "").strip()
    if not expected or (header or key) != expected:
        raise HTTPException(401, "This needs the admin key (X-Admin-Key, or ?key=).")


def _do(fn, *a, **k):
    try:
        return fn(*a, **k)
    except advisors.MessageRefused as e:
        raise HTTPException(422, {"message": str(e), "sentence": e.sentence})
    except advisors.RateLimited as e:
        raise HTTPException(429, str(e))
    except PermissionError as e:
        raise HTTPException(403, str(e))
    except LookupError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    except sqlite3.Error as e:
        print(f"[advisors] database: {type(e).__name__}: {e}", flush=True)
        raise HTTPException(503, "The advisers database is unavailable just now. "
                                 "Try again in a minute.")


def _site() -> str:
    return os.environ.get("SITE_URL", "https://altahascreener.in").rstrip("/")


def _send_notice(notice: dict) -> None:
    import mailer
    subject, html, text = advisors.notice_email(notice, _site())
    ok, detail = mailer.send(notice["email"], subject, html, text)
    if not ok:
        print(f"[advisors] notification for chat {notice['chat_id']} not sent: {detail}",
              flush=True)


def _notify(background: BackgroundTasks, notice) -> None:
    """After the response, so a slow mail provider never holds up a chat."""
    if notice:
        background.add_task(_send_notice, notice)


# ── Public ──────────────────────────────────────────────────────────────────

@router.get("/advisors")
def advisor_directory(kind: str = "", topic: str = "", q: str = ""):
    return {
        "experts": _do(advisors.directory, kind=kind, topic=topic, q=q),
        "kinds": [{"id": k, **{f: v[f] for f in ("label", "short", "registered")}}
                  for k, v in advisors.KINDS.items()],
        "topics": [{"id": t, "label": label, "kinds": list(kinds)}
                   for t, label, kinds in advisors.TOPICS],
        "disclaimer": advisors.DISCLAIMER,
    }


@router.get("/advisors/profile/{slug}")
def advisor_profile(slug: str):
    found = _do(advisors.profile, slug)
    if not found:
        raise HTTPException(404, "That adviser is not listed.")
    return {"expert": found, "disclaimer": advisors.DISCLAIMER}


# ── Signed in ───────────────────────────────────────────────────────────────

@router.get("/advisors/me")
def advisor_me(authorization: Optional[str] = Header(None)):
    """Who I am here: my own profile if I applied, what I could share with an
    adviser, and how many messages are waiting."""
    user = _user(authorization)
    risk = _do(accounts.latest_risk_profile, user["id"])
    return {
        "email": user["email"],
        "expert": _do(advisors.my_profile, user["id"]),
        "unread": _do(advisors.unread_count, user),
        "holdings": len(_do(accounts.get_holdings, user["id"])),
        "risk_profile": None if not risk else {"band": risk["band"],
                                               "assessed_at": risk["assessed_at"]},
    }


@router.put("/advisors/me/profile")
def advisor_save_profile(payload: dict = Body(...),
                         authorization: Optional[str] = Header(None)):
    user = _user(authorization)
    return {"expert": _do(advisors.save_profile, user["id"], payload)}


@router.post("/advisors/me/accepting")
def advisor_accepting(payload: dict = Body(...),
                      authorization: Optional[str] = Header(None)):
    user = _user(authorization)
    return {"expert": _do(advisors.set_accepting, user["id"], bool(payload.get("on")))}


@router.get("/advisors/chats")
def advisor_chats(authorization: Optional[str] = Header(None)):
    return _do(advisors.my_chats, _user(authorization))


@router.post("/advisors/profile/{slug}/chat")
def advisor_start_chat(slug: str, background: BackgroundTasks,
                       payload: dict = Body(...),
                       authorization: Optional[str] = Header(None)):
    user = _user(authorization)
    started = _do(advisors.start_chat, user, slug, payload.get("topic"),
                  payload.get("message"), name=payload.get("name") or "",
                  share_portfolio=bool(payload.get("share_portfolio")))
    _notify(background, started["notify"])
    out = _do(advisors.chat_view, user, started["chat_id"])
    out["existing"] = started["existing"]
    return out


@router.get("/advisors/chats/{chat_id}")
def advisor_chat(chat_id: int, after: int = Query(0, ge=0),
                 authorization: Optional[str] = Header(None)):
    return _do(advisors.chat_view, _user(authorization), chat_id, after)


@router.post("/advisors/chats/{chat_id}/messages")
def advisor_send(chat_id: int, background: BackgroundTasks,
                 payload: dict = Body(...),
                 authorization: Optional[str] = Header(None)):
    sent = _do(advisors.send_message, _user(authorization), chat_id, payload.get("body"))
    _notify(background, sent["notify"])
    return {"message": sent["message"]}


@router.post("/advisors/chats/{chat_id}/close")
def advisor_close(chat_id: int, payload: Optional[dict] = Body(None),
                  authorization: Optional[str] = Header(None)):
    return _do(advisors.close_chat, _user(authorization), chat_id,
               block=bool((payload or {}).get("block")))


@router.post("/advisors/chats/{chat_id}/share")
def advisor_share(chat_id: int, payload: dict = Body(...),
                  authorization: Optional[str] = Header(None)):
    return _do(advisors.set_share, _user(authorization), chat_id, bool(payload.get("share")))


@router.post("/advisors/chats/{chat_id}/report")
def advisor_report(chat_id: int, payload: dict = Body(...),
                   authorization: Optional[str] = Header(None)):
    return _do(advisors.report_chat, _user(authorization), chat_id, payload.get("reason"))


# ── The owner ───────────────────────────────────────────────────────────────

@router.get("/admin/advisors")
def admin_advisors(status: str = "", key: str = "",
                   x_admin_key: Optional[str] = Header(None, alias="X-Admin-Key")):
    _admin(key, x_admin_key)
    return _do(advisors.applications, status)


@router.post("/admin/advisors/review")
def admin_advisor_review(payload: Optional[dict] = Body(None), key: str = "",
                         x_admin_key: Optional[str] = Header(None, alias="X-Admin-Key")):
    # The body is optional in the signature so a request with no key and no
    # body is refused as unauthorised, not as malformed.
    _admin(key, x_admin_key)
    p = payload or {}
    try:
        expert_id = int(p.get("expert_id"))
    except (TypeError, ValueError):
        raise HTTPException(400, "expert_id is required.")
    return {"expert": _do(advisors.review, expert_id, str(p.get("action") or ""),
                          p.get("note") or "")}


@router.get("/admin/advisors/reports")
def admin_advisor_reports(key: str = "",
                          x_admin_key: Optional[str] = Header(None, alias="X-Admin-Key")):
    _admin(key, x_admin_key)
    return {"reports": _do(advisors.reports)}
