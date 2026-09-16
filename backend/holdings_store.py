"""
holdings_store.py — who holds what, kept as a ledger

WHAT THIS IS
An append-only record of every named shareholder the exchange filings disclose,
inverted. The shareholding filing answers "who holds this company"; this store
is what lets you ask the other question — "what does this person hold" — which
no single filing can answer, because the answer is spread across two thousand
separate documents.

WHY IT HAS TO BE A STORE AND NOT A LOOKUP
There is no endpoint anywhere that returns an investor's portfolio. Building one
means reading the shareholding filing of every listed company and keeping what
it said. That is ~2,000 documents a quarter, fetched from an exchange that
throttles bursts, on a 512 MB instance. It cannot happen inside a request, so it
happens incrementally in the background and this is where it accumulates.

THE ROW THAT MUST NOT BE COLLAPSED
Titan's March 2026 filing names Rekha Jhunjhunwala TWICE — 4.24% in one folio
and 1.07% in another. They are two rows in the company's own filing and they
must stay two rows here. Keyed on (symbol, period_end, holder) alone, the
second silently overwrites the first and the position reads 1.07% instead of
5.31%: a fifth of the real stake, with nothing on screen suggesting anything
was lost. Hence `slot` in the primary key.

WHAT IS APPEND-ONLY AND WHAT IS NOT
`holdings` is append-only, INSERT OR IGNORE, first write wins — a filing is a
statement made on a date and a re-crawl must not rewrite it. `coverage` is the
opposite: it is the crawler's own bookkeeping, current state rather than
history, and it is meant to be updated.

WHAT THIS DELIBERATELY DOES NOT STORE
Any judgement about who a holder IS. The ledger keeps the string the company
filed and a normalised form of it for indexing, and nothing else. Deciding that
"VIJAY KEDIA" and "Vijay Kishanlal Kedia" are one person is done at READ time,
from a curated table in investors.py, so that correcting an attribution is an
edit to a list rather than a re-crawl of two thousand companies. It also means
a wrong attribution can never become baked into the record.

NO EXTERNAL DEPENDENCIES. Standard library only.
"""

import os
import re
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

DB_PATH = os.environ.get("ALTAHA_HOLDINGS_DB", "").strip() or \
    os.path.join(_DATA_DIR, "altaha_holdings.db")

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


