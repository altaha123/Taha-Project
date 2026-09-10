"""
The daily digest, as an email.

WHY TABLES AND NOT A PICTURE
og.py can already render a beautiful PNG card, and it is the wrong tool here.
Gmail, Outlook and most Indian mail clients block remote images by default
until a reader clicks "display images" — so an emailed card is, for a large
share of first-time recipients, a blank rectangle where their portfolio should
be. The one email that has to work on the first open is the first one. So the
numbers are laid out in HTML tables that cannot fail to render, and the PNG
stays where it earns its keep: social previews, where it always displays.

WHY IT LOOKS OLD-FASHIONED
Email clients are not browsers. Outlook renders with Word's engine; Gmail
strips <style> blocks in some contexts and all of them in others. So: tables
for layout, inline styles only, no flexbox, no grid, no web fonts, no
JavaScript, 600px wide. This is not carelessness, it is the format.

DARK MODE
Some clients invert colours automatically and cannot be stopped. The palette
is therefore mid-tone rather than pure white on pure black, so an inverted
copy stays readable instead of turning into grey text on a grey card.

EVERY EMAIL HAS A PLAIN-TEXT TWIN
render_text() is not a fallback nobody sees. Spam filters read it, and a
message with no text part scores worse; some people genuinely prefer it.
"""
from __future__ import annotations

import html as _html

INK = "#1a1a1a"
MUTE = "#6b6b6b"
LINE = "#e4e2dd"
PAPER = "#faf9f7"
UP = "#1f5d45"
DOWN = "#8e2f2a"


def _esc(s) -> str:
    return _html.escape(str(s if s is not None else ""))


def rupees(v, *, signed=False) -> str:
    """Indian digit grouping: ₹12,34,567, not ₹1,234,567.

    A reader checks this against their broker app. Western grouping reads as
    an error even when the number is right.
    """
    if v is None:
        return "—"
    try:
        n = float(v)
    except (TypeError, ValueError):
        return "—"
    sign = "-" if n < 0 else ("+" if signed and n > 0 else "")
    n = abs(n)
    whole = int(round(n))
    s = str(whole)
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        s = ",".join(parts) + "," + tail
    return f"{sign}₹{s}"


def pct(v, *, signed=True) -> str:
    if v is None:
        return "—"
    try:
        n = float(v)
    except (TypeError, ValueError):
        return "—"
    return f"{'+' if signed and n > 0 else ''}{n:.2f}%"


def _tone(v) -> str:
    try:
        n = float(v)
    except (TypeError, ValueError):
        return MUTE
    return UP if n > 0 else (DOWN if n < 0 else MUTE)


def subject(digest: dict) -> str:
    """What shows in the inbox list, and the only thing most people read.

    The day's number goes first because that is the question being answered.
    A subject that says "Your daily portfolio digest" is one every reader can
    safely ignore for ever.
    """
    t = digest.get("totals") or {}
    move = t.get("day_change")
    p = t.get("day_change_pct")
    if move is None or p is None:
        return f"Your portfolio — {digest.get('date', '')}"
    word = "up" if move > 0 else ("down" if move < 0 else "flat")
    head = (f"Portfolio {word} {rupees(abs(move))} ({pct(abs(p), signed=False)})"
            if move else "Portfolio flat today")
    n = len(digest.get("events") or [])
    return f"{head}" + (f" · {n} filing{'s' if n != 1 else ''}" if n else "")


def _row_cells(r: dict) -> str:
    return (
        f'<tr>'
        f'<td style="padding:9px 0;border-bottom:1px solid {LINE};font:600 14px Georgia,serif;color:{INK}">{_esc(r["symbol"])}'
        f'<div style="font:400 11px Arial,sans-serif;color:{MUTE};padding-top:2px">{_esc(r["qty"])} × {rupees(r["price"])}</div></td>'
        f'<td align="right" style="padding:9px 0;border-bottom:1px solid {LINE};font:400 14px Arial,sans-serif;color:{INK}">{rupees(r["value"])}</td>'
        f'<td align="right" style="padding:9px 0;border-bottom:1px solid {LINE};font:600 13px Arial,sans-serif;color:{_tone(r.get("day_change"))};white-space:nowrap">'
        f'{rupees(r.get("day_change"), signed=True)}<div style="font:400 11px Arial,sans-serif;color:{_tone(r.get("day_change_pct"))};padding-top:2px">{pct(r.get("day_change_pct"))}</div></td>'
        f'</tr>'
    )


