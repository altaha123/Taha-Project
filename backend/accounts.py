"""
Accounts, sessions and saved portfolios.

WHY SQLITE AND NOT A HOSTED DATABASE
Because it works today. A hosted Postgres means an account somewhere, keys
handed over, and a bill — and none of that makes the first user's watchlist
survive their next phone any better than the disk this service already mounts.
tracker.py and pit_store.py have kept the two datasets that cannot be rebuilt
on that disk for months. Every statement here is plain SQL through one module,
so moving to Postgres later is a change to this file and nothing else.

WHY BEARER TOKENS AND NOT COOKIES
The site is altahascreener.in and the API is on onrender.com. Those are
different origins, so a session cookie would have to be SameSite=None, which
means Secure, credentialed CORS, an explicit origin allowlist in place of the
"*" this API uses today, and a CSRF story. An opaque bearer token in the
Authorization header sidesteps all of it and cannot be attached to a request
by somebody else's page.

WHY MAGIC LINKS AND NOT PASSWORDS
A password means a reset flow, a hashing choice, a breach to worry about, and
one more thing for a person to reuse from another site. A link to the address
they typed proves they own the address — which is exactly what a product that
emails you a daily digest needs to establish anyway.

WHAT IS STORED, AND WHAT IS NOT
An email address, what somebody holds, and when they were last emailed. No
passwords, ever. Tokens are stored as SHA-256 digests, so a copy of this
database does not let the holder log in as anybody: a stolen digest cannot be
turned back into the link that was mailed.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import os
import re
import secrets
import sqlite3
import threading

_HERE = os.path.dirname(os.path.abspath(__file__))
_DATA_DIR = os.environ.get("DATA_DIR", "").strip() or _HERE
try:
    os.makedirs(_DATA_DIR, exist_ok=True)
except Exception:                                             # pragma: no cover
    _DATA_DIR = _HERE

DB_PATH = os.environ.get("ALTAHA_ACCOUNTS_DB", "").strip() or \
    os.path.join(_DATA_DIR, "altaha_accounts.db")

# A login link is short-lived on purpose: it sits in an inbox, and inboxes are
# forwarded, synced and occasionally shared. Fifteen minutes is enough to walk
# to a laptop and not much else.
LOGIN_TTL_MINUTES = 15
SESSION_TTL_DAYS = 90

# Anyone can type anyone's address into a login box, so the throttle protects
# the person who owns the address from being mailed repeatedly by a stranger,
# not just the sender's reputation.
MAX_LINKS_PER_EMAIL_PER_HOUR = 5
MAX_HOLDINGS = 100

_local = threading.local()
_state = {"path": DB_PATH, "fell_back": False, "last_error": None}

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s.]+\.[^@\s]{2,}$")


def valid_email(raw) -> str:
    """Normalised address, or "". Lowercased because People@X and people@x are
    the same inbox, and two accounts for one person is a support problem."""
    s = str(raw or "").strip().lower()
    return s if len(s) <= 254 and EMAIL_RE.match(s) else ""


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _iso(t: dt.datetime) -> str:
    return t.replace(microsecond=0).isoformat()


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  email         TEXT NOT NULL UNIQUE,
  created_at    TEXT NOT NULL,
  last_login_at TEXT,
  digest_opt_in INTEGER NOT NULL DEFAULT 1,
  unsub_token   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS login_tokens (
  token_hash TEXT PRIMARY KEY,
  email      TEXT NOT NULL,
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  used_at    TEXT
);
CREATE INDEX IF NOT EXISTS idx_login_email ON login_tokens(email, created_at);
CREATE TABLE IF NOT EXISTS sessions (
  token_hash TEXT PRIMARY KEY,
  user_id    INTEGER NOT NULL,
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  last_seen  TEXT
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
CREATE TABLE IF NOT EXISTS holdings (
  user_id    INTEGER NOT NULL,
  symbol     TEXT NOT NULL,
  qty        REAL NOT NULL,
  avg_price  REAL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (user_id, symbol)
);
-- What was sent, so a retry after a crash cannot mail the same person the
-- same day twice. The digest job is not transactional; this table is what
-- makes it safe to run again.
CREATE TABLE IF NOT EXISTS send_log (
  user_id  INTEGER NOT NULL,
  kind     TEXT NOT NULL,
  ref_date TEXT NOT NULL,
  sent_at  TEXT NOT NULL,
  ok       INTEGER NOT NULL,
  detail   TEXT,
  PRIMARY KEY (user_id, kind, ref_date)
);
"""


