"""
Altaha Screener — WOW orders: an order big enough to matter

THE IDEA IN ONE LINE
"Company wins Rs 450 crore order" is a headline. "Rs 450 crore, against a
market value of Rs 3,700 crore" is a fact about the company. The second one is
the product, and it is arithmetic on two published numbers, so it stays on the
factual side of the line this project is built inside.

WHY THE VALUE HAS TO COME OUT OF THE PDF
Measured over 800 announcements across six trading days: one headline in the
whole set carried a rupee figure, and none of the four order disclosures stated
a value in the headline. The exchange feed gives a subject line; the amount is
in the attachment. So this reads the attachment.

WHAT IT REUSES
The rupee-figure patterns and the crore normalisation already exist in
social_posts, written for the same problem, and they are imported rather than
written again. What is added here is WHERE to look: in a one-page order letter
the largest figure in the document is almost always the order, but in a longer
filing it may be turnover, or last year's order book, or the company's paid-up
capital. So a figure sitting next to an order-value phrase beats a bigger
figure that is not, and the basis for the choice travels with the number.

WHAT IT REFUSES TO DO
  · No value in the filing means no value. Plenty of Reg 30 order disclosures
    quantify a contract in megawatts, containers or route-kilometres and never
    state a rupee amount — the live example this was built against is a Letter
    of Intent measured in containers. Those are listed as "value not disclosed"
    and are excluded from the ranking rather than given a guessed number.
  · No market cap means no percentage. The order value is still shown.
  · A foreign-currency order is marked as converted at an assumed rate, because
    it was.

None of this is a recommendation. An order is an event with a size, and the
size is the whole of what this claims.
"""

import datetime as dt
import os
import re
import threading
import time

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))

# An order worth this much of the company is what the feature is named after.
# Inspectable and configurable, and shown in the response so a reader knows
# what line they are looking at.
WOW_MIN_PCT = float(os.environ.get("WOW_MIN_PCT", "10") or 10)

# How far from an order-value phrase a figure may sit and still be read as the
# order's value. Two sentences, roughly.
NEAR = int(os.environ.get("WOW_NEAR_CHARS", "260") or 260)

MAX_PDFS = int(os.environ.get("WOW_MAX_PDFS", "40") or 40)
CACHE_TTL = int(os.environ.get("WOW_CACHE_TTL", "600") or 600)

# Seconds one refresh may spend downloading filings it has not read before.
# A filing that does not fit is left for the next refresh and says "not read
# yet"; it is never reported as "value not disclosed", which it may not be.
SCAN_BUDGET = int(os.environ.get("WOW_SCAN_BUDGET", "180") or 180)

# The announcements poller keeps three days. The orders window is seven, so
# the wide walk runs on the first refresh and then every few hours; between
# those the three-day poll keeps the newest days current. Orders the feed has
# seen stay in its memory, so nothing older is lost by not re-walking it.
WIDE_POLL_EVERY = int(os.environ.get("WOW_WIDE_POLL_EVERY", str(3 * 3600)) or 3 * 3600)

_lock = threading.Lock()
# One entry per window: {days: {"at": epoch, "rows": [...], "note": str}}.
_cache = {}
# The refresh itself. It runs on a thread, one at a time: a page that opened
# while it was running gets the last answer at once, not a second scan.
_run = {"running": False, "started": None, "finished": None, "error": "",
        "wide_poll": {}}
_mcap_cache = {}


# ---------------------------------------------------------------------------
# The value of the order
# ---------------------------------------------------------------------------

# Phrases a filing uses immediately around the number that IS the order.
VALUE_CUE = re.compile(
    r"\b(order value|contract value|value of the (?:order|contract|project|work)"
    r"|total value|aggregate value|aggregating to|valued at|worth(?: of)?"
    r"|order (?:worth|of|for)|contract (?:worth|of|for)|consideration of"
    r"|estimated (?:value|cost)|project cost|size of the order)\b", re.I)

