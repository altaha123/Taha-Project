"""
Connect your broker: a member links their own Dhan account to Altaha, sees
what it holds, and — once the owner switches orders on — places orders here
that land in that account and show up in the broker's own app.

ALTAHA IS NOT THE BROKER
The broker executes every order and holds every rupee. Altaha sends an order
the member typed, on the member's own broker session, and shows what the
broker says back. Nothing here holds money, routes to an exchange or decides
what to buy.

WHAT IS STORED, AND WHAT NEVER IS
The broker's access token, encrypted (BROKER_TOKEN_KEY, Fernet), with the
client id and name it belongs to. Never a broker password, PIN or TOTP
secret: the member logs in on the broker's own page, and the broker hands
back a token that expires on its own (about a day at Dhan). A copy of the
accounts database without the key is a list of client ids, not a way to
trade. A key rotated away makes every stored token unreadable, which reads
as "reconnect", never as a crash.

AN ALTAHA SESSION NOW REACHES MONEY
The site keeps its session token in localStorage (see accounts.py), a risk
that was accepted when the worst a stolen token could do was read a
watchlist. With a broker linked it could place an order, so the defences sit
here, on the server, where a modified page cannot remove them:

  * Orders stay off until BROKER_TRADING=on, and the owner can halt them all
    at once without a deploy (POST /admin/broker/halt).
  * The broker token expires daily, so a stolen Altaha session is good for
    orders until the member's broker session ends, not for ninety days.
  * Every order is capped in value (BROKER_MAX_ORDER_VALUE), in count per day
    and per minute, and a limit price far from the market is refused as a
    likely typo. A member can pause trading on their own account.

AN ORDER IS NEVER SENT TWICE, AND NEVER GUESSED AT
The browser names each order (client_ref). The row is written before the
broker is called, under a unique (member, client_ref) key, so a double tap
or a retried request finds the first row and sends nothing. If the broker
does not answer — a timeout, a dropped connection, this instance restarted
mid-call — the row says "unknown", the member is told to check before
placing it again, and the next look asks the broker by the order's
correlation id. Altaha never retries an order on its own.

WHAT THE MEMBER CHOOSES
This module takes a symbol, a side, a quantity and a price from the member
and nothing from Altaha's scores, picks or levels. The README's line between
research and advice is why: an order button pre-filled from a pick is a
recommendation to trade, and that needs SEBI registration this project does
not have.

ONE BROKER PER MEMBER, ONE MODULE PER BROKER
broker_dhan.py speaks Dhan and broker_zerodha.py speaks Zerodha (Kite
Connect). A member links one at a time. Another broker is another module with the same
functions (start_login, finish_login, place, cancel, order, order_by_ref,
orders, holdings, positions, funds, instrument), added to _adapters().
"""
from __future__ import annotations

import datetime as dt
import os
import re
import secrets
import sqlite3
import threading

import accounts

# ---------------------------------------------------------------------------
# What can go wrong, as the routes see it
# ---------------------------------------------------------------------------


class NotSwitchedOn(Exception):
    """The owner has not configured this (keys, or orders). A 503."""


class NeedsReconnect(Exception):
    """The broker session has ended or cannot be read. The member logs in at
    the broker again; nothing else is wrong. A 409, never a 401, because the
    site reads 401 as "your Altaha session has ended" and signs the member
    out."""


class BrokerError(Exception):
    """The broker answered and said no, with a reason worth showing."""

    def __init__(self, message: str, code: str = ""):
        super().__init__(message)
        self.code = code


class BrokerUnreachable(Exception):
    """The broker did not answer. For an order this means "we do not know"."""


class RateLimited(Exception):
    """Too many, too fast. A 429."""


# ---------------------------------------------------------------------------
# Settings. Read on every call, so a changed environment needs no import.
# ---------------------------------------------------------------------------

DISCLAIMER = (
    "Orders go to your broker exactly as you enter them, and your broker executes them. "
    "Altaha does not advise on any order, is not a broker, and is not registered with "
    "SEBI as an adviser or research analyst. Check every order in your broker's app."
)

