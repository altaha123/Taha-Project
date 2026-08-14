"""
Altaha Screener — Alert delivery  (v23)

Telegram by default: free, instant, no template approval, five-minute setup.
Two environment variables on Render:

    TELEGRAM_BOT_TOKEN   from @BotFather
    TELEGRAM_CHAT_ID     from https://api.telegram.org/bot<TOKEN>/getUpdates
                         after you message your own bot once

Optionally TELEGRAM_PUBLIC_CHAT_ID — a second destination (a public channel)
that receives a facts-only version: what happened, on what volume, at what
price. No entry, no stop, no target. Publishing specific entry/stop/target
levels to the public is a materially different activity from publishing
observations, and the SEBI Research Analyst regulations care about that
difference. Keeping the trade plan on the private feed keeps the public
channel to reporting.

WHAT CHANGED FROM v22
  · send_batch() sends ONE ranked digest per pass instead of one message per
    alert. Six separate buzzes in a minute is how a person learns to ignore
    the notification.
  · HTML parse mode with escaping. Markdown broke on any symbol containing
    an underscore, and the retry silently dropped the formatting.
  · send_plain() for heartbeats and end-of-day summaries.
"""

import html
import os

import requests

TG_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TG_CHAT = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
TG_PUBLIC = os.environ.get("TELEGRAM_PUBLIC_CHAT_ID", "").strip()

WA_TOKEN = os.environ.get("WHATSAPP_TOKEN", "").strip()
WA_PHONE_ID = os.environ.get("WHATSAPP_PHONE_ID", "").strip()
WA_TO = os.environ.get("WHATSAPP_TO", "").strip()
WA_TEMPLATE = os.environ.get("WHATSAPP_TEMPLATE", "").strip()

KIND_LABEL = {
    "RVOL": "VOLUME SPIKE",
    "RVOL_DOWN": "HEAVY SELLING",
    "ORB": "OPENING RANGE BREAK",
    "ORB_DOWN": "OPENING RANGE BREAKDOWN",
    "LEVEL": "LEVEL BREAK",
}


def configured() -> bool:
    return bool(TG_TOKEN and TG_CHAT) or bool(WA_TOKEN and WA_PHONE_ID and WA_TO)


def _e(s):
    return html.escape(str(s), quote=False)


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

def format_alert(a: dict) -> str:
    """Full private version — includes the trade plan."""
    kind = KIND_LABEL.get(a["kind"], a["kind"])
    arrow = "▲" if a.get("direction", "UP") == "UP" else "▼"
    lines = [
        f"{arrow} <b>{_e(a['symbol'])}</b> — {_e(kind)}  <i>score {a.get('score', '-')}</i>",
        _e(a["headline"]),
        "",
        f"Price   ₹{a['price']:,}",
        f"Entry   ₹{a['entry']:,}",
        f"Stop    ₹{a['stop']:,}  (risk {a['risk_pct']}%)",
        f"Target  ₹{a['target']:,}  (R:R 1:{a.get('rr', '-')})",
        f"RVOL    {a['rvol']}x now"
        + (f", {a['day_rvol']}x on the day" if a.get("day_rvol") else ""),
    ]
    if a.get("vwap"):
        lines.append(f"VWAP    ₹{a['vwap']:,}")
    if a.get("regime") is not None:
        lines.append(f"Index   {a['regime']:+.2f}%")
    lines += ["", _e(a["why"]), "",
              "<i>Observation, not advice. Size the position before you act.</i>"]
    return "\n".join(lines)


def format_public(a: dict) -> str:
    """Facts-only version — no entry, stop or target."""
    kind = KIND_LABEL.get(a["kind"], a["kind"])
    arrow = "▲" if a.get("direction", "UP") == "UP" else "▼"
    return "\n".join([
        f"{arrow} <b>{_e(a['symbol'])}</b> — {_e(kind)}",
        f"₹{a['price']:,} · {a['rvol']}x normal volume · "
        f"{int(float(a.get('range_pos', 0)) * 100)}% up the day's range",
        "",
        _e(a["why"]),
        "",
        "<i>Altaha Screener. Observation of unusual market activity. "
        "Not a recommendation.</i>",
    ])


def format_digest(rows: list) -> str:
    """One message for several alerts, best first."""
    if len(rows) == 1:
        return format_alert(rows[0])
    head = f"<b>{len(rows)} setups</b> — best first"
    body = []
    for a in rows:
        arrow = "▲" if a.get("direction", "UP") == "UP" else "▼"
        body.append(
            f"\n{arrow} <b>{_e(a['symbol'])}</b> ({a.get('score', '-')}) "
            f"{_e(KIND_LABEL.get(a['kind'], a['kind']))}\n"
            f"₹{a['price']:,} · {a['rvol']}x vol · entry {a['entry']:,} / "
            f"stop {a['stop']:,} / target {a['target']:,} · "
            f"risk {a['risk_pct']}% · R:R 1:{a.get('rr', '-')}\n"
            f"{_e(a['headline'])}")
    tail = "\n<i>Observations, not advice. Size before you act.</i>"
    return head + "".join(body) + "\n" + tail


