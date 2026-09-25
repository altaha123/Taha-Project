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
    "net_change_in_cash", "closing_cash",
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


def read_docs(symbol):
    """The filing documents already read for one company."""
    return {r["source_url"] for r in _connect().execute(
        "SELECT source_url FROM docs WHERE symbol=?", ((symbol or "").strip().upper(),))}


def mark_doc(symbol, source_url, period_end=None):
    with _tx() as conn:
        conn.execute("INSERT OR REPLACE INTO docs VALUES (?,?,?,?)",
                     ((symbol or "").strip().upper(), source_url, period_end, _utcnow()))


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
    ones tried longest ago. A re-read fetches only documents not yet in
    `docs`, so a fortnight keeps the tables current through a results season.
    """
    conn = _connect()
    seen = {r["symbol"]: ((r["last_try_utc"] or ""), r["status"]) for r in conn.execute(
        "SELECT symbol, last_try_utc, status FROM %s" % _COVERAGE[source]).fetchall()}
    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(hours=stale_hours)).isoformat(timespec="seconds")
    # A company left half-read because the exchange started refusing is
    # retried the next day, not a fortnight later.
    retry = (now - timedelta(hours=20)).isoformat(timespec="seconds")
    never, stale = [], []
    for sym in universe or []:
        s = (sym or "").strip().upper()
        if not s:
            continue
        if s not in seen:
            never.append(s)
            continue
        tried, status = seen[s]
        if tried < (retry if status in ("partial", "unreadable", "error") else cutoff):
            stale.append((tried, s))
    stale.sort()
    return (never + [s for _t, s in stale])[: max(1, int(limit))]


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


# ---------------------------------------------------------------------------
# Readers for the rest of the site
#
# The tables were filled so that the pages reading a company's statements need
# not go back to the exchange or to Yahoo for them. These shape what is held
# into what each consumer already expects.
# ---------------------------------------------------------------------------

def _latest_basis(recs):
    """Consolidated where held, else standalone — one basis, never both."""
    held = {r.get("basis") for r in recs}
    return "consolidated" if "consolidated" in held else \
        ("standalone" if "standalone" in held else None)


def _nse_time(iso):
    """The exchange's own '23-Apr-2026 18:00:00' back from the stored ISO
    text, so the point-in-time store keys a stored row and the same filing
    read live as one version rather than two."""
    try:
        return datetime.fromisoformat(str(iso)).strftime("%d-%b-%Y %H:%M:%S")
    except (TypeError, ValueError):
        return iso


def scoring_quarters(symbol, limit=16):
    """
    One company's quarters in the shape xbrl.statements() returns, for the
    factor library: rupees for money, `period`, `filed_at`, `consolidated`,
    `ebitda_margin_pct`, and return on assets annualised against the balance
    sheet filed at or before the quarter (within seven months), exactly as
    xbrl.normalise() derives it from a filing's own total assets.

    Each row is the latest filing for its period, so this is for scoring
    today. A historical as-of read needs every revision and stays on the
    point-in-time path.
    """
    sym = (symbol or "").strip().upper()
    recs = rows("income", symbol=sym, freq="quarterly")
    basis = _latest_basis(recs)
    if not basis:
        return []
    recs = [r for r in recs if r.get("basis") == basis][: max(1, int(limit))]
    sheets = sorted(((_date(b["period_end"]), b.get("total_assets_cr"))
                     for b in rows("balance", symbol=sym)
                     if b.get("basis") == basis and b.get("total_assets_cr")),
                    key=lambda x: x[0] or date.min, reverse=True)
    out = []
    for r in recs:
        end = _date(r["period_end"])
        q = {"period": {"from": r.get("period_from"), "to": r["period_end"]},
             "to": r["period_end"], "from": r.get("period_from"),
             "filed_at": _nse_time(r.get("filed_at")), "audited": r.get("audited"),
             "consolidated": basis == "consolidated", "company": r.get("company"),
             "source_url": r.get("source_url"), "regime": "stored"}
        for k in INCOME_LINES:
            v = r.get("%s_cr" % k)
            q[k] = None if v is None else v * CRORE
        q["eps_basic"] = r.get("eps_basic")
        q["ebitda_margin_pct"] = r.get("opm_pct")
        q["net_margin_pct"] = r.get("net_margin_pct")
        ta = next((a for d, a in sheets if d and end and 0 <= (end - d).days <= 215), None)
        if ta and r.get("pat_cr") is not None:
            q["roa_annualised_pct"] = round(r["pat_cr"] * 4 / ta * 100, 2)
        for k in INCOME_YOY:
            if r.get("%s_yoy_pct" % k) is not None:
                q["%s_yoy_pct" % k] = r["%s_yoy_pct" % k]
        out.append(q)
    return out


def latest_for(symbols, fresh_after=None):
    """
    Each company's newest quarter and newest balance sheet, on its own basis,
    for comparing a company with its peers. One query per table however many
    companies are asked for. `fresh_after` (ISO date) drops a company whose
    newest quarter ended before it, so a peer that has stopped filing does not
    drag the median towards an old year.
    """
    syms = sorted({(s or "").strip().upper() for s in symbols or [] if s})
    if not syms:
        return {}
    conn = _connect()
    out = {}
    for i in range(0, len(syms), 500):
        part = syms[i:i + 500]
        marks = ",".join("?" * len(part))
        inc = conn.execute(
            "SELECT symbol, basis, period_end, label, revenue_cr, pat_cr, opm_pct,"
            " net_margin_pct, revenue_yoy_pct, pat_yoy_pct, ebitda_yoy_pct"
            " FROM income_statement WHERE freq='quarterly' AND symbol IN (%s)"
            " ORDER BY symbol, period_end DESC" % marks, part).fetchall()
        by = {}
        for r in inc:
            by.setdefault(r["symbol"], []).append(dict(r))
        for sym, recs in by.items():
            basis = _latest_basis(recs)
            top = next(r for r in recs if r["basis"] == basis)
            if fresh_after and str(top["period_end"]) < fresh_after:
                continue
            out[sym] = {"basis": basis, "quarter": top}
        bal = conn.execute(
            "SELECT symbol, basis, period_end, debt_equity_x, current_ratio_x,"
            " total_equity_cr, net_debt_cr FROM balance_sheet WHERE symbol IN (%s)"
            " ORDER BY symbol, period_end DESC" % marks, part).fetchall()
        for r in bal:
            o = out.get(r["symbol"])
            if o is not None and "balance" not in o and r["basis"] == o["basis"]:
                o["balance"] = dict(r)
        ann = conn.execute(
            "SELECT symbol, basis, period_end, pat_cr FROM income_statement"
            " WHERE freq='annual' AND symbol IN (%s) ORDER BY symbol, period_end DESC"
            % marks, part).fetchall()
        for r in ann:
            o = out.get(r["symbol"])
            if o is not None and "annual" not in o and r["basis"] == o["basis"]:
                o["annual"] = dict(r)
    return out
