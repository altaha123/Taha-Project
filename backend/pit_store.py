"""
pit_store.py — Altaha Point-In-Time Data Store
================================================

WHAT THIS DOES (plain English):
Every time your screener scans the market, this file writes down exactly what
Altaha knew about every stock on that date — and never changes it afterwards.

Think of it like a set of signed, dated audit working papers. You can go back to
any date and ask "what did Altaha actually know on 3rd March?" and get the honest
answer, not today's revised figures.

WHY IT MATTERS:
Without this, every backtest you run is contaminated. You'd be scoring a stock in
March 2024 using financials published in June 2024 — results look brilliant, live
performance doesn't match. This file is what makes your numbers trustworthy.

DESIGN RULES (deliberate, do not "fix" these):
  1. Writes are INSERT OR IGNORE. The FIRST value written for a
     (date, symbol, factor) wins. Re-running a scan cannot rewrite history.
  2. Nothing is ever UPDATEd or DELETEd. This is an append-only ledger.
  3. WAL mode is on, so reads never block writes.

NO EXTERNAL DEPENDENCIES. Standard library only.
"""

import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import date, datetime, timezone

DB_PATH = os.environ.get("ALTAHA_PIT_DB", "altaha_pit.db")

_local = threading.local()


# --------------------------------------------------------------------------
# Connection handling
# --------------------------------------------------------------------------

def _connect():
    """One connection per thread. Safe under ThreadPoolExecutor."""
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = sqlite3.connect(DB_PATH, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=30000")
        _local.conn = conn
    return conn


@contextmanager
def _tx():
    conn = _connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


# --------------------------------------------------------------------------
# Schema
# --------------------------------------------------------------------------

SCHEMA = """
-- One row per scan run. Lets you tie snapshots back to a run and its regime.
CREATE TABLE IF NOT EXISTS scan_runs (
    run_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    as_of_date    TEXT NOT NULL,
    started_utc   TEXT NOT NULL,
    universe_size INTEGER,
    regime        TEXT,
    notes         TEXT
);

-- The core ledger. Long format: one row per stock per factor per date.
-- Long format is deliberate — you can add new factors forever without ever
-- having to alter this table or migrate old data.
CREATE TABLE IF NOT EXISTS factor_snapshots (
    as_of_date  TEXT    NOT NULL,
    symbol      TEXT    NOT NULL,
    factor      TEXT    NOT NULL,
    value       REAL,
    text_value  TEXT,
    run_id      INTEGER,
    written_utc TEXT    NOT NULL,
    PRIMARY KEY (as_of_date, symbol, factor)
) WITHOUT ROWID;

CREATE INDEX IF NOT EXISTS ix_snap_symbol_factor
    ON factor_snapshots (symbol, factor, as_of_date);
CREATE INDEX IF NOT EXISTS ix_snap_date
    ON factor_snapshots (as_of_date);

-- TIER 1: the filing-date table. This is the point-in-time anchor.
-- It records WHEN the market actually learned each number.
CREATE TABLE IF NOT EXISTS filings (
    symbol       TEXT NOT NULL,
    period       TEXT NOT NULL,      -- e.g. 'FY2025', 'Q1FY2026'
    filing_date  TEXT NOT NULL,      -- ISO date the filing hit the exchange
    filing_type  TEXT,               -- 'RESULTS', 'ANNUAL_REPORT', 'SHP', ...
    headline     TEXT,
    url          TEXT,
    source       TEXT,               -- 'BSE', 'NSE', 'MANUAL'
    ingested_utc TEXT NOT NULL,
    PRIMARY KEY (symbol, period, filing_type)
) WITHOUT ROWID;

CREATE INDEX IF NOT EXISTS ix_filings_date
    ON filings (filing_date);

-- Forward returns, filled in later by the backtest harness.
CREATE TABLE IF NOT EXISTS forward_returns (
    as_of_date   TEXT NOT NULL,
    symbol       TEXT NOT NULL,
    horizon_days INTEGER NOT NULL,
    ret_pct      REAL,
    bench_ret_pct REAL,
    excess_pct   REAL,
    computed_utc TEXT NOT NULL,
    PRIMARY KEY (as_of_date, symbol, horizon_days)
) WITHOUT ROWID;
"""


def init_db():
    """Create tables if they don't exist. Safe to call on every app start."""
    with _tx() as conn:
        conn.executescript(SCHEMA)


# --------------------------------------------------------------------------
# Writing snapshots
# --------------------------------------------------------------------------

def start_run(as_of=None, universe_size=None, regime=None, notes=None):
    """Call once at the beginning of a scan. Returns run_id."""
    as_of = _as_date(as_of)
    with _tx() as conn:
        cur = conn.execute(
            "INSERT INTO scan_runs (as_of_date, started_utc, universe_size, regime, notes)"
            " VALUES (?,?,?,?,?)",
            (as_of, _utcnow(), universe_size, regime, notes),
        )
        return cur.lastrowid


def snapshot(symbol, factors, as_of=None, run_id=None):
    """
    Record everything Altaha knows about ONE stock on ONE date.

    factors: a plain dict, e.g.
        {"composite": 88.4, "roce": 24.1, "rs_63d": 12.7,
         "archetype": "Momentum Breakout", "sector": "Auto"}

    Numbers go in `value`, strings go in `text_value`. Anything else is
    JSON-encoded into text_value. Nones are skipped.

    Calling this twice for the same (date, symbol, factor) does NOT overwrite —
    the first write stands. That is the whole point.
    """
    as_of = _as_date(as_of)
    now = _utcnow()
    rows = []
    for name, raw in factors.items():
        num, txt = _split_value(raw)
        if num is None and txt is None:
            continue
        rows.append((as_of, symbol, name, num, txt, run_id, now))

    if not rows:
        return 0

    with _tx() as conn:
        conn.executemany(
            "INSERT OR IGNORE INTO factor_snapshots"
            " (as_of_date, symbol, factor, value, text_value, run_id, written_utc)"
            " VALUES (?,?,?,?,?,?,?)",
            rows,
        )
    return len(rows)


def snapshot_many(records, as_of=None, run_id=None):
    """
    Bulk version. `records` is a dict of {symbol: factors_dict} or a list of
    (symbol, factors_dict) pairs. Much faster than looping snapshot().
    """
    if isinstance(records, dict):
        records = records.items()

    as_of = _as_date(as_of)
    now = _utcnow()
    rows = []
    for symbol, factors in records:
        if not factors:
            continue
        for name, raw in factors.items():
            num, txt = _split_value(raw)
            if num is None and txt is None:
                continue
            rows.append((as_of, symbol, name, num, txt, run_id, now))

    if not rows:
        return 0

    with _tx() as conn:
        conn.executemany(
            "INSERT OR IGNORE INTO factor_snapshots"
            " (as_of_date, symbol, factor, value, text_value, run_id, written_utc)"
            " VALUES (?,?,?,?,?,?,?)",
            rows,
        )
    return len(rows)


# --------------------------------------------------------------------------
# TIER 1: filing dates
# --------------------------------------------------------------------------

def record_filing(symbol, period, filing_date, filing_type="RESULTS",
                  headline=None, url=None, source="BSE"):
    """
    Record that `symbol` filed results for `period` on `filing_date`.
    This is the table that makes point-in-time backtesting honest.
    """
    with _tx() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO filings"
            " (symbol, period, filing_date, filing_type, headline, url, source, ingested_utc)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (symbol, period, _as_date(filing_date), filing_type,
             headline, url, source, _utcnow()),
        )


