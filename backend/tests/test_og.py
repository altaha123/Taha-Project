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

# The summary of the track record (call_log.listing), which is what the card
# is drawn from.
STATS = {"calls": 96, "since_priced": 94, "up_since": 55, "up_since_pct": 58.5,
         "avg_since_pct": 2.31, "median_since_pct": 1.4, "median_days": 6,
         "index_priced": 80, "beat_index_pct": 56.3, "avg_vs_index_pct": 1.15}


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
    # Before the index's closes have loaded the card has no index figure to
    # print, and says how long the ideas have run in its place.
    assert _png_size(og.record_card(dict(STATS, index_priced=0, avg_vs_index_pct=None))) == (1200, 630)


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
    html = og.share_page("Acme (ACME) | Altaha", "Scores 74/100.",
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


# ---------------------------------------------------------------------------
# The rest of the cards
# ---------------------------------------------------------------------------

def _candles(n=220, start=100.0):
    """A deterministic price series. Shape does not matter; coverage does."""
    import math
    out = []
    t = 1_700_000_000
    for i in range(n):
        base = start + 18 * math.sin(i / 21.0) + i * 0.08
        o = base
        c = base + math.sin(i / 3.0)
        h = max(o, c) + 1.4
        l = min(o, c) - 1.4
        out.append([t + i * 86400, round(o, 2), round(h, 2), round(l, 2),
                    round(c, 2), 100000 + (i % 17) * 4000])
    return out


CHART = {
    "symbol": "RELIANCE", "name": "Reliance Industries Limited",
    "timeframe": "1 day", "candles": _candles(),
    "last": 118.42, "change_pct": 12.4,
    "ema20": [None] * 19 + [100.0 + i * 0.09 for i in range(201)],
    "ema50": [None] * 49 + [99.0 + i * 0.08 for i in range(171)],
    "shape": {
        "name": "Cup and Handle", "status": "forming", "direction": "bullish",
        "confidence": 74,
        "points": [
            {"i": 120, "price": 112.0, "label": "L"},
            {"i": 150, "price": 88.0, "label": "B"},
            {"i": 190, "price": 111.5, "label": "R"},
            {"i": 208, "price": 104.0, "label": "H"},
        ],
    },
}

IDEA = {
    "symbol": "HDFCBANK", "name": "HDFC Bank Limited", "conviction": 68.4,
    "conviction_band": "High", "setup": "Momentum Breakout", "horizon": "3–6 months",
    "evidence": [
        {"factor": "Setup fit", "points": 24.1, "of": 30, "detail": "…"},
        {"factor": "Engine composite", "points": 12.0, "of": 18, "detail": "…"},
        {"factor": "Sector outlook", "points": 11.2, "of": 16, "detail": "…"},
        {"factor": "Market regime", "points": 2.0, "of": 4, "detail": "…"},
        {"factor": "Catalyst", "points": 8.0, "of": 12, "detail": "…"},
        {"factor": "Liquidity", "points": 8.0, "of": 8, "detail": "…"},
        {"factor": "Archetype record", "points": 3.1, "of": 12, "detail": "…"},
        {"factor": "Scan freshness", "points": -0.5, "of": 0, "detail": "…"},
    ],
}

HOLDING = {"symbol": "ITC", "name": "ITC Limited", "added_on": "2026-01-04",
           "return_pct": 8.42, "alpha_pct": 3.11, "bench_return_pct": 5.31,
           "days_held": 61, "status": "open"}


def test_chart_card_renders():
    assert _png_size(og.chart_card(CHART)) == (1200, 630)


def test_chart_card_without_a_pattern_still_renders():
    payload = dict(CHART)
    payload["shape"] = None
    png = og.chart_card(payload)
    assert _png_size(png) == (1200, 630)


def test_chart_card_survives_an_empty_series():
    """A card must never fail. An empty window says so on the image."""
    assert _png_size(og.chart_card({"symbol": "X", "candles": []})) == (1200, 630)


def test_chart_card_survives_a_flat_series():
    """Every high equal to every low: the price span is zero and every
    coordinate divides by it. This used to be the shape that crashed."""
    flat = [[1_700_000_000 + i * 86400, 50.0, 50.0, 50.0, 50.0, 0] for i in range(120)]
    assert _png_size(og.chart_card({"symbol": "FLAT", "candles": flat,
                                    "last": 50.0, "change_pct": 0.0})) == (1200, 630)


def test_the_window_always_contains_the_whole_shape():
    """
    A cup whose left rim is cropped off is a worse picture than no picture,
    and the crop is silent — the card renders, it is simply wrong.
    """
    candles = _candles(600)
    points = [{"i": 30, "price": 100.0}, {"i": 400, "price": 90.0}]
    start, end = og._series_window(candles, points)
    assert start <= 30 - 8 or start == 0
    assert end == len(candles)
    # With no points it is just the tail.
    assert og._series_window(candles, [])[0] == len(candles) - 150


def test_a_triangle_is_drawn_as_trendlines_not_a_zigzag():
    """Joining a triangle's alternating pivots in time order draws a zigzag
    that looks nothing like a triangle."""
    assert og._pattern_polyline("Cup and Handle") is True
    assert og._pattern_polyline("Double Bottom") is True
    assert og._pattern_polyline("Ascending Triangle") is False
    assert og._pattern_polyline("Rectangle") is False
    assert og._pattern_polyline("Bull Flag") is False


def test_the_chart_card_never_carries_the_trigger_or_the_target():
    """
    The compliance guard for the chart.

    Historical candles are public fact and may be drawn — that is what a chart
    is. The pattern's geometry describes what already happened. The TRIGGER and
    the MEASURED MOVE are forecasts about what a reader should do next, so
    neither the lines nor their numbers may reach a published image; they stay
    on the site beside the base rate that qualifies them.
    """
    drawn = []
    from PIL import ImageDraw

    original = ImageDraw.ImageDraw.text

    def spy(self, xy, text, *a, **k):
        drawn.append(str(text))
        return original(self, xy, text, *a, **k)

    payload = dict(CHART)
    payload["shape"] = dict(CHART["shape"], trigger=1995.98, invalidation=1836.31,
                            target=2315.34)

    ImageDraw.ImageDraw.text = spy
    try:
        og.chart_card(payload)
    finally:
        ImageDraw.ImageDraw.text = original

    blob = "".join(drawn)
    for forbidden in ("1995", "1836", "2315", "1,995", "1,836", "2,315"):
        assert forbidden not in blob, f"a forecast level reached the chart card: {forbidden}"
    for word in ("BUY", "SELL", "TARGET", "STOP LOSS", "CONFIRMS ABOVE"):
        assert word not in blob.upper(), f"a directive reached the chart card: {word}"
    assert "NOT INVESTMENT ADVICE" in blob.upper()


def test_idea_card_renders_with_its_ledger():
    assert _png_size(og.idea_card(IDEA)) == (1200, 630)
    assert _png_size(og.idea_card({"symbol": "X"})) == (1200, 630)


def test_holding_card_renders_a_loss_as_readily_as_a_gain():
    assert _png_size(og.holding_card(HOLDING)) == (1200, 630)
    loser = dict(HOLDING, return_pct=-12.5, alpha_pct=-8.2, bench_return_pct=-4.3)
    assert _png_size(og.holding_card(loser)) == (1200, 630)
    assert _png_size(og.holding_card({})) == (1200, 630)


def test_the_idea_card_never_carries_a_price_level():
    drawn = []
    from PIL import ImageDraw

    original = ImageDraw.ImageDraw.text

    def spy(self, xy, text, *a, **k):
        drawn.append(str(text))
        return original(self, xy, text, *a, **k)

    ImageDraw.ImageDraw.text = spy
    try:
        og.idea_card(dict(IDEA, plan={"entry": 1995.98, "stop": 1836.31, "t1": 2315.34}))
        og.holding_card(dict(HOLDING, added_price=1995.98, last_price=2315.34))
    finally:
        ImageDraw.ImageDraw.text = original

    blob = "".join(drawn)
    for forbidden in ("1995", "1836", "2315"):
        assert forbidden not in blob, f"a price level reached the card: {forbidden}"


# ---------------------------------------------------------------------------
# The mark
#
# A missing logo file does not raise and does not change the card's size, so
# nothing above would notice it. What would notice is a timeline: the card is
# the only thing most people ever see of this product, and an unbranded one is
# indistinguishable from a screenshot somebody else made.
# ---------------------------------------------------------------------------

RESULTS = {
    "symbol": "TARIL", "name": "Transformers And Rectifiers (India) Limited",
    "quarter": "Q2 FY27", "as_of": "2026-09-30", "filed_at": "13-Oct-2026 16:34:09",
    "basis": "consolidated", "pat_cr": 81.38, "pat_yoy_pct": 117.9,
    "pat_yoy_base_cr": 37.35, "revenue_cr": 739.44, "revenue_yoy_pct": 60.7,
    "net_margin_pct": 11.0, "net_margin_yoy_pct": 8.1,
    "revenue_series": [{"period": "Q2 FY27", "value_cr": 739.44},
                       {"period": "Q1 FY27", "value_cr": 572.34},
                       {"period": "Q2 FY26", "value_cr": 460.03}],
    "pat_series": [{"period": "Q2 FY27", "value_cr": 81.38},
                   {"period": "Q1 FY27", "value_cr": 64.29},
                   {"period": "Q2 FY26", "value_cr": 37.35}],
}


def _drawn(build):
    """Every string a card draws, in order."""
    from PIL import ImageDraw
    seen = []
    original = ImageDraw.ImageDraw.text

    def spy(self, xy, text, *a, **k):
        seen.append(str(text))
        return original(self, xy, text, *a, **k)

    ImageDraw.ImageDraw.text = spy
    try:
        png = build()
    finally:
        ImageDraw.ImageDraw.text = original
    return png, "".join(seen)


def test_results_card_carries_the_quarter_as_filed():
    png, text = _drawn(lambda: og.results_card(RESULTS))
    assert _png_size(png) == (1200, 630)
    for want in ("Q2 FY27 RESULTS", "FILED WITH NSE 13 OCT 2026, 16:34 IST",
                 "Transformers And Rectifiers", "CONSOLIDATED", "81.38",
                 "+117.9% YoY", "37.35", "739.44", "460.03", "NET MARGIN 11.0%"):
        assert want.replace(" ", "") in text.replace(" ", ""), want
    # The year-ago bar is the same quarter a year back, not the last one.
    assert "Q2 FY26" in text and "572.34" not in text


def test_a_loss_is_named_and_never_given_a_percentage():
    loss = dict(RESULTS, pat_cr=-12.5, pat_yoy_pct=None, pat_yoy_base_cr=5.2)
    png, text = _drawn(lambda: og.results_card(loss))
    assert _png_size(png) == (1200, 630)
    assert "NETLOSS" in text.replace(" ", "")
    assert "a profit of ₹5.20 Cr" in text
    assert "YoY" not in text.split("NET MARGIN")[0].replace("REVENUE", "")


def test_a_yahoo_card_does_not_claim_an_exchange_filing():
    yahoo = {k: v for k, v in RESULTS.items() if k not in ("filed_at", "basis")}
    _png, text = _drawn(lambda: og.results_card(yahoo))
    assert "NSE" not in text and "REG 33" not in text.replace("  ", " ")
    assert "STATEMENTS DATED 30 SEP 2026" in text.replace("  ", " ")


def test_a_sparse_results_payload_still_renders():
    assert _png_size(og.results_card({"symbol": "X"})) == (1200, 630)


# ---------------------------------------------------------------------------
# The concall card: the only one that is mostly prose
# ---------------------------------------------------------------------------

CONCALL = {
    "symbol": "SOLARWORLD", "company": "Solarworld Energy Solutions Limited",
    "quarter": "Q2 FY27", "call_date": "2026-11-14",
    "filed_at": "2026-11-20T16:10:00+05:30", "key": True,
    "brief": {
        "status": "ready",
        "headline": ("Management cut FY27 guidance to ₹1,600–1,700 crore revenue "
                     "and 5–6% profit margin"),
        "summary": ("Q2 revenue rose about 77% to ₹244 crore, but profit fell to "
                    "₹4.2 crore from ₹9.3 crore as metal costs squeezed margins. "
                    "Management guided FY27 revenue of ₹1,600–1,700 crore. "
                    "The order book stands at ₹2,900 crore. "
                    "A fourth sentence that there is no room for on any card."),
    },
}


def _lines(build):
    """What a prose card drew, a line at a time: [(y, size, text)]."""
    from PIL import ImageDraw
    rows = {}
    original = ImageDraw.ImageDraw.text

    def spy(self, xy, text, *a, **k):
        if k.get("anchor") == "ls":
            rows.setdefault(round(xy[1]), []).append(str(text))
        return original(self, xy, text, *a, **k)

    ImageDraw.ImageDraw.text = spy
    try:
        build()
    finally:
        ImageDraw.ImageDraw.text = original
    return ["".join(parts) for _y, parts in sorted(rows.items())]


def test_concall_card_says_whose_call_it_is_and_what_was_said():
    png, text = _drawn(lambda: og.concall_card(CONCALL))
    assert _png_size(png) == (1200, 630)
    flat = text.replace(" ", "")
    for want in ("Q2 FY27 EARNINGS CALL", "CALL HELD 14 NOV 2026", "KEY CALL",
                 "SOLARWORLD ENERGY SOLUTIONS LIMITED",
                 "Management cut FY27 guidance to ₹1,600–1,700 crore",
                 "Q2 revenue rose about 77% to ₹244 crore"):
        assert want.replace(" ", "") in flat, want


def test_concall_card_says_a_model_wrote_it():
    """The page says so on every brief. A picture that travels without the
    page has to carry that with it, beside the line that it is not advice."""
    _png, text = _drawn(lambda: og.concall_card(CONCALL))
    flat = text.replace(" ", "")
    assert "AI-WRITTENFROMTHETRANSCRIPTFILEDWITHBSE" in flat
    assert "NOTINVESTMENTADVICE" in flat


def test_a_call_that_is_not_key_is_not_flagged_as_one():
    _png, text = _drawn(lambda: og.concall_card(dict(CONCALL, key=False)))
    assert "KEYCALL" not in text.replace(" ", "")


def test_a_call_with_no_date_read_from_it_says_when_it_was_filed():
    _png, text = _drawn(lambda: og.concall_card(dict(CONCALL, call_date=None)))
    assert "TRANSCRIPT FILED 20 NOV 2026".replace(" ", "") in text.replace(" ", "")
    assert "CALLHELD" not in text.replace(" ", "")


def test_the_rupee_sign_is_drawn_by_a_face_that_has_one():
    """Instrument Serif has no ₹. Asking it for one draws a hollow box, and a
    brief has a rupee figure in nearly every sentence."""
    assert og._covers("A") and og._covers("7") and og._covers("–")
    assert not og._covers("₹")
    from PIL import ImageDraw
    faces = []
    original = ImageDraw.ImageDraw.text

    def spy(self, xy, text, *a, **k):
        if "₹" in str(text):
            faces.append((str(text), k.get("font").path))
        return original(self, xy, text, *a, **k)

    ImageDraw.ImageDraw.text = spy
    try:
        og.concall_card(CONCALL)
    finally:
        ImageDraw.ImageDraw.text = original
    assert faces, "the card drew no rupee sign at all"
    for text, path in faces:
        assert text == "₹", "the sign must be a run of its own: %r" % text
        assert "IBMPlexMono" in path, path


def test_the_summary_stops_at_the_end_of_a_sentence():
    """A summary cut mid-sentence reads as a mistake. What fits is whole
    sentences; the rest is on the site."""
    brief = dict(CONCALL["brief"], summary=CONCALL["brief"]["summary"] + " "
                 + "Another sentence about demand in the second half of the year. " * 8
                 + "The last sentence, which no card has room for.")
    lines = _lines(lambda: og.concall_card(dict(CONCALL, brief=brief)))
    drawn = " ".join(lines)
    assert drawn.rstrip().endswith("."), drawn
    assert "…" not in drawn
    assert "The last sentence" not in drawn
    # What is there is the start of the summary, in order, and it fills the
    # room it has rather than stopping after one sentence.
    assert "squeezed margins. Management guided" in drawn
    assert "The order book stands at ₹2,900 crore." in drawn


def test_a_decimal_point_does_not_end_a_sentence():
    parts = og._sentences("Profit fell to ₹4.2 crore from ₹9.3 crore. Margin was 5.5%. "
                          "₹3,000 crore is the FY28 aim.")
    assert parts == ["Profit fell to ₹4.2 crore from ₹9.3 crore.", "Margin was 5.5%.",
                     "₹3,000 crore is the FY28 aim."]


def test_a_long_headline_steps_down_before_it_is_cut():
    from PIL import Image, ImageDraw
    d = ImageDraw.Draw(Image.new("RGB", (og.W, og.H)))
    long = ("Management said that the company will be raising ₹2,500 crore through a "
            "qualified institutional placement to fund three new plants in Gujarat, "
            "Odisha and Tamil Nadu over two years")
    sizes = []
    original = ImageDraw.ImageDraw.text

    def spy(self, xy, text, *a, **k):
        if k.get("anchor") == "ls" and k.get("fill") == og.INK:
            sizes.append((round(xy[1]), k["font"].size))
        return original(self, xy, text, *a, **k)

    ImageDraw.ImageDraw.text = spy
    try:
        og.concall_card(dict(CONCALL, brief=dict(CONCALL["brief"], headline=long)))
    finally:
        ImageDraw.ImageDraw.text = original
    baselines = sorted({y for y, _s in sizes})
    assert len(baselines) <= og.HEADLINE_LINES
    size = max(s for _y, s in sizes)
    assert size < og.HEADLINE_SIZES[0], "a long headline should be set smaller"
    # Smaller, and whole: nothing was cut to make it fit.
    assert len(og._wrap(d, long, size, og.W - 128)) <= og.HEADLINE_LINES


def test_nothing_on_a_concall_card_runs_off_the_card():
    """Every line of prose ends inside the right-hand margin, whatever the
    brief says: a long name, a long headline, a summary of one long sentence."""
    from PIL import Image, ImageDraw
    d = ImageDraw.Draw(Image.new("RGB", (og.W, og.H)))
    worst = dict(CONCALL, company="The Extraordinarily Long Named Infrastructure "
                 "Development And Finance Corporation Of India Limited", quarter="",
                 brief={"headline": "Word " * 60, "summary": "clause after clause " * 60})
    seen = []
    original = ImageDraw.ImageDraw.text

    def spy(self, xy, text, *a, **k):
        seen.append((xy[0] + d.textlength(str(text), font=k.get("font")), xy[1]))
        return original(self, xy, text, *a, **k)

    ImageDraw.ImageDraw.text = spy
    try:
        png = og.concall_card(worst)
    finally:
        ImageDraw.ImageDraw.text = original
    assert _png_size(png) == (1200, 630)
    assert max(x for x, _y in seen) <= og.W - 60
    # Prose stays above the footer rule.
    assert all(y < og.H - 92 or y >= og.H - 72 for _x, y in seen)


@pytest.mark.parametrize("call", [
    {}, {"symbol": "X"}, {"symbol": "X", "brief": {}},
    {"symbol": "X", "company": "X Ltd", "brief": {"headline": "", "summary": "One. Two."}},
    {"symbol": "X", "brief": {"headline": None, "summary": None}, "call_date": "not a date"},
])
def test_a_sparse_concall_still_renders(call):
    assert _png_size(og.concall_card(call)) == (1200, 630)


# ---------------------------------------------------------------------------
# The WOW order card: an order against its company
# ---------------------------------------------------------------------------

ORDER = {
    "symbol": "PACEDIGITK", "company": "Pace Digitek Limited", "key": "6eed6d67e567",
    "at": "2026-11-16T14:55:00+05:30", "stage": "order", "kind": "Letter of award",
    "customer": "NTPC Green Energy Limited",
    "nature": ("BESS system supply, system integration, installation, testing, commissioning, "
               "civil works and 15-year operations & maintenance for Block-01 and Block-02 "
               "under Cluster-01 of the flagship 3300 MWh BESS Project"),
    "value_cr": 2691.3, "value_confident": True, "currency_converted": False,
    "market_cap_cr": 3569.3, "pct_of_market_cap": 75.4,
    "sales_year": "FY26", "months_of_sales": 12.2, "wow": True, "outsized": False,
}


def test_wow_card_says_who_won_what_and_how_big_it_is():
    png, text = _drawn(lambda: og.wow_card(ORDER))
    assert _png_size(png) == (1200, 630)
    flat = text.replace(" ", "")
    for want in ("WOW ORDER", "FILED 16 NOV 2026", "PACE DIGITEK LIMITED", "75%",
                 "OF MARKET CAP", "₹2,691 cr letter of award from NTPC Green Energy Limited",
                 "BESS system supply", "ORDER", "MARKET CAP", "₹3,569 cr",
                 "AGAINST FY26 SALES", "12.2 months", "AS THE COMPANY FILED IT",
                 "NOT INVESTMENT ADVICE"):
        assert want.replace(" ", "") in flat, want


def test_an_order_under_the_line_is_not_called_wow_on_its_card():
    small = dict(ORDER, pct_of_market_cap=3.3, wow=False)
    _png, text = _drawn(lambda: og.wow_card(small))
    flat = text.replace(" ", "")
    assert "ORDERWIN" in flat and "WOWORDER" not in flat and "3.3%" in flat


def test_an_order_larger_than_the_company_says_to_open_the_filing():
    """The page says so beside the row. A picture travels without the page."""
    huge = dict(ORDER, pct_of_market_cap=127.7, outsized=True, months_of_sales=None,
                sales_year=None)
    _png, text = _drawn(lambda: og.wow_card(huge))
    flat = text.replace(" ", "")
    assert "128%" in flat and "LARGERTHANTHECOMPANY:OPENTHEFILING" in flat
    assert "SALES" not in flat, "no sales on file means no sales comparison"


def test_a_converted_order_says_what_rate_was_assumed():
    conv = dict(ORDER, currency_converted=True, fx_rate=93.5)
    _png, text = _drawn(lambda: og.wow_card(conv))
    assert "USDOLLARSAT₹93.5,ANASSUMEDRATE" in text.replace(" ", "")


def test_the_wow_card_never_carries_a_level_or_a_directive():
    """An order is an event with a size. Nothing on its card is about the share."""
    _png, text = _drawn(lambda: og.wow_card(dict(ORDER, price=1234.5, target=1500, stop=1100,
                                               entry=1200)))
    for bad in ("1234", "1500", "1100", "1200"):
        assert bad not in text.replace(",", "")
    for word in ("BUY", "SELL", "TARGET", "STOP", "ENTRY"):
        assert word not in text.upper()


def test_nothing_on_a_wow_card_runs_off_the_card():
    from PIL import Image, ImageDraw
    d = ImageDraw.Draw(Image.new("RGB", (og.W, og.H)))
    worst = dict(ORDER, company="The Extraordinarily Long Named Infrastructure Development And "
                 "Finance Corporation Of India Limited", customer="Customer " * 30,
                 nature="scope " * 80, value_cr=278400.0, market_cap_cr=1234567.0,
                 pct_of_market_cap=1234.5, months_of_sales=480)
    seen = []
    original = ImageDraw.ImageDraw.text

    def spy(self, xy, text, *a, **k):
        seen.append((xy[0] + d.textlength(str(text), font=k.get("font")), xy[1]))
        return original(self, xy, text, *a, **k)

    ImageDraw.ImageDraw.text = spy
    try:
        png = og.wow_card(worst)
    finally:
        ImageDraw.ImageDraw.text = original
    assert _png_size(png) == (1200, 630)
    assert max(x for x, _y in seen) <= og.W - 60
    assert all(y < og.H - 92 or y >= og.H - 72 for _x, y in seen)


@pytest.mark.parametrize("row", [
    {}, {"symbol": "X"}, {"symbol": "X", "value_cr": 5},
    {"symbol": "X", "value_cr": 5, "pct_of_market_cap": 0.01, "at": "not a date"},
    {"symbol": "X", "company": "X Ltd", "value_cr": None, "pct_of_market_cap": None},
])
def test_a_sparse_order_still_renders(row):
    assert _png_size(og.wow_card(row)) == (1200, 630)


@pytest.mark.parametrize("v,want", [
    (278400, "₹2.78 lakh cr"), (2691.3, "₹2,691 cr"), (136.29, "₹136 cr"),
    (18.51, "₹18.51 cr"), (6.0, "₹6 cr"), (0.45, "₹45 lakh"), (None, "—"), ("x", "—"),
])
def test_rupees_read_the_way_the_page_writes_them(v, want):
    assert og._rupee_cr(v) == want


@pytest.mark.parametrize("m,want", [
    (0.1, "under a week"), (0.6, "about 3 weeks"), (1.0, "1 month"), (6.7, "6.7 months"),
    (12.2, "12.2 months"), (30, "2.5 years"),
])
def test_sales_are_a_length_a_reader_can_picture(m, want):
    assert og._sales_span(m) == want


def test_the_order_sentence_is_built_only_from_what_the_filing_states():
    assert og.order_sentence(ORDER) == ("₹2,691 cr letter of award from "
                                        "NTPC Green Energy Limited")
    assert og.order_sentence({"value_cr": 136.29}) == "₹136 cr order"


def test_every_card_carries_the_mark():
    """The gold arrow only exists in the logo, so its pixels prove it landed."""
    from PIL import Image
    import io as _io

    cards = {
        "stock": og.stock_card(ANALYZE),
        "record": og.record_card(STATS),
        "idea": og.idea_card(IDEA),
        "holding": og.holding_card(HOLDING),
        "chart": og.chart_card(CHART),
        "results": og.results_card(RESULTS),
        "concall": og.concall_card(CONCALL),
        "wow": og.wow_card(ORDER),
    }
    for name, png in cards.items():
        im = Image.open(_io.BytesIO(png)).convert("RGB")
        # The lockup's left slot, tight enough that only the mark is inside it.
        box = im.crop((64, 52, 64 + 82, 52 + og.LOGO_H))
        colours = box.getcolors(maxcolors=100_000) or []
        ink = sum(n for n, (r, g, b) in colours if max(r, g, b) < 90)
        gold = sum(n for n, (r, g, b) in colours if r > 140 and b < 120 and r - b > 70)
        assert ink > 500, f"{name} card: no letterform where the mark should be"
        assert gold > 120, f"{name} card: no gold arrow where the mark should be"


def test_the_wordmark_does_not_sit_on_top_of_the_mark():
    """
    The mark shifts the wordmark right. If the shift is ever dropped the two
    overlap into mush, which renders perfectly and reads as a printing error.
    """
    from PIL import Image, ImageDraw

    if og.logo(og.LOGO_H) is None:
        pytest.skip("no mark to shift past — test_every_card_carries_the_mark covers that")

    img = Image.new("RGB", (og.W, og.H), og.PAPER)
    d = ImageDraw.Draw(img)
    seen = []
    original = ImageDraw.ImageDraw.text

    def spy(self, xy, text, *a, **k):
        seen.append((xy[0], str(text)))
        return original(self, xy, text, *a, **k)

    ImageDraw.ImageDraw.text = spy
    try:
        og._shell(d, img)
    finally:
        ImageDraw.ImageDraw.text = original

    x = min(px for px, text in seen if text == "Altaha")
    assert x >= 64 + og.LOGO_H, "the wordmark still starts where the mark is drawn"


def test_a_missing_logo_file_costs_the_mark_and_nothing_else():
    """Same contract as the fonts: an unbranded card beats a broken link."""
    original, og.LOGO_PATH = og.LOGO_PATH, "/nonexistent/altaha-logo.png"
    cache, og._logo_cache = og._logo_cache, {}
    try:
        assert og.logo(og.LOGO_H) is None
        assert _png_size(og.stock_card(ANALYZE)) == (1200, 630)
    finally:
        og.LOGO_PATH = original
        og._logo_cache = cache


def test_the_redirect_keeps_every_parameter():
    """
    An HTML entity is not decoded inside <script>. The redirect used the
    escaped URL, so `&amp;` reached location.replace and everything after the
    first parameter was lost: a shared results link opened an empty Results
    tab, and a chart link lost its tab and its range.
    """
    import json as _json
    target = "https://site.example/?go=results&q=TARIL"
    html = og.share_page("T", "D", "https://site.example/og.png", target)
    script = re.search(r"<script>location\.replace\((.*?)\);</script>", html).group(1)
    assert _json.loads(script) == target
    assert 'url=https://site.example/?go=results&amp;q=TARIL"' in html


def test_the_redirect_cannot_close_its_script():
    html = og.share_page("T", "D", "i.png", "https://x/?q=</script><script>alert(1)//&a='\"")
    script = re.search(r"<script>location\.replace\((.*?)\);</script>", html, re.S).group(1)
    assert "</script>" not in script and "<" not in script
    assert html.count("<script>") == 1


def test_the_share_page_points_a_crawler_at_the_icon():
    html = og.share_page("Title", "Desc",
                         "https://altahascreener.in/og/stock.png?ticker=X",
                         "https://altahascreener.in/?q=X")
    assert '<link rel="icon" href="https://altahascreener.in/favicon.ico"' in html
    assert 'apple-touch-icon" href="https://altahascreener.in/apple-touch-icon.png"' in html
    assert 'og:logo" content="https://altahascreener.in/icon-512.png"' in html
    # A target that is not an absolute URL must not produce a half-built link.
    assert "rel=\"icon\"" not in og.share_page("T", "D", "i.png", "/?q=X")


def test_no_factor_label_is_painted_over_by_its_bar():
    """The rebuilt lists' factor names (leaders.FACTOR_LABELS) are longer than
    the old ones. Each is drawn whole, or cut short with an ellipsis, and ends
    before its bar starts."""
    import leaders
    from PIL import ImageDraw

    texts, bars = [], []
    t0, r0 = ImageDraw.ImageDraw.text, ImageDraw.ImageDraw.rectangle

    def text(self, xy, s, *a, **k):
        if xy[0] == 64 and k.get("font") is not None:
            texts.append((xy[1], str(s), self.textlength(str(s), font=k["font"])))
        return t0(self, xy, s, *a, **k)

    def rect(self, box, *a, **k):
        bars.append(box)
        return r0(self, box, *a, **k)

    def draw(evidence):
        texts.clear(); bars.clear()
        ImageDraw.ImageDraw.text, ImageDraw.ImageDraw.rectangle = text, rect
        try:
            og.idea_card({"symbol": "LONGNAMES", "conviction": 71, "evidence": evidence})
        finally:
            ImageDraw.ImageDraw.text, ImageDraw.ImageDraw.rectangle = t0, r0
        starts = {round(b[0]) for b in bars if isinstance(b, (list, tuple)) and len(b) == 4 and b[1] >= 318 - 4}
        assert len(starts) == 1, starts
        bar = starts.pop()
        drawn = [t for t in texts if t[0] >= 314]
        for _, s, width in drawn:
            assert 64 + width < bar, f"{s!r} runs under its bar"
        return [s for _, s, _ in drawn]

    # Every label the lists use is drawn whole, six at a time.
    labels = list(leaders.FACTOR_LABELS.values())
    for i in range(0, len(labels), 6):
        part = labels[i:i + 6]
        assert draw([{"factor": t, "points": 10 - j, "of": 20} for j, t in enumerate(part)]) == part
    # One too long for any card is cut short, not painted over.
    shown = draw([{"factor": "x" * 80, "points": 9, "of": 20}, {"factor": labels[0], "points": 1, "of": 20}])
    assert shown[0].endswith("\u2026") and shown[1] == labels[0]
