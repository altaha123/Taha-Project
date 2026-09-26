"""
Altaha Screener — WOW order alerts, pushed to Telegram as they are filed

WHAT IT DOES
Watches NSE's announcement feed, and when a company files an order whose
disclosed value is at least WOW_MIN_PCT of its market cap, sends one Telegram
message. Nothing else is sent: orders that are small, undisclosed, or placed BY
the company (it is the buyer) are checked and written down, not alerted.

HOW FAST, AND WHY NOT FASTER
NSE has no push feed, so this polls. Two calls, deliberately different:

  · every POLL_SECONDS (15s): the unparameterised announcements call, which
    returns only the latest ~20 filings. It is ~15 KB and answers in about a
    tenth of a second, so polling it this often costs almost nothing.
  · every SWEEP_SECONDS (3 min): the whole of today. On a busy evening more
    than twenty filings can land inside fifteen seconds, and an order pushed
    off the short list by a wave of AGM results would otherwise be missed. The
    sweep catches it, a few minutes late rather than never.

Once an order is seen, the PDF has to be read for its value (a few seconds),
and the market cap comes from NSE's daily file (in memory). Measured end to
end, the alert lands about 15-40 seconds after NSE publishes the filing; each
alert says how long it took.

WHAT IT WILL NOT DO
  · Alert on an order older than MAX_AGE_MIN. After a restart the poller must
    not replay the afternoon.
  · Alert twice. Every order checked is written to the ledger on the data disk,
    keyed the same way as the WOW ledger, before the next one is looked at.
  · Guess. No disclosed value or no market cap means no percentage, and no
    percentage means no alert.
"""

import datetime as dt
import html
import os
import threading
import time

import requests

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))

POLL_SECONDS = int(os.environ.get("ORDER_ALERT_SECONDS", "15") or 15)
NIGHT_SECONDS = int(os.environ.get("ORDER_ALERT_NIGHT_SECONDS", "60") or 60)
SWEEP_SECONDS = int(os.environ.get("ORDER_ALERT_SWEEP_SECONDS", "180") or 180)
MAX_AGE_MIN = int(os.environ.get("ORDER_ALERT_MAX_AGE_MIN", "45") or 45)
MAX_TRIES = 6                 # PDF reads before an order is given up on
ENABLED = os.environ.get("ORDER_ALERTS", "1").strip() not in ("0", "false", "off", "")

NSE_ANN = "https://www.nseindia.com/api/corporate-announcements?index=equities"
NSE_PAGE = "https://www.nseindia.com/companies-listing/corporate-filings-announcements"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

_lock = threading.Lock()
_done = set()                 # ledger keys already decided
_tries = {}                   # key -> failed PDF reads
_session = requests.Session()  # its own: the 3-day poller must not share cookies mid-call
_warm = {"at": 0.0}
_state = {
    "thread": None, "started_at": None, "loaded": False,
    "last_poll": None, "last_sweep": 0.0, "polls": 0, "poll_errors": 0,
    "last_error": None, "checked": 0, "alerts_sent": 0, "alerts_failed": 0,
    "last_alert": None, "last_lag_s": None,
}


# ---------------------------------------------------------------------------
# The ledger of decisions
# ---------------------------------------------------------------------------

