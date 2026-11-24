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

import csv
import gc
import io
import os
import threading
import time
import datetime as dt

import pandas as pd
import requests

import market_calendar

BASE = "https://api.dhan.co/v2"
IST_TZ = dt.timezone(dt.timedelta(hours=5, minutes=30))
SCRIP_URLS = [
    "https://images.dhan.co/api-data/api-scrip-master.csv",            # compact — try first
    "https://images.dhan.co/api-data/api-scrip-master-detailed.csv",   # huge — fallback
]
# The CDN sometimes rejects the default python-requests user agent from
# datacenter IPs; present a normal browser instead.
SCRIP_HEADERS = {"User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                "AppleWebKit/537.36 (KHTML, like Gecko) "
                                "Chrome/126.0 Safari/537.36"),
                 "Accept": "text/csv,*/*"}

CLIENT_ID = os.environ.get("DHAN_CLIENT_ID", "").strip()
ACCESS_TOKEN = os.environ.get("DHAN_ACCESS_TOKEN", "").strip()

# Optional auto-refresh: requires TOTP enabled on the Dhan account.
# Storing the login PIN grants full account access to whoever holds it —
# keep these in the host's encrypted environment, never in the repository.
DHAN_PIN = os.environ.get("DHAN_PIN", "").strip()
TOTP_SECRET = os.environ.get("DHAN_TOTP_SECRET", "").strip().replace(" ", "")
AUTH_URL = "https://auth.dhan.co/app/generateAccessToken"

_token = {"value": ACCESS_TOKEN, "issued": time.time() if ACCESS_TOKEN else 0,
          "source": "env" if ACCESS_TOKEN else None, "error": None,
          "last_attempt": 0}
TOKEN_TTL = 20 * 3600          # refresh before Dhan's 24h expiry
AUTH_COOLDOWN = 130            # Dhan: "Token can be generated once every 2 minutes"

_scrip = {"map": None, "at": 0, "error": None}
_status = {"ok": None, "checked": 0, "detail": "not checked"}
SCRIP_TTL = 12 * 3600
STATUS_TTL = 300


def _india_today():
    """Today's date in India, which is the exchange's date.

    dt.date.today() is the server's date, and the server runs in UTC: from
    midnight to 05:30 IST it is still yesterday there. Dhan's daily history
    takes `toDate` as the first day NOT wanted, so a request dated by the
    server at 00:30 IST asked for the sessions before the one that had just
    closed, and nothing adds a bar before 09:15. On the night of 23 November
    2026 RELIANCE read Friday's close from 00:07 IST."""
    return dt.datetime.now(IST_TZ).date()


def can_auto_refresh() -> bool:
    return bool(CLIENT_ID and DHAN_PIN and TOTP_SECRET)


