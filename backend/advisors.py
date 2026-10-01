"""
Advisors: people a reader can talk to.

SEBI-registered investment advisers, registered research analysts, and
well-known market educators register here; once approved they are listed, and
any signed-in reader can open a chat with them — about a portfolio, a stock,
a fund, a career, anything.

THREE KINDS OF PERSON, BECAUSE THE LAW HAS THREE
  ria       SEBI-registered Investment Adviser (INA + 9 digits). May advise
            on a person's own money, so only they can take a "Portfolio
            review" and only they can see a portfolio a reader shares.
  ra        SEBI-registered Research Analyst (INH + 9 digits). May publish
            views on securities; advice on somebody's whole book is the
            adviser's licence, not theirs.
  educator  Not registered. A well-known investor, author, creator. May
            teach and say how they think; may not tell a reader to buy or
            sell. Their replies are checked for that before they are sent
            (call_sentence below), the same rule score_explain.py applies to
            the AI explanation.

A registration number is typed by the applicant and verified by the owner
against SEBI's public register before the profile is listed. Nothing is
listed until that review (status "approved"), and changing the category or
the number on a live profile sends it back for review.

WHY NO STAR RATINGS
SEBI's advertisement code for registered advisers does not allow testimonials,
and a five-star badge next to a registration number is a testimonial. What is
shown instead is factual: the registration, experience, and how quickly the
person usually replies.

WHY POLLING AND NOT WEBSOCKETS
One uvicorn worker, eight threads, 512 MB. A socket or a long poll holds a
thread for as long as somebody has a chat open, and eight open chats would
starve every other page on the site. A short poll is one indexed SQLite read
and returns at once; the page polls every few seconds while a chat is open
and visible, and slows down when nothing is happening.

WHY THE SAME DATABASE AS ACCOUNTS
Every row here belongs to an account, the backup already copies that file,
and a join to `users` is how a notification finds an address. The statements
live in this module rather than accounts.py so the feature can be read in one
place; moving to Postgres is these two files.

WHAT IS STORED
Profiles, chats and every message, kept — never edited, never deleted. A
registered adviser must be able to produce the record of what was said to
whom and when, and a reader who reports a chat needs the owner to be able to
read what happened. The reader's email address is never shown to the person
they are talking to: they choose the name the other side sees.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import threading

import accounts

# ---------------------------------------------------------------------------
# The vocabulary
# ---------------------------------------------------------------------------

KINDS = {
    "ria": {"label": "SEBI-registered Investment Adviser", "short": "SEBI RIA",
            "prefix": "INA", "registered": True},
    "ra": {"label": "SEBI-registered Research Analyst", "short": "SEBI RA",
           "prefix": "INH", "registered": True},
    "educator": {"label": "Educator · not SEBI-registered", "short": "Educator",
                 "prefix": None, "registered": False},
}

# Topic id, label, and who may offer it. Advice on a person's own holdings is
# the investment adviser's licence and nobody else's.
TOPICS = [
    ("portfolio", "Portfolio review", ("ria",)),
    ("stocks", "Stocks & research", ("ria", "ra", "educator")),
    ("mutual_funds", "Mutual funds & SIPs", ("ria", "ra", "educator")),
    ("retirement", "Retirement & goals", ("ria", "educator")),
    ("tax", "Tax & planning", ("ria", "educator")),
    ("trading", "Trading & technicals", ("ria", "ra", "educator")),
    ("learning", "Learning the markets", ("ria", "ra", "educator")),
    ("career", "Careers in finance", ("ria", "ra", "educator")),
    ("ama", "Ask me anything", ("ria", "ra", "educator")),
]
TOPIC_LABEL = {t: label for t, label, _ in TOPICS}
TOPIC_KINDS = {t: kinds for t, _, kinds in TOPICS}

STATUSES = ("pending", "approved", "rejected", "suspended")

# SEBI's own lists, linked from every registered profile so a reader can check
# the number without taking Altaha's word for it.
SEBI_REGISTER = {
    "ria": "https://www.sebi.gov.in/sebiweb/other/OtherAction.do?doRecognisedFpi=yes&intmId=13",
    "ra": "https://www.sebi.gov.in/sebiweb/other/OtherAction.do?doRecognisedFpi=yes&intmId=14",
}

DISCLAIMER = (
    "Altaha lists these people and carries the conversation; it does not advise "
    "you and does not read your chats. A SEBI registration shown here was "
    "checked against SEBI's public register before the profile was listed — "
    "check it yourself on sebi.gov.in. Educators are not registered: they can "
    "teach and share how they think, not tell you what to buy or sell. Chats "
    "are free. Never pay anyone you meet here, never move the conversation to "
    "WhatsApp or Telegram, and never share an OTP, password or demat login."
)

# ---------------------------------------------------------------------------
# Limits
# ---------------------------------------------------------------------------

MAX_MESSAGE = 2000
NEW_CHATS_PER_DAY = 5          # per reader; enough to shop around, not to spam
MESSAGES_PER_MINUTE = 12       # per person, across every chat
PAGE = 200                     # messages returned per read
ONLINE_WINDOW = dt.timedelta(minutes=5)
# Somebody who has looked at the chat this recently will see the message on
# the page; an email would only arrive after they had read it.
NOTIFY_IF_UNSEEN_FOR = dt.timedelta(minutes=3)
# A poll is a read. Writing "seen" on every one of them would turn every open
# chat into a write every few seconds, so the timestamp moves at most this often.
TOUCH_EVERY = dt.timedelta(seconds=60)
MAX_DIRECTORY = 200


class RateLimited(Exception):
    """Too much, too fast. A 429, with a sentence."""


class MessageRefused(ValueError):
    """A message that cannot be sent as written. Carries the sentence that
    tripped the check, so the sender can see exactly what to rephrase."""

    def __init__(self, message: str, sentence: str = ""):
        super().__init__(message)
        self.sentence = sentence


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS experts (
  id               INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id          INTEGER NOT NULL UNIQUE,
  slug             TEXT NOT NULL UNIQUE,
  display_name     TEXT NOT NULL,
  headline         TEXT NOT NULL,
  bio              TEXT NOT NULL,
  kind             TEXT NOT NULL,
  sebi_reg         TEXT,
  topics           TEXT NOT NULL,      -- JSON list of TOPICS ids
  languages        TEXT NOT NULL,      -- JSON list
  experience_years INTEGER,
  links            TEXT NOT NULL,      -- JSON list of https URLs
  status           TEXT NOT NULL,      -- pending | approved | rejected | suspended
  review_note      TEXT,
  featured         INTEGER NOT NULL DEFAULT 0,
  accepting        INTEGER NOT NULL DEFAULT 1,
  last_seen        TEXT,
  created_at       TEXT NOT NULL,
  updated_at       TEXT NOT NULL,
  reviewed_at      TEXT
);
CREATE INDEX IF NOT EXISTS idx_experts_status ON experts(status);
-- One conversation between a reader (the seeker) and an expert. The read
-- pointers are message ids, so "unread" is a comparison, not a table.
CREATE TABLE IF NOT EXISTS chats (
  id                 INTEGER PRIMARY KEY AUTOINCREMENT,
  expert_id          INTEGER NOT NULL,
  user_id            INTEGER NOT NULL,
  topic              TEXT NOT NULL,
  seeker_name        TEXT NOT NULL,
  share_portfolio    INTEGER NOT NULL DEFAULT 0,
  status             TEXT NOT NULL DEFAULT 'open',   -- open | closed
  closed_by          TEXT,
  blocked            INTEGER NOT NULL DEFAULT 0,
  created_at         TEXT NOT NULL,
  last_message_at    TEXT NOT NULL,
  seeker_read_id     INTEGER NOT NULL DEFAULT 0,
  expert_read_id     INTEGER NOT NULL DEFAULT 0,
  seeker_seen_at     TEXT,
  expert_seen_at     TEXT,
  seeker_notified_at TEXT,
  expert_notified_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_chats_user ON chats(user_id, last_message_at);
CREATE INDEX IF NOT EXISTS idx_chats_expert ON chats(expert_id, last_message_at);
CREATE TABLE IF NOT EXISTS chat_messages (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  chat_id    INTEGER NOT NULL,
  sender     TEXT NOT NULL,          -- seeker | expert | system
  user_id    INTEGER,                -- who typed it; NULL for system lines
  body       TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_chat ON chat_messages(chat_id, id);
CREATE INDEX IF NOT EXISTS idx_messages_user ON chat_messages(user_id, created_at);
CREATE TABLE IF NOT EXISTS chat_reports (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  chat_id     INTEGER NOT NULL,
  reporter    TEXT NOT NULL,         -- seeker | expert
  reason      TEXT NOT NULL,
  created_at  TEXT NOT NULL,
  UNIQUE (chat_id, reporter)
);
"""

