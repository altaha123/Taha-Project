"""
The forum: investors talking to each other, about the market and about one
stock at a time.

ONE FORUM, TWO WAYS IN
Every conversation is a thread in a category. One category is special:
"Stocks" threads carry the company's symbol, and the company's own page
(stock.html, the Discussion section) lists them. So "the stock discussion
forum" is not a second forum; it is this one, read one company at a time,
and a thread started from a stock page is also on the forum's front page.

WHO CAN DO WHAT
Anyone can read. Posting needs an account and a forum name: the email
address is never shown to anybody, so a member picks the name the forum
sees, once, before their first post. A banned member can still read.

THE HOUSE RULES ARE CHECKED BEFORE A POST IS SAVED
Three things are refused outright, each with the sentence that tripped it so
the writer can see what to change:

  contact details   phone numbers, UPI addresses, email addresses, WhatsApp
                    and Telegram links. Moving a conversation off the site is
                    how the investment scams that end in a fake trading app
                    begin (advisors.off_platform, the same check the adviser
                    chats use).
  promised returns  "guaranteed returns", "sure shot", "double your money"
                    (promise_sentence below; narrower than the adviser
                    chats' check, so "credit guarantee scheme" passes).
  tips              a price to buy or sell at, a target, a stop-loss level.
                    Those are what a stock tip is made of, and publishing one
                    is a SEBI-registered research analyst's licence. Opinions
                    and reasons are welcome; "I bought at 450 in 2021" is a
                    fact about the writer and passes; "buy at 450, target
                    520" does not. A question is never a tip, and a negation
                    before the level ("I would not buy at 450") passes, by the
                    same sentence rule the adviser chats use.

None of this makes Altaha the author of what members write. The page says
so, and every thread carries the line.

REPORTS, AND WHAT HAPPENS WITHOUT THE OWNER
Any member can report a post, once. At HIDE_AFTER_REPORTS distinct reports
the post is hidden until the owner looks at it, so a scam posted at night
does not stay up until morning. The owner can hide, restore, lock, pin and
ban from /admin/forum. Hidden posts are kept, never deleted, so a decision
can be reviewed; a member deleting their own post replaces what the public
sees with "removed by the author" and keeps the row for the same reason.

WHY POLLING-FREE
A forum is read at the pace of a reply, not of a chat. Every read is one or
two indexed SQLite queries; nothing holds a thread open.

WHY THE ACCOUNTS DATABASE
Every row belongs to an account, the backup already copies that file, and a
ban has to find the person. As advisors.py does, the statements live here so
the feature reads in one place.
"""
from __future__ import annotations

import datetime as dt
import re
import threading

import accounts
import advisors

# ---------------------------------------------------------------------------
# The vocabulary
# ---------------------------------------------------------------------------

# id, label, one line. "stocks" is the one whose threads carry a symbol.
CATEGORIES = [
    ("stocks", "Stocks", "One company at a time: results, management, the business"),
    ("market", "Market & economy", "Indices, sectors, flows, rates and the budget"),
    ("strategy", "Investing & trading", "How you pick, size, hold and sell"),
    ("funds", "Mutual funds & ETFs", "Schemes, SIPs, index funds and costs"),
    ("tax", "Tax & personal finance", "Capital gains, ITR, insurance and planning"),
    ("beginners", "Beginners", "No question is too basic here"),
    ("altaha", "Using Altaha", "Feedback, ideas and questions about the site"),
]
CATEGORY_LABEL = {c: label for c, label, _ in CATEGORIES}

SORTS = ("latest", "new", "top")

HOUSE_RULES = [
    "Share reasons, not tips: no prices to buy or sell at, no targets, no stop-loss levels.",
    "Nobody may promise returns.",
    "Keep it here: no phone numbers, payment addresses, emails, WhatsApp or Telegram links.",
    "Disagree with the idea, not the person.",
    "Say if you own the stock you are writing about.",
]

DISCLAIMER = (
    "Posts are written by members and are their own opinions. Altaha does not check "
    "them, does not agree or disagree with them, and is not registered with SEBI as "
    "an adviser or research analyst. Nothing here is advice to buy or sell. Never pay "
    "anyone you meet here and never share an OTP, password or demat login."
)

# ---------------------------------------------------------------------------
# Limits
# ---------------------------------------------------------------------------

TITLE_MIN, TITLE_MAX = 8, 140
OPENING_MIN, BODY_MAX = 20, 5000
REPLY_MIN = 2
HANDLE_MIN, HANDLE_MAX = 3, 24
MAX_LINKS = 3
THREADS_PER_DAY = 5           # per member
POSTS_PER_MINUTE = 4          # per member, threads and replies together
POSTS_PER_DAY = 80
HIDE_AFTER_REPORTS = 3
PAGE = 30                     # threads per page
POSTS_PAGE = 200              # posts returned per thread
REPORT_MAX = 300


