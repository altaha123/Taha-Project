"""
money_flow_store.py — where Money Flow keeps what it has read and worked out

One SQLite file on the data disk (DATA_DIR/altaha_money_flow.db), in the same
shape as the other stores: WAL, one connection per thread, and a schema that
is numbered migration files (backend/migrations/moneyflow/) applied once each.

WHAT IS A RECORD AND WHAT IS A CACHE
  records   fpi_sector_fortnight, inst_flow_daily, index_close_daily and
            deals_daily are what the sources published. The daily FII/DII
            figures and the deals cannot be fetched again by date, so they are
            the only copy and are never pruned.
  caches    sector_score_daily, stock_accumulation_daily and snapshots are
            worked out from the records and can be rebuilt. The page and the
            accumulation rows are kept for KEEP_SNAPSHOTS sessions, the sector
            scores for KEEP_SCORE_SESSIONS.

EVERY WRITE IS IDEMPOTENT. Each table is keyed on what the row IS (a sector
and a fortnight, an index and a session, a whole deal disclosure), so reading
the same file twice changes nothing, and a job that died half way is simply
run again.

The daily bhavcopy is deliberately NOT here. special.py already keeps 400
sessions of delivery, volume and close for the whole exchange as float32
panels (8.6 MB), and bhav_archive.py keeps five years of the files in R2. A
third copy as SQL rows would be about 1.1 million rows on a 1 GB disk.

NO EXTERNAL DEPENDENCIES. Standard library only.
"""

import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone

_HERE = os.path.dirname(os.path.abspath(__file__))
_DATA_DIR = os.environ.get("DATA_DIR", "").strip() or _HERE
try:
    os.makedirs(_DATA_DIR, exist_ok=True)
except Exception:
    _DATA_DIR = _HERE

DB_PATH = os.environ.get("ALTAHA_MONEYFLOW_DB", "").strip() or \
    os.path.join(_DATA_DIR, "altaha_money_flow.db")
MIGRATIONS_DIR = os.path.join(_HERE, "migrations", "moneyflow")
KEEP_SNAPSHOTS = 60
KEEP_SCORE_SESSIONS = 750
KEEP_JOB_RUNS = 400

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
# NSDL fortnights
# ---------------------------------------------------------------------------

REVISION_TOLERANCE_CR = 1.0


def upsert_fpi(rows, source_url=None):
    """
    Store sector-fortnight rows. Returns {"written", "revised"}.

    A fortnight arrives twice, once in its own report and once in the next.
    The later copy wins, a figure it leaves blank keeps the earlier one, and a
    net figure that moved by more than a crore is counted in `revisions`.
    """
    rows = [r for r in rows or [] if r.get("sector") and r.get("period_end")]
    written = revised = 0
    now = _utcnow()
    with _tx() as conn:
        for r in rows:
            old = conn.execute(
                "SELECT equity_net_inr_cr, revisions FROM fpi_sector_fortnight"
                " WHERE period_end=? AND sector=?", (r["period_end"], r["sector"])).fetchone()
            new = r.get("equity_net_inr_cr")
            bump = 0
            if old is not None and old[0] is not None and new is not None \
                    and abs(old[0] - new) > REVISION_TOLERANCE_CR:
                bump = 1
                revised += 1
            conn.execute(
                "INSERT INTO fpi_sector_fortnight (period_end, sector, period_start,"
                " equity_net_inr_cr, equity_net_usd_mn, total_net_inr_cr, equity_auc_inr_cr,"
                " source_url, revisions, updated_utc) VALUES (?,?,?,?,?,?,?,?,?,?)"
                " ON CONFLICT(period_end, sector) DO UPDATE SET"
                " period_start=COALESCE(excluded.period_start, period_start),"
                " equity_net_inr_cr=COALESCE(excluded.equity_net_inr_cr, equity_net_inr_cr),"
                " equity_net_usd_mn=COALESCE(excluded.equity_net_usd_mn, equity_net_usd_mn),"
                " total_net_inr_cr=COALESCE(excluded.total_net_inr_cr, total_net_inr_cr),"
                " equity_auc_inr_cr=COALESCE(excluded.equity_auc_inr_cr, equity_auc_inr_cr),"
                " source_url=COALESCE(excluded.source_url, source_url),"
                " revisions=revisions + ?, updated_utc=excluded.updated_utc",
                (r["period_end"], r["sector"], r.get("period_start"), new,
                 r.get("equity_net_usd_mn"), r.get("total_net_inr_cr"),
                 r.get("equity_auc_inr_cr"), source_url or r.get("source_url"), 0, now, bump))
            written += 1
    return {"written": written, "revised": revised}


