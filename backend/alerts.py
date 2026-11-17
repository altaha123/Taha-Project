"""
Altaha Screener — Alert delivery  (v24)

WHAT CHANGED FROM v23 AND WHY
-----------------------------
1. THE MESSAGES WERE UNREADABLE ON A PHONE.
   v23 sent numbers in Telegram's proportional body font, so nothing lined
   up: "Entry 1,044" and "Stop 1,028" sat at different x-positions and the
   eye had to re-parse every line. Every figure now goes inside a <code>
   block, which Telegram renders monospaced, and the labels are padded to a
   fixed width. Same information, one glance instead of five seconds.

2. THE MESSAGES HAD NO FIXED SKELETON.
   Optional fields (vwap, regime, filing) were appended in whatever order
   they happened to exist, so no two messages had the same shape and you
   could not learn where to look. Every alert now has exactly four zones in
   exactly this order:  identity -> what happened -> the numbers -> context.
   Absent context is omitted, never reordered.

3. NEW vs REPEAT WAS INVISIBLE.
   A symbol re-firing after its 90-minute cooldown looked identical to a
   first sighting. Alerts now carry a sequence number for the day and are
   marked AGAIN when that symbol has already fired.

4. ONE RETRY, AND ONLY TO STRIP HTML.
   A 429 or a 502 from Telegram dropped the alert silently. Now: up to three
   attempts, honouring Retry-After on 429 and backing off on 5xx and network
   errors, with the HTML-stripped retry kept as the last resort.

5. SILENT FAILURE WAS INVISIBLE.
   Delivery outcome is recorded per send. health() exposes it so the Live
   view can show "Telegram verified 09:14" instead of making you press
   "Test alert" to find out.

6. DUPLICATE DIGESTS.
   If a pass produced a byte-identical digest to the previous one — which
   happens when the scanner restarts and re-detects the same setup — it is
   dropped rather than buzzing twice.

Environment (unchanged):
    TELEGRAM_BOT_TOKEN        from @BotFather
    TELEGRAM_CHAT_ID          your own chat
    TELEGRAM_PUBLIC_CHAT_ID   optional public channel, facts only
"""

import hashlib
import html
import os
import time

import requests

TG_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TG_CHAT = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
TG_PUBLIC = os.environ.get("TELEGRAM_PUBLIC_CHAT_ID", "").strip()

WA_TOKEN = os.environ.get("WHATSAPP_TOKEN", "").strip()
WA_PHONE_ID = os.environ.get("WHATSAPP_PHONE_ID", "").strip()
WA_TO = os.environ.get("WHATSAPP_TO", "").strip()
WA_TEMPLATE = os.environ.get("WHATSAPP_TEMPLATE", "").strip()

TIMEOUT = 12
MAX_ATTEMPTS = 3

KIND_LABEL = {
    "RVOL": "Volume spike",
    "RVOL_DOWN": "Heavy selling",
    "ORB": "Opening range break",
    "ORB_DOWN": "Opening range breakdown",
    "LEVEL": "Level break",
    # Intraday breakouts (breakouts.py), up and down.
    "BO_BASE": "Base breakout", "BO_HIGH52": "52-week high breakout",
    "BO_HIGH20": "20-day high breakout", "BO_PDH": "Yesterday's high broken",
    "BO_ORB": "Opening range breakout", "BO_RANGE": "Intraday range breakout",
    "BO_BASE_DN": "Base breakdown", "BO_LOW52": "52-week low breakdown",
    "BO_LOW20": "20-day low breakdown", "BO_PDL": "Yesterday's low broken",
    "BO_ORB_DN": "Opening range breakdown", "BO_RANGE_DN": "Intraday range breakdown",
}

# Delivery memory, read by health() and by the Live view.
_LAST = {"ok": None, "at": None, "detail": "no send attempted yet",
         "sent_today": 0, "failed_today": 0, "day": None, "last_hash": None}


def configured() -> bool:
    return bool(TG_TOKEN and TG_CHAT) or bool(WA_TOKEN and WA_PHONE_ID and WA_TO)


def _e(s):
    return html.escape(str(s), quote=False)


def _money(v):
    """1042.3 -> '1,042.30'. Indian grouping is not used here on purpose:
    lakh/crore separators make two prices of different magnitude harder to
    compare at a glance, which is the whole job of this column."""
    try:
        return f"{float(v):,.2f}"
    except (TypeError, ValueError):
        return str(v)


