"""
news_routes.py — routes for the market news surface.

Mounted under /social/news deliberately. news_feed.py from Update 3 already owns
/news/press and /news/status, and those stay exactly where they are. Nothing
here collides with them.

  GET  /social/news/feed      clustered stories, ranked
  GET  /social/news/status    per-source health, what was dropped and why
  GET  /social/news/themes    the theme list, for the UI filter
  POST /social/news/refresh   fetch all enabled sources now (ADMIN_KEY)
  POST /social/news/skip      hide a story from the queue (ADMIN_KEY)
"""

from __future__ import annotations

import os
from typing import Optional

from fastapi import APIRouter, Body, Header, HTTPException, Query

import market_news

router = APIRouter(prefix="/social/news", tags=["social-news"])


def _check_admin(key: Optional[str]) -> None:
    expected = os.getenv("ADMIN_KEY")
    if not expected:
        return
    if key != expected:
        raise HTTPException(status_code=401, detail="admin key required")


_poller_started = False


def _ensure_poller() -> None:
    """Start the background poller on first use rather than at import.

    See the comment in main.py: a thread per worker at import time is what
    made the instance unstable. Lazy start means the cost is only paid by
    someone actually looking at the news tab.
    """
    global _poller_started
    if _poller_started:
        return
    _poller_started = True
    try:
        market_news.start_poller()
    except Exception:
        pass


@router.get("/feed")
def news_feed_route(
    limit: int = Query(40, ge=1, le=120),
    theme: Optional[str] = None,
    symbol: Optional[str] = None,
    min_corroboration: int = Query(1, ge=1, le=8),
):
    _ensure_poller()
    clusters = market_news.feed(limit=limit, theme=theme, symbol=symbol,
                               min_corroboration=min_corroboration)
    return {
        "count": len(clusters),
        "clusters": clusters,
        "note": (
            "Press coverage, not company filings, and never merged with them. "
            "Headlines are reproduced as published with the publication named "
            "and the original linked."
        ),
    }


@router.get("/status")
def news_status_route():
    _ensure_poller()
    return market_news.status_report()


@router.get("/themes")
def news_themes_route():
    return {
        "themes": sorted(market_news.THEMES.keys()),
        "weights": market_news.THEME_WEIGHT,
        "drop_reasons": sorted({why for _, why in market_news.KILL}),
    }


@router.post("/refresh")
def news_refresh_route(x_admin_key: Optional[str] = Header(None, alias="X-Admin-Key")):
    _check_admin(x_admin_key)
    return market_news.poll_once()


@router.post("/skip")
def news_skip_route(
    payload: dict = Body(...),
    x_admin_key: Optional[str] = Header(None, alias="X-Admin-Key"),
):
    _check_admin(x_admin_key)
    rec = market_news.set_status(payload.get("id"), "skipped")
    if not rec:
        raise HTTPException(status_code=404, detail="story not found")
    return {"item": rec}