# Figures that are emphatically NOT the order, even when they are the largest
# number on the page.
ANTI_CUE = re.compile(
    r"\b(paid-?up|share capital|authorised capital|turnover|revenue from operations"
    r"|net worth|market capitali[sz]ation|order book|outstanding orders"
    r"|previous year|corresponding quarter|face value|authorized capital)\b", re.I)


# A sentence break, except after the abbreviations an Indian filing is full
# of. "Rs. 5,000 crore" is one clause, not two, and splitting it there detaches
# the figure from the words that say what it is — which is how a company's
# paid-up capital gets read as the value of its order.
_SENT_BREAK = re.compile(r"(?:(?<=[.;:!?])\s+(?!\d))|\n")


def _sentence_spans(text: str):
    """
    Sentence boundaries for the whole document, computed once.

    Deliberately not done per match with re's pos/endpos arguments: those
    truncate the string the pattern can see, so a lookahead sitting at the
    boundary succeeds against nothing and "Rs. 5,000 crore" splits after the
    "Rs." after all. That detaches every figure from the words describing it,
    which is precisely how a company's paid-up capital gets read as the value
    of its order.
    """
    spans, left = [], 0
    for m in _SENT_BREAK.finditer(text):
        if m.end() > left:
            spans.append((left, m.start()))
            left = m.end()
    spans.append((left, len(text)))
    return spans


def _sentence_at(text: str, spans, start: int) -> str:
    for a, b in spans:
        if a <= start < b:
            return text[a:b]
    return text[max(0, start - 200):start + 200]


def _patterns():
    """The rupee patterns, borrowed from social_posts rather than rewritten."""
    import social_posts
    return social_posts.MONEY_PATTERNS


def _is_foreign(pattern) -> bool:
    return "usd" in pattern.pattern.lower() or r"\$" in pattern.pattern


def order_value_cr(text: str):
    """
    The order's value in crore, with the basis for believing it.

    Returns a dict, or None when the filing does not state one. Never a guess.
    """
    if not text:
        return None
    spans = _sentence_spans(text)
    hits = []
    for rx, mult in _patterns():
        for m in rx.finditer(text):
            try:
                val = float(m.group(1).replace(",", "")) * mult
            except (ValueError, IndexError):
                continue
            if val <= 0 or val > 5_000_000:      # > Rs 50 lakh crore is a typo
                continue
            start, end = m.start(), m.end()
            window = text[max(0, start - NEAR):min(len(text), end + NEAR)]
            near_value = bool(VALUE_CUE.search(window))
            # A number in a sentence about paid-up capital is not the order.
            # Scoped to the SENTENCE, not a character window: a filing that
            # states its share capital one sentence before the order would
            # otherwise disqualify the order too, which is the exact shape of
            # a real disclosure.
            if ANTI_CUE.search(_sentence_at(text, spans, start)):
                continue
            hits.append({
                "cr": round(val, 2),
                "near_cue": near_value,
                "foreign": _is_foreign(rx),
                "at": start,
                "excerpt": re.sub(r"\s+", " ",
                                  text[max(0, start - 120):end + 120]).strip(),
            })
    if not hits:
        return None

    cued = [h for h in hits if h["near_cue"]]
    if cued:
        best = max(cued, key=lambda h: h["cr"])
        basis = "stated next to an order-value phrase in the filing"
    else:
        best = max(hits, key=lambda h: h["cr"])
        basis = ("largest rupee figure in the filing; the filing does not label "
                 "it as the order value")
    return {
        "value_cr": best["cr"],
        "basis": basis,
        "confident": bool(cued),
        "currency_converted": best["foreign"],
        "excerpt": best["excerpt"][:320],
    }


# ---------------------------------------------------------------------------
# Market cap
# ---------------------------------------------------------------------------

