"""
Altaha Screener — Alert delivery

Telegram by default: free, instant, no template approval, and set up in
about five minutes. Set two environment variables on Render:

    TELEGRAM_BOT_TOKEN   from @BotFather
    TELEGRAM_CHAT_ID     from https://api.telegram.org/bot<TOKEN>/getUpdates
                         after you message your own bot once

A WhatsApp adapter is stubbed below. It is deliberately NOT the default:
business-initiated WhatsApp messages need pre-approved templates and are
billed per message, which suits a paying-subscriber feature far better
than a personal alert feed.
"""

import os

import requests

TG_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TG_CHAT = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

WA_TOKEN = os.environ.get("WHATSAPP_TOKEN", "").strip()
WA_PHONE_ID = os.environ.get("WHATSAPP_PHONE_ID", "").strip()
WA_TO = os.environ.get("WHATSAPP_TO", "").strip()
WA_TEMPLATE = os.environ.get("WHATSAPP_TEMPLATE", "").strip()


def configured() -> bool:
    return bool(TG_TOKEN and TG_CHAT) or bool(WA_TOKEN and WA_PHONE_ID and WA_TO)


def format_alert(a: dict) -> str:
    kind = {"RVOL": "VOLUME SPIKE", "ORB": "OPENING RANGE BREAK",
            "LEVEL": "LEVEL BREAK"}.get(a["kind"], a["kind"])
    lines = [
        f"*{a['symbol']}*  —  {kind}",
        f"{a['headline']}",
        "",
        f"Price   ₹{a['price']:,}",
        f"Entry   ₹{a['entry']:,}",
        f"Stop    ₹{a['stop']:,}  (−{a['risk_pct']}%)",
        f"Target  ₹{a['target']:,}" + (f"   R:R 1:{a['rr']}" if a.get("rr") else ""),
        f"RVOL    {a['rvol']}×",
        "",
        a["why"],
        "",
        "_Not advice. Position size before you act._",
    ]
    return "\n".join(lines)


def send_telegram(text: str) -> bool:
    if not (TG_TOKEN and TG_CHAT):
        return False
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            json={"chat_id": TG_CHAT, "text": text, "parse_mode": "Markdown",
                  "disable_web_page_preview": True},
            timeout=12)
        return r.status_code == 200
    except Exception:
        return False


def send_whatsapp(a: dict) -> bool:
    """
    Stub for later. Meta requires a pre-approved template for
    business-initiated messages; free-form text only works inside a
    24-hour window opened by the recipient. Fill in template params
    to match whatever template you get approved.
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


def send_alert(a: dict) -> bool:
    ok = send_telegram(format_alert(a))
    if WA_TOKEN:
        send_whatsapp(a)
    return ok


def test() -> dict:
    """Fire a test message so setup can be verified without waiting for a signal."""
    sample = {"symbol": "TESTMSG", "kind": "RVOL",
              "headline": "alert delivery test — if you can read this, it works",
              "price": 1000.0, "entry": 1000.0, "stop": 975.0, "target": 1050.0,
              "rr": 2.0, "risk_pct": 2.5, "rvol": 3.2,
              "why": "This is a test alert from Altaha Screener."}
    return {"telegram_configured": bool(TG_TOKEN and TG_CHAT),
            "whatsapp_configured": bool(WA_TOKEN and WA_PHONE_ID and WA_TO),
            "sent": send_alert(sample)}