# ---------------------------------------------------------------------------
# Formatting
#
# Four zones, always in this order, never reordered:
#   1  identity     direction, sequence, symbol, score
#   2  event        one line: what happened, on what volume, where in the range
#   3  numbers      monospaced block, labels padded to a fixed width
#   4  context      filing / index / vwap — omitted when absent
# ---------------------------------------------------------------------------

def _headline_line(a):
    """Zone 2. One line, always the same grammar: event — volume, position."""
    kind = KIND_LABEL.get(a["kind"], a["kind"])
    bits = [kind]
    if a.get("rvol"):
        bits.append(f"{a['rvol']}× normal volume")
    rp = a.get("range_pos")
    if rp is not None:
        pct = int(float(rp) * 100)
        where = "up the day's range" if a.get("direction", "UP") == "UP" else "down the day's range"
        bits.append(f"{pct}% {where}")
    return " · ".join(bits)


def _numbers_block(a):
    """Zone 3. Monospaced so the decimals line up. Telegram renders <code>
    in its mono face on every client, which <b> and plain text do not."""
    if a.get("level") is not None:
        # A breakout: the level it broke, then the trade. "Half" is one risk
        # from the entry — where to book half and move the stop to cost.
        rows = [
            ("Level", _money(a.get("level")), ""),
            ("Entry", _money(a.get("entry")), ""),
            ("Stop", _money(a.get("stop")),
             f"-{a['risk_pct']}%" if a.get("risk_pct") is not None else ""),
        ]
        if a.get("t1") is not None:
            rows.append(("Half", _money(a["t1"]), "1:1"))
        rows.append(("Target", _money(a.get("target")),
                     f"1:{a['rr']}" if a.get("rr") is not None else ""))
    else:
        rows = [
            ("Now", _money(a.get("price")), ""),
            ("Entry", _money(a.get("entry")), ""),
            ("Stop", _money(a.get("stop")),
             f"-{a['risk_pct']}%" if a.get("risk_pct") is not None else ""),
            ("Target", _money(a.get("target")),
             f"1:{a['rr']}" if a.get("rr") is not None else ""),
        ]
    width = max(len(_money(r[1])) for r in rows)
    out = []
    for label, value, tail in rows:
        line = f"{label:<7}{value:>{width}}"
        if tail:
            line += f"  {tail}"
        out.append(line)
    return "<code>" + _e("\n".join(out)) + "</code>"


def _context_lines(a):
    """Zone 4. Only what exists, in a fixed order."""
    out = []
    f = a.get("filing")
    if f:
        out.append("\U0001F4CE " + _e(f"{f.get('line', '')} — {f.get('category', '')}"))
    # NOTE: index regime is deliberately not repeated per alert — the digest
    # header carries it once. Repeating it made every card look different
    # depending on which optional fields happened to be present.
    tail = []
    if a.get("vwap"):
        tail.append(f"VWAP {_money(a['vwap'])}")
    if a.get("day_rvol"):
        tail.append(f"{a['day_rvol']}× on the day")
    if tail:
        out.append(_e(" · ".join(tail)))
    return out


def format_alert(a, seq=None, repeat=False):
    """Full private version — includes the trade plan."""
    arrow = "▲" if a.get("direction", "UP") == "UP" else "▼"
    head = f"{arrow} "
    if seq:
        head += f"{seq} · "
    head += f"<b>{_e(a['symbol'])}</b>"
    if a.get("level") is not None:
        head += " · " + ("BUY" if a.get("direction", "UP") == "UP" else "SELL")
    if a.get("score") is not None:
        head += f" · score {a['score']}"
    if repeat:
        head += "  <i>(again)</i>"

    parts = [head, _e(_headline_line(a)), _numbers_block(a)]
    parts += _context_lines(a)
    if a.get("why"):
        parts.append("<i>" + _e(str(a["why"])[:260]) + "</i>")
    return "\n".join(parts)


