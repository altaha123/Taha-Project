"""
Altaha Screener — share cards

Renders the 1200x630 image that X, WhatsApp and LinkedIn show when someone
shares a link. Server-side, as PNG, because no social crawler runs JavaScript
and none of them render SVG.

WHAT THE CARD IS ALLOWED TO SAY
This is the part that matters more than the pixels. A card is published to the
public and read by people who never visit the site, so it carries exactly the
things this project is allowed to say to strangers: computed scores, the
archetype the setup matched, and the fact that every number opens into its own
arithmetic.

It carries no entry price, no stop, no target and no "buy". Those live behind
the site, next to their ledger and their disclaimer, and putting them on a
shareable image is the difference between publishing analysis and publishing
advice — which in India is the difference between an educational tool and one
that needs SEBI Research Analyst registration.

FONTS
Instrument Serif and IBM Plex Mono are bundled under the SIL Open Font
License, which permits redistribution. They are the site's own faces, so a
shared card looks like the product rather than like a generic template. If a
face fails to load the renderer falls back rather than failing the request —
an ugly card beats a broken link preview.
"""

import datetime as dt
import io
import os
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
FONT_DIR = os.path.join(HERE, "assets", "fonts")

W, H = 1200, 630

# The site's own tokens, light theme. A card is a poster, not a UI, so it does
# not follow the reader's dark-mode preference — it has to look the same in
# everyone's timeline.
PAPER = (251, 248, 241)
PAPER_2 = (243, 239, 228)
INK = (23, 20, 14)
INK_2 = (75, 68, 56)
MUTE = (138, 129, 113)
RULE = (226, 218, 202)
GOLD = (168, 128, 28)
GOLD_LT = (201, 166, 62)
PASS = (31, 122, 85)
FAIL = (176, 58, 43)

_cache = {}
_lock = threading.Lock()
CACHE_MAX = 200


def _font(name, size):
    from PIL import ImageFont
    path = os.path.join(FONT_DIR, name)
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        for fallback in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                         "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"):
            try:
                return ImageFont.truetype(fallback, size)
            except Exception:
                continue
        return ImageFont.load_default()


def serif(size):
    return _font("InstrumentSerif-Regular.ttf", size)


def mono(size, medium=False):
    return _font("IBMPlexMono-Medium.ttf" if medium else "IBMPlexMono-Regular.ttf", size)


def _tracking(draw, xy, text, font, fill, px=0):
    """
    Draw text with letter-spacing. Pillow has no tracking, and the site's
    labels are 0.14em-spaced uppercase mono — without this they read as a
    different product.
    """
    x, y = xy
    for ch in text:
        draw.text((x, y), ch, font=font, fill=fill)
        x += draw.textlength(ch, font=font) + px
    return x


def _tracked_width(draw, text, font, px=0):
    return sum(draw.textlength(c, font=font) for c in text) + px * max(0, len(text) - 1)


def _num(v):
    """A score, whatever container it arrived in."""
    if isinstance(v, dict):
        v = v.get("score")
    try:
        f = float(v)
        return None if f != f else f
    except (TypeError, ValueError):
        return None


def _read(payload):
    """
    Pull the card's fields out of an /analyze response.

    The endpoint nests them — scoring.score, technical.score, setup.name — and
    a flat payload turns up in tests and from the ideas list, so both shapes
    are accepted. Reading the wrong key here does not raise, it silently
    renders a card full of dashes, which is exactly the kind of quiet failure
    this project keeps producing. Hence one reader, used everywhere.
    """
    sym = str(payload.get("ticker") or payload.get("symbol") or "").upper()
    sym = sym.replace(".NS", "").replace(".BO", "")
    name = str(payload.get("name") or sym or "—")

    scoring = payload.get("scoring") or payload.get("verdict") or {}
    comp = _num(scoring) if scoring else _num(payload.get("composite"))
    if comp is None:
        comp = _num(payload.get("composite"))
    label = (scoring.get("label") if isinstance(scoring, dict) else None) or ""

    tech = _num(payload.get("technical"))
    fund = _num(payload.get("fundamental"))

    fsrc = payload.get("fundamental")
    fsc = (fsrc.get("f_score") if isinstance(fsrc, dict) else None)
    if fsc is None:
        fsc = payload.get("f_score")

    setup = payload.get("setup")
    setup = setup.get("name") if isinstance(setup, dict) else setup

    return sym, name, comp, label, tech, fund, fsc, setup


def _band(score):
    if score is None:
        return MUTE
    if score >= 70:
        return PASS
    if score >= 50:
        return GOLD
    return FAIL


def _shell(draw):
    """Background, gold rule, wordmark, footer. Shared by every card."""
    draw.rectangle([0, 0, W, H], fill=PAPER)
    draw.rectangle([0, 0, W, 8], fill=GOLD)

    draw.text((64, 52), "Altaha", font=serif(46), fill=INK)
    w = draw.textlength("Altaha ", font=serif(46))
    draw.text((64 + w, 52), "Screener", font=serif(46), fill=GOLD)

    _tracking(draw, (66, 112), "EVERY SCORE SHOWS ITS WORKING", mono(15), MUTE, 3.2)
    draw.line([(64, H - 92), (W - 64, H - 92)], fill=RULE, width=1)


def _footer(draw, note):
    _tracking(draw, (66, H - 70), note.upper(), mono(14), MUTE, 2.4)
    tail = "EDUCATIONAL ANALYSIS · NOT INVESTMENT ADVICE"
    tw = _tracked_width(draw, tail, mono(14), 2.4)
    _tracking(draw, (W - 64 - tw, H - 70), tail, mono(14), MUTE, 2.4)