def refresh_token(force=False) -> bool:
    """Generate a fresh access token using TOTP. Returns True on success."""
    if not can_auto_refresh():
        return False
    fresh = _token["value"] and (time.time() - _token["issued"]) < TOKEN_TTL
    if fresh and not force:
        return True
    # Dhan hard-limits token generation to once per 2 minutes — even forced
    # retries must wait, or every attempt fails and we lock ourselves out.
    if (time.time() - _token["last_attempt"]) < AUTH_COOLDOWN:
        return bool(_token["value"])
    _token["last_attempt"] = time.time()
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
            _token["error"] = f"auth HTTP {r.status_code}: {r.text[:160]}"
            return False
        d = r.json() or {}
        tok = d.get("accessToken") or d.get("access_token") or d.get("token")
        if not tok:
            # Show Dhan's own words — usually "invalid pin", "invalid totp" etc.
            _token["error"] = f"auth response without accessToken: {r.text[:160]}"
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
    """
    Return {SYMBOL: securityId} for NSE equity.

    Streamed line-by-line and parsed with the csv module rather than pandas:
    the master file carries ~150k rows across all segments, and loading it into
    a DataFrame peaked at over 130 MB, which is fatal on a 512 MB instance.
    Streaming keeps this under a megabyte.
    """
    if not force and _scrip["map"] is not None and (time.time() - _scrip["at"]) < SCRIP_TTL:
        return _scrip["map"]

    for url in SCRIP_URLS:
        try:
            with requests.get(url, headers=SCRIP_HEADERS, timeout=(15, 120), stream=True) as r:
                if r.status_code != 200:
                    _scrip["error"] = f"HTTP {r.status_code} downloading instrument master"
                    continue
                # CDN omits the charset header; without this requests yields
                # bytes and the csv module rejects them.
                r.encoding = r.encoding or "utf-8"
                lines = r.iter_lines(decode_unicode=True)
                reader = csv.reader(
                    (l.decode("utf-8", "replace") if isinstance(l, bytes) else l)
                    for l in lines if l)
                header = [h.strip().lower() for h in next(reader)]

                def col(*names):
                    for n in names:
                        if n in header:
                            return header.index(n)
                    return None

                i_seg = col("exch_id", "sem_exm_exch_id", "exchange_segment", "segment")
                i_sym = col("underlying_symbol", "sem_trading_symbol", "trading_symbol",
                            "sm_symbol_name", "symbol_name", "sem_custom_symbol")
                i_sid = col("security_id", "sem_smst_security_id", "securityid")
                i_ins = col("instrument", "sem_instrument_name", "instrument_type")
                if i_sym is None or i_sid is None:
                    continue

                m = {}
                for row in reader:
                    try:
                        if i_seg is not None and row[i_seg].strip().upper() not in ("NSE", "NSE_EQ", "E"):
                            continue
                        if i_ins is not None and "EQUITY" not in row[i_ins].strip().upper():
                            continue
                        sym = row[i_sym].strip().upper()
                        if sym and sym not in m:
                            m[sym] = str(int(float(row[i_sid])))
                    except (IndexError, ValueError):
                        continue

            if len(m) > 500:
                _scrip.update({"map": m, "at": time.time(), "error": None})
                gc.collect()
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
        sid = security_id("RELIANCE")
        if not sid:
            detail = ("instrument master unavailable: "
                      + (_scrip.get("error") or "download returned no usable rows"))
        else:
            today = _india_today()
            body = {"securityId": sid, "exchangeSegment": "NSE_EQ", "instrument": "EQUITY",
                    "fromDate": str(today - dt.timedelta(days=10)), "toDate": str(today)}
            r = requests.post(f"{BASE}/charts/historical", json=body,
                              headers=_headers(), timeout=15)
            if r.status_code in (401, 403) and can_auto_refresh() and refresh_token(force=True):
                r = requests.post(f"{BASE}/charts/historical", json=body,
                                  headers=_headers(), timeout=15)
            ok = r.status_code == 200
            if ok:
                detail = "token valid"
            elif r.status_code in (401, 403):
                detail = ("token expired or unauthorised. Regenerate in the Dhan "
                          "portal, or check DHAN_PIN / DHAN_TOTP_SECRET. Dhan said "
                          f"HTTP {r.status_code}: {(r.text or '')[:160]}")
            else:
                detail = f"HTTP {r.status_code}: {r.text[:120]}"
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

def _session_dates(ts):
    """
    The trading date of each daily candle, from Dhan's epoch stamps.

    Dhan's stamps sit at 18:30 UTC, which is midnight IST, and read as the
    wrong midnight they move every bar a day. Rather than assume which
    midnight it is, both readings are taken and the one that puts candles on
    trading days wins: NSE does not trade on Saturday or Sunday, so the wrong
    reading shows up as a year of weekend candles. A tie (too few bars to
    tell) keeps the UTC reading, which is how this was read before.
    """
    utc = pd.to_datetime(pd.Series(ts, dtype="int64"), unit="s")
    ist = utc.dt.tz_localize("UTC").dt.tz_convert("Asia/Kolkata").dt.tz_localize(None)
    a, b = pd.DatetimeIndex(utc.dt.normalize()), pd.DatetimeIndex(ist.dt.normalize())
    weekend = lambda ix: int((ix.dayofweek >= 5).sum())
    return b if weekend(b) < weekend(a) else a


