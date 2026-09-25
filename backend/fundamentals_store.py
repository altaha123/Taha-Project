"""
fundamentals_store.py — every listed company's statements, as three tables

WHAT THIS IS
The Fundamentals pane reads a company's Regulation 33 filings when someone
opens it, and until now that was the only time anything was read. This is
where a crawl of the whole NSE list keeps what those filings say, as three
tables a person can open, export and query:

  income_statement  one row per company per quarter AND per financial year:
                    the P&L in ₹ crore, EPS, six ratios, year-on-year growth.
                    Quarters go back to September 2018 — eight years.
  balance_sheet     one row per company per half-year end (March, September):
                    assets, equity, borrowings, and the ratios that follow.
                    Filed in XBRL only from the September 2022 half-year, so
                    four financial years to begin with, growing every year.
  cash_flow         one row per company per half-year and full year: operating,
                    investing and financing cash flow, capex, free cash flow.
                    Filed from the 2020-21 year — six financial years.

All three come from the same documents: every Reg 33 filing carries the
quarter's P&L, and the March and September ones also carry the balance sheet
at that date and the cash flow for the year to date.

WHY THE BASIS IS PART OF EVERY KEY
A company files standalone and consolidated results for the same period, and
the two are not comparable — see fundamentals.py. The crawl reads one basis
per company (consolidated where it files it) and every row says which.

WHAT IS UPDATED AND WHAT IS NOT
A company can revise a period's results. A row holds the LATEST filing for its
period, judged by `filed_at`; an older filing read later never replaces a
newer one. `docs` records every document read, so a re-crawl fetches only
what is new.

AND YAHOO'S STATEMENTS BESIDE THEM
yf_statements holds Yahoo Finance's income statement, balance sheet and cash
flow for the same companies — a secondary source, kept in its own table with
its own coverage and never mixed into the three above.

NO EXTERNAL DEPENDENCIES. Standard library only.
"""

import csv
import io
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone

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

# ---------------------------------------------------------------------------
# The three tables
#
# Money columns end in _cr and are ₹ crore; eps_basic is ₹ per share; *_pct
# is a percentage and *_x a multiple. Line keys are the ones xbrl.normalise()
# returns, so a column is `<key>_cr`.
# ---------------------------------------------------------------------------

INCOME_LINES = [
    "revenue", "other_income", "total_income", "materials", "employee_cost",
    "finance_cost", "depreciation", "other_expenses", "total_expenses",
    "operating_profit_pre_provision", "provisions", "ebitda",
    "pbt_before_exceptional", "exceptional", "pbt", "tax", "pat",
    "pat_continuing", "discontinued_pat", "share_of_associates",
    "regulatory_deferral", "pat_owners", "pat_minority",
]
INCOME_RATIOS = ["opm_pct", "net_margin_pct", "tax_rate_pct",
                 "other_income_share_pct", "interest_cover_x", "employee_cost_pct"]
# Year-on-year against the same period a year earlier, where a percentage
# means something — None across zero, exactly as the pane shows it.
INCOME_YOY = ["revenue", "ebitda", "pat"]

BALANCE_LINES = [
    "total_assets", "non_current_assets", "ppe", "cwip", "goodwill",
    "other_intangibles", "non_current_investments", "current_assets",
    "inventories", "current_investments", "investments", "trade_receivables",
    "cash_and_equivalents", "other_bank_balances", "loans",
    "total_equity", "equity_capital", "other_equity", "equity_to_owners",
    "minority_interest", "total_liabilities", "non_current_liabilities",
    "current_liabilities", "borrowings_non_current", "borrowings_current",
    "borrowings", "debt_securities", "subordinated_liabilities", "deposits",
    "trade_payables", "total_equity_and_liabilities",
    "total_borrowings", "net_debt",                      # derived
]
BALANCE_RATIOS = ["debt_equity_x", "current_ratio_x"]

CASHFLOW_LINES = [
    "cfo", "cfi", "cff", "capex_ppe", "capex_intangibles", "capex",
    "fcf", "asset_sale_proceeds", "income_tax_paid", "dividends_paid",
    "interest_paid", "borrowings_raised", "borrowings_repaid",
    "lease_payments", "share_buyback", "shares_issued",
    "net_change_in_cash", "fx_effect_on_cash", "closing_cash",
]

