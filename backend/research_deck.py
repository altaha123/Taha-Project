"""
research_deck.py — the Research Deck: articles and photos the owner publishes.

WHO WRITES, WHO READS
Reading is open to anyone: the deck, every published article and every photo
in one. Writing is the owner's alone — uploading a photo, saving a draft,
publishing, unpublishing, deleting — and is checked in research_routes.py
against ADMIN_KEY. Unlike some older admin switches on this API, the deck is
CLOSED when ADMIN_KEY is unset: a deploy that forgot the key must not leave a
public upload form on the site's own domain.

WHERE IT LIVES
One SQLite file, `altaha_research.db`, at the top of DATA_DIR. Photos are kept
in the same file as BLOBs rather than in a folder beside it, for one reason:
backup.py copies every regular file at the top of DATA_DIR to R2 and nothing in
a subdirectory, so a folder of photos would be the one thing on the disk that a
lost disk took with it. A photo is re-encoded on upload to at most 2000 px on
its long side, which puts a typical chart screenshot at 150-500 KB; the 1 GB
disk holds thousands.

WHAT AN UPLOAD BECOMES
Every photo is opened, checked and re-encoded by Pillow before it is stored.
That does three jobs at once: it refuses anything that is not really an image,
whatever its name says; it drops the EXIF block, which on a phone photo
carries the GPS position it was taken at; and it caps the size, so the page a
reader on a phone opens is not a 12 MB original. Screenshots and charts stay
PNG (JPEG smears text); photographs become JPEG.

ADDRESSES THAT DO NOT MOVE
An article's slug is set from its title the first time it is saved and never
changes afterwards, even if the title does: a link posted on X is permanent in
a way an article's wording is not. `version` changes on every save, and the
share card's URL carries it, because X caches a card by its URL.

Articles reference their photos as `media:<id>` (the cover, and `![caption]
(media:<id>)` lines in the body) rather than by a full URL, so moving the API
to another host changes nothing stored here.
"""
from __future__ import annotations

import base64
import binascii
import io
import os
import re
import secrets
import sqlite3
import threading
import unicodedata
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

_HERE = os.path.dirname(os.path.abspath(__file__))
_DATA_DIR = os.environ.get("DATA_DIR", "").strip() or _HERE
try:
    os.makedirs(_DATA_DIR, exist_ok=True)
except Exception:                                             # pragma: no cover
    _DATA_DIR = _HERE

DB_PATH = os.environ.get("ALTAHA_RESEARCH_DB", "").strip() or \
    os.path.join(_DATA_DIR, "altaha_research.db")

# Limits. Generous for one author, small enough that a mistake cannot fill
# the disk or the instance's memory.
MAX_UPLOAD_BYTES = 15 * 1024 * 1024       # the file as sent, before re-encoding
MAX_PIXELS = 50_000_000                   # a 50 MP original decodes to ~150 MB
MAX_SIDE = 2000                           # long side once stored
PNG_CEILING = 1_600_000                   # a PNG bigger than this becomes JPEG
JPEG_QUALITY = 85

TITLE_MIN, TITLE_MAX = 3, 160
SUMMARY_MAX = 300
BODY_MAX = 60_000
MAX_TICKERS = 10
MAX_CAPTION = 200
ORPHAN_DAYS = 7                           # an uploaded photo no article uses

STATUSES = ("draft", "published")

_lock = threading.Lock()
_ready = set()


# ── storage ─────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    if DB_PATH not in _ready:
        with _lock:
            if DB_PATH not in _ready:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.executescript("""
                CREATE TABLE IF NOT EXISTS articles (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    slug          TEXT NOT NULL UNIQUE,
                    title         TEXT NOT NULL,
                    summary       TEXT NOT NULL DEFAULT '',
                    body          TEXT NOT NULL DEFAULT '',
                    cover         TEXT,
                    tickers       TEXT NOT NULL DEFAULT '',
                    status        TEXT NOT NULL DEFAULT 'draft',
                    version       INTEGER NOT NULL DEFAULT 1,
                    created_at    TEXT NOT NULL,
                    updated_at    TEXT NOT NULL,
                    published_at  TEXT
                );
                CREATE INDEX IF NOT EXISTS articles_pub
                    ON articles(status, published_at);
                CREATE TABLE IF NOT EXISTS media (
                    id          TEXT PRIMARY KEY,
                    mime        TEXT NOT NULL,
                    width       INTEGER NOT NULL,
                    height      INTEGER NOT NULL,
                    size        INTEGER NOT NULL,
                    data        BLOB NOT NULL,
                    article_id  INTEGER,
                    created_at  TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS media_article ON media(article_id);
                """)
                conn.commit()
                _ready.add(DB_PATH)
    return conn