def daily_ohlcv(symbol: str, days: int = 400, with_today: bool = True):
    """Return a DataFrame of daily OHLCV, or None if Dhan can't serve it.
    with_today=False skips building today's bar from a live quote — one quote call
    saved per symbol, for callers that only want completed sessions."""
    if not configured():
        return None
    sid = security_id(symbol)
    if not sid:
        return None

    # `toDate` is not inclusive (Dhan's own description of the field), so
    # this asks for every session before today in India. Today's bar is built
    # from the live quote, in _append_today.
    today = _india_today()
    body = {
        "securityId": sid,
        "exchangeSegment": "NSE_EQ",
        "instrument": "EQUITY",
        "expiryCode": 0,
        "fromDate": str(today - dt.timedelta(days=days)),
        "toDate": str(today),
    }
    try:
        _throttle_hist()
        r = requests.post(f"{BASE}/charts/historical", json=body, headers=_headers(), timeout=20)
        if r.status_code in (401, 403):
            # Token may have expired mid-session — try one refresh, then retry once
            if can_auto_refresh() and refresh_token(force=True):
                r = requests.post(f"{BASE}/charts/historical", json=body,
                                  headers=_headers(), timeout=20)
            if r.status_code != 200:
                _status.update({"ok": False, "checked": time.time(),
                                "detail": f"token expired or unauthorised. Dhan said "
                                          f"HTTP {r.status_code}: {(r.text or '')[:160]}"})
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
        idx = (_session_dates(ts) if len(ts) == len(d["close"]) else
               pd.RangeIndex(len(d["close"])))
        df = pd.DataFrame({
            "Open": d["open"], "High": d["high"], "Low": d["low"], "Close": d["close"],
            "Volume": d.get("volume") or [0] * len(d["close"]),
        }, index=idx)
        df = df.dropna(subset=["Close"])
        if len(df) < 60:
            return None
        if with_today:
            df = _append_today(symbol, df)
        return df
    except Exception:
        return None


def _append_today(symbol, df):
    """
    Dhan's /charts/historical is asked for every session before today (its
    `toDate` is not inclusive), so on a trading day the last bar it returns
    is yesterday's, at 8 PM as much as at noon. That makes the screener look
    a day stale.

    When the last bar predates today AND today is a trading day on which the
    session has already opened, we build today's bar from the live quote
    (open/high/low/LTP/volume) and append it. During market hours this bar
    is the forming candle; after 15:30 it is effectively the close.

    A trading holiday owes no bar. The quote on one is the last session's,
    and a bar built from it would be that session again under today's date.

    When today's bar is owed and the quote does not arrive, the frame is
    returned without it and marked `today_missing`, so the caller can keep it
    for a minute rather than serve the last session as today's for half an
    hour.
    """
    try:
        now = dt.datetime.now(IST_TZ)
        if not market_calendar.trading_day(now.date()):
            return df
        mins = now.hour * 60 + now.minute
        if mins < 555:                       # before 09:15 — nothing to add
            return df
        last = df.index[-1]
        try:
            last_date = last.date()
        except AttributeError:
            return df
        if last_date >= now.date():
            return df

        # mode="quote", not "ohlc": the ohlc feed carries no volume, so the
        # bar built here had a volume of 0 and every after-close measure of
        # the day's volume — a breakout's above all — read as nothing traded.
        df.attrs["today_missing"] = True
        q = bulk_quotes([symbol], mode="quote").get(symbol.upper())
        if not q:
            return df
        close = q.get("ltp") or q.get("close")
        if not close:
            return df
        o = q.get("open") or close
        h = q.get("high") or close
        l = q.get("low") or close
        v = q.get("volume") or 0
        stamp = pd.Timestamp(now.date())
        df.loc[stamp] = {"Open": float(o), "High": float(h), "Low": float(l),
                         "Close": float(close), "Volume": float(v)}
        df.attrs.pop("today_missing", None)
        return df
    except Exception:
        return df


