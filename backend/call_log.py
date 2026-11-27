"""
Altaha Screener — the Track record (the call log)

WHAT THIS ANSWERS
"When did Altaha first put this on the list, what exactly did it say, and what
has it returned since?" The Ideas tab is rebuilt from the latest scan every
time it loads, so until this file a call had no date. A stock that had sat on
the list for two weeks looked identical to one that arrived this morning, and
a call that was dropped simply vanished — along with any way to check it.

This is the one record of the site's ideas. There used to be two — this log,
and a Tracker of ideas added by hand — which answered the same question from
two ledgers. The page called Track record now reads this file alone: every
idea, recorded by the scan that generated it, with its return from that day.

WHAT A CALL IS
One (symbol, horizon, setup) on the Ideas list, with the stance and levels it
carried: BUY ZONE with a buy range, stop and target; BREAKOUT WATCH; WAIT. It
opens the first time a scan puts it on the list and closes exactly once:

  · stop      a later scan priced it at or below the stop it was given
  · target    a later scan priced it at or above its first target
  · dropped   a later scan no longer lists it

Stop and target are checked against the levels the call carried BEFORE the
new scan redrew them. Checking after would let a breached stop be quietly
moved under the price, and the record would never show a loss.

A stock that comes back after closing is a NEW call with its own date. The old
one keeps its outcome; reopening it would let the log flatter itself.

Every change in between — the stance moving from BREAKOUT WATCH to BUY ZONE,
the levels being redrawn — is an event on the call's timeline, dated.

WHEN IT RECORDS
Once per scan per horizon, never per page view. The list a reader sees can
shift between page loads as the news feed catches up; recording on every load
would turn that wobble into calls opened and closed within the hour. Recording
keys on the scan's own timestamp, so the second and the hundredth view of the
same scan change nothing.

TWO RETURNS, AND WHICH ONE LEADS
  · since     from the price on the day of the idea to the latest scan price,
              as if it was bought that day and nothing was done after. Every
              idea has one, open or closed, and it is the figure the record
              leads with and averages.
  · move      from the same price to where the call closed (stop, target or
              dropped), or to the latest scan while it is still open. For an
              open call the two are the same number.
A call whose stock is no longer in the scan has no latest price; its "since"
is then its closing move, and the row says the price is the closing one.

AGAINST THE INDEX
Return alone mostly measures the market. Given the index's daily closes, each
idea also carries the index's move over the same days and the difference. The
window runs from the first index close on or after the idea's day to the last
one on or before the day its "since" price was read. An idea made today has
no such window yet and carries no index figure.

PRICES
Every price here is a scan price — what the universe scan read for the stock —
so "since the idea" means "from the scan that made the call to the latest
scan", and the page names that scan. A stop that was touched and recovered
between two scans is not seen. The page says so rather than implying an
intraday check that does not happen.

STORAGE
DATA_DIR/call_log.db, SQLite in WAL mode, standard library only. A call's
opening date and price are written once and never updated.
"""

import bisect
import csv
import datetime as dt
import io
import os
import sqlite3
import statistics
import threading
from contextlib import contextmanager

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("DATA_DIR", "").strip() or HERE
try:
    os.makedirs(DATA_DIR, exist_ok=True)
except Exception:
    DATA_DIR = HERE

DB_PATH = os.environ.get("ALTAHA_CALL_DB", "").strip() or os.path.join(DATA_DIR, "call_log.db")

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
# The tested lists whose calls are logged (leaders.py), then the lists they
# replaced. The old keys stay valid so the calls already in the log keep
# their labels: this week and momentum were folded into the month and
# long-term lists in December 2026, and short and medium before them.
PICK_HORIZONS = ("month", "long")
RETIRED_HORIZONS = ("week", "momentum")
LEGACY_HORIZONS = ("short", "medium")
HORIZONS = PICK_HORIZONS + RETIRED_HORIZONS + LEGACY_HORIZONS
HORIZON_LABEL = {"month": "Swing / This month", "long": "Long-term compounders",
                 "week": "This week", "momentum": "Momentum",
                 "short": "Short term", "medium": "Medium term"}