CONSENT_TTL_MINUTES = 15
CONSENTS_PER_HOUR = 10
MAX_QTY = 100_000
FAT_FINGER = 0.20            # a limit or trigger price this far from the market is refused
SIDES = ("BUY", "SELL")
TYPES = ("MARKET", "LIMIT", "SL", "SL-M")
PRODUCTS = ("CNC", "INTRADAY")
VALIDITIES = ("DAY", "IOC")
OPEN = ("sending", "open", "part_filled", "unknown")
FINAL = ("filled", "rejected", "cancelled", "expired")
REF_RE = re.compile(r"^[A-Za-z0-9-]{8,40}$")

# main.py points this at a live last-price lookup (Dhan's quote feed). It is
# the price a market order's value is judged by. Left as None, the price the
# ticket showed the member is used instead.
PRICE = None


def _env_num(name: str, default: float) -> float:
    try:
        v = float(os.environ.get(name, "").strip() or default)
        return v if v > 0 else default
    except ValueError:
        return default


def max_order_value() -> float:
    return _env_num("BROKER_MAX_ORDER_VALUE", 500_000)


def max_orders_per_day() -> int:
    return int(_env_num("BROKER_MAX_ORDERS_PER_DAY", 50))


def max_orders_per_minute() -> int:
    return int(_env_num("BROKER_MAX_ORDERS_PER_MINUTE", 10))


def _members() -> set:
    raw = os.environ.get("BROKER_MEMBERS", "")
    return {accounts.valid_email(e) for e in raw.split(",") if accounts.valid_email(e)}


def _adapters() -> dict:
    """Imported here, not at the top: an adapter imports this module for its
    exceptions, and a broker module that fails to import must cost that
    broker and nothing else."""
    out = {}
    for name in ("broker_dhan", "broker_zerodha"):
        try:
            mod = __import__(name)
            out[mod.ID] = mod
        except Exception as e:                                # pragma: no cover
            print(f"[brokers] {name} not loaded: {type(e).__name__}: {e}", flush=True)
    return out


# Tests replace this with a dict of fakes.
ADAPTERS = None


def adapters() -> dict:
    return ADAPTERS if ADAPTERS is not None else _adapters()


def _adapter(broker_id: str):
    a = adapters().get(str(broker_id or "").strip().lower())
    if a is None:
        raise ValueError("That broker is not supported yet.")
    return a


# ---------------------------------------------------------------------------
# The key that keeps tokens unreadable at rest
# ---------------------------------------------------------------------------

def _cipher():
    """MultiFernet over BROKER_TOKEN_KEY (comma-separated, newest first, so a
    key can be rotated without signing everybody out at once), or None."""
    raw = [k.strip() for k in os.environ.get("BROKER_TOKEN_KEY", "").split(",") if k.strip()]
    if not raw:
        return None
    try:
        from cryptography.fernet import Fernet, MultiFernet
        return MultiFernet([Fernet(k.encode()) for k in raw])
    except Exception as e:
        print(f"[brokers] BROKER_TOKEN_KEY unusable: {type(e).__name__}", flush=True)
        return None


def _seal(token: str) -> str:
    c = _cipher()
    if c is None:
        raise NotSwitchedOn("Broker connections are not switched on.")
    return c.encrypt(token.encode()).decode()


def _open_token(blob: str) -> str:
    c = _cipher()
    if c is None:
        raise NotSwitchedOn("Broker connections are not switched on.")
    try:
        return c.decrypt(blob.encode()).decode()
    except Exception:
        raise NeedsReconnect("Your broker session could not be read. Connect again to continue.")


# ---------------------------------------------------------------------------
# Storage, in the accounts database (the backup already copies it)
# ---------------------------------------------------------------------------

