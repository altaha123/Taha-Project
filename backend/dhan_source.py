"""
Altaha Screener — Dhan Data Source

Uses DhanHQ Data APIs for Indian equity prices when a valid access token is
present, and reports failure clearly so the caller can fall back to Yahoo.

Credentials come from environment variables only — never from the repository:
    DHAN_CLIENT_ID
    DHAN_ACCESS_TOKEN

Dhan identifies instruments by numeric securityId, not ticker, so the
instrument master CSV is downloaded once and cached in memory.

Note on token life: Dhan access tokens are short-lived (24h by default). This
module treats an expired token as a normal, expected condition — is_live()
reports it and every fetch returns None so the caller degrades to Yahoo
rather than erroring.
"""

import io
import os
import time
import datetime as dt

import pandas as pd
import requests

BASE = "https://api.dhan.co/v2"
SCRIP_URLS = [
    "https://images.dhan.co/api-data/api-scrip-master-detailed.csv",
    "https://images.dhan.co/api-data/api-scrip-master.csv",
]

CLIENT_ID = os.environ.get("DHAN_CLIENT_ID", "").strip()
ACCESS_TOKEN = os.environ.get("DHAN_ACCESS_TOKEN", "").strip()

# Optional auto-refresh: requires TOTP enabled on the Dhan account.
# Storing the login PIN grants full account access to whoever holds it —
# keep these in the host's encrypted environment, never in the repository.
DHAN_PIN = os.environ.get("DHAN_PIN", "").strip()
TOTP_SECRET = os.environ.get("DHAN_TOTP_SECRET", "").strip().replace(" ", "")
AUTH_URL = "https://auth.dhan.co/app/generateAccessToken"

_token = {"value": ACCESS_TOKEN, "issued": time.time() if ACCESS_TOKEN else 0,
          "source": "env" if ACCESS_TOKEN else None, "error": None}
TOKEN_TTL = 20 * 3600          # refresh before Dhan's 24h expiry

_scrip = {"map": None, "at": 0, "error": None}
_status = {"ok": None, "checked": 0, "detail": "not checked"}
SCRIP_TTL = 12 * 3600
STATUS_TTL = 300


def can_auto_refresh() -> bool:
    return bool(CLIENT_ID and DHAN_PIN and TOTP_SECRET)


def refresh_token(force=False) -> bool:
    """Generate a fresh access token using TOTP. Returns True on success."""
    if not can_auto_refresh():
        return False
    fresh = _token["value"] and (time.time() - _token["issued"]) < TOKEN_TTL
    if fresh and not force:
        return True
    try:
        import pyotp
        code = pyotp.TOTP(TOTP_SECRET).now()
    except Exception as e:
        _token["error"] = f"TOTP generation failed: {str(e)[:100]}"
        return False

    try:
        r = requests.post(AUTH_URL, params={"dhanClientId": CLIENT_ID,
                                            "pin": DHAN_PIN, "totp": code}, timeout=20)
        if r.status_code != 200:
            _token["error"] = f"auth HTTP {r.status_code}"
            return False
        d = r.json() or {}
        tok = d.get("accessToken") or d.get("access_token") or d.get("token")
        if not tok:
            _token["error"] = "no accessToken in auth response"
            return False
        _token.update({"value": tok, "issued": time.time(),
                       "source": "totp", "error": None})
        _status.update({"ok": True, "checked": time.time(), "detail": "token auto-refreshed"})
        return True
    except Exception as e:
        _token["error"] = str(e)[:140]
        return False


def token() -> str:
    """Current access token, refreshing via TOTP when possible."""
    if can_auto_refresh():
        stale = not _token["value"] or (time.time() - _token["issued"]) >= TOKEN_TTL
        if stale:
            refresh_token()
    return _token["value"] or ACCESS_TOKEN


def configured() -> bool:
    return bool(CLIENT_ID and (token() or can_auto_refresh()))


def _headers():
    return {"access-token": token(), "client-id": CLIENT_ID,
            "Content-Type": "application/json", "Accept": "application/json"}


# ---------------------------------------------------------------------------
# Instrument master — symbol -> securityId
# ---------------------------------------------------------------------------

def _pick(cols, *names):
    low = {str(c).strip().lower(): c for c in cols}
    for n in names:
        if n in low:
            return low[n]
    return None


def load_scrip(force=False) -> dict:
    """Return {SYMBOL: securityId} for NSE equity. Cached in memory."""
    if not force and _scrip["map"] is not None and (time.time() - _scrip["at"]) < SCRIP_TTL:
        return _scrip["map"]

    for url in SCRIP_URLS:
        try:
            r = requests.get(url, timeout=30)
            if r.status_code != 200 or len(r.text) < 1000:
                continue
            df = pd.read_csv(io.StringIO(r.text), low_memory=False)
            cols = df.columns

            c_seg = _pick(cols, "exch_id", "sem_exm_exch_id", "exchange_segment", "segment")
            c_sym = _pick(cols, "underlying_symbol", "sem_trading_symbol", "trading_symbol",
                          "sm_symbol_name", "symbol_name", "sem_custom_symbol")
            c_sid = _pick(cols, "security_id", "sem_smst_security_id", "securityid")
            c_inst = _pick(cols, "instrument", "sem_instrument_name", "instrument_type")
            if not (c_sym and c_sid):
                continue

            d = df
            if c_seg:
                d = d[d[c_seg].astype(str).str.upper().str.strip().isin(["NSE", "NSE_EQ", "E"])]
            if c_inst:
                d = d[d[c_inst].astype(str).str.upper().str.contains("EQUITY", na=False)]

            m = {}
            for _, row in d.iterrows():
                try:
                    sym = str(row[c_sym]).strip().upper()
                    sid = str(int(float(row[c_sid])))
                    if sym and sym not in m:
                        m[sym] = sid
                except Exception:
                    continue

            if len(m) > 500:
                _scrip.update({"map": m, "at": time.time(), "error": None})
                return m
        except Exception as e:
            _scrip["error"] = str(e)[:160]
            continue

    _scrip.update({"map": _scrip["map"] or {}, "at": time.time(),
                   "error": _scrip["error"] or "instrument master unavailable"})
    return _scrip["map"]