# Why an open call on a retired list was closed: the list that took its place.
RETIRED_NOTE = {"week": "List replaced by Swing / This month.",
                "momentum": "List replaced by Long-term compounders."}


def _anchored(setup_key):
    """A tested pick keeps the exit line it was called with. Redrawing it from
    each new scan's price would move a line the reader was told to act on."""
    return str(setup_key or "").startswith("pick_")

# A redrawn level that moved less than this is rounding, not a new plan, and
# logging it would bury the events that matter.
LEVEL_CHANGE_PCT = 0.5

METHOD = ("Each idea is dated by the scan that first listed it, and recorded then, whether "
          "or not it goes on to work. Its return is measured from that scan's price to the "
          "latest scan's price, as if it was bought that day and nothing was done after; "
          "where the list later closed the call, at a stop, a target or by dropping it, "
          "that is shown beside it. Prices are scan prices: stop and target are checked "
          "against each new scan's price using the levels the call carried before that scan, "
          "and a level touched and recovered between two scans is not seen. A stock that "
          "returns after a call closes is a new idea with its own date.")
INDEX_METHOD = ("The index figure is {name} over the same days, from its close on the day "
                "of the idea to its latest close.")

SCHEMA = """
CREATE TABLE IF NOT EXISTS calls (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  symbol          TEXT NOT NULL,
  name            TEXT,
  sector          TEXT,
  horizon         TEXT NOT NULL,
  setup_key       TEXT NOT NULL DEFAULT '',
  setup           TEXT,
  hold            TEXT,
  called_at       TEXT NOT NULL,
  called_scan     TEXT,
  called_price    REAL,
  called_stance   TEXT,
  stance          TEXT,
  entry           REAL,
  stop            REAL,
  target          REAL,
  rr              REAL,
  conviction      REAL,
  band            TEXT,
  last_at         TEXT,
  last_price      REAL,
  scans_seen      INTEGER NOT NULL DEFAULT 1,
  status          TEXT NOT NULL DEFAULT 'open',
  closed_at       TEXT,
  closed_price    REAL,
  outcome         TEXT
);
CREATE INDEX IF NOT EXISTS ix_calls_open ON calls (status, horizon);
CREATE INDEX IF NOT EXISTS ix_calls_symbol ON calls (symbol, called_at);
CREATE TABLE IF NOT EXISTS call_events (
  call_id  INTEGER NOT NULL,
  at       TEXT NOT NULL,
  kind     TEXT NOT NULL,
  stance   TEXT,
  price    REAL,
  note     TEXT
);
CREATE INDEX IF NOT EXISTS ix_events_call ON call_events (call_id, at);
CREATE TABLE IF NOT EXISTS recorded_scans (
  horizon  TEXT NOT NULL,
  scan     TEXT NOT NULL,
  at       TEXT NOT NULL,
  PRIMARY KEY (horizon, scan)
);
CREATE TABLE IF NOT EXISTS list_recipes (
  horizon  TEXT NOT NULL,
  recipe   TEXT NOT NULL,
  since    TEXT NOT NULL,
  PRIMARY KEY (horizon, recipe)
);
"""

_write_lock = threading.Lock()
_local = threading.local()


def _connect():
    conn = getattr(_local, "conn", None)
    if conn is not None and getattr(_local, "path", None) == DB_PATH:
        return conn
    conn = sqlite3.connect(DB_PATH, timeout=10, check_same_thread=False)
    # Transactions are opened by hand in _tx(), so the module's implicit ones
    # must not race them.
    conn.isolation_level = None
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
    except sqlite3.DatabaseError:
        pass
    conn.executescript(SCHEMA)
    _local.conn, _local.path = conn, DB_PATH
    return conn


@contextmanager
def _tx():
    with _write_lock:
        conn = _connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f and f not in (float("inf"), float("-inf")) else None


def _iso(t: dt.datetime) -> str:
    if t.tzinfo is None:
        t = t.replace(tzinfo=dt.timezone.utc)
    return t.astimezone(dt.timezone.utc).isoformat(timespec="seconds")


def _parse(iso):
    if not iso:
        return None
    try:
        t = dt.datetime.fromisoformat(str(iso))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)


