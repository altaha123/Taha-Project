"""
Wealth desk: a portfolio manager's book of clients.

WHO IT IS FOR
Somebody who looks after other people's money — a portfolio manager, an
adviser, the family member everybody hands their demat login to — and is
keeping it all in a spreadsheet. For every client they need to know what is
held, at what price it was RECOMMENDED and at what price the client actually
BOUGHT, what it is worth now, and — when the arrangement is a share of the
profits — what they have earned. This module is that spreadsheet, with the
arithmetic done properly and shown.

WHAT A DESK HOLDS
  desk         the manager: name, firm, registration, default fee terms
  clients      one row each: who, since when, risk, status, and their terms
  events       the ledger — buy, sell, deposit, withdrawal, dividend, split.
               Everything else (holdings, cash, profit, fees) is computed
               from it, so there is one record of what happened and no total
               that can drift away from it.
  recs         the manager's calls: buy/sell, the price, target, stop, why.
               A call can be booked for many clients at once; each client's
               fill keeps the recommended price beside the price they got.
  settlements  fees crystallised: the period, the profit level at the end
               of it, the amount billed and whether it has been paid. These
               are the anchors the high-water mark is measured from.
  prices       a hand-set price for anything without a live quote — an
               unlisted share, a fund, a bond.

THE PROFIT, ONE NUMBER, TWO WAYS
Cumulative profit since the client started is

    P = sale proceeds + market value of what is held − cost of every buy
        + dividends − charges

which is the same number as realised + unrealised + dividends − charges.
Deposits and withdrawals do not appear in it at all: money moving in or out
is not a gain or a loss. "Booked" profit is the same with the unrealised
part left out. A fee agreement chooses which of the two it is measured on.

CAPITAL, AND WHY CASH NEVER GOES NEGATIVE
Many managers record trades and never the money behind them. So a buy that
costs more than the cash on hand is treated as the client topping up exactly
the shortfall, that day. With deposits recorded this changes nothing; with
none, capital is simply the money the client had to put in, and returns,
the hurdle and the fixed fee all have something honest to be measured on.

THE FEE
For the period since the last settlement:

    new profit   = profit now − the high-water mark   (or − the profit at the
                   last settlement, when there is no high-water mark)
    fixed fee    = fixed % a year × capital × days invested / 365
    hurdle       = hurdle % a year × capital × days invested / 365
    above hurdle = new profit − fixed fee − hurdle     (hard hurdle)
                   new profit − fixed fee, if it clears the hurdle (soft)
    share        = share % × above hurdle, never below zero
    due          = fixed fee + share, plus GST if the desk charges it

The high-water mark is the highest profit level at any past settlement, and
never below zero — so a client who lost money pays no share of profits
until the loss is made back. That is the rule SEBI requires of registered
portfolio managers, and it is on by default.

Capital is time-weighted ("rupee-days"): a rupee invested for ten days of a
ninety-day quarter carries a ninth of the hurdle, not all of it.

WHAT IS NOT STORED
No PAN, no Aadhaar, no bank details, no demat login. A client is a name, an
optional email and phone, and their trades. The email matters only if the
manager chooses to show a client their own portfolio: that client signs in
with that address and sees it, read-only, and nobody else's.

Every statement is plain SQL against the accounts database, like advisors.py,
so the nightly backup already covers it.
"""
from __future__ import annotations

import datetime as dt
import json
import math
import re
import threading

import accounts

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))

# ---------------------------------------------------------------------------
# Limits and vocabulary
# ---------------------------------------------------------------------------

MAX_CLIENTS = 300
MAX_EVENTS = 3000          # per client
MAX_RECS = 500
MAX_IMPORT = 500           # rows in one paste
MAX_NOTE = 2000
MAX_TAGS = 8

COLORS = ("gold", "green", "blue", "rose", "violet", "slate")
RISKS = ("conservative", "moderate", "aggressive")
STATUSES = ("active", "paused", "closed")
PERIODS = ("monthly", "quarterly", "half-yearly", "yearly")
BASES = ("total", "realised")
HURDLES = ("hard", "soft")
EVENT_KINDS = ("buy", "sell", "deposit", "withdrawal", "dividend", "split")
SETTLE_STATUSES = ("due", "paid", "waived", "nil")

# Same-day order. Money arrives before it is spent, and leaves after the
# sale that raised it.
_ORDER = {"deposit": 0, "dividend": 1, "split": 2, "buy": 3, "sell": 3, "withdrawal": 4}

REGISTRATIONS = {
    "pms": {"label": "SEBI-registered Portfolio Manager", "short": "SEBI PMS",
            "pattern": r"^INP\d{9}$", "hint": "INP followed by nine digits"},
    "ria": {"label": "SEBI-registered Investment Adviser", "short": "SEBI RIA",
            "pattern": r"^INA\d{9}$", "hint": "INA followed by nine digits"},
    "ra": {"label": "SEBI-registered Research Analyst", "short": "SEBI RA",
           "pattern": r"^INH\d{9}$", "hint": "INH followed by nine digits"},
    "mfd": {"label": "AMFI-registered Mutual Fund Distributor", "short": "AMFI ARN",
            "pattern": r"^ARN-\d{1,7}$", "hint": "ARN- followed by its digits"},
    "none": {"label": "Not registered", "short": "", "pattern": None, "hint": ""},
}

DEFAULT_TERMS = {
    "share_pct": 20.0,      # % of profit
    "hurdle_pct": 0.0,      # % a year
    "hurdle_type": "hard",
    "hwm": True,
    "fixed_pct": 0.0,       # % a year of capital
    "basis": "total",       # total (booked + on paper) | realised (booked only)
    "gst_pct": 0.0,         # 18 when the manager is GST-registered
    "period": "quarterly",
}

DISCLAIMER = (
    "Your private book. Only you can see it, and a client sees only their own "
    "portfolio, and only if you switch that on. Prices are delayed daily closes from "
    "Yahoo Finance, or live from Dhan when it is connected; anything without a "
    "quote is valued at the price you set, or at cost. Fees are worked out from "
    "the terms you enter. Check them against your signed agreement before you bill."
)

FEE_NOTE = (
    "Under SEBI's rules a share of profits is a portfolio manager's fee, and it must "
    "be measured from a high-water mark. A registered investment adviser may charge "
    "only a fixed fee or a fee on assets under advice. Altaha does the arithmetic; "
    "whether an arrangement is allowed depends on your registration. Ask your "
    "compliance officer or lawyer if you are unsure."
)