_MONEY = {"income": INCOME_LINES, "balance": BALANCE_LINES, "cashflow": CASHFLOW_LINES}

TABLES = {
    "income": {
        "name": "income_statement",
        "key": ["symbol", "basis", "freq", "period_end"],
        "meta": ["symbol", "company", "basis", "freq", "label", "period_from",
                 "period_end", "months", "filed_at", "audited"],
        "values": ["%s_cr" % k for k in INCOME_LINES] + ["eps_basic"]
                  + INCOME_RATIOS + ["%s_yoy_pct" % k for k in INCOME_YOY],
    },
    "balance": {
        "name": "balance_sheet",
        "key": ["symbol", "basis", "period_end"],
        "meta": ["symbol", "company", "basis", "label", "period_end",
                 "filed_at", "audited"],
        "values": ["%s_cr" % k for k in BALANCE_LINES] + BALANCE_RATIOS,
    },
    "cashflow": {
        "name": "cash_flow",
        "key": ["symbol", "basis", "period_end", "months"],
        "meta": ["symbol", "company", "basis", "label", "period_from",
                 "period_end", "months", "filed_at", "audited"],
        "values": ["%s_cr" % k for k in CASHFLOW_LINES],
    },
}
for _t in TABLES.values():
    _t["columns"] = _t["meta"] + _t["values"] + ["source_url", "updated_utc"]

_INT = {"months"}


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


def _table_sql(t):
    cols = []
    for c in t["columns"]:
        if c in t["values"]:
            cols.append("  %s REAL" % c)
        elif c in _INT:
            cols.append("  %s INTEGER NOT NULL DEFAULT 0" % c)
        elif c in t["key"] or c == "updated_utc":
            cols.append("  %s TEXT NOT NULL" % c)
        else:
            cols.append("  %s TEXT" % c)
    return ("CREATE TABLE IF NOT EXISTS %s (\n%s,\n  first_seen_utc TEXT NOT NULL,\n"
            "  PRIMARY KEY (%s)\n);\nCREATE INDEX IF NOT EXISTS idx_%s_period ON %s (period_end);\n"
            % (t["name"], ",\n".join(cols), ", ".join(t["key"]), t["name"], t["name"]))


SCHEMA = "".join(_table_sql(t) for t in TABLES.values()) + """
-- Every filing document read, so a re-crawl fetches only what is new.
CREATE TABLE IF NOT EXISTS docs (
  symbol      TEXT NOT NULL,
  source_url  TEXT NOT NULL,
  period_end  TEXT,
  read_utc    TEXT NOT NULL,
  version     INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (symbol, source_url)
) WITHOUT ROWID;

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
"""


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
        _migrate(conn)
        conn.commit()
        _ready["done"] = True


def _migrate(conn):
    """
    Add any column a later version introduced. CREATE TABLE IF NOT EXISTS does
    nothing to a table that already exists, so the tables on the live disk keep
    their first shape unless this adds to it. Idempotent; never drops or
    rewrites anything.
    """
    wanted = {t["name"]: [(c, "REAL") for c in t["values"]] for t in TABLES.values()}
    wanted["docs"] = [("version", "INTEGER NOT NULL DEFAULT 0")]
    wanted["coverage"] = [("version", "INTEGER NOT NULL DEFAULT 0")]
    wanted["yf_coverage"] = [("version", "INTEGER NOT NULL DEFAULT 0")]
    for table, cols in wanted.items():
        have = {r[1] for r in conn.execute("PRAGMA table_info(%s)" % table)}
        for col, decl in cols:
            if col not in have:
                conn.execute("ALTER TABLE %s ADD COLUMN %s %s" % (table, col, decl))


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


def _date(raw):
    try:
        return date.fromisoformat(str(raw)[:10])
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------

