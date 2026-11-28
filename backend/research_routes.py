"""
research_routes.py — every route for the Research Deck, in one router.

The rules live in research_deck.py; this file turns them into HTTP. Errors
arrive as exceptions and leave as status codes, as in forum_routes.py:

  ValueError   400  something sent is not acceptable, with a sentence
  LookupError  404  not there (or not published)

Routes
  GET  /research/articles               published articles, newest first
  GET  /research/articles/{slug}        one published article
  GET  /research/media/{media_id}       a photo in a published article
  GET  /og/research.png?slug=&v=        the 1200x630 card X shows
  GET  /share/research/{slug}           the page X reads; forwards a person on
  GET  /admin/research                  every article, drafts too; ?id= for one
  POST /admin/research/media            upload a photo {data: base64 | data URL}
  POST /admin/research/save             create or update an article
  POST /admin/research/delete           delete an article {id}

ONLY THE OWNER WRITES
Every /admin/research route needs ADMIN_KEY, in the X-Admin-Key header or as
?key=, and is CLOSED when ADMIN_KEY is unset (unlike the older control
switches in main.py, which stay open for a local run). The key is checked
before the body is read, so a request without it learns nothing about what
the body should have been.
"""
from __future__ import annotations

import hmac
import json
import os
import sqlite3
from typing import Annotated, Any, Optional
from urllib.parse import quote

from fastapi import APIRouter, Body, Header, HTTPException, Query, Response

import og as og_cards
import research_deck as RD

router = APIRouter(tags=["research"])

# Annotated, so a direct call (the tests) gets None rather than a Header object.
AdminHeader = Annotated[Optional[str], Header(alias="X-Admin-Key")]

SITE_URL = os.environ.get("SITE_URL", "https://altahascreener.in").rstrip("/")
SHARE_ORIGIN = os.environ.get("SHARE_ORIGIN", SITE_URL).rstrip("/")
PAGE = "/research-deck"


def _check_admin(header_key: Optional[str], query_key: Optional[str]) -> None:
    expected = (os.getenv("ADMIN_KEY") or "").strip()
    if not expected:
        raise HTTPException(401, "The Research Deck editor is closed: ADMIN_KEY is not set "
                                 "on the server.")
    given = (header_key or query_key or "").strip()
    if not given or not hmac.compare_digest(given.encode(), expected.encode()):
        raise HTTPException(401, "admin key required")


def _do(fn, *a, **k):
    try:
        return fn(*a, **k)
    except LookupError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    except sqlite3.Error as e:
        print(f"[research] database: {type(e).__name__}: {e}", flush=True)
        raise HTTPException(503, "The Research Deck is unavailable just now. Try again in a minute.")


def article_url(slug: str) -> str:
    return f"{SITE_URL}{PAGE}?a={quote(slug, safe='')}"


def share_url(a: dict) -> str:
    return f"{SHARE_ORIGIN}/share/research/{quote(a['slug'], safe='')}?v={a['version']}"


def card_url(a: dict) -> str:
    return f"{SHARE_ORIGIN}/og/research.png?slug={quote(a['slug'], safe='')}&v={a['version']}"


def _with_links(a: dict) -> dict:
    a = dict(a)
    a["url"] = article_url(a["slug"])
    a["share_url"] = share_url(a)
    a["card_url"] = card_url(a)
    return a


# ── public ──────────────────────────────────────────────────────────────

@router.get("/research/articles")
def research_articles(ticker: Optional[str] = None,
                      limit: Annotated[int, Query(ge=1, le=100)] = 30,
                      offset: Annotated[int, Query(ge=0)] = 0):
    out = _do(RD.listing, include_drafts=False, ticker=ticker, limit=limit, offset=offset)
    out["items"] = [_with_links(a) for a in out["items"]]
    return out


@router.get("/research/articles/{slug}")
def research_article(slug: str):
    a = _do(RD.get, slug, include_drafts=False)
    if a is None:
        raise HTTPException(404, "There is no such article, or it is not published.")
    return _with_links(a)


