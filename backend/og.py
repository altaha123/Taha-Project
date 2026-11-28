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

FONTS AND THE MARK
Instrument Serif and IBM Plex Mono are bundled under the SIL Open Font
License, which permits redistribution. They are the site's own faces, so a
shared card looks like the product rather than like a generic template. If a
face fails to load the renderer falls back rather than failing the request —
an ugly card beats a broken link preview.

The logo sits beside the wordmark on every card under the same rule. It is
the one element that survives being scrolled past at thumbnail size, which is
how most of these cards are actually seen, so it is drawn first and given the
top-left corner; and if `assets/altaha-logo.png` is missing the card renders
without it rather than 500ing the share route.
"""

import datetime as dt
import io
import json
import os
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
FONT_DIR = os.path.join(HERE, "assets", "fonts")
LOGO_PATH = os.path.join(HERE, "assets", "altaha-logo.png")

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


_logo_cache = {}


def logo(height):
    """
    The mark, as RGBA at the requested height, or None if the file is missing.

    Cached per height because every card asks for the same one and LANCZOS on
    a 262x240 source is not free. Same rule as the fonts: a card without the
    mark beats a share route that 500s.
    """
    with _lock:
        if height in _logo_cache:
            return _logo_cache[height]
    try:
        from PIL import Image
        src = Image.open(LOGO_PATH).convert("RGBA")
        w = max(1, round(src.width * height / src.height))
        out = src.resize((w, height), Image.LANCZOS)
    except Exception:
        out = None
    with _lock:
        _logo_cache[height] = out
    return out


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


def _rupees(draw, right, y, value, size):
    """
    A price, right-aligned, with a rupee sign that actually renders.

    Instrument Serif has no ₹ — asking for one returns .notdef, which draws as
    a hollow box, and a share card headed by a box beside the price is worse
    than one with no currency mark at all. IBM Plex Mono does have the glyph,
    so the sign is set in mono at the serif's cap height and the figure stays
    in the serif.
    """
    fig = serif(size)
    sign = mono(int(size * 0.52), True)
    txt = f"{float(value):,.2f}"
    fw = draw.textlength(txt, font=fig)
    sw = draw.textlength("₹", font=sign)
    x = right - fw - sw - 5
    draw.text((x, y + size * 0.30), "₹", font=sign, fill=INK_2)
    draw.text((x + sw + 5, y), txt, font=fig, fill=INK)
    return x


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


# The lockup: mark, then wordmark. Every card carries it, so these two
# numbers set where the rest of every card's header can start.
LOGO_H = 74
LOGO_GAP = 20


def _shell(draw, img=None):
    """
    Background, gold rule, the mark, the wordmark, footer rule. Shared by
    every card.

    `img` is the canvas behind `draw`. It is optional only so a caller that
    wants the typographic shell alone can omit it; every card in this module
    passes it, because the mark is what makes a card recognisable at the size
    a timeline actually renders it.
    """
    draw.rectangle([0, 0, W, H], fill=PAPER)
    draw.rectangle([0, 0, W, 8], fill=GOLD)

    x = 64
    mark = logo(LOGO_H) if img is not None else None
    if mark is not None:
        # The mark is transparent, so it composites onto the paper ground the
        # same way it sits on the site.
        img.paste(mark, (x, 52), mark)
        x += mark.width + LOGO_GAP

    draw.text((x, 52), "Altaha", font=serif(46), fill=INK)
    w = draw.textlength("Altaha ", font=serif(46))
    draw.text((x + w, 52), "Screener", font=serif(46), fill=GOLD)

    _tracking(draw, (x + 2, 112), "EVERY SCORE SHOWS ITS WORKING", mono(15), MUTE, 3.2)
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
    _shell(d, img)

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

    `stats` is the summary of call_log.listing(): every idea, recorded the day
    it was generated, with its return from that day to the latest scan.
    """
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(img)
    _shell(d, img)

    stats = stats or {}
    d.text((64, 178), "Does it work?", font=serif(66), fill=INK)
    _tracking(d, (66, 258),
              "EVERY IDEA RECORDED THE DAY IT WAS GENERATED, WINNERS AND LOSERS",
              mono(16), MUTE, 2.6)

    def pct(v):
        return "—" if v is None else f"{v:+.2f}%".replace("+-", "-")

    def share(v):
        return "—" if v is None else f"{v:g}%"

    up = stats.get("up_since_pct")
    avg = stats.get("avg_since_pct")
    y = 348
    _metric(d, 64, y, "Ideas recorded", str(stats.get("calls") or 0), INK)
    _metric(d, 340, y, "Up since the idea", share(up), PASS if (up or 0) >= 50 else FAIL)
    _metric(d, 640, y, "Average return", pct(avg), PASS if (avg or 0) > 0 else FAIL)
    if stats.get("index_priced"):
        vs = stats.get("avg_vs_index_pct")
        _metric(d, 960, y, "Against the index", pct(vs), PASS if (vs or 0) > 0 else FAIL)
        foot = "RETURN FROM THE DAY OF THE IDEA, NOTHING DONE AFTER · INDEX OVER THE SAME DAYS"
    else:
        days = stats.get("median_days")
        _metric(d, 960, y, "Median days",
                "—" if days is None else f"{days:g}d", INK_2)
        foot = "RETURN FROM THE DAY OF THE IDEA TO THE LATEST SCAN, NOTHING DONE AFTER"

    _tracking(d, (66, 500), foot, mono(15), MUTE, 2.4)

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


def _origin(url):
    """
    The scheme and host of a link, for building sibling absolute URLs.

    A crawler resolves nothing relative to a page it fetched from a proxy, so
    the icon a share page advertises has to be absolute. Returns "" when the
    target is not an absolute URL, and the caller then omits the icon rather
    than emitting a broken one.
    """
    try:
        from urllib.parse import urlsplit
        parts = urlsplit(str(url))
        if parts.scheme in ("http", "https") and parts.netloc:
            return f"{parts.scheme}://{parts.netloc}"
    except Exception:
        pass
    return ""