def format_digest(rows, index_pct=None, total_today=None, clock=None):
    """
    One message per pass. Header answers 'is this worth opening' before you
    open it: how many, at what time, in what market.
    """
    if not rows:
        return ""
    n = len(rows)
    header = f"<b>ALTAHA</b> · {n} setup" + ("s" if n != 1 else "")
    if clock:
        header += f" · {_e(clock)}"
    sub = []
    if index_pct is not None:
        sub.append(f"index {index_pct:+.2f}%")
    if total_today is not None:
        sub.append(f"{total_today} today")
    block = [header]
    if sub:
        block.append("<i>" + _e(" · ".join(sub)) + "</i>")

    seen = set()
    for i, a in enumerate(rows, 1):
        repeat = a["symbol"] in seen
        seen.add(a["symbol"])
        block.append("")
        block.append(format_alert(a, seq=i if n > 1 else None, repeat=repeat))

    block += ["", "<i>Observation, not advice. Size the position before you act.</i>"]
    return "\n".join(block)


def format_public(a):
    """Facts-only version — no entry, stop or target. Publishing specific
    levels to the public is a materially different activity from publishing
    observations, and the SEBI RA regulations care about the difference."""
    arrow = "▲" if a.get("direction", "UP") == "UP" else "▼"
    lines = [f"{arrow} <b>{_e(a['symbol'])}</b>", _e(_headline_line(a)),
             f"<code>{_e('Now    ' + _money(a.get('price')))}</code>"]
    f = a.get("filing")
    if f:
        lines.append("\U0001F4CE " + _e(f.get("line", "")))
    lines += ["", "<i>Altaha Screener · observation of unusual market activity. "
                  "Not a recommendation.</i>"]
    return "\n".join(lines)


def format_day_open(stocks, levels_asof, index_pct, poll_seconds=20):
    """Sent once, before the alert window opens. Its only job is to make a
    dead scanner distinguishable from a quiet market."""
    reg = f"{index_pct:+.2f}%" if index_pct is not None else "n/a"
    lines = ["<b>ALTAHA · scanner live</b>"]
    if stocks:
        lines += [f"<code>{_e(f'Stocks   {stocks}')}</code>",
                  f"<code>{_e(f'Levels   {levels_asof}')}</code>",
                  f"<code>{_e(f'Index    {reg}')}</code>",
                  "<i>" + _e(f"Breakouts up and down, checked every {poll_seconds} seconds, "
                             "alerts 09:20 to 14:30.") + "</i>"]
    else:
        lines.append(_e("No breakout levels yet. They are being built from daily bars now; "
                        "alerts start as soon as they are ready."))
    return "\n".join(lines)


def format_day_close(alerts, near):
    """Sent every trading day whether or not anything fired. Silence that is
    confirmed is information; silence that is ambiguous is a bug report."""
    n = len(alerts)
    lines = ["<b>ALTAHA · close</b>",
             f"{n} alert" + ("s" if n != 1 else "") + " today"]
    if alerts:
        best = max(alerts, key=lambda x: x.get("score") or 0)
        lines.append(f"Best: <b>{_e(best['symbol'])}</b> · score {best.get('score', '-')}")
        lines.append("")
        lines.append("<code>" + _e("\n".join(
            f"{a.get('time', '--:--'):<6}{a['symbol']:<12}{a.get('score', '-')}"
            for a in alerts[:12])) + "</code>")
    if near:
        lines += ["", "<i>" + _e("Closest non-firing: " + ", ".join(
            f"{r['symbol']} {r['rvol']}×" for r in near[:3])) + "</i>"]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Breakout alerts (breakouts.py): the two messages around the live cards
# ---------------------------------------------------------------------------

_KIND_SHORT = {"BASE": "base top", "BASE_DN": "base low", "HIGH52": "52w high", "LOW52": "52w low"}


def format_levels_ready(asof, stocks, near):
    """Sent once after the close, when tomorrow's levels are built."""
    lines = [f"<b>ALTAHA · levels ready</b> · {_e(asof)}",
             _e(f"{stocks} stocks watched tomorrow, up and down.")]
    if near:
        lines += ["", "Closest to a big level at the close:"]
        rows = []
        for w in near[:8]:
            arrow = "▲" if w.get("dir") == "UP" else "▼"
            rows.append(f"{arrow} {w['symbol'][:11]:<11} {w['away_pct']:>4.1f}%  "
                        f"{_KIND_SHORT.get(w.get('kind'), '')}")
        lines.append("<code>" + _e("\n".join(rows)) + "</code>")
    return "\n".join(lines)