SYMBOL_RE = re.compile(r"^[A-Z0-9&.\-]{1,20}$")
_CODE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9\-_/]{0,15}$")
_PHONE_RE = re.compile(r"^[+0-9][0-9 \-]{6,18}$")
_CTRL = re.compile(r"[\u0000-\u001f\u007f]")


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS wm_desks (
  user_id      INTEGER PRIMARY KEY,
  display_name TEXT NOT NULL,
  firm         TEXT,
  reg_kind     TEXT NOT NULL DEFAULT 'none',
  registration TEXT,
  terms        TEXT NOT NULL,          -- JSON, the defaults for a new client
  created_at   TEXT NOT NULL,
  updated_at   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS wm_clients (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id    INTEGER NOT NULL,
  code       TEXT NOT NULL,
  name       TEXT NOT NULL,
  email      TEXT,
  phone      TEXT,
  city       TEXT,
  risk       TEXT NOT NULL DEFAULT 'moderate',
  status     TEXT NOT NULL DEFAULT 'active',
  color      TEXT NOT NULL DEFAULT 'gold',
  since      TEXT NOT NULL,
  terms      TEXT NOT NULL,            -- JSON
  tags       TEXT NOT NULL DEFAULT '[]',
  notes      TEXT,
  portal     INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE (user_id, code)
);
CREATE INDEX IF NOT EXISTS idx_wm_clients_user ON wm_clients(user_id);
CREATE INDEX IF NOT EXISTS idx_wm_clients_email ON wm_clients(email);
-- The ledger. qty is shares for a buy or sell and the factor for a split
-- (2 for a 1:1 bonus or a 2-for-1 split); amount is rupees for money moving.
CREATE TABLE IF NOT EXISTS wm_events (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id    INTEGER NOT NULL,
  client_id  INTEGER NOT NULL,
  kind       TEXT NOT NULL,
  symbol     TEXT,
  qty        REAL,
  price      REAL,
  amount     REAL,
  charges    REAL NOT NULL DEFAULT 0,
  rec_id     INTEGER,
  rec_price  REAL,
  on_date    TEXT NOT NULL,
  note       TEXT,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_wm_events_client ON wm_events(client_id, on_date, id);
CREATE INDEX IF NOT EXISTS idx_wm_events_user ON wm_events(user_id);
CREATE TABLE IF NOT EXISTS wm_recs (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id     INTEGER NOT NULL,
  symbol      TEXT NOT NULL,
  action      TEXT NOT NULL,            -- buy | sell
  price       REAL NOT NULL,
  target      REAL,
  stop        REAL,
  on_date     TEXT NOT NULL,
  horizon     TEXT,
  thesis      TEXT,
  status      TEXT NOT NULL DEFAULT 'open',
  closed_on   TEXT,
  close_price REAL,
  created_at  TEXT NOT NULL,
  updated_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_wm_recs_user ON wm_recs(user_id, on_date);
-- A fee crystallised. Both profit levels are kept, so a change of basis later
-- still has a high-water mark to measure from.
CREATE TABLE IF NOT EXISTS wm_settlements (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id        INTEGER NOT NULL,
  client_id      INTEGER NOT NULL,
  period_start   TEXT NOT NULL,
  period_end     TEXT NOT NULL,
  level_total    REAL NOT NULL,
  level_realised REAL NOT NULL,
  computed       REAL NOT NULL,         -- what the terms said, GST included
  amount         REAL NOT NULL,         -- what was billed
  gst            REAL NOT NULL DEFAULT 0,
  status         TEXT NOT NULL,
  paid_on        TEXT,
  note           TEXT,
  detail         TEXT NOT NULL,         -- JSON: the working, as it stood
  created_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_wm_settle_client ON wm_settlements(client_id, period_end, id);
CREATE TABLE IF NOT EXISTS wm_prices (
  user_id INTEGER NOT NULL,
  symbol  TEXT NOT NULL,
  price   REAL NOT NULL,
  as_of   TEXT NOT NULL,
  PRIMARY KEY (user_id, symbol)
);
"""

_local = threading.local()


def _conn():
    """The accounts connection for this thread, with this module's tables.
    Applied per connection object, because accounts.reset_for_tests swaps it."""
    conn = accounts._connect()
    if getattr(_local, "ready", None) is not conn:
        conn.executescript(SCHEMA)
        _local.ready = conn
    return conn


def _now_iso() -> str:
    return accounts._iso(accounts._now())


def today() -> dt.date:
    return dt.datetime.now(IST).date()


def _date(raw, field="Date", allow_future=False, default=None) -> str:
    s = str(raw or "").strip()[:10]
    if not s:
        if default is not None:
            return default
        raise ValueError(f"{field}: give a date.")
    try:
        d = dt.date.fromisoformat(s)
    except ValueError:
        raise ValueError(f"{field}: {s!r} is not a date (use YYYY-MM-DD).")
    if d.year < 1990:
        raise ValueError(f"{field}: that is too far back.")
    if not allow_future and d > today():
        raise ValueError(f"{field}: {d.isoformat()} is in the future.")
    return d.isoformat()


def _d(s) -> dt.date:
    return dt.date.fromisoformat(str(s)[:10])


def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _pos(raw, field, hi, allow_none=False):
    if raw in (None, "") and allow_none:
        return None
    v = _num(str(raw).replace(",", "").replace("₹", "").strip() if isinstance(raw, str) else raw)
    if v is None or v <= 0:
        raise ValueError(f"{field}: give a number above zero.")
    if v > hi:
        raise ValueError(f"{field}: {v:,.0f} is more than this desk accepts.")
    return v


def _text(raw, limit: int, multiline: bool = False) -> str:
    s = str(raw or "")
    if multiline:
        s = s.replace("\r\n", "\n").replace("\r", "\n")
        s = re.sub(r"[\u0000-\u0009\u000b-\u001f\u007f]", " ", s)
        s = re.sub(r"\n{3,}", "\n\n", s)
        return "\n".join(re.sub(r"[ \t]+", " ", l).strip() for l in s.split("\n")).strip()[:limit]
    s = _CTRL.sub(" ", s).strip()
    return re.sub(r"[ \t]+", " ", s)[:limit]


def _r(v, n=2):
    return None if v is None else round(float(v), n)


def _jl(raw, fb):
    try:
        v = json.loads(raw) if raw else fb
    except ValueError:
        return fb
    return v if isinstance(v, type(fb)) else fb


def clean_symbol(raw) -> str:
    s = str(raw or "").strip().upper().replace(".NS", "").replace(".BO", "")
    if not SYMBOL_RE.match(s):
        raise ValueError(f"{raw!r} is not a symbol (letters, digits, & . - only).")
    return s


# ---------------------------------------------------------------------------
# Terms
# ---------------------------------------------------------------------------

def clean_terms(raw, base=None) -> dict:
    """Fee terms, field by field. Anything not given keeps the base value."""
    t = dict(base or DEFAULT_TERMS)
    raw = raw if isinstance(raw, dict) else {}

    def rng(key, lo, hi, label):
        if key not in raw:
            return
        v = _num(raw.get(key))
        if v is None or v < lo or v > hi:
            raise ValueError(f"{label} must be between {lo:g} and {hi:g}.")
        t[key] = round(v, 4)

    rng("share_pct", 0, 50, "Profit share")
    rng("hurdle_pct", 0, 30, "Hurdle")
    rng("fixed_pct", 0, 5, "Fixed fee")
    rng("gst_pct", 0, 28, "GST")
    for key, allowed, label in (("hurdle_type", HURDLES, "Hurdle type"),
                                ("basis", BASES, "Basis"),
                                ("period", PERIODS, "Billing period")):
        if key in raw:
            v = str(raw.get(key) or "").strip().lower()
            if v not in allowed:
                raise ValueError(f"{label} must be one of: {', '.join(allowed)}.")
            t[key] = v
    if "hwm" in raw:
        t["hwm"] = bool(raw.get("hwm"))
    return t


def _pctx(v) -> str:
    return f"{v:g}%"


def terms_label(t: dict) -> str:
    parts = []
    if t.get("fixed_pct"):
        parts.append(f"{_pctx(t['fixed_pct'])} a year fixed")
    if t.get("share_pct"):
        s = f"{_pctx(t['share_pct'])} of {'booked ' if t.get('basis') == 'realised' else ''}profit"
        if t.get("hurdle_pct"):
            s += f" over {_pctx(t['hurdle_pct'])}" + (" (soft)" if t.get("hurdle_type") == "soft" else "")
        parts.append(s)
    if not parts:
        return "No fee"
    if t.get("share_pct") and t.get("hwm"):
        parts.append("high-water mark")
    parts.append(t.get("period", "quarterly"))
    if t.get("gst_pct"):
        parts.append(f"+{_pctx(t['gst_pct'])} GST")
    return " · ".join(parts)


# ---------------------------------------------------------------------------
# The desk
# ---------------------------------------------------------------------------

def _desk_dict(row) -> dict:
    reg = REGISTRATIONS.get(row["reg_kind"]) or REGISTRATIONS["none"]
    terms = clean_terms(_jl(row["terms"], {}))
    out = {"display_name": row["display_name"], "firm": row["firm"] or "",
           "reg_kind": row["reg_kind"], "registration": row["registration"] or "",
           "reg_label": reg["label"], "reg_short": reg["short"],
           "terms": terms, "terms_label": terms_label(terms),
           "created_at": row["created_at"], "notes": []}
    if row["reg_kind"] == "ria" and terms.get("share_pct"):
        out["notes"].append("SEBI's rules do not let a registered investment adviser charge "
                            "a share of profits. Check these default terms.")
    return out


def get_desk(user_id: int):
    row = _conn().execute("SELECT * FROM wm_desks WHERE user_id=?", (user_id,)).fetchone()
    return _desk_dict(row) if row else None


def has_desk(user_id: int) -> bool:
    return _conn().execute("SELECT 1 FROM wm_desks WHERE user_id=?", (user_id,)).fetchone() is not None


def save_desk(user_id: int, payload: dict) -> dict:
    payload = payload if isinstance(payload, dict) else {}
    conn = _conn()
    row = conn.execute("SELECT * FROM wm_desks WHERE user_id=?", (user_id,)).fetchone()
    cur = _desk_dict(row) if row else None

    name = _text(payload.get("display_name", cur and cur["display_name"]), 60)
    if len(name) < 2:
        raise ValueError("Your name: at least two characters.")
    firm = _text(payload.get("firm", cur and cur["firm"]), 80)
    kind = str(payload.get("reg_kind", cur and cur["reg_kind"]) or "none").strip().lower()
    if kind not in REGISTRATIONS:
        raise ValueError("Registration: choose one of the kinds offered.")
    reg = str(payload.get("registration", cur and cur["registration"]) or "").strip().upper().replace(" ", "")
    spec = REGISTRATIONS[kind]
    if spec["pattern"]:
        if not re.match(spec["pattern"], reg):
            raise ValueError(f"Registration number: {spec['hint']}.")
    else:
        reg = ""
    terms = clean_terms(payload.get("terms"), base=(cur or {}).get("terms"))
    now = _now_iso()
    with conn:
        if row:
            conn.execute("UPDATE wm_desks SET display_name=?, firm=?, reg_kind=?, registration=?, "
                         "terms=?, updated_at=? WHERE user_id=?",
                         (name, firm, kind, reg, json.dumps(terms), now, user_id))
        else:
            conn.execute("INSERT INTO wm_desks(user_id, display_name, firm, reg_kind, registration, "
                         "terms, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?)",
                         (user_id, name, firm, kind, reg, json.dumps(terms), now, now))
    return get_desk(user_id)


def delete_desk(user_id: int) -> dict:
    """Everything on this desk, gone. The client has a right to that, and so
    does the manager."""
    conn = _conn()
    counts = {}
    with conn:
        for table in ("wm_events", "wm_settlements", "wm_recs", "wm_prices", "wm_clients", "wm_desks"):
            counts[table] = conn.execute(f"DELETE FROM {table} WHERE user_id=?", (user_id,)).rowcount
    return counts


def _require_desk(user_id: int):
    if not has_desk(user_id):
        raise PermissionError("Set up your wealth desk first.")


# ---------------------------------------------------------------------------
# Clients
# ---------------------------------------------------------------------------

def _client_row(conn, user_id: int, client_id) -> dict:
    try:
        cid = int(client_id)
    except (TypeError, ValueError):
        raise LookupError("No such client.")
    row = conn.execute("SELECT * FROM wm_clients WHERE id=? AND user_id=?", (cid, user_id)).fetchone()
    if not row:
        raise LookupError("No such client.")
    return row


def _client_dict(row) -> dict:
    terms = clean_terms(_jl(row["terms"], {}))
    return {"id": row["id"], "code": row["code"], "name": row["name"],
            "email": row["email"] or "", "phone": row["phone"] or "", "city": row["city"] or "",
            "risk": row["risk"], "status": row["status"], "color": row["color"],
            "since": row["since"], "terms": terms, "terms_label": terms_label(terms),
            "tags": _jl(row["tags"], []), "notes": row["notes"] or "",
            "portal": bool(row["portal"]), "created_at": row["created_at"]}


def _next_code(conn, user_id: int) -> str:
    n = conn.execute("SELECT COUNT(*) AS n FROM wm_clients WHERE user_id=?", (user_id,)).fetchone()["n"]
    while True:
        n += 1
        code = f"C-{n:03d}"
        if not conn.execute("SELECT 1 FROM wm_clients WHERE user_id=? AND code=?", (user_id, code)).fetchone():
            return code


def _clean_client(payload: dict, cur=None, default_terms=None) -> dict:
    payload = payload if isinstance(payload, dict) else {}
    cur = cur or {}
    out = {}
    name = _text(payload.get("name", cur.get("name")), 80)
    if len(name) < 2:
        raise ValueError("Client name: at least two characters.")
    out["name"] = name
    code = str(payload.get("code", cur.get("code")) or "").strip()
    if code and not _CODE_RE.match(code):
        raise ValueError("Client code: up to 16 letters, digits, - _ or /.")
    out["code"] = code
    email = payload.get("email", cur.get("email"))
    email = str(email or "").strip()
    if email:
        email = accounts.valid_email(email)
        if not email:
            raise ValueError("Email: that does not look like an email address.")
    out["email"] = email
    phone = str(payload.get("phone", cur.get("phone")) or "").strip()
    if phone and not _PHONE_RE.match(phone):
        raise ValueError("Phone: digits, spaces, - and a leading + only.")
    out["phone"] = phone
    out["city"] = _text(payload.get("city", cur.get("city")), 40)
    for key, allowed, label, fb in (("risk", RISKS, "Risk profile", "moderate"),
                                    ("status", STATUSES, "Status", "active"),
                                    ("color", COLORS, "Colour", "gold")):
        v = str(payload.get(key, cur.get(key)) or fb).strip().lower()
        if v not in allowed:
            raise ValueError(f"{label} must be one of: {', '.join(allowed)}.")
        out[key] = v
    out["since"] = _date(payload.get("since", cur.get("since")), "Client since",
                         default=today().isoformat())
    tags = payload.get("tags", cur.get("tags")) or []
    if isinstance(tags, str):
        tags = [t for t in re.split(r"[,;]", tags)]
    if not isinstance(tags, list):
        raise ValueError("Tags: a list of short words.")
    clean = []
    for t in tags:
        t = _text(t, 24)
        if t and t.lower() not in [c.lower() for c in clean]:
            clean.append(t)
    out["tags"] = clean[:MAX_TAGS]
    out["notes"] = _text(payload.get("notes", cur.get("notes")), MAX_NOTE, multiline=True)
    out["portal"] = bool(payload.get("portal", cur.get("portal", False)))
    if out["portal"] and not out["email"]:
        raise ValueError("To show a client their portfolio, add the email address they sign in with.")
    base = cur.get("terms") or default_terms or DEFAULT_TERMS
    out["terms"] = clean_terms(payload.get("terms"), base=base) if "terms" in payload else clean_terms({}, base)
    return out


def create_client(user_id: int, payload: dict) -> dict:
    _require_desk(user_id)
    conn = _conn()
    n = conn.execute("SELECT COUNT(*) AS n FROM wm_clients WHERE user_id=?", (user_id,)).fetchone()["n"]
    if n >= MAX_CLIENTS:
        raise ValueError(f"A desk holds up to {MAX_CLIENTS} clients.")
    desk = get_desk(user_id)
    c = _clean_client(payload, default_terms=desk["terms"])
    code = c["code"] or _next_code(conn, user_id)
    if conn.execute("SELECT 1 FROM wm_clients WHERE user_id=? AND code=?", (user_id, code)).fetchone():
        raise ValueError(f"Another client already has the code {code}.")
    now = _now_iso()
    with conn:
        cur = conn.execute(
            "INSERT INTO wm_clients(user_id, code, name, email, phone, city, risk, status, color, since, "
            "terms, tags, notes, portal, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (user_id, code, c["name"], c["email"] or None, c["phone"] or None, c["city"] or None,
             c["risk"], c["status"], c["color"], c["since"], json.dumps(c["terms"]),
             json.dumps(c["tags"]), c["notes"] or None, int(c["portal"]), now, now))
    return _client_dict(_client_row(conn, user_id, cur.lastrowid))


def update_client(user_id: int, client_id, payload: dict) -> dict:
    conn = _conn()
    row = _client_row(conn, user_id, client_id)
    cur = _client_dict(row)
    c = _clean_client(payload, cur=cur)
    code = c["code"] or cur["code"]
    clash = conn.execute("SELECT id FROM wm_clients WHERE user_id=? AND code=? AND id<>?",
                         (user_id, code, row["id"])).fetchone()
    if clash:
        raise ValueError(f"Another client already has the code {code}.")
    with conn:
        conn.execute(
            "UPDATE wm_clients SET code=?, name=?, email=?, phone=?, city=?, risk=?, status=?, color=?, "
            "since=?, terms=?, tags=?, notes=?, portal=?, updated_at=? WHERE id=? AND user_id=?",
            (code, c["name"], c["email"] or None, c["phone"] or None, c["city"] or None, c["risk"],
             c["status"], c["color"], c["since"], json.dumps(c["terms"]), json.dumps(c["tags"]),
             c["notes"] or None, int(c["portal"]), _now_iso(), row["id"], user_id))
    return _client_dict(_client_row(conn, user_id, row["id"]))


def delete_client(user_id: int, client_id) -> dict:
    conn = _conn()
    row = _client_row(conn, user_id, client_id)
    with conn:
        e = conn.execute("DELETE FROM wm_events WHERE client_id=? AND user_id=?", (row["id"], user_id)).rowcount
        s = conn.execute("DELETE FROM wm_settlements WHERE client_id=? AND user_id=?", (row["id"], user_id)).rowcount
        conn.execute("DELETE FROM wm_clients WHERE id=? AND user_id=?", (row["id"], user_id))
    return {"deleted": row["id"], "events": e, "settlements": s}


# ---------------------------------------------------------------------------
# The ledger
# ---------------------------------------------------------------------------

def _event_dict(row) -> dict:
    return {k: row[k] for k in ("id", "client_id", "kind", "symbol", "qty", "price", "amount",
                                "charges", "rec_id", "rec_price", "on_date", "note")}


def _events_for(conn, user_id: int, client_id: int) -> list:
    rows = conn.execute("SELECT * FROM wm_events WHERE user_id=? AND client_id=? ORDER BY on_date, id",
                        (user_id, client_id)).fetchall()
    return [_event_dict(r) for r in rows]


def clean_event(raw: dict) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    kind = str(raw.get("kind") or raw.get("side") or "").strip().lower()
    if kind not in EVENT_KINDS:
        raise ValueError(f"Kind must be one of: {', '.join(EVENT_KINDS)}.")
    ev = {"kind": kind, "symbol": None, "qty": None, "price": None, "amount": None,
          "charges": 0.0, "rec_id": None, "rec_price": None,
          "on_date": _date(raw.get("on_date") or raw.get("date"), "Date"),
          "note": _text(raw.get("note"), 200) or None}
    if kind in ("buy", "sell"):
        ev["symbol"] = clean_symbol(raw.get("symbol"))
        ev["qty"] = _pos(raw.get("qty"), "Quantity", 1e9)
        ev["price"] = _pos(raw.get("price"), "Price", 1e7)
        ch = _num(raw.get("charges")) if raw.get("charges") not in (None, "") else 0.0
        if ch is None or ch < 0 or ch > ev["qty"] * ev["price"]:
            raise ValueError("Charges: a number from zero up to the trade's value.")
        ev["charges"] = ch
        if raw.get("rec_price") not in (None, ""):
            ev["rec_price"] = _pos(raw.get("rec_price"), "Recommended price", 1e7)
        if raw.get("rec_id") not in (None, ""):
            try:
                ev["rec_id"] = int(raw.get("rec_id"))
            except (TypeError, ValueError):
                raise ValueError("That recommendation does not exist.")
    elif kind == "split":
        ev["symbol"] = clean_symbol(raw.get("symbol"))
        f = _pos(raw.get("qty") or raw.get("factor"), "Split factor", 1000)
        if abs(f - 1) < 1e-9:
            raise ValueError("Split factor: 1 changes nothing. A 1:1 bonus is 2, a 1-for-5 consolidation 0.2.")
        ev["qty"] = f
    else:
        ev["amount"] = _pos(raw.get("amount"), "Amount", 1e11)
    return ev


class State:
    """The ledger walked to a date: lots, cash, capital and every running total."""

    __slots__ = ("lots", "realised", "buys", "sells", "charges", "dividends", "deposits",
                 "withdrawals", "topups", "cash", "capital", "cap_points", "flows", "errors",
                 "sold", "last_date", "topup_events")

    def __init__(self):
        self.lots = {}              # SYMBOL -> [[qty, cost_ps, date, rec_price, rec_id], ...]
        self.realised = {}          # SYMBOL -> rupees
        self.sold = {}              # SYMBOL -> {"qty", "proceeds", "cost"}
        self.buys = self.sells = self.charges = self.dividends = 0.0
        self.deposits = self.withdrawals = self.topups = 0.0
        self.cash = 0.0
        self.capital = 0.0
        self.cap_points = []        # [(date, capital from that date)]
        self.flows = []             # [(date, rupees)] the client's money: in < 0, out > 0
        self.errors = []
        self.last_date = None
        self.topup_events = []      # [(date, rupees)] shown in the ledger as automatic

    def qty(self, sym) -> float:
        return sum(l[0] for l in self.lots.get(sym, []))

    def open_cost(self) -> float:
        return sum(l[0] * l[1] for lots in self.lots.values() for l in lots)

    def _cap(self, d, delta):
        self.capital += delta
        if self.cap_points and self.cap_points[-1][0] == d:
            self.cap_points[-1] = (d, self.capital)
        else:
            self.cap_points.append((d, self.capital))


_EPS = 1e-6


def _sort_key(e):
    return (e["on_date"], _ORDER.get(e["kind"], 9), e.get("id") or 0)


def replay(events, until=None, strict=False) -> State:
    """Walk the ledger. `until` (ISO date) stops after that day. With `strict`,
    the first impossible event (selling what is not held, taking out cash that
    is not there) raises ValueError naming it; otherwise it is recorded in
    state.errors and the walk carries on, so a book never fails to open."""
    st = State()
    for e in sorted(events, key=_sort_key):
        d = e["on_date"]
        if until and d > until:
            break
        st.last_date = d
        k = e["kind"]
        sym = e.get("symbol")
        if k == "deposit":
            st.cash += e["amount"]
            st.deposits += e["amount"]
            st._cap(d, e["amount"])
            st.flows.append((d, -e["amount"]))
        elif k == "withdrawal":
            amt = e["amount"]
            if amt > st.cash + 0.005:
                msg = f"Only ₹{st.cash:,.2f} was in cash on {d}; a withdrawal of ₹{amt:,.2f} cannot come out of it."
                if strict:
                    raise ValueError(msg)
                st.errors.append(msg)
            st.cash -= amt
            st.withdrawals += amt
            st._cap(d, -amt)
            st.flows.append((d, amt))
        elif k == "dividend":
            st.cash += e["amount"]
            st.dividends += e["amount"]
        elif k == "split":
            lots = st.lots.get(sym) or []
            if not lots:
                msg = f"{sym}: nothing was held on {d} to split."
                if strict:
                    raise ValueError(msg)
                st.errors.append(msg)
            f = e["qty"]
            for l in lots:
                l[0] *= f
                l[1] /= f
                if l[3]:
                    l[3] /= f
        elif k == "buy":
            cost = e["qty"] * e["price"]
            need = cost + (e.get("charges") or 0)
            if need > st.cash + _EPS:
                top = need - st.cash
                st.topups += top
                st.cash += top
                st._cap(d, top)
                st.flows.append((d, -top))
                st.topup_events.append((d, top))
            st.cash -= need
            st.buys += cost
            st.charges += e.get("charges") or 0
            st.lots.setdefault(sym, []).append(
                [e["qty"], e["price"], d, e.get("rec_price"), e.get("rec_id")])
        elif k == "sell":
            held = st.qty(sym)
            q = e["qty"]
            if q > held + _EPS:
                msg = f"{sym}: {q:g} shares sold on {d}, but only {held:g} were held."
                if strict:
                    raise ValueError(msg)
                st.errors.append(msg)
                q = held
            proceeds = q * e["price"]
            left, cost_sold = q, 0.0
            lots = st.lots.get(sym, [])
            while left > _EPS and lots:
                lot = lots[0]
                take = min(lot[0], left)
                cost_sold += take * lot[1]
                lot[0] -= take
                left -= take
                if lot[0] <= _EPS:
                    lots.pop(0)
            if not lots:
                st.lots.pop(sym, None)
            st.realised[sym] = st.realised.get(sym, 0.0) + proceeds - cost_sold
            s = st.sold.setdefault(sym, {"qty": 0.0, "proceeds": 0.0, "cost": 0.0})
            s["qty"] += q
            s["proceeds"] += proceeds
            s["cost"] += cost_sold
            st.sells += proceeds
            st.charges += e.get("charges") or 0
            st.cash += proceeds - (e.get("charges") or 0)
    return st


def validate_ledger(events) -> None:
    replay(events, strict=True)


def capital_days(st: State, start: str, end: str) -> float:
    """∫ capital dt over [start, end), in rupee-days. Capital is a step that
    changes on the days money moves; it is never counted below zero."""
    s, e = _d(start), _d(end)
    if e <= s:
        return 0.0
    level, total, cursor = 0.0, 0.0, s
    for d, cap in st.cap_points:
        dd = _d(d)
        if dd <= s:
            level = cap
            continue
        if dd >= e:
            break
        total += max(level, 0.0) * (dd - cursor).days
        cursor, level = dd, cap
    total += max(level, 0.0) * (e - cursor).days
    return total


# ---------------------------------------------------------------------------
# Returns
# ---------------------------------------------------------------------------

def xirr(flows) -> float | None:
    """Annualised money-weighted return of dated flows, as a fraction.
    Money in is negative, money out (and today's value) positive."""
    fl = [(_d(d), float(a)) for d, a in flows if abs(a) > 1e-9]
    if len(fl) < 2 or not any(a < 0 for _, a in fl) or not any(a > 0 for _, a in fl):
        return None
    t0 = min(d for d, _ in fl)
    ts = [((d - t0).days / 365.0, a) for d, a in fl]

    def npv(r):
        return sum(a / (1 + r) ** t for t, a in ts)

    lo, hi = -0.9999, 10.0
    f_lo, f_hi = npv(lo), npv(hi)
    if f_lo * f_hi > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        f = npv(mid)
        if abs(f) < 1e-7:
            break
        if f_lo * f < 0:
            hi, f_hi = mid, f
        else:
            lo, f_lo = mid, f
    return (lo + hi) / 2


# ---------------------------------------------------------------------------
# Billing periods
# ---------------------------------------------------------------------------

_PERIOD_MONTHS = {"monthly": 1, "quarterly": 3, "half-yearly": 6, "yearly": 12}


def _month_end(y, m) -> dt.date:
    if m == 12:
        return dt.date(y, 12, 31)
    return dt.date(y, m + 1, 1) - dt.timedelta(days=1)


def next_due(period_start: str, period: str) -> str:
    """The first billing boundary after the period began. Quarters and halves
    end where India's financial year does (30 Jun, 30 Sep, 31 Dec, 31 Mar);
    a yearly agreement ends on 31 March."""
    s = _d(period_start)
    step = _PERIOD_MONTHS.get(period, 3)
    y, m = s.year, s.month
    while True:
        end = _month_end(y, m)
        # Months counted from April, so 3-, 6- and 12-month periods line up
        # with the financial year.
        fy_index = (m - 4) % 12 + 1
        if fy_index % step == 0 and end > s:
            return end.isoformat()
        m += 1
        if m > 12:
            m, y = 1, y + 1


def fy_of(d: dt.date) -> tuple:
    start = dt.date(d.year if d.month >= 4 else d.year - 1, 4, 1)
    return start, dt.date(start.year + 1, 3, 31)


def fy_label(d: dt.date) -> str:
    s, e = fy_of(d)
    return f"FY {s.year % 100:02d}-{e.year % 100:02d}"


# ---------------------------------------------------------------------------
# Prices
# ---------------------------------------------------------------------------

def price_at(quote: dict, on: str):
    """The close on or before a date, from a quote row's thirty-session history."""
    if not quote:
        return None
    dates, closes = quote.get("spark_dates") or [], quote.get("spark") or []
    best = None
    for d, c in zip(dates, closes):
        if d <= on and _num(c):
            best = float(c)
    return best


def _manual_prices(conn, user_id: int) -> dict:
    return {r["symbol"]: {"price": r["price"], "as_of": r["as_of"]}
            for r in conn.execute("SELECT * FROM wm_prices WHERE user_id=?", (user_id,))}


def set_price(user_id: int, symbol, price) -> dict:
    _require_desk(user_id)
    sym = clean_symbol(symbol)
    conn = _conn()
    with conn:
        if price in (None, "", 0, "0"):
            conn.execute("DELETE FROM wm_prices WHERE user_id=? AND symbol=?", (user_id, sym))
            return {"symbol": sym, "price": None}
        p = _pos(price, "Price", 1e7)
        conn.execute("INSERT INTO wm_prices(user_id, symbol, price, as_of) VALUES(?,?,?,?) "
                     "ON CONFLICT(user_id, symbol) DO UPDATE SET price=excluded.price, as_of=excluded.as_of",
                     (user_id, sym, p, today().isoformat()))
    return {"symbol": sym, "price": p}


# ---------------------------------------------------------------------------
# Writing the ledger
# ---------------------------------------------------------------------------

def _rec_row(conn, user_id, rec_id):
    if rec_id is None:
        return None
    r = conn.execute("SELECT * FROM wm_recs WHERE id=? AND user_id=?", (rec_id, user_id)).fetchone()
    if not r:
        raise ValueError("That recommendation does not exist.")
    return r


def add_events(user_id: int, client_id, raws: list) -> dict:
    """Add one or many events to a client's ledger. All or nothing: the whole
    ledger is replayed with them first, so a sale of shares that were never
    bought is refused with the reason, and nothing is half-written."""
    if not isinstance(raws, list) or not raws:
        raise ValueError("Send at least one entry.")
    if len(raws) > MAX_IMPORT:
        raise ValueError(f"At most {MAX_IMPORT} entries at a time.")
    conn = _conn()
    row = _client_row(conn, user_id, client_id)
    have = _events_for(conn, user_id, row["id"])
    if len(have) + len(raws) > MAX_EVENTS:
        raise ValueError(f"A client's ledger holds up to {MAX_EVENTS} entries.")
    new = []
    for i, raw in enumerate(raws):
        try:
            ev = clean_event(raw)
        except ValueError as e:
            raise ValueError(f"Entry {i + 1}: {e}" if len(raws) > 1 else str(e))
        rec = _rec_row(conn, user_id, ev["rec_id"])
        if rec is not None:
            if rec["symbol"] != ev["symbol"]:
                raise ValueError(f"That recommendation is for {rec['symbol']}, not {ev['symbol']}.")
            if ev["rec_price"] is None:
                ev["rec_price"] = rec["price"]
        new.append(ev)
    trial = have + [dict(ev, id=10 ** 12 + i) for i, ev in enumerate(new)]
    validate_ledger(trial)
    now = _now_iso()
    ids = []
    with conn:
        for ev in new:
            cur = conn.execute(
                "INSERT INTO wm_events(user_id, client_id, kind, symbol, qty, price, amount, charges, "
                "rec_id, rec_price, on_date, note, created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (user_id, row["id"], ev["kind"], ev["symbol"], ev["qty"], ev["price"], ev["amount"],
                 ev["charges"], ev["rec_id"], ev["rec_price"], ev["on_date"], ev["note"], now))
            ids.append(cur.lastrowid)
    settled = conn.execute("SELECT MAX(period_end) AS m FROM wm_settlements WHERE client_id=? AND user_id=?",
                           (row["id"], user_id)).fetchone()["m"]
    warn = None
    if settled and any(ev["on_date"] <= settled for ev in new):
        warn = (f"This is dated on or before {settled}, a period you have already settled. "
                "The settled amount stays as billed; the next period picks up the difference.")
    return {"ids": ids, "added": len(ids), "warning": warn}


def delete_event(user_id: int, client_id, event_id) -> dict:
    conn = _conn()
    row = _client_row(conn, user_id, client_id)
    try:
        eid = int(event_id)
    except (TypeError, ValueError):
        raise LookupError("No such entry.")
    have = _events_for(conn, user_id, row["id"])
    if not any(e["id"] == eid for e in have):
        raise LookupError("No such entry.")
    try:
        validate_ledger([e for e in have if e["id"] != eid])
    except ValueError as e:
        raise ValueError(f"Removing it would break a later entry — {e}")
    with conn:
        conn.execute("DELETE FROM wm_events WHERE id=? AND user_id=? AND client_id=?", (eid, user_id, row["id"]))
    return {"deleted": eid}


_HEAD = {"symbol": "symbol", "stock": "symbol", "scrip": "symbol", "ticker": "symbol", "instrument": "symbol",
         "qty": "qty", "quantity": "qty", "shares": "qty", "units": "qty",
         "price": "price", "buy price": "price", "avg": "price", "avg price": "price", "average price": "price",
         "avg. cost": "price", "buy": "price", "cost": "price", "rate": "price",
         "date": "date", "buy date": "date", "trade date": "date",
         "rec": "rec_price", "rec price": "rec_price", "recommended": "rec_price",
         "recommended price": "rec_price", "reco": "rec_price", "reco price": "rec_price",
         "side": "kind", "type": "kind", "action": "kind", "charges": "charges", "brokerage": "charges"}


def parse_import(text: str, default_date: str = None) -> list:
    """Rows pasted from a spreadsheet or a broker's holdings file, into buy
    events. Comma, tab or semicolon separated; a header row is recognised by
    its words, and without one the columns are symbol, qty, price, date, rec."""
    lines = [l for l in str(text or "").replace("\r", "").split("\n") if l.strip()]
    if not lines:
        raise ValueError("Paste at least one row: symbol, quantity, buy price.")
    if len(lines) > MAX_IMPORT + 1:
        raise ValueError(f"At most {MAX_IMPORT} rows at a time.")
    sep = "\t" if "\t" in lines[0] else (";" if lines[0].count(";") > lines[0].count(",") else ",")

    def cells(l):
        return [c.strip().strip('"').strip() for c in l.split(sep)]

    first = [c.lower() for c in cells(lines[0])]
    cols = None
    if any(c in _HEAD for c in first) and not any(re.match(r"^[\d.,₹]+$", c) for c in first[1:3] if c):
        cols = [_HEAD.get(c) for c in first]
        lines = lines[1:]
    else:
        cols = ["symbol", "qty", "price", "date", "rec_price"]
    if "symbol" not in cols or "qty" not in cols or "price" not in cols:
        raise ValueError("The header needs symbol, quantity and price columns.")
    out = []
    for n, l in enumerate(lines, start=1):
        vals = cells(l)
        rec = {}
        for c, v in zip(cols, vals):
            if c and v != "":
                rec[c] = v
        kind = str(rec.get("kind") or "buy").lower()
        kind = "sell" if kind.startswith("s") else "buy"
        raw = {"kind": kind, "symbol": rec.get("symbol"), "qty": rec.get("qty"),
               "price": rec.get("price"), "rec_price": rec.get("rec_price"),
               "charges": rec.get("charges"),
               "on_date": _loose_date(rec.get("date")) or default_date or today().isoformat()}
        try:
            out.append(clean_event(raw))
        except ValueError as e:
            raise ValueError(f"Row {n}: {e}")
    return out


def _loose_date(raw):
    s = str(raw or "").strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d-%b-%Y", "%d %b %Y", "%d-%b-%y", "%d/%m/%y"):
        try:
            return dt.datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return s


def import_rows(user_id: int, client_id, text: str, default_date=None) -> dict:
    evs = parse_import(text, default_date=_date(default_date, "Date", default=today().isoformat()))
    return add_events(user_id, client_id, evs)


# ---------------------------------------------------------------------------
# Recommendations
# ---------------------------------------------------------------------------

def _rec_dict(row) -> dict:
    return {k: row[k] for k in ("id", "symbol", "action", "price", "target", "stop", "on_date",
                                "horizon", "thesis", "status", "closed_on", "close_price", "created_at")}


def _clean_rec(payload: dict, cur=None) -> dict:
    payload = payload if isinstance(payload, dict) else {}
    cur = cur or {}
    out = {}
    out["symbol"] = clean_symbol(payload.get("symbol", cur.get("symbol")))
    a = str(payload.get("action", cur.get("action")) or "buy").strip().lower()
    if a not in ("buy", "sell"):
        raise ValueError("Action must be buy or sell.")
    out["action"] = a
    out["price"] = _pos(payload.get("price", cur.get("price")), "Recommended price", 1e7)
    out["target"] = _pos(payload.get("target", cur.get("target")), "Target", 1e7, allow_none=True)
    out["stop"] = _pos(payload.get("stop", cur.get("stop")), "Stop", 1e7, allow_none=True)
    if a == "buy":
        if out["target"] is not None and out["target"] <= out["price"]:
            raise ValueError("A buy's target should be above the recommended price.")
        if out["stop"] is not None and out["stop"] >= out["price"]:
            raise ValueError("A buy's stop should be below the recommended price.")
    else:
        if out["target"] is not None and out["target"] >= out["price"]:
            raise ValueError("A sell's target should be below the recommended price.")
        if out["stop"] is not None and out["stop"] <= out["price"]:
            raise ValueError("A sell's stop should be above the recommended price.")
    out["on_date"] = _date(payload.get("on_date", cur.get("on_date")), "Date", default=today().isoformat())
    out["horizon"] = _text(payload.get("horizon", cur.get("horizon")), 40) or None
    out["thesis"] = _text(payload.get("thesis", cur.get("thesis")), 600) or None
    st = str(payload.get("status", cur.get("status")) or "open").strip().lower()
    if st not in ("open", "closed"):
        raise ValueError("Status must be open or closed.")
    out["status"] = st
    if st == "closed":
        out["closed_on"] = _date(payload.get("closed_on", cur.get("closed_on")), "Closed on",
                                 default=today().isoformat())
        out["close_price"] = _pos(payload.get("close_price", cur.get("close_price")), "Closing price", 1e7)
    else:
        out["closed_on"], out["close_price"] = None, None
    return out


def create_rec(user_id: int, payload: dict) -> dict:
    _require_desk(user_id)
    conn = _conn()
    n = conn.execute("SELECT COUNT(*) AS n FROM wm_recs WHERE user_id=?", (user_id,)).fetchone()["n"]
    if n >= MAX_RECS:
        raise ValueError(f"A desk keeps up to {MAX_RECS} recommendations.")
    r = _clean_rec(payload)
    now = _now_iso()
    with conn:
        cur = conn.execute(
            "INSERT INTO wm_recs(user_id, symbol, action, price, target, stop, on_date, horizon, thesis, "
            "status, closed_on, close_price, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (user_id, r["symbol"], r["action"], r["price"], r["target"], r["stop"], r["on_date"],
             r["horizon"], r["thesis"], r["status"], r["closed_on"], r["close_price"], now, now))
    return _rec_dict(conn.execute("SELECT * FROM wm_recs WHERE id=?", (cur.lastrowid,)).fetchone())


def update_rec(user_id: int, rec_id, payload: dict) -> dict:
    conn = _conn()
    try:
        rid = int(rec_id)
    except (TypeError, ValueError):
        raise LookupError("No such recommendation.")
    row = conn.execute("SELECT * FROM wm_recs WHERE id=? AND user_id=?", (rid, user_id)).fetchone()
    if not row:
        raise LookupError("No such recommendation.")
    cur = _rec_dict(row)
    if "symbol" in (payload or {}) and clean_symbol(payload["symbol"]) != cur["symbol"]:
        used = conn.execute("SELECT 1 FROM wm_events WHERE rec_id=? AND user_id=?", (rid, user_id)).fetchone()
        if used:
            raise ValueError("Clients have been booked on this call, so its stock cannot change.")
    r = _clean_rec(payload, cur=cur)
    with conn:
        conn.execute(
            "UPDATE wm_recs SET symbol=?, action=?, price=?, target=?, stop=?, on_date=?, horizon=?, thesis=?, "
            "status=?, closed_on=?, close_price=?, updated_at=? WHERE id=? AND user_id=?",
            (r["symbol"], r["action"], r["price"], r["target"], r["stop"], r["on_date"], r["horizon"],
             r["thesis"], r["status"], r["closed_on"], r["close_price"], _now_iso(), rid, user_id))
    return _rec_dict(conn.execute("SELECT * FROM wm_recs WHERE id=?", (rid,)).fetchone())


def delete_rec(user_id: int, rec_id) -> dict:
    conn = _conn()
    try:
        rid = int(rec_id)
    except (TypeError, ValueError):
        raise LookupError("No such recommendation.")
    if not conn.execute("SELECT 1 FROM wm_recs WHERE id=? AND user_id=?", (rid, user_id)).fetchone():
        raise LookupError("No such recommendation.")
    with conn:
        # The fills stay — they happened — but no longer point at a call that
        # is gone. Their recommended price is kept on the fill itself.
        conn.execute("UPDATE wm_events SET rec_id=NULL WHERE rec_id=? AND user_id=?", (rid, user_id))
        conn.execute("DELETE FROM wm_recs WHERE id=? AND user_id=?", (rid, user_id))
    return {"deleted": rid}


def apply_rec(user_id: int, rec_id, fills: list) -> dict:
    """Book one call for many clients. Each fill: client_id and either qty,
    amount (rupees to put in at the fill price), or all=true for a sell.
    The fill price defaults to the recommended price."""
    conn = _conn()
    try:
        rid = int(rec_id)
    except (TypeError, ValueError):
        raise LookupError("No such recommendation.")
    rec = conn.execute("SELECT * FROM wm_recs WHERE id=? AND user_id=?", (rid, user_id)).fetchone()
    if not rec:
        raise LookupError("No such recommendation.")
    if not isinstance(fills, list) or not fills:
        raise ValueError("Choose at least one client.")
    plans = []
    for f in fills:
        f = f if isinstance(f, dict) else {}
        crow = _client_row(conn, user_id, f.get("client_id"))
        price = _pos(f.get("price") or rec["price"], "Fill price", 1e7)
        on = _date(f.get("on_date") or f.get("date"), "Date", default=today().isoformat())
        if f.get("all") and rec["action"] == "sell":
            st = replay(_events_for(conn, user_id, crow["id"]), until=on)
            qty = st.qty(rec["symbol"])
            if qty <= _EPS:
                raise ValueError(f"{crow['name']} holds no {rec['symbol']} to sell.")
        elif f.get("qty") not in (None, ""):
            qty = _pos(f.get("qty"), "Quantity", 1e9)
        elif f.get("amount") not in (None, ""):
            amt = _pos(f.get("amount"), "Amount", 1e11)
            qty = math.floor(amt / price)
            if qty < 1:
                raise ValueError(f"{crow['name']}: ₹{amt:,.0f} does not buy one share at ₹{price:,.2f}.")
        else:
            raise ValueError(f"{crow['name']}: give a quantity or an amount.")
        plans.append((crow["id"], {"kind": rec["action"], "symbol": rec["symbol"], "qty": qty,
                                   "price": price, "on_date": on, "rec_id": rid,
                                   "rec_price": rec["price"], "charges": f.get("charges")}))
    done = []
    # Validate every client first, so a call is booked for all of them or none.
    for cid, ev in plans:
        have = _events_for(conn, user_id, cid)
        validate_ledger(have + [dict(clean_event(ev), id=10 ** 12)])
    for cid, ev in plans:
        r = add_events(user_id, cid, [ev])
        done.append({"client_id": cid, "id": r["ids"][0], "qty": ev["qty"], "price": ev["price"]})
    return {"booked": done}


# ---------------------------------------------------------------------------
# Settlements
# ---------------------------------------------------------------------------

def _settle_dict(row) -> dict:
    out = {k: row[k] for k in ("id", "client_id", "period_start", "period_end", "level_total",
                               "level_realised", "computed", "amount", "gst", "status", "paid_on",
                               "note", "created_at")}
    out["detail"] = _jl(row["detail"], {})
    return out


def _settlements_for(conn, user_id, client_id) -> list:
    return [_settle_dict(r) for r in conn.execute(
        "SELECT * FROM wm_settlements WHERE user_id=? AND client_id=? ORDER BY period_end, id",
        (user_id, client_id))]


def settle(user_id: int, client_id, quotes: dict, as_of=None, amount=None, note="") -> dict:
    """Crystallise the fee for the period ending `as_of` (today by default).
    A past date is valued at that day's closes, so it must fall inside the
    thirty sessions the quotes carry. `amount` overrides what is billed —
    a waiver, a rounding, a negotiated figure — and the computed figure is
    kept beside it."""
    conn = _conn()
    row = _client_row(conn, user_id, client_id)
    client = _client_dict(row)
    on = _date(as_of, "Settle as of", default=today().isoformat())
    events = _events_for(conn, user_id, row["id"])
    settles = _settlements_for(conn, user_id, row["id"])
    if settles and on <= settles[-1]["period_end"]:
        raise ValueError(f"The last settlement ran to {settles[-1]['period_end']}. "
                         "Settle a later date, or undo that one first.")
    manual = _manual_prices(conn, user_id)
    priced = _price_map(events, quotes, manual, on)
    if priced.get("missing_history"):
        raise ValueError(f"Prices for {on} are not available for "
                         f"{', '.join(priced['missing_history'][:4])}. Settle as of a date in the last "
                         "six weeks, or today.")
    held = replay(events, until=on)
    unpriced = sorted(s for s in held.lots if held.qty(s) > _EPS and s not in priced["prices"])
    if unpriced and client["terms"]["basis"] == "total":
        raise ValueError(f"No price yet for {', '.join(unpriced[:4])}, so the profit cannot be measured. "
                         "Wait for the quotes to load, or set a price for anything that is not listed.")
    fee = client_fee(client, events, settles, priced["prices"], on)
    computed = fee["total"]
    billed = computed if amount in (None, "") else _num(amount)
    if billed is None or billed < 0:
        raise ValueError("Amount: a number, zero or more.")
    gst = fee["gst"] if amount in (None, "") else (
        round(billed - billed / (1 + client["terms"]["gst_pct"] / 100), 2) if client["terms"]["gst_pct"] else 0.0)
    status = "due" if billed > 0.005 else "nil"
    with conn:
        cur = conn.execute(
            "INSERT INTO wm_settlements(user_id, client_id, period_start, period_end, level_total, "
            "level_realised, computed, amount, gst, status, note, detail, created_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (user_id, row["id"], fee["period_start"], on, fee["level_total"], fee["level_realised"],
             computed, round(billed, 2), gst, status, _text(note, 200) or None,
             json.dumps({"steps": fee["steps"], "terms": client["terms"]}), _now_iso()))
    return _settle_dict(conn.execute("SELECT * FROM wm_settlements WHERE id=?", (cur.lastrowid,)).fetchone())


def record_past(user_id: int, client_id, payload: dict) -> dict:
    """A settlement made before this desk existed, so a client brought over
    from a spreadsheet is not billed again for periods already paid.

    The profit level that day cannot be priced from here — the quotes reach
    back six weeks — so the manager gives the portfolio's value that day (from
    the broker's statement), and the level is that value less the capital the
    ledger says was in by then. Or the level itself, when they know it."""
    payload = payload if isinstance(payload, dict) else {}
    conn = _conn()
    row = _client_row(conn, user_id, client_id)
    client = _client_dict(row)
    on = _date(payload.get("period_end") or payload.get("on_date"), "Settled up to")
    settles = _settlements_for(conn, user_id, row["id"])
    if settles and on <= settles[-1]["period_end"]:
        raise ValueError(f"The last settlement ran to {settles[-1]['period_end']}; this has to be later.")
    events = _events_for(conn, user_id, row["id"])
    st = replay(events, until=on)
    if payload.get("level") not in (None, ""):
        lvl = _num(str(payload.get("level")).replace(",", ""))
        if lvl is None:
            raise ValueError("Profit level: a number (it may be negative).")
        how = f"profit level entered as {_inr(lvl)}"
    else:
        val = _pos(payload.get("value"), "Portfolio value that day", 1e12)
        lvl = val - st.capital
        how = f"value {_inr(val)} less capital {_inr(st.capital)} on {_nice(on)}"
    booked = sum(st.realised.values()) + st.dividends - st.charges
    amt = _num(payload.get("amount")) if payload.get("amount") not in (None, "") else 0.0
    if amt is None or amt < 0:
        raise ValueError("Amount billed: a number, zero or more.")
    status = str(payload.get("status") or ("paid" if amt > 0.005 else "nil")).lower()
    if status not in ("due", "paid", "waived", "nil"):
        raise ValueError("Status must be due, paid or waived.")
    if amt <= 0.005:
        status = "nil"
    paid_on = _date(payload.get("paid_on"), "Paid on", default=on) if status == "paid" else None
    start = period_start_for(client, events, settles)
    detail = {"steps": [{"key": "past", "label": "Settled before Altaha", "formula": how, "value": _r(lvl)}],
              "terms": client["terms"], "recorded": True}
    with conn:
        cur = conn.execute(
            "INSERT INTO wm_settlements(user_id, client_id, period_start, period_end, level_total, "
            "level_realised, computed, amount, gst, status, paid_on, note, detail, created_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (user_id, row["id"], min(start, on), on, round(lvl, 2), round(booked, 2), round(amt, 2),
             round(amt, 2), 0.0, status, paid_on, _text(payload.get("note"), 200) or "Recorded from before Altaha",
             json.dumps(detail), _now_iso()))
    return _settle_dict(conn.execute("SELECT * FROM wm_settlements WHERE id=?", (cur.lastrowid,)).fetchone())


def mark_settlement(user_id: int, settlement_id, status: str, paid_on=None) -> dict:
    conn = _conn()
    try:
        sid = int(settlement_id)
    except (TypeError, ValueError):
        raise LookupError("No such settlement.")
    row = conn.execute("SELECT * FROM wm_settlements WHERE id=? AND user_id=?", (sid, user_id)).fetchone()
    if not row:
        raise LookupError("No such settlement.")
    status = str(status or "").strip().lower()
    if status not in ("due", "paid", "waived"):
        raise ValueError("Status must be due, paid or waived.")
    if row["status"] == "nil":
        raise ValueError("Nothing was billed for that period.")
    paid = _date(paid_on, "Paid on", default=today().isoformat()) if status == "paid" else None
    with conn:
        conn.execute("UPDATE wm_settlements SET status=?, paid_on=? WHERE id=?", (status, paid, sid))
    return _settle_dict(conn.execute("SELECT * FROM wm_settlements WHERE id=?", (sid,)).fetchone())


def undo_settlement(user_id: int, settlement_id) -> dict:
    """Only the latest one for that client: every later period was measured
    from it, so removing one from the middle would leave the chain lying."""
    conn = _conn()
    try:
        sid = int(settlement_id)
    except (TypeError, ValueError):
        raise LookupError("No such settlement.")
    row = conn.execute("SELECT * FROM wm_settlements WHERE id=? AND user_id=?", (sid, user_id)).fetchone()
    if not row:
        raise LookupError("No such settlement.")
    last = _settlements_for(conn, user_id, row["client_id"])[-1]
    if last["id"] != sid:
        raise ValueError("Only the most recent settlement can be undone; later periods were measured from it.")
    with conn:
        conn.execute("DELETE FROM wm_settlements WHERE id=?", (sid,))
    return {"deleted": sid}


# ---------------------------------------------------------------------------
# The fee
# ---------------------------------------------------------------------------

def _inr(v) -> str:
    v = float(v or 0)
    sign = "−" if v < -0.005 else ""
    v = abs(v)
    whole, frac = divmod(round(v, 2), 1)
    s = f"{int(whole)}"
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        head = re.sub(r"(\d)(?=(\d\d)+$)", r"\1,", head)
        s = f"{head},{tail}"
    paise = int(round(frac * 100))
    return f"{sign}₹{s}" + (f".{paise:02d}" if paise else "")


def _nice(d: str) -> str:
    x = _d(d)
    return f"{x.day} {x.strftime('%b %Y')}"


def fee_math(terms: dict, level: float, base: float, cap_days: float, days: int) -> dict:
    """The fee for one period, from four numbers. Pure, so the what-if slider
    and the sensitivity table use exactly the arithmetic the bill does."""
    gain = level - base
    fixed = terms["fixed_pct"] / 100 * cap_days / 365
    hurdle = terms["hurdle_pct"] / 100 * cap_days / 365
    after_fixed = gain - fixed
    if terms["hurdle_type"] == "soft":
        excess = after_fixed if after_fixed > hurdle else 0.0
    else:
        excess = after_fixed - hurdle
    excess = max(excess, 0.0)
    share = terms["share_pct"] / 100 * excess
    fee = fixed + share
    gst = fee * terms["gst_pct"] / 100
    return {"gain": gain, "fixed": fixed, "hurdle": hurdle, "excess": excess, "share": share,
            "fee": fee, "gst": gst, "total": fee + gst,
            "avg_capital": (cap_days / days) if days > 0 else 0.0}


def _levels(st: State, prices: dict) -> dict:
    mv = unpriced = 0.0
    for sym, lots in st.lots.items():
        q = sum(l[0] for l in lots)
        p = prices.get(sym)
        if p is None:
            c = sum(l[0] * l[1] for l in lots)
            mv += c
            unpriced += c
        else:
            mv += q * p
    open_cost = st.open_cost()
    realised = sum(st.realised.values())
    unreal = mv - open_cost
    return {"mv": mv, "unpriced": unpriced, "open_cost": open_cost, "realised": realised,
            "unrealised": unreal,
            "total": realised + unreal + st.dividends - st.charges,
            "booked": realised + st.dividends - st.charges}


def period_start_for(client: dict, events: list, settles: list) -> str:
    if settles:
        return settles[-1]["period_end"]
    first = min([e["on_date"] for e in events] + [client["since"]]) if events else client["since"]
    return first


def client_fee(client: dict, events: list, settles: list, prices: dict, on: str,
               st: State = None) -> dict:
    """The fee accrued from the last settlement to `on`, with its working."""
    terms = client["terms"]
    st = st or replay(events, until=on)
    lv = _levels(st, prices)
    key = "level_realised" if terms["basis"] == "realised" else "level_total"
    level = lv["booked"] if terms["basis"] == "realised" else lv["total"]
    start = period_start_for(client, events, settles)
    if start > on:
        start = on
    days = (_d(on) - _d(start)).days
    if terms["hwm"]:
        base = max([0.0] + [s[key] for s in settles])
        base_label = "High-water mark"
        base_formula = ("the highest profit level at any past settlement"
                        if settles else "no settlement yet, so it starts at zero")
    else:
        base = settles[-1][key] if settles else 0.0
        base_label = "Profit at the last settlement"
        base_formula = (f"as settled on {_nice(settles[-1]['period_end'])}" if settles
                        else "no settlement yet, so it starts at zero")
    cd = capital_days(st, start, on)
    m = fee_math(terms, level, base, cd, days)
    basis_word = "Booked profit" if terms["basis"] == "realised" else "Profit"
    if terms["basis"] == "realised":
        level_formula = (f"booked {_inr(lv['realised'])} + dividends {_inr(st.dividends)} "
                         f"− charges {_inr(st.charges)}")
    else:
        level_formula = (f"booked {_inr(lv['realised'])} + on paper {_inr(lv['unrealised'])} "
                         f"+ dividends {_inr(st.dividends)} − charges {_inr(st.charges)}")
    steps = [
        {"key": "period", "label": "Period", "formula": f"{_nice(start)} → {_nice(on)}",
         "value": days, "unit": "days"},
        {"key": "level", "label": f"{basis_word} since the start", "formula": level_formula,
         "value": _r(level)},
        {"key": "base", "label": base_label, "formula": base_formula, "value": _r(base)},
        {"key": "gain", "label": "New profit this period",
         "formula": f"{_inr(level)} − {_inr(base)}", "value": _r(m["gain"])},
    ]
    if terms["fixed_pct"]:
        steps.append({"key": "fixed", "label": "Fixed fee",
                      "formula": f"{_pctx(terms['fixed_pct'])} a year × {_inr(m['avg_capital'])} average capital "
                                 f"× {days}/365", "value": _r(m["fixed"])})
    if terms["share_pct"]:
        if terms["hurdle_pct"]:
            steps.append({"key": "hurdle", "label": f"Hurdle ({terms['hurdle_type']})",
                          "formula": f"{_pctx(terms['hurdle_pct'])} a year × {_inr(m['avg_capital'])} "
                                     f"average capital × {days}/365", "value": _r(m["hurdle"])})
        parts = [_inr(m["gain"])]
        if terms["fixed_pct"]:
            parts.append(f"− fixed {_inr(m['fixed'])}")
        if terms["hurdle_pct"] and terms["hurdle_type"] == "hard":
            parts.append(f"− hurdle {_inr(m['hurdle'])}")
        f_ex = " ".join(parts)
        if terms["hurdle_pct"] and terms["hurdle_type"] == "soft":
            f_ex += f", counted in full once it clears {_inr(m['hurdle'])}"
        f_ex += ", never below zero"
        steps.append({"key": "excess", "label": "Profit the share is taken from", "formula": f_ex,
                      "value": _r(m["excess"])})
        steps.append({"key": "share", "label": "Your share",
                      "formula": f"{_pctx(terms['share_pct'])} × {_inr(m['excess'])}", "value": _r(m["share"])})
    if terms["gst_pct"]:
        steps.append({"key": "gst", "label": "GST",
                      "formula": f"{_pctx(terms['gst_pct'])} × {_inr(m['fee'])}", "value": _r(m["gst"])})
    steps.append({"key": "total", "label": "Due for this period",
                  "formula": "fixed fee + share" + (" + GST" if terms["gst_pct"] else ""),
                  "value": _r(m["total"])})
    period = terms["period"]
    due = next_due(start, period)
    to_hwm = max(0.0, -m["gain"]) if terms["share_pct"] else 0.0
    return {"period_start": start, "period_end": on, "days": days, "basis": terms["basis"],
            "level": _r(level), "level_total": _r(lv["total"]), "level_realised": _r(lv["booked"]),
            "base": _r(base), "gain": _r(m["gain"]), "fixed": _r(m["fixed"]), "hurdle": _r(m["hurdle"]),
            "excess": _r(m["excess"]), "share": _r(m["share"]), "fee": _r(m["fee"]), "gst": _r(m["gst"]),
            "total": _r(m["total"]), "avg_capital": _r(m["avg_capital"]), "capital_days": _r(cd),
            "to_hwm": _r(to_hwm), "next_due": due, "overdue": due < on,
            "mv": _r(lv["mv"]), "steps": steps,
            "whatif": {"level": _r(level), "base": _r(base), "capital_days": _r(cd), "days": days,
                       "mv": _r(lv["mv"]) if terms["basis"] == "total" else 0.0}}


# ---------------------------------------------------------------------------
# The book
# ---------------------------------------------------------------------------

def _price_map(events, quotes: dict, manual: dict, on: str) -> dict:
    """{SYMBOL: price} for valuing a ledger on a date. Today: the live quote,
    or the hand-set price. A past date: that day's close from the quote's
    history; a hand-set price stands for every date."""
    syms = {e["symbol"] for e in events if e.get("symbol")}
    is_today = on >= today().isoformat()
    out, missing, source = {}, [], {}
    for s in syms:
        if s in manual:
            out[s] = manual[s]["price"]
            source[s] = "manual"
            continue
        q = (quotes or {}).get(s) or {}
        p = _num(q.get("ltp")) if is_today else price_at(q, on)
        if p:
            out[s] = p
            source[s] = (q.get("source") or "quote") if is_today else "close"
        elif not is_today:
            missing.append(s)
    if not is_today:
        # A name no longer held on that date needs no price.
        st = replay(events, until=on)
        missing = [s for s in missing if st.qty(s) > _EPS]
    return {"prices": out, "missing_history": sorted(missing) if not is_today else [], "source": source}


def symbols_needed(data: dict) -> list:
    """Every symbol a book needs a live quote for. Hand-priced ones are left
    out: asking Yahoo about a fund code on every load is a slow way to learn
    nothing."""
    manual = data.get("prices") or {}
    syms = set()
    for evs in data["events"].values():
        for e in evs:
            if e.get("symbol"):
                syms.add(e["symbol"])
    for r in data.get("recs") or []:
        syms.add(r["symbol"])
    return sorted(s for s in syms if s not in manual)


def load(user_id: int) -> dict:
    """Everything on one desk, as plain rows, for compute_book."""
    conn = _conn()
    desk = get_desk(user_id)
    if not desk:
        return None
    clients = [_client_dict(r) for r in conn.execute(
        "SELECT * FROM wm_clients WHERE user_id=? ORDER BY name COLLATE NOCASE", (user_id,))]
    events = {c["id"]: [] for c in clients}
    for r in conn.execute("SELECT * FROM wm_events WHERE user_id=? ORDER BY on_date, id", (user_id,)):
        events.setdefault(r["client_id"], []).append(_event_dict(r))
    settles = {c["id"]: [] for c in clients}
    for r in conn.execute("SELECT * FROM wm_settlements WHERE user_id=? ORDER BY period_end, id", (user_id,)):
        settles.setdefault(r["client_id"], []).append(_settle_dict(r))
    recs = [_rec_dict(r) for r in conn.execute(
        "SELECT * FROM wm_recs WHERE user_id=? ORDER BY on_date DESC, id DESC", (user_id,))]
    return {"desk": desk, "clients": clients, "events": events, "settlements": settles,
            "recs": recs, "prices": _manual_prices(conn, user_id)}


def _history(events, quotes, manual, dates) -> list:
    """Value on each of the last sessions: what was held that day at that
    day's close, plus cash. Hand-priced names count at their set price."""
    out = []
    for d in dates:
        st = replay(events, until=d)
        mv = 0.0
        for sym, lots in st.lots.items():
            q = sum(l[0] for l in lots)
            if sym in manual:
                p = manual[sym]["price"]
            else:
                p = price_at((quotes or {}).get(sym), d)
            if p is None:
                p = sum(l[0] * l[1] for l in lots) / q if q else 0
            mv += q * p
        out.append(round(mv + st.cash, 2))
    return out


def _ref_dates(quotes: dict, n: int = 30) -> list:
    ds = set()
    for q in (quotes or {}).values():
        for d in q.get("spark_dates") or []:
            ds.add(d)
    return sorted(ds)[-n:]


def _rec_live(rec: dict, quotes: dict) -> dict:
    q = (quotes or {}).get(rec["symbol"]) or {}
    ltp = _num(q.get("ltp"))
    sign = 1 if rec["action"] == "buy" else -1
    out = dict(rec)
    out.update({"name": q.get("name"), "sector": q.get("sector"), "ltp": ltp,
                "change_pct": q.get("change_pct"), "score": q.get("score"), "label": q.get("label")})
    ref = rec["close_price"] if rec["status"] == "closed" else ltp
    out["since_pct"] = _r(sign * 100 * (ref / rec["price"] - 1)) if ref else None
    out["to_target_pct"] = _r(sign * 100 * (rec["target"] / ltp - 1)) if (ltp and rec["target"]) else None
    out["to_stop_pct"] = _r(sign * 100 * (ltp / rec["stop"] - 1)) if (ltp and rec["stop"]) else None
    # Did a close since the call reach the target or the stop? Only the
    # sessions the quote carries can say; older calls are judged on the
    # current price alone.
    hit = None
    if rec["status"] == "open":
        for d, c in zip(q.get("spark_dates") or [], q.get("spark") or []):
            if d < rec["on_date"] or not _num(c):
                continue
            if rec["target"] and sign * (c - rec["target"]) >= 0:
                hit = {"kind": "target", "on": d, "price": c}
                break
            if rec["stop"] and sign * (rec["stop"] - c) >= 0:
                hit = {"kind": "stop", "on": d, "price": c}
                break
        if not hit and ltp:
            if rec["target"] and sign * (ltp - rec["target"]) >= 0:
                hit = {"kind": "target", "on": None, "price": ltp}
            elif rec["stop"] and sign * (rec["stop"] - ltp) >= 0:
                hit = {"kind": "stop", "on": None, "price": ltp}
    out["hit"] = hit
    if rec["status"] == "closed":
        out["state"] = "closed"
    elif hit:
        out["state"] = "target" if hit["kind"] == "target" else "stop"
    elif out["to_target_pct"] is not None and out["to_target_pct"] <= 3:
        out["state"] = "near"
    else:
        out["state"] = "open"
    # Where the price sits between the stop and the target, 0..1.
    lo = rec["stop"] if rec["action"] == "buy" else rec["target"]
    hi = rec["target"] if rec["action"] == "buy" else rec["stop"]
    if lo and hi and ref and hi > lo:
        out["track"] = {"lo": lo, "hi": hi, "at": max(0.0, min(1.0, (ref - lo) / (hi - lo))),
                        "rec": max(0.0, min(1.0, (rec["price"] - lo) / (hi - lo)))}
    else:
        out["track"] = None
    return out


def compute_client(client: dict, events: list, settles: list, quotes: dict, manual: dict,
                   recs_by_id: dict, on: str, dates: list) -> dict:
    st = replay(events)
    pm = _price_map(events, quotes, manual, on)
    prices = pm["prices"]
    lv = _levels(st, prices)
    value = lv["mv"] + st.cash
    holdings = []
    day = 0.0
    for sym, lots in st.lots.items():
        q = sum(l[0] for l in lots)
        if q <= _EPS:
            continue
        cost = sum(l[0] * l[1] for l in lots)
        rec_lots = [l for l in lots if l[3]]
        rq = sum(l[0] for l in rec_lots)
        rec_avg = (sum(l[0] * l[3] for l in rec_lots) / rq) if rq > _EPS else None
        qt = (quotes or {}).get(sym) or {}
        p = prices.get(sym)
        val = q * p if p is not None else cost
        avg = cost / q
        prev = _num(qt.get("prev_close")) if pm["source"].get(sym) != "manual" else None
        dch = q * (p - prev) if (p is not None and prev) else 0.0
        day += dch
        rec_ids = [l[4] for l in lots if l[4]]
        rec = recs_by_id.get(rec_ids[-1]) if rec_ids else None
        holdings.append({
            "symbol": sym, "name": qt.get("name"), "sector": qt.get("sector") or ("Hand-priced" if sym in manual else None),
            "score": qt.get("score"), "label": qt.get("label"), "tone": qt.get("tone"),
            "qty": _r(q, 4), "avg": _r(avg), "cost": _r(cost), "rec_price": _r(rec_avg),
            "edge_pct": _r(100 * (rec_avg - avg) / rec_avg) if rec_avg else None,
            "ltp": _r(p), "prev_close": _r(prev), "change_pct": qt.get("change_pct") if prev else None,
            "value": _r(val), "pnl": _r(val - cost) if p is not None else None,
            "pnl_pct": _r(100 * (val / cost - 1)) if (p is not None and cost) else None,
            "day_change": _r(dch), "since_rec_pct": _r(100 * (p / rec_avg - 1)) if (p and rec_avg) else None,
            "rec_id": rec["id"] if rec else None, "target": rec["target"] if rec else None,
            "stop": rec["stop"] if rec else None, "first_date": lots[0][2], "lots": len(lots),
            "priced": p is not None, "price_source": pm["source"].get(sym, "cost"),
            "spark": (qt.get("spark") or [])[-30:] if sym not in manual else [],
            "realised": _r(st.realised.get(sym, 0.0)),
        })
    for h in holdings:
        h["weight"] = _r(100 * h["value"] / value) if value > 0 else None
    holdings.sort(key=lambda h: -(h["value"] or 0))
    closed = [{"symbol": s, "qty": _r(v["qty"], 4), "proceeds": _r(v["proceeds"]), "cost": _r(v["cost"]),
               "pnl": _r(v["proceeds"] - v["cost"]),
               "pnl_pct": _r(100 * (v["proceeds"] / v["cost"] - 1)) if v["cost"] else None,
               "held": st.qty(s) > _EPS}
              for s, v in st.sold.items()]
    closed.sort(key=lambda r: -(r["pnl"] or 0))
    sectors = {}
    for h in holdings:
        k = h["sector"] or "Other"
        sectors[k] = sectors.get(k, 0.0) + (h["value"] or 0)
    if st.cash > 0.5:
        sectors["Cash"] = st.cash
    sec = [{"sector": k, "value": _r(v), "weight": _r(100 * v / value) if value > 0 else None}
           for k, v in sorted(sectors.items(), key=lambda kv: -kv[1])]

    start = min([e["on_date"] for e in events] + [client["since"]]) if events else client["since"]
    days_all = max((_d(on) - _d(start)).days, 0)
    cd_all = capital_days(st, start, on)
    avg_cap = cd_all / days_all if days_all > 0 else st.capital
    profit = lv["total"]
    xr = xirr(st.flows + [(on, value)]) if st.flows and days_all >= 90 else None

    fee = client_fee(client, events, settles, prices, on, st=replay(events, until=on))
    alerts = []
    nm = client["name"]
    if client["status"] != "closed":
        if fee["overdue"] and fee["total"] and fee["total"] > 0.5:
            alerts.append({"kind": "overdue", "tone": "gold", "client_id": client["id"], "rank": 1,
                           "text": f"{nm}'s {client['terms']['period']} period ended {_nice(fee['next_due'])} — "
                                   f"{_inr(fee['total'])} to settle."})
        if (client["terms"]["share_pct"] and events and fee["to_hwm"]
                and fee["to_hwm"] > max(500.0, 0.002 * max(st.capital, 0.0))):
            alerts.append({"kind": "below_hwm", "tone": "rose", "client_id": client["id"], "rank": 4,
                           "text": f"{nm} is {_inr(fee['to_hwm'])} below the "
                                   f"{'high-water mark' if client['terms']['hwm'] else 'last settlement'} — "
                                   "no profit share until it is made back."})
        for h in holdings:
            if h["weight"] and h["weight"] > 30 and len(holdings) > 1:
                alerts.append({"kind": "concentration", "tone": "violet", "client_id": client["id"], "rank": 5,
                               "text": f"{h['symbol']} is {h['weight']:.0f}% of {nm}'s portfolio."})
        unp = [h["symbol"] for h in holdings if not h["priced"]]
        if unp:
            alerts.append({"kind": "unpriced", "tone": "slate", "client_id": client["id"], "rank": 6,
                           "text": f"No price for {', '.join(unp[:3])} in {nm}'s book — valued at cost. "
                                   "Set a price if it is not listed."})
        if value > 0 and st.cash / value > 0.25 and st.cash > 10000:
            alerts.append({"kind": "cash", "tone": "blue", "client_id": client["id"], "rank": 7,
                           "text": f"{_inr(st.cash)} of {nm}'s money is idle in cash ({100 * st.cash / value:.0f}%)."})
    for s in settles:
        if s["status"] == "due" and s["amount"] > 0.5 and (_d(on) - _d(s["period_end"])).days > 15:
            alerts.append({"kind": "unpaid", "tone": "rose", "client_id": client["id"], "rank": 2,
                           "text": f"{_inr(s['amount'])} billed to {nm} for the period to "
                                   f"{_nice(s['period_end'])} is still unpaid.", "settlement_id": s["id"]})
    hist = _history(events, quotes, manual, dates) if dates and events else []
    ledger = [dict(e) for e in sorted(events, key=_sort_key, reverse=True)]
    for d, amt in st.topup_events:
        ledger.append({"id": None, "kind": "topup", "amount": _r(amt), "on_date": d, "auto": True,
                       "note": "Added automatically: the buy cost more than the cash on hand"})
    ledger.sort(key=lambda e: (e["on_date"], 0 if e.get("auto") else 1, e.get("id") or 0), reverse=True)
    for e in ledger:
        if e.get("rec_id") and e["rec_id"] in recs_by_id:
            e["rec_action"] = recs_by_id[e["rec_id"]]["action"]
    out = dict(client)
    out.update({
        "mode": "capital" if st.deposits > 0 else "holdings",
        "value": _r(value), "mv": _r(lv["mv"]), "cash": _r(st.cash), "capital": _r(st.capital),
        "deposits": _r(st.deposits), "withdrawals": _r(st.withdrawals), "topups": _r(st.topups),
        "profit": _r(profit), "booked": _r(lv["booked"]), "realised": _r(lv["realised"]),
        "unrealised": _r(lv["unrealised"]), "dividends": _r(st.dividends), "charges": _r(st.charges),
        "avg_capital": _r(avg_cap),
        "profit_pct": _r(100 * profit / avg_cap) if avg_cap and avg_cap > 1 else None,
        "xirr": _r(100 * xr) if xr is not None else None, "days": days_all,
        "day_change": _r(day), "day_pct": _r(100 * day / (value - day)) if value - day > 1 else None,
        "holdings": holdings, "closed": closed, "sectors": sec, "events": ledger,
        "settlements": list(reversed(settles)), "fee": fee, "alerts": alerts,
        "spark": {"dates": dates if hist else [], "values": hist},
        "errors": st.errors, "unpriced": _r(lv["unpriced"]),
    })
    return out


def compute_book(data: dict, quotes: dict, pending=None, on: str = None, market_open=False,
                 demo: bool = False) -> dict:
    """The whole desk, valued. Pure: rows and quotes in, a payload out."""
    on = on or today().isoformat()
    manual = data.get("prices") or {}
    recs_by_id = {r["id"]: r for r in data.get("recs") or []}
    dates = _ref_dates(quotes)
    clients = []
    for c in data["clients"]:
        clients.append(compute_client(c, data["events"].get(c["id"], []), data["settlements"].get(c["id"], []),
                                      quotes, manual, recs_by_id, on, dates))
    live = [c for c in clients if c["status"] != "closed"]

    def tot(k):
        return sum((c.get(k) or 0) for c in live)

    aum, day = tot("value"), tot("day_change")
    avg_cap = tot("avg_capital")
    totals = {"aum": _r(aum), "capital": _r(tot("capital")), "profit": _r(tot("profit")),
              "booked": _r(tot("booked")), "unrealised": _r(tot("unrealised")), "cash": _r(tot("cash")),
              "day_change": _r(day), "day_pct": _r(100 * day / (aum - day)) if aum - day > 1 else None,
              "profit_pct": _r(100 * tot("profit") / avg_cap) if avg_cap > 1 else None,
              "clients": len(clients), "active": sum(1 for c in clients if c["status"] == "active"),
              "paused": sum(1 for c in clients if c["status"] == "paused"),
              "closed": sum(1 for c in clients if c["status"] == "closed"),
              "accrued": _r(sum(c["fee"]["total"] or 0 for c in live)),
              "accrued_share": _r(sum(c["fee"]["share"] or 0 for c in live)),
              "accrued_fixed": _r(sum(c["fee"]["fixed"] or 0 for c in live)),
              "in_profit": sum(1 for c in live if (c["profit"] or 0) > 0),
              "below_hwm": sum(1 for c in live if (c["fee"]["to_hwm"] or 0) > 0.5)}
    # The book's own thirty sessions.
    if dates:
        vals = []
        for i in range(len(dates)):
            s = 0.0
            for c in live:
                v = c["spark"]["values"]
                if v and i < len(v) and v[i] is not None:
                    s += v[i]
            vals.append(round(s, 2))
        spark = {"dates": dates, "values": vals}
    else:
        spark = {"dates": [], "values": []}

    # What the book holds, across clients.
    exp = {}
    for c in live:
        for h in c["holdings"]:
            e = exp.setdefault(h["symbol"], {"symbol": h["symbol"], "name": h["name"], "sector": h["sector"],
                                             "value": 0.0, "qty": 0.0, "clients": [], "change_pct": h["change_pct"],
                                             "score": h["score"], "pnl": 0.0, "cost": 0.0})
            e["value"] += h["value"] or 0
            e["qty"] += h["qty"] or 0
            e["cost"] += h["cost"] or 0
            e["pnl"] += h["pnl"] or 0
            e["clients"].append({"id": c["id"], "name": c["name"], "color": c["color"]})
    exposures = sorted(exp.values(), key=lambda e: -e["value"])
    for e in exposures:
        e["weight"] = _r(100 * e["value"] / aum) if aum > 0 else None
        e["value"], e["qty"], e["pnl"], e["cost"] = _r(e["value"]), _r(e["qty"], 4), _r(e["pnl"]), _r(e["cost"])
        e["pnl_pct"] = _r(100 * e["pnl"] / e["cost"]) if e["cost"] else None
    sectors = {}
    for c in live:
        for s in c["sectors"]:
            sectors[s["sector"]] = sectors.get(s["sector"], 0.0) + (s["value"] or 0)
    sec = [{"sector": k, "value": _r(v), "weight": _r(100 * v / aum) if aum > 0 else None}
           for k, v in sorted(sectors.items(), key=lambda kv: -kv[1])]

    # Commission.
    today_d = _d(on)
    fy_s, fy_e = fy_of(today_d)
    all_settles = []
    names = {c["id"]: c for c in clients}
    for cid, ss in data["settlements"].items():
        for s in ss:
            row = dict(s)
            row.pop("detail", None)
            row["client_name"] = names.get(cid, {}).get("name", "")
            row["client_color"] = names.get(cid, {}).get("color", "gold")
            all_settles.append(row)
    all_settles.sort(key=lambda s: (s["period_end"], s["id"]), reverse=True)
    billed_fy = sum(s["amount"] for s in all_settles if s["status"] in ("due", "paid")
                    and fy_s <= _d(s["period_end"]) <= fy_e)
    paid_fy = sum(s["amount"] for s in all_settles if s["status"] == "paid" and s["paid_on"]
                  and fy_s <= _d(s["paid_on"]) <= fy_e)
    due = sum(s["amount"] for s in all_settles if s["status"] == "due")
    months = []
    y, m = today_d.year, today_d.month
    for _ in range(12):
        months.append(f"{y:04d}-{m:02d}")
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    months.reverse()
    mrows = []
    for mk in months:
        mrows.append({"month": mk,
                      "billed": _r(sum(s["amount"] for s in all_settles if s["status"] in ("due", "paid")
                                       and s["period_end"][:7] == mk)),
                      "received": _r(sum(s["amount"] for s in all_settles if s["status"] == "paid"
                                         and (s["paid_on"] or "")[:7] == mk))})
    # If every price moved by m: the accrued fee across the book.
    sens = []
    for mv_pct in (-20, -10, -5, 0, 5, 10, 20):
        total = 0.0
        for c in live:
            w = c["fee"]["whatif"]
            mm = fee_math(c["terms"], w["level"] + w["mv"] * mv_pct / 100, w["base"],
                          w["capital_days"], w["days"])
            total += mm["total"]
        sens.append({"move": mv_pct, "fee": _r(total)})
    totals.update({"due": _r(due), "billed_fy": _r(billed_fy), "collected_fy": _r(paid_fy),
                   "fy_label": fy_label(today_d)})

    # Recommendations, live, with who acted on each.
    recs = []
    fills = {}
    for c in clients:
        for e in data["events"].get(c["id"], []):
            if e.get("rec_id"):
                fills.setdefault(e["rec_id"], []).append({
                    "client_id": c["id"], "name": c["name"], "color": c["color"], "kind": e["kind"],
                    "qty": e["qty"], "price": e["price"], "on_date": e["on_date"], "event_id": e["id"],
                    "slip_pct": _r(100 * (e["price"] / e["rec_price"] - 1)) if e.get("rec_price") else None})
    for r in data.get("recs") or []:
        lr = _rec_live(r, quotes)
        fl = fills.get(r["id"], [])
        lr["fills"] = fl
        q = sum(f["qty"] for f in fl if f["kind"] == r["action"])
        lr["filled_qty"] = _r(q, 4)
        lr["filled_value"] = _r(sum(f["qty"] * f["price"] for f in fl if f["kind"] == r["action"]))
        lr["avg_fill"] = _r(lr["filled_value"] / q) if q else None
        lr["holders"] = [{"id": c["id"], "name": c["name"], "color": c["color"]} for c in live
                         if any(h["symbol"] == r["symbol"] for h in c["holdings"])]
        recs.append(lr)
    judged = [r for r in recs if r["since_pct"] is not None]
    rec_stats = {"open": sum(1 for r in recs if r["status"] == "open"),
                 "closed": sum(1 for r in recs if r["status"] == "closed"),
                 "judged": len(judged),
                 "working": sum(1 for r in judged if r["since_pct"] > 0),
                 "targets": sum(1 for r in recs if r["state"] == "target"),
                 "stops": sum(1 for r in recs if r["state"] == "stop"),
                 "avg_pct": _r(sum(r["since_pct"] for r in judged) / len(judged)) if judged else None,
                 "best": max(judged, key=lambda r: r["since_pct"])["symbol"] if judged else None,
                 "worst": min(judged, key=lambda r: r["since_pct"])["symbol"] if judged else None}
    alerts = []
    for r in recs:
        if r["state"] in ("target", "stop") and r["status"] == "open":
            n = len(r["holders"])
            word = "target" if r["state"] == "target" else "stop"
            lvl = r["target"] if word == "target" else r["stop"]
            alerts.append({"kind": word, "tone": "green" if word == "target" else "rose", "rec_id": r["id"],
                           "rank": 0 if word == "stop" else 3,
                           "text": f"{r['symbol']} {'reached your target' if word == 'target' else 'hit your stop'} "
                                   f"of {_inr(lvl)}" + ((" — 1 client holds it." if n == 1 else f" — {n} clients hold it.")
                                                        if n else ".")})
    for c in clients:
        alerts.extend(c["alerts"])
    alerts.sort(key=lambda a: a.get("rank", 9))

    return {
        "desk": data["desk"], "as_of": on, "market_open": bool(market_open), "pending": list(pending or []),
        "demo": demo, "totals": totals, "spark": spark, "clients": clients,
        "exposures": exposures[:40], "sectors": sec,
        "commission": {"months": mrows, "sensitivity": sens, "settlements": all_settles[:200]},
        "recs": recs, "rec_stats": rec_stats, "alerts": alerts[:40],
        "prices": [{"symbol": s, "price": v["price"], "as_of": v["as_of"]} for s, v in sorted(manual.items())],
        "limits": {"clients": MAX_CLIENTS, "events": MAX_EVENTS, "recs": MAX_RECS, "import": MAX_IMPORT},
        "vocab": {"colors": list(COLORS), "risks": list(RISKS), "statuses": list(STATUSES),
                  "periods": list(PERIODS), "registrations": [{"id": k, "label": v["label"], "hint": v["hint"]}
                                                             for k, v in REGISTRATIONS.items()]},
        "disclaimer": DISCLAIMER, "fee_note": FEE_NOTE,
    }


# ---------------------------------------------------------------------------
# A client's own view
# ---------------------------------------------------------------------------

_PRIVATE = ("notes", "tags", "portal", "alerts", "errors")


def shared_with(email: str) -> list:
    """Portfolios a manager has chosen to show the person signed in as `email`."""
    addr = accounts.valid_email(email)
    if not addr:
        return []
    conn = _conn()
    rows = conn.execute("SELECT * FROM wm_clients WHERE email=? AND portal=1 AND status<>'closed'",
                        (addr,)).fetchall()
    out = []
    for r in rows:
        desk = get_desk(r["user_id"])
        if desk:
            out.append({"user_id": r["user_id"], "client": _client_dict(r), "desk": desk})
    return out


def client_view(entry: dict, quotes: dict, on: str = None) -> dict:
    """One shared portfolio, valued, without the manager's private notes."""
    on = on or today().isoformat()
    conn = _conn()
    uid, c = entry["user_id"], entry["client"]
    events = _events_for(conn, uid, c["id"])
    settles = _settlements_for(conn, uid, c["id"])
    manual = _manual_prices(conn, uid)
    recs = {r["id"]: _rec_dict(r) for r in conn.execute("SELECT * FROM wm_recs WHERE user_id=?", (uid,))}
    view = compute_client(c, events, settles, quotes, manual, recs, on, _ref_dates(quotes))
    for k in _PRIVATE:
        view.pop(k, None)
    for s in view["settlements"]:
        s.pop("note", None)
    # A note on a trade is the manager's own working, not the client's statement.
    for e in view["events"]:
        if not e.get("auto"):
            e.pop("note", None)
    d = entry["desk"]
    return {"desk": {k: d[k] for k in ("display_name", "firm", "reg_label", "reg_short", "registration")},
            "client": view}


def shared_symbols(entries: list) -> list:
    conn = _conn()
    syms = set()
    for en in entries:
        manual = _manual_prices(conn, en["user_id"])
        for e in _events_for(conn, en["user_id"], en["client"]["id"]):
            if e.get("symbol") and e["symbol"] not in manual:
                syms.add(e["symbol"])
    return sorted(syms)


# ---------------------------------------------------------------------------
# The sample desk
# ---------------------------------------------------------------------------

# Rough levels, used only when a live quote is not to hand, so the sample
# book never opens on a wall of dashes.
_SAMPLE_PRICE = {"RELIANCE": 1450, "HDFCBANK": 1950, "ICICIBANK": 1400, "TCS": 3300, "INFY": 1550,
                 "LT": 3700, "BHARTIARTL": 1950, "ITC": 420, "TITAN": 3500, "BAJFINANCE": 950,
                 "SUNPHARMA": 1700, "POLYCAB": 7000, "TRENT": 5000, "HAL": 4600, "SBIN": 850}

_SAMPLE_CLIENTS = [
    # name, code, city, risk, colour, months ago, terms, capital, tags
    ("Ayesha Kapoor", "AK-01", "Mumbai", "aggressive", "rose", 20,
     {"share_pct": 20, "hurdle_pct": 8, "hurdle_type": "hard", "hwm": True, "period": "quarterly"},
     2500000, ["HNI", "Growth"]),
    ("Rohan & Meera Shah", "RS-02", "Ahmedabad", "moderate", "blue", 14,
     {"share_pct": 15, "fixed_pct": 1.0, "hurdle_pct": 0, "hwm": True, "period": "half-yearly", "gst_pct": 18},
     1800000, ["Family"]),
    ("Dr. Vikram Iyer", "VI-03", "Chennai", "conservative", "green", 9,
     {"share_pct": 10, "hurdle_pct": 6, "hurdle_type": "soft", "hwm": True, "period": "quarterly"},
     1200000, ["Retirement"]),
    ("Sana Qureshi", "SQ-04", "Hyderabad", "aggressive", "violet", 5,
     {"share_pct": 25, "hurdle_pct": 0, "hwm": True, "basis": "realised", "period": "quarterly"},
     600000, ["New"]),
    ("Arjun Mehta", "AM-05", "Pune", "moderate", "gold", 11,
     {"share_pct": 20, "hurdle_pct": 10, "hurdle_type": "hard", "hwm": True, "period": "yearly"},
     900000, ["Salaried"]),
]

# client index, symbol, months ago, share of capital, buy at x·ltp, rec at x·ltp
_SAMPLE_BUYS = [
    (0, "RELIANCE", 19, .20, .86, .88), (0, "HAL", 16, .18, .70, .72), (0, "TRENT", 12, .16, 1.08, 1.05),
    (0, "BHARTIARTL", 10, .18, .80, .82), (0, "POLYCAB", 6, .14, .90, .92),
    (1, "HDFCBANK", 13, .25, .88, .90), (1, "ITC", 12, .15, 1.02, 1.00), (1, "TCS", 9, .20, 1.10, 1.08),
    (1, "LT", 7, .20, .90, .91),
    (2, "ICICIBANK", 8, .28, .92, .93), (2, "SUNPHARMA", 7, .25, .95, .95), (2, "ITC", 6, .20, 1.00, 1.01),
    (2, "HDFCBANK", 5, .18, .97, .97),
    (3, "TRENT", 4, .30, 1.15, 1.12), (3, "BAJFINANCE", 3, .30, .93, .94), (3, "HAL", 2, .28, .96, .95),
    (4, "INFY", 10, .25, 1.06, 1.05), (4, "TITAN", 9, .25, .90, .92), (4, "SBIN", 8, .25, .88, .90),
]


def _months_ago(n: int, ref: dt.date) -> str:
    y, m = ref.year, ref.month - n
    while m <= 0:
        m += 12
        y -= 1
    day = min(ref.day, 28)
    d = dt.date(y, m, day)
    while d.weekday() >= 5:
        d -= dt.timedelta(days=1)
    return d.isoformat()


def sample_symbols() -> list:
    return sorted({b[1] for b in _SAMPLE_BUYS})


def sample_data(quotes: dict, on: str = None) -> dict:
    """An invented desk with five clients, built around today's prices so its
    gains and losses look like a real book's. Nothing here is stored."""
    ref = _d(on) if on else today()

    def px(sym):
        q = (quotes or {}).get(sym) or {}
        return _num(q.get("ltp")) or _SAMPLE_PRICE.get(sym, 1000)

    desk = {"display_name": "Nadia Rahman", "firm": "Rahman Wealth (sample desk)", "reg_kind": "pms",
            "registration": "INP000000000", "reg_label": REGISTRATIONS["pms"]["label"],
            "reg_short": "SEBI PMS", "terms": clean_terms({}), "terms_label": terms_label(clean_terms({})),
            "created_at": ref.isoformat(), "notes": []}
    clients, events, settles = [], {}, {}
    eid = 1
    for i, (name, code, city, risk, color, ago, terms, cap, tags) in enumerate(_SAMPLE_CLIENTS):
        cid = i + 1
        t = clean_terms(terms)
        since = _months_ago(ago, ref)
        clients.append({"id": cid, "code": code, "name": name, "email": "", "phone": "", "city": city,
                        "risk": risk, "status": "active", "color": color, "since": since, "terms": t,
                        "terms_label": terms_label(t), "tags": tags, "portal": False,
                        "notes": "Sample client. Sign in and set up your desk to add your own.",
                        "created_at": since})
        events[cid] = [{"id": eid, "client_id": cid, "kind": "deposit", "symbol": None, "qty": None,
                        "price": None, "amount": float(cap), "charges": 0.0, "rec_id": None,
                        "rec_price": None, "on_date": since, "note": "Opening capital"}]
        eid += 1
        settles[cid] = []
    recs = []
    rid = 1
    rec_for = {}
    for ci, sym, ago, frac, buy_x, rec_x in _SAMPLE_BUYS:
        p = px(sym)
        on_d = _months_ago(ago, ref)
        if sym not in rec_for:
            rp = round(p * rec_x, 1)
            recs.append({"id": rid, "symbol": sym, "action": "buy", "price": rp,
                         "target": round(rp * 1.28, 1), "stop": round(rp * 0.88, 1), "on_date": on_d,
                         "horizon": "12–18 months", "thesis": "Sample call.", "status": "open",
                         "closed_on": None, "close_price": None, "created_at": on_d})
            rec_for[sym] = recs[-1]
            rid += 1
        rec = rec_for[sym]
        bp = round(rec["price"] * buy_x / rec_x, 2)
        cap = _SAMPLE_CLIENTS[ci][7]
        qty = max(1, math.floor(cap * frac / bp))
        events[ci + 1].append({"id": eid, "client_id": ci + 1, "kind": "buy", "symbol": sym, "qty": float(qty),
                               "price": bp, "amount": None, "charges": round(qty * bp * 0.0012, 2),
                               "rec_id": rec["id"], "rec_price": rec["price"], "on_date": on_d, "note": None})
        eid += 1
    # A booked profit and a dividend, so the ledger shows every kind of line.
    ev0 = [e for e in events[1] if e.get("symbol") == "HAL"][0]
    events[1].append({"id": eid, "client_id": 1, "kind": "sell", "symbol": "HAL", "qty": math.floor(ev0["qty"] / 3),
                      "price": round(px("HAL") * 0.97, 2), "amount": None, "charges": 180.0, "rec_id": None,
                      "rec_price": None, "on_date": _months_ago(2, ref), "note": "Booked a third"})
    eid += 1
    events[2].append({"id": eid, "client_id": 2, "kind": "dividend", "symbol": None, "qty": None, "price": None,
                      "amount": 4250.0, "charges": 0.0, "rec_id": None, "rec_price": None,
                      "on_date": _months_ago(3, ref), "note": "ITC final dividend"})
    eid += 1
    # Two periods already settled for most clients, each measured from the one
    # before it, at profit levels below today's — so the high-water mark, the
    # invoices and this quarter's accrual all have something to show.
    data = {"desk": desk, "clients": clients, "events": events, "settlements": settles, "recs": recs, "prices": {}}
    first = compute_book(data, quotes, on=ref.isoformat(), demo=True)
    sid = 1
    plan = {1: (0.52, 0.80), 2: (0.70,), 3: (0.45, 0.76), 5: (0.66,)}
    for c in first["clients"]:
        fracs = plan.get(c["id"])
        if not fracs or not c["profit"] or c["profit"] <= 0:
            continue
        period = c["terms"]["period"]
        # The boundaries before today, oldest first.
        ends, d = [], _d(c["since"])
        while True:
            e = next_due(d.isoformat(), period)
            if e >= ref.isoformat():
                break
            ends.append(e)
            d = _d(e)
        ends = ends[-len(fracs):]
        start, hwm = c["since"], 0.0
        for k, (end, frac) in enumerate(zip(ends, fracs)):
            lvl = round(c["profit"] * frac, 2)
            st = replay(events[c["id"]], until=end)
            m = fee_math(c["terms"], lvl, hwm, capital_days(st, start, end), (_d(end) - _d(start)).days)
            fee = round(m["total"], 2)
            last = k == len(ends) - 1
            unpaid = last and c["id"] == 3
            settles[c["id"]].append({
                "id": sid, "client_id": c["id"], "period_start": start, "period_end": end,
                "level_total": lvl, "level_realised": round(c["booked"] or 0, 2), "computed": fee,
                "amount": fee, "gst": round(m["gst"], 2),
                "status": "nil" if fee < 0.5 else ("due" if unpaid else "paid"),
                "paid_on": None if (fee < 0.5 or unpaid) else (_d(end) + dt.timedelta(days=9 + k)).isoformat(),
                "note": None, "detail": {}, "created_at": end})
            sid += 1
            hwm, start = max(hwm, lvl), end
    return data
