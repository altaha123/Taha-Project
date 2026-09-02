"""
Altaha Screener — bulk, block and short deals

WHAT THESE ARE
  · A BULK DEAL is any trade where a single client buys or sells more than
    0.5% of a company's listed shares in one day. The broker reports it to the
    exchange; the exchange publishes it.
  · A BLOCK DEAL is a single negotiated trade of at least ₹10 crore, executed
    in one of two dedicated windows (08:45–09:00 and 14:05–14:20).
  · A SHORT DEAL is the exchange's disclosure of institutional short selling.

HOW "LIVE" THIS ACTUALLY IS, STATED HONESTLY
Not tick-by-tick, and it cannot be. These are DISCLOSURES made after a trade
happens, not a price feed. Block deals appear within minutes of their window
because the window itself is fixed; bulk deals are reported by the broker over
the course of the day and are complete only after the close. The snapshot
endpoint carries the current day's disclosures and is polled through the
session — which is same-day, and same-day is the whole value. Nobody needs to
know within four seconds that a fund bought 0.6% of a smallcap; they need to
know it happened, on the day it happened, without going to look.

WHY THE RAW TABLE IS NOT ENOUGH, AND WHAT THIS MODULE ADDS
Every finance site prints these rows. Printed raw they mislead, in two
specific and very common ways:

  1. ROUND TRIPS. The same client frequently appears as both buyer and seller
     of the same stock on the same day. That is a position opened and closed,
     or a cross — it is not accumulation, and counting the buy side as
     conviction is simply wrong. This module nets each client per stock and
     marks the round trips.

  2. PROPRIETARY DESKS. A large share of bulk-deal rows in small caps are
     high-frequency proprietary firms providing liquidity. Their name appearing
     on the buy side means a market maker had inventory that afternoon; it
     carries no view about the company at all. Reading it as "smart money is
     buying" is exactly backwards.

So the payload separates what somebody actually accumulated from what merely
crossed the tape, and says which is which. That distinction is the product.

NOT A RECOMMENDATION
A bulk deal is a fact about who traded, not a reason to trade. Small-cap bulk
deals are as often an operator distributing stock as an investor building a
position, and the exchange record cannot tell you which. Nothing here scores a
stock or feeds the engine; it sits beside the analysis as evidence, the same
way filings do.
"""

import datetime as dt
import os
import re
import threading
import time

import requests

NSE_SNAPSHOT = "https://www.nseindia.com/api/snapshot-capital-market-largedeal"
NSE_HISTORY = "https://www.nseindia.com/api/historicalOR/bulk-block-short-deals"
NSE_REFERER = "https://www.nseindia.com/market-data/large-deals"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/122.0 Safari/537.36")

TIMEOUT = 25

# The disclosures change a handful of times a day, and the block window closes
# at 14:20. Polling harder than this buys nothing and NSE rate-limits.
TTL = int(os.environ.get("DEALS_TTL_SECONDS", "600") or 600)

KINDS = ("bulk", "block", "short")

# Proprietary and high-frequency desks that appear constantly in bulk-deal
# rows because they make markets, not because they have a view. The list is
# deliberately short and conservative — a firm is only here if its presence in
# these rows is overwhelmingly liquidity provision. Anything unmatched is
# treated as a real participant, because wrongly dismissing a genuine buyer is
# the more expensive mistake.
PROP_DESKS = (
    "HRTI", "GRAVITON", "ALPHAGREP", "QE SECURITIES", "TOWER RESEARCH",
    "AQUA MARINE", "DOLAT", "JANE STREET", "OPTIVER", "QUADEYE",
    "NK SECURITIES", "XTX MARKETS", "MANSUKH", "CROSSEAS CAPITAL",
    "SHAREKHAN SECURITIES",
)

# Words that mark a counterparty as an institution rather than an individual.
# Presence is informative; absence is not — plenty of serious investors trade
# in a personal name, so this never becomes a quality score.
INSTITUTION_WORDS = (
    "MUTUAL FUND", "INSURANCE", "LIFE INSURANCE", "PENSION", "PROVIDENT",
    "ASSET MANAGEMENT", "AMC", "TRUSTEE", "FUND", "CAPITAL", "INVESTMENT",
    "PORTFOLIO", "FPI", "FII", "SOVEREIGN", "ENDOWMENT", "LLP", "LIMITED",
    "PVT", "PRIVATE", "PLC", "HOLDINGS", "VENTURES", "PARTNERS",
)

