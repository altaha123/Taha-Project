"""
The daily copy of the data disk to Cloudflare R2.

A backup fails in the ways that matter only on the day it is needed: a
database copied mid-write that will not open, a file that was never included,
or last month's good copies pruned by a night when nothing uploaded. Each of
those is tested here against a fake bucket, and the request signing against a
signature produced by AWS's own botocore.
"""
import datetime as dt
import gzip
import io
import os
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import backup  # noqa: E402


class FakeBucket:
    def __init__(self, fail_on=None):
        self.objects, self.deleted, self.fail_on = {}, [], fail_on or set()

    def put_file(self, key, path, content_type=None):
        if any(f in key for f in self.fail_on):
            raise RuntimeError("HTTP 500")
        with open(path, "rb") as fh:
            self.objects[key] = fh.read()

    def put_bytes(self, key, body, content_type=None):
        self.objects[key] = body

    def list(self, prefix):
        return [k for k in self.objects if k.startswith(prefix)]

    def delete(self, key):
        self.deleted.append(key)
        self.objects.pop(key, None)


@pytest.fixture()
def disk(tmp_path):
    db = sqlite3.connect(tmp_path / "altaha_accounts.db")
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("CREATE TABLE users (email TEXT)")
    db.executemany("INSERT INTO users VALUES (?)", [("a@x.in",), ("b@x.in",)])
    db.commit()                       # left open: the -wal file is live
    (tmp_path / "tracked.json").write_text('{"ideas": []}')
    (tmp_path / "xbrl-cache").mkdir()
    (tmp_path / "xbrl-cache" / "doc.json").write_text("{}")
    yield tmp_path
    db.close()


def _restore(blob, tmp_path):
    p = tmp_path / "restored.db"
    p.write_bytes(gzip.decompress(blob))
    return sqlite3.connect(p)


def test_a_live_database_is_copied_so_it_restores(disk, tmp_path_factory):
    b = FakeBucket()
    out = backup.run(client=b, data_dir=str(disk), today=dt.date(2026, 9, 24))
    assert out["ok"]
    blob = b.objects["daily/2026-09-24/altaha_accounts.db.gz"]
    con = _restore(blob, tmp_path_factory.mktemp("r"))
    assert con.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 2
    assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_every_top_level_file_goes_and_side_files_and_caches_do_not(disk):
    b = FakeBucket()
    backup.run(client=b, data_dir=str(disk), today=dt.date(2026, 9, 24))
    names = sorted(k.split("/")[-1] for k in b.objects)
    assert names == ["altaha_accounts.db.gz", "manifest.json", "tracked.json.gz"]
    assert gzip.decompress(b.objects["daily/2026-09-24/tracked.json.gz"]) == b'{"ideas": []}'
    assert not os.listdir(disk / backup._SCRATCH)          # scratch cleaned up


def test_old_days_are_pruned_after_a_good_night(disk):
    b = FakeBucket()
    b.objects["daily/2026-08-01/tracked.json.gz"] = b"old"
    b.objects["daily/2026-09-01/tracked.json.gz"] = b"recent"
    out = backup.run(client=b, data_dir=str(disk), today=dt.date(2026, 9, 24))
    assert out["pruned"] == 1
    assert "daily/2026-08-01/tracked.json.gz" not in b.objects
    assert "daily/2026-09-01/tracked.json.gz" in b.objects


def test_a_bad_night_never_prunes_the_last_good_copies(disk):
    b = FakeBucket(fail_on={"altaha_accounts"})
    b.objects["daily/2026-08-01/altaha_accounts.db.gz"] = b"the last good copy"
    out = backup.run(client=b, data_dir=str(disk), today=dt.date(2026, 9, 24))
    assert not out["ok"] and out["errors"][0]["name"] == "altaha_accounts.db"
    assert b.deleted == []
    assert "daily/2026-09-24/tracked.json.gz" in b.objects     # the rest still went


def test_the_signature_matches_botocore():
    """Reference produced by botocore's S3SigV4Auth with an unsigned payload."""
    when = dt.datetime(2026, 9, 24, 6, 24, 40, tzinfo=dt.timezone.utc)
    h = backup.sign("PUT", "/altaha-backups/daily/2026-09-24/altaha_pit.db.gz", {},
                    {"content-type": "application/gzip", "content-length": "1234"},
                    "AKID", "SECRET", "abc123.r2.cloudflarestorage.com", now=when)
    assert h["authorization"].endswith(
        "Signature=41967309bd0af9627cc17035862e9b4d68e77dd4967d7ddc2667c97832c510aa")
    assert h["x-amz-content-sha256"] == "UNSIGNED-PAYLOAD"


class FakeHTTP:
    def __init__(self, pages):
        self.pages, self.calls = list(pages), []

    def request(self, method, url, headers=None, data=None, timeout=None):
        self.calls.append((method, url))

        class R:
            status_code = 200
        r = R()
        r.text = self.pages.pop(0) if self.pages else ""
        return r


def test_listing_follows_continuation_tokens():
    cfg = {"R2_ACCOUNT_ID": "abc", "R2_ACCESS_KEY_ID": "k", "R2_SECRET_ACCESS_KEY": "s",
           "R2_BUCKET": "b", "missing": [], "endpoint": "https://abc.r2.cloudflarestorage.com"}
    http = FakeHTTP([
        "<IsTruncated>true</IsTruncated><Key>daily/a</Key><NextContinuationToken>t+1/=</NextContinuationToken>",
        "<IsTruncated>false</IsTruncated><Key>daily/b</Key>",
    ])
    assert backup.R2(cfg, session=http).list("daily/") == ["daily/a", "daily/b"]
    assert "continuation-token=t%2B1%2F%3D" in http.calls[1][1]


def test_unconfigured_says_which_variables_are_missing(monkeypatch):
    for k in ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("R2_BUCKET", "altaha-backups")
    assert backup.config()["missing"] == ["R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID",
                                          "R2_SECRET_ACCESS_KEY"]
    with pytest.raises(RuntimeError):
        backup.R2()