_local = threading.local()


def _conn():
    """The accounts connection for this thread, with this module's tables.

    accounts.reset_for_tests swaps the connection out from under us, so the
    schema is applied per connection object rather than once per process."""
    conn = accounts._connect()
    if getattr(_local, "ready", None) is not conn:
        conn.executescript(SCHEMA)
        _local.ready = conn
    return conn


_now = accounts._now
_iso = accounts._iso


def _parse(ts):
    try:
        return dt.datetime.fromisoformat(ts) if ts else None
    except ValueError:
        return None


def _jl(raw) -> list:
    try:
        v = json.loads(raw or "[]")
        return v if isinstance(v, list) else []
    except ValueError:
        return []


# ---------------------------------------------------------------------------
# What may be said
#
# Two checks, both a sentence at a time with the negation rule from
# score_explain.py: a sentence trips only when no "not / never / no" comes
# before the term, so "nothing here is guaranteed" passes and "returns are
# guaranteed" does not. A question is never a call, so a sentence ending in
# "?" is skipped.
# ---------------------------------------------------------------------------

# A call: telling somebody to trade, or giving them the levels to do it at.
# Only educators are held to this — giving calls is what registration is for.
_CALL = re.compile(
    r"\b(buy(?![- ]?(?:and[- ]hold|back|side))|sell(?![- ]?(?:off|side))|"
    r"accumulate|go (?:long|short)|"
    r"target price|price target|target of|tgt|stop[- ]?loss|sl at|"
    r"(?:entry|exit) (?:at|price|point|level|zone)|"
    r"book (?:profits?|gains?|losses?)|recommend(?:ed|s|ation)?)\b", re.I)

# A promise of returns. Nobody may make one, registered or not.
_PROMISE = re.compile(
    r"\b(guarantee(?:d|s)?|assured returns?|sure[- ]?shot|risk[- ]?free|"
    r"double your money|100% (?:safe|sure|returns?|profit))\b", re.I)

# The ways a conversation is moved somewhere nobody can see it — which is how
# the investment scams that end in a fake trading app begin. Applies to both
# sides: a reader asked for their number cannot be talked into sending it.
_OFF_PLATFORM = [
    (re.compile(r"(?<![\d+])(?:\+?91[\s-]?)?[6-9]\d{4}[\s-]?\d{5}(?!\d)"), "a phone number"),
    (re.compile(r"\b[\w.\-]{2,}@(?:ok(?:axis|hdfcbank|icici|sbi)|ybl|ibl|axl|apl|"
                r"paytm|upi|ptyes|ptaxis|pthdfc|ptsbi|yapl|jupiteraxis|fbl|"
                r"freecharge|airtel|kotak|icici|sbi|hdfcbank|axisbank)\b", re.I),
     "a UPI payment address"),
    (re.compile(r"(?:wa\.me|chat\.whatsapp\.com|whatsapp\.com/|t\.me/|telegram\.(?:me|dog)/)", re.I),
     "a WhatsApp or Telegram link"),
    (re.compile(r"\b[\w.+\-]+@[\w\-]+\.[\w.\-]{2,}\b"), "an email address"),
]

_NEGATION = re.compile(r"\b(?:not|never|no|nothing|neither|nor|without|cannot)\b|n't\b", re.I)
_SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+")