def scan_time(scanned_at):
    """
    The moment a scan finished, as an aware datetime, or None.

    scanned_at is written by scan.py with the server's naive local clock
    ("29 Oct 2026, 11:42"). astimezone() on a naive value reads it as that
    same local clock, which is exactly what wrote it — UTC on the host.
    """
    head = str(scanned_at or "").split(" (")[0].strip()
    for fmt in ("%d %b %Y, %H:%M", "%d %b %Y"):
        try:
            return dt.datetime.strptime(head, fmt).astimezone(dt.timezone.utc)
        except ValueError:
            continue
    return None


def when(iso):
    """{iso, date, weekday, day, time} in IST, for one stored timestamp."""
    t = _parse(iso)
    if t is None:
        return None
    local = t.astimezone(IST)
    return {"iso": iso, "date": local.date().isoformat(),
            "weekday": local.strftime("%A"), "day": local.strftime("%a %d %b %Y"),
            "time": local.strftime("%H:%M IST")}


def _inr(v):
    return "—" if v is None else f"₹{v:,.2f}"


def _plan_line(stance, entry, stop, target):
    bits = [stance or "On the list"]
    if entry is not None:
        bits.append(f"buy near {_inr(entry)}")
    if stop is not None:
        bits.append(f"stop {_inr(stop)}")
    if target is not None:
        bits.append(f"target {_inr(target)}")
    return " · ".join(bits)


def _moved(a, b):
    if a is None and b is None:
        return False
    if a is None or b is None:
        return True
    return abs(a - b) / max(abs(a), 1e-9) * 100 >= LEVEL_CHANGE_PCT


def _levels(row):
    plan = row.get("plan") or {}
    target = plan.get("t1")
    if target is None:
        target = (plan.get("targets") or [None])[0]
    return {"stance": (plan.get("stance") or "").strip() or None,
            "entry": _num(plan.get("entry")), "stop": _num(plan.get("stop")),
            "target": _num(target), "rr": _num(plan.get("rr"))}


def _event(conn, call_id, at, kind, stance=None, price=None, note=None):
    conn.execute("INSERT INTO call_events(call_id,at,kind,stance,price,note) VALUES(?,?,?,?,?,?)",
                 (call_id, at, kind, stance, price, note))


def _close(conn, call, at, price, outcome, note):
    conn.execute("UPDATE calls SET status='closed', closed_at=?, closed_price=?, outcome=? WHERE id=?",
                 (at, price, outcome, call["id"]))
    _event(conn, call["id"], at, outcome, call["stance"], price, note)


# ---------------------------------------------------------------------------
# Recording
# ---------------------------------------------------------------------------

def recorded(horizon: str, scanned_at: str) -> bool:
    if not scanned_at:
        return False
    row = _connect().execute("SELECT 1 FROM recorded_scans WHERE horizon=? AND scan=?",
                             (horizon, str(scanned_at))).fetchone()
    return row is not None