class RateLimited(Exception):
    """Too much, too fast. A 429, with a sentence."""


class PostRefused(ValueError):
    """A post that cannot be saved as written, with the sentence that
    tripped the check."""

    def __init__(self, message: str, sentence: str = "", rule: str = ""):
        super().__init__(message)
        self.sentence = sentence
        self.rule = rule                  # contact | promise | tip | links


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

SCHEMA = """
-- A member's public name. The email is never shown; handle_key is the name
-- folded for uniqueness, so "Value Hunter" and "value hunter" are one name.
CREATE TABLE IF NOT EXISTS forum_members (
  user_id     INTEGER PRIMARY KEY,
  handle      TEXT NOT NULL,
  handle_key  TEXT NOT NULL UNIQUE,
  status      TEXT NOT NULL DEFAULT 'active',     -- active | banned
  status_note TEXT,
  created_at  TEXT NOT NULL,
  updated_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS forum_threads (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  category     TEXT NOT NULL,
  symbol       TEXT,                               -- stocks only
  company      TEXT,                               -- the server's name for it
  title        TEXT NOT NULL,
  user_id      INTEGER NOT NULL,
  created_at   TEXT NOT NULL,
  last_post_at TEXT NOT NULL,
  replies      INTEGER NOT NULL DEFAULT 0,         -- visible replies, not counting the opening post
  last_post_id INTEGER NOT NULL DEFAULT 0,         -- orders "latest": ids rise, timestamps tie within a second
  status       TEXT NOT NULL DEFAULT 'open',       -- open | locked | hidden
  pinned       INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_fthreads_last ON forum_threads(status, last_post_id);
CREATE INDEX IF NOT EXISTS idx_fthreads_cat ON forum_threads(category, last_post_at);
CREATE INDEX IF NOT EXISTS idx_fthreads_sym ON forum_threads(symbol, last_post_at);
CREATE INDEX IF NOT EXISTS idx_fthreads_user ON forum_threads(user_id, created_at);
CREATE TABLE IF NOT EXISTS forum_posts (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  thread_id  INTEGER NOT NULL,
  user_id    INTEGER NOT NULL,
  body       TEXT NOT NULL,
  created_at TEXT NOT NULL,
  status     TEXT NOT NULL DEFAULT 'visible',      -- visible | removed | hidden
  hidden_by  TEXT,                                 -- owner | reports
  helpful    INTEGER NOT NULL DEFAULT 0,
  reports    INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_fposts_thread ON forum_posts(thread_id, id);
CREATE INDEX IF NOT EXISTS idx_fposts_user ON forum_posts(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_fposts_time ON forum_posts(created_at);
CREATE TABLE IF NOT EXISTS forum_votes (
  post_id    INTEGER NOT NULL,
  user_id    INTEGER NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY (post_id, user_id)
);
CREATE TABLE IF NOT EXISTS forum_reports (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  post_id     INTEGER NOT NULL,
  user_id     INTEGER NOT NULL,
  reason      TEXT NOT NULL,
  created_at  TEXT NOT NULL,
  resolved_at TEXT,
  UNIQUE (post_id, user_id)
);
"""

_local = threading.local()


def _conn():
    """The accounts connection for this thread, with this module's tables.
    Applied per connection object, because accounts.reset_for_tests swaps
    the connection out from under every module that shares it."""
    conn = accounts._connect()
    if getattr(_local, "ready", None) is not conn:
        conn.executescript(SCHEMA)
        _local.ready = conn
    return conn


_now = accounts._now
_iso = accounts._iso


# ---------------------------------------------------------------------------
# What may be said
# ---------------------------------------------------------------------------

# A price: "450", "₹1,250.50", "Rs. 300". Not a percentage: "a stop-loss of
# 8%" is how somebody manages risk, not a level for anybody else to trade at.
_LEVEL = r"(?:₹|rs\.?|inr)?\s*\d[\d,]*(?:\.\d+)?(?![\d.,]*\s*(?:%|percent|per\s*cent))"
_TIP = re.compile(
    r"(?:"
    # target 520 / price target of ₹520 / targets 520, 560 / tgt 520
    r"\b(?:price\s+)?(?:targets?|tgts?)(?:\s+price)?\s*(?:of|is|at|=|:|-|–|around|near)?\s*" + _LEVEL +
    # stop loss at 430 / stoploss: 430 / SL 430 / sl below 430
    r"|\bstop[\s-]?loss(?:es)?\b[^.\n\d%]{0,16}?" + _LEVEL +
    r"|\bsl\b\s*(?:at|is|of|below|above|=|:|-|–)?\s*" + _LEVEL +
    # buy at 450 / sell above 1200 / accumulate below 500 / entry 450-460 /
    # exit @ 520 / buy HDFC Bank at 1650: up to three words of a name may sit
    # between the verb and the level. Not "from" or "over": "the promoter's
    # exit from 2019" and "sell over 1,000 shares" are not tips.
    r"|\b(?:buy|sell|short|accumulate|add|entry|enter|exit|book\s+(?:profits?|gains?))"
    r"(?:\s+(?!(?:at|above|below|around|near|between|under)\b)[A-Za-z][\w&.\-]*){0,3}?"
    r"\s*(?:at|above|below|around|near|between|under|@|in\s+the\s+range(?:\s+of)?|range|zone|level|price|:)\s*"
    + _LEVEL +
    r")", re.I)