def _utcnow():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _open(path):
    conn = sqlite3.connect(path, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=30000")
    # Same reasoning as pit_store: one connection per thread, each with its own
    # page cache, and a request threadpool multiplies the default 2 MB by the
    # number of threads for a database of a few MB.
    conn.execute("PRAGMA cache_size=-256")
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute("PRAGMA mmap_size=0")
    return conn


SCHEMA = """
CREATE TABLE IF NOT EXISTS holdings (
  symbol      TEXT NOT NULL,
  period_end  TEXT NOT NULL,
  slot        INTEGER NOT NULL,
  holder_raw  TEXT NOT NULL,
  holder_key  TEXT NOT NULL,
  holder_base TEXT NOT NULL DEFAULT '',
  pct         REAL,
  shares      REAL,
  kind        TEXT,
  promoter    INTEGER NOT NULL DEFAULT 0,
  filed       TEXT,
  source_url  TEXT,
  first_seen_utc TEXT NOT NULL,
  PRIMARY KEY (symbol, period_end, slot)
);
CREATE INDEX IF NOT EXISTS idx_holdings_key    ON holdings (holder_key, period_end);
CREATE INDEX IF NOT EXISTS idx_holdings_period ON holdings (period_end);

CREATE TABLE IF NOT EXISTS coverage (
  symbol         TEXT PRIMARY KEY,
  last_try_utc   TEXT,
  last_ok_utc    TEXT,
  latest_period  TEXT,
  quarters       INTEGER NOT NULL DEFAULT 0,
  rows_written   INTEGER NOT NULL DEFAULT 0,
  status         TEXT,
  note           TEXT
);
CREATE INDEX IF NOT EXISTS idx_coverage_try ON coverage (last_try_utc);

-- Fund-house holdings, from the monthly portfolio disclosures SEBI requires.
-- A separate table rather than a column on `holdings`, because they are a
-- different kind of fact: monthly rather than quarterly, complete rather than
-- truncated at 1%, and joined to a company by registered identifier rather
-- than by name. Mixing them into one table would invite a query that averages
-- the two and means nothing.
CREATE TABLE IF NOT EXISTS fund_holdings (
  amc_id      TEXT NOT NULL,
  scheme      TEXT NOT NULL,
  as_of       TEXT NOT NULL,            -- month end, YYYY-MM-DD
  isin        TEXT NOT NULL,
  symbol      TEXT,                     -- NSE symbol where the ISIN maps
  name        TEXT NOT NULL,
  industry    TEXT,
  quantity    REAL,
  value_lakh  REAL,
  pct_nav     REAL,
  first_seen_utc TEXT NOT NULL,
  PRIMARY KEY (amc_id, scheme, as_of, isin)
);
CREATE INDEX IF NOT EXISTS idx_fund_symbol ON fund_holdings (symbol, as_of);
CREATE INDEX IF NOT EXISTS idx_fund_amc    ON fund_holdings (amc_id, as_of);

CREATE TABLE IF NOT EXISTS fund_packs (
  amc_id      TEXT NOT NULL,
  as_of       TEXT NOT NULL,
  amc_name    TEXT,
  source_url  TEXT,
  schemes     INTEGER NOT NULL DEFAULT 0,
  rows        INTEGER NOT NULL DEFAULT 0,
  unmapped    INTEGER NOT NULL DEFAULT 0,
  read_utc    TEXT NOT NULL,
  PRIMARY KEY (amc_id, as_of)
);
"""

# Columns added after the first release. CREATE TABLE IF NOT EXISTS does
# nothing to a table that already exists, so a ledger built by an earlier
# version keeps its old shape and every query naming a new column fails with
# "no such column" — on the live instance, where the ledger is the one thing
# that cannot simply be rebuilt. Each entry is (table, column, definition), and
# adding one is idempotent.
MIGRATIONS = [
    ("holdings", "holder_base", "TEXT NOT NULL DEFAULT ''"),
]

# Indexes are created after the migrations, so an index over a column added
# above is not attempted before the column exists.
INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_holdings_base ON holdings (holder_base, period_end)",
]


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
        # hidden — every caller that surfaces coverage surfaces this too.
        _state["last_error"] = "%s: %s" % (type(e).__name__, e)
        fallback = os.path.join(_HERE, "altaha_holdings.db")
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
        for sql in INDEXES:
            conn.execute(sql)
        conn.commit()
        _ready["done"] = True


def _migrate(conn):
    """Add any column a later version introduced. Idempotent, and never drops
    or rewrites anything — this is a ledger."""
    for table, column, decl in MIGRATIONS:
        have = {r["name"] for r in conn.execute("PRAGMA table_info(%s)" % table)}
        if column not in have:
            conn.execute("ALTER TABLE %s ADD COLUMN %s %s" % (table, column, decl))


def backfill_base_keys(limit=200000):
    """
    Fill holder_base on rows written before that column existed.

    Derived purely from holder_raw, which never changes, so this is a
    recomputation rather than an edit to what a filing said.
    """
    with _tx() as conn:
        rows = conn.execute(
            "SELECT symbol, period_end, slot, holder_raw FROM holdings"
            " WHERE holder_base = '' LIMIT ?", (int(limit),)).fetchall()
        if not rows:
            return 0
        conn.executemany(
            "UPDATE holdings SET holder_base=? WHERE symbol=? AND period_end=? AND slot=?",
            [(holder_base(r["holder_raw"])[:180], r["symbol"], r["period_end"], r["slot"])
             for r in rows])
        return len(rows)


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
# Normalising a holder's name
# ---------------------------------------------------------------------------

