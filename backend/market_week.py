"""
market_week.py — the week in five sessions, for the Universe Scan planets.

Each weekday planet opens one session: how the indices closed and what the
institutions did in the cash market that day.

WHY FLOWS ARE RECORDED, NOT FETCHED BY DATE
NSE publishes FII/DII cash-market activity for the latest session only; there
is no public by-date endpoint. So every successful fetch is written to a small
JSON file keyed by session date, and the week is assembled from that record.
A session the server never saw says "not recorded" rather than showing a
guessed number. The record fills in on its own as the week goes by.

The figures are NSE's provisional numbers in ₹ crore. The final NSDL/CDSL
numbers land a day later and differ slightly; the label says provisional.
"""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timedelta, timezone

import nse_http

IST = timezone(timedelta(hours=5, minutes=30))
FLOWS_URL = "https://www.nseindia.com/api/fiidiiTradeReact"
FLOWS_REFERER = "https://www.nseindia.com/reports/fii-dii"
KEEP_DAYS = 90
CACHE_TTL = 900

INDICES = [("^NSEI", "NIFTY 50"), ("^BSESN", "SENSEX"),
           ("^NSEBANK", "BANK NIFTY"), ("^INDIAVIX", "INDIA VIX")]

_HERE = os.path.dirname(os.path.abspath(__file__))
_DIR = os.environ.get("DATA_DIR", "").strip() or _HERE
_PATH = os.path.join(_DIR, "market_flows.json")
_lock = threading.Lock()
_cache = {"at": 0.0, "body": None}


def _num(v):
    try:
        return round(float(str(v).replace(",", "")), 2)
    except (TypeError, ValueError):
        return None


def parse_flows(body):
    """NSE rows -> (iso_date, {"fii": {...}, "dii": {...}}) or None."""
    out, day = {}, None
    for r in nse_http.rows(body):
        cat = str(r.get("category", "")).upper()
        key = "fii" if ("FII" in cat or "FPI" in cat) else ("dii" if "DII" in cat else None)
        if not key:
            continue
        try:
            d = datetime.strptime(str(r.get("date", "")).strip(), "%d-%b-%Y").date().isoformat()
        except ValueError:
            continue
        day = day or d
        if d != day:
            continue
        out[key] = {"buy": _num(r.get("buyValue")), "sell": _num(r.get("sellValue")),
                    "net": _num(r.get("netValue"))}
    return (day, out) if day and out else None


def _load():
    try:
        with open(_PATH) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save(data):
    keep = sorted(data)[-KEEP_DAYS:]
    tmp = _PATH + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump({k: data[k] for k in keep}, f)
        os.replace(tmp, _PATH)
    except Exception:
        pass


def record_latest():
    """Fetch today's provisional flows and add them to the record."""
    parsed = parse_flows(nse_http.get_json(FLOWS_URL, referer=FLOWS_REFERER))
    with _lock:
        data = _load()
        if parsed:
            day, flows = parsed
            data[day] = flows
            _save(data)
        return data


def _closes(symbol):
    from data_source import resolve
    try:
        _, _, hist = resolve(symbol)
        c = hist["Close"].dropna()
        return {ts.date().isoformat(): float(v) for ts, v in c.tail(12).items()}
    except Exception:
        return {}


def _crore(v):
    return f"₹{abs(v):,.0f} cr"


def synopsis(nifty, flows, vix=None):
    """One plain sentence or three: index, then who bought, then fear gauge."""
    parts = []
    if nifty and nifty.get("change_pct") is not None:
        ch = nifty["change_pct"]
        verb = "rose" if ch > 0.05 else ("fell" if ch < -0.05 else "was flat")
        amt = f" {abs(ch):.2f}%" if verb != "was flat" else ""
        parts.append(f"Nifty {verb}{amt} to {nifty['close']:,.0f}.")
    fii = (flows or {}).get("fii", {}).get("net")
    dii = (flows or {}).get("dii", {}).get("net")
    if fii is not None and dii is not None:
        fv = "bought" if fii >= 0 else "sold"
        dv = "bought" if dii >= 0 else "sold"
        line = f"FIIs {fv} a net {_crore(fii)}; DIIs {dv} {_crore(dii)}"
        if fii < 0 < dii:
            line += f", absorbing {min(999, round(dii / -fii * 100))}% of the selling"
        elif dii < 0 < fii:
            line += f", while FIIs absorbed {min(999, round(fii / -dii * 100))}% of theirs"
        parts.append(line + ".")
    if vix and vix.get("change_pct") is not None and abs(vix["change_pct"]) >= 3:
        parts.append(f"VIX {'jumped' if vix['change_pct'] > 0 else 'eased'} "
                     f"{abs(vix['change_pct']):.1f}%.")
    return " ".join(parts)


def build_week(series, flows_by_day, sessions=5):
    """Pure assembly, so it can be tested without a network."""
    nifty = series.get("NIFTY 50") or {}
    days = sorted(nifty)[-(sessions + 1):]
    out = []
    for i, day in enumerate(days):
        if i == 0 and len(days) > sessions:
            continue
        idx = {}
        for label, closes in series.items():
            dates = sorted(closes)
            if day not in closes:
                continue
            pos = dates.index(day)
            prev = closes[dates[pos - 1]] if pos else None
            idx[label] = {"close": round(closes[day], 2),
                          "change_pct": round((closes[day] - prev) / prev * 100, 2) if prev else None}
        flows = flows_by_day.get(day)
        d = datetime.fromisoformat(day)
        out.append({"date": day, "weekday": d.strftime("%a"), "label": d.strftime("%a %d %b"),
                    "indices": idx, "flows": flows,
                    "mood": ("up" if (idx.get("NIFTY 50", {}).get("change_pct") or 0) > 0.05
                             else "down" if (idx.get("NIFTY 50", {}).get("change_pct") or 0) < -0.05
                             else "flat"),
                    "synopsis": synopsis(idx.get("NIFTY 50"), flows, idx.get("INDIA VIX"))})
    return out


def week():
    now = time.time()
    if _cache["body"] and now - _cache["at"] < CACHE_TTL:
        return _cache["body"]
    flows = record_latest()
    series = {label: _closes(sym) for sym, label in INDICES}
    body = {"sessions": build_week(series, flows),
            "flows_source": "NSE provisional cash-market figures, ₹ crore",
            "as_of": datetime.now(IST).strftime("%d %b %Y, %H:%M IST")}
    if body["sessions"]:
        _cache.update(at=now, body=body)
    return body