_URL = re.compile(r"https?://\S+", re.I)

# A promise of returns. Narrower than the adviser chats' check, because the
# forum and the brief discuss policy and finance in their own words: the
# "credit guarantee scheme" is a government scheme and the "risk-free rate"
# is a textbook term, and neither is a promise. A guarantee counts only next
# to returns, profit or a percentage.
_GAIN = r"(?:returns?|profits?|gains?|income|money|multibaggers?|doubl\w*|\d+(?:\.\d+)?\s*%)"
_PROMISE = re.compile(
    r"\b(?:guarantee(?:d|s)?\s+(?:[\w%₹,.]+\s+){0,3}?" + _GAIN +
    r"|" + _GAIN + r"\s+(?:(?:are|is|will\s+be)\s+)?(?:guaranteed|assured)"
    r"|assured\s+(?:returns?|profits?|gains?|income)"
    r"|sure[\s-]?shot"
    r"|risk[\s-]?free\s+(?:returns?|profits?|gains?|trades?|money)"
    r"|double\s+your\s+money"
    r"|100%\s+(?:safe|sure|returns?|profit))", re.I)


def promise_sentence(text: str):
    """The first sentence that promises a return."""
    return advisors._tripping(_PROMISE, text)


def tip_sentence(text: str):
    """The first sentence that reads as a tip: a level to trade at."""
    return advisors._tripping(_TIP, text)


def check_post(text: str) -> None:
    """Raise PostRefused when this cannot be posted as written."""
    what = advisors.off_platform(text)
    if what:
        raise PostRefused(
            f"This contains {what}, so it was not posted. Keep the conversation "
            "here: moving it to a phone, a payment app or a private group is how "
            "investment scams start.", rule="contact")
    s = promise_sentence(text)
    if s:
        raise PostRefused("Nobody may promise returns here. Rephrase the sentence below.", s, "promise")
    s = tip_sentence(text)
    if s:
        raise PostRefused(
            "A price to buy or sell at, a target or a stop-loss level is what a stock "
            "tip is made of, and only a SEBI-registered research analyst may publish "
            "one. Share your reasoning and leave the levels out.", s, "tip")
    if len(_URL.findall(text or "")) > MAX_LINKS:
        raise PostRefused(f"Keep it to {MAX_LINKS} links in a post.", rule="links")


def _clean_body(raw, lo: int) -> str:
    s = str(raw or "").replace("\r\n", "\n").replace("\r", "\n")
    s = re.sub(r"[ \t]+\n", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s).strip()
    if len(s) < lo:
        raise ValueError(f"Write at least {lo} characters.")
    if len(s) > BODY_MAX:
        raise ValueError(f"Keep a post under {BODY_MAX:,} characters.")
    return s


def _clean_title(raw) -> str:
    s = " ".join(str(raw or "").split())
    if len(s) < TITLE_MIN:
        raise ValueError(f"A title needs at least {TITLE_MIN} characters.")
    if len(s) > TITLE_MAX:
        raise ValueError(f"Keep the title under {TITLE_MAX} characters.")
    if s.upper() == s and sum(c.isalpha() for c in s) > 10:
        raise ValueError("Please write the title in ordinary case, not all capitals.")
    return s


# ---------------------------------------------------------------------------
# Members
# ---------------------------------------------------------------------------

_HANDLE = re.compile(r"^[^\W_][\w .'-]*[^\W_]$", re.U)
_RESERVED = ("altaha", "admin", "moderator", "official", "sebi", "support", "staff")


def handle_key(handle: str) -> str:
    return re.sub(r"[\s._'-]+", "", str(handle or "")).lower()


