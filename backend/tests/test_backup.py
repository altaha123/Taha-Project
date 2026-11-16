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


@pytest.fixture()
def scratch(tmp_path_factory):
    """Somewhere other than the data disk for the temporary copies."""
    return tmp_path_factory.mktemp("scratch")


def test_a_live_database_is_copied_so_it_restores(disk, scratch, tmp_path_factory):
    b = FakeBucket()
    out = backup.run(client=b, data_dir=str(disk), today=dt.date(2026, 9, 24),
                     scratch=[str(scratch), str(disk)])
    assert out["ok"]
    blob = b.objects["daily/2026-09-24/altaha_accounts.db.gz"]
    con = _restore(blob, tmp_path_factory.mktemp("r"))
    assert con.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 2
    assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_every_top_level_file_goes_and_side_files_and_caches_do_not(disk, scratch):
    b = FakeBucket()
    backup.run(client=b, data_dir=str(disk), today=dt.date(2026, 9, 24),
               scratch=[str(scratch), str(disk)])
    names = sorted(k.split("/")[-1] for k in b.objects)
    assert names == ["altaha_accounts.db.gz", "manifest.json", "tracked.json.gz"]
    assert gzip.decompress(b.objects["daily/2026-09-24/tracked.json.gz"]) == b'{"ideas": []}'
    assert not (scratch / backup._SCRATCH).exists()        # scratch cleaned up


def test_old_days_are_pruned_after_a_good_night(disk, scratch):
    b = FakeBucket()
    b.objects["daily/2026-08-01/tracked.json.gz"] = b"old"
    b.objects["daily/2026-09-01/tracked.json.gz"] = b"recent"
    out = backup.run(client=b, data_dir=str(disk), today=dt.date(2026, 9, 24),
                     scratch=[str(scratch)])
    assert out["pruned"] == 1
    assert "daily/2026-08-01/tracked.json.gz" not in b.objects
    assert "daily/2026-09-01/tracked.json.gz" in b.objects


def test_a_bad_night_never_prunes_the_last_good_copies(disk, scratch):
    b = FakeBucket(fail_on={"altaha_accounts"})
    b.objects["daily/2026-08-01/altaha_accounts.db.gz"] = b"the last good copy"
    out = backup.run(client=b, data_dir=str(disk), today=dt.date(2026, 9, 24),
                     scratch=[str(scratch)])
    assert not out["ok"] and out["errors"][0]["name"] == "altaha_accounts.db"
    assert b.deleted == []
    assert "daily/2026-09-24/tracked.json.gz" in b.objects     # the rest still went


# --- Where the temporary copies go ------------------------------------------
#
# From 8 to 13 November 2026 every night failed with "database or disk is
# full": the copies were made on the data disk itself, which held 692 MB of a
# 1 GB disk, and the 307 MB point-in-time store needs that much free again.

def _free(monkeypatch, room):
    """Pretend each folder has the free space given in MB; others plenty."""
    real = backup.shutil.disk_usage

    def fake(path):
        for p, mb in room.items():
            if os.path.realpath(path) == os.path.realpath(p):
                return real(path)._replace(free=mb * 1024 * 1024)
        return real(path)
    monkeypatch.setattr(backup.shutil, "disk_usage", fake)


def test_copies_are_made_off_the_data_disk_when_somewhere_else_has_room(disk, scratch):
    b = FakeBucket()
    out = backup.run(client=b, data_dir=str(disk), today=dt.date(2026, 11, 16),
                     scratch=[str(scratch), str(disk)])
    assert out["ok"]
    assert {f["scratch"] for f in out["files"]} == {str(scratch)}
    assert not (disk / backup._SCRATCH).exists()


def test_a_full_place_is_passed_over_for_the_next(disk, scratch, monkeypatch):
    _free(monkeypatch, {str(scratch): 1})          # 1 MB: less than the margin
    out = backup.run(client=FakeBucket(), data_dir=str(disk),
                     today=dt.date(2026, 11, 16), scratch=[str(scratch), str(disk)])
    assert out["ok"]
    assert {f["scratch"] for f in out["files"]} == {str(disk)}


def test_a_folder_in_memory_is_never_used(disk, scratch, monkeypatch):
    real = backup._fs_type
    monkeypatch.setattr(backup, "_fs_type", lambda p: "tmpfs"
                        if os.path.realpath(p) == os.path.realpath(str(scratch)) else real(p))
    out = backup.run(client=FakeBucket(), data_dir=str(disk),
                     today=dt.date(2026, 11, 16), scratch=[str(scratch), str(disk)])
    assert {f["scratch"] for f in out["files"]} == {str(disk)}


