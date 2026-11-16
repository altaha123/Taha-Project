"""
bhav_archive.py — every NSE daily bhavcopy for five years, kept in R2

WHY
The site kept 400 sessions of the exchange's daily file (special.py, on the
1 GB data disk) and nothing older. The Ideas study downloaded 2017-2026 once,
into a folder that is not in git and not on the server, so the only long run of
the exchange's own prices lived on whichever machine last ran it. This keeps
the files themselves, as NSE published them, in the same private R2 bucket the
nightly backup uses: five years back from today, and every new session added
each evening.

WHAT IS KEPT, PER SESSION
  bhavcopy/cm/YYYY/YYYYMMDD.csv.zip   the bhavcopy: every security that
      traded, with ISIN, open, high, low, close, previous close, volume and
      value. Stored exactly as NSE serves it (a zip). Before 8 July 2024 that
      is the old cmDDMONYYYYbhav.csv; from that day the UDiFF
      BhavCopy_NSE_CM file, which has other column names (read() maps both).
  bhavcopy/full/YYYY/YYYYMMDD.csv.gz  sec_bhavdata_full: the same session
      with delivered quantity and delivery %, which nothing else carries.
      NSE serves it as plain CSV; it is gzipped here.
  bhavcopy/absent.json                days NSE has no file for (weekends,
      holidays), so they are asked for once and not every night.

The files are unadjusted for splits and bonuses, as published. A reader that
needs an adjusted series adjusts it (research/ideas_study.py shows how).

WHERE IT RUNS
On the API, like the backup: the R2 keys are already there, NSE's archive
already answers that host (special.py reads the same files from it every day),
and GitHub needs no new secrets. Nothing is written to the data disk: each file
is held in memory (a few hundred KB), checked, uploaded and dropped.

HOW
POST /admin/bhavcopy/archive does a bounded slice: up to `limit` days, newest
first, within a time budget, and says how many remain. The workflow
bhavcopy.yml calls it after each close until nothing is left, so the first
night backfills five years and every night after adds one day.

A day is written off as having no file only on a 404 (or the archive's small
not-found page), never on a refusal or a timeout: the archive refuses good
requests now and then, and a day written off is never asked for again. A day
younger than SETTLE_DAYS is never written off, because its file may not be out.
Weekends are tried once, because the exchange does trade on some (Diwali's
Muhurat session, the Saturday budget session) and a complete record has them.

Data terms: the files are NSE's. This is the site's own record of public
exchange files; showing them to the public, or charging for what is built on
them, is a question for NSE's data policy, not for this module.
"""

import csv
import datetime as dt
import gzip
import io
import json
import os
import threading
import time
import zipfile

import backup

PREFIX = "bhavcopy/"
ABSENT_KEY = PREFIX + "absent.json"
KINDS = ("cm", "full")
YEARS = int(os.environ.get("BHAV_ARCHIVE_YEARS", "5") or 5)
UDIFF_FROM = dt.date(2024, 7, 8)      # NSE's new bhavcopy format starts here
# Today's and yesterday's files may not be out yet (NSE publishes the same
# evening, now and then the next morning), so a 404 for them is not written
# off. Older than that, a 404 means no session. Wider than two days, every
# weekend would sit in the window and be asked for again on every call.
SETTLE_DAYS = 2
HOSTS = ("https://nsearchives.nseindia.com", "https://archives.nseindia.com")
NOT_FOUND_BYTES = 5000                # the archive's not-found page is smaller
PAUSE = float(os.environ.get("BHAV_ARCHIVE_PAUSE", "0.2") or 0.2)
BLOCKED_STOP = 5                      # refusals in a row before a slice gives up
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

_lock = threading.Lock()
_last = {"result": None}


# ---------------------------------------------------------------------------
# Names
# ---------------------------------------------------------------------------

def key(kind, day):
    ext = "csv.zip" if kind == "cm" else "csv.gz"
    return "%s%s/%d/%s.%s" % (PREFIX, kind, day.year, day.strftime("%Y%m%d"), ext)