def _tripping(pattern, text: str):
    for sentence in _SENTENCE.split(text or ""):
        s = sentence.strip()
        if not s or s.endswith("?"):
            continue
        m = pattern.search(s)
        if not m:
            continue
        neg = _NEGATION.search(s)
        if neg and neg.start() < m.start():
            continue
        return s
    return None


def call_sentence(text: str):
    """The first sentence that reads as a buy/sell call or a price level."""
    return _tripping(_CALL, text)


def promise_sentence(text: str):
    """The first sentence that promises a return."""
    return _tripping(_PROMISE, text)


def off_platform(text: str):
    """What kind of contact detail the text carries, or None."""
    for pattern, what in _OFF_PLATFORM:
        if pattern.search(text or ""):
            return what
    return None


def check_message(body: str, sender: str, kind: str) -> None:
    """Raise MessageRefused when this cannot be sent as written."""
    what = off_platform(body)
    if what:
        raise MessageRefused(
            f"This message contains {what}, so it was not sent. Keep the "
            "conversation on Altaha — moving it to a phone, a payment app or a "
            "private group is how investment scams start.")
    if sender != "expert":
        return
    s = promise_sentence(body)
    if s:
        raise MessageRefused(
            "Nobody may promise returns, so this was not sent. Rephrase the "
            "sentence below.", s)
    if kind == "educator":
        s = call_sentence(body)
        if s:
            raise MessageRefused(
                "You are listed as an educator, not a SEBI-registered adviser, "
                "so a buy or sell call, a target or a stop-loss cannot be sent. "
                "Explain how you would think about it instead.", s)


# ---------------------------------------------------------------------------
# Profiles
# ---------------------------------------------------------------------------

_REG = re.compile(r"^(INA|INH)\d{9}$")
# Any script — Hindi is as likely as English — but a word, not markup or a number.
_NOT_LANG = re.compile(r"[\d<>@/\\:;{}\[\]()=+*&^%$#!?,._\"]")
_RESERVED_SLUGS = {"me", "admin", "chats", "profile", "new", "join"}


def _text(raw, field, lo, hi) -> str:
    s = " ".join(str(raw or "").split()) if hi <= 200 else str(raw or "").strip()
    if len(s) < lo:
        raise ValueError(f"{field} needs at least {lo} characters.")
    if len(s) > hi:
        raise ValueError(f"Keep {field.lower()} under {hi} characters.")
    return s


def clean_profile(p: dict) -> dict:
    """Validate an application. Raises ValueError with a sentence the
    applicant can act on."""
    p = p or {}
    kind = str(p.get("kind") or "").strip().lower()
    if kind not in KINDS:
        raise ValueError("Choose what you are: a registered adviser, a registered "
                         "research analyst, or an educator.")
    reg = re.sub(r"[\s\-/]", "", str(p.get("sebi_reg") or "")).upper()
    prefix = KINDS[kind]["prefix"]
    if prefix:
        if not reg:
            raise ValueError(f"Enter your SEBI registration number ({prefix} followed by nine digits).")
        if not _REG.match(reg) or not reg.startswith(prefix):
            raise ValueError(f"A {KINDS[kind]['label']} number is {prefix} followed by "
                             f"nine digits, like {prefix}000012345.")
    elif reg:
        raise ValueError("Educators are listed without a registration number. If you "
                         "are registered, choose that category instead.")

    topics = []
    for t in p.get("topics") or []:
        t = str(t)
        if t not in TOPIC_KINDS:
            raise ValueError(f"Unknown topic: {t[:30]}.")
        if kind not in TOPIC_KINDS[t]:
            raise ValueError(f"{TOPIC_LABEL[t]} is for SEBI-registered investment "
                             "advisers only.")
        if t not in topics:
            topics.append(t)
    if not topics:
        raise ValueError("Pick at least one topic people can ask you about.")
    if len(topics) > 6:
        raise ValueError("Pick at most six topics.")

    languages = []
    for lang in p.get("languages") or []:
        lang = " ".join(str(lang).split())
        if not lang:
            continue
        if len(lang) > 24 or _NOT_LANG.search(lang) or not any(c.isalpha() for c in lang):
            raise ValueError(f"“{lang[:24]}” does not look like a language.")
        if lang.lower() not in (x.lower() for x in languages):
            languages.append(lang)
    if not languages:
        raise ValueError("Add at least one language you can chat in.")
    if len(languages) > 6:
        raise ValueError("List at most six languages.")

    exp = p.get("experience_years")
    if exp in (None, ""):
        exp = None
    else:
        try:
            exp = int(exp)
        except (TypeError, ValueError):
            raise ValueError("Years of experience should be a whole number.")
        if not 0 <= exp <= 60:
            raise ValueError("Years of experience should be between 0 and 60.")

    links = []
    for u in p.get("links") or []:
        u = str(u or "").strip()
        if not u:
            continue
        if not re.match(r"^https://[^\s<>\"']{4,200}$", u):
            raise ValueError("Links must be full https:// addresses.")
        links.append(u)
    if len(links) > 3:
        raise ValueError("Add at most three links.")

    out = {
        "display_name": _text(p.get("display_name"), "Your name", 2, 60),
        "headline": _text(p.get("headline"), "The headline", 10, 120),
        "bio": _text(p.get("bio"), "About you", 40, 2000),
        "kind": kind, "sebi_reg": reg or None, "topics": topics,
        "languages": languages, "experience_years": exp, "links": links,
    }
    # A public profile is held to the same rules as a message: it is read by
    # more people than any one chat, and a phone number in a bio is the same
    # exit from the platform as one typed into a conversation.
    shown = "\n".join([out["display_name"], out["headline"], out["bio"]] + links)
    what = off_platform(shown)
    if what:
        raise ValueError(f"Your profile contains {what}. Readers reach you through "
                         "Altaha chats, so leave contact details out.")
    s = promise_sentence("\n".join([out["headline"], out["bio"]]))
    if s:
        raise ValueError(f"Nobody may promise returns. Rephrase: \u201c{s[:120]}\u201d")
    return out