def market_cap_cr(symbol: str):
    """
    Market capitalisation in crore, Dhan first and the provider after.

    Cached for the life of the process: it moves with the price, and a figure
    that is a day stale changes "12% of market value" to "12.4% of market
    value", which is not a difference this feature turns on.
    """
    if not symbol:
        return None
    with _lock:
        hit = _mcap_cache.get(symbol)
    if hit and time.time() - hit[0] < 6 * 3600:
        return hit[1]

    value = None
    try:
        import social_posts
        value = social_posts._market_cap_cr(symbol)
    except Exception:
        value = None
    if value is None:
        try:
            from data_source import resolve
            t, _ = resolve(symbol)
            raw = (getattr(t, "info", None) or {}).get("marketCap")
            if raw:
                value = float(raw) / 1e7        # rupees -> crore
        except Exception:
            value = None
    with _lock:
        _mcap_cache[symbol] = (time.time(), value)
    return value


# ---------------------------------------------------------------------------
# Fiscal quarters — the Indian ones
# ---------------------------------------------------------------------------

def fiscal_quarter(day: dt.date):
    """(label, start, end) for the Indian fiscal quarter a date falls in."""
    y, m = day.year, day.month
    if m <= 3:
        q, start, fy = "Q4", dt.date(y, 1, 1), y
    elif m <= 6:
        q, start, fy = "Q1", dt.date(y, 4, 1), y + 1
    elif m <= 9:
        q, start, fy = "Q2", dt.date(y, 7, 1), y + 1
    else:
        q, start, fy = "Q3", dt.date(y, 10, 1), y + 1
    end = dt.date(start.year + (1 if start.month == 10 else 0),
                  (start.month + 3 - 1) % 12 + 1, 1) - dt.timedelta(days=1)
    return "%s FY%02d" % (q, fy % 100), start, end


def previous_quarter(day: dt.date):
    _, start, _ = fiscal_quarter(day)
    return fiscal_quarter(start - dt.timedelta(days=1))


# ---------------------------------------------------------------------------
# The scan
# ---------------------------------------------------------------------------

def _order_items(days: int):
    """
    Order announcements from the feed the app already polls.

    Returns (items, note, polled_ok). The wide walk over every day of the
    window runs on the first refresh and then every WIDE_POLL_EVERY seconds;
    in between, the feed's own three-day poll is enough, because the orders
    it has seen stay in its memory.
    """
    try:
        import announcements
    except Exception:
        return [], "The announcements feed is not available.", False
    try:
        wide = _run.get("wide_poll") or {}
        if (time.time() - wide.get("at", 0.0) > WIDE_POLL_EVERY
                or wide.get("days", 0) < days):
            announcements.poll(days=days)
            _run["wide_poll"] = {"at": time.time(), "days": days}
        else:
            announcements.poll_if_stale(background=False)
    except Exception as e:
        return [], "Could not refresh announcements: %s" % str(e)[:90], False
    return list(announcements.orders(days)), "", True


def _as_date(iso):
    try:
        return dt.datetime.fromisoformat(str(iso)).astimezone(IST).date()
    except Exception:
        return None


def _read_filing(filings_text, url, budget):
    """
    The filing's text, and what became of the attempt to read it.

    ("read", text)        the text layer was read
    ("unreadable", None)  the PDF has no text layer (a scan): any value it
                          states is in the picture, so this is NOT "no value"
    ("unread", None)      not downloaded this time: out of budget, or the
                          download failed. The next refresh tries again.

    `budget` is a dict {"left": n, "until": epoch}, spent only on documents
    that are not already cached.
    """
    hit = filings_text.cached(url)
    if hit is not None:
        return ("read", hit) if hit else ("unreadable", None)
    if budget["left"] <= 0 or time.time() >= budget["until"]:
        return ("unread", None)
    budget["left"] -= 1
    text = filings_text.extract(url)
    if text:
        return ("read", text)
    # extract() caches an empty string for a document with no text layer,
    # and nothing for a download or parse failure. The cache says which.
    return ("unreadable", None) if filings_text.cached(url) == "" else ("unread", None)


