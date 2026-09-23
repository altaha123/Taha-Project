"""
fundamentals_store.py — every listed company's quarterly P&L, as one table

WHAT THIS IS
The Fundamentals pane reads a company's Regulation 33 filings when someone
opens it, and until now that was the only time anything was read. The XBRL
documents were cached on disk as hashed JSON files, which nobody can browse,
and a company nobody had looked at had nothing stored at all.

This is the table those reads land in: one row per company per quarter, one
column per P&L line, in ₹ crore, on the basis `fundamentals.series()` chose.
It is filled by fundamentals_crawl a slice at a time across the whole NSE
list, and also whenever the pane is served, so a page view is never wasted.

WHY ONE ROW PER (symbol, basis, period_end)
A company files standalone and consolidated results for the same quarter, and
the two are not comparable — see fundamentals.py. The basis is part of the key
so the two can never overwrite each other, and every row says which it is.

WHAT IS UPDATED AND WHAT IS NOT
A company can revise a quarter's results. The row for a period holds the
LATEST filing for it, judged by `filed_at`; an older filing arriving later
never replaces a newer one. The raw documents stay in xbrl-cache and the
point-in-time history of revisions stays in pit_store.quarter_versions — this
table is the current view, meant to be read, exported and queried.

AND YAHOO'S FULL STATEMENTS BESIDE IT
A quarterly filing has no balance sheet and no cash flow, so yf_statements
holds Yahoo Finance's income statement, balance sheet and cash flow, annual
and quarterly, for the same companies. A separate table with its own coverage,
because it is a different source with a different standing — see
fundamentals_crawl.

NO EXTERNAL DEPENDENCIES. Standard library only.
"""

import csv
import io
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

_HERE = os.path.dirname(os.path.abspath(__file__))
_DATA_DIR = os.environ.get("DATA_DIR", "").strip() or _HERE
try:
    os.makedirs(_DATA_DIR, exist_ok=True)
except Exception:
    _DATA_DIR = _HERE

DB_PATH = os.environ.get("ALTAHA_FUNDAMENTALS_DB", "").strip() or \
    os.path.join(_DATA_DIR, "altaha_fundamentals.db")

_local = threading.local()
_init_lock = threading.Lock()
_ready = {"done": False}

_state = {
    "configured_path": DB_PATH,
    "active_path": DB_PATH,
    "data_dir": _DATA_DIR,
    "data_dir_from_env": bool(os.environ.get("DATA_DIR", "").strip()),
    "fell_back": False,
    "last_error": None,
}

CRORE = 1e7

# (column, key in fundamentals.series()'s `values`). Money in ₹ crore, so the
# table reads the way an Indian P&L is read; EPS stays in rupees per share.
MONEY = [
    ("revenue_cr",          "revenue"),
    ("other_income_cr",     "other_income"),
    ("total_income_cr",     "total_income"),
    ("materials_cr",        "materials"),
    ("employee_cost_cr",    "employee_cost"),
    ("finance_cost_cr",     "finance_cost"),
    ("depreciation_cr",     "depreciation"),
    ("other_expenses_cr",   "other_expenses"),
    ("total_expenses_cr",   "total_expenses"),
    ("ebitda_cr",           "ebitda"),
    ("pbt_before_exceptional_cr", "pbt_before_exceptional"),
    ("exceptional_cr",      "exceptional"),
    ("pbt_cr",              "pbt"),
    ("tax_cr",              "tax"),
    ("pat_cr",              "pat"),
]
RUPEES = [("eps_basic", "eps_basic")]
RATIOS = ["opm_pct", "net_margin_pct", "tax_rate_pct",
          "other_income_share_pct", "interest_cover_x", "employee_cost_pct"]
# Year-on-year against the same quarter a year earlier, where a percentage
# means something — None across zero, exactly as the pane shows it.
YOY = [("revenue_yoy_pct", "revenue"), ("ebitda_yoy_pct", "ebitda"),
       ("pat_yoy_pct", "pat")]

VALUE_COLUMNS = [c for c, _k in MONEY + RUPEES] + RATIOS + [c for c, _k in YOY]

# The order a reader wants the export in: who, when, then the statement top
# to bottom, then what follows from it.
COLUMNS = (["symbol", "company", "basis", "quarter", "period_end",
            "period_from", "filed_at", "audited"]
           + VALUE_COLUMNS + ["source_url", "updated_utc"])