def record(horizon: str, rows: list, scanned_at: str, prices: dict | None = None,
           now: dt.datetime | None = None, recipe: str | None = None) -> dict:
    """
    Write one scan's Ideas list for one horizon. Idempotent per scan.

    rows    the list exactly as /ideas served it, best first
    prices  {SYMBOL: price} for the whole scored universe in the same scan, so
            a call that left the list still gets a closing price
    recipe  the leaders.RECIPE stamp the list was ranked under. The first scan
            logged under a stamp dates it (recipe_since), so a list rebuilt
            under its old name does not count the calls its old recipe made
            as its own.
    """
    if horizon not in HORIZONS:
        return {"recorded": False, "reason": "unknown horizon"}
    if not scanned_at:
        return {"recorded": False, "reason": "the scan has no timestamp"}
    if "partial" in str(scanned_at):
        return {"recorded": False, "reason": "the scan is still running"}
    prices = {str(k).upper(): _num(v) for k, v in (prices or {}).items()}
    at = _iso(scan_time(scanned_at) or now or dt.datetime.now(dt.timezone.utc))
    listed = {}
    for r in rows or []:
        sym = str(r.get("symbol") or "").strip().upper()
        if sym:
            listed.setdefault((sym, r.get("setup_key") or ""), r)

    opened, kept, closed = 0, 0, {"stop": 0, "target": 0, "dropped": 0}
    with _tx() as conn:
        if conn.execute("SELECT 1 FROM recorded_scans WHERE horizon=? AND scan=?",
                        (horizon, str(scanned_at))).fetchone():
            return {"recorded": False, "reason": "this scan is already in the log"}

        # 1. Judge every open call against the levels it carried INTO this scan.
        still_open = {}
        for c in conn.execute("SELECT * FROM calls WHERE status='open' AND horizon=?", (horizon,)):
            key = (c["symbol"], c["setup_key"] or "")
            row = listed.get(key)
            price = _num(row.get("price")) if row else None
            if price is None:
                price = prices.get(c["symbol"])
            if price is not None and c["stop"] is not None and price <= c["stop"]:
                _close(conn, c, at, price, "stop",
                       f"Scan price {_inr(price)} at or below the {_inr(c['stop'])} stop.")
                closed["stop"] += 1
            elif price is not None and c["target"] is not None and price >= c["target"]:
                _close(conn, c, at, price, "target",
                       f"Scan price {_inr(price)} at or above the {_inr(c['target'])} target.")
                closed["target"] += 1
            elif row is None:
                _close(conn, c, at, price, "dropped",
                       "No longer on the list in this scan.")
                closed["dropped"] += 1
            else:
                still_open[key] = c

        # 2. Carry forward what is still listed; open whatever is new.
        for key, r in listed.items():
            sym, setup_key = key
            lv = _levels(r)
            price = _num(r.get("price"))
            if price is None:
                price = prices.get(sym)
            c = still_open.get(key)
            if c is None:
                cur = conn.execute(
                    "INSERT INTO calls(symbol,name,sector,horizon,setup_key,setup,hold,called_at,"
                    "called_scan,called_price,called_stance,stance,entry,stop,target,rr,conviction,"
                    "band,last_at,last_price) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (sym, r.get("name"), r.get("sector"), horizon, setup_key, r.get("setup"),
                     r.get("horizon"), at, str(scanned_at), price, lv["stance"], lv["stance"],
                     lv["entry"], lv["stop"], lv["target"], lv["rr"], _num(r.get("conviction")),
                     r.get("conviction_band"), at, price))
                _event(conn, cur.lastrowid, at, "called", lv["stance"], price,
                       _plan_line(lv["stance"], lv["entry"], lv["stop"], lv["target"]))
                opened += 1
                continue
            if _anchored(setup_key):
                lv = {"stance": c["stance"], "entry": c["entry"], "stop": c["stop"],
                      "target": c["target"], "rr": c["rr"]}
            if lv["stance"] != c["stance"]:
                _event(conn, c["id"], at, "stance", lv["stance"], price,
                       f"{c['stance'] or 'On the list'} → {lv['stance'] or 'On the list'}")
            elif (_moved(c["entry"], lv["entry"]) or _moved(c["stop"], lv["stop"])
                  or _moved(c["target"], lv["target"])):
                _event(conn, c["id"], at, "levels", lv["stance"], price,
                       "Levels redrawn: " + _plan_line(None, lv["entry"], lv["stop"], lv["target"])
                       .replace("On the list · ", ""))
            conn.execute(
                "UPDATE calls SET stance=?,entry=?,stop=?,target=?,rr=?,conviction=?,band=?,"
                "last_at=?,last_price=?,scans_seen=scans_seen+1 WHERE id=?",
                (lv["stance"], lv["entry"], lv["stop"], lv["target"], lv["rr"],
                 _num(r.get("conviction")), r.get("conviction_band"), at, price, c["id"]))
            kept += 1

        conn.execute("INSERT INTO recorded_scans(horizon,scan,at) VALUES(?,?,?)",
                     (horizon, str(scanned_at), _iso(now or dt.datetime.now(dt.timezone.utc))))
        if recipe:
            conn.execute("INSERT OR IGNORE INTO list_recipes(horizon,recipe,since) VALUES(?,?,?)",
                         (horizon, str(recipe), at))
    return {"recorded": True, "horizon": horizon, "opened": opened,
            "carried": kept, "closed": closed, "at": at}


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------