def _build_rows(days: int):
    """
    Read the window's order filings. Slow — it downloads PDFs — so it runs
    on the refresh thread, never inside a page request.

    Returns (rows, note, polled_ok).
    """
    orders, note, polled = _order_items(days)
    rows = []

    try:
        import filings_text
        can_read = filings_text.available()
    except Exception:
        filings_text, can_read = None, False
    budget = {"left": MAX_PDFS, "until": time.time() + SCAN_BUDGET}

    for item in orders:
        day = _as_date(item.get("at"))
        symbol = (item.get("symbol") or "").strip().upper()
        row = {
            "symbol": symbol or None,
            "company": item.get("company") or "",
            "headline": item.get("headline") or "",
            "at": item.get("at"),
            "date": day.isoformat() if day else None,
            "quarter": fiscal_quarter(day)[0] if day else None,
            "pdf": item.get("pdf"),
            # "read" when there is no document: the headline is all there is.
            "read_state": "read" if not item.get("pdf") else "unread",
            "value_cr": None,
            "value_basis": None,
            "value_confident": False,
            "currency_converted": False,
            "excerpt": None,
            "market_cap_cr": None,
            "pct_of_market_cap": None,
            "wow": False,
        }

        if can_read and item.get("pdf"):
            state, text = _read_filing(filings_text, item["pdf"], budget)
            row["read_state"] = state
            found = order_value_cr(text) if text else None
            if found:
                row.update({
                    "value_cr": found["value_cr"],
                    "value_basis": found["basis"],
                    "value_confident": found["confident"],
                    "currency_converted": found["currency_converted"],
                    "excerpt": found["excerpt"],
                })

        if row["value_cr"] and symbol:
            cap = market_cap_cr(symbol)
            if cap and cap > 0:
                row["market_cap_cr"] = round(cap, 2)
                row["pct_of_market_cap"] = round(100.0 * row["value_cr"] / cap, 2)
                row["wow"] = row["pct_of_market_cap"] >= WOW_MIN_PCT
        rows.append(row)

    _sort(rows)
    if not can_read:
        note = ("The PDF reader is not installed on this instance, so order "
                "values could not be read from the filings.")
    return rows, note, polled


def _sort(rows):
    rows.sort(key=lambda r: (r["pct_of_market_cap"] is None,
                             -(r["pct_of_market_cap"] or 0),
                             -(r["value_cr"] or 0),
                             r["at"] or ""))
    return rows


def _refresh(days: int):
    """One full refresh, synchronously. Records what it read and caches it."""
    rows, note, polled = _build_rows(days)
    # Every refresh writes down what it saw. This is how the ledger fills up
    # in normal operation — the quarter comparison reads from there, not from
    # a feed that only remembers three days. A filing not read yet is left
    # out: recording it as "no value" would be a permanent wrong answer.
    try:
        record([r for r in rows if r.get("read_state") != "unread"])
        # A day counts as watched only if the feed was actually reached.
        if polled:
            today = dt.datetime.now(IST).date()
            mark_covered([today - dt.timedelta(days=b) for b in range(days)])
    except Exception:
        pass
    with _lock:
        _cache[days] = {"at": time.time(), "rows": rows, "note": note}
    return rows, note


def refresh(days: int = 7) -> bool:
    """
    Start a refresh on a thread. One at a time; a refresh that failed is not
    retried for a minute, so an open page polling for news cannot turn one
    broken exchange call into a retry loop. Returns whether one was started.
    """
    with _lock:
        if _run["running"]:
            return False
        if _run["error"] and time.time() - (_run["finished"] or 0) < 60:
            return False
        _run.update({"running": True, "started": time.time(), "error": ""})

    def work():
        try:
            _refresh(days)
        except Exception as e:
            _run["error"] = str(e)[:140] or e.__class__.__name__
        finally:
            with _lock:
                _run["running"] = False
                _run["finished"] = time.time()

    threading.Thread(target=work, daemon=True, name="altaha-wow").start()
    return True


def refresh_if_stale(days: int = 7) -> bool:
    """For the cron tick: keep the answer warm so a page never waits."""
    with _lock:
        hit = _cache.get(days)
    if hit and time.time() - hit["at"] < CACHE_TTL:
        return False
    return refresh(days)


