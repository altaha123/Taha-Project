"""
The Research Deck: only the owner writes, the public reads what is published,
and what goes out on X carries the right card.

The failures worth testing for are the quiet ones. A draft whose photo can be
fetched by anyone who guesses nothing more than its address. A phone photo
published with the GPS position it was taken at still inside it. An edited
title that silently moved the article's address, breaking every link already
posted. An editor left open on a deploy that forgot ADMIN_KEY. None of these
crash.

Handlers are called directly, as test_forum.py does; one TestClient check at
the end covers the wiring.
"""
import base64
import io
import os
import tempfile

import pytest
from fastapi import HTTPException
from PIL import Image

import research_deck as RD
import research_routes as R

KEY = "deck-key"


@pytest.fixture(autouse=True)
def fresh_db(monkeypatch):
    with tempfile.TemporaryDirectory() as d:
        RD.reset_for_tests(os.path.join(d, "research.db"))
        monkeypatch.setenv("ADMIN_KEY", KEY)
        yield


def png_b64(size=(320, 200), colour=(30, 90, 160), mode="RGB"):
    buf = io.BytesIO()
    Image.new(mode, size, colour).save(buf, "PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def jpeg_with_gps_b64(size=(3000, 2000)):
    img = Image.new("RGB", size, (200, 120, 40))
    exif = Image.Exif()
    exif[0x8825] = {2: (12.0, 58.0, 0.0), 4: (77.0, 35.0, 0.0)}   # GPSInfo
    exif[0x010F] = "PhoneMaker"
    buf = io.BytesIO()
    img.save(buf, "JPEG", exif=exif)
    return base64.b64encode(buf.getvalue()).decode()


def upload(data=None):
    return R.admin_research_media({"data": png_b64() if data is None else data}, x_admin_key=KEY)


def save(**fields):
    base = {"title": "Why capital goods are rerating", "summary": "Orders, margins and the cycle.",
            "body": "The order book tells the story.", "status": "published"}
    base.update(fields)
    return R.admin_research_save(base, x_admin_key=KEY)


# ── who may write ───────────────────────────────────────────────────────

def test_every_write_needs_the_key():
    for call in (lambda k: R.admin_research(x_admin_key=k),
                 lambda k: R.admin_research_media({"data": png_b64()}, x_admin_key=k),
                 lambda k: R.admin_research_save({"title": "Something"}, x_admin_key=k),
                 lambda k: R.admin_research_delete({"id": 1}, x_admin_key=k)):
        for wrong in (None, "", "nope"):
            with pytest.raises(HTTPException) as e:
                call(wrong)
            assert e.value.status_code == 401


def test_the_editor_is_closed_when_no_admin_key_is_set(monkeypatch):
    monkeypatch.delenv("ADMIN_KEY", raising=False)
    with pytest.raises(HTTPException) as e:
        R.admin_research_save({"title": "Anything at all"}, x_admin_key="")
    assert e.value.status_code == 401
    with pytest.raises(HTTPException):
        R.admin_research_media({"data": png_b64()}, key="whatever")


def test_the_key_also_works_in_the_query_string():
    assert R.admin_research(key=KEY)["total"] == 0


# ── photos ──────────────────────────────────────────────────────────────

def test_a_phone_photo_loses_its_gps_and_is_shrunk():
    m = upload(jpeg_with_gps_b64())
    assert m["mime"] == "image/jpeg"
    assert max(m["width"], m["height"]) <= RD.MAX_SIDE
    mime, data = RD.get_media(m["id"], public=False)
    img = Image.open(io.BytesIO(data))
    exif = img.getexif()
    assert 0x8825 not in exif and 0x010F not in exif, "EXIF survived the upload"


def test_a_screenshot_stays_png():
    m = upload(png_b64())
    assert m["mime"] == "image/png"
    assert m["ref"] == "media:" + m["id"]


def test_a_transparent_png_keeps_its_transparency():
    m = upload(png_b64(mode="RGBA", colour=(0, 0, 0, 0)))
    _mime, data = RD.get_media(m["id"], public=False)
    assert Image.open(io.BytesIO(data)).mode == "RGBA"


@pytest.mark.parametrize("data", [
    "", "not base64 at all!!!",
    base64.b64encode(b"<svg xmlns='http://www.w3.org/2000/svg'></svg>").decode(),
    base64.b64encode(b"%PDF-1.4 not an image").decode(),
])
def test_anything_that_is_not_a_photo_is_refused(data):
    with pytest.raises(HTTPException) as e:
        upload(data)
    assert e.value.status_code == 400


def test_a_draft_photo_is_not_public_until_the_article_is():
    m = upload()
    a = save(cover=m["ref"], status="draft")
    with pytest.raises(HTTPException) as e:
        R.research_media(m["id"])
    assert e.value.status_code == 404
    # The owner's editor can still preview it.
    assert R.research_media(m["id"], key=KEY).status_code == 200
    save(id=a["id"], cover=m["ref"], status="published")
    r = R.research_media(m["id"])
    assert r.status_code == 200 and "immutable" in r.headers["cache-control"]


def test_a_photo_in_the_body_is_published_with_the_article():
    m = upload()
    save(body=f"Look at this.\n\n![The order book](media:{m['id']})")
    assert R.research_media(m["id"]).status_code == 200


def test_deleting_an_article_deletes_its_photos():
    m = upload()
    a = save(cover=m["ref"])
    R.admin_research_delete({"id": a["id"]}, x_admin_key=KEY)
    assert RD.get_media(m["id"], public=False) is None


def test_a_cover_that_was_never_uploaded_is_refused():
    with pytest.raises(HTTPException) as e:
        save(cover="media:0123456789abcdef")
    assert e.value.status_code == 400


# ── articles ────────────────────────────────────────────────────────────

def test_drafts_are_not_public():
    a = save(status="draft")
    assert R.research_articles()["total"] == 0
    with pytest.raises(HTTPException) as e:
        R.research_article(a["slug"])
    assert e.value.status_code == 404
    assert R.admin_research(x_admin_key=KEY)["total"] == 1


def test_the_address_does_not_move_when_the_title_does():
    a = save()
    b = save(id=a["id"], title="A completely different headline")
    assert b["slug"] == a["slug"]
    assert b["version"] == a["version"] + 1
    assert b["published_at"] == a["published_at"]
    assert b["card_url"] != a["card_url"], "X would keep showing the old card"


def test_two_articles_with_one_title_get_two_addresses():
    assert save()["slug"] != save()["slug"]


def test_tickers_are_cleaned_and_filterable():
    a = save(tickers="tcs, infy.ns, INFY, uno minda")
    assert a["tickers"] == ["TCS", "INFY", "UNOMINDA"]
    save(title="Banks", tickers=["HDFCBANK"])
    assert [x["slug"] for x in R.research_articles(ticker="infy")["items"]] == [a["slug"]]
    with pytest.raises(HTTPException):
        save(tickers="<script>")


def test_a_title_is_required_and_bounded():
    for bad in ("", "  ", "x" * (RD.TITLE_MAX + 1)):
        with pytest.raises(HTTPException) as e:
            save(title=bad)
        assert e.value.status_code == 400


# ── what X sees ─────────────────────────────────────────────────────────

def test_the_share_page_carries_the_card_and_forwards_to_the_article():
    m = upload()
    a = save(cover=m["ref"], title='Q3 "beats" & <misses>')
    html = R.share_research(a["slug"]).body.decode()
    assert 'name="twitter:card" content="summary_large_image"' in html
    assert f"/og/research.png?slug={a['slug']}&amp;v={a['version']}" in html
    assert f"/research-deck?a={a['slug']}" in html
    assert "<misses>" not in html, "the title reached the page unescaped"
    assert "onrender.com" not in html


def test_the_card_renders_with_and_without_a_cover():
    for cover in (None, upload()["ref"]):
        a = save(title="A long title " * 8, summary="One sentence. Two sentences. Three.",
                 cover=cover, tickers="TCS,INFY,HDFCBANK,ITC,LT")
        r = R.og_research(slug=a["slug"], v=str(a["version"]))
        img = Image.open(io.BytesIO(r.body))
        assert img.size == (1200, 630)


def test_no_card_or_share_page_for_a_draft():
    a = save(status="draft")
    with pytest.raises(HTTPException):
        R.og_research(slug=a["slug"])
    assert R.share_research(a["slug"]).status_code == 404


# ── wiring ──────────────────────────────────────────────────────────────

def test_the_routes_are_served_over_http():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    app = FastAPI()
    app.include_router(R.router)
    c = TestClient(app)
    assert c.post("/admin/research/save", json={"title": "Hello there"}).status_code == 401
    up = c.post("/admin/research/media", json={"data": png_b64()}, headers={"X-Admin-Key": KEY})
    assert up.status_code == 200, up.text
    sv = c.post("/admin/research/save", headers={"X-Admin-Key": KEY},
                json={"title": "Hello there", "summary": "Hi.", "cover": up.json()["ref"],
                      "status": "published"})
    assert sv.status_code == 200, sv.text
    slug = sv.json()["slug"]
    assert c.get("/research/articles").json()["items"][0]["slug"] == slug
    assert c.get(f"/share/research/{slug}").status_code == 200
    assert c.get(f"/og/research.png?slug={slug}").headers["content-type"] == "image/png"