@router.get("/research/media/{media_id}")
def research_media(media_id: str, key: Optional[str] = None,
                   x_admin_key: AdminHeader = None):
    # A photo in a draft is the owner's until the article is published; the
    # editor previews it by passing the key.
    public = True
    if key or x_admin_key:
        _check_admin(x_admin_key, key)
        public = False
    got = _do(RD.get_media, media_id, public=public)
    if got is None:
        raise HTTPException(404, "There is no such photo.")
    mime, data = got
    cache = ("public, max-age=31536000, immutable" if public else "private, no-store")
    return Response(content=data, media_type=mime, headers={"Cache-Control": cache})


@router.get("/og/research.png")
def og_research(slug: str = "", v: Optional[str] = None):
    a = _do(RD.get, slug, include_drafts=False) if slug else None
    if a is None:
        raise HTTPException(404, "There is no such article, or it is not published.")
    cover = None
    if a.get("cover"):
        got = _do(RD.get_media, a["cover"], public=True)
        cover = got[1] if got else None
    try:
        png = og_cards.cached(f"research:{a['slug']}:{a['version']}",
                              lambda: og_cards.research_card(a, cover))
    except Exception as e:
        raise HTTPException(500, f"Could not render the card: {str(e)[:100]}")
    return Response(content=png, media_type="image/png",
                    headers={"Cache-Control": "public, max-age=3600, s-maxage=86400"})


@router.get("/share/research/{slug}")
def share_research(slug: str):
    a = _do(RD.get, slug, include_drafts=False)
    if a is None:
        # A link to an article taken down still lands somewhere useful.
        return Response(content=og_cards.share_page(
            "Research Deck | Altaha Screener",
            "Research notes, charts and photos from Altaha.",
            f"{SHARE_ORIGIN}/og/record.png", f"{SITE_URL}{PAGE}"),
            media_type="text/html", status_code=404)
    desc = a.get("summary") or " ".join((a.get("body") or "").split())[:240]
    return Response(content=og_cards.share_page(
        f"{a['title']} | Altaha Research", desc, card_url(a), article_url(a["slug"])),
        media_type="text/html")


# ── the owner ───────────────────────────────────────────────────────────

def _payload(body: Any) -> dict:
    if isinstance(body, (bytes, str)):
        try:
            body = json.loads(body)
        except Exception:
            raise HTTPException(400, "Send JSON.")
    if not isinstance(body, dict):
        raise HTTPException(400, "Send a JSON object.")
    return body


@router.get("/admin/research")
def admin_research(id: Optional[str] = None, key: Optional[str] = None,
                   x_admin_key: AdminHeader = None):
    _check_admin(x_admin_key, key)
    if id:
        a = _do(RD.get, id, include_drafts=True)
        if a is None:
            raise HTTPException(404, "There is no such article.")
        return _with_links(a)
    out = _do(RD.listing, include_drafts=True, limit=100)
    out["items"] = [_with_links(a) for a in out["items"]]
    return out


@router.post("/admin/research/media")
def admin_research_media(body: Annotated[Any, Body()] = None, key: Optional[str] = None,
                         x_admin_key: AdminHeader = None):
    _check_admin(x_admin_key, key)
    p = _payload(body)
    return _do(RD.save_media, p.get("data"))


@router.post("/admin/research/save")
def admin_research_save(body: Annotated[Any, Body()] = None, key: Optional[str] = None,
                        x_admin_key: AdminHeader = None):
    _check_admin(x_admin_key, key)
    return _with_links(_do(RD.save, _payload(body)))


@router.post("/admin/research/delete")
def admin_research_delete(body: Annotated[Any, Body()] = None, key: Optional[str] = None,
                          x_admin_key: AdminHeader = None):
    _check_admin(x_admin_key, key)
    return _do(RD.delete, _payload(body).get("id"))