def to_row(table, meta, values):
    """
    One row for `table` from filing metadata and xbrl.normalise() line values
    in rupees. Money becomes crore; ratios and EPS pass through; anything the
    table has no column for is dropped.
    """
    t = TABLES[table]
    out = {c: meta.get(c) for c in t["meta"]}
    out["filed_at"] = _iso(meta.get("filed_at"))
    out["months"] = int(meta.get("months") or 0) if "months" in t["meta"] else None
    out["source_url"] = meta.get("source_url")
    for k in _MONEY[table]:
        out["%s_cr" % k] = _num(values.get(k), CRORE)
    for c in t["values"]:
        if not c.endswith("_cr"):
            out[c] = _num(values.get(c))
    return out


def upsert(table, rows):
    """
    Write rows into one of the three tables. Returns rows written.

    A row already held for a period is replaced only by a filing made on or
    after the one it came from, so a revision wins and a stale re-read of an
    older document never undoes it.
    """
    t = TABLES[table]
    rows = [r for r in rows or [] if all(r.get(k) not in (None, "") for k in t["key"])]
    if not rows:
        return 0
    now = _utcnow()
    cols = t["columns"]
    sql = ("INSERT INTO %s (%s, first_seen_utc) VALUES (%s, ?) "
           "ON CONFLICT(%s) DO UPDATE SET %s "
           "WHERE COALESCE(excluded.filed_at, '') >= COALESCE(%s.filed_at, '')"
           % (t["name"], ", ".join(cols), ", ".join("?" * len(cols)),
              ", ".join(t["key"]),
              ", ".join("%s=excluded.%s" % (c, c) for c in cols if c not in t["key"]),
              t["name"]))
    with _tx() as conn:
        before = conn.total_changes
        conn.executemany(sql, [[r.get(c) if c != "updated_utc" else now
                                for c in cols] + [now] for r in rows])
        return conn.total_changes - before


def _pct(now, before):
    """A percentage only across a positive base, as fundamentals.change()."""
    if now is None or before is None or before <= 0 or now <= 0:
        return None
    return round(100.0 * (now - before) / before, 2)


def recompute_yoy(symbol):
    """
    Year-on-year growth on every income row of one company: against the row
    of the same frequency and basis whose period ended a year earlier, within
    a fortnight either way. Recomputed from the table rather than carried in
    from a filing, so a quarter that arrives late fills in its successor too.
    """
    sym = (symbol or "").strip().upper()
    with _tx() as conn:
        recs = [dict(r) for r in conn.execute(
            "SELECT basis, freq, period_end, %s FROM income_statement WHERE symbol=?"
            % ", ".join("%s_cr" % k for k in INCOME_YOY), (sym,))]
        by = {}
        for r in recs:
            by.setdefault((r["basis"], r["freq"]), []).append(r)
        updates = []
        for group in by.values():
            for r in group:
                end = _date(r["period_end"])
                prev = next((p for p in group if end and _date(p["period_end"])
                             and 350 <= (end - _date(p["period_end"])).days <= 380), None)
                updates.append(tuple(
                    _pct(r["%s_cr" % k], prev["%s_cr" % k]) if prev else None
                    for k in INCOME_YOY) + (sym, r["basis"], r["freq"], r["period_end"]))
        conn.executemany(
            "UPDATE income_statement SET %s WHERE symbol=? AND basis=? AND freq=? AND period_end=?"
            % ", ".join("%s_yoy_pct=?" % k for k in INCOME_YOY), updates)


# Bumped whenever the parser learns to read something new from a filing. A
# document read under an older version is read again, once, so the new
# columns fill in for every period rather than only for filings made from now
# on. 2: the profit reconciliation lines and the FX effect on cash.
DOC_VERSION = 2


def read_docs(symbol):
    """The filing documents already read, by the current parser, for one company."""
    return {r["source_url"] for r in _connect().execute(
        "SELECT source_url FROM docs WHERE symbol=? AND version>=?",
        ((symbol or "").strip().upper(), DOC_VERSION))}


def mark_doc(symbol, source_url, period_end=None):
    with _tx() as conn:
        conn.execute("INSERT OR REPLACE INTO docs (symbol, source_url, period_end,"
                     " read_utc, version) VALUES (?,?,?,?,?)",
                     ((symbol or "").strip().upper(), source_url, period_end,
                      _utcnow(), DOC_VERSION))


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
        if ok:
            conn.execute("UPDATE %s SET version=? WHERE symbol=?" % _COVERAGE[source],
                         (DOC_VERSION, (symbol or "").strip().upper()))