_lock = threading.Lock()
_sess = {"s": None}
_warm = {"at": 0.0}
_cache = {}


# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------

def session():
    with _lock:
        if _sess["s"] is None:
            s = requests.Session()
            s.headers.update({
                "User-Agent": UA,
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "en-US,en;q=0.9",
                "Referer": NSE_REFERER,
            })
            _sess["s"] = s
        return _sess["s"]


def _warm_session(force=False):
    """
    NSE hands out a cookie on the public pages and rejects API calls without
    it. Warmed at most every ten minutes, and every failure here is swallowed
    — a cold call that happens to work is better than a hard failure because
    the warm-up page was slow.
    """
    if not force and (time.time() - _warm["at"]) < 600:
        return
    for url in ("https://www.nseindia.com/", NSE_REFERER):
        try:
            session().get(url, timeout=TIMEOUT)
        except Exception:
            pass
    _warm["at"] = time.time()


def _api(url, params=None):
    _warm_session()
    try:
        r = session().get(url, timeout=TIMEOUT, params=params or {})
        if r.status_code in (401, 403):
            _warm_session(force=True)
            r = session().get(url, timeout=TIMEOUT, params=params or {})
        if r.status_code != 200:
            return None
        return r.json()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Normalising
# ---------------------------------------------------------------------------

def _num(v):
    try:
        return float(str(v).replace(",", "").strip())
    except (TypeError, ValueError, AttributeError):
        return None


def _clean_name(v):
    return re.sub(r"\s+", " ", str(v or "")).strip().upper()


def is_prop_desk(client):
    c = _clean_name(client)
    return any(p in c for p in PROP_DESKS)


def looks_institutional(client):
    c = _clean_name(client)
    return any(w in c for w in INSTITUTION_WORDS)


def _row(symbol, name, client, side, qty, price, date, kind, remarks=None):
    qty = _num(qty)
    price = _num(price)
    value = (qty * price) if (qty and price) else None
    side = str(side or "").strip().upper()
    return {
        "symbol": str(symbol or "").strip().upper(),
        "name": str(name or "").strip(),
        "client": _clean_name(client),
        "side": "BUY" if side.startswith("B") else "SELL" if side.startswith("S") else side,
        "qty": qty,
        "price": price,
        "value": value,
        "value_cr": round(value / 1e7, 2) if value else None,
        "date": str(date or "").strip(),
        "kind": kind,
        "remarks": (remarks or "").strip() or None,
        "prop_desk": is_prop_desk(client),
        "institutional": looks_institutional(client),
    }


def _from_snapshot(rows, kind):
    return [_row(r.get("symbol"), r.get("name"), r.get("clientName"),
                 r.get("buySell"), r.get("qty"), r.get("watp"),
                 r.get("date"), kind, r.get("remarks"))
            for r in (rows or [])]


def _from_history(rows, kind):
    return [_row(r.get("BD_SYMBOL"), r.get("BD_SCRIP_NAME"), r.get("BD_CLIENT_NAME"),
                 r.get("BD_BUY_SELL"), r.get("BD_QTY_TRD"), r.get("BD_TP_WATP"),
                 r.get("BD_DT_DATE"), kind, r.get("BD_REMARKS"))
            for r in (rows or [])]


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------

def _cached(key, build):
    now = time.time()
    hit = _cache.get(key)
    if hit and (now - hit[0]) < TTL:
        return hit[1]
    out = build()
    if out is not None:
        _cache[key] = (now, out)
    return out


def today(force=False):
    """
    Every bulk, block and short-sell disclosure the exchange has published for
    the current session.
    """
    if force:
        _cache.pop("today", None)

    def build():
        d = _api(NSE_SNAPSHOT)
        if not isinstance(d, dict):
            return None
        rows = (_from_snapshot(d.get("BULK_DEALS_DATA"), "bulk") +
                _from_snapshot(d.get("BLOCK_DEALS_DATA"), "block") +
                _from_snapshot(d.get("SHORT_DEALS_DATA"), "short"))
        return {"as_on": d.get("as_on_date"), "rows": rows,
                "counts": {"bulk": int(d.get("BULK_DEALS") or 0),
                           "block": int(d.get("BLOCK_DEALS") or 0),
                           "short": int(d.get("SHORT_DEALS") or 0)}}

    return _cached("today", build)