def share_page(title, description, image, target):
    """The document a crawler reads and a human never sees for long."""
    def esc(t):
        return (str(t).replace("&", "&amp;").replace("<", "&lt;")
                .replace(">", "&gt;").replace('"', "&quot;"))
    t, d, i, u = esc(title), esc(description), esc(image), esc(target)
    # The script gets the raw URL as a JS string, not the HTML-escaped one:
    # inside <script> an entity is never decoded, so `&amp;` reached
    # location.replace literally and every parameter after the first was
    # lost — /?go=results&q=TARIL opened Results with nothing in it, and a
    # chart link lost its tab and its range. The \u escapes keep the raw URL
    # from closing the script element whatever it contains.
    js = (json.dumps(str(target)).replace("<", "\\u003c").replace(">", "\\u003e")
          .replace("&", "\\u0026"))

    # The mark, so the tab, the bookmark and every chat client that shows a
    # site icon beside the unfurled card get the brand rather than a blank
    # globe. Served by the static site, which is also what `target` points at.
    site = _origin(target)
    icon = ""
    if site:
        icon = (f'<link rel="icon" href="{esc(site)}/favicon.ico" sizes="any">\n'
                f'<link rel="icon" type="image/png" href="{esc(site)}/icon-512.png" '
                f'sizes="512x512">\n'
                f'<link rel="apple-touch-icon" href="{esc(site)}/apple-touch-icon.png">\n'
                f'<meta property="og:logo" content="{esc(site)}/icon-512.png">\n')

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{t}</title>
<meta name="description" content="{d}">
{icon}<meta property="og:type" content="article">
<meta property="og:site_name" content="Altaha Screener">
<meta property="og:title" content="{t}">
<meta property="og:description" content="{d}">
<meta property="og:image" content="{i}">
<meta property="og:image:alt" content="Altaha Screener card: {t}">
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
<script>location.replace({js});</script>
</body></html>"""


# ---------------------------------------------------------------------------
# Chart cards
#
# A picture of the price history, with the shape the detector found drawn on
# top of it. This is the card people actually want to post, because a chart
# argues for itself in a way a number never does.
#
# The same compliance line holds, and it needs restating because a chart makes
# it easy to cross by accident. Historical candles are public fact and may be
# drawn. The pattern's geometry — the rims of the cup, the shoulders, the
# trendlines — is a description of what already happened and may be drawn. The
# pattern's TRIGGER and its MEASURED-MOVE TARGET are forecasts about what a
# reader should do next, so they are not drawn and their numbers never reach
# the image. They stay on the site, beside the base rate and the disclaimer
# that qualify them.
# ---------------------------------------------------------------------------

# Plot box. The right edge stops short of the card so the price axis has a
# gutter of its own — labels drawn inside the plot sit on top of the candles,
# which is exactly what a price axis is supposed to avoid.
PX0, PX1 = 64, 1068
PY0, PY1 = 272, 458
VY0, VY1 = 466, 502          # the volume strip

UP = (31, 122, 85)
DOWN = (176, 58, 43)
GRID = (233, 226, 211)


def _series_window(candles, points, want=150):
    """
    Which slice of history the card shows.

    Wide enough to give the shape context, but never so wide that the shape
    itself becomes six pixels of noise — and always wide enough to contain
    every point of the shape, because a cup with its left rim cropped off is
    a worse picture than no picture.
    """
    n = len(candles)
    if n == 0:
        return 0, 0
    start = max(0, n - want)
    if points:
        first = min(int(p.get("i", n - 1)) for p in points)
        start = min(start, max(0, first - 8))
    return start, n


def _pattern_polyline(name):
    """
    Shapes whose pivots read as a continuous line, versus shapes whose pivots
    are separate touches of two trendlines. Joining a triangle's alternating
    highs and lows produces a zigzag that looks nothing like a triangle, so
    those are drawn as two fitted lines instead.
    """
    n = (name or "").lower()
    return not any(k in n for k in ("triangle", "rectangle", "channel", "flag", "wedge"))


def _fit_line(xs, ys):
    """Least-squares slope/intercept. Two points or fewer: the line through them."""
    n = len(xs)
    if n < 2:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    den = sum((x - mx) ** 2 for x in xs)
    if den <= 0:
        return None
    m = sum((xs[i] - mx) * (ys[i] - my) for i in range(n)) / den
    return m, my - m * mx


def _dashed(d, a, b, fill, width=2, on=9, off=7):
    """Pillow has no dash pattern; a projected or fitted line needs one."""
    (x0, y0), (x1, y1) = a, b
    dx, dy = x1 - x0, y1 - y0
    length = (dx * dx + dy * dy) ** 0.5
    if length <= 0:
        return
    ux, uy = dx / length, dy / length
    t = 0.0
    while t < length:
        e = min(t + on, length)
        d.line([(x0 + ux * t, y0 + uy * t), (x0 + ux * e, y0 + uy * e)], fill=fill, width=width)
        t = e + off


def chart_card(payload: dict) -> bytes:
    """
    One symbol's candles on one timeframe, with the detected shape drawn over
    them.

    payload:
      symbol, name, timeframe, candles [[t, o, h, l, c, v], ...],
      last, change_pct, ema20 [...], ema50 [...] (aligned to candles),
      shape {name, status, direction, confidence, points [{i, price, label}]}
    """
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(img)
    _shell(d, img)

    sym = str(payload.get("symbol") or "").upper().replace(".NS", "").replace(".BO", "")
    name = str(payload.get("name") or sym or "—")
    tf = str(payload.get("timeframe") or "1D")
    candles = [c for c in (payload.get("candles") or []) if c and len(c) >= 5]
    shape = payload.get("shape") or None
    points = list(shape.get("points") or []) if shape else []

    # --- header ------------------------------------------------------------
    f = serif(46)
    if d.textlength(name, font=f) > 600:
        while name and d.textlength(name + "…", font=f) > 600:
            name = name[:-1]
        name = name.rstrip() + "…"
    d.text((64, 144), name, font=f, fill=INK)
    _tracking(d, (66, 202), f"{sym}  ·  NSE  ·  {tf.upper()}", mono(15), MUTE, 2.6)

    last = payload.get("last")
    chg = payload.get("change_pct")
    if last is not None:
        _rupees(d, W - 64, 144, last, 46)
        if chg is not None:
            sub = f"{float(chg):+.2f}% OVER THE WINDOW".replace("+-", "-")
            sw = _tracked_width(d, sub, mono(14), 2.4)
            _tracking(d, (W - 64 - sw, 204), sub, mono(14),
                      UP if float(chg) >= 0 else DOWN, 2.4)

    # --- what was found, above the chart rather than under it ---------------
    #
    # It used to sit at the bottom, where it collided with the footer date and
    # read as a caption. It is the headline: someone scrolling a timeline
    # decides whether to look at the picture based on this line.
    if shape:
        nm = str(shape.get("name") or "")
        fn = serif(34)
        d.text((64, 226), nm, font=fn, fill=INK)
        tail = str(shape.get("status") or "").upper()
        conf = shape.get("confidence")
        if conf is not None:
            tail += f"  ·  {int(conf)} SHAPE MATCH"
        _tracking(d, (72 + d.textlength(nm, font=fn), 240), tail, mono(14),
                  UP if shape.get("direction") == "bullish"
                  else (DOWN if shape.get("direction") == "bearish" else GOLD), 2.4)
    else:
        d.text((64, 226), "No textbook pattern on this timeframe",
               font=serif(34), fill=MUTE)

    if not candles:
        d.text((64, 340), "No price history for this window.", font=serif(40), fill=MUTE)
        _footer(d, dt.date.today().strftime("%d %b %Y"))
        buf = io.BytesIO()
        img.save(buf, "PNG", optimize=True)
        return buf.getvalue()

    start, end = _series_window(candles, points)
    win = candles[start:end]
    n = len(win)

    highs = [float(c[2]) for c in win]
    lows = [float(c[3]) for c in win]
    hi, lo = max(highs), min(lows)
    for p in points:
        i = int(p.get("i", -1))
        if start <= i < end and p.get("price") is not None:
            hi = max(hi, float(p["price"]))
            lo = min(lo, float(p["price"]))
    pad = (hi - lo) * 0.06 or max(hi * 0.01, 0.5)
    hi, lo = hi + pad, lo - pad
    span = hi - lo or 1.0

    step = (PX1 - PX0) / max(n, 1)
    body = max(1.6, min(9.0, step * 0.62))

    def X(i):
        return PX0 + (i - start + 0.5) * step

    def Y(p):
        return PY1 - (float(p) - lo) / span * (PY1 - PY0)

    # --- grid and the price axis -------------------------------------------
    for k in range(5):
        y = PY0 + (PY1 - PY0) * k / 4
        d.line([(PX0, y), (PX1, y)], fill=GRID, width=1)
        val = hi - (hi - lo) * k / 4
        lbl = f"{val:,.0f}" if val >= 200 else f"{val:,.1f}"
        d.text((PX1 + 14, y - 10), lbl, font=mono(14), fill=MUTE)

    # --- candles ------------------------------------------------------------
    for k, c in enumerate(win):
        o, h, l, cl = float(c[1]), float(c[2]), float(c[3]), float(c[4])
        x = X(start + k)
        col = UP if cl >= o else DOWN
        d.line([(x, Y(h)), (x, Y(l))], fill=col, width=1)
        y0, y1 = Y(max(o, cl)), Y(min(o, cl))
        if y1 - y0 < 1:
            y1 = y0 + 1
        d.rectangle([x - body / 2, y0, x + body / 2, y1], fill=col)

    # --- moving averages ----------------------------------------------------
    for key, colour, width in (("ema20", GOLD, 2), ("ema50", MUTE, 1)):
        vals = payload.get(key) or []
        pts = [(X(start + k), Y(vals[start + k]))
               for k in range(n)
               if start + k < len(vals) and vals[start + k] is not None]
        if len(pts) > 1:
            d.line(pts, fill=colour, width=width)

    # --- volume -------------------------------------------------------------
    vols = [float(c[5]) if len(c) > 5 and c[5] else 0.0 for c in win]
    vmax = max(vols) or 1.0
    for k, v in enumerate(vols):
        if v <= 0:
            continue
        x = X(start + k)
        h = (v / vmax) * (VY1 - VY0)
        c = win[k]
        col = UP if float(c[4]) >= float(c[1]) else DOWN
        d.rectangle([x - body / 2, VY1 - h, x + body / 2, VY1],
                    fill=(col[0], col[1], col[2]))

    # --- the shape ----------------------------------------------------------
    inside = [p for p in points
              if start <= int(p.get("i", -1)) < end and p.get("price") is not None]
    if inside:
        if _pattern_polyline(shape.get("name")):
            line = [(X(int(p["i"])), Y(p["price"])) for p in inside]
            if len(line) > 1:
                d.line(line, fill=GOLD, width=3)
        else:
            # Two fitted trendlines through the touches, which is what the
            # detector itself measured. Dashed, because a fitted line is an
            # approximation and should not be drawn as though it were data.
            mid = sum(float(p["price"]) for p in inside) / len(inside)
            for group in (
                [p for p in inside if float(p["price"]) >= mid],
                [p for p in inside if float(p["price"]) < mid],
            ):
                if len(group) < 2:
                    continue
                xs = [float(p["i"]) for p in group]
                ys = [float(p["price"]) for p in group]
                fit = _fit_line(xs, ys)
                if not fit:
                    continue
                m, b = fit
                a = (X(min(xs)), Y(m * min(xs) + b))
                z = (X(max(xs)), Y(m * max(xs) + b))
                _dashed(d, a, z, GOLD, 2)

        for p in inside:
            x, y = X(int(p["i"])), Y(p["price"])
            d.ellipse([x - 5, y - 5, x + 5, y + 5], fill=PAPER, outline=GOLD, width=3)
            lbl = str(p.get("label") or "")
            if lbl:
                lw = d.textlength(lbl, font=mono(13, True))
                d.text((x - lw / 2, y - 30), lbl, font=mono(13, True), fill=GOLD)

    if not shape:
        _tracking(d, (66, 520),
                  "WHICH IS THE USUAL ANSWER. A DETECTOR THAT ALWAYS FINDS ONE "
                  "HAS STOPPED DETECTING", mono(13), MUTE, 2.2)

    _footer(d, dt.date.today().strftime("%d %b %Y"))
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def idea_card(row: dict) -> bytes:
    """
    One idea, with the ledger that produced its conviction.

    The evidence table is the point. A conviction number alone is an opinion;
    the same number with the seven weighted inputs that add up to it is a
    method someone can argue with, and arguing with it is the invitation.
    """
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(img)
    _shell(d, img)

    sym = str(row.get("symbol") or row.get("ticker") or "").upper()
    sym = sym.replace(".NS", "").replace(".BO", "")
    name = str(row.get("name") or sym or "—")
    conv = _num(row.get("conviction"))
    band = str(row.get("conviction_band") or "")
    setup = row.get("setup")
    setup = setup.get("name") if isinstance(setup, dict) else setup
    horizon = row.get("horizon")

    f = serif(52)
    if d.textlength(name, font=f) > 700:
        while name and d.textlength(name + "…", font=f) > 700:
            name = name[:-1]
        name = name.rstrip() + "…"
    d.text((64, 168), name, font=f, fill=INK)
    sub = f"{sym}  ·  NSE" + (f"  ·  {str(setup).upper()}" if setup else "")
    if horizon:
        sub += f"  ·  HOLD {str(horizon).upper()}"
    _tracking(d, (66, 232), sub, mono(15), MUTE, 2.6)

    score = "—" if conv is None else str(int(round(conv)))
    fs = serif(140)
    sw = d.textlength(score, font=fs)
    d.text((W - 84 - sw, 128), score, font=fs, fill=_band(conv))
    lbl = "CONVICTION / 100" + (f"  ·  {band.upper()}" if band else "")
    lw = _tracked_width(d, lbl, mono(15), 2.6)
    _tracking(d, (W - 84 - lw, 272), lbl, mono(15), MUTE, 2.6)

    # The ledger, as bars. Six lines fit; the rest is on the site.
    ev = [e for e in (row.get("evidence") or []) if e.get("of")]
    ev = sorted(ev, key=lambda e: -(e.get("points") or 0))[:6]
    y = 318
    d.line([(64, y - 18), (W - 64, y - 18)], fill=RULE, width=1)
    # The bars start after the longest label, up to a point; a label longer
    # than the room left is cut short, never painted over.
    fl = mono(17)
    labels = [str(e.get("factor") or "") for e in ev]
    widest = max((d.textlength(t, font=fl) for t in labels), default=0)
    bx0, bx1 = min(max(330, int(64 + widest + 18) + 1), 520), 900
    room = bx0 - 18 - 64
    for e, label in zip(ev, labels):
        pts = e.get("points") or 0
        of = e.get("of") or 1
        frac = max(0.0, min(1.0, float(pts) / float(of)))
        if d.textlength(label, font=fl) > room:
            while label and d.textlength(label + "\u2026", font=fl) > room:
                label = label[:-1]
            label = label.rstrip() + "\u2026"
        d.text((64, y - 4), label, font=fl, fill=INK_2)
        d.rectangle([bx0, y + 4, bx1, y + 12], fill=PAPER_2)
        d.rectangle([bx0, y + 4, bx0 + (bx1 - bx0) * frac, y + 12], fill=GOLD_LT)
        tail = f"{float(pts):.1f} / {int(of)}"
        tw = d.textlength(tail, font=mono(17))
        d.text((W - 64 - tw, y - 4), tail, font=mono(17), fill=MUTE)
        y += 35

    _footer(d, dt.date.today().strftime("%d %b %Y"))
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def holding_card(row: dict) -> bytes:
    """
    One tracked idea, marked to market.

    Return and alpha on a position the engine committed to in public, in
    advance, and cannot now quietly delete. Losers render exactly as readily
    as winners, which is the only reason posting the winners is honest.
    """
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(img)
    _shell(d, img)

    sym = str(row.get("symbol") or "").upper().replace(".NS", "").replace(".BO", "")
    name = str(row.get("name") or sym or "—")

    def pctv(v):
        return "—" if v is None else f"{float(v):+.2f}%".replace("+-", "-")

    def tone(v):
        if v is None:
            return MUTE
        return PASS if float(v) > 0 else (FAIL if float(v) < 0 else INK_2)

    f = serif(52)
    if d.textlength(name, font=f) > 700:
        while name and d.textlength(name + "…", font=f) > 700:
            name = name[:-1]
        name = name.rstrip() + "…"
    d.text((64, 172), name, font=f, fill=INK)
    added = row.get("added_on")
    _tracking(d, (66, 236),
              f"{sym}  ·  NSE" + (f"  ·  TRACKED SINCE {str(added).upper()}" if added else ""),
              mono(15), MUTE, 2.6)

    ret = row.get("return_pct")
    fs = serif(140)
    txt = pctv(ret)
    sw = d.textlength(txt, font=fs)
    d.text((W - 84 - sw, 144), txt, font=fs, fill=tone(ret))
    lbl = "RETURN SINCE THE IDEA WAS RECORDED"
    lw = _tracked_width(d, lbl, mono(15), 2.6)
    _tracking(d, (W - 84 - lw, 292), lbl, mono(15), MUTE, 2.6)

    y = 384
    _metric(d, 64, y, "Alpha vs index", pctv(row.get("alpha_pct")), tone(row.get("alpha_pct")))
    _metric(d, 366, y, "Index did", pctv(row.get("bench_return_pct")), INK_2)
    _metric(d, 640, y, "Days held", str(row.get("days_held") or 0), INK_2)
    status = str(row.get("status") or "open")
    _tracking(d, (900, y), "STATUS", mono(15), MUTE, 2.6)
    d.text((898, y + 30), status.title(), font=serif(46), fill=INK_2)

    _tracking(d, (66, 500),
              "ALPHA IS RETURN MINUS THE INDEX OVER THE IDENTICAL WINDOW",
              mono(14), MUTE, 2.4)

    _footer(d, dt.date.today().strftime("%d %b %Y"))
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Results cards
#
# A quarter as the company filed it: profit, revenue, margin and the same
# quarter a year earlier. Every figure on it is the company's own, so it is a
# statement of fact rather than an opinion — the safest card on the site to
# post, and the one people most want to post on the evening results land.
# ---------------------------------------------------------------------------

def _crore(v):
    """₹ crore, Indian grouping is the site's job; the card keeps it plain."""
    if v is None:
        return "—"
    return f"{float(v):,.2f}"


