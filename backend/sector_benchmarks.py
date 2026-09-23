"""Homepage benchmark board: published NSE indices, never stock-basket proxies.

One exchange snapshot supplies all current levels. Historical comparisons use
one NSE daily index CSV for all indices, with a bounded holiday lookback.
The existing sector story/portfolio contracts remain separate.
"""
import csv
import datetime as dt
import io
import math
import threading
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import nse_http

# Actual benchmark identities, not mappings from broad provider sectors.
INDICES = {
    "NIFTY AUTO": "car", "NIFTY BANK": "bank",
    "NIFTY FINANCIAL SERVICES": "bank", "NIFTY FMCG": "wheat",
    "NIFTY HEALTHCARE INDEX": "pill", "NIFTY IT": "chip",
    "NIFTY MEDIA": "tower", "NIFTY METAL": "ingot",
    "NIFTY OIL & GAS": "bolt", "NIFTY PHARMA": "pill",
    "NIFTY PRIVATE BANK": "bank", "NIFTY PSU BANK": "bank",
    "NIFTY REALTY": "building", "NIFTY CONSUMER DURABLES": "plug",
}
ALIASES = {"NIFTY HEALTHCARE": "NIFTY HEALTHCARE INDEX",
           "NIFTY OIL AND GAS": "NIFTY OIL & GAS",
           "NIFTY OIL AND GAS INDEX": "NIFTY OIL & GAS"}
SOURCE_URL = "https://www.nseindia.com/market-data/live-market-indices"
_cache = {}
_archives = {}
_lock = threading.Lock()


def number(value):
    try:
        n = float(str(value).replace(",", ""))
        return n if math.isfinite(n) else None
    except (ValueError, TypeError):
        return None


def name(value):
    key = " ".join(str(value or "").upper().split())
    return ALIASES.get(key, key)


def date(value):
    text = str(value or "").strip()
    for fmt, length in (("%d-%b-%Y", 11), ("%d-%m-%Y", 10),
                        ("%Y-%m-%d", 10)):
        try:
            return dt.datetime.strptime(text[:length], fmt).date()
        except ValueError:
            pass
    return None


def parse_archive(text, expected_date):
    """Reject error HTML, wrong dates, invalid/zero closes and unrelated rows."""
    result = {}
    for raw in csv.DictReader(io.StringIO(text.lstrip("\ufeff"))):
        row = {k.strip(): v for k, v in raw.items() if k}
        key = name(row.get("Index Name"))
        close = number(row.get("Closing Index Value"))
        if (key in INDICES or key == "NIFTY 50") and close and close > 0:
            if date(row.get("Index Date")) == expected_date:
                result[key] = close
    return result


def archive_on_or_before(target):
    """Cache successful immutable archives; stop on connection/WAF failures."""
    for offset in range(8):
        day = target - dt.timedelta(days=offset)
        if day in _archives:
            return day, _archives[day]
        url = ("https://nsearchives.nseindia.com/content/indices/ind_close_all_"
               + day.strftime("%d%m%Y") + ".csv")
        try:
            req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urlopen(req, timeout=4) as response:
                rows = parse_archive(response.read().decode("utf-8-sig"), day)
        except HTTPError as exc:
            if exc.code == 404:
                continue  # weekend/holiday or file not published
            break
        except Exception:
            break
        if rows:
            if len(_archives) >= 32:
                _archives.pop(next(iter(_archives)))
            _archives[day] = rows
            return day, rows
        break  # unexpected schema is not evidence of a holiday
    return None, {}


def build(snapshot, window, baseline_date=None, baseline=None):
    baseline = baseline or {}
    records = {name(r.get("index")): r for r in snapshot.get("data", [])
               if isinstance(r, dict)}
    stamp = snapshot.get("timestamp")
    snapshot_day = date(stamp)

    def value(key):
        raw = records.get(key, {})
        last = number(raw.get("last"))
        if not last or last <= 0 or not snapshot_day:
            return None
        if window == "1D":
            previous = number(raw.get("previousClose"))
            return round((last / previous - 1) * 100, 2) if previous and previous > 0 else None
        previous = baseline.get(key)
        return round((last / previous - 1) * 100, 2) if previous and previous > 0 else None

    bench = value("NIFTY 50")
    rows = []
    for key, icon in INDICES.items():
        change = value(key)
        rows.append({"sector": key.title().replace("It", "IT").replace("Fmcg", "FMCG").replace("Psu", "PSU"),
                     "index": key, "icon": icon, "change_pct": change,
                     "index_level": number(records.get(key, {}).get("last")),
                     "benchmark": "Nifty 50", "benchmark_pct": bench,
                     "relative_pp": round(change - bench, 2) if change is not None and bench is not None else None,
                     "as_of": stamp, "baseline_date": baseline_date.isoformat() if baseline_date else None})
    rows.sort(key=lambda r: (r["change_pct"] is None, -(r["change_pct"] or 0)))
    return {"window": window, "rows": rows, "as_of": stamp,
            "source": "NSE", "source_url": SOURCE_URL,
            "available": any(r["change_pct"] is not None for r in rows),
            "stale": False, "baseline_date": baseline_date.isoformat() if baseline_date else None,
            "method": ("Published NSE price indices. Day: latest level versus previous close. "
                       "7D/30D: latest level versus the close on or before 7/30 calendar days earlier. "
                       "Relative performance is the difference from Nifty 50 in percentage points. "
                       "These are price returns, excluding dividends; constituent breadth is not supplied.")}


def overview(window="1D"):
    if window not in ("1D", "1W", "1M"):
        window = "1D"
    # Serialize cold refreshes across visitors; no duplicate exchange bursts.
    with _lock:
        now = time.monotonic()
        hit = _cache.get(window)
        if hit and now - hit[0] < 60:
            return hit[1]
        snapshot_hit = _cache.get("snapshot")
        if snapshot_hit and now - snapshot_hit[0] < 60:
            snapshot = snapshot_hit[1]
        else:
            try:
                snapshot = nse_http.get_json("https://www.nseindia.com/api/allIndices")
            except Exception:
                snapshot = None
            if isinstance(snapshot, dict) and isinstance(snapshot.get("data"), list) and date(snapshot.get("timestamp")):
                _cache["snapshot"] = (now, snapshot)
            else:
                snapshot = None
        baseline_date, baseline = None, {}
        if snapshot and window != "1D":
            target = date(snapshot.get("timestamp")) - dt.timedelta(days=7 if window == "1W" else 30)
            baseline_date, baseline = archive_on_or_before(target)
        result = build(snapshot or {}, window, baseline_date, baseline)
        if not result["available"] and hit:
            result = {**hit[1], "stale": True}
        _cache[window] = (time.monotonic(), result)
        return result