def mark_report(url, report_date, status, note="", rows=0):
    with _tx() as conn:
        conn.execute(
            "INSERT INTO fpi_reports (url, report_date, status, note, rows, fetched_utc)"
            " VALUES (?,?,?,?,?,?) ON CONFLICT(url) DO UPDATE SET"
            " report_date=excluded.report_date, status=excluded.status, note=excluded.note,"
            " rows=excluded.rows, fetched_utc=excluded.fetched_utc",
            (url, report_date, status, (note or "")[:300], int(rows or 0), _utcnow()))


def reports_done():
    """{url: status} for every report page already asked for."""
    return {r["url"]: r["status"] for r in
            _connect().execute("SELECT url, status FROM fpi_reports")}


def fpi_periods(limit=None):
    """Fortnight end dates held, newest first."""
    q = "SELECT DISTINCT period_end FROM fpi_sector_fortnight ORDER BY period_end DESC"
    if limit:
        q += " LIMIT %d" % int(limit)
    return [r[0] for r in _connect().execute(q)]


def fpi_rows(periods=None):
    """Every stored sector-fortnight row, oldest first; `periods` narrows it."""
    q = ("SELECT period_end, sector, period_start, equity_net_inr_cr, equity_net_usd_mn,"
         " total_net_inr_cr, equity_auc_inr_cr, revisions FROM fpi_sector_fortnight")
    args = []
    if periods:
        periods = list(periods)
        q += " WHERE period_end IN (%s)" % ",".join("?" * len(periods))
        args = periods
    q += " ORDER BY period_end, sector"
    return [dict(r) for r in _connect().execute(q, args)]


# ---------------------------------------------------------------------------
# FII / DII, daily
# ---------------------------------------------------------------------------

def upsert_flows(by_day, source="NSE provisional"):
    """{iso_date: {"fii": {buy, sell, net}, "dii": {...}}} -> rows written.
    A side missing from a later read keeps what an earlier read stored."""
    n = 0
    now = _utcnow()
    with _tx() as conn:
        for day, flows in sorted((by_day or {}).items()):
            f, d = (flows or {}).get("fii") or {}, (flows or {}).get("dii") or {}
            if f.get("net") is None and d.get("net") is None:
                continue
            conn.execute(
                "INSERT INTO inst_flow_daily (date, fii_buy, fii_sell, fii_net, dii_buy,"
                " dii_sell, dii_net, provisional, source, updated_utc)"
                " VALUES (?,?,?,?,?,?,?,1,?,?) ON CONFLICT(date) DO UPDATE SET"
                " fii_buy=COALESCE(excluded.fii_buy, fii_buy),"
                " fii_sell=COALESCE(excluded.fii_sell, fii_sell),"
                " fii_net=COALESCE(excluded.fii_net, fii_net),"
                " dii_buy=COALESCE(excluded.dii_buy, dii_buy),"
                " dii_sell=COALESCE(excluded.dii_sell, dii_sell),"
                " dii_net=COALESCE(excluded.dii_net, dii_net),"
                " source=excluded.source, updated_utc=excluded.updated_utc",
                (day, f.get("buy"), f.get("sell"), f.get("net"),
                 d.get("buy"), d.get("sell"), d.get("net"), source, now))
            n += 1
    return n