SCHEMA = """
-- One linked broker account per member.
CREATE TABLE IF NOT EXISTS broker_links (
  user_id      INTEGER PRIMARY KEY,
  broker       TEXT NOT NULL,
  client_id    TEXT NOT NULL,
  client_name  TEXT,
  token_enc    TEXT NOT NULL,       -- Fernet; never the token itself
  expires_at   TEXT,                -- the broker's own expiry, UTC
  connected_at TEXT NOT NULL,
  last_used_at TEXT,
  paused       INTEGER NOT NULL DEFAULT 0
);
-- A login started here. The broker sends the member back with a one-time
-- id and nothing that says who they are, so finishing needs a login this
-- member started, recently, and has not finished yet.
CREATE TABLE IF NOT EXISTS broker_consents (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id    INTEGER NOT NULL,
  broker     TEXT NOT NULL,
  ref        TEXT,
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  used_at    TEXT
);
CREATE INDEX IF NOT EXISTS idx_bconsent_user ON broker_consents(user_id, created_at);
-- Every order Altaha sent, written before it was sent.
CREATE TABLE IF NOT EXISTS broker_orders (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id         INTEGER NOT NULL,
  broker          TEXT NOT NULL,
  client_id       TEXT NOT NULL,
  client_ref      TEXT NOT NULL,     -- the browser's name for it: one row per name
  correlation_id  TEXT,              -- ours, sent to the broker
  broker_order_id TEXT,
  symbol          TEXT NOT NULL,
  side            TEXT NOT NULL,
  qty             INTEGER NOT NULL,
  order_type      TEXT NOT NULL,
  product         TEXT NOT NULL,
  validity        TEXT NOT NULL,
  price           REAL,
  trigger_price   REAL,
  value_est       REAL,
  status          TEXT NOT NULL,     -- sending|open|part_filled|filled|rejected|cancelled|expired|unknown
  broker_status   TEXT,
  message         TEXT,
  filled_qty      INTEGER,
  avg_price       REAL,
  source          TEXT,
  created_at      TEXT NOT NULL,
  updated_at      TEXT NOT NULL,
  UNIQUE (user_id, client_ref)
);
CREATE INDEX IF NOT EXISTS idx_borders_user ON broker_orders(user_id, created_at);
CREATE TABLE IF NOT EXISTS broker_events (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id    INTEGER NOT NULL,
  broker     TEXT,
  kind       TEXT NOT NULL,          -- connect|disconnect|pause|resume|expired
  detail     TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS broker_settings (
  key   TEXT PRIMARY KEY,
  value TEXT
);
"""

_local = threading.local()
_now = accounts._now
_iso = accounts._iso


def _conn():
    """The accounts connection for this thread, with this module's tables
    (per connection object, as forum.py does, because reset_for_tests swaps
    the connection out)."""
    conn = accounts._connect()
    if getattr(_local, "ready", None) is not conn:
        conn.executescript(SCHEMA)
        _local.ready = conn
    return conn


def _event(conn, user_id, broker, kind, detail=""):
    conn.execute("INSERT INTO broker_events(user_id,broker,kind,detail,created_at) VALUES(?,?,?,?,?)",
                 (user_id, broker, kind, str(detail or "")[:300], _iso(_now())))


def _ist_day_start_utc(now=None) -> str:
    now = now or _now()
    ist = now.astimezone(dt.timezone(dt.timedelta(hours=5, minutes=30)))
    start = ist.replace(hour=0, minute=0, second=0, microsecond=0)
    return _iso(start.astimezone(dt.timezone.utc))


# ---------------------------------------------------------------------------
# Switches
# ---------------------------------------------------------------------------

def halted() -> bool:
    try:
        row = _conn().execute("SELECT value FROM broker_settings WHERE key='halt'").fetchone()
        return bool(row and row["value"] == "1")
    except sqlite3.Error:
        return True     # cannot tell, so do not trade


def set_halt(on: bool) -> bool:
    conn = _conn()
    with conn:
        conn.execute("INSERT INTO broker_settings(key,value) VALUES('halt',?) "
                     "ON CONFLICT(key) DO UPDATE SET value=excluded.value", ("1" if on else "0",))
    return halted()


def connect_on() -> bool:
    return _cipher() is not None and any(a.available() for a in adapters().values())


def trading_on() -> bool:
    return (connect_on() and os.environ.get("BROKER_TRADING", "").strip().lower() == "on"
            and not halted())


def allowed_for(user, a) -> bool:
    """Who may connect to one broker. BROKER_MEMBERS, when set, is the list
    for every broker. A broker app that may only log in its owner's account
    (Dhan's individual API key, a Kite Connect app not cleared for other
    clients) is closed unless that list names who it is for. Decided per
    broker, so a test key for one cannot close another that is open."""
    if not user or a is None or not a.available():
        return False
    members = _members()
    if members:
        return user.get("email") in members
    return not a.needs_allowlist()


def allowed(user) -> bool:
    """May this member connect any broker at all."""
    return any(allowed_for(user, a) for a in adapters().values())