def reset_for_tests(path: str) -> None:
    global DB_PATH
    DB_PATH = path
    _ready.discard(path)


# ── photos ──────────────────────────────────────────────────────────────

_MEDIA_ID = re.compile(r"^[0-9a-f]{16}$")
_MEDIA_REF = re.compile(r"media:([0-9a-f]{16})")


def _decode_upload(data: Any) -> bytes:
    """A base64 string, bare or as a data: URL, to bytes."""
    if not isinstance(data, str) or not data.strip():
        raise ValueError("Choose a photo to upload.")
    s = data.strip()
    if s.startswith("data:"):
        head, _, s = s.partition(",")
        if ";base64" not in head:
            raise ValueError("The photo did not arrive as base64.")
    # 4 base64 characters carry 3 bytes; refuse before decoding, not after.
    if len(s) * 3 // 4 > MAX_UPLOAD_BYTES:
        raise ValueError(f"That photo is over {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.")
    try:
        raw = base64.b64decode(s, validate=False)
    except (binascii.Error, ValueError):
        raise ValueError("The photo could not be read.")
    if not raw:
        raise ValueError("The photo is empty.")
    return raw


def process_image(raw: bytes) -> Tuple[bytes, str, int, int]:
    """Check, orient, shrink and re-encode an upload. Returns (bytes, mime, w, h)."""
    from PIL import Image, ImageOps, UnidentifiedImageError

    if len(raw) > MAX_UPLOAD_BYTES:
        raise ValueError(f"That photo is over {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.")
    try:
        img = Image.open(io.BytesIO(raw))
        fmt = (img.format or "").upper()
        if fmt not in ("JPEG", "PNG", "WEBP", "GIF"):
            raise ValueError("Upload a JPEG, PNG, WebP or GIF.")
        if img.width * img.height > MAX_PIXELS:
            raise ValueError("That photo has too many pixels to process. Resize it first.")
        if fmt == "JPEG":
            # Decode at a reduced scale where the codec allows it: a 6000 px
            # phone photo then never exists in memory at full size.
            img.draft("RGB", (MAX_SIDE, MAX_SIDE))
        img.load()
    except ValueError:
        raise
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, SyntaxError):
        raise ValueError("That file is not a photo this site can read.")

    img = ImageOps.exif_transpose(img)            # phones store rotation in EXIF
    if max(img.size) > MAX_SIDE:
        img.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)

    has_alpha = img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info)
    lossless_source = fmt in ("PNG", "GIF") or (fmt == "WEBP" and img.info.get("lossless"))

    if lossless_source:
        out = io.BytesIO()
        im = img.convert("RGBA" if has_alpha else "RGB")
        im.save(out, "PNG", optimize=True)
        if out.tell() <= PNG_CEILING:
            return out.getvalue(), "image/png", im.width, im.height

    # A photograph, or a PNG too large to keep lossless: JPEG on white.
    if has_alpha:
        rgba = img.convert("RGBA")
        bg = Image.new("RGB", rgba.size, (255, 255, 255))
        bg.paste(rgba, mask=rgba.split()[-1])
        img = bg
    else:
        img = img.convert("RGB")
    out = io.BytesIO()
    img.save(out, "JPEG", quality=JPEG_QUALITY, optimize=True, progressive=True)
    return out.getvalue(), "image/jpeg", img.width, img.height


def save_media(data: Any) -> Dict[str, Any]:
    """Store an uploaded photo. `data` is base64 (or a data: URL)."""
    blob, mime, w, h = process_image(_decode_upload(data))
    mid = secrets.token_hex(8)
    with _conn() as c:
        c.execute("INSERT INTO media (id, mime, width, height, size, data, created_at) "
                  "VALUES (?, ?, ?, ?, ?, ?, ?)",
                  (mid, mime, w, h, len(blob), sqlite3.Binary(blob), _now()))
        _sweep_orphans(c)
    return {"id": mid, "ref": f"media:{mid}", "mime": mime, "width": w,
            "height": h, "size": len(blob)}