def _utcnow():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _open(path):
    conn = sqlite3.connect(path, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=30000")
    # Same reasoning as pit_store: one connection per thread, each with its
    # own page cache, on a 512 MB instance.
    conn.execute("PRAGMA cache_size=-256")
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute("PRAGMA mmap_size=0")
    return conn


SCHEMA = """
CREATE TABLE IF NOT EXISTS quarterly_results (
  symbol       TEXT NOT NULL,
  company      TEXT,
  basis        TEXT NOT NULL,            -- 'consolidated' | 'standalone'
  quarter      TEXT,                     -- 'Q1 FY27'
  period_end   TEXT NOT NULL,            -- YYYY-MM-DD
  period_from  TEXT,
  filed_at     TEXT,
  audited      TEXT,
%s,
  source_url   TEXT,
  first_seen_utc TEXT NOT NULL,
  updated_utc  TEXT NOT NULL,
  PRIMARY KEY (symbol, basis, period_end)
);
CREATE INDEX IF NOT EXISTS idx_qr_period ON quarterly_results (period_end);

CREATE TABLE IF NOT EXISTS coverage (
  symbol         TEXT PRIMARY KEY,
  last_try_utc   TEXT,
  last_ok_utc    TEXT,
  latest_period  TEXT,
  quarters       INTEGER NOT NULL DEFAULT 0,
  basis          TEXT,
  status         TEXT,
  note           TEXT
);
CREATE INDEX IF NOT EXISTS idx_fcov_try ON coverage (last_try_utc);

-- Yahoo Finance's full statements: income, balance sheet and cash flow,
-- annual and quarterly. Long format because the line items differ from one
-- company to the next (a bank has no inventory, a manufacturer no deposits),
-- and a column per possible item would be two hundred mostly-empty columns.
-- The item NAME lives once in yf_items, so two million values do not each
-- carry forty bytes of "Net Income From Continuing Operation Net Minority
-- Interest"; yf_statements_v joins it back for anyone querying by hand.
CREATE TABLE IF NOT EXISTS yf_items (
  item_id  INTEGER PRIMARY KEY,
  name     TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS yf_statements (
  symbol      TEXT NOT NULL,
  statement   TEXT NOT NULL,            -- 'income' | 'balance' | 'cashflow'
  freq        TEXT NOT NULL,            -- 'annual' | 'quarterly'
  period_end  TEXT NOT NULL,            -- YYYY-MM-DD
  item_id     INTEGER NOT NULL,
  value       REAL NOT NULL,            -- as Yahoo reports it: rupees for money
  PRIMARY KEY (symbol, statement, freq, period_end, item_id)
) WITHOUT ROWID;
CREATE VIEW IF NOT EXISTS yf_statements_v AS
  SELECT s.symbol, s.statement, s.freq, s.period_end, i.name AS item, s.value
    FROM yf_statements s JOIN yf_items i USING (item_id);

CREATE TABLE IF NOT EXISTS yf_coverage (
  symbol         TEXT PRIMARY KEY,
  last_try_utc   TEXT,
  last_ok_utc    TEXT,
  latest_period  TEXT,
  quarters       INTEGER NOT NULL DEFAULT 0,
  basis          TEXT,
  status         TEXT,
  note           TEXT
);
CREATE INDEX IF NOT EXISTS idx_ycov_try ON yf_coverage (last_try_utc);
""" % ",\n".join("  %s REAL" % c for c in VALUE_COLUMNS)


def _connect():
    conn = getattr(_local, "conn", None)
    if conn is not None:
        return conn
    path = _state["active_path"]
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        conn = _open(path)
    except Exception as e:
        # An ephemeral store beats no store, but it is reported rather than
        # hidden — stats() carries it to every caller that shows coverage.
        _state["last_error"] = "%s: %s" % (type(e).__name__, e)
        fallback = os.path.join(_HERE, "altaha_fundamentals.db")
        if path == fallback:
            raise
        _state["fell_back"] = True
        _state["active_path"] = fallback
        conn = _open(fallback)
    _local.conn = conn
    _ensure(conn)
    return conn


def _ensure(conn):
    if _ready["done"]:
        return
    with _init_lock:
        if _ready["done"]:
            return
        conn.executescript(SCHEMA)
        conn.commit()
        _ready["done"] = True


@contextmanager
def _tx():
    conn = _connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise


def _num(v, scale=1.0):
    try:
        if v is None:
            return None
        f = float(v)
        if f != f or f in (float("inf"), float("-inf")):
            return None
        return round(f / scale, 2)
    except (TypeError, ValueError):
        return None


def _iso(raw):
    """A filing timestamp as sortable ISO text. NSE sends '12-Aug-2026 18:04:11',
    which orders April after August; the revision check compares these."""
    if not raw:
        return None
    for fmt in ("%d-%b-%Y %H:%M:%S", "%d-%b-%Y %H:%M", "%d-%b-%Y",
                "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(str(raw).strip(), fmt).isoformat(sep=" ")
        except ValueError:
            continue
    return str(raw).strip()


def _row(sym, company, basis, q, now):
    values, ratios = q.get("values") or {}, q.get("ratios") or {}
    yoy = q.get("yoy") or {}
    out = {"symbol": sym, "company": company, "basis": basis,
           "quarter": q.get("label"), "period_end": q.get("period_end"),
           "period_from": q.get("from"), "filed_at": _iso(q.get("filed_at")),
           "audited": None if q.get("audited") is None else str(q.get("audited")),
           "source_url": q.get("source"), "updated_utc": now}
    for col, key in MONEY:
        out[col] = _num(values.get(key), CRORE)
    for col, key in RUPEES:
        out[col] = _num(values.get(key))
    for col in RATIOS:
        out[col] = _num(ratios.get(col))
    for col, key in YOY:
        out[col] = _num((yoy.get(key) or {}).get("pct"))
    return out


def record_series(series):
    """
    Store what fundamentals.series() returned. Returns rows written.

    A row already held for a period is replaced only by a filing made on or
    after the one it came from, so a revision wins and a stale re-read of an
    older document never undoes it.
    """
    if not series or not series.get("available"):
        return 0
    sym = (series.get("symbol") or "").strip().upper()
    basis = series.get("basis")
    if not sym or basis not in ("consolidated", "standalone"):
        return 0
    now = _utcnow()
    rows = [_row(sym, series.get("company"), basis, q, now)
            for q in series.get("rows") or [] if q.get("period_end")]
    if not rows:
        return 0
    cols = list(COLUMNS)
    sql = ("INSERT INTO quarterly_results (%s, first_seen_utc) VALUES (%s, ?) "
           "ON CONFLICT(symbol, basis, period_end) DO UPDATE SET %s "
           "WHERE COALESCE(excluded.filed_at, '') >= "
           "COALESCE(quarterly_results.filed_at, '')"
           % (", ".join(cols), ", ".join("?" * len(cols)),
              ", ".join("%s=excluded.%s" % (c, c) for c in cols
                        if c not in ("symbol", "basis", "period_end"))))
    with _tx() as conn:
        before = conn.total_changes
        conn.executemany(sql, [[r[c] for c in cols] + [now] for r in rows])
        return conn.total_changes - before


_COVERAGE = {"nse": "coverage", "yfinance": "yf_coverage"}


def mark_coverage(symbol, status, latest_period=None, quarters=0, basis=None,
                  note="", ok=False, source="nse"):
    now = _utcnow()
    with _tx() as conn:
        conn.execute(
            ("INSERT INTO {t} (symbol, last_try_utc, last_ok_utc, latest_period,"
            " quarters, basis, status, note) VALUES (?,?,?,?,?,?,?,?)"
            " ON CONFLICT(symbol) DO UPDATE SET last_try_utc=excluded.last_try_utc,"
            " last_ok_utc=COALESCE(excluded.last_ok_utc, {t}.last_ok_utc),"
            " latest_period=COALESCE(excluded.latest_period, {t}.latest_period),"
            " quarters=CASE WHEN excluded.quarters > 0 THEN excluded.quarters"
            "               ELSE {t}.quarters END,"
            " basis=COALESCE(excluded.basis, {t}.basis),"
            " status=excluded.status, note=excluded.note").format(t=_COVERAGE[source]),
            ((symbol or "").strip().upper(), now, now if ok else None,
             latest_period, int(quarters or 0), basis, status, (note or "")[:200]))


def due_symbols(universe, limit=40, stale_hours=24 * 14, source="nse"):
    """
    What the crawler should read next: never-tried companies first, then the
    ones tried longest ago. Re-reading a company is cheap once its documents
    are cached — one index call, plus a document only for a new quarter — so
    a fortnight keeps the table current through a results season.
    """
    conn = _connect()
    seen = {r["symbol"]: (r["last_try_utc"] or "") for r in conn.execute(
        "SELECT symbol, last_try_utc FROM %s" % _COVERAGE[source]).fetchall()}
    cutoff = (datetime.now(timezone.utc) -
              timedelta(hours=stale_hours)).isoformat(timespec="seconds")
    never, stale = [], []
    for sym in universe or []:
        s = (sym or "").strip().upper()
        if not s:
            continue
        if s not in seen:
            never.append(s)
        elif seen[s] < cutoff:
            stale.append((seen[s], s))
    stale.sort()
    return (never + [s for _t, s in stale])[: max(1, int(limit))]


def rows(symbol=None, period_end=None, limit=None):
    """The table, newest quarter first within each company."""
    sql = "SELECT %s FROM quarterly_results" % ", ".join(COLUMNS)
    where, args = [], []
    if symbol:
        where.append("symbol = ?")
        args.append(symbol.strip().upper())
    if period_end:
        where.append("period_end = ?")
        args.append(period_end)
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY symbol, period_end DESC"
    if limit:
        sql += " LIMIT %d" % max(1, int(limit))
    return [dict(r) for r in _connect().execute(sql, args).fetchall()]


def to_csv(records):
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=COLUMNS, extrasaction="ignore")
    w.writeheader()
    for r in records:
        w.writerow(r)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Yahoo Finance statements
# ---------------------------------------------------------------------------

STATEMENTS = ("income", "balance", "cashflow")
FREQS = ("annual", "quarterly")

# Line items that are not money, so ?crore=1 must leave them alone: share
# counts, rates and per-share figures divided by ten million are nonsense.
_NOT_MONEY = ("Shares", "Rate", "Number", "Per Share", "EPS")


def _item_ids(conn, names):
    conn.executemany("INSERT OR IGNORE INTO yf_items (name) VALUES (?)",
                     [(n,) for n in names])
    ids = {}
    for chunk in range(0, len(names), 500):
        part = names[chunk:chunk + 500]
        for r in conn.execute("SELECT item_id, name FROM yf_items WHERE name IN (%s)"
                              % ",".join("?" * len(part)), part):
            ids[r["name"]] = r["item_id"]
    return ids


def record_yf(symbol, statement, freq, values):
    """
    One statement for one company, as {(period_end, item): value}.

    Yahoo restates — a later annual report reclassifies a line — so what it
    says now replaces what it said before for the same period and item. Empty
    cells are not stored: Yahoo pads every frame to the union of periods, and
    a missing value is absence, not zero.
    """
    sym = (symbol or "").strip().upper()
    if not sym or statement not in STATEMENTS or freq not in FREQS:
        return 0
    clean = [(p, i, _num(v)) for (p, i), v in (values or {}).items()]
    clean = [(p, i, v) for p, i, v in clean if p and i and v is not None]
    if not clean:
        return 0
    with _tx() as conn:
        ids = _item_ids(conn, sorted({i for _p, i, _v in clean}))
        before = conn.total_changes
        conn.executemany(
            "INSERT OR REPLACE INTO yf_statements VALUES (?,?,?,?,?,?)",
            [(sym, statement, freq, p, ids[i], v) for p, i, v in clean])
        return conn.total_changes - before


def yf_statement(symbol, statement="income", freq="annual", crore=False):
    """
    One company's statement laid out the way it is read: a row per line item,
    a column per period, newest period first.
    """
    sym = (symbol or "").strip().upper()
    recs = _connect().execute(
        "SELECT period_end, item, value FROM yf_statements_v"
        " WHERE symbol=? AND statement=? AND freq=?", (sym, statement, freq)).fetchall()
    periods = sorted({r["period_end"] for r in recs}, reverse=True)
    grid = {}
    for r in recs:
        v = r["value"]
        if crore and not any(k in r["item"] for k in _NOT_MONEY):
            v = round(v / CRORE, 2)
        grid.setdefault(r["item"], {})[r["period_end"]] = v
    return {"symbol": sym, "statement": statement, "freq": freq,
            "unit": "₹ crore (share counts, rates and per-share items as reported)"
                    if crore else "as reported by Yahoo: rupees for money",
            "periods": periods,
            "rows": [{"item": k, **grid[k]} for k in sorted(grid)]}


def yf_statement_csv(table):
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=["item"] + table["periods"])
    w.writeheader()
    for r in table["rows"]:
        w.writerow(r)
    return buf.getvalue()