def security_id(symbol: str):
    base = symbol.strip().upper().replace(".NS", "").replace(".BO", "")
    return load_scrip().get(base)


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------

def is_live(force=False) -> dict:
    """Cheap probe: is the token currently valid?"""
    if not configured():
        return {"ok": False, "detail": "DHAN_CLIENT_ID / DHAN_ACCESS_TOKEN not set"}
    if not force and _status["ok"] is not None and (time.time() - _status["checked"]) < STATUS_TTL:
        return {"ok": _status["ok"], "detail": _status["detail"]}

    ok, detail = False, "unknown"
    try:
        r = requests.get(f"{BASE}/marketfeed/marketstatus", headers=_headers(), timeout=12)
        if r.status_code == 200:
            ok, detail = True, "token valid"
        elif r.status_code in (401, 403):
            detail = "token expired or unauthorised — regenerate in the Dhan portal"
        else:
            # Endpoint may not exist on all plans; try a known-good data call
            sid = security_id("RELIANCE")
            if sid:
                today = dt.date.today()
                body = {"securityId": sid, "exchangeSegment": "NSE_EQ", "instrument": "EQUITY",
                        "fromDate": str(today - dt.timedelta(days=10)), "toDate": str(today)}
                r2 = requests.post(f"{BASE}/charts/historical", json=body,
                                   headers=_headers(), timeout=15)
                ok = r2.status_code == 200
                detail = "token valid" if ok else f"HTTP {r2.status_code}"
            else:
                detail = "instrument master unavailable"
    except Exception as e:
        detail = str(e)[:160]

    _status.update({"ok": ok, "checked": time.time(), "detail": detail})
    return {"ok": ok, "detail": detail}


def token_info() -> dict:
    age = (time.time() - _token["issued"]) / 3600 if _token["issued"] else None
    return {
        "auto_refresh": can_auto_refresh(),
        "source": _token["source"],
        "age_hours": round(age, 1) if age is not None else None,
        "error": _token["error"],
    }


# ---------------------------------------------------------------------------
# Historical candles
# ---------------------------------------------------------------------------

def daily_ohlcv(symbol: str, days: int = 400):
    """Return a DataFrame of daily OHLCV, or None if Dhan can't serve it."""
    if not configured():
        return None
    sid = security_id(symbol)
    if not sid:
        return None

    today = dt.date.today()
    body = {
        "securityId": sid,
        "exchangeSegment": "NSE_EQ",
        "instrument": "EQUITY",
        "expiryCode": 0,
        "fromDate": str(today - dt.timedelta(days=days)),
        "toDate": str(today),
    }
    try:
        r = requests.post(f"{BASE}/charts/historical", json=body, headers=_headers(), timeout=20)
        if r.status_code in (401, 403):
            # Token may have expired mid-session — try one refresh, then retry once
            if can_auto_refresh() and refresh_token(force=True):
                r = requests.post(f"{BASE}/charts/historical", json=body,
                                  headers=_headers(), timeout=20)
            if r.status_code != 200:
                _status.update({"ok": False, "checked": time.time(),
                                "detail": "token expired or unauthorised"})
                return None
        elif r.status_code != 200:
            return None
        d = r.json() or {}
    except Exception:
        return None

    need = ("open", "high", "low", "close")
    if not all(k in d for k in need) or not d["close"]:
        return None

    try:
        ts = d.get("timestamp") or d.get("start_Time") or []
        idx = (pd.to_datetime(pd.Series(ts, dtype="int64"), unit="s")
               if len(ts) == len(d["close"]) else
               pd.RangeIndex(len(d["close"])))
        df = pd.DataFrame({
            "Open": d["open"], "High": d["high"], "Low": d["low"], "Close": d["close"],
            "Volume": d.get("volume") or [0] * len(d["close"]),
        }, index=idx)
        df = df.dropna(subset=["Close"])
        return df if len(df) >= 60 else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Quotes / indices
# ---------------------------------------------------------------------------

INDEX_IDS = {"NIFTY 50": "13", "BANK NIFTY": "25", "INDIA VIX": "21"}


def market_status():
    """Dhan's own market status, or None."""
    if not configured():
        return None
    try:
        r = requests.get(f"{BASE}/marketfeed/marketstatus", headers=_headers(), timeout=12)
        if r.status_code != 200:
            return None
        d = r.json()
        if isinstance(d, dict):
            for k in ("marketStatus", "status", "NSE", "nse"):
                v = d.get(k)
                if isinstance(v, str):
                    return v.lower()
        return None
    except Exception:
        return None