def flows(limit=260):
    """The most recent sessions of FII/DII, oldest first."""
    rows = _connect().execute(
        "SELECT date, fii_buy, fii_sell, fii_net, dii_buy, dii_sell, dii_net"
        " FROM inst_flow_daily ORDER BY date DESC LIMIT ?", (int(limit),)).fetchall()
    return [dict(r) for r in reversed(rows)]


# ---------------------------------------------------------------------------
# Index closes
# ---------------------------------------------------------------------------

def upsert_index_day(day, closes):
    """One session's closes ({INDEX NAME: close}). Returns rows written."""
    iso = day if isinstance(day, str) else day.isoformat()
    items = [(iso, k, float(v)) for k, v in (closes or {}).items() if v]
    with _tx() as conn:
        if items:
            conn.executemany(
                "INSERT INTO index_close_daily (date, index_name, close) VALUES (?,?,?)"
                " ON CONFLICT(date, index_name) DO UPDATE SET close=excluded.close", items)
        conn.execute(
            "INSERT INTO index_days (date, status, rows, fetched_utc) VALUES (?,?,?,?)"
            " ON CONFLICT(date) DO UPDATE SET status=excluded.status, rows=excluded.rows,"
            " fetched_utc=excluded.fetched_utc",
            (iso, "ok" if items else "absent", len(items), _utcnow()))
    return len(items)


def mark_index_absent(day):
    return upsert_index_day(day, {})


def index_days():
    """{iso_date: status} for every calendar day already settled."""
    return {r["date"]: r["status"] for r in
            _connect().execute("SELECT date, status FROM index_days")}


def index_series(names, since=None):
    """{INDEX NAME: [(iso_date, close), ...]} oldest first."""
    names = [n for n in names or [] if n]
    if not names:
        return {}
    q = ("SELECT index_name, date, close FROM index_close_daily WHERE index_name IN (%s)"
         % ",".join("?" * len(names)))
    args = list(names)
    if since:
        q += " AND date >= ?"
        args.append(since)
    q += " ORDER BY index_name, date"
    out = {}
    for r in _connect().execute(q, args):
        out.setdefault(r["index_name"], []).append((r["date"], r["close"]))
    return out


# ---------------------------------------------------------------------------
# Deals
# ---------------------------------------------------------------------------

def upsert_deals(rows):
    """Store disclosures; returns how many were new."""
    rows = [r for r in rows or [] if r]
    if not rows:
        return 0
    with _tx() as conn:
        before = conn.total_changes
        conn.executemany(
            "INSERT OR IGNORE INTO deals_daily (date, symbol, client, side, kind, qty, price,"
            " name, remarks) VALUES (?,?,?,?,?,?,?,?,?)",
            [(r["date"], r["symbol"], r["client"], r["side"], r["kind"], r["qty"], r["price"],
              r.get("name"), r.get("remarks")) for r in rows])
        return conn.total_changes - before


def deals_since(since, symbols=None):
    q = ("SELECT date, symbol, client, side, kind, qty, price, name, remarks FROM deals_daily"
         " WHERE date >= ?")
    args = [since]
    if symbols is not None:
        symbols = list(symbols)
        if not symbols:
            return []
        q += " AND symbol IN (%s)" % ",".join("?" * len(symbols))
        args += symbols
    q += " ORDER BY date DESC"
    return [dict(r) for r in _connect().execute(q, args)]


def mark_deals_window(kind, start, end, rows):
    with _tx() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO deals_windows (kind, start_date, end_date, rows, fetched_utc)"
            " VALUES (?,?,?,?,?)", (kind, start, end, int(rows or 0), _utcnow()))


def deals_windows():
    return {(r["kind"], r["start_date"]) for r in
            _connect().execute("SELECT kind, start_date FROM deals_windows")}