def intraday_ohlcv(symbol: str, interval: str = "5", days: int = 5):
    """
    Intraday candles from Dhan. interval is minutes: 1, 5, 15, 25, 60.
    Returns a DataFrame or None. Dhan-only — Yahoo has no reliable
    intraday feed from a datacenter IP.
    """
    if not configured():
        return None
    sid = security_id(symbol)
    if not sid:
        return None

    today = _india_today()
    body = {
        "securityId": sid,
        "exchangeSegment": "NSE_EQ",
        "instrument": "EQUITY",
        "interval": str(interval),
        "fromDate": str(today - dt.timedelta(days=days)),
        "toDate": str(today),
    }
    try:
        _throttle_hist()
        r = requests.post(f"{BASE}/charts/intraday", json=body, headers=_headers(), timeout=20)
        if r.status_code in (401, 403):
            if can_auto_refresh() and refresh_token(force=True):
                r = requests.post(f"{BASE}/charts/intraday", json=body,
                                  headers=_headers(), timeout=20)
        if r.status_code != 200:
            return None
        d = r.json() or {}
    except Exception:
        return None

    if not all(k in d for k in ("open", "high", "low", "close")) or not d["close"]:
        return None
    try:
        ts = d.get("timestamp") or []
        idx = (pd.to_datetime(pd.Series(ts, dtype="int64"), unit="s")
               .dt.tz_localize("UTC").dt.tz_convert("Asia/Kolkata").dt.tz_localize(None)
               if len(ts) == len(d["close"]) else pd.RangeIndex(len(d["close"])))
        df = pd.DataFrame({
            "Open": d["open"], "High": d["high"], "Low": d["low"], "Close": d["close"],
            "Volume": d.get("volume") or [0] * len(d["close"]),
        }, index=idx)
        return df.dropna(subset=["Close"])
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Bulk quotes — up to 1000 instruments per request (rate limit 1/second)
# ---------------------------------------------------------------------------

BULK_MAX = 900          # stay under the documented 1000 ceiling
QUOTE_GAP = 1.15        # seconds between quote calls (limit is 1/sec)

# Dhan's Data APIs (/charts/historical and /charts/intraday) allow 5 requests
# per second. Nothing here used to throttle them, so the scanner's warm-up —
# hundreds of calls in a tight loop — was rate-limited into returning None for
# almost every symbol, which looked exactly like "Dhan has no data".
HIST_GAP = 0.25
_last_hist = {"at": 0.0}
_last_quote = {"at": 0.0}

# The gaps only hold if callers take turns. The intraday scanner, the sector
# board, watchlists and stock pages all quote from their own threads, and two
# of them reading `at` in the same instant both saw a free slot and both fired,
# inside Dhan's one-a-second limit. A refused quote comes back empty, and for a
# stock page an empty quote is no bar for today: on 23 Nov 2026 WELSPUNLIV
# read Friday's close, with Friday's +6.18% as "today", on Monday afternoon.
# A lock makes each caller wait its turn.
_hist_lock = threading.Lock()
_quote_lock = threading.Lock()


def _throttle_hist():
    with _hist_lock:
        wait = HIST_GAP - (time.time() - _last_hist["at"])
        if wait > 0:
            time.sleep(wait)
        _last_hist["at"] = time.time()


def _throttle_quote():
    with _quote_lock:
        wait = QUOTE_GAP - (time.time() - _last_quote["at"])
        if wait > 0:
            time.sleep(wait)
        _last_quote["at"] = time.time()


def _quote_call(path: str, ids: list) -> dict:
    """POST a batch of security IDs to a marketfeed endpoint."""
    _throttle_quote()
    body = {"NSE_EQ": [int(i) for i in ids]}
    try:
        r = requests.post(f"{BASE}/marketfeed/{path}", json=body, headers=_headers(), timeout=25)
        if r.status_code in (401, 403) and can_auto_refresh() and refresh_token(force=True):
            _throttle_quote()
            r = requests.post(f"{BASE}/marketfeed/{path}", json=body, headers=_headers(), timeout=25)
        if r.status_code != 200:
            return {}
        payload = r.json() or {}
    except Exception:
        return {}
    data = payload.get("data") or payload
    seg = data.get("NSE_EQ") if isinstance(data, dict) else None
    return seg or {}


