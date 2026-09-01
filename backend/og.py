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
    _shell(d)

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
                  "WHICH IS THE USUAL ANSWER — A DETECTOR THAT ALWAYS FINDS ONE "
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
    _shell(d)

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
    for e in ev:
        pts = e.get("points") or 0
        of = e.get("of") or 1
        frac = max(0.0, min(1.0, float(pts) / float(of)))
        d.text((64, y - 4), str(e.get("factor") or ""), font=mono(17), fill=INK_2)
        bx0, bx1 = 330, 900
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
    _shell(d)

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