def config(user=None) -> dict:
    return {
        "connect": connect_on(),
        "trading": trading_on(),
        "halted": halted(),
        "allowed": allowed(user) if user else None,
        "brokers": [{"id": a.ID, "label": a.LABEL, "available": bool(a.available()),
                     "allowed": allowed_for(user, a) if user else None}
                    for a in adapters().values()],
        "limits": {"max_order_value": max_order_value(),
                   "max_orders_per_day": max_orders_per_day(),
                   "max_qty": MAX_QTY},
        "disclaimer": DISCLAIMER,
    }


# ---------------------------------------------------------------------------
# Connecting
# ---------------------------------------------------------------------------

def _require_connect(user, a=None):
    if not connect_on():
        raise NotSwitchedOn("Broker connections are not switched on yet.")
    if a is not None and not a.available():
        raise NotSwitchedOn(f"{a.LABEL} connections are not switched on yet.")
    if not (allowed_for(user, a) if a is not None else allowed(user)):
        raise PermissionError("Broker connections are open to a few members while they are tested.")


def start_connect(user: dict, broker_id: str) -> dict:
    """The broker's login page for this member. Records that this member
    started a login, which is what finish_connect checks for."""
    a = _adapter(broker_id)
    _require_connect(user, a)
    conn = _conn()
    now = _now()
    hour_ago = _iso(now - dt.timedelta(hours=1))
    n = conn.execute("SELECT COUNT(*) c FROM broker_consents WHERE user_id=? AND created_at>?",
                     (user["id"], hour_ago)).fetchone()["c"]
    if n >= CONSENTS_PER_HOUR:
        raise RateLimited("Too many connection attempts. Try again in an hour.")
    started = a.start_login()
    with conn:
        conn.execute("INSERT INTO broker_consents(user_id,broker,ref,created_at,expires_at) "
                     "VALUES(?,?,?,?,?)",
                     (user["id"], a.ID, str(started.get("ref") or "")[:200], _iso(now),
                      _iso(now + dt.timedelta(minutes=CONSENT_TTL_MINUTES))))
    return {"broker": a.ID, "login_url": started["login_url"]}


def finish_connect(user: dict, broker_id: str, token_id: str) -> dict:
    """The member is back from the broker with a one-time token id. Only a
    login this member started here in the last fifteen minutes can finish,
    and the attempt is spent before the broker is asked, so a token id that
    reaches the server twice links once."""
    a = _adapter(broker_id)
    _require_connect(user, a)
    token_id = str(token_id or "").strip()
    if not token_id or len(token_id) > 2000:
        raise ValueError(f"{a.LABEL} did not send back a sign-in. Press Connect again.")
    conn = _conn()
    now = _iso(_now())
    with conn:
        row = conn.execute(
            "SELECT id FROM broker_consents WHERE user_id=? AND broker=? AND used_at IS NULL "
            "AND expires_at>? ORDER BY id DESC LIMIT 1", (user["id"], a.ID, now)).fetchone()
        if row is None:
            raise ValueError(f"This {a.LABEL} sign-in was not started here, or took longer than "
                             f"{CONSENT_TTL_MINUTES} minutes. Press Connect again.")
        conn.execute("UPDATE broker_consents SET used_at=? WHERE id=?", (now, row["id"]))
    got = a.finish_login(token_id)
    token = str(got.get("access_token") or "")
    client_id = str(got.get("client_id") or "").strip()
    if not token or not client_id:
        raise BrokerError(f"{a.LABEL} did not return a usable session. Press Connect again.")
    sealed = _seal(token)
    with conn:
        conn.execute(
            "INSERT INTO broker_links(user_id,broker,client_id,client_name,token_enc,expires_at,"
            "connected_at,paused) VALUES(?,?,?,?,?,?,?,0) ON CONFLICT(user_id) DO UPDATE SET "
            "broker=excluded.broker, client_id=excluded.client_id, client_name=excluded.client_name, "
            "token_enc=excluded.token_enc, expires_at=excluded.expires_at, "
            "connected_at=excluded.connected_at",
            (user["id"], a.ID, client_id, str(got.get("client_name") or "")[:120], sealed,
             got.get("expires_at"), now))
        _event(conn, user["id"], a.ID, "connect", client_id)
    return link(user["id"])


def _mask(client_id: str) -> str:
    s = str(client_id or "")
    return ("•" * max(0, len(s) - 4)) + s[-4:] if len(s) > 4 else s