def clean_handle(raw) -> str:
    s = " ".join(str(raw or "").split())
    if len(s) < HANDLE_MIN or len(s) > HANDLE_MAX:
        raise ValueError(f"A forum name is {HANDLE_MIN} to {HANDLE_MAX} characters.")
    if not _HANDLE.match(s):
        raise ValueError("Use letters, numbers, spaces, dots or dashes, starting and "
                         "ending with a letter or number.")
    if "@" in s or re.search(r"\d{6,}", s):
        raise ValueError("A forum name cannot be an email address or a phone number.")
    key = handle_key(s)
    if any(r in key for r in _RESERVED):
        raise ValueError("That name could be mistaken for Altaha or a regulator. Pick another.")
    return s


def member(user_id: int):
    row = _conn().execute("SELECT * FROM forum_members WHERE user_id=?", (user_id,)).fetchone()
    if row is None:
        return None
    return {"handle": row["handle"], "status": row["status"],
            "since": row["created_at"][:10]}


def set_handle(user_id: int, raw) -> dict:
    """Choose, or change, the name the forum shows."""
    handle = clean_handle(raw)
    key = handle_key(handle)
    conn = _conn()
    taken = conn.execute("SELECT user_id FROM forum_members WHERE handle_key=?", (key,)).fetchone()
    if taken and taken["user_id"] != user_id:
        raise ValueError("Somebody already uses that name. Pick another.")
    now = _iso(_now())
    with conn:
        conn.execute(
            "INSERT INTO forum_members(user_id,handle,handle_key,created_at,updated_at) "
            "VALUES(?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET "
            "handle=excluded.handle, handle_key=excluded.handle_key, updated_at=excluded.updated_at",
            (user_id, handle, key, now, now))
    return member(user_id)


def _poster(user_id: int) -> dict:
    """The member about to write, or the reason they cannot."""
    m = member(user_id)
    if m is None:
        raise PermissionError("Choose a forum name before your first post.")
    if m["status"] == "banned":
        raise PermissionError("This account can no longer post on the forum.")
    return m


def _rate(user_id: int, new_thread: bool) -> None:
    conn = _conn()
    now = _now()
    minute = _iso(now - dt.timedelta(minutes=1))
    day = _iso(now - dt.timedelta(days=1))
    n_min = conn.execute("SELECT COUNT(*) FROM forum_posts WHERE user_id=? AND created_at>?",
                         (user_id, minute)).fetchone()[0]
    if n_min >= POSTS_PER_MINUTE:
        raise RateLimited("That is a lot of posts in a minute. Wait a moment and try again.")
    n_day = conn.execute("SELECT COUNT(*) FROM forum_posts WHERE user_id=? AND created_at>?",
                         (user_id, day)).fetchone()[0]
    if n_day >= POSTS_PER_DAY:
        raise RateLimited(f"You can post {POSTS_PER_DAY} times a day. Come back tomorrow.")
    if new_thread:
        n = conn.execute("SELECT COUNT(*) FROM forum_threads WHERE user_id=? AND created_at>?",
                         (user_id, day)).fetchone()[0]
        if n >= THREADS_PER_DAY:
            raise RateLimited(f"You can start {THREADS_PER_DAY} new discussions a day. "
                              "Reply to one that is already going, or come back tomorrow.")


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------

def start_thread(user: dict, category, title, body, symbol=None, known=None) -> dict:
    """Open a discussion. `known(symbol)` is the server's record of a
    company ({"name": ...}) or None; a stock thread for a company the server
    has never heard of is refused, so the stock pages only list real ones."""
    cat = str(category or "").strip().lower()
    if cat not in CATEGORY_LABEL:
        raise ValueError("Choose where this discussion belongs.")
    sym, company = None, None
    if cat == "stocks":
        sym = accounts._clean_symbol(symbol)
        if not sym:
            raise ValueError("Name the stock this discussion is about, by its NSE symbol.")
        if known is not None:
            rec = known(sym)
            if not rec:
                raise ValueError(f"{sym} is not a company Altaha knows. Check the symbol.")
            company = (rec.get("name") or None) if isinstance(rec, dict) else None
    elif symbol:
        sym = accounts._clean_symbol(symbol) or None
        if sym and known is not None:
            rec = known(sym)
            if not rec:
                sym = None
            else:
                company = (rec.get("name") or None) if isinstance(rec, dict) else None
    t = _clean_title(title)
    b = _clean_body(body, OPENING_MIN)
    check_post(t)
    check_post(b)
    _poster(user["id"])
    _rate(user["id"], True)
    now = _iso(_now())
    conn = _conn()
    with conn:
        cur = conn.execute(
            "INSERT INTO forum_threads(category,symbol,company,title,user_id,created_at,last_post_at) "
            "VALUES(?,?,?,?,?,?,?)", (cat, sym, company, t, user["id"], now, now))
        tid = cur.lastrowid
        pid = conn.execute("INSERT INTO forum_posts(thread_id,user_id,body,created_at) VALUES(?,?,?,?)",
                           (tid, user["id"], b, now)).lastrowid
        conn.execute("UPDATE forum_threads SET last_post_id=? WHERE id=?", (pid, tid))
    return {"thread_id": tid}


