"""
backup.py — a copy of everything on the data disk, in Cloudflare R2

WHY
Every database this app keeps lives on one Render disk: the accounts, the
holdings ledger, the fundamentals tables, the point-in-time store, the
tracker. Render's own snapshots live inside Render and are kept for days, so a
lost service or account loses them with it. This puts a copy somewhere else,
once a day, and keeps thirty days of them.

WHAT IS COPIED
Every regular file at the top of DATA_DIR — so a database added next month is
backed up without anyone remembering to add it here — except the SQLite side
files (-wal, -shm, -journal) and this module's own scratch files. Folders are
skipped: xbrl-cache, shp-cache and filing-text are caches of public filings,
rebuilt on demand, and would multiply the size for nothing.

A database is NOT copied as a file. The app is writing to it, and a file copy
taken mid-write is a corrupt database that looks fine until it is restored.
SQLite's backup API takes a consistent snapshot of a live database; that
snapshot is what is uploaded.

HOW, ON A 512 MB INSTANCE
One file at a time: snapshot to disk, gzip to disk, stream the upload from
disk, delete both. Nothing is held in memory whole. The upload is a plain
S3-compatible PUT signed here with AWS Signature V4 (which is what R2 speaks),
using `requests` — boto3 would add tens of megabytes of resident memory to do
the same four calls.

WHERE THE TEMPORARY COPIES GO
Not on the data disk if anywhere else has room. They used to, and from 8 to 13
November 2026 every night failed with "database or disk is full": the 1 GB
disk held 692 MB of data, and the snapshot of the largest database (the
point-in-time store, 307 MB) needs that much free again beside it. The two
largest databases were the two left out, every night, for a week. The
instance's own scratch space (the system temp folder, then the code folder) is
tried first; the data disk is the last resort, as before. A folder that lives
in memory (tmpfs) is never used: a 307 MB copy there is 307 MB of a 512 MB
instance, and the out-of-memory kill takes the site down with the backup.
Each manifest records where each copy was made and how full the data disk is,
so the next disk running out is a warning in the job's log before it is a
failed night.

WHERE
  s3://$R2_BUCKET/daily/YYYY-MM-DD/<file>.gz
  s3://$R2_BUCKET/daily/YYYY-MM-DD/manifest.json   what was copied, sizes, sha256

The bucket must stay PRIVATE. altaha_accounts.db holds users' email addresses
and sign-in sessions.

Configured by four environment variables on Render; unset means off, and the
admin endpoint says so rather than pretending:
  R2_ACCOUNT_ID  R2_ACCESS_KEY_ID  R2_SECRET_ACCESS_KEY  R2_BUCKET
"""

import datetime as dt
import gzip
import hashlib
import hmac
import json
import os
import re
import shutil
import sqlite3
import tempfile
import threading
import time
from urllib.parse import quote

_HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("DATA_DIR", "").strip() or _HERE

KEEP_DAYS = int(os.environ.get("BACKUP_KEEP_DAYS", "30") or 30)
PREFIX = "daily/"
_SCRATCH = ".backup-tmp"
_SKIP_SUFFIXES = ("-wal", "-shm", "-journal", ".tmp", ".partial")
_CHUNK = 1024 * 1024
_MB = 1024 * 1024
# Filesystems that are memory, not disk. Never a place for a scratch copy.
_RAM_FS = {"tmpfs", "ramfs"}
_MOUNTS = "/proc/mounts"
# Room a file's copy needs: the snapshot itself, its gzip beside it while it is
# written (at worst about half the size, for the pickle; the databases shrink
# six to eight times), and a margin so the copy never fills a disk to the byte.
_NEED_FACTOR = 1.5
_NEED_MARGIN = 16 * _MB