def link(user_id: int):
    """What the member's own page shows about their connection, or None.
    Never the token."""
    row = _conn().execute("SELECT * FROM broker_links WHERE user_id=?", (user_id,)).fetchone()
    if row is None:
        return None
    a = adapters().get(row["broker"])
    exp = row["expires_at"]
    return {
        "broker": row["broker"],
        "label": a.LABEL if a else row["broker"].title(),
        "client_id": _mask(row["client_id"]),
        "client_name": row["client_name"] or "",
        "connected_at": row["connected_at"],
        "expires_at": exp,
        "expired": bool(exp and exp <= _iso(_now())),
        "paused": bool(row["paused"]),
    }


def disconnect(user_id: int) -> bool:
    conn = _conn()
    with conn:
        row = conn.execute("SELECT broker FROM broker_links WHERE user_id=?", (user_id,)).fetchone()
        conn.execute("DELETE FROM broker_links WHERE user_id=?", (user_id,))
        if row:
            _event(conn, user_id, row["broker"], "disconnect")
    return row is not None


def set_paused(user_id: int, paused: bool) -> dict:
    conn = _conn()
    with conn:
        cur = conn.execute("UPDATE broker_links SET paused=? WHERE user_id=?",
                           (1 if paused else 0, user_id))
        if cur.rowcount == 0:
            raise LookupError("No broker is connected.")
        _event(conn, user_id, None, "pause" if paused else "resume")
    return link(user_id)


def _session(user_id: int):
    """(adapter, {"client_id", "token"}) for a member's live connection."""
    if _cipher() is None:
        raise NotSwitchedOn("Broker connections are not switched on.")
    conn = _conn()
    row = conn.execute("SELECT * FROM broker_links WHERE user_id=?", (user_id,)).fetchone()
    if row is None:
        raise LookupError("No broker is connected. Connect one first.")
    a = adapters().get(row["broker"])
    if a is None:
        raise NeedsReconnect("That broker is no longer supported here.")
    if row["expires_at"] and row["expires_at"] <= _iso(_now()):
        raise NeedsReconnect(f"Your {a.LABEL} session has ended. Log in to {a.LABEL} again to continue.")
    sess = {"client_id": row["client_id"], "token": _open_token(row["token_enc"])}
    try:
        with conn:
            conn.execute("UPDATE broker_links SET last_used_at=? WHERE user_id=?",
                         (_iso(_now()), user_id))
    except sqlite3.Error:
        pass
    return a, sess, row


def _expire(user_id: int, broker: str, why: str):
    """The broker refused the token: mark it ended, so the page says so."""
    conn = _conn()
    try:
        with conn:
            conn.execute("UPDATE broker_links SET expires_at=? WHERE user_id=?",
                         (_iso(_now()), user_id))
            _event(conn, user_id, broker, "expired", why)
    except sqlite3.Error:
        pass


def _ask(user_id: int, what: str, *args):
    """One read from the broker on the member's session."""
    a, sess, row = _session(user_id)
    try:
        return getattr(a, what)(sess, *args)
    except NeedsReconnect as e:
        _expire(user_id, a.ID, str(e))
        raise


def funds(user_id: int) -> dict:
    return _ask(user_id, "funds")


def holdings(user_id: int) -> list:
    return _ask(user_id, "holdings")


def positions(user_id: int) -> list:
    return _ask(user_id, "positions")


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------

def _num(v, what):
    if v in (None, ""):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        raise ValueError(f"{what} must be a number.")
    if f != f or f <= 0:
        raise ValueError(f"{what} must be more than zero.")
    return round(f, 2)