def latest_known_period(symbol, as_of, filing_type="RESULTS"):
    """
    THE KEY FUNCTION for avoiding look-ahead bias.

    Answers: "As of this date, what was the most recent financial period the
    market had actually seen for this stock?"

    Returns a dict with period / filing_date, or None if nothing was filed yet.
    Use this to decide which financials you are ALLOWED to score with.
    """
    conn = _connect()
    row = conn.execute(
        "SELECT period, filing_date, headline, url FROM filings"
        " WHERE symbol = ? AND filing_type = ? AND filing_date <= ?"
        " ORDER BY filing_date DESC LIMIT 1",
        (symbol, filing_type, _as_date(as_of)),
    ).fetchone()
    return dict(row) if row else None


def lagged_period_cutoff(as_of, lag_days=90):
    """
    Fallback for stocks with no filing history yet: assume any period ending
    more than `lag_days` before `as_of` was public, and nothing more recent was.

    Crude and conservative — it will UNDERSTATE your edge rather than inflate it.
    That is the correct direction to be wrong in.
    """
    from datetime import timedelta
    d = datetime.strptime(_as_date(as_of), "%Y-%m-%d").date()
    return (d - timedelta(days=lag_days)).isoformat()


# --------------------------------------------------------------------------
# Reading it back
# --------------------------------------------------------------------------

def get_snapshot(as_of, symbol=None):
    """Everything recorded on a date. Returns {symbol: {factor: value}}."""
    conn = _connect()
    if symbol:
        rows = conn.execute(
            "SELECT symbol, factor, value, text_value FROM factor_snapshots"
            " WHERE as_of_date = ? AND symbol = ?", (_as_date(as_of), symbol)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT symbol, factor, value, text_value FROM factor_snapshots"
            " WHERE as_of_date = ?", (_as_date(as_of),)
        ).fetchall()

    out = {}
    for r in rows:
        out.setdefault(r["symbol"], {})[r["factor"]] = (
            r["value"] if r["value"] is not None else r["text_value"]
        )
    return out