def _pct_txt(v):
    return "—" if v is None else f"{float(v):+.1f}%".replace("+-", "-")


def _filed_on(filed_at):
    """'13-Oct-2026 16:34:09' -> '13 OCT 2026, 16:34 IST'; anything else as given."""
    s = str(filed_at or "").strip()
    for fmt, out in (("%d-%b-%Y %H:%M:%S", "%d %b %Y, %H:%M IST"),
                     ("%d-%b-%Y %H:%M", "%d %b %Y, %H:%M IST"),
                     ("%d-%b-%Y", "%d %b %Y"), ("%Y-%m-%d", "%d %b %Y")):
        try:
            return dt.datetime.strptime(s, fmt).strftime(out).upper()
        except ValueError:
            continue
    return s.upper()


def _year_ago(series):
    """The same fiscal quarter a year before the newest, by label."""
    if not series:
        return None
    head = str(series[0].get("period") or "")
    parts = head.split("FY")
    if len(parts) != 2 or not parts[1].strip().isdigit():
        return None
    want = f"{parts[0].strip()} FY{(int(parts[1]) - 1) % 100:02d}"
    for item in series[1:]:
        if str(item.get("period") or "").strip() == want:
            return item
    return None


def results_card(r: dict) -> bytes:
    """
    One quarter's results. `r` is a /results payload, from the exchange filing
    or the Yahoo fallback; the card says which by what it can state.
    """
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(img)
    _shell(d, img)

    sym = str(r.get("symbol") or "").upper().replace(".NS", "").replace(".BO", "")
    name = str(r.get("name") or sym or "—")
    quarter = str(r.get("quarter") or "")
    filed = bool(r.get("filed_at"))

    # The quarter, top right, where the eye lands after the mark.
    tag = f"{quarter} RESULTS" if quarter else "QUARTERLY RESULTS"
    tw = _tracked_width(d, tag, mono(20, True), 3)
    _tracking(d, (W - 64 - tw, 60), tag, mono(20, True), GOLD, 3)
    sub = (f"FILED WITH NSE {_filed_on(r.get('filed_at'))}" if filed
           else (f"STATEMENTS DATED {_filed_on(r.get('as_of'))}" if r.get("as_of") else ""))
    if sub:
        sw = _tracked_width(d, sub, mono(14), 2.2)
        _tracking(d, (W - 64 - sw, 96), sub, mono(14), MUTE, 2.2)

    f = serif(54)
    if d.textlength(name, font=f) > W - 128:
        while name and d.textlength(name + "…", font=f) > W - 128:
            name = name[:-1]
        name = name.rstrip() + "…"
    d.text((64, 160), name, font=f, fill=INK)
    bits = [sym] if sym else []
    if filed:
        bits.append("NSE")
    if r.get("basis") and filed:
        bits.append(str(r["basis"]).upper())
    if r.get("as_of"):
        bits.append("QUARTER ENDED " + _filed_on(r.get("as_of")))
    _tracking(d, (66, 228), "  ·  ".join(bits), mono(15), MUTE, 2.6)
    d.line([(64, 270), (W - 64, 270)], fill=RULE, width=1)

    # Left: profit after tax, the headline.
    pat, yoy = r.get("pat_cr"), r.get("pat_yoy_pct")
    # A loss is named as one and set in red. A minus sign in front of a
    # rupee figure is the easiest thing on a card to miss at thumbnail size.
    loss = pat is not None and float(pat) < 0
    _tracking(d, (66, 296), "NET LOSS" if loss else "PROFIT AFTER TAX",
              mono(15), FAIL if loss else MUTE, 2.6)
    big = serif(112)
    sign, unit = mono(52, True), serif(48)
    y0 = 318
    x = 64
    d.text((x, y0 + 36), "₹", font=sign, fill=INK_2)
    x += d.textlength("₹", font=sign) + 8
    fig = "—" if pat is None else _crore(abs(float(pat)))
    d.text((x, y0), fig, font=big, fill=FAIL if loss else INK)
    x += d.textlength(fig, font=big) + 14
    d.text((x, y0 + 52), "Cr", font=unit, fill=INK_2)

    base = r.get("pat_yoy_base_cr")
    then = None
    if base is not None:
        if float(base) < 0:
            then = f"vs a loss of ₹{_crore(abs(float(base)))} Cr a year earlier"
        elif loss:
            then = f"vs a profit of ₹{_crore(base)} Cr a year earlier"
        else:
            then = f"vs ₹{_crore(base)} Cr a year earlier"
    if yoy is not None:
        col = PASS if yoy >= 0 else FAIL
        pill = f"{_pct_txt(yoy)} YoY"
        pf = mono(22, True)
        pw = d.textlength(pill, font=pf)
        d.rounded_rectangle([64, 452, 64 + pw + 28, 492], radius=6, outline=col, width=2)
        d.text((78, 458), pill, font=pf, fill=col)
        if then:
            d.text((64 + pw + 46, 461), then, font=mono(18), fill=MUTE)
    elif then:
        # Across zero a percentage means nothing; the two figures say it.
        d.text((64, 461), then, font=mono(18), fill=MUTE)
    elif pat is not None:
        d.text((64, 461), "Year-ago quarter not published", font=mono(18), fill=MUTE)

    # Right: revenue and net profit, the same quarter a year apart.
    def bars(top, title, series, now):
        if not series:
            return top
        _tracking(d, (700, top), f"{title}, ₹ CRORE", mono(14), MUTE, 2.4)
        then = _year_ago(series or [])
        rows = [(then.get("period"), then.get("value_cr"), False)] if then else []
        if series:
            rows.append((series[0].get("period"), now, True))
        vals = [abs(float(v)) for _p, v, _c in rows if v is not None] or [1.0]
        top_v = max(vals) or 1.0
        y = top + 30
        for period, v, cur in rows:
            d.text((700, y - 2), str(period or ""), font=mono(15), fill=INK_2 if cur else MUTE)
            bx0, bx1 = 800, 1036
            d.rectangle([bx0, y + 2, bx1, y + 16], fill=PAPER_2)
            if v is not None:
                w = max(3, (bx1 - bx0) * abs(float(v)) / top_v)
                d.rectangle([bx0, y + 2, bx0 + w, y + 16],
                            fill=(PASS if float(v) >= 0 else FAIL) if cur else RULE)
            tail = _crore(v)
            vw = d.textlength(tail, font=mono(15, cur))
            d.text((W - 64 - vw, y - 2), tail, font=mono(15, cur), fill=INK if cur else MUTE)
            y += 30
        return y

    y = bars(296, "REVENUE", r.get("revenue_series"), r.get("revenue_cr"))
    y = bars(y + 14, "NET PROFIT", r.get("pat_series"), pat)

    m_now, m_then = r.get("net_margin_pct"), r.get("net_margin_yoy_pct")
    if m_now is not None:
        line = f"NET MARGIN {m_now:.1f}%"
        if m_then is not None:
            line += f"  ·  {m_then:.1f}% A YEAR EARLIER"
        _tracking(d, (700, y + 12), line, mono(14), INK_2, 2.2)

    _footer(d, "AS FILED · REG 33" if filed else dt.date.today().strftime("%d %b %Y"))
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Concall cards
#
# One earnings call: the company, the quarter, the brief's headline and as
# much of its summary as fits in whole sentences. It is the only card here
# that is mostly prose, so it is the only one that wraps text.
#
# What it may say is what the brief may say: what management told the call,
# with their figures. A revenue or margin figure management guided for is a
# fact about the call and is drawn; it is not a price level, and nothing on
# the card is a view on the share. The card also says a model wrote it — the
# page does, on every brief, and a picture that travels without the page has
# to carry that with it.
# ---------------------------------------------------------------------------