# ---------------------------------------------------------------------------
# What was worked out
# ---------------------------------------------------------------------------

def save_snapshot(date, payload, sectors, stocks):
    """
    One computed session, written in one transaction: the page, the sector
    cards and the accumulation rows. Writing a date again replaces it.
    """
    now = _utcnow()
    with _tx() as conn:
        conn.execute("INSERT OR REPLACE INTO snapshots (date, payload, built_utc) VALUES (?,?,?)",
                     (date, json.dumps(payload, separators=(",", ":")), now))
        conn.execute("DELETE FROM sector_score_daily WHERE date=?", (date,))
        conn.executemany(
            "INSERT INTO sector_score_daily (date, sector, score, rank, quadrant, payload)"
            " VALUES (?,?,?,?,?,?)",
            [(date, s["sector"], s.get("score"), s.get("rank"), s.get("quadrant"),
              json.dumps(s, separators=(",", ":"))) for s in sectors or []])
        conn.execute("DELETE FROM stock_accumulation_daily WHERE date=?", (date,))
        conn.executemany(
            "INSERT OR REPLACE INTO stock_accumulation_daily (date, sector, symbol, score, payload)"
            " VALUES (?,?,?,?,?)",
            [(date, r["sector"], r["symbol"], r.get("score"),
              json.dumps(r, separators=(",", ":"))) for r in stocks or []])
        old = [r[0] for r in conn.execute(
            "SELECT date FROM snapshots ORDER BY date DESC LIMIT -1 OFFSET ?", (KEEP_SNAPSHOTS,))]
        for d in old:
            conn.execute("DELETE FROM snapshots WHERE date=?", (d,))
            conn.execute("DELETE FROM stock_accumulation_daily WHERE date=?", (d,))
        # Sector scores are kept much longer, as the history a card can draw,
        # but not for ever: three years of sessions is about 30 MB.
        cut = conn.execute("SELECT DISTINCT date FROM sector_score_daily ORDER BY date DESC"
                           " LIMIT 1 OFFSET ?", (KEEP_SCORE_SESSIONS,)).fetchone()
        if cut:
            conn.execute("DELETE FROM sector_score_daily WHERE date <= ?", (cut[0],))


def latest_snapshot():
    r = _connect().execute(
        "SELECT date, payload, built_utc FROM snapshots ORDER BY date DESC LIMIT 1").fetchone()
    if not r:
        return None
    try:
        return {"date": r["date"], "built_utc": r["built_utc"], "payload": json.loads(r["payload"])}
    except ValueError:
        return None


def sector_cards(date=None, before=None):
    """The sector cards of one computed session: the latest, a named one, or
    the latest strictly before `before`. ({} when there is none.)"""
    conn = _connect()
    if date is None:
        q, args = "SELECT MAX(date) FROM sector_score_daily", ()
        if before:
            q, args = "SELECT MAX(date) FROM sector_score_daily WHERE date < ?", (before,)
        row = conn.execute(q, args).fetchone()
        date = row[0] if row else None
    if not date:
        return None, {}
    out = {}
    for r in conn.execute("SELECT sector, payload FROM sector_score_daily WHERE date=?", (date,)):
        try:
            out[r["sector"]] = json.loads(r["payload"])
        except ValueError:
            pass
    return date, out


def accumulation(sector, date=None):
    conn = _connect()
    if date is None:
        row = conn.execute("SELECT MAX(date) FROM stock_accumulation_daily").fetchone()
        date = row[0] if row else None
    if not date:
        return None, []
    out = []
    for r in conn.execute(
            "SELECT payload FROM stock_accumulation_daily WHERE date=? AND sector=?"
            " ORDER BY score DESC", (date, sector)):
        try:
            out.append(json.loads(r["payload"]))
        except ValueError:
            pass
    return date, out


