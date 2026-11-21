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
            if path == "/og/wow.png":
                return self.main.og_wow(**q)
            if path.startswith("/share/wow/"):
                return self.main.share_wow(path.rsplit("/", 1)[1], **q)
            if path == "/wow-order":
                return self.main.wow_order_one(**q)
            if path == "/og/concall.png":
                return self.main.og_concall(**q)
            if path.startswith("/share/concall/"):
                return self.main.share_concall(path.rsplit("/", 1)[1], **q)
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


# ---------------------------------------------------------------------------
# A concall, shared
# ---------------------------------------------------------------------------

@pytest.fixture
def call_on_file(client, tmp_path, monkeypatch):
    """One call in the ledger with a written brief, and nothing behind it: the
    feed and the model both fail the test if a card or a share page asks."""
    import datetime as dt
    C = client.main.concall_source
    monkeypatch.setattr(C, "DB_PATH", str(tmp_path / "concalls.db"))
    monkeypatch.setitem(C._db_ready, "done", False)
    monkeypatch.setattr(C, "find", lambda *a, **k: pytest.fail("a card walked the feed"))
    monkeypatch.setattr(C, "write_brief", lambda *a, **k: pytest.fail("a card called a model"))
    monkeypatch.setattr(C, "refresh_if_stale", lambda *a, **k: pytest.fail(
        "a card started the reader"))
    at = dt.datetime.now(C.IST) - dt.timedelta(days=2)
    pdf = "https://www.bseindia.com/x/m.pdf"
    assert C.file_call({"symbol": "M&M", "company": "Mahindra & Mahindra Ltd",
                        "headline": "Earnings Call Transcript", "at": at.isoformat(),
                        "epoch": at.timestamp(), "pdf": pdf},
                       True, {"quarter": "Q2 FY27", "call_date": "2026-11-14", "words": 9000})
    assert C._put_brief(pdf, {
        "status": "ready", "model": "claude-sonnet-5-5", "weight": "high",
        "headline": "Tractor volumes guided to grow 12% in FY27 <b>",
        "summary": ("Management raised its tractor volume guidance to 12% growth for "
                    "FY27. " + "Rural demand was described as firm across regions. " * 12),
    })
    return C


def test_a_concall_card_renders_from_the_ledger_alone(client, call_on_file):
    assert _png(client.get("/og/concall.png?ticker=M%26M&period=Q2-FY27")) == (1200, 630)
    # A link with no quarter, or last quarter's, still has a card.
    assert _png(client.get("/og/concall.png?ticker=M%26M")) == (1200, 630)


def test_a_concall_share_page_is_that_call(client, call_on_file):
    r = client.get("/share/concall/M&M?period=Q2-FY27")
    assert _status(r) == 200, _text(r)[:300]
    html = _text(r)
    for tag in ('property="og:image"', 'name="twitter:card" content="summary_large_image"',
                'rel="canonical"'):
        assert tag in html
    assert "Mahindra &amp; Mahindra Ltd | Q2 FY27 earnings call" in html
    assert "Tractor volumes guided to grow 12% in FY27 &lt;b&gt;" in html
    assert "<b>" not in html, "a tag in a model's headline reached the page as markup"
    # The symbol's ampersand must not end the parameter it is in.
    assert "/og/concall.png?ticker=M%26M&amp;period=Q2-FY27" in html
    assert "go=concalls&amp;q=M%26M" in html, "a shared call must open the call"
    assert "onrender.com" not in html
    # The description is the summary, cut to a length a preview will show.
    desc = re.search(r'<meta name="description" content="([^"]*)"', html).group(1)
    assert desc.startswith("Management raised its tractor volume guidance")
    assert len(desc) <= 300 and desc.endswith("…")


def test_a_call_with_no_brief_has_no_card_and_no_share_page(client, call_on_file):
    """Better a 404 than a card for a summary that was never written."""
    assert _status(client.get("/og/concall.png?ticker=NOBRIEF")) == 404
    assert _status(client.get("/share/concall/NOBRIEF")) == 404
    assert _status(client.get("/og/concall.png?ticker=")) in (400, 422)


# ---------------------------------------------------------------------------
# An order win, shared
# ---------------------------------------------------------------------------

@pytest.fixture
def order_on_file(client, tmp_path, monkeypatch):
    """One order in the ledger and none in memory, with nothing behind it:
    the exchange fails the test if a card or a share page asks."""
    W = client.main.wow_orders
    monkeypatch.setattr(W, "DB_PATH", str(tmp_path / "wow.db"))
    monkeypatch.setitem(W._db_ready, "done", False)
    monkeypatch.setattr(W, "_cache", {"at": 0.0, "rows": [], "note": ""})
    monkeypatch.setattr(W, "_order_items", lambda days: pytest.fail("a card walked the feed"))
    monkeypatch.setattr(W, "feed", lambda *a, **k: pytest.fail("a card started the reader"))
    monkeypatch.setattr(W, "company_facts", lambda s: {
        "market_cap_cr": 3569.3, "sales_cr": 2641.27, "sales_year": "FY26"})
    monkeypatch.setattr(W, "market_cap_cr", lambda s: 3569.3)
    text = ("Name of the entity awarding the order(s)/contract(s); NTPC Green <b>Energy</b> Limited\n"
            "Nature of order(s) / contract(s); BESS system supply and integration\n"
            "Time period by which the order(s)/contract(s) is to be executed; By September 2027\n"
            "Broad consideration or size of the order(s)/contract(s); Rs. 26,913 Million\n"
            "Whether the promoter group have any interest; No\n")
    row = W.size_up(W.read_filing(
        {"symbol": "M&M", "company": "Mahindra & Mahindra Ltd",
         "headline": "has received a Letter of Award (LOA)",
         "at": "2026-11-16T14:55:00+05:30", "pdf": "https://x/loa.pdf"}, text))
    assert W.record([row]) == 1
    return row


