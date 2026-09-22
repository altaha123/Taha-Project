"""
Altaha Special — Delivery-Weighted Momentum
===========================================

WHAT THIS IS, AND WHY IT IS NOT ANOTHER MOMENTUM SCREEN

Every momentum screen in India ranks stocks by how much they went up. This one
ranks them by how much they went up ON DAYS WHEN OWNERSHIP ACTUALLY CHANGED
HANDS.

NSE publishes, per stock per day, what share of the traded volume was actually
DELIVERED — settled into somebody's demat account — rather than bought and sold
again the same session. That field (DELIV_PER in the full bhavcopy) does not
exist in a Yahoo or Bloomberg OHLCV feed. It is specific to this market, it is
free, and as far as I can find nothing in the retail tooling here uses it
systematically.

The signal is:

    S = sum over the last 252 sessions of  ( daily return x delivery share )

Two stocks both up 60% score very differently. The one that rose on days when
70% of volume was delivered has been ACCUMULATED by people who wanted to own
it. The one that rose on 20%-delivery days was churned by traders who were flat
by 3:30pm. Same return, different future.

WHAT THE BACKTEST ACTUALLY FOUND — including the part that did not work

Tested on the 100 most-liquid NSE names, point-in-time, March 2021 to August
2026 (delivery history begins 2020), net of a 0.49% round trip:

                              CAGR     Sharpe   MaxDD    worst year
    delivery-weighted         23.05%   1.14     -26.3%   +0.4%
    residual momentum         21.52%   1.05     -30.7%   -7.1%
    NIFTY 50                  10.22%   0.77     -17.2%

BUT: across 24 parameter settings the CAGR advantage held in only 5, while the
DRAWDOWN improvement held in 24 of 24 — and in 12 of 12 gate variants. So the
honest claim is narrow and it is the one made here:

    Delivery weighting is a RISK improvement, not a return improvement.
    It reliably makes the ride shallower. It does not reliably make it richer.

The headline 23.05% sits near the top of the 24-setting range (median 20.02%);
quoting it as the expected return would be quoting a lucky parameter pick.

LIMITS, STATED WHERE THE CODE IS RATHER THAN IN A FOOTNOTE
  · Delivery data begins in 2020, so the test covers 5.5 years and ONE regime.
  · The universe is today's liquid list, so survivorship still inflates it.
  · The signal's information coefficient was +0.031 with a t-statistic of 1.53
    — the right direction, NOT statistically significant on 64 observations.
  · This ranks stocks on published exchange data. It is not advice, and it is
    not a prediction.
"""

import datetime as dt
import io
import json
import math
import os
import threading
import time

import warnings

import numpy as np
import pandas as pd

try:
    import requests
except Exception:                                        # pragma: no cover
    requests = None

from data_source import resolve

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("DATA_DIR", "").strip() or HERE
try:
    os.makedirs(DATA_DIR, exist_ok=True)
except Exception:
    DATA_DIR = HERE
CACHE = os.path.join(DATA_DIR, "delivery_panels_v3.pkl")
# Days the archive genuinely has no file for — holidays, mostly. Remembered so
# the builder stops asking for them on every pass.
BLANKS = os.path.join(DATA_DIR, "delivery_blank_days.json")

# MEMORY. This runs on a 512 MB Render instance that already carries a ~99 MB
# floor of numpy, pandas and yfinance before a line of app code runs, and whose
# scan path already has an out-of-memory handler in main.py. The first version
# of this module cached the bhavcopy in LONG format — one row per symbol per
# day, with the symbol string repeated — and measured 299 MB resident at 305
# sessions, on track for ~736 MB at its own three-year retention. It would have
# OOM-ed the box on its own.
#
# Three changes, each measured:
#   1. Store WIDE float32 panels, never the long frame. The repeated symbol
#      strings were most of the 86 MB.
#   2. Keep 400 sessions, not 1100. The signal needs 252 + 21; the rest was
#      being carried for nothing.
#   3. Prune to symbols that clear the turnover floor. Roughly 2,950 symbols
#      trade on any given day and about 600 are rankable; the other 2,350 were
#      being stored so they could be filtered out later.
RETAIN_SESSIONS = int(os.environ.get("SPECIAL_RETAIN", "400") or 400)
PANEL_FIELDS = ("deliv", "qty", "vwap", "close", "high", "low")
# Bumped when a change alters what a stored SESSION contains rather than how
# it is laid out. 4 is "every EQ symbol, not only the rankable ones". A store
# without it was written by the pruning builder and its days are refetched.
WIDE_SCHEMA = 4

LOOKBACK = 252          # sessions in the signal window
SKIP = 21               # ignore the most recent month
BOOK = 20               # names published
MIN_SESSIONS = 120      # nothing is published below this
BUILD_CHUNK = 20        # sessions fetched per pass before the cache is written
BLANK_SETTLE_DAYS = 3   # today's file lands after the close, so a young day is
                        # never written off as a holiday
