"""
Altaha Screener — market capitalisation from NSE's own daily file

WHY THIS EXISTS
The WOW view divides an order's value by the company's market value. Every
source it used for the denominator failed on the server, and silently:

  · social_posts._market_cap_cr asks dhan_source for a market-cap function
    that dhan_source does not have, so it always returned None.
  · Yahoo's quote summary is throttled from a datacenter IP.
  · NSE's quote-equity API answers 403 to the server whatever the handshake.

With no denominator there is no percentage, so no order could ever be WOW —
the page showed "market cap unavailable" on every row.

NSE publishes the answer as a file. The daily PR bhavcopy zip on its archive
host (the same host the filing PDFs come from, which does answer) carries
mcapDDMMYYYY.csv: every listed security's issue size, closing price and market
cap. One ~0.7 MB download a day covers the whole exchange.

WHAT THE NUMBER IS
Market value at the LAST CLOSE, not intraday. A filing at 2 pm is measured
against yesterday's close. For "is this order a tenth of the company" that
difference does not decide anything, and the close date travels with the
figure so the alert can say which close it used.
"""

import csv
import datetime as dt
import io
import os
import threading
import time
import zipfile

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
PR_URL = "https://nsearchives.nseindia.com/archives/equities/bhavcopy/pr/PR%s.zip"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
LOOKBACK = 8                # a long weekend plus a holiday
RETRY_SECONDS = int(os.environ.get("MCAP_RETRY_SECONDS", "1800") or 1800)

_lock = threading.Lock()
_state = {"date": None, "caps": {}, "tried": 0.0, "error": None}

# Equity series first: a symbol listed as EQ and also carrying a BE or RR line
# must be measured on the EQ row.
_SERIES_RANK = {"EQ": 0, "BE": 1, "BZ": 2, "SM": 3, "ST": 3}


def _num(v):
    try:
        return float(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def parse(text: str) -> dict:
    """{SYMBOL: market cap in crore} from the mcap CSV."""
    out, rank = {}, {}
    reader = csv.reader(io.StringIO(text))
    header = None
    for row in reader:
        cells = [c.strip() for c in row]
        if header is None:
            header = [c.lower() for c in cells]
            continue
        if len(cells) < len(header):
            continue
        rec = dict(zip(header, cells))
        sym = (rec.get("symbol") or "").upper()
        series = (rec.get("series") or "").upper()
        cap = _num(next((v for k, v in rec.items() if k.startswith("market cap")), None))
        if not sym or not cap or cap <= 0:
            continue
        r = _SERIES_RANK.get(series, 9)
        if sym in out and rank[sym] <= r:
            continue
        out[sym], rank[sym] = round(cap / 1e7, 2), r        # rupees -> crore
    return out


def _fetch(day: dt.date):
    import requests
    r = requests.get(PR_URL % day.strftime("%d%m%y"),
                     headers={"User-Agent": UA, "Referer": "https://www.nseindia.com/"},
                     timeout=40)
    if r.status_code != 200:
        return None
    z = zipfile.ZipFile(io.BytesIO(r.content))
    name = next((n for n in z.namelist() if n.lower().startswith("mcap")), None)
    if not name:
        return None
    return parse(z.read(name).decode("latin-1"))


def refresh(force: bool = False) -> bool:
    """Load the newest published file. Cheap to call: it is a no-op until the
    next trading day's file can exist, and retries are spaced out."""
    today = dt.datetime.now(IST).date()
    with _lock:
        have = _state["date"]
        if not force and have == today:
            return True
        if not force and time.time() - _state["tried"] < RETRY_SECONDS and have:
            return True
        _state["tried"] = time.time()
    for back in range(LOOKBACK):
        day = today - dt.timedelta(days=back)
        if day.weekday() >= 5:
            continue
        if have and day <= have:
            return True                  # nothing newer is published yet
        try:
            caps = _fetch(day)
        except Exception as e:
            with _lock:
                _state["error"] = "%s: %s" % (type(e).__name__, str(e)[:80])
            continue
        if caps:
            with _lock:
                _state.update({"date": day, "caps": caps, "error": None})
            return True
    return bool(have)


def market_cap_cr(symbol: str):
    """(crore, close date) or (None, None)."""
    if not symbol:
        return None, None
    refresh()
    with _lock:
        v = _state["caps"].get(symbol.strip().upper())
        return (v, _state["date"]) if v else (None, None)


def status() -> dict:
    with _lock:
        return {"close_date": _state["date"].isoformat() if _state["date"] else None,
                "symbols": len(_state["caps"]), "error": _state["error"]}