def test_a_wow_card_renders_from_the_ledger_alone(client, order_on_file):
    key = order_on_file["key"]
    assert _png(client.get("/og/wow.png?ticker=M%26M&id=" + key)) == (1200, 630)
    # A link with no handle, or one that names nothing, still has a card.
    assert _png(client.get("/og/wow.png?ticker=M%26M")) == (1200, 630)
    assert _png(client.get("/og/wow.png?ticker=M%26M&id=zzzz")) == (1200, 630)


def test_a_wow_share_page_is_that_order(client, order_on_file):
    key = order_on_file["key"]
    r = client.get("/share/wow/M&M?id=" + key)
    assert _status(r) == 200, _text(r)[:300]
    html = _text(r)
    for tag in ('property="og:image"', 'name="twitter:card" content="summary_large_image"',
                'rel="canonical"'):
        assert tag in html
    assert ("Mahindra &amp; Mahindra Ltd: ₹2,691 cr letter of award from "
            "NTPC Green &lt;b&gt;Energy&lt;/b&gt; Limited") in html
    assert "<b>" not in html, "a tag in a customer's name reached the page as markup"
    assert "That is 75% of the company's market cap of ₹3,569 cr" in html.replace("&#x27;", "'")
    assert "12.2 months of FY26 sales" in html
    # The symbol's ampersand must not end the parameter it is in.
    assert "/og/wow.png?ticker=M%26M&amp;id=" + key in html
    assert "go=wow&amp;q=M%26M&amp;id=" + key in html, "a shared order must open the order"
    assert "onrender.com" not in html


def test_one_order_can_be_asked_for_by_name(client, order_on_file):
    """What the page asks for when a link is older than the week it lists."""
    out = client.get("/wow-order?ticker=M%26M&id=" + order_on_file["key"])
    assert out["available"] is True and out["threshold_pct"] == 10.0
    assert out["row"]["value_cr"] == 2691.3 and out["row"]["wow"] is True
    assert out["row"]["nature"] == "BESS system supply and integration"
    assert client.get("/wow-order?ticker=NOORDER")["available"] is False


def test_an_order_with_no_card_has_no_share_page(client, order_on_file):
    """Better a 404 than a card for a bid, a memorandum or nothing at all."""
    assert _status(client.get("/og/wow.png?ticker=NOORDER")) == 404
    assert _status(client.get("/share/wow/NOORDER")) == 404
    assert _status(client.get("/og/wow.png?ticker=")) in (400, 422)


def test_vercel_rewrites_cover_every_public_path():
    """
    The seam. The backend now hands out https://SITE/share/... and
    https://SITE/og/... — which are 404s on the static host unless the rewrite
    exists. Both halves would be individually correct and every shared link
    would be dead, which is this project's recurring failure exactly.

    Which is what happened: the file sat at the repo root for two months while
    the Vercel project's Root Directory is `frontend`, so Vercel never read it
    and /share/RELIANCE was Vercel's own 404 on the live site. It has to live
    in frontend/, and one at the root is a decoy that looks like it works.
    """
    import json
    assert not os.path.exists(os.path.join(REPO, "vercel.json")), (
        "vercel.json at the repo root is ignored: the Vercel project's Root "
        "Directory is frontend. Put it in frontend/vercel.json")
    path = os.path.join(REPO, "frontend", "vercel.json")
    assert os.path.exists(path), "frontend/vercel.json is gone — every shared link is now a 404"
    cfg = json.load(open(path, encoding="utf-8"))
    sources = [r["source"] for r in cfg.get("rewrites", [])]
    assert any(s.startswith("/share/") for s in sources), "no /share rewrite"
    assert any(s.startswith("/og/") for s in sources), "no /og rewrite"
    # The pages the API writes for a search engine are proxied too
    # (company_pages.py; test_company_pages.py checks each has a route).
    proxied = ("/share/", "/og/", "/stock-", "/sector-", "/stocks", "/sitemap.xml")
    for r in cfg.get("rewrites", []):
        if r["source"] == "/share" or r["source"].startswith(proxied):
            # Proxied to the API: must leave the static host.
            assert r["destination"].startswith("https://"), r
        else:
            # A clean page address (/stock -> /stock.html, see DEPLOY-SHARE.md):
            # must name a page that is actually in frontend/, or it is a 404.
            dest = r["destination"]
            assert dest.startswith("/") and dest.endswith(".html"), r
            assert os.path.exists(os.path.join(REPO, "frontend", dest.lstrip("/"))), r