def scan(days: int = 7, force: bool = False, wait: bool = False) -> dict:
    """
    Recent order wins, sized against the company that won them.

    Answers at once. A fresh answer is returned as it is. A stale or missing
    one starts a refresh on a thread and returns the last answer meanwhile —
    on a cold start, the orders the ledger already holds for the window — with
    `refreshing` set, so the page can say it is checking for new filings and
    ask again. Reading filings inside the request is what left the page on
    "Reading the filings…" for minutes: forty PDF downloads, one after another.

    `wait=True` runs the refresh in the caller and returns its result, for
    tests and admin calls. Every row carries the filing it was read from, the
    excerpt the value came out of, and whether the filing labelled that
    figure as the order's value.
    """
    days = int(days)
    if wait:
        rows, note = _refresh(days)
        return _payload(rows, note, as_of=time.time())

    with _lock:
        hit = _cache.get(days)
    if hit and not force and time.time() - hit["at"] < CACHE_TTL:
        return _payload(hit["rows"], hit["note"], as_of=hit["at"],
                        refreshing=_run["running"])

    refresh(days)
    if hit:
        rows, note, as_of = hit["rows"], hit["note"], hit["at"]
    else:
        rows, note, as_of = recent(days), "", None
    return _payload(rows, note, as_of=as_of, refreshing=_run["running"],
                    from_ledger=not hit)


def _payload(rows, note, as_of=None, refreshing=False, from_ledger=False):
    priced = [r for r in rows if r["value_cr"] is not None]
    wow = [r for r in rows if r["wow"]]
    # A row from before read_state existed was read: unread rows were never
    # recorded, and the live scan always sets it.
    state = [r.get("read_state", "read") for r in rows]
    not_read = state.count("unread")
    unreadable = state.count("unreadable")
    return {
        "available": True,
        "threshold_pct": WOW_MIN_PCT,
        "rows": rows,
        "counts": {
            "orders": len(rows),
            "with_value": len(priced),
            "value_not_disclosed": len(rows) - len(priced) - not_read - unreadable,
            "unreadable": unreadable,
            "not_read": not_read,
            "wow": len(wow),
        },
        # When this answer was read from the filings, and whether a newer one
        # is being read now. A page that is told `refreshing` asks again.
        "as_of": (dt.datetime.fromtimestamp(as_of, IST).isoformat(timespec="seconds")
                  if as_of else None),
        "refreshing": bool(refreshing),
        "from_ledger": bool(from_ledger),
        "refresh_error": _run.get("error") or "",
        "note": note or "",
        "source": ("Exchange corporate announcements (BSE, or NSE when BSE is "
                   "unreachable), Regulation 30. Order values "
                   "are read from the filed document, not the headline."),
        "explain": (
            "An order is called WOW when its disclosed value is at least %g%% "
            "of the company's market capitalisation. Orders whose value the "
            "company did not disclose are listed but never ranked, and never "
            "given an assumed figure." % WOW_MIN_PCT),
    }


# ---------------------------------------------------------------------------
# Quarter on quarter
# ---------------------------------------------------------------------------

