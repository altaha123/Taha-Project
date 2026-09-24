"""
lens_store.py — where the Lenses keep their inputs and their answers

WHAT LIVES HERE
Two kinds of table, in one SQLite file on the data disk:

  inputs   lens_company (NSE industry, issued shares, price) and
           lens_shareholding (promoter / FII / DII and the promoter pledge,
           per quarter). The fundamentals tables carry the statements; these
           carry what the statements do not.
  answers  lens_runs and lens_results — the nightly compute, cached so an
           endpoint is a read, never a recomputation across two thousand
           companies inside a request.

THE SCHEMA IS A MIGRATION, NOT A STRING IN THIS FILE
The tables are defined in backend/migrations/lenses/NNN_*.sql and applied in
order, once each; `schema_migrations` records what has run. A later change is
a new numbered file. CREATE TABLE IF NOT EXISTS does nothing to a table that
already exists, which is how a column added in code silently never reaches a
live database — a numbered file that runs once does not have that problem.

RESULTS ARE A CACHE
Unlike the point-in-time store, nothing here is a record that cannot be
rebuilt: every run can be recomputed from the fundamentals tables. So old runs
are pruned, keeping the last few for comparison.

NO EXTERNAL DEPENDENCIES. Standard library only.
"""

import json
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

DB_PATH = os.environ.get("ALTAHA_LENS_DB", "").strip() or \
    os.path.join(_DATA_DIR, "altaha_lenses.db")
MIGRATIONS_DIR = os.path.join(_HERE, "migrations", "lenses")
KEEP_RUNS = 3

_local = threading.local()
_init_lock = threading.Lock()
_ready = {"path": None}


def _utcnow():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _open(path):
    conn = sqlite3.connect(path, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=30000")
    # Same budget as the other stores: one connection per thread, each with
    # its own page cache, on a 512 MB instance.
    conn.execute("PRAGMA cache_size=-256")
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute("PRAGMA mmap_size=0")
    return conn


def migration_files():
    try:
        names = sorted(n for n in os.listdir(MIGRATIONS_DIR) if n.endswith(".sql"))
    except FileNotFoundError:
        return []
    return [(n, os.path.join(MIGRATIONS_DIR, n)) for n in names]


def migrate(conn):
    """Apply every migration not yet recorded, in file order. Idempotent."""
    conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations ("
                 " name TEXT PRIMARY KEY, applied_utc TEXT NOT NULL)")
    done = {r[0] for r in conn.execute("SELECT name FROM schema_migrations")}
    applied = []
    for name, path in migration_files():
        if name in done:
            continue
        with open(path, encoding="utf-8") as fh:
            conn.executescript(fh.read())
        conn.execute("INSERT INTO schema_migrations VALUES (?, ?)", (name, _utcnow()))
        conn.commit()
        applied.append(name)
    return applied


def _connect():
    conn = getattr(_local, "conn", None)
    if conn is not None and getattr(_local, "path", None) == DB_PATH:
        return conn
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    conn = _open(DB_PATH)
    _local.conn, _local.path = conn, DB_PATH
    if _ready["path"] != DB_PATH:
        with _init_lock:
            if _ready["path"] != DB_PATH:
                migrate(conn)
                _ready["path"] = DB_PATH
    return conn


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


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------

_COMPANY_COLS = ["symbol", "company", "macro", "sector", "industry",
                 "basic_industry", "issued_shares", "face_value", "last_price",
                 "price_date"]


def upsert_company(row):
    rec = {c: row.get(c) for c in _COMPANY_COLS}
    rec["symbol"] = (rec["symbol"] or "").strip().upper()
    if not rec["symbol"]:
        return 0
    cols = _COMPANY_COLS + ["updated_utc"]
    with _tx() as conn:
        conn.execute(
            "INSERT INTO lens_company (%s) VALUES (%s) ON CONFLICT(symbol) DO UPDATE SET %s"
            % (", ".join(cols), ", ".join("?" * len(cols)),
               ", ".join("%s=COALESCE(excluded.%s, lens_company.%s)" % (c, c, c)
                         for c in cols if c != "symbol")),
            [rec[c] for c in _COMPANY_COLS] + [_utcnow()])
    return 1


_SHP_COLS = ["symbol", "period_end", "promoter_pct", "fii_pct", "dii_pct",
             "public_pct", "pledged", "pledge_pct", "dii_derived", "source_url"]


def upsert_shareholding(rows):
    rows = [r for r in rows or [] if r.get("symbol") and r.get("period_end")]
    if not rows:
        return 0
    cols = _SHP_COLS + ["updated_utc"]
    now = _utcnow()
    with _tx() as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO lens_shareholding (%s) VALUES (%s)"
            % (", ".join(cols), ", ".join("?" * len(cols))),
            [[(r.get(c) if c != "dii_derived" else int(bool(r.get(c)))) for c in _SHP_COLS]
             + [now] for r in rows])
    return len(rows)


def mark_coverage(symbol, status, note="", ok=False):
    now = _utcnow()
    with _tx() as conn:
        conn.execute(
            "INSERT INTO lens_coverage (symbol, last_try_utc, last_ok_utc, status, note)"
            " VALUES (?,?,?,?,?) ON CONFLICT(symbol) DO UPDATE SET"
            " last_try_utc=excluded.last_try_utc,"
            " last_ok_utc=COALESCE(excluded.last_ok_utc, lens_coverage.last_ok_utc),"
            " status=excluded.status, note=excluded.note",
            ((symbol or "").strip().upper(), now, now if ok else None, status,
             (note or "")[:200]))