_covers_cache = {}


def _covers(ch):
    """
    Whether the serif can draw this character.

    Instrument Serif has no ₹, and a brief is full of them. Pillow does not
    expose a font's character map, so a missing glyph is recognised by what it
    draws: the same .notdef box as a code point no font has.
    """
    if ch.isspace():
        return True
    hit = _covers_cache.get(ch)
    if hit is None:
        try:
            f = serif(40)
            hit = bytes(f.getmask(ch)) != bytes(f.getmask("\U0010fffd"))
        except Exception:
            hit = True
        _covers_cache[ch] = hit
    return hit


def _runs(text):
    """Split text into (serif can draw it, run) pieces, in order."""
    out = []
    for ch in text:
        ok = _covers(ch)
        if out and out[-1][0] == ok:
            out[-1][1] += ch
        else:
            out.append([ok, ch])
    return out


def _prose_fonts(size):
    # The mono is wider and taller for its size than the serif; at four fifths
    # a rupee sign sits at the height of the figures beside it.
    return serif(size), mono(max(8, round(size * 0.8)))


def _prose_width(draw, text, size):
    fs, fm = _prose_fonts(size)
    return sum(draw.textlength(run, font=fs if ok else fm) for ok, run in _runs(text))


def _prose(draw, x, baseline, text, size, fill):
    """One line of serif text on a baseline, with the mono filling its gaps."""
    fs, fm = _prose_fonts(size)
    for ok, run in _runs(text):
        f = fs if ok else fm
        draw.text((x, baseline), run, font=f, fill=fill, anchor="ls")
        x += draw.textlength(run, font=f)
    return x