def _thread_row(thread_id: int):
    return _conn().execute("SELECT * FROM forum_threads WHERE id=?", (thread_id,)).fetchone()


def reply(user: dict, thread_id: int, body) -> dict:
    t = _thread_row(thread_id)
    if t is None or t["status"] == "hidden":
        raise LookupError("That discussion is not on the forum.")
    if t["status"] == "locked":
        raise PermissionError("This discussion is closed to new replies.")
    b = _clean_body(body, REPLY_MIN)
    check_post(b)
    _poster(user["id"])
    _rate(user["id"], False)
    now = _iso(_now())
    conn = _conn()
    with conn:
        cur = conn.execute("INSERT INTO forum_posts(thread_id,user_id,body,created_at) VALUES(?,?,?,?)",
                           (thread_id, user["id"], b, now))
        conn.execute("UPDATE forum_threads SET replies=replies+1, last_post_at=?, last_post_id=? "
                     "WHERE id=?", (now, cur.lastrowid, thread_id))
    return {"post": _post_dict(_post_row(cur.lastrowid), set(), user["id"])}


def _post_row(post_id: int):
    return _conn().execute("SELECT p.*, m.handle FROM forum_posts p "
                           "LEFT JOIN forum_members m ON m.user_id=p.user_id WHERE p.id=?",
                           (post_id,)).fetchone()


def _first_post_id(thread_id: int):
    r = _conn().execute("SELECT MIN(id) FROM forum_posts WHERE thread_id=?", (thread_id,)).fetchone()
    return r[0] if r else None


def _recount(conn, thread_id: int) -> None:
    """Replies are the visible posts after the first, kept as a column so a
    listing is one query; recounted whenever a post changes state."""
    conn.execute(
        "UPDATE forum_threads SET replies=(SELECT COUNT(*) FROM forum_posts WHERE thread_id=? "
        "AND status='visible') - 1 WHERE id=?", (thread_id, thread_id))
    conn.execute("UPDATE forum_threads SET replies=0 WHERE id=? AND replies<0", (thread_id,))


def remove_own(user: dict, post_id: int) -> dict:
    p = _post_row(post_id)
    if p is None or p["user_id"] != user["id"]:
        raise LookupError("That post is not yours to remove.")
    conn = _conn()
    with conn:
        conn.execute("UPDATE forum_posts SET status='removed' WHERE id=? AND status='visible'", (post_id,))
        _recount(conn, p["thread_id"])
    return {"removed": True}


def set_helpful(user: dict, post_id: int, on: bool) -> dict:
    p = _post_row(post_id)
    if p is None or p["status"] != "visible":
        raise LookupError("That post is not on the forum.")
    if p["user_id"] == user["id"]:
        raise PermissionError("You cannot mark your own post as helpful.")
    _poster(user["id"])
    conn = _conn()
    with conn:
        if on:
            cur = conn.execute("INSERT OR IGNORE INTO forum_votes(post_id,user_id,created_at) VALUES(?,?,?)",
                               (post_id, user["id"], _iso(_now())))
        else:
            cur = conn.execute("DELETE FROM forum_votes WHERE post_id=? AND user_id=?", (post_id, user["id"]))
        if cur.rowcount:
            conn.execute("UPDATE forum_posts SET helpful=(SELECT COUNT(*) FROM forum_votes WHERE post_id=?) "
                         "WHERE id=?", (post_id, post_id))
    n = conn.execute("SELECT helpful FROM forum_posts WHERE id=?", (post_id,)).fetchone()[0]
    return {"post_id": post_id, "helpful": n, "mine": bool(on)}


def report(user: dict, post_id: int, reason) -> dict:
    """Report a post, once per member. Enough reports hide it until the
    owner has looked."""
    p = _post_row(post_id)
    if p is None:
        raise LookupError("That post is not on the forum.")
    if p["user_id"] == user["id"]:
        raise PermissionError("You cannot report your own post. Remove it instead.")
    why = " ".join(str(reason or "").split())[:REPORT_MAX]
    if len(why) < 4:
        raise ValueError("Say in a few words what is wrong with it.")
    conn = _conn()
    with conn:
        cur = conn.execute("INSERT OR IGNORE INTO forum_reports(post_id,user_id,reason,created_at) "
                           "VALUES(?,?,?,?)", (post_id, user["id"], why, _iso(_now())))
        if not cur.rowcount:
            return {"reported": True, "already": True, "hidden": p["status"] == "hidden"}
        n = conn.execute("SELECT COUNT(*) FROM forum_reports WHERE post_id=? AND resolved_at IS NULL",
                         (post_id,)).fetchone()[0]
        conn.execute("UPDATE forum_posts SET reports=? WHERE id=?", (n, post_id))
        hidden = False
        if n >= HIDE_AFTER_REPORTS and p["status"] == "visible":
            conn.execute("UPDATE forum_posts SET status='hidden', hidden_by='reports' WHERE id=?", (post_id,))
            if post_id == _first_post_id(p["thread_id"]):
                conn.execute("UPDATE forum_threads SET status='hidden' WHERE id=?", (p["thread_id"],))
            _recount(conn, p["thread_id"])
            hidden = True
    return {"reported": True, "already": False, "hidden": hidden}


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------