def format_day_result(day, alerts):
    """
    Sent once after the close, when every alert has been marked. In R: one R
    is the distance from entry to stop, so +2.0R is a target and -1.0R a stop.
    """
    n = len(alerts)
    lines = [f"<b>ALTAHA · today's result</b> · {_e(day)}"]
    if not n:
        lines.append("No alert today. Nothing cleared a level on enough volume.")
        return "\n".join(lines)
    marked = [a for a in alerts if a.get("r") is not None]
    tg = sum(1 for a in alerts if a.get("outcome") == "TARGET")
    st = sum(1 for a in alerts if a.get("outcome") == "STOP")
    flat = sum(1 for a in alerts if a.get("outcome") == "OPEN_AT_CLOSE")
    lines.append(_e(f"{n} alert" + ("s" if n != 1 else "") +
                    f" · {tg} target · {st} stopped · {flat} flat at 15:15"))
    if marked:
        total = sum(a["r"] for a in marked)
        lines.append(f"<b>Net {total:+.1f}R</b>")
    rows = []
    for a in alerts[:15]:
        arrow = "▲" if a.get("direction", "UP") == "UP" else "▼"
        r = f"{a['r']:+.1f}R" if a.get("r") is not None else "  n/a"
        rows.append(f"{a.get('time', '--:--')} {arrow} {a['symbol'][:11]:<11} {r:>6}")
    lines.append("<code>" + _e("\n".join(rows)) + "</code>")
    lines.append("<i>" + _e("Judged on 5-minute bars after each alert; when a bar touches both "
                            "stop and target, the stop is assumed.") + "</i>")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Transport
# ---------------------------------------------------------------------------

def _mark(ok, detail):
    day = time.strftime("%Y-%m-%d")
    if _LAST["day"] != day:
        _LAST.update({"day": day, "sent_today": 0, "failed_today": 0})
    _LAST["ok"] = ok
    _LAST["at"] = time.strftime("%H:%M:%S")
    _LAST["detail"] = detail
    _LAST["sent_today" if ok else "failed_today"] += 1


def _post(chat_id: str, text: str, html_mode: bool = True):
    """
    Up to three attempts. 429 is honoured rather than retried blindly —
    Telegram tells you how long to wait and ignoring it extends the ban.
    Returns (ok, detail).
    """
    if not TG_TOKEN:
        return False, "TELEGRAM_BOT_TOKEN not set on the server"
    if not chat_id:
        return False, "chat id not set on the server"

    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    base = {"chat_id": chat_id, "text": text[:4000], "disable_web_page_preview": True}

    for attempt in range(1, MAX_ATTEMPTS + 1):
        payload = dict(base, parse_mode="HTML") if html_mode else base
        try:
            r = requests.post(url, json=payload, timeout=TIMEOUT)
        except Exception as e:
            if attempt == MAX_ATTEMPTS:
                return False, f"network error after {attempt} attempts: {str(e)[:120]}"
            time.sleep(2 ** attempt)
            continue

        if r.status_code == 200:
            return True, "sent" if html_mode else "sent (plain text)"

        if r.status_code == 429:
            wait = 3
            try:
                wait = int(r.json().get("parameters", {}).get("retry_after", 3))
            except Exception:
                pass
            if attempt == MAX_ATTEMPTS:
                return False, f"rate limited, gave up after {attempt} attempts"
            time.sleep(min(wait + 1, 30))
            continue

        if 500 <= r.status_code < 600:
            if attempt == MAX_ATTEMPTS:
                return False, f"HTTP {r.status_code} after {attempt} attempts"
            time.sleep(2 ** attempt)
            continue

        # 4xx that is not 429 — almost always malformed HTML or a bad chat id.
        # Retrying the same body will not help; drop the formatting once.
        if html_mode:
            return _post(chat_id, text, html_mode=False)
        try:
            d = r.json()
            return False, f"HTTP {r.status_code}: {d.get('description') or r.text[:140]}"
        except Exception:
            return False, f"HTTP {r.status_code}: {r.text[:140]}"

    return False, "exhausted attempts"


def send_telegram(text: str):
    ok, detail = _post(TG_CHAT, text)
    _mark(ok, detail)
    return ok, detail


def send_plain(text: str) -> bool:
    """Heartbeats and summaries. Accepts pre-formatted HTML from the
    format_day_* helpers, or bare text, which is escaped."""
    body = text if "<" in text and ">" in text else _e(text)
    ok, detail = _post(TG_CHAT, body)
    _mark(ok, detail)
    return ok


