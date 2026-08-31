"""
Share cards.

Two things are being protected here. The first is that the image renders at
all — a broken card means every link posted to X shows a grey box, and the
failure is invisible from the server's side.

The second matters more: a card is published to strangers who never visit the
site, so it must carry scores and nothing that reads as a directive. The test
that asserts no entry, stop or target appears on the card is the reason this
feature is safe to ship.
"""
import json
import re

import pytest

import og


ANALYZE = {
    "ticker": "RELIANCE", "name": "Reliance Industries Limited",
    "scoring": {"score": 42, "label": "MIXED"},
    "technical": {"score": 9}, "fundamental": {"score": 75, "f_score": 6},
    "setup": {"name": "Quality at Discount"},
    "plan": {"entry": 1995.98, "stop": 1836.31, "t1": 2315.34},
}

FLAT = {"symbol": "ACME", "name": "Acme Ltd", "composite": 74, "technical": 81,
        "fundamental": 66, "f_score": 7, "setup": "Momentum Breakout"}

STATS = {"total_tracked": 96,
         "overall": {"avg_alpha_pct": 1.15, "beat_index_pct": 56,
                     "median_days_held": 2}}


def _png_size(data):
    """Width and height straight out of the PNG IHDR, no decoding."""
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")


@pytest.mark.parametrize("payload", [ANALYZE, FLAT], ids=["nested", "flat"])
def test_stock_card_renders_at_the_right_size(payload):
    png = og.stock_card(payload)
    assert _png_size(png) == (1200, 630)
    assert len(png) > 5_000


def test_reader_accepts_both_payload_shapes():
    sym, name, comp, label, tech, fund, fsc, setup = og._read(ANALYZE)
    assert (sym, comp, label, tech, fund, fsc) == ("RELIANCE", 42.0, "MIXED", 9.0, 75.0, 6)
    assert setup == "Quality at Discount"
    sym, name, comp, label, tech, fund, fsc, setup = og._read(FLAT)
    assert (sym, comp, tech, fund, fsc, setup) == ("ACME", 74.0, 81.0, 66.0, 7,
                                                   "Momentum Breakout")


def test_a_missing_score_renders_a_dash_not_a_crash():
    png = og.stock_card({"ticker": "X", "name": "Unknown Co"})
    assert _png_size(png) == (1200, 630)


def test_record_card_renders():
    assert _png_size(og.record_card(STATS)) == (1200, 630)
    assert _png_size(og.record_card({})) == (1200, 630)


def test_the_card_never_carries_a_price_level():
    """
    The compliance guard. The payload handed in contains an entry, a stop and
    a target; none of them may reach the image. A card with a target price on
    it is a recommendation published to the public, which is the line this
    project deliberately does not cross.
    """
    drawn = []
    from PIL import ImageDraw

    original = ImageDraw.ImageDraw.text

    def spy(self, xy, text, *a, **k):
        drawn.append(str(text))
        return original(self, xy, text, *a, **k)

    ImageDraw.ImageDraw.text = spy
    try:
        og.stock_card(ANALYZE)
    finally:
        ImageDraw.ImageDraw.text = original

    blob = "".join(drawn)
    for forbidden in ("1995", "1836", "2315", "1,995", "1,836", "2,315"):
        assert forbidden not in blob, f"a price level reached the card: {forbidden}"
    for word in ("BUY", "SELL", "TARGET", "STOP LOSS"):
        assert word not in blob.upper(), f"a directive reached the card: {word}"
    assert "NOT INVESTMENT ADVICE" in blob.upper()


def test_cards_are_cached_per_day():
    calls = {"n": 0}

    def build():
        calls["n"] += 1
        return b"x"

    og._cache.clear()
    assert og.cached("k", build) == b"x"
    assert og.cached("k", build) == b"x"
    assert calls["n"] == 1


def test_share_page_carries_the_tags_a_crawler_reads():
    html = og.share_page("Acme (ACME) — Altaha", "Scores 74/100.",
                         "https://api.example/og/stock.png?ticker=ACME",
                         "https://site.example/?ticker=ACME")
    for tag in ('property="og:image"', 'property="og:title"', 'property="og:description"',
                'name="twitter:card" content="summary_large_image"',
                'property="og:image:width" content="1200"',
                'rel="canonical"'):
        assert tag in html, tag
    # A human must still land on the app.
    assert "https://site.example/?ticker=ACME" in html


def test_share_page_escapes_hostile_input():
    html = og.share_page('Acme " onload="alert(1)', "<script>alert(1)</script>",
                         "https://x/i.png", "https://x/?t=A")
    assert "<script>alert(1)</script>" not in html
    assert 'onload="alert(1)' not in html
    assert "&lt;script&gt;" in html