# Corporate suffixes carry no identity: "KEDIA SECURITIES PRIVATE LIMITED" and
# "Kedia Securities Pvt Ltd" are one entity. Stripped only for the INDEX key —
# the filed string is kept verbatim on the row and is what gets shown.
_SUFFIXES = (
    "private limited", "pvt limited", "pvt ltd", "private ltd", "p ltd",
    "limited", "ltd", "llp", "inc", "incorporated", "corporation", "corp",
)
_HONORIFICS = ("mr", "mrs", "ms", "shri", "smt", "dr", "sri", "late")
_PUNCT = re.compile(r"[^a-z0-9 ]+")
_SPACE = re.compile(r"\s+")
_PAREN = re.compile(r"\s*\([^()]*\)")


def holder_key(name: str) -> str:
    """
    A stable index key for a filed holder name.

    Deliberately conservative. It folds case, punctuation and corporate
    suffixes — differences that are never a different person — and stops
    there. It does NOT fold initials, middle names or word order, because
    "Vijay Kedia" and "Vijay Kishanlal Kedia" differing by a middle name is
    exactly as likely to be two people as one, and that decision belongs to a
    curated table where a human made it, not to a string function.
    """
    s = (name or "").strip().lower()
    if not s:
        return ""
    s = s.replace("&", " and ")
    s = _PUNCT.sub(" ", s)
    s = _SPACE.sub(" ", s).strip()
    words = s.split()
    while words and words[0] in _HONORIFICS:
        words = words[1:]
    s = " ".join(words)
    changed = True
    while changed:
        changed = False
        for suf in _SUFFIXES:
            if s.endswith(" " + suf):
                s = s[: -(len(suf) + 1)].strip()
                changed = True
    return s


def holder_base(name: str) -> str:
    """
    The key with any parenthetical annotation removed.

    Metro Brands files the same trust as "ARYAMAN JHUNJHUNWALA DISCRETIONARY
    TRUST (TRUSTEE - REKHA RAKESH JHUNJHUNWALA)" while another company writes
    a shorter trustee, and Damani's partnership rows carry "(On behalf of ...)".
    A parenthetical there annotates the holder; it is not part of who they are,
    and an alias table cannot enumerate every wording of it.

    Still exact, never fuzzy: two names match on the base form only when they
    are character-identical once the bracket is gone. The one case this could
    get wrong is two entities distinguished ONLY by their parenthetical — a
    fund's Series A and Series B, say — so the base form is used purely as a
    fallback for a curated alias, never to group rows on its own.
    """
    s = (name or "")
    prev = None
    while prev != s:                 # nested brackets, innermost out
        prev = s
        s = _PAREN.sub(" ", s)
    return holder_key(s)


# Rows the exchange format emits that are category totals, not holders. Left in
# the ledger they become an "investor" called Foreign Institutional Investors
# holding four hundred companies.
_NOT_A_HOLDER = {
    "foreign bank", "foreign institutional investors", "foreign portfolio investors",
    "mutual funds", "mutual fund", "insurance companies", "financial institutions banks",
    "alternate investment funds", "public", "promoter", "promoter group", "others",
    "bodies corporate", "resident individuals", "nri", "clearing members",
    "trusts", "hindu undivided family", "non resident indians", "banks",
    "central government state government s president of india",
    "investor education and protection fund authority",
    "investor education and protection fund authority ministry of corporate affairs",
}


def is_real_holder(name: str, key: str = None) -> bool:
    """
    A named person or entity, rather than a category heading.

    The filings put both through the same element. "Foreign Institutional
    Investors, 0.00%" is a row in Titan's filing and it is not a shareholder.
    """
    k = key if key is not None else holder_key(name)
    if not k or len(k) < 3:
        return False
    if k in _NOT_A_HOLDER:
        return False
    # A name that is only digits or a single token of punctuation-stripped
    # noise is not a holder either.
    return any(c.isalpha() for c in k)


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------