def bulk_quotes(symbols: list, mode: str = "ohlc") -> dict:
    """
    Snapshot for many symbols at once. mode: 'ltp' | 'ohlc' | 'quote'.
    Returns {SYMBOL: {...}} — the single biggest efficiency win Dhan offers,
    since 2000 stocks cost 3 requests instead of 2000.
    """
    if not configured():
        return {}
    scrip = load_scrip()
    pairs = [(s, scrip.get(s.upper().replace(".NS", ""))) for s in symbols]
    pairs = [(s, sid) for s, sid in pairs if sid]
    if not pairs:
        return {}
    by_id = {str(sid): s for s, sid in pairs}

    out = {}
    ids = [sid for _, sid in pairs]
    for i in range(0, len(ids), BULK_MAX):
        chunk = ids[i:i + BULK_MAX]
        seg = _quote_call(mode, chunk)
        for sid, row in (seg or {}).items():
            sym = by_id.get(str(sid))
            if not sym or not isinstance(row, dict):
                continue
            ohlc = row.get("ohlc") or {}
            out[sym] = {
                "ltp": row.get("last_price") or row.get("ltp") or row.get("LTP"),
                "open": ohlc.get("open") or row.get("open"),
                "high": ohlc.get("high") or row.get("high"),
                "low": ohlc.get("low") or row.get("low"),
                "close": ohlc.get("close") or row.get("close"),
                # volume, average_price, buy_quantity and sell_quantity exist
                # ONLY on /marketfeed/quote. Callers that need them (the live
                # scanner does — every signal is volume-gated) must pass
                # mode="quote"; mode="ohlc" returns price fields and nothing
                # else, which silently produces None here.
                "volume": row.get("volume") or row.get("net_change_volume"),
                "vwap": row.get("average_price") or row.get("avg_price"),
                "buy_qty": row.get("buy_quantity"),
                "sell_qty": row.get("sell_quantity"),
                "oi": row.get("oi"),
                "prev_close": ohlc.get("close"),
                "net_change": row.get("net_change"),
            }
    _settle_prev_close(out)
    return out


# ---------------------------------------------------------------------------
# The previous close, after the close
#
# During a session, the quote's ohlc.close is the PREVIOUS session's close,
# and (ltp - close) is the day's move. Some time after 15:30 the feed rolls:
# close becomes TODAY's close, equal to ltp, and every stock on the site read
# "0.00%" all evening — while the indices, which come from elsewhere, showed
# the day's real move beside them.
#
# A market where nine stocks in ten are exactly unchanged does not exist, so
# that is how the roll is recognised — no clock, no assumption about when the
# exchange finishes its processing. Once recognised, each row gets the
# previous close this process remembered during the session; failing that,
# ltp minus the feed's own net_change; failing that, None — and a caller
# given None falls back to its daily history instead of printing a zero.
# ---------------------------------------------------------------------------

_PREV_FILE = os.path.join(os.environ.get("DATA_DIR", "").strip()
                          or os.path.dirname(os.path.abspath(__file__)), "prev_close.json")
_prev = {"day": None, "map": {}, "saved": 0.0, "loaded": False}
ROLL_MIN_ROWS = 8          # too few rows cannot tell a roll from a quiet stock
ROLL_SHARE = 0.9


def _session_day(now):
    """The session a quote taken at `now` belongs to: today from 09:15 on a
    weekday, otherwise the weekday before."""
    day = now.date()
    if now.weekday() >= 5 or (now.hour * 60 + now.minute) < 555:
        day -= dt.timedelta(days=1)
        while day.weekday() >= 5:
            day -= dt.timedelta(days=1)
    return day.isoformat()