def _slug_for(conn, name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40].strip("-")
    if not base or base in _RESERVED_SLUGS:
        base = "adviser"
    slug, n = base, 1
    while conn.execute("SELECT 1 FROM experts WHERE slug=?", (slug,)).fetchone():
        n += 1
        slug = f"{base}-{n}"
    return slug


def _online(row, now=None) -> bool:
    seen = _parse(row["last_seen"])
    return bool(row["accepting"] and seen and (now or _now()) - seen <= ONLINE_WINDOW)


def _reply_stats(conn, expert_id: int) -> dict:
    """How quickly this person usually answers a new chat, from their last
    thirty. A fact about them, not a review of them."""
    rows = conn.execute(
        "SELECT c.created_at, (SELECT MIN(m.created_at) FROM chat_messages m "
        " WHERE m.chat_id=c.id AND m.sender='expert') AS first_reply "
        "FROM chats c WHERE c.expert_id=? ORDER BY c.id DESC LIMIT 30",
        (expert_id,)).fetchall()
    waits = sorted((_parse(r["first_reply"]) - _parse(r["created_at"])).total_seconds() / 60
                   for r in rows if r["first_reply"])
    answered = conn.execute(
        "SELECT COUNT(DISTINCT chat_id) FROM chat_messages m JOIN chats c ON c.id=m.chat_id "
        "WHERE c.expert_id=? AND m.sender='expert'", (expert_id,)).fetchone()[0]
    median = waits[len(waits) // 2] if len(waits) >= 3 else None
    return {"answered": answered,
            "reply_minutes": None if median is None else max(1, round(median))}


def _public(conn, row, full: bool = False) -> dict:
    k = KINDS.get(row["kind"], KINDS["educator"])
    out = {
        "slug": row["slug"], "display_name": row["display_name"],
        "headline": row["headline"], "kind": row["kind"],
        "kind_label": k["label"], "kind_short": k["short"],
        "registered": k["registered"], "sebi_reg": row["sebi_reg"],
        "register_url": SEBI_REGISTER.get(row["kind"]),
        "topics": [{"id": t, "label": TOPIC_LABEL.get(t, t)} for t in _jl(row["topics"])],
        "languages": _jl(row["languages"]),
        "experience_years": row["experience_years"],
        "featured": bool(row["featured"]), "accepting": bool(row["accepting"]),
        "online": _online(row), "can_see_portfolio": row["kind"] == "ria",
    }
    out.update(_reply_stats(conn, row["id"]))
    if full:
        out["bio"] = row["bio"]
        out["links"] = _jl(row["links"])
    return out


def _own(conn, row) -> dict:
    """Everything the applicant typed, plus where the review stands."""
    out = _public(conn, row, full=True)
    out.update({"id": row["id"], "status": row["status"],
                "review_note": row["review_note"], "created_at": row["created_at"],
                "reviewed_at": row["reviewed_at"]})
    return out


def _expert_by_user(conn, user_id: int):
    return conn.execute("SELECT * FROM experts WHERE user_id=?", (user_id,)).fetchone()


def my_profile(user_id: int):
    conn = _conn()
    row = _expert_by_user(conn, user_id)
    return _own(conn, row) if row else None


def save_profile(user_id: int, payload: dict) -> dict:
    """Apply, or edit an application or a live profile.

    The slug is fixed at the first save, so a rename does not break a link
    somebody already shared. A change of category or registration number on
    a listed profile takes it off the list until the new number is checked:
    the number is the one thing on the page a reader relies on Altaha for.
    """
    clean = clean_profile(payload)
    conn = _conn()
    now = _iso(_now())
    row = _expert_by_user(conn, user_id)
    cols = ("display_name", "headline", "bio", "kind", "sebi_reg", "topics",
            "languages", "experience_years", "links")
    vals = (clean["display_name"], clean["headline"], clean["bio"], clean["kind"],
            clean["sebi_reg"], json.dumps(clean["topics"]), json.dumps(clean["languages"]),
            clean["experience_years"], json.dumps(clean["links"]))
    with conn:
        if row is None:
            conn.execute(
                "INSERT INTO experts(user_id,slug," + ",".join(cols) +
                ",status,created_at,updated_at,last_seen) VALUES(?,?," +
                ",".join("?" * len(cols)) + ",'pending',?,?,?)",
                (user_id, _slug_for(conn, clean["display_name"])) + vals + (now, now, now))
        else:
            status = row["status"]
            if status == "rejected" or (
                    status == "approved" and
                    (row["kind"] != clean["kind"] or row["sebi_reg"] != clean["sebi_reg"])):
                status = "pending"
            conn.execute(
                "UPDATE experts SET " + ",".join(f"{c}=?" for c in cols) +
                ",status=?,updated_at=? WHERE id=?",
                vals + (status, now, row["id"]))
    return my_profile(user_id)


def set_accepting(user_id: int, on: bool) -> dict:
    conn = _conn()
    row = _expert_by_user(conn, user_id)
    if row is None:
        raise LookupError("You do not have an adviser profile.")
    with conn:
        conn.execute("UPDATE experts SET accepting=?, last_seen=? WHERE id=?",
                     (1 if on else 0, _iso(_now()), row["id"]))
    return my_profile(user_id)


def directory(kind: str = "", topic: str = "", q: str = "") -> list:
    """Everyone listed. Featured first, then whoever is around right now."""
    conn = _conn()
    sql, args = "SELECT * FROM experts WHERE status='approved'", []
    if kind in KINDS:
        sql += " AND kind=?"
        args.append(kind)
    elif kind == "registered":
        sql += " AND kind IN ('ria','ra')"
    q = " ".join(str(q or "").split())[:60]
    if q:
        sql += " AND (display_name LIKE ? OR headline LIKE ?)"
        args += [f"%{q}%", f"%{q}%"]
    rows = conn.execute(sql + " LIMIT ?", args + [MAX_DIRECTORY]).fetchall()
    if topic in TOPIC_KINDS:
        rows = [r for r in rows if topic in _jl(r["topics"])]
    now = _now()
    # Stable sorts, least important key first: most recently seen, then
    # taking chats, then around right now, then featured.
    rows = sorted(rows, key=lambda r: r["last_seen"] or "", reverse=True)
    rows.sort(key=lambda r: (not r["featured"], not _online(r, now), not r["accepting"]))
    return [_public(conn, r) for r in rows]


def profile(slug: str):
    conn = _conn()
    row = conn.execute("SELECT * FROM experts WHERE slug=? AND status='approved'",
                       (str(slug or "")[:60],)).fetchone()
    return _public(conn, row, full=True) if row else None


# ---------------------------------------------------------------------------
# Chats
# ---------------------------------------------------------------------------

def _body(raw) -> str:
    s = str(raw or "").replace("\r\n", "\n").strip()
    if not s:
        raise ValueError("Write a message first.")
    if len(s) > MAX_MESSAGE:
        raise ValueError(f"Keep a message under {MAX_MESSAGE} characters.")
    return s


def _throttle(conn, user_id: int) -> None:
    since = _iso(_now() - dt.timedelta(minutes=1))
    n = conn.execute("SELECT COUNT(*) FROM chat_messages WHERE user_id=? AND created_at>=?",
                     (user_id, since)).fetchone()[0]
    if n >= MESSAGES_PER_MINUTE:
        raise RateLimited("That is a lot of messages in a minute. Wait a moment and send again.")


def _insert_message(conn, chat_id: int, sender: str, user_id, body: str) -> int:
    now = _iso(_now())
    cur = conn.execute(
        "INSERT INTO chat_messages(chat_id,sender,user_id,body,created_at) VALUES(?,?,?,?,?)",
        (chat_id, sender, user_id, body, now))
    mid = cur.lastrowid
    if sender == "system":
        conn.execute("UPDATE chats SET last_message_at=? WHERE id=?", (now, chat_id))
    else:
        # Your own message is one you have read.
        conn.execute(f"UPDATE chats SET last_message_at=?, {sender}_read_id=?, "
                     f"{sender}_seen_at=? WHERE id=?", (now, mid, now, chat_id))
    return mid


def _role(conn, chat, user_id: int):
    """'seeker', 'expert', or LookupError. A chat that is not yours does not
    exist, as far as the answer is concerned."""
    if chat is None:
        raise LookupError("That chat does not exist.")
    if chat["user_id"] == user_id:
        return "seeker"
    exp = conn.execute("SELECT user_id FROM experts WHERE id=?", (chat["expert_id"],)).fetchone()
    if exp and exp["user_id"] == user_id:
        return "expert"
    raise LookupError("That chat does not exist.")


def _seeker_name(raw) -> str:
    s = " ".join(str(raw or "").split())[:40]
    if s and len(s) < 2:
        raise ValueError("Use at least two characters for your name, or leave it blank.")
    if s and (off_platform(s) or "@" in s):
        raise ValueError("Use a name, not a contact detail.")
    return s or "Altaha reader"


def start_chat(user: dict, slug: str, topic: str, message: str,
               name: str = "", share_portfolio: bool = False) -> dict:
    """Open a conversation with a listed expert, or add to the open one.

    One open chat per reader per expert, like any messaging app: writing to
    somebody you are already talking to continues that conversation.
    Returns {"chat_id", "existing", "notify"}.
    """
    conn = _conn()
    exp = conn.execute("SELECT * FROM experts WHERE slug=? AND status='approved'",
                       (str(slug or "")[:60],)).fetchone()
    if exp is None:
        raise LookupError("That adviser is not listed.")
    if exp["user_id"] == user["id"]:
        raise ValueError("That is your own profile.")
    body = _body(message)
    check_message(body, "seeker", exp["kind"])
    share = bool(share_portfolio)
    if share and exp["kind"] != "ria":
        raise ValueError("Only a SEBI-registered investment adviser can see a shared portfolio.")

    # A block on any chat holds, not only on the latest one.
    if conn.execute("SELECT 1 FROM chats WHERE expert_id=? AND user_id=? AND blocked=1",
                    (exp["id"], user["id"])).fetchone():
        raise PermissionError("This adviser is not taking messages from you.")
    prior = conn.execute(
        "SELECT * FROM chats WHERE expert_id=? AND user_id=? ORDER BY id DESC LIMIT 1",
        (exp["id"], user["id"])).fetchone()
    if prior is not None and prior["status"] == "open":
        notify = send_message(user, prior["id"], body)["notify"]
        if share and not prior["share_portfolio"]:
            set_share(user, prior["id"], True)
        return {"chat_id": prior["id"], "existing": True, "notify": notify}

    if not exp["accepting"]:
        raise PermissionError(f"{exp['display_name']} is not taking new chats right now.")
    topic = str(topic or "")
    if topic not in _jl(exp["topics"]):
        raise ValueError("Pick one of the topics this person takes questions on.")
    since = _iso(_now() - dt.timedelta(days=1))
    started = conn.execute("SELECT COUNT(*) FROM chats WHERE user_id=? AND created_at>=?",
                           (user["id"], since)).fetchone()[0]
    if started >= NEW_CHATS_PER_DAY:
        raise RateLimited(f"You can start {NEW_CHATS_PER_DAY} new chats a day. "
                          "Carry on in the ones you have, or try again tomorrow.")
    _throttle(conn, user["id"])
    seeker = _seeker_name(name)
    now = _iso(_now())
    with conn:
        cur = conn.execute(
            "INSERT INTO chats(expert_id,user_id,topic,seeker_name,share_portfolio,"
            "created_at,last_message_at) VALUES(?,?,?,?,?,?,?)",
            (exp["id"], user["id"], topic, seeker, 1 if share else 0, now, now))
        chat_id = cur.lastrowid
        _insert_message(conn, chat_id, "seeker", user["id"], body)
        if share:
            _insert_message(conn, chat_id, "system", None,
                            _shared_line(seeker, exp["display_name"], user["id"]))
    chat = conn.execute("SELECT * FROM chats WHERE id=?", (chat_id,)).fetchone()
    return {"chat_id": chat_id, "existing": False,
            "notify": _claim_notice(conn, chat, "expert")}


def send_message(user: dict, chat_id: int, body) -> dict:
    """Add a message. Returns {"message", "notify"} — notify is who to email,
    or None; the caller sends it after the response so a slow mail provider
    never holds up a chat."""
    conn = _conn()
    chat = conn.execute("SELECT * FROM chats WHERE id=?", (int(chat_id),)).fetchone()
    role = _role(conn, chat, user["id"])
    if chat["status"] != "open":
        raise PermissionError("This chat is closed.")
    exp = conn.execute("SELECT * FROM experts WHERE id=?", (chat["expert_id"],)).fetchone()
    if exp["status"] != "approved":
        raise PermissionError("This adviser is no longer listed, so the chat is read-only.")
    text = _body(body)
    check_message(text, role, exp["kind"])
    _throttle(conn, user["id"])
    with conn:
        mid = _insert_message(conn, chat["id"], role, user["id"], text)
        if role == "expert":
            conn.execute("UPDATE experts SET last_seen=? WHERE id=?", (_iso(_now()), exp["id"]))
    msg = conn.execute("SELECT * FROM chat_messages WHERE id=?", (mid,)).fetchone()
    chat = conn.execute("SELECT * FROM chats WHERE id=?", (chat["id"],)).fetchone()
    other = "expert" if role == "seeker" else "seeker"
    return {"message": _msg(msg), "notify": _claim_notice(conn, chat, other)}


def _claim_notice(conn, chat, recipient: str):
    """Whether to email the other side about this message, and to whom.

    One email per unread stretch: none while they have the chat open, one
    when they have been away, and no more until they come back and read it.
    Claimed here, inside the request, so two quick messages cannot both
    decide to send.
    """
    now = _now()
    seen = _parse(chat[f"{recipient}_seen_at"])
    if seen and now - seen < NOTIFY_IF_UNSEEN_FOR:
        return None
    notified = _parse(chat[f"{recipient}_notified_at"])
    if notified and (seen is None or notified >= seen):
        return None
    with conn:
        claimed = conn.execute(
            f"UPDATE chats SET {recipient}_notified_at=? WHERE id=? AND "
            f"({recipient}_notified_at IS NULL OR {recipient}_notified_at=?)",
            (_iso(now), chat["id"], chat[f"{recipient}_notified_at"]))
    if claimed.rowcount != 1:
        return None
    exp = conn.execute("SELECT * FROM experts WHERE id=?", (chat["expert_id"],)).fetchone()
    uid = chat["user_id"] if recipient == "seeker" else exp["user_id"]
    u = conn.execute("SELECT email FROM users WHERE id=?", (uid,)).fetchone()
    if not u:
        return None
    return {"email": u["email"], "chat_id": chat["id"], "recipient": recipient,
            "from_name": exp["display_name"] if recipient == "seeker" else chat["seeker_name"],
            "topic": TOPIC_LABEL.get(chat["topic"], chat["topic"]),
            "new_chat": recipient == "expert" and chat["expert_read_id"] == 0}


def _msg(row) -> dict:
    return {"id": row["id"], "sender": row["sender"], "body": row["body"],
            "created_at": row["created_at"]}


def _shared_line(seeker: str, expert: str, user_id: int) -> str:
    """The system line both sides see, naming only what actually exists."""
    what = "saved portfolio and risk profile" if accounts.latest_risk_profile(user_id) \
        else "saved portfolio"
    return f"{seeker} shared their {what} with {expert}."


def _shared_context(conn, chat) -> dict:
    """What the reader agreed to show their adviser: the portfolio saved to
    their account and their latest risk profile. Read live, so withdrawing
    consent — or editing the portfolio — takes effect on the next poll."""
    holdings = accounts.get_holdings(chat["user_id"])
    risk = accounts.latest_risk_profile(chat["user_id"])
    return {"holdings": holdings,
            "risk_profile": None if not risk else {
                k: risk[k] for k in ("band", "score", "capacity", "tolerance", "assessed_at")}}


def chat_view(user: dict, chat_id: int, after: int = 0) -> dict:
    """One chat, from the reader's or the expert's side. Messages after
    `after` only, so a poll returns nothing when nothing has happened."""
    conn = _conn()
    chat = conn.execute("SELECT * FROM chats WHERE id=?", (int(chat_id),)).fetchone()
    role = _role(conn, chat, user["id"])
    other = "expert" if role == "seeker" else "seeker"
    exp = conn.execute("SELECT * FROM experts WHERE id=?", (chat["expert_id"],)).fetchone()
    after = max(0, int(after or 0))
    if after:
        rows = conn.execute(
            "SELECT * FROM chat_messages WHERE chat_id=? AND id>? ORDER BY id LIMIT ?",
            (chat["id"], after, PAGE)).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM (SELECT * FROM chat_messages WHERE chat_id=? ORDER BY id DESC LIMIT ?) "
            "ORDER BY id", (chat["id"], PAGE)).fetchall()

    now = _now()
    last = rows[-1]["id"] if rows else 0
    seen = _parse(chat[f"{role}_seen_at"])
    stale = seen is None or now - seen >= TOUCH_EVERY
    if last > chat[f"{role}_read_id"] or stale:
        with conn:
            conn.execute(f"UPDATE chats SET {role}_read_id=MAX({role}_read_id, ?), "
                         f"{role}_seen_at=? WHERE id=?", (last, _iso(now), chat["id"]))
            if role == "expert":
                conn.execute("UPDATE experts SET last_seen=? WHERE id=?", (_iso(now), exp["id"]))

    out = {
        "id": chat["id"], "role": role, "topic": chat["topic"],
        "topic_label": TOPIC_LABEL.get(chat["topic"], chat["topic"]),
        "status": chat["status"], "closed_by": chat["closed_by"],
        "blocked": bool(chat["blocked"]),
        "share_portfolio": bool(chat["share_portfolio"]),
        "read_only": chat["status"] != "open" or exp["status"] != "approved",
        "messages": [_msg(r) for r in rows],
        "their_read_id": chat[f"{other}_read_id"],
        "created_at": chat["created_at"],
        "expert": _public(conn, exp),
        "seeker_name": chat["seeker_name"],
    }
    if role == "expert" and chat["share_portfolio"] and exp["kind"] == "ria":
        out["shared"] = _shared_context(conn, chat)
    return out