def quarter_comparison(today: dt.date = None) -> dict:
    """
    Disclosed order inflow this fiscal quarter against the previous one.

    Read from the ledger, not from the live feed: the announcements feed keeps
    three days, so a quarter compared out of it would be three days against
    nothing. The response says what date recording actually started, because
    a quarter that began before this instance did is a partial quarter and a
    reader is entitled to know that before drawing a conclusion from it.

    Only orders whose value the company disclosed are counted, which makes
    every total a floor rather than an estimate. How many were left out is
    reported alongside.
    """
    today = today or dt.datetime.now(IST).date()
    this_label, this_start, this_end = fiscal_quarter(today)
    prev_label, prev_start, prev_end = previous_quarter(today)
    since = recording_since()

    def bucket(start, end, label):
        got = history(start, end)
        valued = [r for r in got if r.get("value_cr")]
        wanted = _business_days(start, end, today)
        have = covered_days(start, end)
        missing = [d for d in wanted if d.isoformat() not in have]
        # A handful of missing days is a holiday or a blip; a quarter that is
        # mostly unseen is not a quarter. The line is drawn at a tenth.
        partial = bool(wanted) and len(missing) > max(2, len(wanted) // 10)
        return {
            "label": label,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "orders": len(got),
            "with_value": len(valued),
            "value_not_disclosed": len(got) - len(valued),
            "total_cr": round(sum(r["value_cr"] for r in valued), 2) if valued else 0.0,
            "companies": len({r["symbol"] for r in got if r.get("symbol")}),
            "biggest": max(
                ({"symbol": r["symbol"], "company": r["company"],
                  "value_cr": r["value_cr"],
                  "pct_of_market_cap": r["pct_of_market_cap"]} for r in valued),
                key=lambda r: r["value_cr"], default=None),
            # A quarter that started before this instance began recording is
            # not a quarter, and comparing against it would understate it.
            "partial": partial,
            "trading_days": len(wanted),
            "days_not_recorded": len(missing),
        }

    now_b = bucket(this_start, this_end, this_label)
    prev_b = bucket(prev_start, prev_end, prev_label)
    change = None
    if prev_b["total_cr"] > 0 and not prev_b["partial"]:
        change = round(100.0 * (now_b["total_cr"] - prev_b["total_cr"])
                       / prev_b["total_cr"], 1)

    comparable = not (now_b["partial"] or prev_b["partial"])
    return {
        "this_quarter": now_b,
        "previous_quarter": prev_b,
        "change_pct": change,
        "change_cr": round(now_b["total_cr"] - prev_b["total_cr"], 2),
        "comparable": comparable,
        "recording_since": since,
        "caveat": (
            "Counts only orders whose value the company disclosed, so every "
            "total is a floor on order inflow rather than a complete order "
            "book." + ("" if comparable else
                       " One of these quarters began before this service "
                       "started recording, so the two are not yet comparable "
                       "and no percentage change is shown.")),
    }


# ---------------------------------------------------------------------------
# The ledger
#
# The announcements feed keeps three days. A quarter-on-quarter comparison over
# a three-day memory is not a comparison, so order events are written down as
# they are seen and never rewritten — the same append-only discipline the
# point-in-time store uses, and for the same reason: a number that can be
# revised after the fact is a number you cannot check.
#
# The table is small. A busy quarter is a few hundred rows.
# ---------------------------------------------------------------------------

import sqlite3
from contextlib import contextmanager

DATA_DIR = (os.environ.get("DATA_DIR", "").strip()
            or os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(DATA_DIR, "wow_orders.db")

_db_lock = threading.Lock()
_db_ready = {"done": False}


@contextmanager
def _db():
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    try:
        if not _db_ready["done"]:
            with _db_lock:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS orders (
                        key            TEXT PRIMARY KEY,
                        seen_at        TEXT NOT NULL,
                        date           TEXT,
                        at             TEXT,
                        symbol         TEXT,
                        company        TEXT,
                        headline       TEXT,
                        pdf            TEXT,
                        value_cr       REAL,
                        value_confident INTEGER,
                        currency_converted INTEGER,
                        market_cap_cr  REAL,
                        pct_of_market_cap REAL
                    )""")
                # The sentence the value came out of, and why it was chosen,
                # so an answer served from the ledger on a cold start still
                # shows its evidence. Added after the table first shipped.
                have = {r[1] for r in conn.execute("PRAGMA table_info(orders)")}
                for col in ("excerpt", "value_basis"):
                    if col not in have:
                        conn.execute("ALTER TABLE orders ADD COLUMN %s TEXT" % col)
                conn.execute("CREATE INDEX IF NOT EXISTS orders_date ON orders(date)")
                # Which days this service has actually looked at.
                #
                # Without this, "the earliest order we hold" has to stand in
                # for "when we started watching", and those are different
                # facts: a quarter with no orders in its first six weeks looks
                # identical to a quarter we were not recording for. One of
                # those is a real lull worth comparing; the other is a hole.
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS coverage (
                        day     TEXT PRIMARY KEY,
                        seen_at TEXT NOT NULL
                    )""")
                conn.commit()
                _db_ready["done"] = True
        yield conn
    finally:
        conn.close()


def _key(row) -> str:
    import hashlib
    raw = (row.get("pdf") or "") or "%s|%s|%s" % (
        row.get("company") or "", row.get("date") or "", (row.get("headline") or "")[:120])
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:24]