def stats():
    """What the table actually holds, for the coverage endpoint."""
    conn = _connect()

    def one(sql):
        r = conn.execute(sql).fetchone()
        return r[0] if r and r[0] is not None else 0
    cov = conn.execute(
        "SELECT status, COUNT(*) AS n FROM coverage GROUP BY status").fetchall()
    return {
        "path": _state["active_path"],
        "persistent": not _state["fell_back"] and _state["data_dir_from_env"],
        "fell_back": _state["fell_back"],
        "last_error": _state["last_error"],
        "rows": one("SELECT COUNT(*) FROM quarterly_results"),
        "companies": one("SELECT COUNT(DISTINCT symbol) FROM quarterly_results"),
        "latest_period": one("SELECT MAX(period_end) FROM quarterly_results") or None,
        "coverage": {(r["status"] or "unknown"): r["n"] for r in cov},
        "tried": one("SELECT COUNT(*) FROM coverage"),
        "yfinance": {
            "values": one("SELECT COUNT(*) FROM yf_statements"),
            "companies": one("SELECT COUNT(DISTINCT symbol) FROM yf_statements"),
            "latest_period": one("SELECT MAX(period_end) FROM yf_statements") or None,
            "coverage": {(r["status"] or "unknown"): r["n"] for r in conn.execute(
                "SELECT status, COUNT(*) AS n FROM yf_coverage GROUP BY status")},
        },
        "unit": "₹ crore, except eps_basic (₹ per share) and the *_pct / *_x ratios",
    }