def _pct(now, then):
    if now is None or not then:
        return None
    return round(100 * (now / then - 1), 2)


def _index_series(index):
    """[(date, close)] oldest first, from pairs or a {date: close} mapping."""
    if not index:
        return []
    items = index.items() if isinstance(index, dict) else index
    out = []
    for day, close in items:
        close = _num(close)
        if day and close:
            out.append((str(day)[:10], close))
    out.sort()
    return out


def _index_move(series, start, end):
    """
    The index's move, in percent, from its first close on or after `start` to
    its last close on or before `end` (both ISO dates). None until those are
    two different closes: an idea made today has no index window yet, and
    printing 0.00% for it would read as "the market did nothing".
    """
    if not series or not start or not end:
        return None
    dates = [d for d, _ in series]
    i = bisect.bisect_left(dates, start)
    j = bisect.bisect_right(dates, end) - 1
    if i >= len(dates) or j <= i:
        return None
    return _pct(series[j][1], series[i][1])


def _shape(c, prices, events, now, series=()):
    open_ = c["status"] == "open"
    latest = prices.get(c["symbol"])
    price_now = latest if open_ else c["closed_price"]
    if open_ and price_now is None:
        price_now = c["last_price"]
    end = _parse(c["closed_at"]) if not open_ else now
    start = _parse(c["called_at"])
    days = max(0, (end - start).days) if end and start else None
    called = when(c["called_at"])

    # Since the idea, nothing done after. An open call is priced at the latest
    # scan already; a closed one is priced there too while its stock is still
    # in the scan, and at its closing price once it is not.
    if open_ or latest is not None:
        since_price, since_basis, since_end = (price_now if open_ else latest), "latest", now
    else:
        since_price, since_basis, since_end = c["closed_price"], "close", end
    since_pct = _pct(since_price, c["called_price"])
    since_days = max(0, (since_end - start).days) if since_end and start else None
    index_pct = None
    if series and called and since_end:
        index_pct = _index_move(series, called["date"],
                                since_end.astimezone(IST).date().isoformat())
    vs_index = (round(since_pct - index_pct, 2)
                if since_pct is not None and index_pct is not None else None)
    return {
        "id": c["id"], "symbol": c["symbol"], "name": c["name"], "sector": c["sector"],
        "horizon": c["horizon"], "horizon_label": HORIZON_LABEL.get(c["horizon"], c["horizon"]),
        "setup_key": c["setup_key"], "setup": c["setup"], "hold": c["hold"],
        "called": called, "called_scan": c["called_scan"],
        "called_price": c["called_price"], "called_stance": c["called_stance"],
        "stance": c["stance"], "entry": c["entry"], "stop": c["stop"], "target": c["target"],
        "rr": c["rr"], "conviction": c["conviction"], "band": c["band"],
        "status": c["status"], "outcome": c["outcome"], "closed": when(c["closed_at"]),
        "price_now": price_now, "move_pct": _pct(price_now, c["called_price"]),
        "days": days, "scans_seen": c["scans_seen"],
        "since_price": since_price, "since_pct": since_pct, "since_basis": since_basis,
        "since_days": since_days, "index_pct": index_pct, "vs_index_pct": vs_index,
        "events": [{"at": when(e["at"]), "kind": e["kind"], "stance": e["stance"],
                    "price": e["price"], "note": e["note"]} for e in events],
    }


def _events_for(conn, ids):
    out = {i: [] for i in ids}
    for chunk in (ids[i:i + 400] for i in range(0, len(ids), 400)):
        marks = ",".join("?" * len(chunk))
        for e in conn.execute(f"SELECT * FROM call_events WHERE call_id IN ({marks}) "
                              f"ORDER BY at, rowid", chunk):
            out[e["call_id"]].append(e)
    return out