def day_of(k):
    """The (kind, date) a key holds, or None for anything else."""
    parts = k[len(PREFIX):].split("/") if k.startswith(PREFIX) else []
    if len(parts) != 3 or parts[0] not in KINDS:
        return None
    try:
        return parts[0], dt.datetime.strptime(parts[2][:8], "%Y%m%d").date()
    except ValueError:
        return None


def source_path(kind, day):
    """Where NSE publishes the file, after the host."""
    if kind == "full":
        return "/products/content/sec_bhavdata_full_%s.csv" % day.strftime("%d%m%Y")
    if day < UDIFF_FROM:
        return ("/content/historical/EQUITIES/%d/%s/cm%sbhav.csv.zip"
                % (day.year, day.strftime("%b").upper(), day.strftime("%d%b%Y").upper()))
    return "/content/cm/BhavCopy_NSE_CM_0_0_0_%s_F_0000.csv.zip" % day.strftime("%Y%m%d")


def window(today=None, years=None):
    """The first and last day the archive is meant to hold."""
    today = today or dt.date.today()
    years = YEARS if years is None else years
    try:
        start = today.replace(year=today.year - years)
    except ValueError:                                   # 29 February
        start = today.replace(year=today.year - years, day=28)
    return start, today


# ---------------------------------------------------------------------------
# Reading a file: the check before it is stored, and the reader after
# ---------------------------------------------------------------------------

# Column names in each format, normalised. Only the symbol and the close are
# required: they are the two that every reader of these files in this project
# has relied on (special.py, research/ideas_study.py), so a file without them is
# not a bhavcopy, whatever its status code said.
_COLUMNS = {
    "symbol": ("SYMBOL", "TckrSymb"),
    "series": ("SERIES", "SctySrs"),
    "isin": ("ISIN",),
    "open": ("OPEN", "OpnPric", "OPEN_PRICE"),
    "high": ("HIGH", "HghPric", "HIGH_PRICE"),
    "low": ("LOW", "LwPric", "LOW_PRICE"),
    "close": ("CLOSE", "ClsPric", "CLOSE_PRICE"),
    "prev_close": ("PREVCLOSE", "PrvsClsgPric", "PREV_CLOSE"),
    "volume": ("TOTTRDQTY", "TtlTradgVol", "TTL_TRD_QNTY"),
    "value": ("TOTTRDVAL", "TtlTrfVal"),
    "turnover_lacs": ("TURNOVER_LACS",),
    "trades": ("TOTALTRADES", "TtlNbOfTxsExctd", "NO_OF_TRADES"),
    "vwap": ("AVG_PRICE",),
    "deliv_qty": ("DELIV_QTY",),
    "deliv_pct": ("DELIV_PER",),
}


def _text(kind, body):
    """The CSV text inside a stored or downloaded file, or None."""
    try:
        if body[:2] == b"PK":
            z = zipfile.ZipFile(io.BytesIO(body))
            names = [n for n in z.namelist() if n.lower().endswith(".csv")] or z.namelist()
            raw = z.read(names[0])
        elif body[:2] == b"\x1f\x8b":
            raw = gzip.decompress(body)
        else:
            raw = body
        return raw.decode("utf-8-sig", errors="replace")
    except Exception:
        return None


def _rows(text):
    """Header-mapped rows of a bhavcopy CSV: dicts keyed by the names above."""
    reader = csv.reader(io.StringIO(text))
    try:
        header = [h.strip() for h in next(reader)]
    except StopIteration:
        return None, iter(())
    where = {}
    for name, options in _COLUMNS.items():
        for o in options:
            if o in header:
                where[name] = header.index(o)
                break
    if "symbol" not in where or "close" not in where:
        return None, iter(())

    def gen():
        for row in reader:
            if len(row) < len(header):
                continue
            yield {n: row[i].strip() for n, i in where.items()}
    return where, gen()