def history(kind="bulk", days=30, symbol=None):
    """Past disclosures. NSE serves these from a separate, slower index."""
    kind = kind if kind in KINDS else "bulk"
    end = dt.date.today()
    start = end - dt.timedelta(days=max(1, min(int(days), 365)))
    opt = {"bulk": "bulk_deals", "block": "block_deals",
           "short": "short_selling"}[kind]
    key = f"hist:{kind}:{days}:{(symbol or '').upper()}"

    def build():
        params = {"optionType": opt,
                  "from": start.strftime("%d-%m-%Y"),
                  "to": end.strftime("%d-%m-%Y")}
        if symbol:
            params["symbol"] = symbol.strip().upper()
        d = _api(NSE_HISTORY, params)
        if not isinstance(d, dict):
            return None
        return _from_history(d.get("data"), kind)

    return _cached(key, build)


# ---------------------------------------------------------------------------
# The part that makes it worth showing
# ---------------------------------------------------------------------------

def net_by_symbol(rows, min_value_cr=0.0):
    """
    What was actually accumulated, per stock, after the noise is removed.

    Three things happen here and each one changes the answer:

    · Buys and sells are NETTED. A stock with a ₹40cr buy and a ₹39cr sell did
      not see ₹40cr of demand; it saw one crore and a change of hands.
    · ROUND TRIPS are identified. Where the same client is on both sides of the
      same stock on the same day, that client's net is what matters, and if it
      nets to roughly nothing they are marked as crossing rather than
      accumulating.
    · PROPRIETARY DESKS are separated out. A market maker's inventory is not a
      view, and leaving it in the total is how a liquidity print gets read as
      institutional conviction.
    """
    agg = {}
    for r in rows or []:
        if r.get("kind") == "short" or not r.get("symbol") or not r.get("value"):
            continue
        a = agg.setdefault(r["symbol"], {
            "symbol": r["symbol"], "name": r.get("name"),
            "buy_value": 0.0, "sell_value": 0.0,
            "prop_value": 0.0, "deals": 0, "kinds": set(),
            "clients": {}, "block": False,
        })
        a["deals"] += 1
        a["kinds"].add(r["kind"])
        if r["kind"] == "block":
            a["block"] = True
        signed = r["value"] if r["side"] == "BUY" else -r["value"]
        c = a["clients"].setdefault(r["client"], {"net": 0.0, "gross": 0.0,
                                                  "prop": r.get("prop_desk"),
                                                  "institutional": r.get("institutional")})
        c["net"] += signed
        c["gross"] += r["value"]
        if r.get("prop_desk"):
            a["prop_value"] += r["value"]
        elif r["side"] == "BUY":
            a["buy_value"] += r["value"]
        else:
            a["sell_value"] += r["value"]

    out = []
    for a in agg.values():
        # A client is "crossing" when their net is small against their gross —
        # they bought and sold roughly the same amount and ended flat.
        crossers = [c for c, v in a["clients"].items()
                    if v["gross"] > 0 and abs(v["net"]) < 0.15 * v["gross"]]
        real = {c: v for c, v in a["clients"].items()
                if c not in crossers and not v["prop"]}
        net = a["buy_value"] - a["sell_value"]
        gross = a["buy_value"] + a["sell_value"] + a["prop_value"]
        if gross / 1e7 < min_value_cr:
            continue
        buyers = sorted([c for c, v in real.items() if v["net"] > 0],
                        key=lambda c: -real[c]["net"])
        sellers = sorted([c for c, v in real.items() if v["net"] < 0],
                         key=lambda c: real[c]["net"])
        out.append({
            "symbol": a["symbol"], "name": a["name"],
            "deals": a["deals"], "kinds": sorted(a["kinds"]), "block": a["block"],
            "buy_cr": round(a["buy_value"] / 1e7, 2),
            "sell_cr": round(a["sell_value"] / 1e7, 2),
            "net_cr": round(net / 1e7, 2),
            "gross_cr": round(gross / 1e7, 2),
            "prop_cr": round(a["prop_value"] / 1e7, 2),
            "crossed": bool(crossers),
            "crossing_clients": sorted(crossers),
            "top_buyers": [{"client": c, "value_cr": round(real[c]["net"] / 1e7, 2),
                            "institutional": real[c]["institutional"]} for c in buyers[:4]],
            "top_sellers": [{"client": c, "value_cr": round(-real[c]["net"] / 1e7, 2),
                             "institutional": real[c]["institutional"]} for c in sellers[:4]],
            "reading": _reading(a, net, crossers, real),
        })
    out.sort(key=lambda r: -abs(r["net_cr"]))
    return out