def render_html(digest: dict, *, site: str = "https://altahascreener.in",
                unsubscribe_url: str = "", name: str = "") -> str:
    t = digest.get("totals") or {}
    move, movepct = t.get("day_change"), t.get("day_change_pct")
    tone = _tone(move)

    # Headline. One number, large, with the percentage under it — the same
    # shape as the top of a stock page, so the email and the site agree.
    head = (
        f'<div style="font:400 12px Arial,sans-serif;color:{MUTE};letter-spacing:1.5px;'
        f'text-transform:uppercase">Today</div>'
        f'<div style="font:400 34px Georgia,serif;color:{tone};padding:6px 0 2px">'
        f'{rupees(move, signed=True)}</div>'
        f'<div style="font:400 14px Arial,sans-serif;color:{tone}">{pct(movepct)}'
    )
    if digest.get("index_change_pct") is not None:
        head += (f'<span style="color:{MUTE}"> · NIFTY {pct(digest["index_change_pct"])}</span>')
    head += "</div>"

    total_line = (
        f'<div style="font:400 13px Arial,sans-serif;color:{MUTE};padding-top:14px">'
        f'Portfolio value <b style="color:{INK}">{rupees(t.get("value"))}</b>'
    )
    if t.get("pnl") is not None:
        total_line += (f' · overall <b style="color:{_tone(t.get("pnl"))}">'
                       f'{rupees(t["pnl"], signed=True)} ({pct(t.get("pnl_pct"))})</b>')
    total_line += "</div>"

    # Events first when they exist: a filing is the only thing in here that
    # might need a decision today.
    events = ""
    for e in (digest.get("events") or [])[:5]:
        events += (
            f'<tr><td style="padding:8px 0;border-bottom:1px solid {LINE}">'
            f'<span style="font:600 13px Georgia,serif;color:{INK}">{_esc(e["symbol"])}</span> '
            f'<span style="font:400 11px Arial,sans-serif;color:{MUTE};text-transform:uppercase;'
            f'letter-spacing:0.6px">{_esc(e.get("category") or "filing")}</span>'
            f'<div style="font:400 13px Arial,sans-serif;color:{INK};padding-top:3px">{_esc(e.get("headline"))}</div>'
            + (f'<a href="{_esc(e["pdf"])}" style="font:400 12px Arial,sans-serif;color:{MUTE}">Open the filing →</a>'
               if e.get("pdf") else "")
            + "</td></tr>"
        )
    events_block = (
        f'<h2 style="font:400 17px Georgia,serif;color:{INK};margin:30px 0 4px">What was filed</h2>'
        f'<p style="font:400 12px Arial,sans-serif;color:{MUTE};margin:0 0 6px">'
        f'Straight from the exchange. Open the PDF for what the company actually said.</p>'
        f'<table width="100%" cellpadding="0" cellspacing="0">{events}</table>'
    ) if events else ""

    # Observations. Deliberately verdict-free — see digest.py.
    obs = ""
    for o in (digest.get("observations") or [])[:5]:
        obs += (f'<tr><td style="padding:6px 0;font:400 13px Arial,sans-serif;color:{INK}">'
                f'<b style="font-family:Georgia,serif">{_esc(o["symbol"])}</b> {_esc(o["line"])}</td></tr>')
    obs_block = (
        f'<h2 style="font:400 17px Georgia,serif;color:{INK};margin:30px 0 4px">Worth a look</h2>'
        f'<table width="100%" cellpadding="0" cellspacing="0">{obs}</table>'
        f'<p style="font:400 11px Arial,sans-serif;color:{MUTE};margin:8px 0 0">'
        f'Observations, not instructions. Each one is checkable on the chart.</p>'
    ) if obs else ""

    rows = "".join(_row_cells(r) for r in (digest.get("rows") or []))
    missing = digest.get("missing") or []
    missing_block = (
        f'<p style="font:400 12px Arial,sans-serif;color:{MUTE};padding-top:10px">'
        f'No price for {_esc(", ".join(m["symbol"] for m in missing))} today.</p>'
    ) if missing else ""

    greeting = (f'<p style="font:400 14px Arial,sans-serif;color:{INK};margin:0 0 18px">'
                f'{_esc(name)},</p>') if name else ""

    return f"""<!doctype html>
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_esc(subject(digest))}</title></head>
<body style="margin:0;padding:0;background:{PAPER}">
<span style="display:none;font-size:1px;color:{PAPER};max-height:0;overflow:hidden">
{_esc(subject(digest))} — {len(digest.get('rows') or [])} holdings, priced at today's close.
</span>
<table width="100%" cellpadding="0" cellspacing="0" style="background:{PAPER}">
<tr><td align="center" style="padding:24px 12px">
<table width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;background:#ffffff;border:1px solid {LINE}">
<tr><td style="padding:26px 28px">

<div style="font:400 11px Arial,sans-serif;color:{MUTE};letter-spacing:2px;text-transform:uppercase;padding-bottom:20px">
Altaha Screener · {_esc(digest.get("date", ""))}</div>

{greeting}
{head}
{total_line}

<h2 style="font:400 17px Georgia,serif;color:{INK};margin:30px 0 10px">Your holdings</h2>
<table width="100%" cellpadding="0" cellspacing="0">{rows}</table>
{missing_block}

{events_block}
{obs_block}

<div style="padding-top:28px">
<a href="{_esc(site)}" style="font:600 13px Arial,sans-serif;color:#ffffff;background:{INK};
padding:11px 18px;text-decoration:none;display:inline-block">Open the full report</a>
</div>

<p style="font:400 11px Arial,sans-serif;color:{MUTE};line-height:1.6;margin:26px 0 0;
border-top:1px solid {LINE};padding-top:16px">
Educational analysis only — scores and evidence, never a recommendation to buy or sell.
Prices are the exchange's closing prices for {_esc(digest.get("date", ""))} and can be revised.
{'<br><a href="' + _esc(unsubscribe_url) + '" style="color:' + MUTE + '">Stop these emails</a>' if unsubscribe_url else ''}
</p>

</td></tr></table>
</td></tr></table>
</body></html>"""