# ---------------------------------------------------------------------------
# Transport
# ---------------------------------------------------------------------------

def _post(chat_id: str, text: str):
    """Returns (ok, detail). Detail carries Telegram's own error message."""
    if not TG_TOKEN:
        return False, "TELEGRAM_BOT_TOKEN not set on the server"
    if not chat_id:
        return False, "chat id not set on the server"
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text[:4000],
               "disable_web_page_preview": True}
    try:
        r = requests.post(url, json=dict(payload, parse_mode="HTML"), timeout=12)
        if r.status_code == 200:
            return True, "sent"
        # Retry unformatted — formatting is not worth losing the alert over.
        r2 = requests.post(url, json=payload, timeout=12)
        if r2.status_code == 200:
            return True, "sent (plain text — HTML was rejected)"
        try:
            d = r2.json()
            detail = f"HTTP {r2.status_code}: {d.get('description') or r2.text[:160]}"
        except Exception:
            detail = f"HTTP {r2.status_code}: {r2.text[:160]}"
        return False, detail
    except Exception as e:
        return False, f"network error: {str(e)[:160]}"


def send_telegram(text: str):
    return _post(TG_CHAT, text)


def send_plain(text: str) -> bool:
    """Heartbeats, warm-up notices, end-of-day summaries."""
    ok, _ = _post(TG_CHAT, _e(text))
    return ok


def send_batch(rows: list) -> bool:
    """One digest to the private feed; facts-only lines to the public channel."""
    if not rows:
        return False
    ok, _ = _post(TG_CHAT, format_digest(rows))
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


def send_whatsapp(a: dict) -> bool:
    """
    Stub. Meta requires a pre-approved template for business-initiated
    messages; free-form text only works inside a 24-hour window opened by the
    recipient. This suits a paying-subscriber feature far better than a
    personal alert feed.
    """
    if not (WA_TOKEN and WA_PHONE_ID and WA_TO and WA_TEMPLATE):
        return False
    body = {
        "messaging_product": "whatsapp",
        "to": WA_TO,
        "type": "template",
        "template": {
            "name": WA_TEMPLATE,
            "language": {"code": "en"},
            "components": [{
                "type": "body",
                "parameters": [
                    {"type": "text", "text": a["symbol"]},
                    {"type": "text", "text": a["headline"]},
                    {"type": "text", "text": str(a["entry"])},
                    {"type": "text", "text": str(a["stop"])},
                    {"type": "text", "text": str(a["target"])},
                ],
            }],
        },
    }
    try:
        r = requests.post(f"https://graph.facebook.com/v20.0/{WA_PHONE_ID}/messages",
                          json=body, headers={"Authorization": f"Bearer {WA_TOKEN}"},
                          timeout=12)
        return r.status_code in (200, 201)
    except Exception:
        return False


def test() -> dict:
    """Fire a test message so setup can be verified without waiting for a signal."""
    sample = {"symbol": "TESTMSG", "kind": "RVOL", "direction": "UP",
              "headline": "alert delivery test — if you can read this, it works",
              "price": 1000.0, "entry": 1000.0, "stop": 985.0, "target": 1030.0,
              "rr": 2.0, "risk_pct": 1.5, "rvol": 3.2, "day_rvol": 1.8,
              "range_pos": 0.88, "vwap": 996.0, "regime": 0.42, "score": 74,
              "why": "This is a test alert from Altaha Screener."}
    ok, detail = send_telegram(format_alert(sample))
    pub_ok, pub_detail = (None, "not configured")
    if TG_PUBLIC:
        pub_ok, pub_detail = _post(TG_PUBLIC, format_public(sample))
    return {"telegram_configured": bool(TG_TOKEN and TG_CHAT),
            "public_channel_configured": bool(TG_PUBLIC),
            "whatsapp_configured": bool(WA_TOKEN and WA_PHONE_ID and WA_TO),
            "token_shape": (f"{TG_TOKEN.split(':')[0]}:***" if ":" in TG_TOKEN
                            else ("MALFORMED — no colon in token" if TG_TOKEN else "missing")),
            "chat_id": TG_CHAT or "missing",
            "sent": ok, "detail": detail,
            "public_sent": pub_ok, "public_detail": pub_detail}