def due_symbols(universe, limit=40, stale_hours=24 * 7):
    """Never-tried first, then the longest ago. Failures retry the next day."""
    conn = _connect()
    seen = {r["symbol"]: (r["last_try_utc"] or "", r["status"]) for r in
            conn.execute("SELECT symbol, last_try_utc, status FROM lens_coverage")}
    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(hours=stale_hours)).isoformat(timespec="seconds")
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
        if tried < (cutoff if status == "ok" else retry):
            stale.append((tried, s))
    stale.sort()
    return (never + [s for _t, s in stale])[: max(1, int(limit))]


def companies():
    return {r["symbol"]: dict(r) for r in _connect().execute("SELECT * FROM lens_company")}


def shareholding():
    """{symbol: [quarter rows, newest first]}."""
    out = {}
    for r in _connect().execute(
            "SELECT * FROM lens_shareholding ORDER BY symbol, period_end DESC"):
        out.setdefault(r["symbol"], []).append(dict(r))
    return out


# ---------------------------------------------------------------------------
# Answers
# ---------------------------------------------------------------------------

def start_run(config_version=None, universe=None):
    with _tx() as conn:
        cur = conn.execute(
            "INSERT INTO lens_runs (started_utc, config_version, universe, status)"
            " VALUES (?,?,?, 'running')", (_utcnow(), config_version, universe))
        return cur.lastrowid


def write_results(run_id, rows):
    """rows: dicts with lens_id, symbol, company, industry and an engine result."""
    recs = []
    for r in rows:
        recs.append((run_id, r["lens_id"], r["symbol"], r.get("company"),
                     r.get("industry"), r["status"], r["passed"], r["failed"],
                     r["na"], r["total"], r["coverage"],
                     json.dumps(r["rules"], separators=(",", ":"), allow_nan=False,
                                default=str)))
    with _tx() as conn:
        conn.executemany("INSERT OR REPLACE INTO lens_results VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                         recs)
    return len(recs)


def finish_run(run_id, companies=0, status="ok", note=""):
    with _tx() as conn:
        conn.execute("UPDATE lens_runs SET finished_utc=?, companies=?, status=?, note=?"
                     " WHERE run_id=?", (_utcnow(), companies, status, (note or "")[:500], run_id))
        keep = [r[0] for r in conn.execute(
            "SELECT run_id FROM lens_runs WHERE status='ok' ORDER BY run_id DESC LIMIT ?",
            (KEEP_RUNS,))]
        if status == "ok" and keep:
            conn.execute("DELETE FROM lens_results WHERE run_id < ?", (min(keep),))
            conn.execute("DELETE FROM lens_runs WHERE run_id < ?", (min(keep),))


def latest_run():
    r = _connect().execute(
        "SELECT * FROM lens_runs WHERE status='ok' ORDER BY run_id DESC LIMIT 1").fetchone()
    return dict(r) if r else None


def _decode(r):
    d = dict(r)
    d["rules"] = json.loads(d["rules"])
    return d


def results(run_id, lens_id=None, symbol=None, statuses=None):
    sql, args = "SELECT * FROM lens_results WHERE run_id=?", [run_id]
    if lens_id:
        sql += " AND lens_id=?"
        args.append(lens_id)
    if symbol:
        sql += " AND symbol=?"
        args.append(symbol.strip().upper())
    if statuses:
        sql += " AND status IN (%s)" % ",".join("?" * len(statuses))
        args.extend(statuses)
    sql += " ORDER BY symbol"
    return [_decode(r) for r in _connect().execute(sql, args)]


def status_counts(run_id):
    """{lens_id: {status: n}}."""
    out = {}
    for r in _connect().execute(
            "SELECT lens_id, status, COUNT(*) AS n FROM lens_results WHERE run_id=?"
            " GROUP BY lens_id, status", (run_id,)):
        out.setdefault(r["lens_id"], {})[r["status"]] = r["n"]
    return out


def convergence(run_id, min_lenses=3):
    """Companies ranked by how many lenses they pass."""
    rows = _connect().execute(
        "SELECT symbol, MAX(company) AS company, MAX(industry) AS industry,"
        " GROUP_CONCAT(lens_id) AS lenses, COUNT(*) AS n"
        " FROM lens_results WHERE run_id=? AND status='pass'"
        " GROUP BY symbol HAVING COUNT(*) >= ? ORDER BY n DESC, symbol",
        (run_id, max(1, int(min_lenses)))).fetchall()
    return [{"symbol": r["symbol"], "company": r["company"], "industry": r["industry"],
             "lenses": sorted((r["lenses"] or "").split(",")), "passed": r["n"]}
            for r in rows]


def stats():
    conn = _connect()

    def one(sql):
        r = conn.execute(sql).fetchone()
        return r[0] if r and r[0] is not None else 0

    return {
        "path": DB_PATH,
        "persistent": bool(os.environ.get("DATA_DIR", "").strip()),
        "migrations": [r[0] for r in conn.execute(
            "SELECT name FROM schema_migrations ORDER BY name")],
        "companies_profiled": one("SELECT COUNT(*) FROM lens_company"),
        "companies_with_industry": one(
            "SELECT COUNT(*) FROM lens_company WHERE industry IS NOT NULL AND industry != ''"),
        "companies_with_shareholding": one("SELECT COUNT(DISTINCT symbol) FROM lens_shareholding"),
        "coverage": {(r["status"] or "unknown"): r["n"] for r in conn.execute(
            "SELECT status, COUNT(*) AS n FROM lens_coverage GROUP BY status")},
        "latest_run": latest_run(),
    }