def render_text(digest: dict, *, site: str = "https://altahascreener.in",
                unsubscribe_url: str = "") -> str:
    t = digest.get("totals") or {}
    out = [f"ALTAHA SCREENER — {digest.get('date', '')}", ""]
    out.append(f"Today: {rupees(t.get('day_change'), signed=True)} ({pct(t.get('day_change_pct'))})")
    out.append(f"Portfolio value: {rupees(t.get('value'))}")
    if t.get("pnl") is not None:
        out.append(f"Overall: {rupees(t['pnl'], signed=True)} ({pct(t.get('pnl_pct'))})")
    out += ["", "YOUR HOLDINGS"]
    for r in digest.get("rows") or []:
        out.append(f"  {r['symbol']:<12} {rupees(r['value']):>12}   "
                   f"{rupees(r.get('day_change'), signed=True):>10} ({pct(r.get('day_change_pct'))})")
    if digest.get("events"):
        out += ["", "WHAT WAS FILED"]
        for e in digest["events"][:5]:
            out.append(f"  {e['symbol']} — {e.get('category') or 'filing'}: {e.get('headline')}")
            if e.get("pdf"):
                out.append(f"    {e['pdf']}")
    if digest.get("observations"):
        out += ["", "WORTH A LOOK (observations, not instructions)"]
        for o in digest["observations"][:5]:
            out.append(f"  {o['symbol']} {o['line']}")
    out += ["", f"Full report: {site}", "",
            "Educational analysis only — scores and evidence, never a "
            "recommendation to buy or sell."]
    if unsubscribe_url:
        out.append(f"Stop these emails: {unsubscribe_url}")
    return "\n".join(out)