def score_history(sector, limit=60):
    rows = _connect().execute(
        "SELECT date, score, rank, quadrant FROM sector_score_daily WHERE sector=?"
        " ORDER BY date DESC LIMIT ?", (sector, int(limit))).fetchall()
    return [dict(r) for r in reversed(rows)]


# ---------------------------------------------------------------------------
# Jobs and alerts
# ---------------------------------------------------------------------------

def job_start(job):
    with _tx() as conn:
        cur = conn.execute("INSERT INTO job_runs (job, started_utc) VALUES (?,?)", (job, _utcnow()))
        run_id = cur.lastrowid
        conn.execute("DELETE FROM job_runs WHERE id <= ?", (run_id - KEEP_JOB_RUNS,))
        return run_id


def job_finish(run_id, ok, summary):
    with _tx() as conn:
        conn.execute("UPDATE job_runs SET finished_utc=?, ok=?, summary=? WHERE id=?",
                     (_utcnow(), 1 if ok else 0,
                      json.dumps(summary, separators=(",", ":"), default=str)[:20000], run_id))


def job_runs(limit=20, job=None):
    q, args = "SELECT id, job, started_utc, finished_utc, ok, summary FROM job_runs", []
    if job:
        q += " WHERE job=?"
        args.append(job)
    q += " ORDER BY id DESC LIMIT ?"
    args.append(int(limit))
    out = []
    for r in _connect().execute(q, args):
        d = dict(r)
        try:
            d["summary"] = json.loads(d["summary"]) if d["summary"] else None
        except ValueError:
            pass
        d["ok"] = None if d["ok"] is None else bool(d["ok"])
        out.append(d)
    return out


def alert_claim(key, text=""):
    """True the first time a key is seen: the caller may send. Claimed before
    sending, so two overlapping jobs cannot both announce the same thing."""
    with _tx() as conn:
        cur = conn.execute(
            "INSERT OR IGNORE INTO alerts_sent (key, sent_utc, delivered, text) VALUES (?,?,0,?)",
            (key, _utcnow(), (text or "")[:1000]))
        return cur.rowcount == 1


def alert_delivered(key, delivered):
    with _tx() as conn:
        conn.execute("UPDATE alerts_sent SET delivered=? WHERE key=?", (1 if delivered else 0, key))


def alerts(limit=20):
    return [dict(r) for r in _connect().execute(
        "SELECT key, sent_utc, delivered, text FROM alerts_sent ORDER BY sent_utc DESC LIMIT ?",
        (int(limit),))]


def coverage():
    """What the store holds, for the status endpoint."""
    conn = _connect()

    def one(q):
        r = conn.execute(q).fetchone()
        return tuple(r) if r else (None,)
    fpi = one("SELECT COUNT(DISTINCT period_end), MIN(period_end), MAX(period_end),"
              " COALESCE(SUM(revisions),0) FROM fpi_sector_fortnight")
    idx = one("SELECT COUNT(*), MIN(date), MAX(date) FROM index_days WHERE status='ok'")
    flw = one("SELECT COUNT(*), MIN(date), MAX(date) FROM inst_flow_daily")
    dls = one("SELECT COUNT(*), MIN(date), MAX(date), COUNT(DISTINCT date) FROM deals_daily")
    snp = one("SELECT COUNT(*), MAX(date) FROM snapshots")
    return {
        "fpi_fortnights": {"count": fpi[0], "from": fpi[1], "to": fpi[2], "revisions": fpi[3]},
        "index_sessions": {"count": idx[0], "from": idx[1], "to": idx[2]},
        "flow_sessions": {"count": flw[0], "from": flw[1], "to": flw[2]},
        "deals": {"rows": dls[0], "from": dls[1], "to": dls[2], "sessions": dls[3]},
        "snapshots": {"count": snp[0], "latest": snp[1]},
        "db_path": DB_PATH,
        "persistent": bool(os.environ.get("DATA_DIR", "").strip()),
    }