def clean_order(raw: dict, market_price=None) -> dict:
    """The order as the broker will get it, or ValueError with the sentence
    the ticket shows. Pure: the tests drive every rule through here."""
    if not isinstance(raw, dict):
        raise ValueError("Nothing to send.")
    sym = accounts._clean_symbol(raw.get("symbol"))
    if not sym:
        raise ValueError("Choose a stock.")
    side = str(raw.get("side") or "").upper()
    if side not in SIDES:
        raise ValueError("Choose Buy or Sell.")
    try:
        qf = float(raw.get("qty"))
    except (TypeError, ValueError):
        raise ValueError("Quantity must be a whole number of shares.")
    if qf != qf or qf != int(qf) or qf < 1:
        raise ValueError("Quantity must be a whole number of shares, at least 1.")
    qty = int(qf)
    if qty > MAX_QTY:
        raise ValueError(f"At most {MAX_QTY:,} shares in one order.")
    otype = str(raw.get("type") or "").upper()
    if otype not in TYPES:
        raise ValueError("Choose Market, Limit, SL or SL-M.")
    product = str(raw.get("product") or "CNC").upper()
    if product not in PRODUCTS:
        raise ValueError("Choose Delivery or Intraday.")
    validity = str(raw.get("validity") or "DAY").upper()
    if validity not in VALIDITIES:
        raise ValueError("Validity is Day or IOC.")

    price = _num(raw.get("price"), "Price")
    trigger = _num(raw.get("trigger"), "Trigger price")
    if otype in ("LIMIT", "SL") and price is None:
        raise ValueError("Enter the price you want." if otype == "LIMIT" else
                         "A stop-loss limit order needs a limit price.")
    if otype in ("MARKET", "SL-M"):
        price = None
    if otype in ("SL", "SL-M"):
        if trigger is None:
            raise ValueError("Enter the trigger price.")
    else:
        trigger = None
    if otype == "SL":
        # A buy stop triggers on a rise and fills at or below its limit; a
        # sell stop the other way round. The other way is an order that
        # triggers and then cannot fill.
        if side == "BUY" and price < trigger:
            raise ValueError("For a buy stop-loss, the limit price should be at or above the trigger.")
        if side == "SELL" and price > trigger:
            raise ValueError("For a sell stop-loss, the limit price should be at or below the trigger.")

    ref = str(raw.get("client_ref") or "")
    if not REF_RE.match(ref):
        raise ValueError("This order has no reference. Reload the page and try again.")

    mkt = None
    for cand in (market_price, raw.get("ref_price")):
        try:
            f = float(cand)
            if f == f and f > 0:
                mkt = f
                break
        except (TypeError, ValueError):
            continue

    # A typo in a price is the most expensive mistake a ticket allows: ₹1,250
    # typed as ₹12,50 is a different order. The exchange's own bands catch
    # some of it; this catches it before it leaves.
    if mkt:
        for p, what in ((price, "limit price"), (trigger, "trigger price")):
            if p is not None and abs(p / mkt - 1) > FAT_FINGER:
                raise ValueError(f"That {what} is more than {int(FAT_FINGER * 100)}% away from the "
                                 f"market price of ₹{mkt:,.2f}. Check it for a typo.")

    basis = price or trigger or mkt
    if not basis:
        raise ValueError("Could not check the price of this stock just now. Use a limit order, "
                         "or try again in a moment.")
    value = round(qty * basis, 2)
    if value > max_order_value():
        raise ValueError(f"This order is worth about ₹{value:,.0f}. Orders here are limited to "
                         f"₹{max_order_value():,.0f} each; place larger ones in your broker's app.")
    return {"symbol": sym, "side": side, "qty": qty, "type": otype, "product": product,
            "validity": validity, "price": price, "trigger": trigger, "value_est": value,
            "client_ref": ref, "source": str(raw.get("source") or "")[:20]}


def _order_dict(row) -> dict:
    return {k: row[k] for k in (
        "id", "broker", "symbol", "side", "qty", "order_type", "product", "validity", "price",
        "trigger_price", "value_est", "status", "broker_status", "message", "filled_qty",
        "avg_price", "broker_order_id", "created_at", "updated_at")}


def _update(conn, oid, got: dict):
    fields = {"status": got.get("status"), "broker_status": got.get("broker_status"),
              "message": (str(got.get("message") or "")[:400] or None),
              "broker_order_id": got.get("broker_order_id"),
              "filled_qty": got.get("filled_qty"), "avg_price": got.get("avg_price")}
    fields = {k: v for k, v in fields.items() if v not in (None, "")}
    fields["updated_at"] = _iso(_now())
    sets = ",".join(f"{k}=?" for k in fields)
    with conn:
        conn.execute(f"UPDATE broker_orders SET {sets} WHERE id=?", (*fields.values(), oid))