def get_media(mid: str, public: bool = True) -> Optional[Tuple[str, bytes]]:
    """(mime, bytes), or None. The public may see a photo once it is in a
    published article; until then it is the owner's draft."""
    mid = str(mid or "").lower()
    if not _MEDIA_ID.match(mid):
        return None
    with _conn() as c:
        row = c.execute("SELECT m.mime, m.data, a.status FROM media m "
                        "LEFT JOIN articles a ON a.id = m.article_id WHERE m.id = ?",
                        (mid,)).fetchone()
    if row is None:
        return None
    if public and row["status"] != "published":
        return None
    return row["mime"], bytes(row["data"])


def _sweep_orphans(c: sqlite3.Connection) -> None:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=ORPHAN_DAYS)).replace(
        microsecond=0).isoformat()
    c.execute("DELETE FROM media WHERE article_id IS NULL AND created_at < ?", (cutoff,))


def _claim_media(c: sqlite3.Connection, article_id: int, refs: List[str]) -> None:
    """Tie the photos an article uses to it, and let go of the ones it dropped."""
    refs = sorted(set(refs))
    c.execute("UPDATE media SET article_id = NULL, created_at = ? "
              "WHERE article_id = ?", (_now(), article_id))
    for mid in refs:
        c.execute("UPDATE media SET article_id = ? WHERE id = ? "
                  "AND (article_id IS NULL OR article_id = ?)",
                  (article_id, mid, article_id))


# ── articles ────────────────────────────────────────────────────────────

def _slugify(title: str) -> str:
    s = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s).strip("-").lower()
    s = s[:70].rstrip("-")
    return s or "research"


def _unique_slug(c: sqlite3.Connection, base: str) -> str:
    slug, n = base, 2
    while c.execute("SELECT 1 FROM articles WHERE slug = ?", (slug,)).fetchone():
        slug = f"{base}-{n}"
        n += 1
    return slug


def _clean_text(v: Any, limit: int, field: str, multiline: bool = False) -> str:
    s = "" if v is None else str(v)
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    # Control characters other than newline and tab have no business here.
    s = "".join(ch for ch in s if ch in "\n\t" or unicodedata.category(ch)[0] != "C")
    if not multiline:
        s = " ".join(s.split())
    else:
        s = s.strip()
    if len(s) > limit:
        raise ValueError(f"The {field} is {len(s):,} characters; the most is {limit:,}.")
    return s


_TICKER = re.compile(r"^[A-Z0-9&.\-]{1,20}$")


def _clean_tickers(v: Any) -> List[str]:
    if v is None:
        return []
    # Commas separate symbols; a space inside one is a typed name ("uno
    # minda"), and NSE symbols are those names run together (UNOMINDA).
    items = v if isinstance(v, list) else re.split(r"[,;\n]+", str(v))
    out: List[str] = []
    for t in items:
        t = re.sub(r"\s+", "", str(t or "")).upper()
        t = re.sub(r"\.(NS|BO)$", "", t)
        if not t:
            continue
        if not _TICKER.match(t):
            raise ValueError(f"“{t[:24]}” is not a stock symbol.")
        if t not in out:
            out.append(t)
    if len(out) > MAX_TICKERS:
        raise ValueError(f"Tag at most {MAX_TICKERS} stocks.")
    return out


def _clean_cover(v: Any) -> Optional[str]:
    if v in (None, ""):
        return None
    s = str(v).strip().lower()
    if s.startswith("media:"):
        s = s[6:]
    if not _MEDIA_ID.match(s):
        raise ValueError("The cover photo is not one uploaded here.")
    return s


def reading_minutes(body: str) -> int:
    words = len(re.findall(r"\w+", body or ""))
    return max(1, round(words / 220))