def _summary(conn, chat, role: str, exp) -> dict:
    last = conn.execute("SELECT * FROM chat_messages WHERE chat_id=? ORDER BY id DESC LIMIT 1",
                        (chat["id"],)).fetchone()
    mine = "seeker" if role == "seeker" else "expert"
    unread = conn.execute(
        "SELECT COUNT(*) FROM chat_messages WHERE chat_id=? AND id>? AND sender NOT IN (?, 'system')",
        (chat["id"], chat[f"{mine}_read_id"], mine)).fetchone()[0]
    return {
        "id": chat["id"], "topic": chat["topic"],
        "topic_label": TOPIC_LABEL.get(chat["topic"], chat["topic"]),
        "status": chat["status"], "last_message_at": chat["last_message_at"],
        "preview": (last["body"][:140] if last else ""),
        "preview_from": last["sender"] if last else None,
        "unread": unread,
        "with": (chat["seeker_name"] if role == "expert" else exp["display_name"]),
        "expert_slug": exp["slug"], "expert_kind": exp["kind"],
        "online": _online(exp) if role == "seeker" else None,
    }


def my_chats(user: dict) -> dict:
    """Both inboxes: the chats this person started, and — if they are an
    expert — the chats people started with them."""
    conn = _conn()
    seeking = conn.execute(
        "SELECT c.*, e.id AS eid FROM chats c JOIN experts e ON e.id=c.expert_id "
        "WHERE c.user_id=? ORDER BY c.last_message_at DESC LIMIT 100", (user["id"],)).fetchall()
    experts = {}

    def exp_row(eid):
        if eid not in experts:
            experts[eid] = conn.execute("SELECT * FROM experts WHERE id=?", (eid,)).fetchone()
        return experts[eid]

    out = {"as_seeker": [_summary(conn, c, "seeker", exp_row(c["eid"])) for c in seeking],
           "as_expert": None, "expert": None}
    me = _expert_by_user(conn, user["id"])
    if me is not None:
        rows = conn.execute("SELECT * FROM chats WHERE expert_id=? "
                            "ORDER BY last_message_at DESC LIMIT 200", (me["id"],)).fetchall()
        out["as_expert"] = [_summary(conn, c, "expert", me) for c in rows]
        seen = _parse(me["last_seen"])
        if seen is None or _now() - seen >= TOUCH_EVERY:
            with conn:
                conn.execute("UPDATE experts SET last_seen=? WHERE id=?", (_iso(_now()), me["id"]))
        out["expert"] = {"slug": me["slug"], "status": me["status"],
                         "accepting": bool(me["accepting"]),
                         "display_name": me["display_name"]}
    out["unread"] = sum(c["unread"] for c in out["as_seeker"]) + \
        sum(c["unread"] for c in (out["as_expert"] or []))
    return out