def _table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS order_alerts (
            key         TEXT PRIMARY KEY,
            checked_at  TEXT NOT NULL,
            symbol      TEXT,
            outcome     TEXT,
            pct         REAL,
            sent        INTEGER,
            detail      TEXT
        )""")


def _load_done():
    import wow_orders as W
    since = (dt.datetime.now(IST) - dt.timedelta(days=3)).isoformat()
    try:
        with W._db() as conn:
            _table(conn)
            conn.commit()
            rows = conn.execute("SELECT key FROM order_alerts WHERE checked_at >= ?",
                                (since,)).fetchall()
        with _lock:
            _done.update(r["key"] for r in rows)
    except Exception as e:
        _state["last_error"] = "ledger: %s" % str(e)[:100]
    _state["loaded"] = True


def _decide(key, symbol, outcome, pct=None, sent=None, detail=""):
    import wow_orders as W
    with _lock:
        _done.add(key)
        _tries.pop(key, None)
    _state["checked"] += 1
    try:
        with W._db() as conn:
            _table(conn)
            conn.execute(
                "INSERT OR IGNORE INTO order_alerts (key, checked_at, symbol, outcome,"
                " pct, sent, detail) VALUES (?,?,?,?,?,?,?)",
                (key, dt.datetime.now(IST).isoformat(), symbol, outcome, pct,
                 None if sent is None else int(bool(sent)), (detail or "")[:200]))
            conn.commit()
    except Exception as e:
        _state["last_error"] = "ledger write: %s" % str(e)[:100]


def recent(limit: int = 20):
    import wow_orders as W
    try:
        with W._db() as conn:
            _table(conn)
            rows = conn.execute("SELECT * FROM order_alerts ORDER BY checked_at DESC LIMIT ?",
                                (int(limit),)).fetchall()
            return [dict(r) for r in rows]
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------

def _fetch(full_day: bool):
    """NSE rows normalised by announcements.nse_item. Raises on failure."""
    import announcements as A
    params = None
    if full_day:
        d = dt.datetime.now(IST).strftime("%d-%m-%Y")
        params = {"from_date": d, "to_date": d}
    r = None
    for attempt in range(2):
        if attempt or time.time() - _warm["at"] > 900:
            _session.get(NSE_PAGE, headers={"User-Agent": UA,
                                            "Accept": "text/html,application/xhtml+xml",
                                            "Referer": "https://www.nseindia.com/"},
                         timeout=20)
            _warm["at"] = time.time()
        r = _session.get(NSE_ANN, params=params, timeout=45 if full_day else 15,
                         headers={"User-Agent": UA, "Accept": "application/json",
                                  "Referer": NSE_PAGE})
        if r.status_code == 200:
            break
    if r is None or r.status_code != 200:
        raise RuntimeError("NSE HTTP %s" % (r.status_code if r is not None else "-"))
    data = r.json()
    rows = data if isinstance(data, list) else A._rows_from(data)
    return [i for i in (A.nse_item(x) for x in rows) if i]


# ---------------------------------------------------------------------------
# Deciding and sending
# ---------------------------------------------------------------------------

def _cr(v):
    v = float(v)
    if v >= 100000:
        return "₹%.2f lakh cr" % (v / 100000)
    return "₹{:,.2f} cr".format(v).replace(".00 cr", " cr")


def format_alert(row, lag_s=None, close_date=None) -> str:
    e = lambda s: html.escape(str(s or ""), quote=False)
    when = ""
    try:
        when = dt.datetime.fromisoformat(row["at"]).astimezone(IST).strftime("%d %b, %H:%M:%S")
    except Exception:
        pass
    flags = []
    if not row.get("value_confident"):
        flags.append("figure not labelled as the order value in the filing")
    if row.get("currency_converted"):
        flags.append("converted from a foreign currency")
    close = ""
    if close_date:
        try:
            close = " (close %s)" % dt.date.fromisoformat(str(close_date)).strftime("%d %b")
        except Exception:
            close = ""
    lines = [
        "🟢 <b>WOW ORDER</b> · <code>%.1f%%</code> of market cap" % row["pct_of_market_cap"],
        "<b>%s</b>  <code>%s</code>" % (e(row.get("company") or row["symbol"]), e(row["symbol"])),
        "",
        "<code>Order      %s</code>" % e(_cr(row["value_cr"])),
        "<code>Market cap %s</code>%s" % (e(_cr(row["market_cap_cr"])), e(close)),
        "",
        e((row.get("headline") or "")[:240]),
    ]
    if flags:
        lines.append("<i>Note: %s.</i>" % e("; ".join(flags)))
    tail = "Filed %s IST" % when if when else ""
    if lag_s is not None:
        tail += " · alert %ds after NSE published" % int(lag_s)
    lines += ["", tail]
    if row.get("pdf"):
        lines.append('<a href="%s">Open the filing</a>' % html.escape(row["pdf"], quote=True))
    lines.append("<i>Order size against market value. Not a recommendation.</i>")
    return "\n".join(l for l in lines if l is not None)


def _send(text):
    import alerts
    ok, detail = alerts._post(alerts.TG_CHAT, text)
    try:
        alerts._mark(ok, "order alert: " + detail)
    except Exception:
        pass
    return ok, detail


def evaluate(item):
    """
    Read one order filing and decide. Returns the row, or None when the PDF
    could not be read yet (it is retried on the next poll).
    """
    import filings_text
    import wow_orders as W
    text = filings_text.extract(item["pdf"]) if filings_text.available() else None
    if not text:
        return None
    found = W.order_value_cr(text)
    row = {
        "symbol": item.get("symbol"), "company": item.get("company"),
        "headline": item.get("headline"), "at": item.get("at"),
        "date": None, "pdf": item.get("pdf"),
        "value_cr": None, "value_confident": False, "currency_converted": False,
        "market_cap_cr": None, "pct_of_market_cap": None, "wow": False,
        "placed_by_company": W.placed_by_company((item.get("headline") or "") + "\n" + text),
    }
    try:
        row["date"] = dt.datetime.fromisoformat(item["at"]).astimezone(IST).date().isoformat()
    except Exception:
        pass
    if found:
        row.update({"value_cr": found["value_cr"], "value_confident": found["confident"],
                    "currency_converted": found["currency_converted"]})
        cap = W.market_cap_cr(row["symbol"])
        if cap and cap > 0:
            row["market_cap_cr"] = round(cap, 2)
            row["pct_of_market_cap"] = round(100.0 * row["value_cr"] / cap, 2)
            row["wow"] = (row["pct_of_market_cap"] >= W.WOW_MIN_PCT
                          and not row["placed_by_company"])
    return row


def _handle(item, now=None):
    import wow_orders as W
    now = now or time.time()
    key = W._key({"pdf": item.get("pdf"), "company": item.get("company"),
                  "date": (item.get("at") or "")[:10], "headline": item.get("headline")})
    with _lock:
        if key in _done:
            return
    if not item.get("epoch") or now - item["epoch"] > MAX_AGE_MIN * 60:
        return                                   # too old to be news
    if not item.get("pdf"):
        _decide(key, item.get("symbol"), "no filing attached")
        return

    row = evaluate(item)
    if row is None:
        with _lock:
            _tries[key] = _tries.get(key, 0) + 1
            give_up = _tries[key] >= MAX_TRIES
        if give_up:
            _decide(key, item.get("symbol"), "filing unreadable")
        return

    try:
        W.record([row])                          # the WOW page's ledger too
        with W._lock:
            W._cache["at"] = 0.0                 # next page load re-scans
    except Exception:
        pass

    if row["placed_by_company"]:
        _decide(key, row["symbol"], "placed by the company", row["pct_of_market_cap"])
    elif row["value_cr"] is None:
        _decide(key, row["symbol"], "value not disclosed")
    elif row["pct_of_market_cap"] is None:
        _decide(key, row["symbol"], "market cap unavailable")
    elif not row["wow"]:
        _decide(key, row["symbol"], "below threshold", row["pct_of_market_cap"])
    else:
        lag = max(0, time.time() - item["epoch"])
        close = None
        try:
            import nse_mcap
            close = nse_mcap.status().get("close_date")
        except Exception:
            pass
        ok, detail = _send(format_alert(row, lag_s=lag, close_date=close))
        _state["alerts_sent" if ok else "alerts_failed"] += 1
        _state["last_lag_s"] = round(lag, 1)
        _state["last_alert"] = {"symbol": row["symbol"], "pct": row["pct_of_market_cap"],
                                "value_cr": row["value_cr"], "ok": ok, "detail": detail,
                                "at": dt.datetime.now(IST).isoformat(), "lag_s": round(lag, 1)}
        _decide(key, row["symbol"], "alerted" if ok else "send failed",
                row["pct_of_market_cap"], sent=ok, detail=detail)


def tick(full_day: bool = False):
    """One pass. Returns how many order filings were in view."""
    items = _fetch(full_day)
    try:
        import announcements as A
        A._merge(items, lambda i: (i["symbol"], i["headline"], i["at"]))
    except Exception:
        pass
    orders = [i for i in items if i.get("category") == "Order win"]
    orders.sort(key=lambda i: i.get("epoch") or 0)      # oldest first
    for item in orders:
        try:
            _handle(item)
        except Exception as e:
            _state["last_error"] = "%s: %s" % (type(e).__name__, str(e)[:100])
    return len(orders)


# ---------------------------------------------------------------------------
# The loop
# ---------------------------------------------------------------------------

def _interval():
    now = dt.datetime.now(IST)
    if now.hour < 6 or (now.hour == 6 and now.minute < 30):
        return NIGHT_SECONDS                     # the exchange is quiet overnight
    return POLL_SECONDS


def _loop():
    _load_done()
    try:
        import nse_mcap
        nse_mcap.refresh()
    except Exception:
        pass
    while True:
        started = time.time()
        full = started - _state["last_sweep"] >= SWEEP_SECONDS
        try:
            tick(full_day=full)
            if full:
                _state["last_sweep"] = started
            _state["last_poll"] = dt.datetime.now(IST).isoformat()
            _state["polls"] += 1
        except Exception as e:
            _state["poll_errors"] += 1
            _state["last_error"] = "%s: %s" % (type(e).__name__, str(e)[:100])
        time.sleep(max(1.0, _interval() - (time.time() - started)))


def configured() -> bool:
    try:
        import alerts
        return bool(alerts.TG_TOKEN and alerts.TG_CHAT)
    except Exception:
        return False


def ensure_running():
    """Start the poller if it is not alive. Safe to call on every request."""
    if not ENABLED or not configured():
        return False
    with _lock:
        t = _state["thread"]
        if t is not None and t.is_alive():
            return True
        t = threading.Thread(target=_loop, daemon=True, name="altaha-order-alerts")
        _state["thread"] = t
        _state["started_at"] = dt.datetime.now(IST).isoformat()
    t.start()
    return True


def status() -> dict:
    t = _state["thread"]
    out = {k: v for k, v in _state.items() if k != "thread"}
    out.update({
        "enabled": ENABLED,
        "telegram_configured": configured(),
        "running": bool(t is not None and t.is_alive()),
        "poll_seconds": POLL_SECONDS, "sweep_seconds": SWEEP_SECONDS,
        "max_age_min": MAX_AGE_MIN,
        "decided": len(_done), "pending_pdf_retries": len(_tries),
    })
    try:
        import wow_orders as W
        out["threshold_pct"] = W.WOW_MIN_PCT
    except Exception:
        pass
    try:
        import nse_mcap
        out["market_cap_file"] = nse_mcap.status()
    except Exception:
        pass
    return out


def test_message() -> dict:
    """Send one example so the chat can be checked without waiting for a WOW."""
    ok, detail = _send(
        "✅ <b>WOW order alerts are connected.</b>\n"
        "You will get one message per order whose disclosed value is at least "
        "%g%% of the company's market cap, usually within a minute of NSE "
        "publishing the filing." % __import__("wow_orders").WOW_MIN_PCT)
    return {"ok": ok, "detail": detail}