def record(rows) -> int:
    """
    Write down what was seen. INSERT OR IGNORE, so the first record of an
    event wins and a later re-scan can never restate it.

    One exception, and only in one direction: an event first recorded with
    no value gets the value when a later read finds one. Until refreshes had
    a reading budget, filings past the fortieth were recorded unread, as if
    they stated no value. Filling in a blank is not restating a number. A
    value once recorded is never changed.
    """
    if not rows:
        return 0
    now = dt.datetime.now(IST).isoformat()
    written = 0
    try:
        with _db() as conn:
            for r in rows:
                if not r.get("date"):
                    continue
                vals = (r.get("value_cr"), 1 if r.get("value_confident") else 0,
                        1 if r.get("currency_converted") else 0,
                        r.get("market_cap_cr"), r.get("pct_of_market_cap"),
                        r.get("excerpt"), r.get("value_basis"))
                cur = conn.execute(
                    "INSERT OR IGNORE INTO orders (key, seen_at, date, at, symbol,"
                    " company, headline, pdf, value_cr, value_confident,"
                    " currency_converted, market_cap_cr, pct_of_market_cap,"
                    " excerpt, value_basis)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (_key(r), now, r.get("date"), r.get("at"), r.get("symbol"),
                     r.get("company"), r.get("headline"), r.get("pdf")) + vals)
                if cur.rowcount:
                    written += cur.rowcount
                elif r.get("value_cr") is not None:
                    cur = conn.execute(
                        "UPDATE orders SET value_cr=?, value_confident=?,"
                        " currency_converted=?, market_cap_cr=?,"
                        " pct_of_market_cap=?, excerpt=?, value_basis=?"
                        " WHERE key=? AND value_cr IS NULL", vals + (_key(r),))
                    written += cur.rowcount or 0
            conn.commit()
    except Exception:
        return 0
    return written


def recent(days: int = 7):
    """
    The window's orders as the ledger holds them, shaped like live rows.

    What a cold start shows while the first refresh reads the filings: the
    instance restarted, its memory is empty, but the disk remembers.
    """
    since = (dt.datetime.now(IST).date() - dt.timedelta(days=max(1, days) - 1))
    out = []
    for r in history(since, dt.date(9999, 12, 31)):
        day = _as_date(r.get("at")) or (
            dt.date.fromisoformat(r["date"]) if r.get("date") else None)
        pct = r.get("pct_of_market_cap")
        out.append({
            "symbol": r.get("symbol"), "company": r.get("company") or "",
            "headline": r.get("headline") or "", "at": r.get("at"),
            "date": r.get("date"),
            "quarter": fiscal_quarter(day)[0] if day else None,
            "pdf": r.get("pdf"), "read_state": "read",
            "value_cr": r.get("value_cr"),
            "value_basis": r.get("value_basis"),
            "value_confident": bool(r.get("value_confident")),
            "currency_converted": bool(r.get("currency_converted")),
            "excerpt": r.get("excerpt"),
            "market_cap_cr": r.get("market_cap_cr"),
            "pct_of_market_cap": pct,
            "wow": pct is not None and pct >= WOW_MIN_PCT,
        })
    return _sort(out)


def history(start: dt.date, end: dt.date):
    try:
        with _db() as conn:
            rows = conn.execute(
                "SELECT * FROM orders WHERE date >= ? AND date <= ? ORDER BY date DESC",
                (start.isoformat(), end.isoformat())).fetchall()
            return [dict(r) for r in rows]
    except Exception:
        return []