def due_symbols(universe, limit=40, stale_hours=24 * 14, source="nse"):
    """
    What the crawler should read next: never-tried companies first, then the
    ones tried longest ago. A re-read fetches only documents not yet in
    `docs`, so a fortnight keeps the tables current through a results season.
    """
    conn = _connect()
    seen = {r["symbol"]: ((r["last_try_utc"] or ""), r["status"], r["version"])
            for r in conn.execute("SELECT symbol, last_try_utc, status, version FROM %s"
                                  % _COVERAGE[source]).fetchall()}
    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(hours=stale_hours)).isoformat(timespec="seconds")
    # A company left half-read because the exchange started refusing is
    # retried the next day, not a fortnight later.
    retry = (now - timedelta(hours=20)).isoformat(timespec="seconds")
    never, outdated, stale = [], [], []
    for sym in universe or []:
        s = (sym or "").strip().upper()
        if not s:
            continue
        if s not in seen:
            never.append(s)
            continue
        tried, status, version = seen[s]
        if source == "nse" and status in ("ok", "partial") and (version or 0) < DOC_VERSION:
            # Read by an older parser: its filings hold lines the tables do
            # not have yet. After the never-tried, before the merely stale.
            outdated.append((tried, s))
        elif tried < (retry if status in ("partial", "unreadable", "error") else cutoff):
            stale.append((tried, s))
    outdated.sort()
    stale.sort()
    return (never + [s for _t, s in outdated] + [s for _t, s in stale])[: max(1, int(limit))]


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------

def rows(table, symbol=None, period_end=None, freq=None, limit=None):
    """One of the three tables, each company's newest period first."""
    t = TABLES[table]
    sql = "SELECT %s FROM %s" % (", ".join(t["columns"]), t["name"])
    where, args = [], []
    if symbol:
        where.append("symbol = ?")
        args.append(symbol.strip().upper())
    if period_end:
        where.append("period_end = ?")
        args.append(period_end)
    if freq and "freq" in t["columns"]:
        where.append("freq = ?")
        args.append(freq)
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY symbol, %speriod_end DESC" % ("freq, " if "freq" in t["columns"] else "")
    if limit:
        sql += " LIMIT %d" % max(1, int(limit))
    return [dict(r) for r in _connect().execute(sql, args).fetchall()]


def to_csv(table, records):
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=TABLES[table]["columns"], extrasaction="ignore")
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
    """What the tables actually hold, for the coverage endpoint."""
    conn = _connect()

    def one(sql):
        r = conn.execute(sql).fetchone()
        return r[0] if r and r[0] is not None else 0

    def cov(table):
        return {(r["status"] or "unknown"): r["n"] for r in conn.execute(
            "SELECT status, COUNT(*) AS n FROM %s GROUP BY status" % table)}

    tables = {}
    for key, t in TABLES.items():
        n = t["name"]
        tables[n] = {
            "rows": one("SELECT COUNT(*) FROM %s" % n),
            "companies": one("SELECT COUNT(DISTINCT symbol) FROM %s" % n),
            "earliest_period": one("SELECT MIN(period_end) FROM %s" % n) or None,
            "latest_period": one("SELECT MAX(period_end) FROM %s" % n) or None,
        }
    return {
        "path": _state["active_path"],
        "persistent": not _state["fell_back"] and _state["data_dir_from_env"],
        "fell_back": _state["fell_back"],
        "last_error": _state["last_error"],
        "tables": tables,
        "documents_read": one("SELECT COUNT(*) FROM docs"),
        "coverage": cov("coverage"),
        "tried": one("SELECT COUNT(*) FROM coverage"),
        "yfinance": {
            "values": one("SELECT COUNT(*) FROM yf_statements"),
            "companies": one("SELECT COUNT(DISTINCT symbol) FROM yf_statements"),
            "latest_period": one("SELECT MAX(period_end) FROM yf_statements") or None,
            "coverage": cov("yf_coverage"),
        },
        "unit": ("₹ crore for *_cr columns; eps_basic in ₹ per share; *_pct a "
                 "percentage; *_x a multiple"),
    }