def _metric(draw, x, y, label, value, colour=INK, width=250):
    _tracking(draw, (x, y), label.upper(), mono(15), MUTE, 2.6)
    draw.text((x - 2, y + 26), value, font=serif(62), fill=colour)


def stock_card(payload: dict) -> bytes:
    """
    One stock. Scores and the archetype — never a level or a directive.

    `payload` is an /analyze response.
    """
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(img)
    _shell(d)

    sym, name, comp, label, tech, fund, fsc, setup = _read(payload)

    # Name, trimmed to fit rather than overflowing the card.
    f = serif(60)
    if d.textlength(name, font=f) > 720:
        while name and d.textlength(name + "…", font=f) > 720:
            name = name[:-1]
        name = name.rstrip() + "…"
    d.text((64, 186), name, font=f, fill=INK)
    _tracking(d, (66, 262), f"{sym}  ·  NSE", mono(17), MUTE, 2.6)

    # The headline score, right-aligned as a big serif figure.
    score = "—" if comp is None else str(int(round(comp)))
    fs = serif(190)
    sw = d.textlength(score, font=fs)
    d.text((W - 84 - sw, 150), score, font=fs, fill=_band(comp))
    lbl = f"COMPOSITE / 100{('  ·  ' + label.upper()) if label else ''}"
    lw = _tracked_width(d, lbl, mono(15), 2.6)
    _tracking(d, (W - 84 - lw, 356), lbl, mono(15), MUTE, 2.6)

    # Supporting numbers.
    y = 420
    _metric(d, 64, y, "Technical", "—" if tech is None else str(int(round(tech))), _band(tech))
    _metric(d, 300, y, "Fundamental", "—" if fund is None else str(int(round(fund))), _band(fund))
    _metric(d, 560, y, "Piotroski", "—" if fsc is None else f"{int(fsc)}/9", INK_2)

    if setup:
        _tracking(d, (820, y), "SETUP", mono(15), MUTE, 2.6)
        s = str(setup)
        fsx = serif(34)
        if d.textlength(s, font=fsx) > 320:
            while s and d.textlength(s + "…", font=fsx) > 320:
                s = s[:-1]
            s = s.rstrip() + "…"
        d.text((818, y + 30), s, font=fsx, fill=INK_2)

    _footer(d, dt.date.today().strftime("%d %b %Y"))

    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def record_card(stats: dict) -> bytes:
    """
    The track record. This is the card worth sharing weekly — it is the one
    claim in this product that nobody else in the market makes, and it is a
    statement of fact about a measured ledger rather than a prediction.
    """
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(img)
    _shell(d)

    o = stats.get("overall") or {}
    d.text((64, 178), "Does it work?", font=serif(66), fill=INK)
    _tracking(d, (66, 258),
              "EVERY IDEA RECORDED AUTOMATICALLY — WINNERS AND LOSERS",
              mono(16), MUTE, 2.6)

    def pct(v):
        return "—" if v is None else f"{v:+.2f}%".replace("+-", "-")

    alpha = o.get("avg_alpha_pct")
    beat = o.get("beat_index_pct")
    y = 348
    _metric(d, 64, y, "Ideas tracked", str(stats.get("total_tracked") or 0), INK)
    _metric(d, 340, y, "Beat the index",
            "—" if beat is None else f"{beat}%", PASS if (beat or 0) >= 50 else FAIL)
    _metric(d, 640, y, "Avg alpha vs index", pct(alpha),
            PASS if (alpha or 0) > 0 else FAIL)
    _metric(d, 960, y, "Median hold",
            f"{o.get('median_days_held') or 0}d", INK_2)

    _tracking(d, (66, 500),
              "ALPHA IS RETURN MINUS THE INDEX OVER THE IDENTICAL WINDOW",
              mono(15), MUTE, 2.4)

    _footer(d, dt.date.today().strftime("%d %b %Y"))
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def cached(key, build):
    """
    Rendering costs ~100ms and a card changes at most once a day, so the same
    symbol shared into a busy thread must not re-render for every crawler that
    comes calling.
    """
    stamp = f"{key}|{dt.date.today().isoformat()}"
    with _lock:
        hit = _cache.get(stamp)
    if hit is not None:
        return hit
    out = build()
    with _lock:
        if len(_cache) > CACHE_MAX:
            _cache.clear()
        _cache[stamp] = out
    return out


def share_page(title, description, image, target):
    """The document a crawler reads and a human never sees for long."""
    def esc(t):
        return (str(t).replace("&", "&amp;").replace("<", "&lt;")
                .replace(">", "&gt;").replace('"', "&quot;"))
    t, d, i, u = esc(title), esc(description), esc(image), esc(target)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{t}</title>
<meta name="description" content="{d}">
<meta property="og:type" content="article">
<meta property="og:site_name" content="Altaha Screener">
<meta property="og:title" content="{t}">
<meta property="og:description" content="{d}">
<meta property="og:image" content="{i}">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta property="og:url" content="{u}">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{t}">
<meta name="twitter:description" content="{d}">
<meta name="twitter:image" content="{i}">
<link rel="canonical" href="{u}">
<meta http-equiv="refresh" content="0; url={u}">
</head><body>
<p>Opening <a href="{u}">{t}</a>&hellip;</p>
<script>location.replace({u!r});</script>
</body></html>"""