# Rs 25 crore, not 5. At 5 the first live run ranked MON100 — an ETF trading
# Rs 11 crore — above every real company on the list. A screen that surfaces
# something you cannot buy in size is worse than one that returns fewer names.
MIN_TURNOVER_CR = float(os.environ.get("SPECIAL_MIN_TURNOVER_CR", "25") or 25)

# ETFs and fund units clear the EQ series filter and then dominate signals like
# calmness and delivery share, because a fund unit is structurally calm and
# almost fully delivered. They are not companies and do not belong in a stock
# screener.
FUND_PAT = ("ETF", "BEES", "IETF", "MON100", "MAFANG", "GOLDCASE", "SILVER",
            "LIQUID", "GSEC", "SDL", "NIFTYBEES", "JUNIORBEES", "MOM100")


def _is_fund(sym: str) -> bool:
    u = str(sym).upper()
    return any(p in u for p in FUND_PAT)
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

_lock = threading.Lock()
_state = {"panel": None, "built_at": None, "days": 0, "error": None}


# ---------------------------------------------------------------------------
# The delivery feed
# ---------------------------------------------------------------------------

def _session():
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept": "text/csv,*/*",
                      "Referer": "https://www.nseindia.com/"})
    return s


def _bhav(sess, day):
    """
    One day's full bhavcopy, as (frame, state).

    state is "ok", "blank" (a holiday, or today's file is not out yet — not an
    error) or "blocked" (the archive refused us). The distinction matters: the
    archive answers a perfectly good request with 403 every so often, and an
    earlier version counted that as a holiday. A day written off as a holiday
    is never asked for again, so every refusal became a permanent hole.
    """
    tag = day.strftime("%d%m%Y")
    url = f"https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{tag}.csv"
    try:
        r = sess.get(url, timeout=30)
        if r.status_code in (401, 403, 429, 500, 502, 503, 504):
            return None, "blocked"
        if r.status_code == 404 or len(r.content) < 5000:
            return None, "blank"
        r.raise_for_status()
        df = pd.read_csv(io.StringIO(r.text))
        df.columns = [c.strip() for c in df.columns]
        df["SERIES"] = df["SERIES"].astype(str).str.strip()
        df = df[df["SERIES"] == "EQ"]
        df["SYMBOL"] = df["SYMBOL"].astype(str).str.strip()
        for c in ("DELIV_PER", "TTL_TRD_QNTY", "AVG_PRICE", "CLOSE_PRICE",
                  "HIGH_PRICE", "LOW_PRICE"):
            df[c] = pd.to_numeric(df[c], errors="coerce")
        df = df.dropna(subset=["DELIV_PER", "CLOSE_PRICE"])
        df["date"] = pd.Timestamp(day)
        return df[["date", "SYMBOL", "DELIV_PER", "TTL_TRD_QNTY", "AVG_PRICE",
                   "CLOSE_PRICE", "HIGH_PRICE", "LOW_PRICE"]], "ok"
    except Exception:
        # A timeout or a half-read file is a day to come back for, not a
        # holiday.
        return None, "blocked"


def _load_blanks():
    try:
        with io.open(BLANKS, encoding="utf-8") as fh:
            return set(json.load(fh))
    except Exception:
        return set()


def _save_blanks(days):
    try:
        with io.open(BLANKS, "w", encoding="utf-8") as fh:
            json.dump(sorted(days), fh)
    except Exception:
        pass


def _missing(have, days_back, blanks):
    """Sessions inside the window that the cache does not hold, oldest first.

    Computed as a set difference rather than "everything after the last day I
    stored", so a day skipped because the archive was busy is picked up on the
    next pass instead of being lost behind the high-water mark.
    """
    today = dt.date.today()
    got = set()
    if have and have.get("close") is not None and len(have["close"]):
        got = {d.date() for d in have["close"].index}
    # A day held from before the store kept the whole exchange counts as
    # missing: it is on file, but for a fraction of the companies.
    got -= _thin_days(have)
    out, day = [], today - dt.timedelta(days=days_back)
    while day <= today:
        if (day.weekday() < 5 and day not in got
                and day.isoformat() not in blanks):
            out.append(day)
        day += dt.timedelta(days=1)
    return out


def refresh(days_back=420, max_days=None):
    """
    Fetch the sessions the cache is missing and fold them in.

    Incremental on purpose: a full build walks about 420 calendar days and
    takes minutes, every pass after that fetches only what it lacks. Pass
    max_days to do it a chunk at a time — the cache is written at the end of
    every call, so an instance that sleeps or restarts resumes from where it
    got to instead of starting over.

    Newest days are taken first: a book off the most recent 120 sessions is
    worth more than one waiting on a complete year.
    """
    if requests is None:
        _state["error"] = "requests unavailable"
        # Never hand the caller _state itself: it carries the panel, and the
        # route serialises whatever it gets back.
        return {"error": _state["error"], "built_at": _state["built_at"],
                "days": _state["days"], "fetched": 0, "blocked": 0,
                "remaining": 0}

    with _lock:
        have = _load_cache()
        blanks = _load_blanks()
        wanted = _missing(have, days_back, blanks)
        outstanding = len(wanted)
        if max_days:
            wanted = wanted[-max_days:]

        today = dt.date.today()
        rows, fetched, blocked = [], 0, 0
        if wanted:
            sess = _session()
            for day in wanted:
                got, state = _bhav(sess, day)
                if state == "ok":
                    rows.append(got)
                    fetched += 1
                elif state == "blocked":
                    blocked += 1
                    time.sleep(1.5)          # back off rather than hammer it
                elif day <= today - dt.timedelta(days=BLANK_SETTLE_DAYS):
                    blanks.add(day.isoformat())
                time.sleep(0.05)

        if rows:
            # Convert to panels in one pass and drop the long frame immediately;
            # holding both at once is the peak that matters on a 512 MB box.
            have = _merge(have, pd.concat(rows, ignore_index=True))
            del rows
            try:
                pd.to_pickle(have, CACHE)
            except Exception:
                pass
        _save_blanks(blanks)

        _state["panel"] = have
        _state["built_at"] = dt.datetime.now().isoformat(timespec="seconds")
        _state["days"] = 0 if not have else int(len(have["close"]))
        _state["error"] = None
        out = {k: v for k, v in _state.items() if k != "panel"}
        out.update({"fetched": fetched, "blocked": blocked,
                    "remaining": max(0, outstanding - fetched)})
        return out


# ---------------------------------------------------------------------------
# The builder
#
# The cache used to be filled only by an admin POST to /special/refresh. Nothing
# ever called it, so on a fresh disk the page read "not ready" forever and there
# was no path from that state to a book. It now fills itself, in chunks, the
# first time somebody opens the tab.
# ---------------------------------------------------------------------------

_build = {"running": False, "started_at": None, "fetched": 0, "blocked": 0,
          "remaining": None, "error": None, "last_start": 0.0}


def _build_worker(days_back):
    stalls = 0
    try:
        while True:
            r = refresh(days_back=days_back, max_days=BUILD_CHUNK)
            _build["fetched"] += r.get("fetched", 0)
            _build["blocked"] += r.get("blocked", 0)
            _build["remaining"] = r.get("remaining")
            if not r.get("remaining"):
                _build["error"] = None
                break
            if r.get("fetched"):
                stalls = 0
                continue
            # Nothing came back. Give the archive room, then try twice more
            # before leaving it for the next visitor.
            stalls += 1
            if stalls >= 3:
                _build["error"] = ("The exchange archive is refusing requests "
                                   "right now. It picks up where it stopped.")
                break
            time.sleep(20)
    except Exception as e:                                   # pragma: no cover
        _build["error"] = f"{type(e).__name__}: {str(e)[:90]}"
    finally:
        _build["running"] = False


def _rss_mb():
    """Resident memory in MB, or None off Linux."""
    try:
        with open("/proc/self/status") as fh:
            for line in fh:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) / 1024.0
    except Exception:
        pass
    return None


# Do not start a build when the process is already close to its ceiling. The
# builder fetches twenty bhavcopies and pivots them, which is a real spike on a
# 512 MB instance, and being killed mid-build helps nobody — the cache resumes
# either way, so waiting costs one visitor a few minutes and losing the process
# costs everyone the whole site.
BUILD_RSS_CEILING = int(os.environ.get("SPECIAL_RSS_CEILING_MB", "380") or 380)


def ensure_building(days_back=420):
    """Start a build if the cache is short or stale. Cheap and idempotent."""
    if requests is None or _build["running"]:
        return
    rss = _rss_mb()
    if rss is not None and rss > BUILD_RSS_CEILING:
        _build["error"] = (f"Holding {rss:.0f} MB of 512 — waiting for headroom "
                           "before fetching more. The cache resumes on its own.")
        return
    P = _load_cache()
    deep = bool(P and P.get("close") is not None
                and len(P["close"]) >= LOOKBACK + SKIP)
    # A store that is deep, current and complete has nothing to do but pick up
    # today's file once it lands, so it is asked rarely. A store with a
    # backlog is asked often: at twenty sessions a pass, the difference
    # between 60s and 900s is the difference between twenty minutes and four
    # hours of catching up.
    settled = deep and _is_current(P) and not _thin_days(P)
    since = time.time() - _build["last_start"]
    if since < (900 if settled else 60):
        return
    _build.update({"running": True, "last_start": time.time(), "fetched": 0,
                   "blocked": 0, "error": None,
                   "started_at": dt.datetime.now().isoformat(timespec="seconds")})
    threading.Thread(target=_build_worker, args=(days_back,), daemon=True,
                     name="altaha-special-build").start()


def _to_panels(long_df):
    """Long bhavcopy rows -> six wide float32 panels, pruned to what is
    actually rankable."""
    piv = lambda c: long_df.pivot_table(index="date", columns="SYMBOL",
                                        values=c, aggfunc="last").sort_index()
    P = {"deliv": piv("DELIV_PER"), "qty": piv("TTL_TRD_QNTY"),
         "vwap": piv("AVG_PRICE"), "close": piv("CLOSE_PRICE"),
         "high": piv("HIGH_PRICE"), "low": piv("LOW_PRICE")}
    out = {k: v.tail(RETAIN_SESSIONS).astype("float32") for k, v in P.items()}
    out["schema"] = WIDE_SCHEMA
    return out

    # THE PRUNE THAT USED TO BE HERE, AND WHY IT IS GONE
    #
    # This kept only symbols clearing half the turnover floor, on the grounds
    # that a stock which cannot appear in the book is pure cost to store. That
    # was written against the v2 LONG-format cache, which measured 299 MB at
    # 305 sessions because it repeated the symbol string on every row, and
    # there the argument was overwhelming.
    #
    # It stopped being true the moment the cache became wide float32, and
    # nobody went back to check. Measured on the live instance: 1,198 symbols
    # over 297 sessions is 8.6 MB. A session lists about 2,665 EQ symbols with
    # a delivery figure, of which roughly 820 clear the floor — so the prune
    # was discarding about 1,845 companies to save some 11 MB on a 512 MB box.
    #
    # Those 1,845 are the entire reason somebody opens a screener: the small
    # and mid caps nobody else covers. The whole exchange is now stored, and
    # the BOOK is narrowed instead, at rank time, by _rank_cols below. That
    # keeps the ranking identical — including its market proxy, which is the
    # cross-sectional median of the panel and would otherwise have moved the
    # moment the panel got wider.


def _rank_cols(P):
    """The symbols the BOOK may draw from: liquid enough to buy in size, and
    not a fund unit.

    This is the rule that used to decide what got stored. It now decides only
    what gets ranked, which is all it was ever really about — a stock's median
    turnover does not depend on which other stocks are in the file, so the set
    it returns is the same one the old prune produced.
    """
    turn_cr = (P["qty"] * P["vwap"]) / 1e7
    med = turn_cr.tail(120).median()
    cols = med[med >= MIN_TURNOVER_CR * 0.5].index
    return [c for c in cols if not _is_fund(c)]


def _for_ranking(P):
    """The panel as the book sees it. Narrowing BEFORE any cross-sectional
    statistic is computed is the whole point: _components takes the median
    return across columns as its market proxy, so a wider file would quietly
    change every score in the book."""
    cols = _rank_cols(P)
    return {k: (None if P.get(k) is None else P[k].reindex(columns=cols))
            for k in PANEL_FIELDS}, cols


def _is_current(have, slack_days=4):
    """Whether the store has caught up with the exchange.

    Deliberately loose: weekends, holidays and a file that lands after the
    close all mean the newest session is legitimately a few days old. This is
    only used to decide how often to look, so erring towards looking more
    often costs one HTTP request.
    """
    close = None if not have else have.get("close")
    if close is None or not len(close):
        return False
    newest = close.index.max()
    try:
        newest = newest.date()
    except AttributeError:
        pass
    return (dt.date.today() - newest).days <= slack_days


def _thin_days(have, floor_ratio=0.6):
    """Dates held from before the store kept the whole exchange.

    Handed back to the builder as if they were missing; _merge replaces them
    because it de-duplicates keep="last". Measured from the file rather than
    from a date in the code, so the backfill resumes if it is interrupted and
    stops on its own when nothing thin is left.

    WHY THIS ASKS WHICH CODE WROTE THE DAY, AND NOT HOW MANY SYMBOLS IT HOLDS.
    The first attempt compared each day's coverage against an absolute floor —
    a real session lists about 2,665 EQ symbols, a pruned one about 1,200, so
    1,800 looked like a safe line to draw. It is not a line that can be drawn.
    A store whose days all legitimately sit under the floor is thin for ever:
    every pass refetches every day, the worker never reaches remaining == 0,
    and the build loop does not terminate. test_builder_fills_the_cache_without
    _an_admin_call caught exactly that, which is the whole reason it exists.

    Narrowness is not a property of a day's size. It is a property of the code
    that wrote it, and that is what a schema marker is for. A store written by
    the pruning builder carries no marker, so all of its days are thin. Any
    merge since runs this module, which stamps one — and from then on the
    relative test is enough, because a pruned day sits well under half the
    coverage of a whole one. Both terminate: a rewritten day is never thin
    again, whatever its size.
    """
    dp = None if not have else have.get("deliv")
    if dp is None or not len(dp):
        return set()
    cover = dp.notna().sum(axis=1)
    if have.get("schema") != WIDE_SCHEMA:
        # Written before the store kept the whole exchange: all of it.
        return {d.date() for d in cover.index}
    best = float(cover.max() or 0)
    if best <= 0:
        return set()
    return {d.date() for d, c in cover.items() if float(c) < best * floor_ratio}


def _merge(old, new_long):
    """Fold newly fetched days into the stored panels."""
    fresh = _to_panels(new_long)
    if not old:
        return fresh
    out = {}
    for k in PANEL_FIELDS:
        a, b = old.get(k), fresh.get(k)
        if a is None: out[k] = b; continue
        if b is None: out[k] = a; continue
        m = pd.concat([a, b])
        m = m[~m.index.duplicated(keep="last")].sort_index()
        out[k] = m.tail(RETAIN_SESSIONS).astype("float32")
    out["schema"] = WIDE_SCHEMA
    return out


def _load_cache():
    if _state["panel"] is not None:
        return _state["panel"]
    try:
        if os.path.exists(CACHE):
            P = pd.read_pickle(CACHE)
            if isinstance(P, dict) and "close" in P:
                _state["panel"] = P
                _state["days"] = int(len(P["close"]))
                return P
            # A v2 long-format cache: convert once, then keep the panels.
            if isinstance(P, pd.DataFrame):
                P = _to_panels(P)
                _state["panel"] = P
                pd.to_pickle(P, CACHE)
                return P
    except Exception:
        pass
    return None


def status():
    P = _load_cache()
    close = None if not P else P.get("close")
    # Two different counts, and conflating them is how the old prune hid for
    # so long: `symbols` is what the store holds and can answer a delivery
    # lookup for; `rankable` is the much smaller set the book may draw from.
    try:
        rankable = 0 if not P else len(_rank_cols(P))
    except Exception:
        rankable = 0
    out = {"cached_sessions": 0 if close is None else int(len(close)),
           "symbols": 0 if close is None else int(close.shape[1]),
           "rankable": rankable,
           "backfilling": 0 if not P else len(_thin_days(P)),
           "built_at": _state["built_at"], "error": _state["error"],
           "cache_path": CACHE,
           "persistent": bool(os.environ.get("DATA_DIR", "").strip())}
    if close is not None and len(close):
        out["from"] = str(close.index.min().date())
        out["to"] = str(close.index.max().date())
        try:
            out["resident_mb"] = round(sum(
                P[k].memory_usage(deep=True).sum()
                for k in PANEL_FIELDS if P.get(k) is not None) / 1e6, 1)
        except Exception:
            pass
        out["ready"] = out["cached_sessions"] >= LOOKBACK + SKIP
    else:
        out["ready"] = False
    out["needed"] = MIN_SESSIONS
    out["building"] = bool(_build["running"])
    out["build"] = {k: _build[k] for k in
                    ("running", "started_at", "fetched", "blocked",
                     "remaining", "error")}
    if not out["persistent"]:
        out["warning"] = ("Delivery cache is not on a persistent disk, so it "
                          "rebuilds from scratch on every deploy. Mount a disk "
                          "and set DATA_DIR.")
    return out


# ---------------------------------------------------------------------------
# One company, session by session
# ---------------------------------------------------------------------------

DAILY_MAX = 250          # rows a single request may ask for
DAILY_DEFAULT = 60       # about a quarter of sessions


def _col_at(frame, sym, ts):
    """One cell, or None. Returns a float rather than a numpy scalar so the
    payload serialises without to_native having to walk it."""
    try:
        v = float(frame.at[ts, sym])
    except Exception:
        return None
    return None if v != v else v          # NaN is not a reading


def daily_delivery(symbol, days=DAILY_DEFAULT):
    """
    The delivery record for one company, day by day.

    The ranking above reduces a year of this to a single number, which is the
    right thing for a book of twenty names and the wrong thing for somebody
    who has just typed a symbol into a search box. "62% delivered yesterday
    against a 47% year" is a statement a reader can go and check against the
    company's own news. A percentile rank is not.

    Everything here is the exchange's own figure, read from the same full
    bhavcopy the signal is built on, with one exception that the payload
    labels rather than hides:

    DELIVERED QUANTITY IS DERIVED. The panel stores the published share
    (DELIV_PER) and the traded quantity, not the published DELIV_QTY, because
    a seventh float32 panel is real memory on a 512 MB instance for a column
    that is the product of two already held. NSE defines DELIV_PER as
    DELIV_QTY / TTL_TRD_QNTY x 100, so quantity x share recovers the filed
    number to within the rounding of a two-decimal percentage — close enough
    to show, not close enough to call filed. `delivered_qty_derived: true`
    travels with the payload and the page prints the caveat.

    The averages here are plain means over trailing windows. They are NOT the
    `delivery_trend` component of the ranking, which measures 63 sessions
    against 252 and skips the most recent month so the signal cannot read a
    price it would have traded on. Two numbers with the same name and
    different windows is how a page ends up disagreeing with itself, so these
    are named for their windows and the ranking's is left where it is.
    """
    sym = str(symbol or "").strip().upper().replace(".NS", "").replace(".BO", "")
    try:
        days = int(days)
    except Exception:
        days = DAILY_DEFAULT
    days = max(5, min(days, DAILY_MAX))

    if not sym:
        return {"available": False, "symbol": "", "reason": "no_symbol",
                "message": "No symbol was given."}

    # Same reasoning as rank_universe: asked on every lookup, not only when
    # the store is empty. Somebody searching a company the store cannot answer
    # for is exactly the moment to be filling it.
    ensure_building()
    P = _load_cache()
    if not P or P.get("deliv") is None or not len(P["deliv"]):
        # Say what is happening rather than returning an error for a store
        # that is merely young.
        st = status()
        have = int(st.get("cached_sessions", 0))
        return {"available": False, "symbol": sym, "reason": "building",
                "building": True, "sessions": have,
                "message": (st.get("build", {}).get("error")
                            or f"Reading the exchange delivery record — "
                               f"{have} sessions held so far. This fills "
                               f"itself; nothing here needs a retry."),
                "status": {k: st.get(k) for k in
                           ("cached_sessions", "from", "to", "ready")}}

    dp, qty, close, vwap = P["deliv"], P["qty"], P["close"], P["vwap"]

    if sym not in dp.columns:
        # The store now keeps every EQ symbol the bhavcopy lists, so being
        # small is no longer a reason to be missing. What is left is: a US
        # ticker (delivery is an NSE disclosure with no counterpart), a name
        # outside the equity series, a symbol that has changed, or a company
        # that has not traded inside the window held. The file cannot tell
        # those apart, so the message names them rather than guessing.
        return {"available": False, "symbol": sym, "reason": "not_covered",
                "covered_symbols": int(dp.shape[1]),
                "message": (f"No delivery record is held for {sym}. The "
                            f"exchange publishes this for NSE equity-series "
                            f"stocks only — a US listing has no equivalent — "
                            f"and the store carries the {int(dp.shape[1])} "
                            f"symbols that have traded in the sessions held.")}

    series = dp[sym].dropna()
    if not len(series):
        return {"available": False, "symbol": sym, "reason": "no_sessions",
                "message": (f"{sym} is in the store but has no session with a "
                            f"published delivery figure yet.")}

    rows = []
    for ts in series.tail(days).index[::-1]:          # newest first
        share = _col_at(dp, sym, ts)
        traded = _col_at(qty, sym, ts)
        avg_px = _col_at(vwap, sym, ts)
        delivered = None if (share is None or traded is None) else traded * share / 100.0
        rows.append({
            "date": str(ts.date()),
            "deliv_pct": None if share is None else round(share, 2),
            "traded_qty": None if traded is None else int(round(traded)),
            "delivered_qty": None if delivered is None else int(round(delivered)),
            "close": _col_at(close, sym, ts),
            "avg_price": avg_px,
            "turnover_cr": (None if (traded is None or avg_px is None)
                            else round(traded * avg_px / 1e7, 2)),
        })

    def mean_of(n):
        tail = series.tail(n)
        return None if not len(tail) else round(float(tail.mean()), 2)

    # The window the "vs its own year" comparison is made against. Named in
    # the payload so the page can print the sample size instead of implying a
    # full year it may not hold.
    year = series.tail(LOOKBACK)
    year_avg = None if not len(year) else round(float(year.mean()), 2)
    latest = round(float(series.iloc[-1]), 2)
    avg_20 = mean_of(20)

    window = series.tail(days)
    hi_ts = window.idxmax() if len(window) else None
    lo_ts = window.idxmin() if len(window) else None

    # The store kept only the liquid names until recently, so a smaller
    # company's older sessions are still being fetched back in. Its averages
    # are therefore over less history than the file holds, and saying so is
    # the difference between a short window and a wrong one.
    held = 0 if dp is None else int(len(dp))
    backfilling = bool(held and len(series) < held * 0.6)

    return {
        "available": True,
        "symbol": sym,
        "as_of": str(series.index[-1].date()),
        "sessions_returned": len(rows),
        "sessions_held": int(len(series)),
        "panel_sessions": held,
        "backfilling": backfilling,
        "delivered_qty_derived": True,
        "source": "NSE sec_bhavdata_full (EQ series)",
        "summary": {
            "latest": latest,
            "avg_5": mean_of(5),
            "avg_20": avg_20,
            "avg_63": mean_of(63),
            "avg_year": year_avg,
            "year_sessions": int(len(year)),
            # Positive means ownership has been tightening lately relative to
            # how this stock normally trades. It is a comparison, not a
            # forecast, and the units are percentage points.
            "trend_pp": (None if (avg_20 is None or year_avg is None)
                         else round(avg_20 - year_avg, 2)),
            "high": (None if hi_ts is None else
                     {"date": str(hi_ts.date()), "deliv_pct": round(float(window.max()), 2)}),
            "low": (None if lo_ts is None else
                    {"date": str(lo_ts.date()), "deliv_pct": round(float(window.min()), 2)}),
        },
        "rows": rows,
    }


# ---------------------------------------------------------------------------
# The signal
# ---------------------------------------------------------------------------

SIGNALS = [
    ("residual_momentum",  "Residual drift",
     "Return with the market's contribution regressed out, divided by its own "
     "noise. Ranks company-specific drift rather than beta."),
    ("delivery_weighted",  "Delivery-weighted return",
     "Each day's return multiplied by that day's delivered share of volume. "
     "Rewards advances that happened while ownership actually changed hands."),
    ("range_persistence",  "Close-range persistence",
     "Where inside its own daily high-low range the stock kept closing. A "
     "buyer working an order pushes the close toward the high, day after day."),
    ("low_volatility",     "Calmness",
     "Realised volatility, negated. Calm compounders have outperformed on a "
     "risk-adjusted basis for decades and nobody has explained it away."),
    ("delivery_trend",     "Delivery trend",
     "Recent delivered share against its own one-year average. Rising "
     "delivery is ownership tightening."),
]


@np.errstate(all="ignore")
def _components(P, look=LOOKBACK, skip=SKIP):
    """Every signal, computed from the one bhavcopy feed. Returns raw values.

    The market proxy for the residual regression is the cross-sectional MEDIAN
    return of the panel itself — self-contained, needs no index feed, and is
    arguably the better benchmark since it is the actual opportunity set.
    """
    close, high, low, dp = P["close"], P["high"], P["low"], P["deliv"]
    r = close.pct_change(fill_method=None)
    n = len(close)
    look = min(look, max(80, n - skip - 5))
    win = slice(-(look + skip), -skip if skip else None)

    out = {}
    # 1 · residual drift t-statistic
    mkt = r.median(axis=1)
    rw, mw = r.iloc[win], mkt.iloc[win]
    var_m = float(mw.var()) if len(mw) > 2 else 0.0
    if var_m > 0 and np.isfinite(var_m):
        # cov(x, m) = E[xm] - E[x]E[m], computed for every column at once.
        # The per-column .apply() this replaces walked ~3,000 symbols one by
        # one and was by far the slowest thing in the request.
        cov = rw.mul(mw, axis=0).mean() - rw.mean() * mw.mean()
        beta = cov / var_m
        resid = rw.sub(np.outer(mw.to_numpy(), beta.to_numpy()))
        sd = resid.std()
        out["residual_momentum"] = resid.mean() / sd.where(sd > 0)
    else:
        out["residual_momentum"] = pd.Series(np.nan, index=close.columns)

    # 2 · delivery-weighted return
    out["delivery_weighted"] = (r * (dp / 100.0)).iloc[win].sum()

    # 3 · close-range persistence
    rng = (high - low).replace(0, np.nan)
    out["range_persistence"] = ((close - low) / rng).clip(0, 1).iloc[win].mean()

    # 4 · calmness
    out["low_volatility"] = -r.iloc[win].std()

    # 5 · delivery trend
    recent = dp.iloc[-(63 + skip):-skip if skip else None].mean()
    out["delivery_trend"] = recent - dp.iloc[win].mean()

    return out, look


def rank_universe(limit=BOOK):
    """
    The published book.

    FIVE signals, EQUALLY weighted as cross-sectional percentile ranks.

    Equal weighting is deliberate and is the finding, not laziness. Weighting
    by each signal's measured information coefficient was tested and produced
    a WORSE book (CAGR 19.4% vs 20.7%, Sharpe 1.12 vs 1.21): the weights chase
    whichever signal last worked, which is the opposite of what you want from
    an ensemble. Every signal here also decayed over the test window, and the
    equal-weight blend decayed least. Diversification across signals is doing
    the work; cleverness about the weights was not.
    """
    # Unconditional. This used to sit inside the "too short to rank" branch
    # below, which meant that the moment the store passed MIN_SESSIONS nothing
    # asked it to fetch anything ever again — no cron calls /special/refresh
    # either, so the live store sat frozen eighteen days stale and nobody
    # could tell, because a stale book looks exactly like a current one.
    # ensure_building is already rate-limited and has its own memory ceiling,
    # so calling it on every request costs a comparison.
    ensure_building()
    P = _load_cache()
    if not P or P.get("close") is None or len(P["close"]) < MIN_SESSIONS:
        st = status()
        have = int(st.get("cached_sessions", 0))
        err = st.get("build", {}).get("error")
        return {"available": False, "building": True, "sessions": have,
                "needed": MIN_SESSIONS,
                "message": (err or (f"Reading the exchange delivery record — "
                                    f"{have} of {MIN_SESSIONS} sessions in.")),
                "status": st}

    # The book is drawn from the liquid, non-fund subset. The store itself is
    # the whole exchange now, so this narrowing has to happen before anything
    # cross-sectional is computed — see _for_ranking.
    P, rank_cols = _for_ranking(P)
    close, vwap, qty, dp = P["close"], P["vwap"], P["qty"], P["deliv"]
    comps, look = _components(P)

    turnover_cr = (qty * vwap).tail(60).median() / 1e7
    n = len(close)
    sma200 = close.rolling(min(200, max(20, n - 1))).mean().iloc[-1]
    last = close.iloc[-1]
    obs = close.tail(look).notna().sum()

    frame = pd.DataFrame(comps)
    frame["turnover_cr"] = turnover_cr
    frame["price"] = last
    frame["sma200"] = sma200
    frame["obs"] = obs
    frame = frame.dropna(subset=["price", "turnover_cr"])
    frame = frame[~pd.Series(frame.index, index=frame.index).map(_is_fund)]
    frame = frame[(frame["turnover_cr"] >= MIN_TURNOVER_CR)
                  & (frame["obs"] >= look * 0.6)
                  & (frame["price"] > frame["sma200"])]
    if len(frame) < 20:
        return {"available": False,
                "message": ("Too few names clear liquidity, history and trend "
                            "together to rank a cross-section today."),
                "status": status()}

    keys = [k for k, _l, _d in SIGNALS]
    pct = {k: frame[k].rank(pct=True) * 100 for k in keys}
    live = [k for k in keys if frame[k].notna().sum() >= len(frame) * 0.5]
    frame["composite"] = sum(pct[k].fillna(50.0) for k in live) / len(live)
    frame = frame.sort_values("composite", ascending=False)
    top = frame.head(limit)

    rows = []
    for sym, r in top.iterrows():
        parts = [{"key": k, "label": lab,
                  "percentile": (None if pd.isna(pct[k].get(sym))
                                 else round(float(pct[k][sym]), 0)),
                  "value": (None if pd.isna(r[k]) else round(float(r[k]), 4)),
                  "note": note}
                 for k, lab, note in SIGNALS]
        strong = [p["label"] for p in parts
                  if p["percentile"] is not None and p["percentile"] >= 70]
        weak = [p["label"] for p in parts
                if p["percentile"] is not None and p["percentile"] <= 30]
        rows.append({
            "symbol": sym,
            "composite": round(float(r["composite"]), 1),
            "components": parts,
            "turnover_cr": round(float(r["turnover_cr"]), 1),
            "price": round(float(r["price"]), 2),
            "above_200dma_pct": round(float(r["price"] / r["sma200"] - 1) * 100, 1),
            "why": (("Strong on " + ", ".join(strong).lower() + ". " if strong else "")
                    + ("Weak on " + ", ".join(weak).lower() + ". " if weak else "")
                    + f"It clears the {len(live)} signals on {r['composite']:.0f} "
                      "out of 100, averaged across them."),
        })

    return {
        "available": True,
        "as_of": str(close.index[-1].date()),
        "universe_ranked": int(len(frame)),
        "signals": [{"key": k, "label": lab, "note": note} for k, lab, note in SIGNALS],
        "signals_live": live,
        "book": rows,
        "method": (
            f"Five signals, each turned into a percentile against every other "
            f"name ranked today, then averaged with EQUAL weight over {look} "
            f"sessions skipping the most recent {SKIP}. Names must trade at "
            f"least Rs {MIN_TURNOVER_CR:.0f} crore a day and sit above their "
            "200-day average. Equal weighting beat IC-weighting in testing."),
        "measured": {
            "window": "2021-03 to 2026-08, 100 most-liquid NSE names, "
                      "net of a 0.49% round trip",
            "cagr_pct": 20.65, "sharpe": 1.21, "max_drawdown_pct": -22.4,
            "nifty_cagr_pct": 10.22, "nifty_sharpe": 0.77,
            "vs_single_best": (
                "Delivery-weighted return alone returned 23.05% at Sharpe 1.14 "
                "and a -26.3% drawdown. The five-signal blend gives up 2.4 "
                "points of return for a 3.9-point shallower drawdown and a "
                "higher Sharpe. Residual momentum alone: 21.52%, Sharpe 1.05, "
                "-30.7%."),
            "decay_warning": (
                "EVERY signal here weakened in the last two and a half years. "
                "Measured information coefficient of the delivery signal was "
                "+0.070 over 2021-2023 and -0.008 over 2024-2026; close-range "
                "persistence was +0.065 over 2015-2020 and -0.001 after. Only "
                "residual momentum held its sign across both halves, and even "
                "it is not individually significant. The blend decayed least, "
                "which is the case for holding five rather than one — it is "
                "not a claim that any of them still works."),
            "honest_note": (
                "This is measured over one regime on a universe of survivors. "
                "Treat the ranking between names as more reliable than any "
                "return figure, and check the live record before acting."),
        },
        "disclaimer": (
            "Educational. A ranking of published exchange data, with the "
            "arithmetic shown. Not a recommendation to buy or sell."),
        "status": status(),
    }
