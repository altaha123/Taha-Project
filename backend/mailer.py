"""
Sending email, without marrying a provider.

One function, send(), and four transports behind it. Which one runs is an
environment variable, so choosing Resend over Brevo — or moving off both after
the free tier runs out — is a dashboard change and not a code change. The
pattern is the one SENTRY_DSN already uses here: unconfigured means inert,
never broken.

    EMAIL_PROVIDER   resend | brevo | smtp | console   (default: console)
    EMAIL_FROM       "Altaha Screener <hello@altahascreener.in>"
    EMAIL_REPLY_TO   optional

    resend:  RESEND_API_KEY
    brevo:   BREVO_API_KEY
    smtp:    SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, SMTP_TLS

CONSOLE IS NOT A STUB
With nothing configured, send() prints the message and reports success. That
is what makes the whole login flow runnable and testable before a provider
exists, and on this project it also means a deploy that loses its mail
credentials degrades to "logged, not sent" rather than to a 500 on the login
page.

DELIVERABILITY IS DNS, NOT CODE
None of this matters if the domain cannot vouch for the sender. SPF, DKIM and
a DMARC record on altahascreener.in are what decide whether these land in the
inbox or the spam folder, and no library can substitute for them. Whichever
provider is chosen, do its DNS step first.
"""
from __future__ import annotations

import os
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, parseaddr

import requests

TIMEOUT = 15


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def provider() -> str:
    p = _env("EMAIL_PROVIDER", "console").lower()
    return p if p in ("resend", "brevo", "smtp", "console") else "console"


def sender() -> tuple:
    """(name, address). Falls back to something obviously local rather than
    guessing a real address it has no right to send from."""
    raw = _env("EMAIL_FROM") or "Altaha Screener <no-reply@altahascreener.in>"
    name, addr = parseaddr(raw)
    return (name or "Altaha Screener", addr or "no-reply@altahascreener.in")


def configured() -> bool:
    p = provider()
    if p == "resend":
        return bool(_env("RESEND_API_KEY"))
    if p == "brevo":
        return bool(_env("BREVO_API_KEY"))
    if p == "smtp":
        return bool(_env("SMTP_HOST"))
    return True                      # console always "works"


def status() -> dict:
    name, addr = sender()
    return {"provider": provider(), "configured": configured(),
            "from": formataddr((name, addr)),
            "note": ("Nothing is being delivered — set EMAIL_PROVIDER and its key."
                     if provider() == "console" else
                     "Deliverability depends on SPF/DKIM/DMARC for the sending domain.")}


# ---------------------------------------------------------------------------
# Transports
# ---------------------------------------------------------------------------

def _send_resend(to: str, subject: str, html: str, text: str, headers: dict) -> tuple:
    name, addr = sender()
    body = {"from": formataddr((name, addr)), "to": [to], "subject": subject,
            "html": html, "text": text}
    if _env("EMAIL_REPLY_TO"):
        body["reply_to"] = _env("EMAIL_REPLY_TO")
    if headers:
        body["headers"] = headers
    r = requests.post("https://api.resend.com/emails", json=body, timeout=TIMEOUT,
                      headers={"Authorization": f"Bearer {_env('RESEND_API_KEY')}"})
    return (r.status_code in (200, 201), f"resend {r.status_code}: {r.text[:180]}")


def _send_brevo(to: str, subject: str, html: str, text: str, headers: dict) -> tuple:
    name, addr = sender()
    body = {"sender": {"name": name, "email": addr}, "to": [{"email": to}],
            "subject": subject, "htmlContent": html, "textContent": text}
    if _env("EMAIL_REPLY_TO"):
        body["replyTo"] = {"email": _env("EMAIL_REPLY_TO")}
    if headers:
        body["headers"] = headers
    r = requests.post("https://api.brevo.com/v3/smtp/email", json=body, timeout=TIMEOUT,
                      headers={"api-key": _env("BREVO_API_KEY"),
                               "content-type": "application/json"})
    return (r.status_code in (200, 201, 202), f"brevo {r.status_code}: {r.text[:180]}")