def _row(r: sqlite3.Row, full: bool) -> Dict[str, Any]:
    out = {
        "id": r["id"],
        "slug": r["slug"],
        "title": r["title"],
        "summary": r["summary"],
        "cover": r["cover"],
        "tickers": [t for t in (r["tickers"] or "").split(",") if t],
        "status": r["status"],
        "version": r["version"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "published_at": r["published_at"],
        "minutes": reading_minutes(r["body"]),
    }
    if full:
        out["body"] = r["body"]
    return out


def save(fields: Dict[str, Any]) -> Dict[str, Any]:
    """Create (no id) or update (id) an article. Returns the stored article."""
    if not isinstance(fields, dict):
        raise ValueError("Send the article as a JSON object.")
    title = _clean_text(fields.get("title"), TITLE_MAX, "title")
    if len(title) < TITLE_MIN:
        raise ValueError("Give the article a title.")
    summary = _clean_text(fields.get("summary"), SUMMARY_MAX, "summary")
    body = _clean_text(fields.get("body"), BODY_MAX, "article", multiline=True)
    tickers = _clean_tickers(fields.get("tickers"))
    cover = _clean_cover(fields.get("cover"))
    status = str(fields.get("status") or "draft").strip().lower()
    if status not in STATUSES:
        raise ValueError("Status is draft or published.")
    if status == "published" and not (summary or body):
        raise ValueError("An article needs a summary or some text before it is published.")

    refs = _MEDIA_REF.findall(body) + ([cover] if cover else [])
    now = _now()
    aid = fields.get("id")

    with _conn() as c:
        for mid in set(refs):
            if not c.execute("SELECT 1 FROM media WHERE id = ?", (mid,)).fetchone():
                raise ValueError("A photo in this article is no longer on the server. "
                                 "Upload it again.")
        if aid in (None, ""):
            slug = _unique_slug(c, _slugify(title))
            cur = c.execute(
                "INSERT INTO articles (slug, title, summary, body, cover, tickers, status, "
                "version, created_at, updated_at, published_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)",
                (slug, title, summary, body, cover, ",".join(tickers), status, now, now,
                 now if status == "published" else None))
            aid = cur.lastrowid
        else:
            try:
                aid = int(aid)
            except (TypeError, ValueError):
                raise ValueError("That article id is not a number.")
            old = c.execute("SELECT * FROM articles WHERE id = ?", (aid,)).fetchone()
            if old is None:
                raise LookupError("There is no such article.")
            # First publication sets the date; a later edit keeps it.
            published_at = old["published_at"]
            if status == "published" and not published_at:
                published_at = now
            c.execute(
                "UPDATE articles SET title = ?, summary = ?, body = ?, cover = ?, "
                "tickers = ?, status = ?, version = version + 1, updated_at = ?, "
                "published_at = ? WHERE id = ?",
                (title, summary, body, cover, ",".join(tickers), status, now,
                 published_at, aid))
        _claim_media(c, aid, refs)
        r = c.execute("SELECT * FROM articles WHERE id = ?", (aid,)).fetchone()
    return _row(r, full=True)


def delete(aid: Any) -> Dict[str, Any]:
    try:
        aid = int(aid)
    except (TypeError, ValueError):
        raise ValueError("That article id is not a number.")
    with _conn() as c:
        r = c.execute("SELECT slug FROM articles WHERE id = ?", (aid,)).fetchone()
        if r is None:
            raise LookupError("There is no such article.")
        c.execute("DELETE FROM media WHERE article_id = ?", (aid,))
        c.execute("DELETE FROM articles WHERE id = ?", (aid,))
    return {"deleted": aid, "slug": r["slug"]}


def get(slug_or_id: Any, include_drafts: bool = False) -> Optional[Dict[str, Any]]:
    key = str(slug_or_id or "").strip()
    if not key:
        return None
    with _conn() as c:
        if key.isdigit():
            r = c.execute("SELECT * FROM articles WHERE id = ?", (int(key),)).fetchone()
        else:
            r = c.execute("SELECT * FROM articles WHERE slug = ?", (key.lower(),)).fetchone()
    if r is None or (not include_drafts and r["status"] != "published"):
        return None
    return _row(r, full=True)


def listing(include_drafts: bool = False, ticker: Optional[str] = None,
            limit: int = 30, offset: int = 0) -> Dict[str, Any]:
    limit = max(1, min(int(limit or 30), 100))
    offset = max(0, int(offset or 0))
    where, args = [], []
    if not include_drafts:
        where.append("status = 'published'")
    if ticker:
        t = _clean_tickers([ticker])
        if t:
            where.append("(',' || tickers || ',') LIKE ?")
            args.append(f"%,{t[0]},%")
    sql_where = (" WHERE " + " AND ".join(where)) if where else ""
    with _conn() as c:
        total = c.execute(f"SELECT COUNT(*) FROM articles{sql_where}", args).fetchone()[0]
        rows = c.execute(
            f"SELECT * FROM articles{sql_where} "
            "ORDER BY COALESCE(published_at, updated_at) DESC, id DESC LIMIT ? OFFSET ?",
            args + [limit, offset]).fetchall()
    return {"total": total, "items": [_row(r, full=False) for r in rows]}