def _reading(a, net, crossers, real):
    """One sentence saying what the numbers do and do not support."""
    net_cr = net / 1e7
    prop_cr = a["prop_value"] / 1e7
    if not real and prop_cr > 0:
        return ("Entirely proprietary desks. This is market making, not a view "
                "on the company — there is no accumulation here to read.")
    if crossers and abs(net_cr) < 0.5:
        return ("The same counterparty is on both sides and ends roughly flat. "
                "Stock changed hands; nobody built a position.")
    if a["block"] and net_cr > 0:
        return (f"A negotiated block. Somebody bought ₹{abs(net_cr):.1f}cr net at "
                "an agreed price — which says a buyer and a seller both wanted "
                "the trade, not that the price is right.")
    if net_cr > 0:
        return (f"₹{net_cr:.1f}cr net bought. Who they are matters more than the "
                "number; a bulk deal in a small cap is as often distribution as "
                "accumulation.")
    if net_cr < 0:
        return (f"₹{abs(net_cr):.1f}cr net sold. Worth knowing who is leaving, and "
                "whether they were an early holder rather than a recent one.")
    return "Buying and selling cancelled out."


def for_symbol(symbol, days=90):
    """Everything disclosed for one stock, newest first."""
    sym = str(symbol or "").strip().upper().replace(".NS", "").replace(".BO", "")
    if not sym:
        return {"available": False, "message": "Provide a symbol."}
    rows = []
    snap = today()
    if snap:
        rows += [r for r in snap["rows"] if r["symbol"] == sym]
    for kind in ("bulk", "block"):
        h = history(kind, days=days, symbol=sym)
        if h:
            rows += [r for r in h if r["symbol"] == sym]
    # The snapshot and the history overlap on the current day.
    seen, unique = set(), []
    for r in rows:
        key = (r["date"], r["client"], r["side"], r["qty"], r["kind"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(r)
    unique.sort(key=lambda r: (_sort_date(r["date"]), r.get("value") or 0), reverse=True)
    return {"available": True, "symbol": sym, "rows": unique,
            "count": len(unique), "days": days,
            "net": (net_by_symbol(unique) or [None])[0]}


def _sort_date(s):
    for fmt in ("%d-%b-%Y", "%d-%B-%Y", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(str(s).strip().title(), fmt).date()
        except Exception:
            continue
    return dt.date.min


def board(min_value_cr=1.0, limit=40):
    """The day's disclosures, aggregated and ranked. What the panel shows."""
    snap = today()
    if not snap:
        return {"available": False,
                "message": "The exchange's large-deal feed did not answer. It is "
                           "published through the day and completes after the close."}
    rows = snap["rows"]
    nets = net_by_symbol(rows, min_value_cr=min_value_cr)
    shorts = [r for r in rows if r["kind"] == "short"]
    return {
        "available": True,
        "as_on": snap.get("as_on"),
        "counts": snap.get("counts"),
        "symbols": nets[:max(1, min(int(limit), 200))],
        "shown": min(len(nets), limit),
        "total_symbols": len(nets),
        "short_sold": sorted({r["symbol"] for r in shorts}),
        "min_value_cr": min_value_cr,
        "timing": ("Block deals are published within minutes of their window "
                   "(08:45–09:00 and 14:05–14:20). Bulk deals are reported by the "
                   "broker through the day and are complete only after the close. "
                   "This is a disclosure record, not a live trade feed — there is "
                   "no such thing as a real-time bulk deal."),
        "caveat": ("A bulk deal says who traded, not whether they were right. In "
                   "small caps it is as often an operator distributing stock as an "
                   "investor building a position, and the exchange record cannot "
                   "tell you which. Nothing here scores a stock."),
    }