def _send_smtp(to: str, subject: str, html: str, text: str, headers: dict) -> tuple:
    name, addr = sender()
    msg = EmailMessage()
    msg["From"] = formataddr((name, addr))
    msg["To"] = to
    msg["Subject"] = subject
    if _env("EMAIL_REPLY_TO"):
        msg["Reply-To"] = _env("EMAIL_REPLY_TO")
    for k, v in (headers or {}).items():
        msg[k] = v
    msg.set_content(text or " ")
    msg.add_alternative(html, subtype="html")

    host, port = _env("SMTP_HOST"), int(_env("SMTP_PORT", "587") or 587)
    user, pw = _env("SMTP_USER"), _env("SMTP_PASS")
    use_tls = _env("SMTP_TLS", "1") not in ("0", "false", "no")
    with smtplib.SMTP(host, port, timeout=TIMEOUT) as s:
        if use_tls:
            s.starttls(context=ssl.create_default_context())
        if user:
            s.login(user, pw)
        s.send_message(msg)
    return (True, f"smtp {host}:{port}")


def _send_console(to: str, subject: str, html: str, text: str, headers: dict) -> tuple:
    print(f"\n[email → {to}] {subject}\n{'-' * 60}\n{text}\n{'-' * 60}\n", flush=True)
    return (True, "console (not delivered)")


_TRANSPORTS = {"resend": _send_resend, "brevo": _send_brevo,
               "smtp": _send_smtp, "console": _send_console}


def send(to: str, subject: str, html: str, text: str = "",
         unsubscribe_url: str = "") -> tuple:
    """(ok, detail). Never raises — a failed send is a logged failure, not a
    500 on somebody's login page.

    List-Unsubscribe is set whenever an unsubscribe URL is given. Gmail and
    Yahoo require a one-click unsubscribe for bulk senders, and a mailbox
    provider that cannot find one is markedly more willing to believe the
    recipient who presses "spam".
    """
    if not to or "@" not in to:
        return (False, "no recipient")
    headers = {}
    if unsubscribe_url:
        headers["List-Unsubscribe"] = f"<{unsubscribe_url}>"
        headers["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
    fn = _TRANSPORTS.get(provider(), _send_console)
    try:
        return fn(to, subject, html, text or "", headers)
    except Exception as e:
        return (False, f"{type(e).__name__}: {str(e)[:180]}")


# ---------------------------------------------------------------------------
# The login email
# ---------------------------------------------------------------------------

def login_email(link: str, *, minutes: int = 15) -> tuple:
    """(subject, html, text).

    Short, plain, and it says what to do if the reader did not ask for it —
    which is the difference between a stranger shrugging and a stranger
    reporting the message as phishing.
    """
    subject = "Your Altaha Screener sign-in link"
    html = f"""<!doctype html><html><body style="margin:0;background:#faf9f7">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#faf9f7">
<tr><td align="center" style="padding:28px 12px">
<table width="480" cellpadding="0" cellspacing="0" style="max-width:480px;width:100%;
background:#fff;border:1px solid #e4e2dd">
<tr><td style="padding:30px 28px">
<div style="font:400 11px Arial,sans-serif;color:#6b6b6b;letter-spacing:2px;
text-transform:uppercase;padding-bottom:22px">Altaha Screener</div>
<p style="font:400 15px Arial,sans-serif;color:#1a1a1a;margin:0 0 22px">
Here is your sign-in link. It works once, and it expires in {minutes} minutes.</p>
<a href="{link}" style="font:600 14px Arial,sans-serif;color:#fff;background:#1a1a1a;
padding:13px 22px;text-decoration:none;display:inline-block">Sign in</a>
<p style="font:400 12px Arial,sans-serif;color:#6b6b6b;margin:22px 0 0;line-height:1.6">
If the button does not work, paste this into your browser:<br>
<span style="color:#1a1a1a;word-break:break-all">{link}</span></p>
<p style="font:400 12px Arial,sans-serif;color:#6b6b6b;margin:22px 0 0;
border-top:1px solid #e4e2dd;padding-top:16px;line-height:1.6">
If you did not ask to sign in, you can ignore this email — nothing happens
until the link is opened, and it stops working shortly.</p>
</td></tr></table></td></tr></table></body></html>"""
    text = (f"Your Altaha Screener sign-in link\n\n{link}\n\n"
            f"It works once and expires in {minutes} minutes.\n\n"
            "If you did not ask to sign in, ignore this email — nothing "
            "happens until the link is opened.")
    return subject, html, text