def _open(path):
    conn = sqlite3.connect(path, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA cache_size=-256")
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute("PRAGMA mmap_size=0")
    conn.executescript(SCHEMA)
    return conn


def _connect():
    """One connection per thread, as pit_store does — safe under the request
    threadpool, and each connection keeps its own small page cache."""
    conn = getattr(_local, "conn", None)
    if conn is not None:
        return conn
    try:
        conn = _open(_state["path"])
    except Exception as e:
        # An accounts database that cannot be written is not something to hide
        # behind a fallback: somebody would "log in", save a portfolio, and
        # lose it on the next deploy. It is reported and it fails.
        _state["last_error"] = f"{type(e).__name__}: {e}"
        raise
    _local.conn = conn
    return conn


def reset_for_tests(path: str):                               # pragma: no cover
    _state["path"] = path
    _local.conn = None


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------

def start_login(email: str) -> dict:
    """Mint a login link. Returns {"token", "email"} or {"error"}.

    The token is returned rather than emailed here: sending is the mailer's
    job, and keeping them apart means this whole flow is testable without a
    mail provider and works the same whichever provider is configured.
    """
    addr = valid_email(email)
    if not addr:
        return {"error": "That does not look like an email address."}

    conn = _connect()
    hour_ago = _iso(_now() - dt.timedelta(hours=1))
    recent = conn.execute(
        "SELECT COUNT(*) AS n FROM login_tokens WHERE email=? AND created_at>=?",
        (addr, hour_ago)).fetchone()["n"]
    if recent >= MAX_LINKS_PER_EMAIL_PER_HOUR:
        return {"error": "Too many login links for that address in the last hour. "
                         "Check your inbox, including spam."}

    token = secrets.token_urlsafe(32)
    now = _now()
    with conn:
        conn.execute(
            "INSERT INTO login_tokens(token_hash,email,created_at,expires_at) "
            "VALUES(?,?,?,?)",
            (_hash(token), addr, _iso(now),
             _iso(now + dt.timedelta(minutes=LOGIN_TTL_MINUTES))))
    return {"token": token, "email": addr}


def complete_login(token: str) -> dict:
    """Spend a login token. Returns {"session", "user"} or {"error"}.

    Single use. A link that has been clicked once is dead, so a forwarded
    email, a browser prefetch or a mail scanner that follows links cannot be
    replayed into a second session.
    """
    if not token:
        return {"error": "This login link is not valid."}
    conn = _connect()
    row = conn.execute("SELECT * FROM login_tokens WHERE token_hash=?",
                       (_hash(token),)).fetchone()
    if row is None:
        return {"error": "This login link is not valid."}
    if row["used_at"]:
        return {"error": "This login link has already been used. Ask for a new one."}
    if row["expires_at"] < _iso(_now()):
        return {"error": "This login link has expired. Ask for a new one."}

    now = _now()
    with conn:
        conn.execute("UPDATE login_tokens SET used_at=? WHERE token_hash=?",
                     (_iso(now), _hash(token)))
        user = conn.execute("SELECT * FROM users WHERE email=?",
                            (row["email"],)).fetchone()
        if user is None:
            conn.execute(
                "INSERT INTO users(email,created_at,last_login_at,unsub_token) "
                "VALUES(?,?,?,?)",
                (row["email"], _iso(now), _iso(now), secrets.token_urlsafe(24)))
            user = conn.execute("SELECT * FROM users WHERE email=?",
                                (row["email"],)).fetchone()
        else:
            conn.execute("UPDATE users SET last_login_at=? WHERE id=?",
                         (_iso(now), user["id"]))

        session = secrets.token_urlsafe(32)
        conn.execute(
            "INSERT INTO sessions(token_hash,user_id,created_at,expires_at,last_seen) "
            "VALUES(?,?,?,?,?)",
            (_hash(session), user["id"], _iso(now),
             _iso(now + dt.timedelta(days=SESSION_TTL_DAYS)), _iso(now)))

    return {"session": session, "user": _user_dict(user)}


def user_for_session(token: str):
    """The user behind a bearer token, or None."""
    if not token:
        return None
    conn = _connect()
    row = conn.execute(
        "SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id "
        "WHERE s.token_hash=? AND s.expires_at>?",
        (_hash(token), _iso(_now()))).fetchone()
    if row is None:
        return None
    try:
        with conn:
            conn.execute("UPDATE sessions SET last_seen=? WHERE token_hash=?",
                         (_iso(_now()), _hash(token)))
    except Exception:
        pass
    return _user_dict(row)


def logout(token: str) -> bool:
    if not token:
        return False
    conn = _connect()
    with conn:
        cur = conn.execute("DELETE FROM sessions WHERE token_hash=?", (_hash(token),))
    return cur.rowcount > 0


def _user_dict(row) -> dict:
    return {"id": row["id"], "email": row["email"], "created_at": row["created_at"],
            "digest_opt_in": bool(row["digest_opt_in"]),
            "unsub_token": row["unsub_token"]}


# ---------------------------------------------------------------------------
# Portfolios
# ---------------------------------------------------------------------------

def _clean_symbol(s) -> str:
    s = str(s or "").strip().upper().replace(".NS", "").replace(".BO", "")
    return s if re.match(r"^[A-Z0-9&.\-]{1,20}$", s) else ""


def save_holdings(user_id: int, rows: list) -> dict:
    """Replace the whole portfolio. Returns {"saved": n, "rejected": [...]}.

    Replace rather than merge: the UI shows a list and a Save button, and a
    merge would make a deleted row reappear — the single most alarming thing a
    portfolio screen can do.
    """
    good, rejected = {}, []
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        sym = _clean_symbol(r.get("symbol"))
        try:
            qty = float(r.get("qty"))
        except (TypeError, ValueError):
            qty = None
        if not sym:
            rejected.append({"symbol": str(r.get("symbol"))[:20], "why": "unreadable symbol"})
            continue
        if qty is None or qty <= 0 or qty != qty:
            rejected.append({"symbol": sym, "why": "quantity must be a positive number"})
            continue
        avg = r.get("avg_price")
        try:
            avg = float(avg) if avg not in (None, "") else None
            if avg is not None and (avg <= 0 or avg != avg):
                avg = None
        except (TypeError, ValueError):
            avg = None
        # Later rows win, so pasting a CSV with the same scrip twice keeps one
        # line rather than failing the whole import.
        good[sym] = (qty, avg)
        if len(good) > MAX_HOLDINGS:
            rejected.append({"symbol": sym, "why": f"over the {MAX_HOLDINGS}-holding limit"})
            good.pop(sym)
            break

    now = _iso(_now())
    conn = _connect()
    with conn:
        conn.execute("DELETE FROM holdings WHERE user_id=?", (user_id,))
        conn.executemany(
            "INSERT INTO holdings(user_id,symbol,qty,avg_price,updated_at) VALUES(?,?,?,?,?)",
            [(user_id, s, q, a, now) for s, (q, a) in good.items()])
    return {"saved": len(good), "rejected": rejected}


def get_holdings(user_id: int) -> list:
    conn = _connect()
    rows = conn.execute(
        "SELECT symbol,qty,avg_price FROM holdings WHERE user_id=? ORDER BY symbol",
        (user_id,)).fetchall()
    return [{"symbol": r["symbol"], "qty": r["qty"], "avg_price": r["avg_price"]}
            for r in rows]


# ---------------------------------------------------------------------------
# The daily send
# ---------------------------------------------------------------------------

def set_digest_opt_in(user_id: int, on: bool) -> None:
    conn = _connect()
    with conn:
        conn.execute("UPDATE users SET digest_opt_in=? WHERE id=?",
                     (1 if on else 0, user_id))


def unsubscribe_by_token(token: str) -> bool:
    """One click, no login. Anything else and people press the spam button
    instead, which costs the sender's reputation rather than one subscriber."""
    if not token:
        return False
    conn = _connect()
    with conn:
        cur = conn.execute(
            "UPDATE users SET digest_opt_in=0 WHERE unsub_token=?", (token,))
    return cur.rowcount > 0


def digest_recipients() -> list:
    """Everyone who has opted in AND actually holds something."""
    conn = _connect()
    rows = conn.execute(
        "SELECT u.id,u.email,u.unsub_token FROM users u "
        "WHERE u.digest_opt_in=1 AND EXISTS "
        "(SELECT 1 FROM holdings h WHERE h.user_id=u.id)").fetchall()
    return [{"id": r["id"], "email": r["email"], "unsub_token": r["unsub_token"]}
            for r in rows]


def already_sent(user_id: int, kind: str, ref_date: str) -> bool:
    conn = _connect()
    row = conn.execute(
        "SELECT ok FROM send_log WHERE user_id=? AND kind=? AND ref_date=?",
        (user_id, kind, ref_date)).fetchone()
    return bool(row and row["ok"])


def record_send(user_id: int, kind: str, ref_date: str, ok: bool, detail: str = "") -> None:
    conn = _connect()
    with conn:
        conn.execute(
            "INSERT OR REPLACE INTO send_log(user_id,kind,ref_date,sent_at,ok,detail) "
            "VALUES(?,?,?,?,?,?)",
            (user_id, kind, ref_date, _iso(_now()), 1 if ok else 0, detail[:200]))


def stats() -> dict:
    """For /health and for answering "is anybody using this yet"."""
    try:
        conn = _connect()
        one = lambda q: conn.execute(q).fetchone()[0]              # noqa: E731
        return {
            "ok": True,
            "path": _state["path"],
            "users": one("SELECT COUNT(*) FROM users"),
            "with_holdings": one("SELECT COUNT(DISTINCT user_id) FROM holdings"),
            "opted_in": one("SELECT COUNT(*) FROM users WHERE digest_opt_in=1"),
            "sessions": one("SELECT COUNT(*) FROM sessions WHERE expires_at>'%s'"
                            % _iso(_now())),
        }
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}",
                "path": _state["path"]}


def purge_expired() -> dict:
    """Housekeeping. Dead sessions and spent login tokens are not evidence of
    anything and keeping them is a liability rather than an asset."""
    conn = _connect()
    now = _iso(_now())
    with conn:
        s = conn.execute("DELETE FROM sessions WHERE expires_at<=?", (now,)).rowcount
        t = conn.execute(
            "DELETE FROM login_tokens WHERE expires_at<=? OR used_at IS NOT NULL",
            (now,)).rowcount
    return {"sessions_removed": s, "login_tokens_removed": t}