def place_order(user: dict, raw: dict) -> dict:
    """Send one order. Returns the order as Altaha recorded it, with
    "duplicate": True when this client_ref was already sent."""
    if not trading_on():
        if halted():
            raise NotSwitchedOn("Orders from Altaha are paused just now. Use your broker's app.")
        raise NotSwitchedOn("Placing orders from Altaha is not switched on yet.")
    a, sess, linkrow = _session(user["id"])
    if not allowed_for(user, a):
        raise PermissionError("Broker trading is open to a few members while it is tested.")
    if linkrow["paused"]:
        raise PermissionError("You paused trading on this account. Resume it on Your broker page.")

    conn = _conn()
    ref = str((raw or {}).get("client_ref") or "")
    if REF_RE.match(ref):
        seen = conn.execute("SELECT * FROM broker_orders WHERE user_id=? AND client_ref=?",
                            (user["id"], ref)).fetchone()
        if seen is not None:
            return dict(_order_dict(seen), duplicate=True)

    market = None
    sym = accounts._clean_symbol((raw or {}).get("symbol"))
    if PRICE is not None and sym:
        try:
            market = PRICE(sym)
        except Exception:
            market = None
    o = clean_order(raw, market)

    sid = a.instrument(o["symbol"])
    if not sid:
        raise ValueError(f"{o['symbol']} cannot be traded through {a.LABEL} from here.")

    now = _now()
    n_day = conn.execute("SELECT COUNT(*) c FROM broker_orders WHERE user_id=? AND created_at>=?",
                         (user["id"], _ist_day_start_utc(now))).fetchone()["c"]
    if n_day >= max_orders_per_day():
        raise RateLimited(f"That is {n_day} orders from Altaha today, the most allowed in a day. "
                          "Use your broker's app for more.")
    n_min = conn.execute("SELECT COUNT(*) c FROM broker_orders WHERE user_id=? AND created_at>=?",
                         (user["id"], _iso(now - dt.timedelta(minutes=1)))).fetchone()["c"]
    if n_min >= max_orders_per_minute():
        raise RateLimited("Too many orders in a minute. Wait a moment.")

    stamp = _iso(now)
    try:
        with conn:
            cur = conn.execute(
                "INSERT INTO broker_orders(user_id,broker,client_id,client_ref,symbol,side,qty,"
                "order_type,product,validity,price,trigger_price,value_est,status,source,"
                "created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,'sending',?,?,?)",
                (user["id"], a.ID, sess["client_id"], o["client_ref"], o["symbol"], o["side"],
                 o["qty"], o["type"], o["product"], o["validity"], o["price"], o["trigger"],
                 o["value_est"], o["source"], stamp, stamp))
            oid = cur.lastrowid
            # Letters and digits only, under 20: Kite's order tag allows
            # nothing else, and Dhan's correlationId accepts it too.
            corr = f"alt{oid}x{secrets.token_hex(3)}"
            conn.execute("UPDATE broker_orders SET correlation_id=? WHERE id=?", (corr, oid))
    except sqlite3.IntegrityError:
        # The same order, arriving twice at once: the first one is sending it.
        seen = conn.execute("SELECT * FROM broker_orders WHERE user_id=? AND client_ref=?",
                            (user["id"], o["client_ref"])).fetchone()
        return dict(_order_dict(seen), duplicate=True)

    try:
        got = a.place(sess, dict(o, security_id=sid, correlation_id=corr))
        _update(conn, oid, got)
    except NeedsReconnect as e:
        _update(conn, oid, {"status": "rejected", "message": str(e)})
        _expire(user["id"], a.ID, str(e))
        raise
    except BrokerError as e:
        _update(conn, oid, {"status": "rejected", "message": str(e)})
    except Exception as e:
        # BrokerUnreachable, a timeout, anything: the broker may have it.
        _update(conn, oid, {"status": "unknown", "message":
                            f"{a.LABEL} did not confirm this order. Check Today's orders before "
                            "placing it again."})
        print(f"[brokers] order {oid} unconfirmed: {type(e).__name__}: {e}", flush=True)
    row = conn.execute("SELECT * FROM broker_orders WHERE id=?", (oid,)).fetchone()
    return _order_dict(row)