def record_filing(symbol, period_end, names, filed=None, source_url=None):
    """
    Write one company-quarter's named holders.

    `names` is the list shareholding_filings.parse() produces. Returns the
    number of rows actually inserted — zero on a re-crawl of a quarter already
    held, which is how the crawler tells new work from repeated work.

    `slot` is the position in the filing's own ordering. It is what keeps two
    folios of the same name as two rows, and it makes re-running idempotent:
    the same filing parsed again yields the same slots.
    """
    sym = (symbol or "").strip().upper()
    if not sym or not period_end:
        return 0
    rows, slot = [], 0
    now = _utcnow()
    for n in names or []:
        raw = (n.get("name") or "").strip()
        key = holder_key(raw)
        if not is_real_holder(raw, key):
            continue
        pct = n.get("pct")
        # A named row at or below zero per cent is a disclosure artefact, not a
        # position. Keeping it would put companies into a portfolio that the
        # investor does not hold.
        if pct is None or pct <= 0:
            continue
        rows.append((sym, period_end, slot, raw[:180], key[:180],
                     holder_base(raw)[:180], float(pct),
                     n.get("shares"), (n.get("kind") or "")[:60],
                     1 if n.get("promoter") else 0, filed, source_url, now))
        slot += 1
    if not rows:
        return 0
    with _tx() as conn:
        before = conn.total_changes
        conn.executemany(
            "INSERT OR IGNORE INTO holdings (symbol, period_end, slot, holder_raw,"
            " holder_key, holder_base, pct, shares, kind, promoter, filed,"
            " source_url, first_seen_utc) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
        return conn.total_changes - before


def mark_coverage(symbol, status, latest_period=None, quarters=0,
                  rows_written=0, note=None, ok=False):
    """The crawler's bookkeeping. Current state, updated in place — unlike the
    ledger, which is history and is not."""
    sym = (symbol or "").strip().upper()
    if not sym:
        return
    now = _utcnow()
    with _tx() as conn:
        conn.execute(
            "INSERT INTO coverage (symbol, last_try_utc, last_ok_utc, latest_period,"
            " quarters, rows_written, status, note) VALUES (?,?,?,?,?,?,?,?)"
            " ON CONFLICT(symbol) DO UPDATE SET"
            "   last_try_utc=excluded.last_try_utc,"
            "   last_ok_utc=COALESCE(excluded.last_ok_utc, coverage.last_ok_utc),"
            "   latest_period=COALESCE(excluded.latest_period, coverage.latest_period),"
            "   quarters=MAX(excluded.quarters, coverage.quarters),"
            "   rows_written=coverage.rows_written + excluded.rows_written,"
            "   status=excluded.status, note=excluded.note",
            (sym, now, now if ok else None, latest_period, int(quarters or 0),
             int(rows_written or 0), status, (note or "")[:200]))


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------

def periods(limit=12):
    """Every period end in the ledger, newest first."""
    conn = _connect()
    rows = conn.execute(
        "SELECT period_end, COUNT(DISTINCT symbol) AS companies, COUNT(*) AS rows"
        " FROM holdings GROUP BY period_end ORDER BY period_end DESC LIMIT ?",
        (int(limit),)).fetchall()
    return [dict(r) for r in rows]


def latest_period():
    conn = _connect()
    r = conn.execute("SELECT MAX(period_end) AS p FROM holdings").fetchone()
    return r["p"] if r else None


def positions_for_keys(keys, period_end=None):
    """
    Every row filed by any of `keys`, newest quarter first.

    Matched on the exact key or on the parenthetical-free base form, so a trust
    whose trustee suffix is worded differently by two companies is still the
    same trust. `matched_on` says which rule fired, because a reader auditing
    an attribution should be able to see why a row was included.

    Rows, not positions: two folios of one name in one company come back as two
    rows and the caller sums them. Summing here would hide the split, and the
    split is worth showing — it is the difference between a position and a
    position held two ways.
    """
    keys = [k for k in {(k or "").strip() for k in (keys or [])} if k]
    if not keys:
        return []
    conn = _connect()
    marks = ",".join("?" * len(keys))
    sql = ("SELECT symbol, period_end, holder_raw, holder_key, holder_base, pct,"
           " shares, kind, promoter, filed, source_url,"
           " CASE WHEN holder_key IN (%s) THEN 'name' ELSE 'name-without-bracket'"
           " END AS matched_on"
           " FROM holdings WHERE holder_key IN (%s) OR holder_base IN (%s)"
           % (marks, marks, marks))
    args = list(keys) * 3
    if period_end:
        sql += " AND period_end = ?"
        args.append(period_end)
    sql += " ORDER BY period_end DESC, pct DESC"
    return [dict(r) for r in conn.execute(sql, args).fetchall()]


def holders_of(symbol, period_end=None):
    """Every named holder of one company — the direction the filing already
    answers, served from the ledger so the stock page costs no network."""
    sym = (symbol or "").strip().upper()
    if not sym:
        return []
    conn = _connect()
    if period_end is None:
        r = conn.execute("SELECT MAX(period_end) AS p FROM holdings WHERE symbol=?",
                         (sym,)).fetchone()
        period_end = r["p"] if r else None
    if not period_end:
        return []
    rows = conn.execute(
        "SELECT symbol, period_end, holder_raw, holder_key, holder_base, pct,"
        " shares, kind, promoter, filed, source_url FROM holdings"
        " WHERE symbol=? AND period_end=? ORDER BY pct DESC",
        (sym, period_end)).fetchall()
    return [dict(r) for r in rows]


def symbols_seen():
    conn = _connect()
    return [r[0] for r in conn.execute(
        "SELECT DISTINCT symbol FROM holdings ORDER BY symbol").fetchall()]


def due_symbols(universe, limit=60, stale_hours=24 * 20):
    """
    What the crawler should fetch next.

    Never-tried symbols first, then the ones tried longest ago. A sweep of two
    thousand companies takes many runs, and this is what makes each run
    continue the last rather than restart it.
    """
    conn = _connect()
    seen = {r["symbol"]: r for r in conn.execute(
        "SELECT symbol, last_try_utc, status FROM coverage").fetchall()}
    cutoff = _utcnow()[:10]
    fresh = []
    try:
        from datetime import timedelta
        cutoff_dt = datetime.now(timezone.utc) - timedelta(hours=stale_hours)
        cutoff = cutoff_dt.isoformat(timespec="seconds")
    except Exception:
        pass
    never, stale = [], []
    for sym in universe or []:
        s = (sym or "").strip().upper()
        if not s:
            continue
        row = seen.get(s)
        if row is None:
            never.append(s)
        elif (row["last_try_utc"] or "") < cutoff:
            stale.append((row["last_try_utc"] or "", s))
    stale.sort()
    fresh = never + [s for _t, s in stale]
    return fresh[: max(1, int(limit))]


# ---------------------------------------------------------------------------
# Fund houses
# ---------------------------------------------------------------------------

def record_fund_pack(amc_id, amc_name, as_of, schemes, source_url=None,
                     symbol_for=None):
    """
    One AMC's monthly pack.

    `schemes` is what fund_workbook.parse_workbook returns. `symbol_for` maps
    an ISIN to an NSE symbol; a holding whose ISIN does not map is still
    stored, with a null symbol, and counted — it is a real position in
    something unlisted, foreign or not equity, and dropping it silently would
    make every weight on the page add up to less than the fund actually holds
    without saying why.
    """
    amc_id = (amc_id or "").strip()
    if not amc_id or not as_of:
        return {"rows": 0, "schemes": 0, "unmapped": 0, "seen": 0}
    now = _utcnow()
    rows, unmapped = [], 0
    for pack in schemes or []:
        sheet = pack.get("scheme") or pack.get("sheet") or ""
        for h in pack.get("holdings") or []:
            isin = (h.get("isin") or "").strip().upper()
            if not isin:
                continue
            sym = symbol_for(isin) if symbol_for else None
            if not sym:
                unmapped += 1
            rows.append((amc_id, sheet[:120], as_of, isin, sym,
                         (h.get("name") or "")[:160], (h.get("industry") or None),
                         h.get("quantity"), h.get("value_lakh"), h.get("pct_nav"),
                         now))
    if not rows:
        return {"rows": 0, "schemes": 0, "unmapped": 0, "seen": 0}
    with _tx() as conn:
        before = conn.total_changes
        conn.executemany(
            "INSERT OR IGNORE INTO fund_holdings (amc_id, scheme, as_of, isin,"
            " symbol, name, industry, quantity, value_lakh, pct_nav,"
            " first_seen_utc) VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows)
        written = conn.total_changes - before
        conn.execute(
            "INSERT INTO fund_packs (amc_id, as_of, amc_name, source_url,"
            " schemes, rows, unmapped, read_utc) VALUES (?,?,?,?,?,?,?,?)"
            " ON CONFLICT(amc_id, as_of) DO UPDATE SET"
            "   amc_name=excluded.amc_name, source_url=excluded.source_url,"
            "   schemes=excluded.schemes, rows=excluded.rows,"
            "   unmapped=excluded.unmapped, read_utc=excluded.read_utc",
            (amc_id, as_of, amc_name, source_url, len(schemes or []),
             len(rows), unmapped, now))
    return {"rows": written, "schemes": len(schemes or []),
            "unmapped": unmapped, "seen": len(rows)}


def fund_months(limit=12):
    conn = _connect()
    return [dict(r) for r in conn.execute(
        "SELECT as_of, COUNT(DISTINCT amc_id) AS amcs, COUNT(*) AS rows"
        " FROM fund_holdings GROUP BY as_of ORDER BY as_of DESC LIMIT ?",
        (int(limit),)).fetchall()]


def latest_fund_month():
    conn = _connect()
    r = conn.execute("SELECT MAX(as_of) AS m FROM fund_holdings").fetchone()
    return r["m"] if r else None


def fund_positions(amc_id, as_of=None, min_pct=0.0):
    """Every listed-equity position an AMC disclosed, newest month by default."""
    conn = _connect()
    as_of = as_of or latest_fund_month()
    if not as_of or not amc_id:
        return []
    return [dict(r) for r in conn.execute(
        "SELECT scheme, isin, symbol, name, industry, quantity, value_lakh,"
        " pct_nav FROM fund_holdings WHERE amc_id=? AND as_of=? AND pct_nav >= ?"
        " ORDER BY value_lakh DESC", (amc_id, as_of, float(min_pct))).fetchall()]


def funds_holding(symbol, as_of=None):
    """Which schemes hold one company — the direction a stock page asks in."""
    sym = (symbol or "").strip().upper()
    conn = _connect()
    as_of = as_of or latest_fund_month()
    if not sym or not as_of:
        return []
    return [dict(r) for r in conn.execute(
        "SELECT amc_id, scheme, isin, name, quantity, value_lakh, pct_nav"
        " FROM fund_holdings WHERE symbol=? AND as_of=?"
        " ORDER BY value_lakh DESC", (sym, as_of)).fetchall()]


def fund_packs(as_of=None):
    conn = _connect()
    as_of = as_of or latest_fund_month()
    if not as_of:
        return []
    return [dict(r) for r in conn.execute(
        "SELECT * FROM fund_packs WHERE as_of=? ORDER BY rows DESC",
        (as_of,)).fetchall()]


def stats():
    """What the store actually holds, for the admin view and the pane's footer."""
    conn = _connect()
    def one(sql, *a):
        r = conn.execute(sql, a).fetchone()
        return (r[0] if r and r[0] is not None else 0)
    cov = conn.execute(
        "SELECT status, COUNT(*) AS n FROM coverage GROUP BY status").fetchall()
    return {
        "path": _state["active_path"],
        "persistent": not _state["fell_back"] and _state["data_dir_from_env"],
        "fell_back": _state["fell_back"],
        "last_error": _state["last_error"],
        "rows": one("SELECT COUNT(*) FROM holdings"),
        "companies": one("SELECT COUNT(DISTINCT symbol) FROM holdings"),
        "holders": one("SELECT COUNT(DISTINCT holder_key) FROM holdings"),
        "periods": [p["period_end"] for p in periods(8)],
        "latest_period": latest_period(),
        "coverage": {(r["status"] or "unknown"): r["n"] for r in cov},
        "tried": one("SELECT COUNT(*) FROM coverage"),
        "funds": {
            "rows": one("SELECT COUNT(*) FROM fund_holdings"),
            "amcs": one("SELECT COUNT(DISTINCT amc_id) FROM fund_holdings"),
            "schemes": one("SELECT COUNT(DISTINCT amc_id || scheme) FROM fund_holdings"),
            "latest_month": latest_fund_month(),
            "months": [m["as_of"] for m in fund_months(6)],
        },
    }