def _summary(rows, now):
    moves = [r["move_pct"] for r in rows if r["move_pct"] is not None]
    outcomes = {"stop": 0, "target": 0, "dropped": 0}
    for r in rows:
        if r["outcome"] in outcomes:
            outcomes[r["outcome"]] += 1
    week_start = (now.astimezone(IST).date() - dt.timedelta(days=now.astimezone(IST).weekday()))
    first = min((r["called"]["date"] for r in rows if r["called"]), default=None)
    since = [r["since_pct"] for r in rows if r["since_pct"] is not None]
    held = [r["since_days"] for r in rows if r["since_pct"] is not None and r["since_days"] is not None]
    # Only the ideas the index could be measured against, on both sides of the
    # comparison: averaging every idea's return against some ideas' index
    # would compare two different sets.
    both = [r for r in rows if r["vs_index_pct"] is not None]
    return {
        # Since the idea, nothing done after — what the record leads with.
        "since_priced": len(since),
        "up_since": sum(1 for m in since if m > 0),
        "up_since_pct": round(100 * sum(1 for m in since if m > 0) / len(since), 1) if since else None,
        "avg_since_pct": round(statistics.fmean(since), 2) if since else None,
        "median_since_pct": round(statistics.median(since), 2) if since else None,
        "median_days": statistics.median(held) if held else None,
        "index_priced": len(both),
        "beat_index": sum(1 for r in both if r["vs_index_pct"] > 0),
        "beat_index_pct": (round(100 * sum(1 for r in both if r["vs_index_pct"] > 0) / len(both), 1)
                           if both else None),
        "avg_index_pct": round(statistics.fmean(r["index_pct"] for r in both), 2) if both else None,
        "avg_vs_index_pct": (round(statistics.fmean(r["vs_index_pct"] for r in both), 2)
                             if both else None),
        "calls": len(rows),
        "open": sum(1 for r in rows if r["status"] == "open"),
        "closed": sum(1 for r in rows if r["status"] == "closed"),
        "outcomes": outcomes,
        "this_week": sum(1 for r in rows if r["called"] and r["called"]["date"] >= week_start.isoformat()),
        "priced": len(moves),
        "in_profit": sum(1 for m in moves if m > 0),
        "in_profit_pct": round(100 * sum(1 for m in moves if m > 0) / len(moves), 1) if moves else None,
        "median_move_pct": round(statistics.median(moves), 2) if moves else None,
        "first_logged": first,
    }


def _by_day(rows, now, days=14):
    counts = {}
    for r in rows:
        if r["called"]:
            counts[r["called"]["date"]] = counts.get(r["called"]["date"], 0) + 1
    today = now.astimezone(IST).date()
    out = []
    for i in range(days - 1, -1, -1):
        d = today - dt.timedelta(days=i)
        out.append({"date": d.isoformat(), "weekday": d.strftime("%a"),
                    "label": d.strftime("%d %b"), "calls": counts.get(d.isoformat(), 0)})
    return out


def listing(horizon: str = "", status: str = "", symbol: str = "", limit: int = 300,
            prices: dict | None = None, now: dt.datetime | None = None,
            index=None, index_name: str = "", since: str = "") -> dict:
    """
    Ideas newest first, each with its timeline, plus a summary of all of them.

    prices  {SYMBOL: price} from the latest scan — what "since the idea" is
            measured to
    index   the index's daily closes, as [(date, close)] or {date: close}, for
            the same-days comparison; without it the index fields are None
    since   only the calls made at or after this time (recipe_since)
    """
    now = now or dt.datetime.now(dt.timezone.utc)
    prices = {str(k).upper(): _num(v) for k, v in (prices or {}).items()}
    series = _index_series(index)
    where, args = [], []
    if horizon in HORIZONS:
        where.append("horizon=?"); args.append(horizon)
    if status in ("open", "closed"):
        where.append("status=?"); args.append(status)
    if symbol:
        where.append("symbol=?"); args.append(symbol.strip().upper())
    if since:
        where.append("called_at>=?"); args.append(str(since))
    sql = "SELECT * FROM calls" + (" WHERE " + " AND ".join(where) if where else "")
    conn = _connect()
    calls = conn.execute(sql + " ORDER BY called_at DESC, id DESC", args).fetchall()
    events = _events_for(conn, [c["id"] for c in calls])
    rows = [_shape(c, prices, events.get(c["id"], []), now, series) for c in calls]
    last = conn.execute("SELECT scan, at FROM recorded_scans ORDER BY at DESC LIMIT 1").fetchone()
    return {
        "rows": rows[:max(1, min(int(limit or 300), 1000))],
        "total": len(rows),
        "summary": _summary(rows, now),
        "by_day": _by_day(rows, now),
        "last_scan": last["scan"] if last else None,
        "horizons": [{"key": h, "label": HORIZON_LABEL[h]} for h in HORIZONS
                     if any(r["horizon"] == h for r in rows)],
        "index_name": (index_name or "the index") if series else None,
        "method": METHOD + (" " + INDEX_METHOD.format(name=index_name or "the index")
                            if series else ""),
    }


