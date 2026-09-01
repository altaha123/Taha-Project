"""
The card and share endpoints, end to end.

These are the routes a stranger's browser hits, and every one of them fails
silently from the server's point of view: a crawler that gets a 500 shows a
grey box in the timeline and tells nobody. So they are exercised here with the
data feed stubbed out, which is the only part of the path that cannot be.

The assertion that matters most is the last one. A published document must
never name the API's hosting provider — that host appears in a link, links are
permanent, and infrastructure is not.
"""
import os
import re
import sys

import numpy as np
import pytest

from conftest import ohlcv, arc, ramp

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.dirname(BACKEND)


# The routes are called directly rather than through TestClient. Starlette's
# TestClient needs httpx, which this project does not otherwise depend on, and
# a share card is not worth a production dependency; calling the handler runs
# the same code with the same validation and the same exceptions.


class Client:
    """The two things a caller needs: the route, and what came back."""

    def __init__(self, main):
        self.main = main

    def get(self, url):
        from urllib.parse import urlparse, parse_qs
        u = urlparse(url)
        q = {k: v[0] for k, v in parse_qs(u.query, keep_blank_values=True).items()}
        path = u.path
        try:
            if path == "/og/chart.png":
                return self.main.og_chart(**q)
            if path == "/og/idea.png":
                return self.main.og_idea(**q)
            if path == "/og/holding.png":
                return self.main.og_holding(**q)
            if path == "/og/stock.png":
                return self.main.og_stock(**q)
            if path == "/og/record.png":
                return self.main.og_record()
            if path == "/share/record":
                return self.main.share_record()
            if path.startswith("/share/chart/"):
                return self.main.share_chart(path.rsplit("/", 1)[1], **q)
            if path.startswith("/share/idea/"):
                return self.main.share_idea(path.rsplit("/", 1)[1], **q)
            if path.startswith("/share/holding/"):
                return self.main.share_holding(path.rsplit("/", 1)[1])
            if path.startswith("/share/"):
                return self.main.share_stock(path.rsplit("/", 1)[1])
        except Exception as e:
            return e
        raise AssertionError("no route for " + url)


@pytest.fixture(scope="module")
def client():
    import data_source
    import main

    frame = ohlcv(arc(150, 100, 160) + ramp(150, 168, 120))

    def fake_resolve(raw):
        return raw.upper() + ".NS", None, frame

    data_source.resolve = fake_resolve
    main.resolve = fake_resolve
    return Client(main)


def _status(resp):
    from fastapi import HTTPException
    return resp.status_code if isinstance(resp, HTTPException) else 200


def _text(resp):
    body = getattr(resp, "body", b"")
    return body.decode("utf-8") if isinstance(body, (bytes, bytearray)) else str(body)


def _png(resp):
    assert _status(resp) == 200, _text(resp)[:300]
    assert resp.media_type == "image/png"
    body = resp.body
    assert body[:8] == b"\x89PNG\r\n\x1a\n"
    return (int.from_bytes(body[16:20], "big"), int.from_bytes(body[20:24], "big"))


@pytest.mark.parametrize("url", [
    "/og/chart.png?ticker=RELIANCE",
    "/og/chart.png?ticker=RELIANCE&range=1W",
    "/og/record.png",
])
def test_cards_render(client, url):
    assert _png(client.get(url)) == (1200, 630)


def test_an_intraday_range_falls_back_rather_than_failing(client):
    """
    A card must never 500. Without the Dhan feed an intraday range cannot be
    served, and a broken image in somebody's timeline is a worse answer than
    the daily chart — which is still a truthful answer to "show me this stock".
    """
    assert _png(client.get("/og/chart.png?ticker=RELIANCE&range=5m")) == (1200, 630)


def test_an_unknown_range_falls_back_to_daily(client):
    assert _png(client.get("/og/chart.png?ticker=RELIANCE&range=zz")) == (1200, 630)


def test_a_missing_ticker_is_rejected_not_rendered(client):
    assert _status(client.get("/og/chart.png?ticker=")) in (400, 422)


@pytest.mark.parametrize("url", [
    "/share/RELIANCE",
    "/share/chart/RELIANCE",
    "/share/chart/RELIANCE?range=1W",
    "/share/record",
])
def test_share_pages_carry_the_tags_a_crawler_reads(client, url):
    r = client.get(url)
    assert _status(r) == 200, _text(r)[:300]
    html = _text(r)
    for tag in ('property="og:image"', 'property="og:title"',
                'name="twitter:card" content="summary_large_image"',
                'rel="canonical"'):
        assert tag in html, f"{url} is missing {tag}"


@pytest.mark.parametrize("url", [
    "/share/RELIANCE",
    "/share/chart/RELIANCE?range=1D",
    "/share/idea/RELIANCE",
    "/share/record",
])
def test_no_share_page_names_the_hosting_provider(client, url):
    """
    The guard on the whole point of this change.

    Every URL a share page publishes — the card, the canonical, the link a
    human follows — must be on the site's own domain. vercel.json proxies
    /share and /og through to the API so both hosts serve the same documents;
    only one of them is allowed to appear in public.
    """
    r = client.get(url)
    assert _status(r) == 200, _text(r)[:300]
    assert "onrender.com" not in _text(r), (
        f"{url} published the API's hosting provider in a link")


def test_the_chart_share_page_links_to_the_charts_tab(client):
    html = _text(client.get("/share/chart/RELIANCE?range=1W"))
    assert "go=charts" in html, "a shared chart must open the chart"
    assert "range=1W" in html, "a shared chart must open on the timeframe it shows"
    assert "q=RELIANCE" in html


def test_holding_share_page_404s_for_an_untracked_symbol(client):
    """Better a 404 than a card describing a position that does not exist."""
    assert _status(client.get("/share/holding/NOTTRACKED")) == 404


def test_vercel_rewrites_cover_every_public_path():
    """
    The seam. The backend now hands out https://SITE/share/... and
    https://SITE/og/... — which are 404s on the static host unless the rewrite
    exists. Both halves would be individually correct and every shared link
    would be dead, which is this project's recurring failure exactly.
    """
    import json
    path = os.path.join(REPO, "vercel.json")
    assert os.path.exists(path), "vercel.json is gone — every shared link is now a 404"
    cfg = json.load(open(path, encoding="utf-8"))
    sources = [r["source"] for r in cfg.get("rewrites", [])]
    assert any(s.startswith("/share/") for s in sources), "no /share rewrite"
    assert any(s.startswith("/og/") for s in sources), "no /og rewrite"
    for r in cfg.get("rewrites", []):
        assert r["destination"].startswith("https://"), r
