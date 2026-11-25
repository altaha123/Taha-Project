"""
backfill_money_flow.py — fill Money Flow's history, a slice at a time

Money Flow needs two years behind it before it can say anything: 48 NSDL
fortnights for the flow trends, and about 500 sessions of NSE index closes for
relative strength and the rotation chart. This reads them.

TWO WAYS TO RUN IT

  Against the live API (the usual one: the database is on Render's disk):

      python backend/backfill_money_flow.py --api https://taha-project.onrender.com --key $ADMIN_KEY

  Here, into DATA_DIR (a laptop, or a shell on the instance):

      DATA_DIR=/data python backend/backfill_money_flow.py

Either way it calls the same code the evening job calls
(money_flow.run_backfill), in bounded slices, until nothing remains. It is
idempotent: every row is keyed on what it is, a day already read is not asked
for again, and stopping it half way loses nothing. Run it again to carry on.

WHAT IT CANNOT FILL
  · Daily FII/DII before the first evening the site recorded. NSE publishes
    the latest session only and has no by-date archive, so that record starts
    when the job starts.
  · Bulk and block deals, where NSE's history API refuses the address (it
    refuses most datacenter addresses). The slice says so and carries on; the
    daily file fills the record from then on.

--delivery-days N also reads N days of NSE's full bhavcopy into special.py's
panels, which breadth and stock-level accumulation are measured from. The
live instance keeps those itself; this is for a run on a laptop.
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


def _line(summary):
    steps = summary.get("steps") or {}
    n, i, d = steps.get("nsdl") or {}, steps.get("indices") or {}, steps.get("deals_history") or {}
    c = steps.get("compute") or {}
    return ("nsdl +%s reports (%s rows, %s left) | index +%s days (%s absent, %s refused, %s left) | "
            "deals +%s%s | scored %s sectors as of %s"
            % (n.get("read", 0), n.get("rows", 0), n.get("remaining", "?"),
               i.get("stored", 0), i.get("absent", 0), i.get("blocked", 0), i.get("remaining", "?"),
               d.get("new", 0), " (refused)" if d.get("refused") else "",
               c.get("sectors_scored", "-"), c.get("as_of", "-")))


def _local(months, limit):
    import money_flow
    return money_flow.run_backfill(months=months, limit=limit)


def _remote(api, key, months, limit):
    url = "%s/admin/moneyflow/run?%s" % (api.rstrip("/"), urllib.parse.urlencode(
        {"job": "backfill", "months": months, "limit": limit}))
    req = urllib.request.Request(url, method="POST", headers={
        "X-Admin-Key": key, "User-Agent": "altaha-backfill"})
    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:300]
        return {"ok": False, "errors": ["HTTP %s: %s" % (e.code, body)], "remaining": None,
                "fatal": e.code in (401, 404)}
    except Exception as e:
        return {"ok": False, "errors": ["%s: %s" % (type(e).__name__, e)], "remaining": None}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Fill Money Flow's history in slices.")
    ap.add_argument("--months", type=int, default=24, help="how far back (default 24)")
    ap.add_argument("--limit", type=int, default=60, help="index days per slice (default 60)")
    ap.add_argument("--max-slices", type=int, default=120)
    ap.add_argument("--api", default="", help="base URL of the live API; omit to run here")
    ap.add_argument("--key", default="", help="the admin key, with --api")
    ap.add_argument("--delivery-days", type=int, default=0,
                    help="local runs only: also read this many days of delivery panels")
    args = ap.parse_args(argv)

    if args.delivery_days and not args.api:
        import special
        print("Reading %d days of NSE's full bhavcopy into the delivery panels ..." % args.delivery_days)
        special.refresh(days_back=args.delivery_days)
        st = special.status()
        print("  panels hold %s sessions, %s to %s" % (st.get("cached_sessions"), st.get("from"), st.get("to")))

    stuck, last_left = 0, None
    for n in range(1, args.max_slices + 1):
        summary = (_remote(args.api, args.key, args.months, args.limit) if args.api
                   else _local(args.months, args.limit))
        if summary.get("busy"):
            print("slice %d: a job is already running, waiting" % n)
            time.sleep(20)
            continue
        print("slice %d: %s" % (n, _line(summary)))
        for e in summary.get("errors") or []:
            print("    ! %s" % e)
        if summary.get("fatal"):
            return 2
        left = summary.get("remaining")
        if left == 0:
            print("Done. Nothing remains.")
            return 0
        # The same amount left three slices running is a source refusing us,
        # not work in progress.
        stuck = stuck + 1 if left == last_left else 0
        last_left = left
        if stuck >= 3:
            print("Stopped: %s still to read and no progress in three slices. "
                  "A source is refusing this address; run it again later." % left)
            return 1
        time.sleep(1)
    print("Stopped after %d slices with %s still to read. Run it again to carry on."
          % (args.max_slices, last_left))
    return 1


if __name__ == "__main__":
    sys.exit(main())