def mark_covered(days):
    """Write down which days were actually fetched."""
    if not days:
        return
    now = dt.datetime.now(IST).isoformat()
    try:
        with _db() as conn:
            conn.executemany(
                "INSERT OR IGNORE INTO coverage (day, seen_at) VALUES (?,?)",
                [(d.isoformat(), now) for d in days])
            conn.commit()
    except Exception:
        pass


def covered_days(start: dt.date, end: dt.date):
    try:
        with _db() as conn:
            rows = conn.execute(
                "SELECT day FROM coverage WHERE day >= ? AND day <= ?",
                (start.isoformat(), end.isoformat())).fetchall()
            return {r["day"] for r in rows}
    except Exception:
        return set()


def _business_days(start: dt.date, end: dt.date, today: dt.date):
    """Weekdays in the range that have already happened."""
    out, day = [], start
    stop = min(end, today)
    while day <= stop:
        if day.weekday() < 5:
            out.append(day)
        day += dt.timedelta(days=1)
    return out


def recording_since():
    try:
        with _db() as conn:
            row = conn.execute("SELECT MIN(day) AS d FROM coverage").fetchone()
            return row["d"] if row and row["d"] else None
    except Exception:
        return None


def backfill(days: int = 45, max_days: int = 120) -> dict:
    """
    Walk back through the exchange's announcement archive and record order
    events this instance never saw live.

    Bounded and explicit: this is a few hundred requests, so it belongs in a
    background job or an admin call, never in a page load. Weekends are
    skipped because the exchanges are shut.
    """
    try:
        import announcements
    except Exception:
        return {"ok": False, "error": "announcements unavailable"}
    try:
        import filings_text
        can_read = filings_text.available()
    except Exception:
        filings_text, can_read = None, False

    days = max(1, min(int(days or 45), max_days))
    announcements._build_maps()
    today = dt.datetime.now(IST).date()
    seen, recorded, unread = 0, 0, 0
    # A backfill is an admin call, not a page: it gets the PDF cap but no
    # clock. Filings past the cap are left unrecorded rather than recorded
    # as stating no value; the next backfill or live refresh reads them.
    budget = {"left": MAX_PDFS, "until": float("inf")}

    for back in range(days):
        day = today - dt.timedelta(days=back)
        if day.weekday() >= 5:
            continue
        seen_day = False
        for page in range(1, 4):
            raw_rows, _note = announcements._fetch_day(day, page)
            if not raw_rows:
                break
            seen_day = True
            batch = []
            for raw in raw_rows:
                item = announcements._norm(raw)
                if not item or item.get("category") != "Order win":
                    continue
                seen += 1
                d = _as_date(item.get("at")) or day
                row = {
                    "symbol": (item.get("symbol") or "").strip().upper() or None,
                    "company": item.get("company") or "",
                    "headline": item.get("headline") or "",
                    "at": item.get("at"), "date": d.isoformat(),
                    "pdf": item.get("pdf"),
                    "value_cr": None, "value_confident": False,
                    "currency_converted": False,
                    "market_cap_cr": None, "pct_of_market_cap": None,
                }
                if row["pdf"]:
                    state, text = (_read_filing(filings_text, row["pdf"], budget)
                                   if can_read else ("unread", None))
                    if state == "unread":
                        unread += 1
                        continue
                    found = order_value_cr(text) if text else None
                    if found:
                        row.update({"value_cr": found["value_cr"],
                                    "value_confident": found["confident"],
                                    "currency_converted": found["currency_converted"],
                                    "excerpt": found["excerpt"],
                                    "value_basis": found["basis"]})
                if row["value_cr"] and row["symbol"]:
                    cap = market_cap_cr(row["symbol"])
                    if cap and cap > 0:
                        row["market_cap_cr"] = round(cap, 2)
                        row["pct_of_market_cap"] = round(
                            100.0 * row["value_cr"] / cap, 2)
                batch.append(row)
            recorded += record(batch)
        if seen_day:
            mark_covered([day])
    return {"ok": True, "days": days, "orders_seen": seen,
            "newly_recorded": recorded,
            "pdfs_read": MAX_PDFS - budget["left"],
            "left_unread": unread}