def _excerpt(body: str, n: int = 220) -> str:
    s = " ".join(str(body or "").split())
    return s if len(s) <= n else s[:n].rsplit(" ", 1)[0] + "…"


def _thread_dict(row, opening=None) -> dict:
    return {
        "id": row["id"], "category": row["category"],
        "category_label": CATEGORY_LABEL.get(row["category"], row["category"]),
        "symbol": row["symbol"], "company": row["company"], "title": row["title"],
        "author": row["handle"] if "handle" in row.keys() else None,
        "created_at": row["created_at"], "last_post_at": row["last_post_at"],
        "replies": row["replies"], "locked": row["status"] == "locked",
        "pinned": bool(row["pinned"]),
        "helpful": row["helpful"] if "helpful" in row.keys() else 0,
        "excerpt": _excerpt(opening) if opening is not None else None,
    }


_LIST_SQL = (
    "SELECT t.*, m.handle, p.body AS opening, p.helpful AS helpful FROM forum_threads t "
    "LEFT JOIN forum_members m ON m.user_id=t.user_id "
    "LEFT JOIN forum_posts p ON p.id=(SELECT MIN(id) FROM forum_posts WHERE thread_id=t.id) "
    "WHERE t.status!='hidden'")


def threads(category: str = "", symbol: str = "", q: str = "", sort: str = "latest",
            page: int = 1, limit: int = PAGE) -> dict:
    """The front page, a category, a stock, or a search. Pinned threads lead
    the front page and a category; a stock's list and a search are in order."""
    where, args = [], []
    cat = str(category or "").strip().lower()
    if cat:
        if cat not in CATEGORY_LABEL:
            raise ValueError("Unknown category.")
        where.append("t.category=?")
        args.append(cat)
    sym = accounts._clean_symbol(symbol) if symbol else ""
    if symbol and not sym:
        raise ValueError("That is not a stock symbol.")
    if sym:
        where.append("t.symbol=?")
        args.append(sym)
    words = [w for w in re.split(r"\s+", str(q or "").strip()) if w][:6]
    for w in words:
        where.append("(t.title LIKE ? ESCAPE '\\' OR t.symbol=?)")
        like = "%" + w.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        args += [like, w.upper()]
    sort = sort if sort in SORTS else "latest"
    order = {"latest": "t.last_post_id DESC", "new": "t.id DESC",
             "top": "(t.replies + COALESCE(p.helpful,0) * 2) DESC, t.last_post_id DESC"}[sort]
    if not sym and not words and sort == "latest":
        order = "t.pinned DESC, " + order
    limit = max(1, min(int(limit or PAGE), 100))
    page = max(1, min(int(page or 1), 500))
    sql = _LIST_SQL + "".join(" AND " + w for w in where) + f" ORDER BY {order}, t.id DESC LIMIT ? OFFSET ?"
    rows = _conn().execute(sql, args + [limit + 1, (page - 1) * limit]).fetchall()
    return {"threads": [_thread_dict(r, r["opening"]) for r in rows[:limit]],
            "page": page, "has_more": len(rows) > limit,
            "category": cat or None, "symbol": sym or None, "q": " ".join(words) or None, "sort": sort}


def _post_dict(row, mine_votes: set, viewer_id=None) -> dict:
    status = row["status"]
    body = row["body"] if status == "visible" else None
    return {"id": row["id"], "author": row["handle"] or "member",
            "created_at": row["created_at"], "status": status,
            "body": body, "helpful": row["helpful"] if status == "visible" else 0,
            "voted": row["id"] in mine_votes,
            "mine": viewer_id is not None and row["user_id"] == viewer_id}