def unread_count(user: dict) -> int:
    return my_chats(user)["unread"]


def close_chat(user: dict, chat_id: int, block: bool = False) -> dict:
    """Either side can end a chat. Only the expert can block — a reader who
    wants nothing more to do with somebody simply stops writing."""
    conn = _conn()
    chat = conn.execute("SELECT * FROM chats WHERE id=?", (int(chat_id),)).fetchone()
    role = _role(conn, chat, user["id"])
    if block and role != "expert":
        raise PermissionError("Only the adviser can block.")
    was_open = chat["status"] == "open"
    if not was_open and not (block and not chat["blocked"]):
        return chat_view(user, chat_id)
    who = chat["seeker_name"] if role == "seeker" else \
        conn.execute("SELECT display_name FROM experts WHERE id=?",
                     (chat["expert_id"],)).fetchone()[0]
    with conn:
        conn.execute("UPDATE chats SET status='closed', closed_by=COALESCE(closed_by, ?), "
                     "blocked=MAX(blocked, ?) WHERE id=?", (role, 1 if block else 0, chat["id"]))
        if was_open:
            _insert_message(conn, chat["id"], "system", None, f"{who} closed this chat.")
    return chat_view(user, chat_id)


def set_share(user: dict, chat_id: int, share: bool) -> dict:
    """The reader, and only the reader, decides whether their portfolio is
    visible — and can take it back at any point."""
    conn = _conn()
    chat = conn.execute("SELECT * FROM chats WHERE id=?", (int(chat_id),)).fetchone()
    if _role(conn, chat, user["id"]) != "seeker":
        raise PermissionError("Only the person who shared the portfolio can change that.")
    exp = conn.execute("SELECT * FROM experts WHERE id=?", (chat["expert_id"],)).fetchone()
    if share and exp["kind"] != "ria":
        raise ValueError("Only a SEBI-registered investment adviser can see a shared portfolio.")
    if bool(chat["share_portfolio"]) != bool(share):
        with conn:
            conn.execute("UPDATE chats SET share_portfolio=? WHERE id=?",
                         (1 if share else 0, chat["id"]))
            _insert_message(conn, chat["id"], "system", None,
                            _shared_line(chat["seeker_name"], exp["display_name"], chat["user_id"])
                            if share else
                            f"{chat['seeker_name']} stopped sharing their portfolio.")
    return chat_view(user, chat_id)