def test_no_room_anywhere_names_each_place_and_the_rest_still_go(disk, scratch, monkeypatch):
    (disk / "altaha_pit.db").write_bytes(b"x" * (2 * 1024 * 1024))
    b = FakeBucket()
    b.objects["daily/2026-08-01/altaha_pit.db.gz"] = b"the last good copy"
    # Room for the small files, not for a copy of the 2 MB one.
    _free(monkeypatch, {str(scratch): 17, str(disk): 17})
    out = backup.run(client=b, data_dir=str(disk), today=dt.date(2026, 11, 16),
                     scratch=[str(scratch), str(disk)])
    assert not out["ok"]
    [err] = out["errors"]
    assert err["name"] == "altaha_pit.db"
    assert "no room" in err["error"] and str(scratch) in err["error"]
    assert "daily/2026-11-16/tracked.json.gz" in b.objects
    assert b.deleted == []                         # a bad night prunes nothing


def test_the_manifest_says_how_full_the_data_disk_is(disk, scratch):
    out = backup.run(client=FakeBucket(), data_dir=str(disk),
                     today=dt.date(2026, 11, 16), scratch=[str(scratch)])
    d = out["disk"]
    assert d["total"] > 0 and d["used"] + d["free"] <= d["total"]
    assert 0 <= d["used_pct"] <= 100


def test_scratch_prefers_temp_then_code_and_the_data_disk_last(tmp_path, monkeypatch):
    monkeypatch.delenv("BACKUP_SCRATCH", raising=False)
    bases = backup.scratch_bases(str(tmp_path))
    assert bases[0] == backup.tempfile.gettempdir()
    assert bases[-1] == str(tmp_path)
    monkeypatch.setenv("BACKUP_SCRATCH", "/somewhere")
    assert backup.scratch_bases(str(tmp_path))[0] == "/somewhere"


def test_the_filesystem_is_read_from_the_longest_matching_mount(tmp_path, monkeypatch):
    mounts = tmp_path / "mounts"
    mounts.write_text("/dev/vda / ext4 rw 0 0\n"
                      "tmpfs /tmp tmpfs rw 0 0\n"
                      "/dev/vdb /data ext4 rw 0 0\n")
    monkeypatch.setattr(backup, "_MOUNTS", str(mounts))
    monkeypatch.setattr(backup.os.path, "realpath", lambda p: p)
    assert backup._fs_type("/tmp/x") == "tmpfs"
    assert backup._fs_type("/tmpfoo") == "ext4"      # a prefix is not a mount
    assert backup._fs_type("/data") == "ext4"
    assert backup._fs_type("/opt/render/project") == "ext4"


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


_CFG = {"R2_ACCOUNT_ID": "abc", "R2_ACCESS_KEY_ID": "k", "R2_SECRET_ACCESS_KEY": "s",
        "R2_BUCKET": "b", "missing": [], "endpoint": "https://abc.r2.cloudflarestorage.com"}


def test_a_sized_listing_reads_each_object_and_follows_pages():
    """The shape R2 and S3 answer ListObjectsV2 with: one <Contents> each."""
    http = FakeHTTP([
        "<ListBucketResult><IsTruncated>true</IsTruncated>"
        "<Contents><Key>bhavcopy/cm/2026/20261113.csv.zip</Key><LastModified>x</LastModified>"
        "<ETag>&quot;e&quot;</ETag><Size>182344</Size></Contents>"
        "<NextContinuationToken>t</NextContinuationToken></ListBucketResult>",
        "<ListBucketResult><IsTruncated>false</IsTruncated>"
        "<Contents><Key>bhavcopy/absent.json</Key><Size>90</Size></Contents></ListBucketResult>",
    ])
    assert backup.R2(_CFG, session=http).list_objects("bhavcopy/") == [
        ("bhavcopy/cm/2026/20261113.csv.zip", 182344), ("bhavcopy/absent.json", 90)]


def test_reading_a_key_that_is_not_there_is_none_not_an_error():
    class One:
        def __init__(self, code, body):
            self.code, self.body = code, body

        def request(self, method, url, headers=None, data=None, timeout=None):
            class R:
                pass
            r = R()
            r.status_code, r.content, r.text = self.code, self.body, self.body.decode()
            return r
    assert backup.R2(_CFG, session=One(404, b"<Error/>")).get("bhavcopy/absent.json") is None
    assert backup.R2(_CFG, session=One(200, b'{"cm":[]}')).get("bhavcopy/absent.json") == b'{"cm":[]}'
    with pytest.raises(RuntimeError):
        backup.R2(_CFG, session=One(403, b"denied")).get("bhavcopy/absent.json")


def test_unconfigured_says_which_variables_are_missing(monkeypatch):
    for k in ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("R2_BUCKET", "altaha-backups")
    assert backup.config()["missing"] == ["R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID",
                                          "R2_SECRET_ACCESS_KEY"]
    with pytest.raises(RuntimeError):
        backup.R2()