def _prev_memory(day):
    """{SYMBOL: previous close} remembered for session `day`."""
    if not _prev["loaded"]:
        _prev["loaded"] = True
        try:
            import json
            with open(_PREV_FILE) as fh:
                blob = json.load(fh)
            _prev.update({"day": blob.get("day"), "map": blob.get("map") or {}})
        except Exception:
            pass
    if _prev["day"] != day:
        _prev.update({"day": day, "map": {}})
    return _prev["map"]


def _settle_prev_close(out, now=None):
    now = now or dt.datetime.now(IST_TZ)
    rows = []
    for sym, r in out.items():
        try:
            ltp, prev = float(r.get("ltp") or 0), float(r.get("prev_close") or 0)
        except (TypeError, ValueError):
            continue
        if ltp > 0 and prev > 0:
            rows.append((sym, r, ltp, prev))
    if not rows:
        return out
    mins = now.hour * 60 + now.minute
    live = now.weekday() < 5 and 555 <= mins < 930
    memory = _prev_memory(_session_day(now))
    flat = [abs(ltp - prev) < 1e-9 for _s, _r, ltp, prev in rows]
    rolled = len(rows) >= ROLL_MIN_ROWS and sum(flat) / len(rows) >= ROLL_SHARE

    if live and not rolled:
        # The close in hand is the previous close. Remember it for tonight.
        for sym, _r, _ltp, prev in rows:
            memory[sym] = prev
        if time.time() - _prev["saved"] > 300:
            _prev["saved"] = time.time()
            try:
                import json
                tmp = _PREV_FILE + ".tmp"
                with open(tmp, "w") as fh:
                    json.dump({"day": _prev["day"], "map": memory}, fh)
                os.replace(tmp, _PREV_FILE)
            except Exception:
                pass
        return out

    for (sym, r, ltp, _prev_now), is_flat in zip(rows, flat):
        if not is_flat:
            continue
        # A small batch cannot show a roll by itself, but outside the session
        # a flat row with a remembered close is the same thing, one stock wide.
        if not rolled and (live or sym not in memory):
            continue
        if sym in memory:
            r["prev_close"] = memory[sym]
            continue
        try:
            change = float(r.get("net_change") or 0)
        except (TypeError, ValueError):
            change = 0.0
        r["prev_close"] = round(ltp - change, 2) if abs(change) > 1e-9 else None
    return out


# ---------------------------------------------------------------------------
# Option chain
#
# Dhan enforces a SEPARATE rate limit here: 1 request per 3 seconds across
# both /optionchain and /optionchain/expirylist. The generic 1.15 s quote
# throttle is not enough — calling expirylist then the chain back-to-back
# gets the chain request rejected every time, which is exactly the
# "options never load" symptom. So these endpoints get their own 3.2 s
# throttle, one retry after a rate-limit response, and short caches so a
# user flipping between expiries doesn't burn the limit again.
# ---------------------------------------------------------------------------

OC_GAP = 3.2                    # Dhan option-chain limit: 1 request / 3 s
_last_oc = {"at": 0.0, "error": None}   # error: Dhan's reply to the last failed call
_exp_cache = {}                 # {SYMBOL: (expiries, fetched_at, seg_used)}
_chain_cache = {}               # {SYMBOL|EXPIRY: (payload, fetched_at)}
EXP_TTL = 3600                  # expiry dates change rarely
CHAIN_TTL = 25                  # OI updates slowly per Dhan's own docs


def _throttle_oc():
    wait = OC_GAP - (time.time() - _last_oc["at"])
    if wait > 0:
        time.sleep(wait)
    _last_oc["at"] = time.time()