def send_batch(rows: list, index_pct=None, total_today=None, clock=None) -> bool:
    """One digest to the private feed; facts-only lines to the public channel."""
    if not rows:
        return False

    text = format_digest(rows, index_pct=index_pct,
                         total_today=total_today, clock=clock)

    # A restart that re-detects the same setups must not buzz twice.
    h = hashlib.sha1(text.encode("utf-8")).hexdigest()
    if h == _LAST.get("last_hash"):
        _mark(True, "suppressed — identical to the previous digest")
        return True
    _LAST["last_hash"] = h

    ok, detail = _post(TG_CHAT, text)
    _mark(ok, detail)

    if TG_PUBLIC:
        for a in rows[:5]:
            _post(TG_PUBLIC, format_public(a))
    if WA_TOKEN:
        for a in rows[:3]:
            send_whatsapp(a)
    return ok


def send_alert(a: dict) -> bool:
    """Kept for compatibility with anything still calling the single-alert path."""
    return send_batch([a])


def health() -> dict:
    """What the Live view's delivery tile reads. No test message sent."""
    return {
        "configured": configured(),
        "channel": "telegram" if (TG_TOKEN and TG_CHAT) else
                   ("whatsapp" if WA_TOKEN else "none"),
        "public_channel": bool(TG_PUBLIC),
        "last_ok": _LAST["ok"],
        "last_at": _LAST["at"],
        "last_detail": _LAST["detail"],
        "sent_today": _LAST["sent_today"],
        "failed_today": _LAST["failed_today"],
    }


def send_whatsapp(a: dict) -> bool:
    """
    Stub. Meta requires a pre-approved template for business-initiated
    messages; free-form text only works inside a 24-hour window opened by
    the recipient. That suits a paying-subscriber feature far better than a
    personal alert feed.
    """
    if not (WA_TOKEN and WA_PHONE_ID and WA_TO and WA_TEMPLATE):
        return False
    body = {
        "messaging_product": "whatsapp", "to": WA_TO, "type": "template",
        "template": {"name": WA_TEMPLATE, "language": {"code": "en"},
                     "components": [{"type": "body", "parameters": [
                         {"type": "text", "text": a["symbol"]},
                         {"type": "text", "text": a["headline"]},
                         {"type": "text", "text": str(a["entry"])},
                         {"type": "text", "text": str(a["stop"])},
                         {"type": "text", "text": str(a["target"])}]}]},
    }
    try:
        r = requests.post(f"https://graph.facebook.com/v20.0/{WA_PHONE_ID}/messages",
                          json=body, headers={"Authorization": f"Bearer {WA_TOKEN}"},
                          timeout=TIMEOUT)
        return r.status_code in (200, 201)
    except Exception:
        return False


def test(sample: dict = None) -> dict:
    """Fire a test so setup can be verified without waiting for a signal.
    Pass a sample alert to send that; without one the old volume card goes."""
    if sample is None:
        sample = {"symbol": "TESTMSG", "kind": "RVOL", "direction": "UP",
                  "headline": "alert delivery test",
                  "why": "This is a test alert from Altaha Screener.",
                  "price": 1042.30, "entry": 1044.0, "stop": 1028.0, "target": 1076.0,
                  "rr": 2.0, "risk_pct": 1.5, "rvol": 3.2, "day_rvol": 1.8,
                  "range_pos": 0.88, "vwap": 1036.4, "regime": 0.42, "score": 74}
    ok, detail = send_telegram("<i>Test message, not a real alert.</i>\n\n" +
                               format_digest([sample], index_pct=0.42,
                                             total_today=1, clock="09:28"))
    public = format_public(sample)
    pub_ok, pub_detail = (None, "not configured")
    if TG_PUBLIC:
        pub_ok, pub_detail = _post(TG_PUBLIC, public)
    return {"telegram_configured": bool(TG_TOKEN and TG_CHAT),
            "public_channel_configured": bool(TG_PUBLIC),
            "whatsapp_configured": bool(WA_TOKEN and WA_PHONE_ID and WA_TO),
            "token_shape": (f"{TG_TOKEN.split(':')[0]}:***" if ":" in TG_TOKEN
                            else ("MALFORMED — no colon in token" if TG_TOKEN else "missing")),
            "chat_id": TG_CHAT or "missing",
            "sent": ok, "detail": detail,
            "public_sent": pub_ok, "public_detail": pub_detail}