def recipe_since(horizon: str, recipe: str):
    """When the first scan ranked under `recipe` was logged for this list, or
    None if none has been. Calls made before it belong to an earlier recipe."""
    if not horizon or not recipe:
        return None
    row = _connect().execute("SELECT since FROM list_recipes WHERE horizon=? AND recipe=?",
                             (horizon, str(recipe))).fetchone()
    return row["since"] if row else None


def open_index(horizon: str, prices: dict | None = None) -> dict:
    """{(SYMBOL, setup_key): compact call} for the open calls of one horizon.
    What the Ideas list uses to say how long each row has been there."""
    prices = {str(k).upper(): _num(v) for k, v in (prices or {}).items()}
    out = {}
    for c in _connect().execute("SELECT * FROM calls WHERE status='open' AND horizon=?", (horizon,)):
        now_px = prices.get(c["symbol"], c["last_price"])
        out[(c["symbol"], c["setup_key"] or "")] = {
            "id": c["id"], "called": when(c["called_at"]), "called_price": c["called_price"],
            "called_stance": c["called_stance"], "scans_seen": c["scans_seen"],
            "entry": c["entry"], "stop": c["stop"],
            "move_pct": _pct(now_px, c["called_price"])}
    return out


def retire_replaced(scanned_at: str, prices: dict | None = None) -> int:
    """
    Close the open calls of this week and momentum, the two lists folded into
    the month and long-term lists in December 2026, each with the name of the
    list that took its place. Idempotent: once closed, nothing is open there
    to close again.
    """
    return sum(retire((h,), scanned_at, prices, RETIRED_NOTE[h]) for h in RETIRED_HORIZONS)


def retire(horizons, scanned_at: str, prices: dict | None = None, note: str = "") -> int:
    """
    Close every open call of the given horizons as dropped. Idempotent.

    Used when a list is replaced: its open calls would otherwise stay open for
    ever, because no scan would list or drop them again (the short- and
    medium-term lists, then this week and momentum: retire_replaced).
    """
    prices = {str(k).upper(): _num(v) for k, v in (prices or {}).items()}
    at = _iso(scan_time(scanned_at) or dt.datetime.now(dt.timezone.utc))
    n = 0
    with _tx() as conn:
        for h in horizons:
            for c in conn.execute("SELECT * FROM calls WHERE status='open' AND horizon=?", (h,)).fetchall():
                price = prices.get(c["symbol"], c["last_price"])
                _close(conn, c, at, price, "dropped",
                       note or "This list was replaced by the four tested lists.")
                n += 1
    return n


def export_csv(prices: dict | None = None, index=None) -> str:
    data = listing(limit=1000, prices=prices, index=index)["rows"]
    cols = ["called_date", "called_weekday", "called_time", "symbol", "name", "horizon",
            "setup", "called_stance", "called_price", "since_price", "since_pct",
            "since_basis", "since_days", "index_pct", "vs_index_pct",
            "stance", "entry", "stop", "target",
            "status", "outcome", "closed_date", "price_now", "move_pct", "days", "scans_seen"]
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
    w.writeheader()
    for r in data:
        w.writerow({**r,
                    "called_date": (r["called"] or {}).get("date"),
                    "called_weekday": (r["called"] or {}).get("weekday"),
                    "called_time": (r["called"] or {}).get("time"),
                    "closed_date": (r["closed"] or {}).get("date")})
    return buf.getvalue()