def _oc_post(path: str, body: dict):
    """POST to an option-chain endpoint with throttle + one rate-limit retry."""
    _throttle_oc()
    _last_oc["error"] = None
    try:
        r = requests.post(f"{BASE}/{path}", json=body, headers=_headers(), timeout=25)
        if r.status_code in (401, 403) and can_auto_refresh() and refresh_token(force=True):
            _throttle_oc()
            r = requests.post(f"{BASE}/{path}", json=body, headers=_headers(), timeout=25)
        if r.status_code == 429 or (r.status_code >= 400 and "Rate" in (r.text or "")[:200]):
            time.sleep(OC_GAP)
            _last_oc["at"] = time.time()
            r = requests.post(f"{BASE}/{path}", json=body, headers=_headers(), timeout=25)
        if r.status_code != 200:
            # Keep Dhan's own words ("DH-901 ...", "DH-902 ...") so the caller
            # can say why instead of claiming the symbol has no options.
            # A 400 is usually "no such underlying" — a real non-F&O answer,
            # not a feed fault — so only auth, rate and server errors count.
            if r.status_code in (401, 403, 429) or r.status_code >= 500:
                _last_oc["error"] = f"HTTP {r.status_code}: {(r.text or '')[:160]}"
            return None
        return r.json() or {}
    except Exception as e:
        _last_oc["error"] = str(e)[:160]
        return None


def last_oc_error():
    """Dhan's reply to the most recent failed option-chain call, or None."""
    return _last_oc["error"]


INDEX_UNDERLYING = {
    "NIFTY":     {"scrip": 13, "seg": "IDX_I"},
    "BANKNIFTY": {"scrip": 25, "seg": "IDX_I"},
    "FINNIFTY":  {"scrip": 27, "seg": "IDX_I"},
    "MIDCPNIFTY": {"scrip": 442, "seg": "IDX_I"},
    "SENSEX":    {"scrip": 51, "seg": "IDX_I"},
}


def underlying_ref(symbol: str):
    """Resolve an underlying to (scripId, segment) for option-chain calls."""
    s = symbol.strip().upper().replace(".NS", "")
    if s in INDEX_UNDERLYING:
        ref = INDEX_UNDERLYING[s]
        return ref["scrip"], ref["seg"]
    sid = security_id(s)
    return (int(sid), "NSE_EQ") if sid else (None, None)


def expiry_list(symbol: str) -> list:
    if not configured():
        return []
    key = symbol.strip().upper().replace(".NS", "")
    hit = _exp_cache.get(key)
    if hit and (time.time() - hit[1]) < EXP_TTL:
        return hit[0]

    scrip, seg = underlying_ref(key)
    if not scrip:
        return []

    # Stocks: Dhan's docs only show IDX_I examples. In practice the equity
    # security-id with NSE_EQ works for most stock underlyings; if that comes
    # back empty, retry once with NSE_FNO before giving up.
    seg_tries = [seg] if seg == "IDX_I" else [seg, "NSE_FNO"]
    for s in seg_tries:
        d = _oc_post("optionchain/expirylist",
                     {"UnderlyingScrip": scrip, "UnderlyingSeg": s})
        exp = (d or {}).get("data") or []
        if exp:
            _exp_cache[key] = (exp, time.time(), s)
            return exp
    return []


def option_chain(symbol: str, expiry: str) -> dict:
    """Full chain with OI, IV, Greeks and LTP across strikes."""
    if not configured():
        return {}
    key = symbol.strip().upper().replace(".NS", "")
    ck = f"{key}|{expiry}"
    hit = _chain_cache.get(ck)
    if hit and (time.time() - hit[1]) < CHAIN_TTL:
        return hit[0]

    scrip, seg = underlying_ref(key)
    if not scrip or not expiry:
        return {}
    # Reuse whichever segment the expiry lookup succeeded with
    cached = _exp_cache.get(key)
    if cached and cached[2]:
        seg = cached[2]

    d = _oc_post("optionchain", {"UnderlyingScrip": scrip,
                                 "UnderlyingSeg": seg, "Expiry": expiry})
    if d and (d.get("data") or {}).get("oc"):
        _chain_cache[ck] = (d, time.time())
        if len(_chain_cache) > 40:            # keep the cache tiny
            oldest = min(_chain_cache, key=lambda k: _chain_cache[k][1])
            _chain_cache.pop(oldest, None)
        return d
    return d or {}


# ---------------------------------------------------------------------------
# Quotes / indices
# ---------------------------------------------------------------------------

INDEX_IDS = {"NIFTY 50": "13", "BANK NIFTY": "25", "INDIA VIX": "21"}
