"""
social_x.py — posting to X.

Default behaviour is DRAFT ONLY. Nothing leaves this server unless every one of
these is true:
  X_AUTO_POST=1                        explicitly turned on
  all four OAuth credentials present   from developer.x.com
  the item was approved in the queue   tier-A only

Without credentials this module still works: it returns the post text for you to
copy and paste. That is the intended starting mode, and honestly the right one
for the first few weeks — every post gets a human read before it goes out under
your name about a listed company.

X API free tier allows 500 posts a month, roughly 16 a day. The filter in
announcements.py is tuned to land under that. If you start hitting the cap the
answer is a stricter filter, not a bigger plan.

OAuth 1.0a is signed here with stdlib hmac/hashlib — no tweepy, keeps the
512 MB instance small.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
import urllib.parse
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

try:
    import requests
except Exception:  # pragma: no cover
    requests = None

IST = timezone(timedelta(hours=5, minutes=30))
POST_URL = "https://api.x.com/2/tweets"

_sent_today: Dict[str, int] = {}


def _creds() -> Optional[Dict[str, str]]:
    ck = os.getenv("X_API_KEY")
    cs = os.getenv("X_API_SECRET")
    at = os.getenv("X_ACCESS_TOKEN")
    ats = os.getenv("X_ACCESS_SECRET")
    if all([ck, cs, at, ats]):
        return {"ck": ck, "cs": cs, "at": at, "ats": ats}
    return None


def auto_post_enabled() -> bool:
    return os.getenv("X_AUTO_POST", "0") in ("1", "true", "True") and _creds() is not None


def _quote(s: str) -> str:
    return urllib.parse.quote(str(s), safe="~-._")


def _oauth_header(method: str, url: str, creds: Dict[str, str]) -> str:
    params = {
        "oauth_consumer_key": creds["ck"],
        "oauth_nonce": secrets.token_hex(16),
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": str(int(time.time())),
        "oauth_token": creds["at"],
        "oauth_version": "1.0",
    }
    # JSON body params are not part of the OAuth 1.0a signature base string.
    base_params = "&".join(f"{_quote(k)}={_quote(params[k])}" for k in sorted(params))
    base = f"{method.upper()}&{_quote(url)}&{_quote(base_params)}"
    key = f"{_quote(creds['cs'])}&{_quote(creds['ats'])}".encode()
    sig = base64.b64encode(hmac.new(key, base.encode(), hashlib.sha1).digest()).decode()
    params["oauth_signature"] = sig
    return "OAuth " + ", ".join(f'{_quote(k)}="{_quote(v)}"' for k, v in sorted(params.items()))


def daily_count() -> int:
    key = datetime.now(IST).strftime("%Y-%m-%d")
    return _sent_today.get(key, 0)


def _bump() -> None:
    key = datetime.now(IST).strftime("%Y-%m-%d")
    _sent_today[key] = _sent_today.get(key, 0) + 1


def post(text: str, force: bool = False) -> Dict[str, Any]:
    """Returns {'sent': bool, 'mode': 'live'|'draft', ...}. Never raises."""
    text = (text or "").strip()
    if not text:
        return {"sent": False, "mode": "draft", "error": "empty text"}
    if len(text) > 280:
        return {"sent": False, "mode": "draft", "error": f"too long ({len(text)} chars)"}

    creds = _creds()
    if creds is None:
        return {"sent": False, "mode": "draft", "reason": "no X credentials configured", "text": text}
    if not force and not auto_post_enabled():
        return {"sent": False, "mode": "draft", "reason": "X_AUTO_POST is off", "text": text}

    cap = int(os.getenv("X_DAILY_CAP", "15"))
    if daily_count() >= cap:
        return {"sent": False, "mode": "draft", "reason": f"daily cap {cap} reached", "text": text}

    if requests is None:
        return {"sent": False, "mode": "draft", "error": "requests not installed"}

    try:
        headers = {
            "Authorization": _oauth_header("POST", POST_URL, creds),
            "Content-Type": "application/json",
            "User-Agent": "altaha-screener/1.0",
        }
        r = requests.post(POST_URL, headers=headers, data=json.dumps({"text": text}), timeout=20)
        if r.status_code in (200, 201):
            _bump()
            body = r.json()
            return {"sent": True, "mode": "live",
                    "id": (body.get("data") or {}).get("id"), "text": text}
        return {"sent": False, "mode": "draft", "error": f"HTTP {r.status_code}: {r.text[:220]}", "text": text}
    except Exception as e:
        return {"sent": False, "mode": "draft", "error": f"{type(e).__name__}: {e}", "text": text}


def health() -> Dict[str, Any]:
    creds = _creds()
    return {
        "credentials_present": creds is not None,
        "auto_post_enabled": auto_post_enabled(),
        "daily_cap": int(os.getenv("X_DAILY_CAP", "15")),
        "sent_today": daily_count(),
        "mode": "live" if auto_post_enabled() else "draft — copy and paste from the Social panel",
    }
