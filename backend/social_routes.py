"""
social_routes.py — every route for the Social surface, in one router.

This exists so main.py needs exactly two new lines instead of a hand-edit in
six places. Nothing here imports the scoring engine, and nothing here can
change an alert threshold.

Routes
  GET  /social/feed        the reviewed queue, newest first
  GET  /social/status      what was ingested, what was dropped and why
  GET  /social/health      source + X posting health, no side effects
  POST /social/refresh     poll BSE + NSE now (ADMIN_KEY)
  POST /social/approve     mark an item approved; posts if auto-post is on (ADMIN_KEY)
  POST /social/skip        mark an item skipped (ADMIN_KEY)
  POST /social/post        post an approved item to X now (ADMIN_KEY)
  GET  /social/categories  the filter's category list, for the UI
"""

from __future__ import annotations

import os
from typing import Optional

from fastapi import APIRouter, Body, Header, HTTPException, Query

import social_posts
import social_x

router = APIRouter(prefix="/social", tags=["social"])


def _check_admin(key: Optional[str]) -> None:
    expected = os.getenv("ADMIN_KEY")
    if not expected:
        return  # not configured: behave as before, open
    if key != expected:
        raise HTTPException(status_code=401, detail="admin key required")


@router.get("/feed")
def social_feed(
    limit: int = Query(60, ge=1, le=200),
    status: Optional[str] = None,
    category: Optional[str] = None,
):
    social_posts.build()
    items = social_posts.feed(limit=limit, status=status, category=category)
    return {
        "count": len(items),
        "items": items,
        "posting_mode": "live" if social_x.auto_post_enabled() else "draft",
        "note": (
            "Restatement of company filings only. No opinion, no recommendation, "
            "no target. Figures are the company's own; percentages are arithmetic "
            "on published numbers."
        ),
    }


@router.get("/status")
def social_status():
    return social_posts.status_report()


@router.get("/health")
def social_health():
    rep = social_posts.status_report()
    up = rep.get("upstream_announcements") or {}
    return {
        "ok": up.get("error") is None and up.get("last_poll") is not None,
        "last_build": rep.get("last_build"),
        "upstream_announcements": up,
        "held": rep.get("held"),
        "kept_pct": rep.get("kept_pct"),
        "x": social_x.health(),
        "store": rep.get("store_path"),
    }


@router.get("/categories")
def social_categories():
    return {
        "keep": [
            {"key": r["key"], "label": r["label"], "tier": r["tier"]}
            for r in social_posts.CATEGORY_RULES
        ],
        "drop_reasons": sorted({why for _, why in social_posts.DROP_RULES}),
    }


@router.post("/refresh")
def social_refresh(x_admin_key: Optional[str] = Header(None, alias="X-Admin-Key")):
    _check_admin(x_admin_key)
    # Asks announcements.py to refresh if its data is stale, then rebuilds the
    # drafts. No second fetcher — announcements.py owns the BSE session.
    return social_posts.build(refresh=True)


@router.post("/approve")
def social_approve(
    payload: dict = Body(...),
    x_admin_key: Optional[str] = Header(None, alias="X-Admin-Key"),
):
    _check_admin(x_admin_key)
    item_id = payload.get("id")
    text = payload.get("x_post")
    rec = social_posts.set_status(item_id, "approved", text)
    if not rec:
        raise HTTPException(status_code=404, detail="item not found")
    result = {"item": rec, "posted": None}
    if social_x.auto_post_enabled() and rec.get("tier") == "A":
        result["posted"] = social_x.post(rec.get("x_post", ""))
        if result["posted"].get("sent"):
            social_posts.set_status(item_id, "posted")
    return result


@router.post("/skip")
def social_skip(
    payload: dict = Body(...),
    x_admin_key: Optional[str] = Header(None, alias="X-Admin-Key"),
):
    _check_admin(x_admin_key)
    rec = social_posts.set_status(payload.get("id"), "skipped")
    if not rec:
        raise HTTPException(status_code=404, detail="item not found")
    return {"item": rec}


@router.post("/post")
def social_post_now(
    payload: dict = Body(...),
    x_admin_key: Optional[str] = Header(None, alias="X-Admin-Key"),
):
    _check_admin(x_admin_key)
    item_id = payload.get("id")
    rec = social_posts.set_status(item_id, "approved", payload.get("x_post"))
    if not rec:
        raise HTTPException(status_code=404, detail="item not found")
    res = social_x.post(rec.get("x_post", ""), force=True)
    if res.get("sent"):
        social_posts.set_status(item_id, "posted")
    return res