def _number(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def count_rows(kind, body):
    """Rows with a symbol and a numeric close. 0 means not a bhavcopy."""
    text = _text(kind, body)
    if text is None:
        return 0
    where, rows = _rows(text)
    if where is None:
        return 0
    return sum(1 for r in rows if r["symbol"] and _number(r["close"]) is not None)


def frame(kind, body):
    """
    One stored file as a DataFrame with the column names above, whichever
    format it came in. Numbers are floats; value is in rupees in every format
    (sec_bhavdata_full publishes lakh, which is converted).
    """
    import pandas as pd
    text = _text(kind, body)
    if text is None:
        return None
    where, rows = _rows(text)
    if where is None:
        return None
    df = pd.DataFrame(list(rows))
    if not len(df):
        return df
    for c in df.columns:
        if c not in ("symbol", "series", "isin"):
            df[c] = pd.to_numeric(df[c], errors="coerce")
    if "turnover_lacs" in df.columns:
        df["value"] = df.pop("turnover_lacs") * 1e5
    return df


def read(day, kind="cm", client=None):
    """One session from the archive as a DataFrame, or None if not held."""
    client = client or backup.R2()
    body = client.get(key(kind, day))
    return None if body is None else frame(kind, body)


# ---------------------------------------------------------------------------
# Fetching from NSE
# ---------------------------------------------------------------------------

def _session():
    """curl_cffi impersonating Chrome where available (NSE's WAF reads the TLS
    handshake; see nse_http.py), plain requests otherwise."""
    try:
        from curl_cffi import requests as cr
        s = cr.Session(impersonate="chrome")
    except Exception:
        import requests
        s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept": "*/*",
                      "Referer": "https://www.nseindia.com/"})
    return s


def fetch(http, kind, day):
    """
    One file from NSE, as (state, body, url).

    state is "ok" (body is a checked bhavcopy), "absent" (NSE has no such
    file) or "blocked" (refused, timed out, or something that is not a
    bhavcopy came back: try again another time). The second host is asked only
    when the first refuses; a 404 is an answer.
    """
    path = source_path(kind, day)
    state, last_url = "blocked", None
    for host in HOSTS:
        url = last_url = host + path
        try:
            r = http.get(url, timeout=40)
        except Exception:
            state = "blocked"
            continue
        code, body = r.status_code, r.content or b""
        if code == 404:
            return "absent", None, url
        if code == 200:
            if count_rows(kind, body) > 0:
                return "ok", body, url
            if len(body) < NOT_FOUND_BYTES:
                return "absent", None, url
        state = "blocked"
    return state, None, last_url


# ---------------------------------------------------------------------------
# The archive
# ---------------------------------------------------------------------------

def _load_absent(client):
    try:
        body = client.get(ABSENT_KEY)
        d = json.loads(body) if body else {}
    except Exception:
        d = {}
    return {k: set(d.get(k) or []) for k in KINDS}


def _held(client):
    """{kind: {date: bytes}} for every file the archive holds."""
    held = {k: {} for k in KINDS}
    for k, size in client.list_objects(PREFIX):
        got = day_of(k)
        if got:
            held[got[0]][got[1]] = size
    return held


def _needs(day, held, absent):
    """The kinds still to fetch for a day: the bhavcopy first, and the
    delivery file only once the bhavcopy says the day traded."""
    iso = day.isoformat()
    if day not in held["cm"]:
        return [] if iso in absent["cm"] else ["cm", "full"]
    if day not in held["full"] and iso not in absent["full"]:
        return ["full"]
    return []


def todo(held, absent, today=None, years=None):
    """Days in the window with something still to fetch, newest first."""
    start, end = window(today, years)
    out, day = [], end
    while day >= start:
        if _needs(day, held, absent):
            out.append(day)
        day -= dt.timedelta(days=1)
    return out


def run(client=None, http=None, limit=40, budget_s=240, today=None, years=None,
        recheck=False, sleep=time.sleep):
    """
    Fetch up to `limit` missing days, newest first, and store them.

    recheck forgets which days were written off as having no file, so they are
    asked for again (for a day wrongly written off). Returns what was stored,
    what was found absent, what was refused, and how many days remain.
    """
    if not _lock.acquire(blocking=False):
        return {"ok": False, "error": "an archive run is already going"}
    try:
        client = client or backup.R2()
        today = today or dt.date.today()
        started = time.time()
        held = _held(client)
        absent = {k: set() for k in KINDS} if recheck else _load_absent(client)
        absent_before = {k: set(v) for k, v in absent.items()}
        days = todo(held, absent, today, years)
        settle = today - dt.timedelta(days=SETTLE_DAYS)
        http = http or _session()

        stored = {k: 0 for k in KINDS}
        stored_bytes, blocked, done, waiting = 0, 0, 0, 0
        refused_in_a_row, stopped = 0, "finished"
        errors = []
        for day in days:
            if done + waiting >= limit:
                stopped = "limit"
                break
            if time.time() - started > budget_s:
                stopped = "time"
                break
            if refused_in_a_row >= BLOCKED_STOP:
                stopped = "refused"
                break
            resolved, young_absent = True, False
            for kind in _needs(day, held, absent):
                if kind == "full" and day not in held["cm"]:
                    break                       # the bhavcopy did not land
                state, body, url = fetch(http, kind, day)
                sleep(PAUSE)
                if state == "ok":
                    refused_in_a_row = 0
                    if kind == "cm":
                        data, ctype = body, "application/zip"
                    else:
                        data, ctype = gzip.compress(body, 6), "application/gzip"
                    try:
                        client.put_bytes(key(kind, day), data, content_type=ctype)
                    except Exception as e:
                        errors.append({"day": day.isoformat(), "kind": kind,
                                       "error": ("%s: %s" % (type(e).__name__, e))[:200]})
                        resolved = False
                        break
                    held[kind][day] = len(data)
                    stored[kind] += 1
                    stored_bytes += len(data)
                elif state == "absent":
                    refused_in_a_row = 0
                    if day > settle:
                        young_absent = True     # not out yet, perhaps
                        resolved = False
                        break
                    absent[kind].add(day.isoformat())
                    if kind == "cm":
                        break                   # no trading, no delivery file
                else:
                    blocked += 1
                    refused_in_a_row += 1
                    resolved = False
                    sleep(PAUSE * 10)           # back off rather than hammer it
                    break
            if resolved:
                done += 1
            elif young_absent:
                waiting += 1

        changed = any(absent[k] != absent_before[k] for k in KINDS)
        if changed or recheck:
            client.put_bytes(ABSENT_KEY, json.dumps(
                {k: sorted(absent[k]) for k in KINDS}, separators=(",", ":")).encode("utf-8"))

        left = todo(held, absent, today, years)
        young = sum(1 for d in left if d > settle)
        out = {"ok": not errors, "stored": stored, "stored_bytes": stored_bytes,
               "absent_found": {k: len(absent[k] - absent_before[k]) for k in KINDS},
               "blocked": blocked, "days_done": done,
               "remaining": len(left) - young, "waiting_for_nse": young,
               "stopped": stopped, "errors": errors,
               "window": [d.isoformat() for d in window(today, years)],
               "seconds": round(time.time() - started, 1)}
        _last["result"] = out
        return out
    finally:
        _lock.release()


def status(client=None, today=None, years=None):
    """What the archive holds: days, span, size, and what is still to fetch."""
    client = client or backup.R2()
    today = today or dt.date.today()
    held = _held(client)
    absent = _load_absent(client)
    out = {"window": [d.isoformat() for d in window(today, years)],
           "absent": {k: len(absent[k]) for k in KINDS},
           "last_run": _last["result"]}
    for kind in KINDS:
        days = sorted(held[kind])
        out[kind] = {"days": len(days),
                     "first": days[0].isoformat() if days else None,
                     "last": days[-1].isoformat() if days else None,
                     "bytes": sum(held[kind].values())}
    left = todo(held, absent, today, years)
    settle = today - dt.timedelta(days=SETTLE_DAYS)
    out["remaining"] = sum(1 for d in left if d <= settle)
    out["waiting_for_nse"] = len(left) - out["remaining"]
    out["complete"] = out["remaining"] == 0
    return out