def thread(thread_id: int, viewer=None) -> dict:
    t = _conn().execute("SELECT t.*, m.handle FROM forum_threads t LEFT JOIN forum_members m "
                        "ON m.user_id=t.user_id WHERE t.id=?", (thread_id,)).fetchone()
    if t is None or t["status"] == "hidden":
        raise LookupError("That discussion is not on the forum.")
    conn = _conn()
    rows = conn.execute("SELECT p.*, m.handle FROM forum_posts p LEFT JOIN forum_members m "
                        "ON m.user_id=p.user_id WHERE p.thread_id=? ORDER BY p.id LIMIT ?",
                        (thread_id, POSTS_PAGE)).fetchall()
    vid = viewer["id"] if viewer else None
    votes = set()
    if vid is not None and rows:
        votes = {r[0] for r in conn.execute(
            "SELECT post_id FROM forum_votes WHERE user_id=? AND post_id IN (%s)" % ",".join("?" * len(rows)),
            [vid] + [r["id"] for r in rows])}
    posts = [_post_dict(r, votes, vid) for r in rows]
    out = _thread_dict(t)
    out["helpful"] = posts[0]["helpful"] if posts else 0
    return {"thread": out, "posts": posts, "disclaimer": DISCLAIMER}


def for_stock(symbol: str, limit: int = 6) -> dict:
    """What the stock page shows: how many discussions, and the latest."""
    sym = accounts._clean_symbol(symbol)
    if not sym:
        raise ValueError("That is not a stock symbol.")
    conn = _conn()
    n = conn.execute("SELECT COUNT(*) FROM forum_threads WHERE symbol=? AND status!='hidden'",
                     (sym,)).fetchone()[0]
    week = _iso(_now() - dt.timedelta(days=7))
    recent = conn.execute(
        "SELECT COUNT(*) FROM forum_posts p JOIN forum_threads t ON t.id=p.thread_id "
        "WHERE t.symbol=? AND t.status!='hidden' AND p.status='visible' AND p.created_at>?",
        (sym, week)).fetchone()[0]
    listing = threads(symbol=sym, limit=limit)
    return {"symbol": sym, "count": n, "posts_this_week": recent,
            "threads": listing["threads"], "has_more": listing["has_more"]}


def activity(since: dt.datetime, until: dt.datetime, limit: int = 5) -> dict:
    """A window of the forum, for the weekly brief: the busiest discussions
    and the most talked-about stocks, counted in visible posts."""
    conn = _conn()
    a, b = _iso(since), _iso(until)
    busy = conn.execute(
        "SELECT t.id, t.title, t.category, t.symbol, t.replies, COUNT(p.id) AS n FROM forum_posts p "
        "JOIN forum_threads t ON t.id=p.thread_id WHERE p.status='visible' AND t.status!='hidden' "
        "AND p.created_at>=? AND p.created_at<? GROUP BY t.id ORDER BY n DESC, t.last_post_id DESC LIMIT ?",
        (a, b, limit)).fetchall()
    stocks = conn.execute(
        "SELECT t.symbol, MAX(t.company) AS company, COUNT(p.id) AS n, COUNT(DISTINCT t.id) AS threads "
        "FROM forum_posts p JOIN forum_threads t ON t.id=p.thread_id WHERE p.status='visible' "
        "AND t.status!='hidden' AND t.symbol IS NOT NULL AND p.created_at>=? AND p.created_at<? "
        "GROUP BY t.symbol ORDER BY n DESC, t.symbol LIMIT ?", (a, b, limit)).fetchall()
    totals = conn.execute(
        "SELECT COUNT(*), COUNT(DISTINCT p.user_id) FROM forum_posts p JOIN forum_threads t ON t.id=p.thread_id "
        "WHERE p.status='visible' AND t.status!='hidden' AND p.created_at>=? AND p.created_at<?",
        (a, b)).fetchone()
    new_threads = conn.execute(
        "SELECT COUNT(*) FROM forum_threads WHERE status!='hidden' AND created_at>=? AND created_at<?",
        (a, b)).fetchone()[0]
    return {
        "posts": totals[0], "members": totals[1], "new_threads": new_threads,
        "threads": [{"id": r["id"], "title": r["title"], "category": r["category"],
                     "category_label": CATEGORY_LABEL.get(r["category"], r["category"]),
                     "symbol": r["symbol"], "posts": r["n"], "replies": r["replies"]} for r in busy],
        "stocks": [{"symbol": r["symbol"], "company": r["company"], "posts": r["n"],
                    "threads": r["threads"]} for r in stocks],
    }


def overview() -> dict:
    """The categories with their counts, for the forum's side panel."""
    conn = _conn()
    counts = {r["category"]: r["n"] for r in conn.execute(
        "SELECT category, COUNT(*) AS n FROM forum_threads WHERE status!='hidden' GROUP BY category")}
    return {"categories": [{"id": c, "label": label, "blurb": blurb, "threads": counts.get(c, 0)}
                           for c, label, blurb in CATEGORIES],
            "rules": HOUSE_RULES, "disclaimer": DISCLAIMER}