def _wrap(draw, text, size, width):
    """Greedy word wrap. A word wider than the line gets a line to itself."""
    lines, line = [], ""
    for word in str(text or "").split():
        trial = (line + " " + word) if line else word
        if line and _prose_width(draw, trial, size) > width:
            lines.append(line)
            line = word
        else:
            line = trial
    if line:
        lines.append(line)
    return lines


def _clip(draw, lines, n, size, width):
    """The first n lines, the last ending in an ellipsis when some were cut."""
    if len(lines) <= n:
        return lines
    kept = lines[:n]
    last = kept[-1].rstrip(" ,;:—-")
    while last and _prose_width(draw, last + "…", size) > width:
        last = last.rsplit(" ", 1)[0] if " " in last else last[:-1]
        last = last.rstrip(" ,;:—-")
    kept[-1] = last + "…"
    return kept


def _sentences(text):
    """
    Sentences, split only where a full stop ends one.

    A brief is written in rupees and percentages, so most of its full stops
    are decimal points: "₹4.2 crore", "5.5%". A stop counts only when a space
    and a capital, a digit or a rupee sign follow it.
    """
    import re
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9₹“\"'(])", str(text or "").strip())
    return [p.strip() for p in parts if p.strip()]


def _whole_sentences(draw, text, size, width, room):
    """
    As much of a paragraph as fits in `room` lines, ending on a sentence.

    A summary cut mid-sentence reads as a mistake; one that stops a sentence
    early reads as a summary. Only when even the first sentence is too long is
    it cut, and then it says so with an ellipsis.
    """
    if room < 1:
        return []
    kept = []
    for s in _sentences(text):
        trial = _wrap(draw, " ".join(kept + [s]), size, width)
        if len(trial) > room:
            break
        kept.append(s)
    if kept:
        return _wrap(draw, " ".join(kept), size, width)
    return _clip(draw, _wrap(draw, text, size, width), room, size, width)