_lock = threading.Lock()
_last = {"result": None}


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def config():
    c = {k: os.environ.get(k, "").strip() for k in
         ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET")}
    c["missing"] = [k for k, v in c.items() if not v]
    c["endpoint"] = ("https://%s.r2.cloudflarestorage.com" % c["R2_ACCOUNT_ID"]
                     if c["R2_ACCOUNT_ID"] else None)
    return c


def configured():
    return not config()["missing"]


# ---------------------------------------------------------------------------
# AWS Signature V4, the part of it an S3 PUT / GET / DELETE needs
# ---------------------------------------------------------------------------

def _hmac(key, msg):
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def _canonical_query(query):
    return "&".join("%s=%s" % (quote(k, safe="-_.~"), quote(str(v), safe="-_.~"))
                    for k, v in sorted((query or {}).items()))


def sign(method, url_path, query, headers, access_key, secret_key, host,
         now=None, region="auto", service="s3"):
    """
    Headers to send for one request, Authorization included.

    The payload is declared UNSIGNED-PAYLOAD so an upload can be streamed from
    disk without hashing it first; TLS already protects it in transit, and R2
    accepts it as S3 does.
    """
    now = now or dt.datetime.now(dt.timezone.utc)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    day = now.strftime("%Y%m%d")
    h = {k.lower(): str(v).strip() for k, v in (headers or {}).items()}
    h.update({"host": host, "x-amz-date": amz_date,
              "x-amz-content-sha256": "UNSIGNED-PAYLOAD"})
    names = sorted(h)
    canonical = "\n".join([
        method,
        quote(url_path, safe="/-_.~"),
        _canonical_query(query),
        "".join("%s:%s\n" % (n, h[n]) for n in names),
        ";".join(names),
        "UNSIGNED-PAYLOAD",
    ])
    scope = "%s/%s/%s/aws4_request" % (day, region, service)
    to_sign = "\n".join(["AWS4-HMAC-SHA256", amz_date, scope,
                         hashlib.sha256(canonical.encode("utf-8")).hexdigest()])
    key = _hmac(_hmac(_hmac(_hmac(("AWS4" + secret_key).encode("utf-8"), day),
                            region), service), "aws4_request")
    signature = hmac.new(key, to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
    h["authorization"] = ("AWS4-HMAC-SHA256 Credential=%s/%s, SignedHeaders=%s, "
                          "Signature=%s" % (access_key, scope, ";".join(names), signature))
    return h


class R2:
    """The four calls a backup needs, against one bucket."""

    def __init__(self, cfg=None, session=None):
        cfg = cfg or config()
        if cfg["missing"]:
            raise RuntimeError("R2 is not configured: %s unset" % ", ".join(cfg["missing"]))
        import requests
        self.http = session or requests.Session()
        self.endpoint = cfg["endpoint"]
        self.host = self.endpoint.split("://", 1)[1]
        self.bucket = cfg["R2_BUCKET"]
        self.ak, self.sk = cfg["R2_ACCESS_KEY_ID"], cfg["R2_SECRET_ACCESS_KEY"]

    def _call(self, method, key="", query=None, headers=None, data=None, timeout=120,
              missing_ok=False):
        path = "/%s/%s" % (self.bucket, key) if key else "/%s" % self.bucket
        h = sign(method, path, query, headers, self.ak, self.sk, self.host)
        # The query string is built here, not by requests, so that what is
        # sent is byte for byte what was signed.
        qs = _canonical_query(query)
        url = self.endpoint + quote(path, safe="/-_.~") + ("?" + qs if qs else "")
        r = self.http.request(method, url, headers=h, data=data, timeout=timeout)
        if missing_ok and r.status_code == 404:
            return None
        if r.status_code >= 300:
            raise RuntimeError("R2 %s %s: HTTP %s %s" % (method, key or "(bucket)",
                                                         r.status_code, r.text[:200]))
        return r

    def put_file(self, key, path, content_type="application/octet-stream"):
        size = os.path.getsize(path)
        with open(path, "rb") as fh:
            self._call("PUT", key, headers={"content-type": content_type,
                                            "content-length": str(size)},
                       data=fh, timeout=1800)

    def put_bytes(self, key, body, content_type="application/json"):
        self._call("PUT", key, headers={"content-type": content_type,
                                        "content-length": str(len(body))}, data=body)

    def get(self, key):
        """The object's bytes, or None when there is no such key."""
        r = self._call("GET", key, missing_ok=True)
        return None if r is None else r.content

    def _pages(self, prefix):
        """The text of each page of a listing, following continuation tokens."""
        token = None
        while True:
            q = {"list-type": "2", "prefix": prefix}
            if token:
                q["continuation-token"] = token
            text = self._call("GET", query=q).text
            yield text
            m = re.search(r"<NextContinuationToken>([^<]+)</NextContinuationToken>", text)
            if not m or "<IsTruncated>true</IsTruncated>" not in text:
                return
            token = m.group(1)

    def list(self, prefix):
        """Every key under prefix, following continuation tokens."""
        keys = []
        for text in self._pages(prefix):
            keys += re.findall(r"<Key>([^<]+)</Key>", text)
        return keys

    def list_objects(self, prefix):
        """Every (key, size in bytes) under prefix."""
        out = []
        for text in self._pages(prefix):
            for block in re.findall(r"<Contents>(.*?)</Contents>", text, re.S):
                k = re.search(r"<Key>([^<]+)</Key>", block)
                n = re.search(r"<Size>(\d+)</Size>", block)
                if k:
                    out.append((k.group(1), int(n.group(1)) if n else 0))
        return out

    def delete(self, key):
        self._call("DELETE", key)


# ---------------------------------------------------------------------------
# Taking the copy
# ---------------------------------------------------------------------------

def _is_sqlite(path):
    try:
        with open(path, "rb") as fh:
            return fh.read(16) == b"SQLite format 3\x00"
    except OSError:
        return False


def candidates(data_dir=None):
    """The files a backup copies, largest last so the small ones land first."""
    d = data_dir or DATA_DIR
    out = []
    for name in os.listdir(d):
        p = os.path.join(d, name)
        if not os.path.isfile(p) or name.startswith(_SCRATCH) or \
                name.endswith(_SKIP_SUFFIXES):
            continue
        out.append(p)
    return sorted(out, key=os.path.getsize)


def _snapshot(src, dst):
    """A consistent copy of a live SQLite database, via its backup API."""
    s = sqlite3.connect("file:%s?mode=ro" % src, uri=True, timeout=60)
    d = sqlite3.connect(dst)
    try:
        s.backup(d, pages=2048, sleep=0.01)      # 8 MB at a time; yields to writers
    finally:
        d.close()
        s.close()


def _fs_type(path):
    """The type of the filesystem holding path, from /proc/mounts; None when
    that cannot be read (not Linux), which counts as disk."""
    try:
        path = os.path.realpath(path)
        best, kind = "", None
        with open(_MOUNTS, encoding="utf-8") as fh:
            for line in fh:
                parts = line.split()
                if len(parts) < 3:
                    continue
                mnt = parts[1].replace("\\040", " ")
                inside = path == mnt or path.startswith(mnt.rstrip("/") + "/")
                if inside and len(mnt) >= len(best):
                    best, kind = mnt, parts[2]
        return kind
    except OSError:
        return None


def scratch_bases(data_dir=None):
    """
    Where a temporary copy may be made, in order of preference: BACKUP_SCRATCH
    if set, the system temp folder, the code folder, and the data disk last.
    """
    d = data_dir or DATA_DIR
    env = os.environ.get("BACKUP_SCRATCH", "").strip()
    out, seen = [], set()
    for b in ([env] if env else []) + [tempfile.gettempdir(), _HERE, d]:
        real = os.path.realpath(b)
        if real not in seen:
            seen.add(real)
            out.append(b)
    return out


def _need(path):
    """Bytes of free space a copy of path needs. The -wal file counts: the
    snapshot carries the pages still waiting in it."""
    raw = os.path.getsize(path)
    try:
        raw += os.path.getsize(path + "-wal")
    except OSError:
        pass
    return int(raw * _NEED_FACTOR) + _NEED_MARGIN


def _pick_scratch(need, bases):
    """
    The first base that is disk, not memory, and has room for a copy; with
    why each one before it was passed over. None when none has room.
    """
    passed = []
    for b in bases:
        if not os.path.isdir(b):
            passed.append("%s missing" % b)
            continue
        if _fs_type(b) in _RAM_FS:
            passed.append("%s is memory" % b)
            continue
        try:
            free = shutil.disk_usage(b).free
        except OSError as e:
            passed.append("%s unreadable (%s)" % (b, e))
            continue
        if free >= need:
            return b, passed
        passed.append("%s has %d MB free" % (b, free // _MB))
    return None, passed


def disk(data_dir=None):
    """How full the data disk is, in bytes and as a share."""
    try:
        u = shutil.disk_usage(data_dir or DATA_DIR)
    except OSError:
        return None
    return {"total": u.total, "used": u.used, "free": u.free,
            "used_pct": round(100.0 * u.used / u.total, 1) if u.total else None}


def _gzip(src, dst):
    sha = hashlib.sha256()
    with open(src, "rb") as fi, gzip.open(dst, "wb", compresslevel=6) as fo:
        while True:
            b = fi.read(_CHUNK)
            if not b:
                break
            sha.update(b)
            fo.write(b)
    return sha.hexdigest()


def run(client=None, data_dir=None, today=None, keep_days=KEEP_DAYS,
        scratch=None):
    """
    One backup: every candidate file to daily/<today>/, a manifest, then the
    days older than keep_days removed. A file that fails is reported and the
    rest still go; old days are pruned only when every file of today's copy
    landed, so a broken night never deletes the last good one.

    scratch is the list of places a temporary copy may be made, in order
    (scratch_bases() when not given). Each file's copy goes to the first with
    room for it.
    """
    if not _lock.acquire(blocking=False):
        return {"ok": False, "error": "a backup is already running"}
    try:
        d = data_dir or DATA_DIR
        client = client or R2()
        day = (today or dt.datetime.now(dt.timezone.utc).date()).isoformat()
        bases = scratch or scratch_bases(d)
        made = set()
        started = time.time()
        files, errors = [], []
        for path in candidates(d):
            name = os.path.basename(path)
            snap = gz = None
            try:
                need = _need(path)
                base, passed = _pick_scratch(need, bases)
                if base is None:
                    raise OSError("no room for a %d MB copy: %s"
                                  % (need // _MB, "; ".join(passed)))
                where = os.path.join(base, _SCRATCH)
                os.makedirs(where, exist_ok=True)
                made.add(where)
                snap = os.path.join(where, name)
                gz = snap + ".gz"
                kind = "sqlite" if _is_sqlite(path) else "file"
                if kind == "sqlite":
                    _snapshot(path, snap)
                else:
                    shutil.copyfile(path, snap)
                raw = os.path.getsize(snap)
                digest = _gzip(snap, gz)
                os.remove(snap)
                client.put_file("%s%s/%s.gz" % (PREFIX, day, name), gz,
                                content_type="application/gzip")
                files.append({"name": name, "kind": kind, "bytes": raw,
                              "gzip_bytes": os.path.getsize(gz), "sha256": digest,
                              "scratch": base})
            except Exception as e:
                errors.append({"name": name, "error": ("%s: %s" % (type(e).__name__, e))[:300]})
            finally:
                for p in (snap, gz):
                    if not p:
                        continue
                    try:
                        os.remove(p)
                    except OSError:
                        pass
        for where in made:
            try:
                os.rmdir(where)                 # only if empty; never a tree
            except OSError:
                pass
        manifest = {"day": day, "data_dir": d, "files": files, "errors": errors,
                    "disk": disk(d),
                    "seconds": round(time.time() - started, 1),
                    "written_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}
        client.put_bytes("%s%s/manifest.json" % (PREFIX, day),
                         json.dumps(manifest, indent=1).encode("utf-8"))

        pruned = []
        if not errors and files:
            cutoff = (dt.date.fromisoformat(day) - dt.timedelta(days=keep_days)).isoformat()
            for key in client.list(PREFIX):
                m = re.match(r"daily/(\d{4}-\d{2}-\d{2})/", key)
                if m and m.group(1) < cutoff:
                    client.delete(key)
                    pruned.append(key)
        out = {"ok": not errors and bool(files), **manifest,
               "total_bytes": sum(f["bytes"] for f in files),
               "total_gzip_bytes": sum(f["gzip_bytes"] for f in files),
               "pruned": len(pruned)}
        _last["result"] = out
        return out
    finally:
        _lock.release()


def days(client=None):
    """The backup days held in the bucket, newest first."""
    client = client or R2()
    found = {m.group(1) for k in client.list(PREFIX)
             for m in [re.match(r"daily/(\d{4}-\d{2}-\d{2})/", k)] if m}
    return sorted(found, reverse=True)


def last_result():
    return _last["result"]