# ---------------------------------------------------------------------------
# The owner
# ---------------------------------------------------------------------------

ACTIONS = ("hide_post", "restore_post", "hide_thread", "restore_thread", "lock_thread",
           "unlock_thread", "pin_thread", "unpin_thread", "ban_member", "unban_member",
           "dismiss_reports")


def moderation_queue() -> dict:
    """Reported and hidden posts, with what was said and who reported it."""
    conn = _conn()
    rows = conn.execute(
        "SELECT p.id, p.thread_id, p.body, p.status, p.hidden_by, p.reports, p.created_at, p.user_id, "
        "m.handle, m.status AS member_status, t.title FROM forum_posts p "
        "JOIN forum_threads t ON t.id=p.thread_id LEFT JOIN forum_members m ON m.user_id=p.user_id "
        "WHERE p.status='hidden' OR EXISTS (SELECT 1 FROM forum_reports r WHERE r.post_id=p.id "
        "AND r.resolved_at IS NULL) ORDER BY p.reports DESC, p.id DESC LIMIT 200").fetchall()
    out = []
    for r in rows:
        reasons = [x["reason"] for x in conn.execute(
            "SELECT reason FROM forum_reports WHERE post_id=? AND resolved_at IS NULL ORDER BY id", (r["id"],))]
        out.append({"post_id": r["id"], "thread_id": r["thread_id"], "thread_title": r["title"],
                    "author": r["handle"], "author_user_id": r["user_id"],
                    "author_status": r["member_status"], "body": r["body"], "status": r["status"],
                    "hidden_by": r["hidden_by"], "reports": r["reports"], "reasons": reasons,
                    "created_at": r["created_at"]})
    one = lambda q: conn.execute(q).fetchone()[0]          # noqa: E731
    return {"queue": out, "counts": {
        "threads": one("SELECT COUNT(*) FROM forum_threads"),
        "posts": one("SELECT COUNT(*) FROM forum_posts"),
        "members": one("SELECT COUNT(*) FROM forum_members"),
        "banned": one("SELECT COUNT(*) FROM forum_members WHERE status='banned'"),
        "open_reports": one("SELECT COUNT(*) FROM forum_reports WHERE resolved_at IS NULL")}}


def moderate(action: str, target: int, note: str = "") -> dict:
    """One owner decision. `target` is a post id, a thread id or a user id,
    by the action's name."""
    if action not in ACTIONS:
        raise ValueError("Unknown action. One of: " + ", ".join(ACTIONS) + ".")
    conn = _conn()
    now = _iso(_now())
    with conn:
        if action in ("hide_post", "restore_post", "dismiss_reports"):
            p = _post_row(target)
            if p is None:
                raise LookupError("No such post.")
            if action == "hide_post":
                conn.execute("UPDATE forum_posts SET status='hidden', hidden_by='owner' WHERE id=?", (target,))
            elif action == "restore_post" and p["status"] == "hidden":
                conn.execute("UPDATE forum_posts SET status='visible', hidden_by=NULL WHERE id=?", (target,))
                if target == _first_post_id(p["thread_id"]):
                    conn.execute("UPDATE forum_threads SET status='open' WHERE id=? AND status='hidden'",
                                 (p["thread_id"],))
            conn.execute("UPDATE forum_reports SET resolved_at=? WHERE post_id=? AND resolved_at IS NULL",
                         (now, target))
            conn.execute("UPDATE forum_posts SET reports=0 WHERE id=?", (target,))
            _recount(conn, p["thread_id"])
            return {"post_id": target, "status": _post_row(target)["status"]}
        if action.endswith("_thread"):
            t = _thread_row(target)
            if t is None:
                raise LookupError("No such discussion.")
            change = {"hide_thread": ("status", "hidden"), "restore_thread": ("status", "open"),
                      "lock_thread": ("status", "locked"), "unlock_thread": ("status", "open"),
                      "pin_thread": ("pinned", 1), "unpin_thread": ("pinned", 0)}[action]
            conn.execute(f"UPDATE forum_threads SET {change[0]}=? WHERE id=?", (change[1], target))
            r = _thread_row(target)
            return {"thread_id": target, "status": r["status"], "pinned": bool(r["pinned"])}
        # members
        m = conn.execute("SELECT user_id FROM forum_members WHERE user_id=?", (target,)).fetchone()
        if m is None:
            raise LookupError("No such member.")
        status = "banned" if action == "ban_member" else "active"
        conn.execute("UPDATE forum_members SET status=?, status_note=?, updated_at=? WHERE user_id=?",
                     (status, str(note or "")[:300] or None, now, target))
        return {"user_id": target, "status": status}