def _call_day(value):
    """'2026-11-20' or an ISO timestamp -> '20 NOV 2026'; '' when unreadable."""
    s = str(value or "").strip()
    if not s:
        return ""
    try:
        return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).strftime("%d %b %Y").upper()
    except ValueError:
        pass
    try:
        return dt.datetime.strptime(s[:10], "%Y-%m-%d").strftime("%d %b %Y").upper()
    except ValueError:
        return ""


# The headline is the card. It is set as large as three lines allow, and a
# long one steps down rather than being cut.
HEADLINE_SIZES = (62, 56, 50, 45, 40)
HEADLINE_LINES = 3
SUMMARY_SIZE = 28
SUMMARY_LEAD = 39


def concall_card(c: dict) -> bytes:
    """
    One earnings call, as its brief tells it.

    c: symbol, company, quarter, call_date, filed_at, key, and brief
       {headline, summary}. The same fields /concalls gives the page.
    """
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(img)
    _shell(d, img)

    brief = c.get("brief") or {}
    sym = str(c.get("symbol") or "").upper().replace(".NS", "").replace(".BO", "")
    company = " ".join(str(c.get("company") or sym or "").split())
    quarter = str(c.get("quarter") or "").strip().upper()
    headline = " ".join(str(brief.get("headline") or "").split())
    summary = " ".join(str(brief.get("summary") or "").split())
    if not headline:
        # A brief always has a summary; a headline is the model's to leave out.
        first = _sentences(summary)
        headline, summary = (first[0], " ".join(first[1:])) if first else ("", "")

    # What this is, top right, where the eye lands after the mark.
    tag = f"{quarter} EARNINGS CALL" if quarter else "EARNINGS CALL"
    tw = _tracked_width(d, tag, mono(20, True), 3)
    _tracking(d, (W - 64 - tw, 60), tag, mono(20, True), GOLD, 3)
    held, filed = _call_day(c.get("call_date")), _call_day(c.get("filed_at"))
    sub = f"CALL HELD {held}" if held else (f"TRANSCRIPT FILED {filed}" if filed else "")
    if sub:
        sw = _tracked_width(d, sub, mono(14), 2.2)
        _tracking(d, (W - 64 - sw, 96), sub, mono(14), MUTE, 2.2)

    # The company, as the line above the headline. A key call is flagged the
    # way the page flags it: a filled gold tag in front of the name.
    x, y = 64, 164
    kf = mono(17, True)
    if c.get("key"):
        flag = "KEY CALL"
        fw = _tracked_width(d, flag, mono(14, True), 2.2)
        d.rounded_rectangle([x, y - 5, x + fw + 24, y + 25], radius=5, fill=GOLD)
        _tracking(d, (x + 12, y + 1), flag, mono(14, True), PAPER, 2.2)
        x += fw + 24 + 16
    name = company.upper()
    tail = f" · {sym}" if sym and sym != name else ""
    room = W - 64 - x
    if _tracked_width(d, name + tail, kf, 2.4) > room:
        tail = ""
    if _tracked_width(d, name, kf, 2.4) > room:
        while name and _tracked_width(d, name + "…", kf, 2.4) > room:
            name = name[:-1]
        name = name.rstrip() + "…"
    end = _tracking(d, (x, y), name, kf, INK, 2.4)
    if tail:
        _tracking(d, (end, y), tail, kf, MUTE, 2.4)

    # The headline.
    width = W - 128
    size, lines = HEADLINE_SIZES[-1], []
    for size in HEADLINE_SIZES:
        lines = _wrap(d, headline, size, width)
        if len(lines) <= HEADLINE_LINES:
            break
    lines = _clip(d, lines, HEADLINE_LINES, size, width)
    lead = round(size * 1.1)
    baseline = 208 + round(size * 0.82)
    for line in lines:
        _prose(d, 62, baseline, line, size, INK)
        baseline += lead
    bottom = baseline - lead + round(size * 0.24)

    # As much of the summary as fits above the footer, in whole sentences.
    top = bottom + 22
    room = int((H - 92 - 20 - top) // SUMMARY_LEAD)
    baseline = top + round(SUMMARY_SIZE * 0.82)
    for line in _whole_sentences(d, summary, SUMMARY_SIZE, width, room):
        _prose(d, 64, baseline, line, SUMMARY_SIZE, INK_2)
        baseline += SUMMARY_LEAD

    _footer(d, "AI-WRITTEN FROM THE TRANSCRIPT FILED WITH BSE")
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# WOW order cards
#
# One order, sized against the company that won it: the percentage of market
# cap as the figure, the order as a sentence built from the filing, and the
# three numbers the percentage is made of. It is arithmetic on published
# figures, so like the results card it states facts and takes no view.
#
# What it never carries is what the page never carries: no target, no level,
# no word on the share. An order larger than the whole company says so and
# says to open the filing, because that is also what a misread figure looks
# like and a picture travels without the page's caution beside it.
# ---------------------------------------------------------------------------

def _rupee_cr(v):
    """₹ crore the way the page writes it: '₹2,691 cr', '₹18.51 cr', '₹45 lakh'."""
    try:
        n = float(v)
    except (TypeError, ValueError):
        return "—"
    if n != n:
        return "—"
    if n >= 100000:
        return f"₹{n / 100000:.2f} lakh cr"
    if n >= 100:
        return f"₹{n:,.0f} cr"
    if n >= 1:
        return f"₹{n:,.2f}".rstrip("0").rstrip(".") + " cr"
    return f"₹{n * 100:.2f}".rstrip("0").rstrip(".") + " lakh"


def _pct_of(v):
    n = float(v)
    if n >= 10:
        return f"{n:.0f}%"
    if n >= 0.1:
        return f"{n:.1f}%"
    return "<0.1%"


def _sales_span(months):
    """A length of sales a reader can picture: weeks, then months, then years."""
    m = float(months)
    if m < 0.25:
        return "under a week"
    if m < 1:
        w = max(1, round(m * 4.35))
        return f"about {w} week" + ("" if w == 1 else "s")
    if m < 18:
        r = round(m, 1)
        txt = f"{r:.1f}".rstrip("0").rstrip(".")
        return f"{txt} month" + ("" if r == 1 else "s")
    return f"{m / 12:.1f} years"


def order_sentence(r: dict) -> str:
    """'₹2,691 cr letter of award from NTPC Green Energy Limited', from the filing."""
    what = (r.get("kind") or "order").lower()
    line = f"{_rupee_cr(r.get('value_cr'))} {what}"
    if r.get("customer"):
        line += f" from {r['customer']}"
    return " ".join(line.split())


WOW_BAR_FULL = 50.0            # the bar is full at half the company's value


def wow_card(r: dict, threshold: float = 10.0) -> bytes:
    """
    One order against its company. `r` is a row of /wow-orders.
    """
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(img)
    _shell(d, img)

    sym = str(r.get("symbol") or "").upper().replace(".NS", "").replace(".BO", "")
    company = " ".join(str(r.get("company") or sym or "").split())
    pct = r.get("pct_of_market_cap")
    is_wow = bool(r.get("wow"))

    # What this is, top right.
    tag = "WOW ORDER" if is_wow else "ORDER WIN"
    tw = _tracked_width(d, tag, mono(20, True), 3)
    _tracking(d, (W - 64 - tw, 60), tag, mono(20, True), GOLD, 3)
    filed = _call_day(r.get("at") or r.get("date"))
    if filed:
        sub = f"FILED {filed}"
        sw = _tracked_width(d, sub, mono(14), 2.2)
        _tracking(d, (W - 64 - sw, 96), sub, mono(14), MUTE, 2.2)

    # The company.
    kf = mono(17, True)
    name = company.upper()
    tail = f" · {sym}" if sym and sym != name else ""
    room = W - 128
    if _tracked_width(d, name + tail, kf, 2.4) > room:
        tail = ""
    if _tracked_width(d, name, kf, 2.4) > room:
        while name and _tracked_width(d, name + "…", kf, 2.4) > room:
            name = name[:-1]
        name = name.rstrip() + "…"
    end = _tracking(d, (64, 164), name, kf, INK, 2.4)
    if tail:
        _tracking(d, (end, 164), tail, kf, MUTE, 2.4)

    # Left: the size against the company, as a figure and a bar.
    col = 300
    if pct is not None:
        txt = _pct_of(pct)
        size = 150
        for size in (150, 132, 116, 100, 84):
            if d.textlength(txt, font=serif(size)) <= col:
                break
        d.text((60, 196 + (150 - size) // 2), txt, font=serif(size),
               fill=GOLD if is_wow else INK)
        _tracking(d, (66, 372), "OF MARKET CAP", mono(15), MUTE, 2.6)
        y0, y1 = 404, 414
        d.rounded_rectangle([64, y0, 64 + col, y1], radius=5, fill=RULE)
        fill = max(6, col * min(1.0, float(pct) / WOW_BAR_FULL))
        d.rounded_rectangle([64, y0, 64 + fill, y1], radius=5, fill=GOLD if is_wow else INK_2)
        tick = 64 + col * min(1.0, float(threshold) / WOW_BAR_FULL)
        d.rectangle([tick - 1, y0 - 4, tick + 1, y1 + 4], fill=INK)

    # Right: the order as a sentence, then what it is for.
    x, width = 412, W - 64 - 412
    sentence = order_sentence(r)
    size, lines = 34, []
    for size in (48, 44, 40, 36, 32):
        lines = _wrap(d, sentence, size, width)
        if len(lines) <= 3:
            break
    lines = _clip(d, lines, 3, size, width)
    lead = round(size * 1.12)
    baseline = 200 + round(size * 0.82)
    for line in lines:
        _prose(d, x, baseline, line, size, INK)
        baseline += lead
    top = baseline - lead + round(size * 0.24) + 16
    nature = " ".join(str(r.get("nature") or "").split())
    room = min(2, int((428 - top) // 34))
    if nature and room >= 1:
        base = top + 21
        for line in _clip(d, _wrap(d, nature, 25, width), room, 25, width):
            _prose(d, x, base, line, 25, INK_2)
            base += 34

    # Under both: the numbers the percentage is made of.
    d.line([(64, 440), (W - 64, 440)], fill=RULE, width=1)
    cells = [("ORDER", _rupee_cr(r.get("value_cr")))]
    if r.get("market_cap_cr") is not None:
        cells.append(("MARKET CAP", _rupee_cr(r.get("market_cap_cr"))))
    if r.get("months_of_sales") is not None:
        year = str(r.get("sales_year") or "").upper()
        cells.append((f"AGAINST {year} SALES" if year else "AGAINST A YEAR'S SALES",
                      _sales_span(r["months_of_sales"])))
    for i, (label, value) in enumerate(cells[:3]):
        cx = 64 + i * 358
        _tracking(d, (cx + 2, 458), label, mono(14), MUTE, 2.4)
        _prose(d, cx, 512, value, 36, INK)

    note = "AS THE COMPANY FILED IT · REG 30"
    if r.get("outsized"):
        note = "LARGER THAN THE COMPANY: OPEN THE FILING"
    elif r.get("currency_converted"):
        rate = r.get("fx_rate")
        note = (f"US DOLLARS AT ₹{rate:g}, AN ASSUMED RATE" if rate
                else "CONVERTED AT AN ASSUMED RATE")
    _footer(d, note)
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Research Deck cards
#
# One article the owner published: its cover photo on the right, the title and
# as much of the summary as fits on the left, the mark above both. The photo is
# the owner's own upload, cropped to its panel from the centre, so a chart
# screenshot keeps its middle and a portrait keeps its face.
#
# The card says what the article says and nothing more. The footer names it as
# research from Altaha and carries the same "not investment advice" line as
# every other card; the article itself is where its reasoning and its
# disclaimer live.
# ---------------------------------------------------------------------------

RESEARCH_PANEL = (W - 64 - 440, 150, W - 64, H - 112)   # x0, y0, x1, y1


def _cover_panel(img, cover_bytes, box, radius=18):
    """Paste `cover_bytes` cropped to fill `box` with rounded corners.
    Returns False, drawing nothing, when the bytes are not an image."""
    from PIL import Image, ImageDraw, ImageOps
    try:
        src = Image.open(io.BytesIO(cover_bytes))
        src.load()
        src = src.convert("RGB")
    except Exception:
        return False
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    fitted = ImageOps.fit(src, (w, h), Image.LANCZOS, centering=(0.5, 0.5))
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, w - 1, h - 1], radius=radius, fill=255)
    img.paste(fitted, (x0, y0), mask)
    ImageDraw.Draw(img).rounded_rectangle([x0, y0, x1 - 1, y1 - 1], radius=radius,
                                          outline=RULE, width=1)
    return True


def research_card(a: dict, cover_bytes: bytes = None) -> bytes:
    """
    One Research Deck article.

    a: title, summary, tickers, published_at — the fields research_deck.get()
       returns. cover_bytes: the stored cover photo, or None.
    """
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(img)
    _shell(d, img)

    has_cover = bool(cover_bytes) and _cover_panel(img, cover_bytes, RESEARCH_PANEL)
    d = ImageDraw.Draw(img)
    right = (RESEARCH_PANEL[0] - 44) if has_cover else (W - 64)
    width = right - 64

    # What this is, top right, where every other card says what it is.
    tag = "RESEARCH DECK"
    tw = _tracked_width(d, tag, mono(20, True), 3)
    _tracking(d, (W - 64 - tw, 60), tag, mono(20, True), GOLD, 3)
    day = _call_day(a.get("published_at"))
    if day:
        sub = f"PUBLISHED {day}"
        sw = _tracked_width(d, sub, mono(14), 2.2)
        _tracking(d, (W - 64 - sw, 96), sub, mono(14), MUTE, 2.2)

    # The stocks it is about, as the line above the title.
    tickers = [str(t).upper() for t in (a.get("tickers") or []) if t][:4]
    y = 168
    if tickers:
        line = " · ".join(tickers)
        kf = mono(17, True)
        while tickers and _tracked_width(d, line, kf, 2.4) > width:
            tickers = tickers[:-1]
            line = " · ".join(tickers) + " …"
        _tracking(d, (64, y), line, kf, INK, 2.4)
        y += 40
    else:
        y += 6

    title = " ".join(str(a.get("title") or "").split())
    sizes = (60, 54, 48, 43, 38) if has_cover else HEADLINE_SIZES
    size, lines = sizes[-1], []
    for size in sizes:
        lines = _wrap(d, title, size, width)
        if len(lines) <= HEADLINE_LINES:
            break
    lines = _clip(d, lines, HEADLINE_LINES, size, width)
    lead = round(size * 1.1)
    baseline = y + round(size * 0.82)
    for line in lines:
        _prose(d, 62, baseline, line, size, INK)
        baseline += lead
    bottom = baseline - lead + round(size * 0.24)

    summary = " ".join(str(a.get("summary") or "").split())
    top = bottom + 22
    room = int((H - 92 - 20 - top) // SUMMARY_LEAD)
    baseline = top + round(SUMMARY_SIZE * 0.82)
    for line in _whole_sentences(d, summary, SUMMARY_SIZE, width, room):
        _prose(d, 64, baseline, line, SUMMARY_SIZE, INK_2)
        baseline += SUMMARY_LEAD

    _footer(d, "RESEARCH FROM ALTAHA")
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()