def order(user_id: int, order_id: int) -> dict:
    """One order Altaha sent, refreshed from the broker while it is open."""
    conn = _conn()
    row = conn.execute("SELECT * FROM broker_orders WHERE id=? AND user_id=?",
                       (order_id, user_id)).fetchone()
    if row is None:
        raise LookupError("No such order.")
    if row["status"] in FINAL:
        return _order_dict(row)
    try:
        a, sess, _ = _session(user_id)
        if row["broker_order_id"]:
            got = a.order(sess, row["broker_order_id"])
        else:
            got = a.order_by_ref(sess, row["correlation_id"])
            # "sending" this old means the instance died between writing the
            # row and hearing back; it is resolved the same way as "unknown".
            if got is None and row["status"] in ("unknown", "sending"):
                age = (_now() - dt.datetime.fromisoformat(row["created_at"])).total_seconds()
                if age > 600:
                    got = {"status": "rejected", "message":
                           f"{a.LABEL} has no record of this order, so it was not placed."}
        if got:
            _update(conn, row["id"], got)
    except (NeedsReconnect, BrokerError, BrokerUnreachable, NotSwitchedOn, LookupError):
        pass
    return _order_dict(conn.execute("SELECT * FROM broker_orders WHERE id=?", (row["id"],)).fetchone())


def orders(user_id: int) -> dict:
    """Today's orders as the broker has them, each marked when it was placed
    from Altaha, plus Altaha's own rows the broker does not list (an order it
    never confirmed is exactly the one a member needs to see)."""
    conn = _conn()
    mine = conn.execute("SELECT * FROM broker_orders WHERE user_id=? AND created_at>=? ORDER BY id DESC",
                        (user_id, _ist_day_start_utc())).fetchall()
    book = _ask(user_id, "orders")
    by_id = {r["broker_order_id"]: r for r in mine if r["broker_order_id"]}
    by_corr = {r["correlation_id"]: r for r in mine if r["correlation_id"]}
    seen = set()
    out = []
    for b in book:
        r = by_id.get(b.get("broker_order_id")) or by_corr.get(b.get("ref"))
        if r is not None:
            seen.add(r["id"])
            if r["status"] != b.get("status") or not r["broker_order_id"]:
                try:
                    _update(conn, r["id"], b)
                except sqlite3.Error:
                    pass
        out.append(dict(b, via_altaha=r is not None, altaha_id=r["id"] if r is not None else None))
    for r in mine:
        if r["id"] not in seen and r["status"] in ("sending", "unknown", "rejected"):
            d = _order_dict(r)
            out.append({"broker_order_id": d["broker_order_id"], "symbol": d["symbol"],
                        "side": d["side"], "qty": d["qty"], "filled_qty": d["filled_qty"],
                        "type": d["order_type"], "product": d["product"], "price": d["price"],
                        "trigger": d["trigger_price"], "status": d["status"],
                        "message": d["message"], "time": d["created_at"],
                        "via_altaha": True, "altaha_id": d["id"]})
    return {"orders": out}


def cancel_order(user_id: int, broker_order_id: str) -> dict:
    """Cancel an open order on the member's own account. Their token can only
    reach their own orders, so any open order in their book may be cancelled
    here, including one placed in the broker's app."""
    boid = str(broker_order_id or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9-]{1,40}", boid):
        raise ValueError("Which order?")
    got = _ask(user_id, "cancel", boid)
    conn = _conn()
    row = conn.execute("SELECT id FROM broker_orders WHERE user_id=? AND broker_order_id=?",
                       (user_id, boid)).fetchone()
    if row is not None and got:
        _update(conn, row["id"], got)
    return got or {"status": "cancelled"}


def copy_holdings(user_id: int) -> dict:
    """The broker's holdings become the portfolio saved on the account
    (replacing it, as the portfolio's own Save does)."""
    rows = holdings(user_id)
    saved = accounts.save_holdings(user_id, [
        {"symbol": h["symbol"], "qty": h["qty"], "avg_price": h.get("avg_price")}
        for h in rows if h.get("qty")])
    return dict(saved, from_broker=len(rows))


# ---------------------------------------------------------------------------
# The owner's view
# ---------------------------------------------------------------------------

def summary() -> dict:
    conn = _conn()
    one = lambda q, *a: conn.execute(q, a).fetchone()["c"]       # noqa: E731
    day = _ist_day_start_utc()
    by_status = {r["status"]: r["c"] for r in conn.execute(
        "SELECT status, COUNT(*) c FROM broker_orders WHERE created_at>=? GROUP BY status", (day,))}
    return {
        "connect": connect_on(), "trading": trading_on(), "halted": halted(),
        "linked": one("SELECT COUNT(*) c FROM broker_links"),
        "orders_today": sum(by_status.values()),
        "orders_today_by_status": by_status,
        "unknown_open": one("SELECT COUNT(*) c FROM broker_orders WHERE status IN ('unknown','sending')"),
    }