def report_chat(user: dict, chat_id: int, reason: str) -> dict:
    conn = _conn()
    chat = conn.execute("SELECT * FROM chats WHERE id=?", (int(chat_id),)).fetchone()
    role = _role(conn, chat, user["id"])
    why = " ".join(str(reason or "").split())
    if len(why) < 5:
        raise ValueError("Say in a few words what happened.")
    with conn:
        conn.execute(
            "INSERT INTO chat_reports(chat_id,reporter,reason,created_at) VALUES(?,?,?,?) "
            "ON CONFLICT(chat_id,reporter) DO UPDATE SET reason=excluded.reason, "
            "created_at=excluded.created_at",
            (chat["id"], role, why[:500], _iso(_now())))
    return {"reported": True}


# ---------------------------------------------------------------------------
# The owner's side
# ---------------------------------------------------------------------------

REVIEW_ACTIONS = ("approve", "reject", "suspend", "feature", "unfeature")


def applications(status: str = "") -> dict:
    """Every profile with the applicant's address, for review. Personal data:
    the route that serves this is closed when ADMIN_KEY is unset."""
    conn = _conn()
    sql = ("SELECT e.*, u.email FROM experts e JOIN users u ON u.id=e.user_id")
    args = []
    if status in STATUSES:
        sql += " WHERE e.status=?"
        args.append(status)
    rows = conn.execute(sql + " ORDER BY e.status='pending' DESC, e.created_at DESC",
                        args).fetchall()
    people = []
    for r in rows:
        d = _own(conn, r)
        d["email"] = r["email"]
        people.append(d)
    counts = {s: conn.execute("SELECT COUNT(*) FROM experts WHERE status=?", (s,)).fetchone()[0]
              for s in STATUSES}
    return {"counts": counts, "experts": people,
            "chats": conn.execute("SELECT COUNT(*) FROM chats").fetchone()[0],
            "messages": conn.execute("SELECT COUNT(*) FROM chat_messages").fetchone()[0],
            "open_reports": conn.execute("SELECT COUNT(*) FROM chat_reports").fetchone()[0]}


