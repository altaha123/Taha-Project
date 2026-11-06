"""
query_ai_routes.py — Ask AI on the query screener, behind the admin key.

  GET  /admin/query/ai   is it switched on; also how the page checks a key
  POST /admin/query/ai   one question:
                         {"messages": [{"role": "user", "content": "..."}, ...],
                          "query": "what is in the editor", "error": "its error"}

CLOSED WHEN ADMIN_KEY IS UNSET. The control endpoints in main.py stay open
without a key so a local run works; this one does not, because every question
is billed to the ANTHROPIC_API_KEY on the server. The key may come in the
X-Admin-Key header (what the page sends) or as ?key= (what test_admin_auth.py
requires of every /admin route).

The handlers are plain `def`, not `async def`: a question can take tens of
seconds, and FastAPI runs a sync handler on its thread pool, so a slow answer
holds one worker thread rather than the event loop every other route shares.
The body is optional for the same reason the guard comes first: a request with
no key and no body must get 401, not a 422 about the body.
"""
from __future__ import annotations

import hmac
import os
from typing import Optional

from fastapi import APIRouter, Body, Header, HTTPException

import query_assistant

router = APIRouter(tags=["query-ai"])


def _admin(key: str, header: Optional[str]) -> None:
    expected = os.environ.get("ADMIN_KEY", "").strip()
    given = (header or key or "").strip()
    if not expected or not hmac.compare_digest(given.encode(), expected.encode()):
        raise HTTPException(401, "Ask AI needs the admin key (X-Admin-Key).")


@router.get("/admin/query/ai")
def query_ai_status(key: str = "",
                    x_admin_key: Optional[str] = Header(None, alias="X-Admin-Key")):
    """Whether Ask AI is switched on, and the model it uses."""
    _admin(key, x_admin_key)
    return query_assistant.status()


@router.post("/admin/query/ai")
def query_ai_ask(payload: Optional[dict] = Body(None), key: str = "",
                 x_admin_key: Optional[str] = Header(None, alias="X-Admin-Key")):
    """One question about the screener, answered with checked queries."""
    _admin(key, x_admin_key)
    payload = payload if isinstance(payload, dict) else {}
    try:
        return query_assistant.ask(payload.get("messages"),
                                   current_query=payload.get("query") or "",
                                   current_error=payload.get("error") or "")
    except query_assistant.AskError as e:
        raise HTTPException(400, str(e))