def factor_history(symbol, factor):
    """Time series of one factor for one stock. [(date, value), ...]"""
    conn = _connect()
    rows = conn.execute(
        "SELECT as_of_date, value, text_value FROM factor_snapshots"
        " WHERE symbol = ? AND factor = ? ORDER BY as_of_date",
        (symbol, factor),
    ).fetchall()
    return [(r["as_of_date"],
             r["value"] if r["value"] is not None else r["text_value"])
            for r in rows]


def snapshot_dates():
    """Every date on which a snapshot exists. Your backtest calendar."""
    conn = _connect()
    rows = conn.execute(
        "SELECT DISTINCT as_of_date FROM factor_snapshots ORDER BY as_of_date"
    ).fetchall()
    return [r["as_of_date"] for r in rows]


def coverage_report():
    """Health check — how much data have you actually banked so far?"""
    conn = _connect()
    q = lambda s: conn.execute(s).fetchone()[0]
    dates = snapshot_dates()
    return {
        "snapshot_dates": len(dates),
        "first_date": dates[0] if dates else None,
        "last_date": dates[-1] if dates else None,
        "total_observations": q("SELECT COUNT(*) FROM factor_snapshots"),
        "distinct_symbols": q("SELECT COUNT(DISTINCT symbol) FROM factor_snapshots"),
        "distinct_factors": q("SELECT COUNT(DISTINCT factor) FROM factor_snapshots"),
        "filings_recorded": q("SELECT COUNT(*) FROM filings"),
        "forward_returns": q("SELECT COUNT(*) FROM forward_returns"),
        "db_size_mb": round(os.path.getsize(DB_PATH) / 1e6, 2)
                      if os.path.exists(DB_PATH) else 0,
    }


# --------------------------------------------------------------------------
# Forward returns (filled by the backtest harness later)
# --------------------------------------------------------------------------

def record_forward_return(as_of, symbol, horizon_days, ret_pct,
                          bench_ret_pct=None):
    excess = None
    if ret_pct is not None and bench_ret_pct is not None:
        excess = ret_pct - bench_ret_pct
    with _tx() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO forward_returns"
            " (as_of_date, symbol, horizon_days, ret_pct, bench_ret_pct,"
            "  excess_pct, computed_utc) VALUES (?,?,?,?,?,?,?)",
            (_as_date(as_of), symbol, horizon_days, ret_pct,
             bench_ret_pct, excess, _utcnow()),
        )


def training_set(factor, horizon_days=63):
    """
    Joins a factor to its forward return. This is the raw material for the
    Factor Lab: does this factor actually predict anything?

    Returns [(as_of_date, symbol, factor_value, excess_pct), ...]
    """
    conn = _connect()
    rows = conn.execute(
        "SELECT s.as_of_date, s.symbol, s.value AS x, f.excess_pct AS y"
        " FROM factor_snapshots s"
        " JOIN forward_returns f"
        "   ON f.as_of_date = s.as_of_date AND f.symbol = s.symbol"
        " WHERE s.factor = ? AND f.horizon_days = ?"
        "   AND s.value IS NOT NULL AND f.excess_pct IS NOT NULL"
        " ORDER BY s.as_of_date",
        (factor, horizon_days),
    ).fetchall()
    return [(r["as_of_date"], r["symbol"], r["x"], r["y"]) for r in rows]


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _utcnow():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _as_date(d=None):
    if d is None:
        return date.today().isoformat()
    if isinstance(d, str):
        return d[:10]
    if isinstance(d, datetime):
        return d.date().isoformat()
    if isinstance(d, date):
        return d.isoformat()
    raise ValueError(f"Cannot interpret date: {d!r}")


def _split_value(raw):
    """Returns (numeric_value, text_value). Exactly one will be non-None."""
    if raw is None:
        return None, None
    if isinstance(raw, bool):
        return (1.0 if raw else 0.0), None
    if isinstance(raw, (int, float)):
        try:
            f = float(raw)
        except (TypeError, ValueError):
            return None, str(raw)
        if f != f or f in (float("inf"), float("-inf")):   # NaN / inf
            return None, None
        return f, None
    if isinstance(raw, str):
        return None, raw
    try:
        return None, json.dumps(raw, default=str)
    except Exception:
        return None, str(raw)


# --------------------------------------------------------------------------

if __name__ == "__main__":
    init_db()
    print("Altaha PIT store ready at:", os.path.abspath(DB_PATH))
    for k, v in coverage_report().items():
        print(f"  {k:24} {v}")