def review(expert_id: int, action: str, note: str = "") -> dict:
    if action not in REVIEW_ACTIONS:
        raise ValueError("action must be one of: " + ", ".join(REVIEW_ACTIONS))
    conn = _conn()
    row = conn.execute("SELECT * FROM experts WHERE id=?", (int(expert_id),)).fetchone()
    if row is None:
        raise LookupError("No such profile.")
    now = _iso(_now())
    note = " ".join(str(note or "").split())[:500] or None
    with conn:
        if action in ("feature", "unfeature"):
            conn.execute("UPDATE experts SET featured=? WHERE id=?",
                         (1 if action == "feature" else 0, row["id"]))
        else:
            status = {"approve": "approved", "reject": "rejected", "suspend": "suspended"}[action]
            conn.execute("UPDATE experts SET status=?, review_note=?, reviewed_at=? WHERE id=?",
                         (status, note, now, row["id"]))
    r = conn.execute("SELECT e.*, u.email FROM experts e JOIN users u ON u.id=e.user_id "
                     "WHERE e.id=?", (row["id"],)).fetchone()
    d = _own(conn, r)
    d["email"] = r["email"]
    return d


def reports() -> list:
    """Reported chats, newest first, with the conversation — the owner cannot
    judge a report without reading what was said."""
    conn = _conn()
    out = []
    for r in conn.execute("SELECT * FROM chat_reports ORDER BY id DESC LIMIT 100").fetchall():
        chat = conn.execute("SELECT * FROM chats WHERE id=?", (r["chat_id"],)).fetchone()
        if chat is None:
            continue
        exp = conn.execute("SELECT * FROM experts WHERE id=?", (chat["expert_id"],)).fetchone()
        msgs = conn.execute("SELECT * FROM chat_messages WHERE chat_id=? ORDER BY id DESC LIMIT 60",
                            (chat["id"],)).fetchall()
        out.append({"id": r["id"], "chat_id": chat["id"], "reporter": r["reporter"],
                    "reason": r["reason"], "created_at": r["created_at"],
                    "expert": {"id": exp["id"], "display_name": exp["display_name"],
                               "slug": exp["slug"], "status": exp["status"]},
                    "seeker_name": chat["seeker_name"],
                    "messages": [_msg(m) for m in reversed(msgs)]})
    return out


# ---------------------------------------------------------------------------
# The notification email
#
# The message itself is NOT in the email. These are conversations about
# somebody's money; an inbox is synced, forwarded and read over shoulders, and
# the mail provider is a third party. The email says who wrote and where to
# read it, and nothing else.
# ---------------------------------------------------------------------------

def notice_email(notice: dict, site: str) -> tuple:
    """(subject, html, text) for a notify dict from send_message/start_chat."""
    from html import escape
    link = f"{site.rstrip('/')}/advisors.html#chat/{notice['chat_id']}"
    who = notice["from_name"]
    if notice.get("new_chat"):
        subject = f"New chat on Altaha: {who} asked about {notice['topic'].lower()}"
        lead = f"{who} started a chat with you about {notice['topic'].lower()}."
    else:
        subject = f"{who} replied to you on Altaha"
        lead = f"{who} sent you a message about {notice['topic'].lower()}."
    after = ("You will not get another email about this chat until you have "
             "opened it.")
    html = f"""<!doctype html><html><body style="margin:0;background:#faf9f7">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#faf9f7">
<tr><td align="center" style="padding:28px 12px">
<table width="480" cellpadding="0" cellspacing="0" style="max-width:480px;width:100%;
background:#fff;border:1px solid #e4e2dd">
<tr><td style="padding:30px 28px">
<div style="font:400 11px Arial,sans-serif;color:#6b6b6b;letter-spacing:2px;
text-transform:uppercase;padding-bottom:22px">Altaha Screener · Advisors</div>
<p style="font:400 15px Arial,sans-serif;color:#1a1a1a;margin:0 0 20px">{escape(lead)}</p>
<a href="{escape(link)}" style="font:600 14px Arial,sans-serif;color:#fff;background:#1a1a1a;
padding:13px 22px;text-decoration:none;display:inline-block">Read and reply</a>
<p style="font:400 12px Arial,sans-serif;color:#6b6b6b;margin:22px 0 0;
border-top:1px solid #e4e2dd;padding-top:16px;line-height:1.6">
The message is not in this email, on purpose: conversations about money stay on
Altaha. {escape(after)} Altaha never asks for payment, an OTP or a password.</p>
</td></tr></table></td></tr></table></body></html>"""
    text = (f"{lead}\n\nRead and reply:\n{link}\n\n"
            "The message is not in this email, on purpose: conversations about "
            f"money stay on Altaha. {after} Altaha never asks for payment, an OTP "
            "or a password.")
    return subject, html, text
