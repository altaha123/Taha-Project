"""
Altaha Screener — API  (v2.1 — on-demand scanning)
Start command on Render:  uvicorn main:app --host 0.0.0.0 --port $PORT
"""

import datetime as _dt_mod
import json
import os
import threading
import time

from fastapi import FastAPI, HTTPException, Body, Response, Header
from typing import Optional
from fastapi.responses import (JSONResponse, StreamingResponse,
                               HTMLResponse, PlainTextResponse)
from fastapi.middleware.cors import CORSMiddleware
import numpy as np
import pandas as pd

# Before any module that pulls prices is imported. yf.download(threads=True)
# starts one OS thread per ticker rather than using a pool, and multitasking
# never releases them; that is what was killing the universe scan on a 512 MB
# box. ythreads.py has the full reading of yfinance/multi.py.
import ythreads
ythreads.serial_downloads()

from engine import technical_score, fundamental_score, composite
from data_source import resolve, fundamentals, shareholding, NotFound
try:
    import dhan_source as dhan
except Exception:
    dhan = None
import io
import csv
import scan as scanner
import announcements as ann
import ideas as ideas_engine
import og as og_cards
try:
    import pit_store
    pit_store.init_db()
except Exception:
    pit_store = None
# The measurement stack. Each is optional: the site works without any of them,
# it just stops being able to answer whether it works.
try:
    import forward_returns as fwd_labels
except Exception:
    fwd_labels = None
try:
    import factor_lab
except Exception:
    factor_lab = None
try:
    import factors as factor_lib
except Exception:
    factor_lib = None
try:
    import multifactor
except Exception:
    multifactor = None
try:
    import attention as attention_mod
except Exception:
    attention_mod = None
try:
    import deals as deals_source
except Exception:
    deals_source = None
try:
    import xbrl as xbrl_source
except Exception:
    xbrl_source = None
try:
    import special as special_engine
except Exception:
    special_engine = None
import patterns as pattern_engine
import forward as forward_engine
import tracker
from results import quarterly_results
from levels import compute_levels
from tradeplan import build_plan

# Live price relay. Optional: if livefeed.py is absent the chart falls back
# to its existing 3-second polling and nothing else changes.
try:
    import livefeed
except Exception:
    livefeed = None
from portfolio import (build_report, clean_policy, DEFAULT_POLICY,
                       MAX_HOLDINGS, WORKERS as PF_WORKERS)
import sectors
from concurrent.futures import ThreadPoolExecutor, as_completed
import uuid
import archetypes as A
import profiles as PR
import sector_story as SS
import news_feed as press
import intraday
import alerts as notify
from plain import highlights, plain_verdict

# MEMORY, PART ONE: THREADS.
#
# Every one of the 74 routes below is a plain `def`, which means Starlette runs
# each request in a worker thread. Its default pool is FORTY threads, and this
# process was sitting at nineteen with 285 MB resident on a 512 MB box.
#
# Each thread costs more than its stack. pit_store.py keeps ONE SQLITE
# CONNECTION PER THREAD in a threading.local(), and every SQLite connection
# carries its own page cache — so the thread count silently multiplies the
# database memory too.
#
# stack_size() has to be set BEFORE any thread is created, which is why it sits
# here at import rather than in a startup hook. 512 KB is ample: nothing in
# this app recurses deeply.
_THREADS = int(os.environ.get("ALTAHA_MAX_THREADS", "8") or 8)
try:
    threading.stack_size(512 * 1024)
except (ValueError, RuntimeError):
    pass

# ---------------------------------------------------------------------------
# Crash reporting
#
# Until now a 500 in here left a traceback in Render's log stream and nothing
# else. Nobody reads a log stream on a Tuesday; the way bugs in this project
# have actually been found is by somebody noticing a wrong number on a screen.
#
# Everything about this is optional and silent. With SENTRY_DSN unset — which
# is how it ships — nothing is imported, nothing is sent, and startup is
# byte-for-byte what it was. If the package is missing on the deployed image
# the failure is printed once and the app carries on, because a monitoring
# tool that can take the API down is worse than no monitoring tool.
#
# Tracing and profiling are explicitly off. They are sampled per request and
# this runs on a 512 MB box with one worker; error reporting is what was
# asked for and error reporting is all that is paid for.
# ---------------------------------------------------------------------------
SENTRY_DSN = os.environ.get("SENTRY_DSN", "").strip()


def _start_sentry() -> bool:
    if not SENTRY_DSN:
        return False
    try:
        import sentry_sdk
        sentry_sdk.init(
            dsn=SENTRY_DSN,
            traces_sample_rate=0.0,
            profiles_sample_rate=0.0,
            # No cookies, no headers, no request bodies. A ticker in a query
            # string is the most personal thing this API ever receives.
            send_default_pii=False,
            environment=os.environ.get("SENTRY_ENV", "production"),
            max_breadcrumbs=20,
        )
        return True
    except Exception as e:                                    # pragma: no cover
        print(f"[sentry] not started: {type(e).__name__}: {e}", flush=True)
        return False


SENTRY_ON = _start_sentry()

app = FastAPI(title="Altaha Screener API", version="2.1")


_threadcap = {"applied": None, "error": None}


def _apply_thread_cap():
    """Hold the request pool to `_THREADS` instead of Starlette's default 40.

    Every route here is a plain `def`, so Starlette hands each request to a
    worker thread and keeps those threads alive for reuse. The pool therefore
    RATCHETS UP and never comes back down: measured on the live instance,
    19 threads / 285 MB at 13:47 and 30 threads / 365 MB five minutes later.
    Each thread also brings its own pit_store SQLite connection with it. Left
    alone it reaches 40, crosses 512 MB and the instance is killed — which is
    exactly the shape of the memory emails.

    With WEB_CONCURRENCY=1 and this traffic eight concurrent slow requests is
    generous; past that they queue. Queuing is slower. Being killed is slower.
    """
    try:
        import anyio.to_thread
        lim = anyio.to_thread.current_default_thread_limiter()
        lim.total_tokens = _THREADS
        _threadcap["applied"] = lim.total_tokens
        _threadcap["error"] = None
    except Exception as e:
        _threadcap["error"] = f"{type(e).__name__}: {e}"
    return _threadcap


@app.on_event("startup")
async def _cap_request_threadpool():
    _apply_thread_cap()


@app.middleware("http")
async def _ensure_thread_cap(request, call_next):
    """Belt and braces.

    on_event("startup") is deprecated and can be skipped when a lifespan is
    installed by something else, and a cap that silently fails to apply is the
    same as no cap. This re-applies it on the first request and then costs one
    comparison per request afterwards. The person running this cannot debug a
    silent failure, so it must not be possible to have one."""
    if _threadcap["applied"] != _THREADS:
        _apply_thread_cap()
    return await call_next(request)

# Everything imported above is permanent. Moving it out of the generational
# collector's reach means every later gc pass walks only real working data,
# which on a 512 MB box is both faster and less fragmenting.
try:
    import gc as _gc
    _gc.collect()
    _gc.freeze()
except Exception:
    pass

# ---------------------------------------------------------------------------
# Social surface — Updates 5 and 6
#
# social_routes  -> /social/*        filing drafts + review queue + X posting
# news_routes    -> /social/news/*   market news, clustered across outlets
#
# social_posts.py reads from announcements.py rather than fetching anything
# itself, so there is still exactly one BSE session in this process.
# news_feed.py is untouched and still owns /news/press.
#
# The news poller is NOT started here. Starting a thread at import time means
# one poller per uvicorn worker, and on a 512 MB instance already running the
# intraday scanner, the alerts loop and the announcements poller, that extra
# memory is what pushes it over and gets the process restarted — which takes
# /announcements down with it. It now starts on the first request to the news
# feed instead, so a user who never opens the Social tab never pays for it.
# ---------------------------------------------------------------------------
import social_routes
import news_routes

app.include_router(social_routes.router)
app.include_router(news_routes.router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Unhandled errors, and why the browser could not see them
#
# An exception inside a route returns 500 from Starlette's ServerErrorMiddleware,
# which sits OUTSIDE the CORS middleware. That response therefore carries no
# Access-Control-Allow-Origin header, so a browser on altahascreener.in refuses
# to hand it to the page's JavaScript and fetch() rejects instead. From inside
# the app the failure is a 500 with a traceback in the logs; from inside the
# page it is indistinguishable from an engine that is down.
#
# That is the whole reason a crash in /ideas read as "Engine unreachable — it
# may be waking from sleep" for nine days while the ticker strip on the same
# page kept updating. The message was not wrong about what the browser saw. It
# was wrong about why, and it sent everyone hunting for a sleeping server.
#
# Registering a handler for Exception moves nothing on its own — Starlette puts
# 500/Exception handlers on the outermost middleware, still outside CORS — so
# the header is set explicitly here. allow_origins is "*" above; this matches it.
@app.exception_handler(Exception)
async def _unhandled_error(request, exc):
    import traceback
    tb = traceback.format_exc()
    # Render captures stdout. This is the only copy of the traceback, so it is
    # printed whole rather than summarised.
    print(f"[unhandled] {request.method} {request.url.path}\n{tb}", flush=True)

    # This handler swallows the exception — Starlette calls it INSTEAD of
    # re-raising — so nothing downstream, Sentry's middleware included, ever
    # sees it. Reporting it here is what makes the difference between a
    # traceback nobody reads and an alert that names the endpoint.
    if SENTRY_ON:
        try:
            import sentry_sdk
            sentry_sdk.capture_exception(exc)
        except Exception:
            pass
    return JSONResponse(
        status_code=500,
        content={"error": type(exc).__name__,
                 "detail": str(exc)[:400],
                 "path": request.url.path,
                 "note": "The engine reached this endpoint and failed inside it. "
                         "This is a bug in the app, not a connectivity problem."},
        headers={"Access-Control-Allow-Origin": "*"},
    )


DISCLAIMER = (
    "Altaha Screener is an educational analysis tool. Scores are objective "
    "computations from public data using disclosed formulas. Nothing here is "
    "investment advice or a recommendation to buy or sell any security. "
    "Rankings reflect scores on the stated date and change as prices and "
    "filings change. Markets carry risk of loss. Do your own research or "
    "consult a SEBI-registered adviser."
)

# Indian Standard Time. Fixed at UTC+5:30 — India observes no daylight saving,
# so an offset is the whole story and no tz database is needed for it.
IST = _dt_mod.timezone(_dt_mod.timedelta(hours=5, minutes=30))

LEADERBOARD_FILE = scanner.OUT_FILE
RESULT_TTL = 12 * 3600          # a ranking older than this is stale

# ---------------------------------------------------------------------------
# Scan job state — one scan at a time, shared by everyone
# ---------------------------------------------------------------------------

_lock = threading.Lock()
_state = {
    "status": "idle",           # idle | running | done | error
    "done": 0, "total": 0, "scored": 0,
    "started_at": None, "finished_at": None,
    "error": None,
    "payload": None,
}



# ---------------------------------------------------------------------------
# Admin guard
#
# Every control endpoint below was previously open to anyone who found the
# Render URL: they could stop the scanner, spam the Telegram alerts, or kick
# off a universe scan that burns the Dhan rate limit. Set ADMIN_KEY in the
# environment and pass ?key=... to use them. If ADMIN_KEY is unset the guard
# stays open, so nothing breaks for a local run — but it should be set in
# production.
# ---------------------------------------------------------------------------

ADMIN_KEY = os.environ.get("ADMIN_KEY", "").strip()


def _require_admin(key: str = ""):
    if ADMIN_KEY and key != ADMIN_KEY:
        raise HTTPException(401, "This control endpoint needs the admin key (?key=...).")


def _autotrack(payload, source: str = "auto", force: bool = False):
    """
    Record every idea a scan produces, for hit-rate statistics only.

    Gated on AUTOTRACK, which is OFF by default. Rows land under
    source="auto" and do not appear in the Tracker tab, which lists your
    manual picks. The statistical argument for recording everything still
    holds — a tracker of only the ideas you liked flatters itself — but that
    record belongs in its own list, not in yours.

    Called from three places, because a scan payload can arrive three ways:
    a fresh scan finishing, a cached payload being read off disk at boot, or
    the user pressing Record on the Tracker tab. Only the first was wired
    originally, which meant anyone whose results came from cache saw an
    empty tracker forever and had no way to tell why. add() de-duplicates,
    so calling this repeatedly is safe.

    force=True bypasses the AUTOTRACK gate. That is what the Record current
    ideas button needs: pressing a button IS the explicit instruction the gate
    exists to require, and without the bypass the button reported "Recorded 0"
    on every press for anyone running the default configuration.
    """
    try:
        rows = []
        for horizon in ("short", "medium"):
            sel = ideas_engine.select(payload, horizon=horizon, limit=25,
                                      include_thin=True,
                                      # The statistical record wants everything the
                                      # setup matched, not only what cleared the
                                      # display floor — filtering it here would make
                                      # the measured hit rate a highlight reel again.
                                      min_conviction=0)
            rows.extend(sel.get("rows") or [])
        if rows:
            return tracker.add_many(rows, source=source, force=force)
    except Exception as e:
        return {"added": 0, "skipped": 0, "error": str(e)[:160]}
    return {"added": 0, "skipped": 0, "reason": "no qualifying ideas in this payload"}


def _load_from_disk():
    if os.path.exists(LEADERBOARD_FILE):
        try:
            with open(LEADERBOARD_FILE) as f:
                _state["payload"] = json.load(f)
                _state["status"] = "done"
                _state["finished_at"] = os.path.getmtime(LEADERBOARD_FILE)
            # A cached payload is still a set of live ideas. Record it — but on
            # a background thread. This runs at import time, and _autotrack
            # reaches for the index quote and the filings feed, so doing it
            # inline delays the port binding and can make Render mark the
            # deploy as failed. A 502 on a fresh deploy usually traces back to
            # something slow happening before the server starts listening.
            threading.Thread(target=_autotrack, args=(_state["payload"],),
                             daemon=True, name="altaha-autotrack").start()
        except Exception:
            pass


_load_from_disk()


def _autostart_intraday():
    """
    Render restarts the process on deploy, on idle wake-up, and sometimes for
    no visible reason. A scanner that only starts when a human presses a button
    silently stops alerting after the first restart, which is the worst kind of
    failure: quiet. So it re-arms itself on boot.
    """
    # Defaults to ON. Previously this defaulted to OFF, so a deploy that never
    # set INTRADAY_AUTOSTART left the scanner permanently unarmed while every
    # status endpoint still returned HTTP 200. Set INTRADAY_AUTOSTART=0 to
    # disable deliberately.
    if os.environ.get("INTRADAY_AUTOSTART", "1").strip().lower() in ("0", "false", "no", "off"):
        return
    try:
        limit = int(os.environ.get("INTRADAY_WATCHLIST", "200"))
    except ValueError:
        limit = 200
    try:
        if dhan is not None and dhan.configured():
            intraday.start(_default_watchlist(limit))
    except Exception:
        pass


def _worker():
    def progress(done, total, scored):
        _state["done"], _state["total"], _state["scored"] = done, total, scored

    def checkpoint(partial_payload):
        # Partial rankings become visible immediately and survive a process
        # restart (they're also written to disk by the scanner), so the Ideas
        # tab is never left empty after minutes of scanning.
        _state["payload"] = partial_payload

    try:
        payload = scanner.run_scan(progress=progress, checkpoint=checkpoint)
        _state["payload"] = payload
        _state["status"] = "done"
        _state["finished_at"] = time.time()
        _state["error"] = None
        # Only records if AUTOTRACK is explicitly switched on. Off by
        # default since 28 Aug 2026 — see the note in tracker.py.
        if tracker.AUTOTRACK:
            _autotrack(payload)
    except MemoryError:
        _state["status"] = "done" if _state["payload"] else "error"
        _state["finished_at"] = time.time()
        _state["error"] = "ran out of memory — partial results kept" \
            if _state["payload"] else "out of memory before any results"
    except Exception as e:
        if _state["payload"]:
            _state["status"] = "done"
            _state["finished_at"] = time.time()
            _state["error"] = "scan interrupted — partial results kept: " + str(e)[:120]
        else:
            _state["status"] = "error"
            _state["error"] = str(e)[:200]


def to_native(obj):
    """
    Plain Python, all the way down.

    FastAPI serialises a response with jsonable_encoder, which does not know
    what a numpy scalar is: it tries dict(obj), then vars(obj), and raises
    ValueError when both fail. That happens AFTER the route function has
    returned, so no try/except inside a route can catch it — the endpoint
    succeeds and the response still 500s. Anything that touches pandas or
    numpy must therefore be converted here, at the boundary, and every
    endpoint that does so passes through this function.

    Sets and numpy's own scalar types are handled explicitly. A set is not
    JSON at all, and np.str_ / np.datetime64 satisfy none of the branches
    below while still failing to encode — .item() is numpy's own answer for
    "give me the Python equivalent", so it is asked rather than guessed at.
    """
    if isinstance(obj, dict):
        return {k: to_native(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_native(v) for v in obj]
    if isinstance(obj, (set, frozenset)):
        return [to_native(v) for v in obj]
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        v = float(obj)
        return None if (v != v or v in (float("inf"), float("-inf"))) else v
    if isinstance(obj, np.generic):
        try:
            return to_native(obj.item())
        except Exception:
            return str(obj)
    if isinstance(obj, np.ndarray):
        return [to_native(v) for v in obj.tolist()]
    return obj


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/")
def root():
    return {"app": "Altaha Screener", "tagline": "Where Logic Meets Validations",
            "endpoints": ["/analyze?ticker=RELIANCE", "/universe", "/leaderboard",
                          "/scan/start", "/scan/status", "/health"]}


INDICES = [("^NSEI", "NIFTY 50"), ("^BSESN", "SENSEX"),
            ("^NSEBANK", "BANK NIFTY"), ("^INDIAVIX", "INDIA VIX")]


@app.get("/market")
def market():
    """Index levels for the ticker strip. Cached by the data layer."""
    import datetime as _dt
    out = []
    for sym, label in INDICES:
        try:
            _, t, hist = resolve(sym)
            c = hist["Close"].dropna()
            if len(c) < 2:
                continue
            last, prev = float(c.iloc[-1]), float(c.iloc[-2])
            out.append({"label": label, "level": round(last, 2),
                        "change": round(last - prev, 2),
                        "change_pct": round(100 * (last - prev) / prev, 2)})
        except Exception:
            continue

    # Market session status, IST
    dhan_status = None
    if dhan is not None and dhan.configured():
        try:
            dhan_status = dhan.market_status()
        except Exception:
            dhan_status = None

    # An IST-aware clock, not naive UTC plus five and a half hours.
    #
    # datetime.utcnow() is deprecated and scheduled for removal — it is already
    # printing a DeprecationWarning on every /market request under the Python
    # 3.14 this runs on, and when it goes this endpoint goes with it, taking
    # the ticker strip and the open/closed badge down.
    #
    # The old line was also lying about what it held: a NAIVE datetime carrying
    # IST wall-clock numbers, which reads as UTC to anything that inspects it.
    # A real timezone makes .hour, .minute and .weekday() mean what the market
    # session checks below already assume they mean.
    now = _dt.datetime.now(IST)
    mins = now.hour * 60 + now.minute
    weekday = now.weekday() < 5
    if not weekday:
        status = "closed"
    elif 555 <= mins < 930:          # 09:15 - 15:30 IST, the NSE equity session
        status = "open"
    elif mins < 555:
        status = "pre"
    else:
        status = "closed"
    if dhan_status:
        if "open" in dhan_status:
            status = "open"
        elif "pre" in dhan_status:
            status = "pre"
        elif "close" in dhan_status:
            status = "closed"

    return to_native({"indices": out, "status": status,
                      "ist": now.strftime("%d %b %Y, %H:%M IST")})


@app.get("/datasource")
def datasource():
    """Which price feed is live right now, and why."""
    if dhan is None or not dhan.configured():
        return {"price_source": "yahoo", "dhan_configured": False,
                "detail": "Set DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN in Render to enable Dhan."}
    st = dhan.is_live()
    scrip = dhan.load_scrip()
    return {"price_source": "dhan" if st["ok"] else "yahoo (dhan unavailable)",
            "dhan_configured": True, "dhan_ok": st["ok"], "detail": st["detail"],
            "instruments_mapped": len(scrip or {}),
            "scrip_error": getattr(dhan, "_scrip", {}).get("error"),
            "token": dhan.token_info()}


@app.get("/universe")
def universe_list():
    """
    Symbol and company name for every NSE equity, for the search typeahead.

    Roughly 2,000 rows / ~90 KB. The client caches it in localStorage for a
    day, so this is fetched once per user per day rather than once per
    keystroke. Cache-Control lets any CDN in front of this do the same.

    Returns an empty list rather than an error when the NSE list is
    unreachable: the frontend has its own fallback, and a 500 here would make
    the whole search box look broken over what is only a degraded feature.
    """
    try:
        rows = scanner.universe_with_names()
    except Exception:
        rows = []
    return JSONResponse(
        {"rows": rows, "count": len(rows)},
        headers={"Cache-Control": "public, max-age=86400"},
    )


def _rss_mb():
    """Resident memory in MB, or None off Linux. No dependency: psutil is 8 MB
    and this is four lines."""
    try:
        with open("/proc/self/status") as fh:
            for line in fh:
                if line.startswith("VmRSS:"):
                    return round(int(line.split()[1]) / 1024, 1)
    except Exception:
        pass
    return None


# Refuse to start a universe scan without this much room left. The scan is the
# only thing here that needs hundreds of MB — it walks ~2,000 symbols pulling a
# year of history each — and on a 512 MB box it is what turns a healthy process
# into a killed one. Better a clear refusal than an OOM restart that takes the
# whole site down with it.
#
# This used to be an ABSOLUTE ceiling of 330 MB, which was the bug: the process
# boots at ~367 MB and idles around 467 MB, so the ceiling sat below the floor
# and every single press of "Generate from universe" was refused, for eight
# days, with the button silently resetting itself. A ceiling you can never be
# under is not a safety valve, it is an outage.
#
# Headroom is the honest question — "is there room for a scan", not "is the
# process small". SCAN_RSS_CEILING_MB is still read so an existing Render
# setting keeps working; it is converted to the equivalent headroom.
MEM_LIMIT_MB = int(os.environ.get("MEM_LIMIT_MB", "512") or 512)
_legacy_ceiling = os.environ.get("SCAN_RSS_CEILING_MB", "").strip()
SCAN_HEADROOM_MB = int(os.environ.get("SCAN_HEADROOM_MB", "0") or 0) or (
    max(MEM_LIMIT_MB - int(_legacy_ceiling), 60) if _legacy_ceiling.isdigit() else 90)


def _reclaim():
    """
    Give back what is droppable, then measure again.

    Called before every scan, because a refusal is only honest if the process
    has first let go of what it does not need, and because the scan is the one
    job here that needs the room. Everything dropped is either a cache with a
    file behind it or a cache that refills on demand — nothing is lost, the
    next request that wants it pays to rebuild it. Returns (before, after).
    """
    before = _rss_mb()
    try:
        import data_source as _ds
        _ds._CACHE.clear()
    except Exception:
        pass
    # The Special panel is tens of MB of float32 price history held resident,
    # with a pickle of exactly the same thing sitting on disk beside it. Of
    # everything this process holds at idle it is the largest single item that
    # costs nothing to drop — _load_cache() reads it straight back.
    try:
        if special_engine is not None:
            special_engine._state["panel"] = None
    except Exception:
        pass
    ythreads.reap()
    try:
        import gc
        gc.collect()
    except Exception:
        pass
    try:                      # hand freed arenas back to the OS
        import ctypes
        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except Exception:
        pass
    return before, _rss_mb()


@app.get("/health/memory")
def health_memory(detail: int = 0):
    """
    What this process is actually holding, and where.

    Exists because "exceeded memory limit" arrives as an email with no detail,
    and this instance has 512 MB against a library floor of roughly 99 MB
    (numpy, pandas, yfinance) before a line of app code runs. Reading it from
    /proc keeps this dependency-free — psutil is not worth 8 MB here.
    """
    out = {"limit_mb": 512, "note": "Render Starter is 512 MB."}
    try:
        with open("/proc/self/status") as fh:
            for line in fh:
                if line.startswith("VmRSS:"):
                    out["rss_mb"] = round(int(line.split()[1]) / 1024, 1)
                elif line.startswith("VmHWM:"):        # high-water mark
                    out["peak_mb"] = round(int(line.split()[1]) / 1024, 1)
                elif line.startswith("Threads:"):
                    out["threads"] = int(line.split()[1])
    except Exception:
        pass
    out["malloc_arena_max"] = os.environ.get("MALLOC_ARENA_MAX") or \
        "UNSET — glibc may open up to 8 arenas per CPU for a threaded process"
    out["web_concurrency"] = os.environ.get("WEB_CONCURRENCY") or "unset (1)"
    out["data_dir_persistent"] = bool(os.environ.get("DATA_DIR", "").strip())
    # DATA_DIR being SET is not the same as the scan cache being written; the
    # env var was true throughout the incident where nine days of scans never
    # reached the disk. Report the write itself.
    try:
        out["scan_persistence"] = scanner.persistence_health()
    except Exception:
        pass

    # The big resident consumers, so a spike can be attributed.
    holders = {}
    try:
        p = _state.get("payload") or {}
        holders["scan_payload_rows"] = len(p.get("rankings") or [])
    except Exception:
        pass
    try:
        if special_engine is not None:
            st = special_engine.status()
            holders["special_panels_mb"] = st.get("resident_mb")
            holders["special_sessions"] = st.get("cached_sessions")
            holders["special_symbols"] = st.get("symbols")
    except Exception:
        pass
    # Name the threads. "19 threads" is not actionable; "12 of them are
    # request workers" is.
    try:
        names = {}
        for t in threading.enumerate():
            key = "request-worker" if t.name.startswith(("ThreadPoolExecutor",
                  "AnyIO", "asyncio_")) else t.name
            names[key] = names.get(key, 0) + 1
        out["thread_names"] = names
        out["yfinance_threads"] = ythreads.status()
        out["thread_cap_requested"] = _THREADS
        out["thread_cap_applied"] = _threadcap["applied"]
        if _threadcap["error"]:
            out["thread_cap_error"] = _threadcap["error"]
        if _threadcap["applied"] != _THREADS:
            out["warning"] = ("The request-thread cap did NOT apply. The pool "
                              "will grow to 40 and the instance will be killed.")
    except Exception:
        pass
    # A real breakdown, on request. /health/memory stays cheap; ?detail=1 walks
    # the module-level stores and reports what each is actually holding, so the
    # next spike is attributed instead of guessed at. I guessed twice and was
    # wrong both times — thread stacks cost almost nothing, and malloc_trim
    # returned 0.2 MB. Measure, do not theorise.
    if detail:
        import sys as _sys

        def deep(obj, cap=400000):
            """Rough recursive size. Capped so this cannot itself be the spike."""
            seen, stack, total, n = set(), [obj], 0, 0
            while stack and n < cap:
                o = stack.pop()
                i = id(o)
                if i in seen:
                    continue
                seen.add(i); n += 1
                try:
                    total += _sys.getsizeof(o)
                except Exception:
                    continue
                if isinstance(o, dict):
                    stack.extend(o.keys()); stack.extend(o.values())
                elif isinstance(o, (list, tuple, set, frozenset)):
                    stack.extend(o)
            return round(total / 1e6, 2)

        det = {}
        for label, getter in (
            ("scan_payload", lambda: _state.get("payload")),
            ("announcements", lambda: getattr(ann, "_state", None)),
            ("market_news", lambda: getattr(__import__("market_news"), "_state", None)),
            ("intraday", lambda: getattr(intraday, "_state", None)),
            ("tracker_cache", lambda: getattr(tracker, "_cache", None)),
            ("scan_names_cache", lambda: getattr(scanner, "_names_cache", None)),
        ):
            try:
                obj = getter()
                if obj is not None:
                    det[label + "_mb"] = deep(obj)
            except Exception:
                pass
        try:
            det["pit_db_mb"] = round(os.path.getsize(
                pit_store.DB_PATH) / 1e6, 2) if pit_store else None
        except Exception:
            pass
        out["detail"] = det
        out["detail_note"] = ("Deep sizes of the module-level stores. These are "
                              "Python object graphs; numpy/pandas buffers and "
                              "allocator overhead sit outside them, so the parts "
                              "will not add up to rss_mb. The gap IS the answer "
                              "when it is large.")
    out["holders"] = holders
    if out.get("rss_mb") and out["rss_mb"] > 420:
        out["warning"] = ("Within 90 MB of the limit. The usual causes are a "
                          "universe scan in flight, MALLOC_ARENA_MAX unset, or "
                          "more than one uvicorn worker.")
    return out


@app.get("/health")
def health():
    # Whether the pieces that are invisible from outside are actually on: is
    # crash reporting live, can email be delivered, is the accounts database
    # writable. Each has failed silently on this project before.
    extras = {"sentry": SENTRY_ON}
    try:
        import mailer
        extras["email"] = mailer.status()
    except Exception as e:
        extras["email"] = {"error": type(e).__name__}
    try:
        import accounts
        extras["accounts"] = accounts.stats()
    except Exception as e:
        extras["accounts"] = {"ok": False, "error": type(e).__name__}

    try:
        sym, t, h = resolve("AAPL")
        return {"data_layer": "ok", "rows": len(h),
                "last_close": round(float(h["Close"].iloc[-1]), 2), **extras}
    except Exception as e:
        return {"data_layer": "unreachable", "detail": str(e)[:200], **extras}


@app.post("/scan/start")
@app.get("/scan/start")
def scan_start(force: bool = False, key: str = "",
               ignore_memory: bool = False, force_memory: bool = False):
    """
    Kick off a background scan. Returns immediately.

    Two separate overrides, which used to be one and should never have been:

      force          ignore the cached result and scan again. This is what the
                     Refresh button sends on every press.
      ignore_memory  ignore the memory guard as well. Nothing sends this by
                     default; it has to be asked for.

    Conflating them is what made "Refresh universe scan" fail identically every
    time. Refresh needs force to get past the 12-hour cache, and force also
    switched off the headroom check — so the one button a user actually presses
    was the one press the safety valve could never see. On an instance idling
    near its limit the scan then started, the instance was killed part-way
    through, and every request after that failed until Render brought it back.
    The browser has no way to tell that apart from a sleeping server, so it
    said "Engine unreachable — it may be waking from sleep", and the obvious
    response to that message is to press the button again.

    force now means only "ignore the cache". A refresh with no room left is
    refused, in words, with the numbers behind the refusal.
    """
    _require_admin(key)
    ignore_memory = bool(ignore_memory or force_memory)
    # Reclaim first, always. This runs before the heaviest job in the process,
    # and the caches it drops are rebuilt on demand — measuring headroom
    # without doing it first refuses scans over memory nobody still needs.
    _, rss = _reclaim()
    headroom = None if rss is None else round(MEM_LIMIT_MB - rss, 1)
    if headroom is not None and headroom < SCAN_HEADROOM_MB and not ignore_memory:
        return {**scan_status(),
                "started": False, "reason": "low_memory",
                "rss_mb": rss, "headroom_mb": headroom,
                "needs_headroom_mb": SCAN_HEADROOM_MB, "limit_mb": MEM_LIMIT_MB,
                "message": (f"Holding {rss:.0f} MB of {MEM_LIMIT_MB} MB, so only "
                            f"{headroom:.0f} MB is free and a scan needs about "
                            f"{SCAN_HEADROOM_MB} MB. Starting one now would get the "
                            "instance killed part-way through, taking the whole "
                            "site down with it for a minute or two — which is what "
                            "an unreachable engine right after pressing Generate "
                            "actually was. Restart the service to clear it, or pass "
                            "ignore_memory=true if you accept the risk.")}
    with _lock:
        if _state["status"] == "running":
            return {"started": False, "reason": "already_running", **scan_status()}

        fresh = (_state["payload"] is not None
                 and _state["finished_at"]
                 and (time.time() - _state["finished_at"]) < RESULT_TTL)
        if fresh and not force:
            return {"started": False, "reason": "cached", **scan_status()}

        _state.update({"status": "running", "done": 0, "scored": 0,
                       "total": len(scanner.universe()),
                       "started_at": time.time(), "error": None})
        threading.Thread(target=_worker, daemon=True).start()
        return {"started": True, **scan_status()}


@app.get("/scan/status")
def scan_status():
    elapsed = int(time.time() - _state["started_at"]) if _state["started_at"] else 0
    out = {
        "status": _state["status"],
        "done": _state["done"], "total": _state["total"], "scored": _state["scored"],
        "elapsed_seconds": elapsed if _state["status"] == "running" else None,
        "error": _state["error"],
    }
    if _state["payload"]:
        p = _state["payload"]
        out["scanned_at"] = p.get("scanned_at")
        # A scan that stopped itself to stay alive is not the same event as one
        # that finished, and the difference is the whole explanation for a
        # short list. Carried through so the browser can say which happened.
        if p.get("stopped_early"):
            out["stopped_early"] = True
            out["stopped_reason"] = p.get("stopped_reason")
    out["rss_mb"] = _rss_mb()
    out["limit_mb"] = MEM_LIMIT_MB
    # A scan that cannot reach disk is a scan that will be lost on the next
    # restart, and the browser is the only place anyone is looking while it
    # runs. Reported only when it is actually broken, so the normal response
    # is unchanged.
    try:
        ph = scanner.persistence_health()
        # Two different faults, both of which end with a stale scan on screen:
        # the write failed, or the process died before a write was reached.
        # The second is what a deploy during a scan causes, and without this
        # the restarted process reports a clean "done" with a date days old.
        if not ph.get("healthy"):
            out["persistence"] = ph
        if ph.get("interrupted_scan") and _state["status"] != "running":
            out["interrupted_scan"] = ph["interrupted_scan"]
            out["last_attempt"] = ph.get("last_attempt")
    except Exception:
        pass
    return out


HORIZONS = ideas_engine.HORIZONS


@app.get("/ideas")
def ideas(horizon: str = "short", limit: int = 15,
          min_tier: str = "moderate", include_thin: bool = False,
          min_conviction: Optional[float] = None):
    """
    Ideas, rebuilt. Differences from the old endpoint, all deliberate:
      · returns FEWER than `limit` when fewer names genuinely qualify, instead
        of padding the list with unrelated high-composite names
      · scores every row out of 100 across seven factors weighted for the
        horizon — setup fit, engine composite, sector outlook, market regime,
        catalyst (filings and press), liquidity and the archetype's measured
        record — and ships the points each factor contributed
      · drops anything under the conviction floor rather than reordering it
      · caps how many ideas can come from one sector
      · marks adverse filings as adverse instead of counting them as news
      · warns per-row when the index is below its 50-day average
    """
    p = _state["payload"]
    if not p:
        return to_native({"available": False, "status": _state["status"],
                           "message": "No scan yet — generate the ranking first.",
                           "market_context": _safe_context(horizon)})
    try:
        # to_native, like every other endpoint that touches pandas. Without it
        # a single numpy scalar anywhere in the response — one sector figure,
        # one corroboration count — fails serialisation and returns 500, and
        # the failure happens after this function returns, so the except below
        # never sees it. This missing call is what broke the Ideas tab.
        return to_native({**ideas_engine.select(p, horizon=horizon,
                                                limit=max(1, min(limit, 25)),
                                                min_tier=min_tier,
                                                include_thin=bool(include_thin),
                                                min_conviction=min_conviction),
                          "disclaimer": DISCLAIMER})
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        # A bug in scoring must not present as a dead engine. The 500 this used
        # to raise reached the browser without CORS headers, so the tab could
        # only report that it could not reach anything — which is how a crash
        # in here went nine days looking like a sleeping server.
        import traceback
        print(f"[ideas] select() failed for horizon={horizon}\n{traceback.format_exc()}",
              flush=True)
        return to_native({
                "available": False,
                "status": _state["status"],
                "error": f"{type(e).__name__}: {str(e)[:300]}",
                "message": ("The scan is on the server but the ideas engine failed while "
                            "scoring it. The ranking is intact — this is a bug in the "
                            "scoring layer, not a lost scan."),
                "scanned_at": p.get("scanned_at"),
                "market_context": _safe_context(horizon)})


def _safe_context(horizon: str):
    """The market context never blocks the tab: a feed that is down returns
    nothing here rather than failing the whole request."""
    try:
        return ideas_engine.market_context(horizon)
    except Exception:
        return None


@app.get("/ideas/context")
def ideas_context(horizon: str = "short"):
    """
    Index regime, sector leaders and laggards, and the market-wide headlines —
    the backdrop the ideas are being picked against. Served separately so the
    Ideas tab can show the state of the market even before a scan exists, and
    so a slow news feed never delays the list itself.
    """
    ctx = _safe_context(horizon)
    if ctx is None:
        return {"available": False,
                "message": "Market context feeds are unavailable right now."}
    return to_native({"available": True, **ctx})


# ---------------------------------------------------------------------------
# Idea tracker
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Corporate announcements
# ---------------------------------------------------------------------------

@app.get("/announcements")
def announcements_feed(limit: int = 60, min_importance: str = "low",
                       symbol: str = "", category: str = ""):
    """
    Live BSE filing feed. Polls at most once every ANN_POLL_SECONDS, so this is
    safe to hit on every page load.
    """
    # Non-blocking: returns whatever is in memory now and refreshes behind it.
    try:
        ann.poll_if_stale()
    except Exception:
        pass
    return ann.feed(limit=limit, min_importance=min_importance,
                    symbol=symbol, category=category)


@app.get("/announcements/refresh")
def announcements_refresh(days: int = 3, wait: bool = True):
    """Force a poll. wait=true blocks until it finishes (useful for checking by
    hand); wait=false returns immediately and refreshes in the background."""
    if wait:
        return ann.poll(days=days)
    return ann.poll_if_stale(seconds=0, background=True)


@app.get("/announcements/probe")
def announcements_probe(days: int = 2):
    """Raw evidence for why the feed is empty: status, bytes, content type and
    the first slice of each response body. Read raw_head."""
    return ann.probe(days=days)


@app.get("/announcements/diag")
def announcements_diag():
    return ann.diagnose()


@app.get("/tracker/list")
def tracker_list(status: str = "", limit: int = 400, source: str = "manual"):
    """source="manual" (default) is your tracker — only what you pressed Add on.
    source="auto" is the scanner's statistical record. source="" is both."""
    return tracker.listing(status=status, limit=max(1, min(limit, 1000)), source=source)


@app.post("/tracker/backfill")
def tracker_backfill(source: str = "auto"):
    """
    Record the ideas from the CURRENT scan, right now.

    Without this, a user whose scan results came from cache had to wait for a
    fresh multi-minute scan before a single idea was ever recorded, and the
    Tracker tab gave no clue that was the reason it looked empty.

    BUGFIX: this went through the AUTOTRACK gate, which has been off by default
    since 28 Aug 2026, so it recorded nothing and said so only as "added: 0".
    A deliberate press bypasses the gate. source=auto (the default) files them
    under the statistical record; source=manual files them as your own picks.
    """
    p = _state["payload"]
    if not p:
        raise HTTPException(404, "No scan available to record. Run a universe scan first.")
    source = "manual" if source == "manual" else "auto"
    res = _autotrack(p, source=source, force=True)
    return {**(res or {}), "scanned_at": p.get("scanned_at"), "recorded_as": source,
            "total_tracked": tracker.listing(source="")["count"]}


@app.get("/tracker/stats")
def tracker_stats(source: str = ""):
    """source="" is the whole ledger; "manual" is your own picks. The Tracker
    tab passes whichever list it is showing, so the headline numbers describe
    the rows underneath them instead of a different population."""
    return tracker.stats(source=source)


@app.post("/tracker/add")
def tracker_add(payload: dict = Body(...)):
    """Add one idea by hand. The scan records everything automatically anyway;
    this is for names spotted outside the Ideas list."""
    return tracker.add(payload, source="manual")


@app.post("/tracker/purge-auto")
def tracker_purge_auto(x_admin_key: Optional[str] = Header(None, alias="X-Admin-Key")):
    """Delete every row the scanner recorded on its own.

    Needed once after 28 Aug 2026: automatic recording ran from the start, so
    an existing tracker already holds rows nobody asked for. Manual rows and
    anything promoted by a click are untouched."""
    expected = os.getenv("ADMIN_KEY")
    if expected and x_admin_key != expected:
        raise HTTPException(status_code=401, detail="admin key required")
    return tracker.purge(source="auto")


@app.post("/tracker/remove")
def tracker_remove(id: str = ""):
    if not id:
        raise HTTPException(400, "id is required")
    return tracker.remove(id)


# Marking reads price feeds, so it must not be possible to run two passes at
# once or to ask for a hundred symbols in one request and have the browser give
# up halfway. One at a time, small batches.
_marking = threading.Lock()


@app.post("/tracker/update")
def tracker_update(key: str = "", limit: int = 25, force: bool = False):
    """
    Mark tracked ideas with their current prices.

    Two changes, both of which the Refresh prices button needed:

    · No admin key. This endpoint reads public closes and writes the price
      columns of rows the user already owns — it is not a control endpoint.
      Guarding it meant the button prompted for a key, and anyone who had not
      set ADMIN_KEY on Render (or typed it wrong once, since the wrong value is
      cached for the session) got 401 and concluded the feature was broken.
      It is protected instead by a lock and a batch cap, which is what actually
      matters here: the risk was hammering the price feed, not authorship.

    · force=true re-marks rows already marked today, which is the whole point
      of a manual refresh button. Without it a press after the daily cron run
      returned "updated: 0" and looked like a no-op.
    """
    if not _marking.acquire(blocking=False):
        raise HTTPException(409, "A marking pass is already running — let it finish.")
    try:
        return tracker.update_all(limit=max(1, min(int(limit), 25)), force=bool(force))
    finally:
        _marking.release()


@app.get("/tracker/export.csv")
def tracker_export():
    return Response(content=tracker.export_csv(), media_type="text/csv",
                    headers={"Content-Disposition":
                             "attachment; filename=altaha-tracked-ideas.csv"})


@app.get("/ideas/export.csv")
def ideas_export(horizon: str = "short", limit: int = 25,
                 min_tier: str = "moderate", include_thin: bool = False):
    p = _state["payload"]
    if not p:
        raise HTTPException(404, "No scan yet.")
    sel = ideas_engine.select(p, horizon=horizon, limit=max(1, min(limit, 25)),
                              min_tier=min_tier, include_thin=bool(include_thin))
    cols = ["symbol", "name", "sector", "setup", "conviction", "conviction_band",
            "setup_fit", "composite", "technical", "fundamental", "f_score",
            "price", "horizon", "liquidity_tier", "avg_turnover_cr",
            "sector_state", "catalyst_category", "adverse_filing"]
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
    w.writeheader()
    # The 0..100 columns come from the v4 engine, which works in peer
    # percentiles and keeps full precision on purpose so ranking can separate
    # near-identical rows. A spreadsheet is not ranking anything, and a cell
    # reading 71.63358681820048 is unreadable, so the published copy is
    # rounded to the precision the number actually carries.
    def _cell(v):
        return round(v, 1) if isinstance(v, float) else v

    for r in sel["rows"]:
        # Flatten the two nested objects the CSV wants a column for; a
        # DictWriter would otherwise print the whole dict into one cell.
        row = {**r,
               "sector_state": (r.get("sector_outlook") or {}).get("state"),
               "catalyst_category": (r.get("catalyst") or {}).get("category")}
        w.writerow({k: _cell(row.get(k)) for k in cols})
    return Response(content=buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition":
                             f"attachment; filename=altaha-ideas-{horizon}.csv"})


@app.get("/patterns")
def chart_patterns(ticker: str, range: str = "1D", base_rates: bool = True):
    """
    Classical chart patterns for one symbol, with the geometry that defines
    each one, the price that confirms or kills it, and how often the same
    shape resolved in this stock's own history.

    Also returns the forward indicator mechanics: the close that would put RSI
    at 30/50/70, the price that flips Supertrend, how many sessions until a
    moving-average cross at an unchanged price. Those are solved from the
    indicator formulas with history held fixed — arithmetic, not forecasts.

    Patterns want daily bars. An intraday range is accepted but the shapes are
    correspondingly less meaningful, and the payload says which timeframe it
    measured so nobody has to guess.
    """
    key, cfg = _pick_range(range or "1D")
    if not cfg:
        raise HTTPException(400, f"range must be one of {', '.join(RANGES)}")

    base = ticker.strip().upper().replace(".NS", "").replace(".BO", "")
    if cfg["mode"] == "intraday":
        if dhan is None or not dhan.configured():
            raise HTTPException(503, "Intraday patterns need the Dhan data feed. "
                                     "Daily and weekly work without it.")
        try:
            df = dhan.intraday_ohlcv(base, interval=cfg["interval"], days=cfg["days"])
        except Exception:
            df = None
        if df is None or len(df) < 80:
            raise HTTPException(404, f"Not enough intraday history for {base} to read a pattern.")
    else:
        try:
            _sym, _t, hist = resolve(base)
        except NotFound:
            raise HTTPException(404, f"Couldn't find '{base}'.")
        except Exception:
            raise HTTPException(503, "The data provider is busy. Try again in a minute.")
        df = hist.tail(cfg["sessions"])
        if cfg.get("resample_w") and isinstance(df.index, pd.DatetimeIndex):
            df = _resample_weeks(df)

    try:
        out = pattern_engine.analyse(df, symbol=base,
                                     with_base_rates=bool(base_rates),
                                     timeframe=key)
    except Exception as e:
        raise HTTPException(500, f"Pattern analysis failed: {str(e)[:120]}")
    return to_native({**out, "range": key, "disclaimer_global": DISCLAIMER})


# ---------------------------------------------------------------------------
# Share cards
#
# No social crawler runs JavaScript. Twitterbot, facebookexternalhit and
# WhatsApp fetch the URL, read the <meta> tags out of the raw HTML and leave —
# so a single-page app served as one static index.html can only ever advertise
# one image, however cleverly the page rewrites its own head afterwards.
#
# /share/SYMBOL is the answer: a small server-rendered document carrying the
# tags for that one stock, which forwards a human straight on to the app. That
# is the link to paste into a post.
# ---------------------------------------------------------------------------

# The deep-link parameters the FRONTEND actually parses, not ones invented
# here. index.html reads ?q=SYMBOL to fill the search box and run the
# analysis, and ?go=TAB to open a tab on arrival. Sending ?ticker= instead —
# which is what this shipped with — produced a share link whose card previewed
# correctly and whose click-through landed on an empty homepage: the crawler
# was happy and the human was not.
SHARE_QUERY_PARAM = "q"
SHARE_TAB_PARAM = "go"

SITE_URL = os.environ.get("SITE_URL", "https://altahascreener.in").rstrip("/")
API_URL = os.environ.get("API_URL", "https://taha-project.onrender.com").rstrip("/")

# The host a shared link is allowed to show.
#
# The API runs on Render, and until now every card URL and every share link
# handed out read https://taha-project.onrender.com/... A link is the first
# thing anybody sees of this product, and a free-tier PaaS hostname in it says
# "someone's weekend project" before the card has finished loading. It is also
# an operational lock-in: every link ever posted breaks the day the API moves.
#
# vercel.json now proxies /share/* and /og/* from the site's own domain
# straight through to the API, so the same documents are reachable at
# SHARE_ORIGIN and that is the only host that appears in public. Set
# SHARE_ORIGIN explicitly once a custom domain is in place; nothing else has
# to change.
SHARE_ORIGIN = os.environ.get("SHARE_ORIGIN", SITE_URL).rstrip("/")

_PNG_HEADERS = {"Cache-Control": "public, max-age=3600, s-maxage=86400"}


@app.get("/og/stock.png")
def og_stock(ticker: str):
    """The share card for one stock: scores and the archetype.

    Deliberately carries no entry, stop or target. Those are on the site next
    to their own ledger; on a public image they would be a recommendation."""
    if not ticker or len(ticker) > 20:
        raise HTTPException(400, "Provide a valid ticker symbol.")
    sym = ticker.strip().upper()
    try:
        png = og_cards.cached(f"stock:{sym}", lambda: og_cards.stock_card(analyze(sym)))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Could not render the card: {str(e)[:100]}")
    return Response(content=png, media_type="image/png", headers=_PNG_HEADERS)


@app.get("/og/record.png")
def og_record():
    """The track-record card — the one claim here nobody else publishes."""
    try:
        png = og_cards.cached("record", lambda: og_cards.record_card(tracker.stats()))
    except Exception as e:
        raise HTTPException(500, f"Could not render the card: {str(e)[:100]}")
    return Response(content=png, media_type="image/png", headers=_PNG_HEADERS)


@app.get("/share/record")
def share_record():
    st = tracker.stats()
    o = st.get("overall") or {}
    alpha = o.get("avg_alpha_pct")
    beat = o.get("beat_index_pct")
    desc = (f"{st.get('total_tracked', 0)} ideas recorded automatically — winners and "
            f"losers. {beat}% beat the index" if beat is not None else
            f"{st.get('total_tracked', 0)} ideas recorded automatically.")
    if alpha is not None:
        desc += f", average alpha {alpha:+.2f}% over the index across the identical window."
    return Response(content=og_cards.share_page(
        "Does the Altaha engine work?", desc,
        f"{SHARE_ORIGIN}/og/record.png", f"{SITE_URL}/?go=tracker"),
        media_type="text/html")


# ---------------------------------------------------------------------------
# The rest of the cards
#
# Every card the site shows can be published, because a screener that only
# publishes its good days is advertising rather than analysis. A chart, an
# idea with its ledger, a tracked position marked to market — winners and
# losers render identically and neither is easier to post than the other.
# ---------------------------------------------------------------------------


def _og_frame(base: str, raw: str):
    """
    Candles for a card, at the requested timeframe.

    Differs from /chart in one way that matters: a card must never fail. An
    intraday range with no Dhan feed behind it silently becomes the daily
    chart rather than a 503, because the alternative is a broken image in
    somebody's timeline — and a daily chart is a truthful answer to "show me
    this stock", just not the one that was asked for.
    """
    key, cfg = _pick_range(raw or "1D", fallback="1D")

    if cfg["mode"] == "intraday" and dhan is not None and dhan.configured():
        try:
            df = dhan.intraday_ohlcv(base, interval=cfg["interval"], days=cfg["days"])
        except Exception:
            df = None
        if df is not None and len(df) >= 40:
            if cfg.get("resample") and isinstance(df.index, pd.DatetimeIndex):
                df = _resample_hours(df, cfg["resample"])
            return key, cfg["label"], df

    if cfg["mode"] == "intraday":
        key, cfg = "1D", RANGES["1D"]

    try:
        _sym, _t, hist = resolve(base)
    except NotFound:
        raise HTTPException(404, f"Couldn't find '{base}'.")
    except Exception:
        raise HTTPException(503, "The data provider is busy. Try again in a minute.")
    df = hist.tail(cfg["sessions"])
    if cfg.get("resample_w") and isinstance(df.index, pd.DatetimeIndex):
        df = _resample_weeks(df)
    return key, cfg["label"], df


def _chart_card_payload(base: str, raw_range: str):
    from engine import ema

    key, label, df = _og_frame(base, raw_range)
    if df is None or len(df) < 20:
        raise HTTPException(404, f"Not enough price history for {base}.")

    close = df["Close"]
    e20, e50 = ema(close, 20), ema(close, 50)
    candles, ema20, ema50 = [], [], []
    for i in df.index:
        try:
            candles.append([
                int(pd.Timestamp(i).timestamp()) if isinstance(df.index, pd.DatetimeIndex) else None,
                float(df.at[i, "Open"]), float(df.at[i, "High"]),
                float(df.at[i, "Low"]), float(df.at[i, "Close"]),
                float(df.at[i, "Volume"]) if "Volume" in df.columns
                and not pd.isna(df.at[i, "Volume"]) else 0.0,
            ])
        except Exception:
            continue
        v20, v50 = e20.get(i), e50.get(i)
        ema20.append(None if pd.isna(v20) else float(v20))
        ema50.append(None if pd.isna(v50) else float(v50))

    if not candles:
        raise HTTPException(404, f"Chart data could not be assembled for {base}.")

    # The strongest shape on this timeframe, if there is one. A card with no
    # pattern on it is published as readily as one with a pattern, and says so.
    shape = None
    try:
        out = pattern_engine.analyse(df, symbol=base, with_base_rates=False, timeframe=key)
        rows = (out or {}).get("patterns") or []
        if rows:
            top = rows[0]
            shape = {"name": top.get("name"), "status": top.get("status"),
                     "direction": top.get("direction"), "confidence": top.get("confidence"),
                     "points": top.get("points") or []}
    except Exception:
        shape = None

    # The company name, from the same NSE list the scan uses (cached for a
    # day). A card headed "RELIANCE" instead of "Reliance Industries Limited"
    # is not wrong, only worse, so this never raises.
    name = base
    try:
        for r in scanner.universe_with_names() or []:
            if str(r.get("s") or "").upper() == base:
                name = r.get("n") or base
                break
    except Exception:
        pass

    first, last = candles[0][4], candles[-1][4]
    return {
        "symbol": base, "name": name, "timeframe": label,
        "candles": candles, "ema20": ema20, "ema50": ema50,
        "last": round(last, 2),
        "change_pct": round(100 * (last - first) / first, 2) if first else None,
        "shape": shape,
        "range_key": key,
    }


@app.get("/og/chart.png")
def og_chart(ticker: str, range: str = "1D"):
    """The price chart with the detected shape drawn on it.

    Carries the candles and the geometry — never the trigger or the measured
    move, which are forecasts and stay on the site beside their base rate."""
    if not ticker or len(ticker) > 20:
        raise HTTPException(400, "Provide a valid ticker symbol.")
    sym = ticker.strip().upper().replace(".NS", "").replace(".BO", "")
    rng = (range or "1D").strip()[:4]
    try:
        png = og_cards.cached(f"chart:{sym}:{rng}",
                              lambda: og_cards.chart_card(_chart_card_payload(sym, rng)))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Could not render the card: {str(e)[:100]}")
    return Response(content=png, media_type="image/png", headers=_PNG_HEADERS)


def _idea_row(sym: str, horizon: str):
    """The idea row for one symbol, or None if it is not on the current list."""
    p = _state["payload"]
    if not p:
        return None
    try:
        out = ideas_engine.select(p, horizon=horizon, limit=25, include_thin=True)
    except Exception:
        return None
    for row in (out or {}).get("rows") or []:
        if str(row.get("symbol") or "").upper() == sym:
            return row
    return None


@app.get("/og/idea.png")
def og_idea(ticker: str, horizon: str = "short"):
    """An idea with the seven weighted inputs that add up to its conviction."""
    if not ticker or len(ticker) > 20:
        raise HTTPException(400, "Provide a valid ticker symbol.")
    sym = ticker.strip().upper().replace(".NS", "").replace(".BO", "")
    h = (horizon or "short").strip().lower()[:10]

    def build():
        row = _idea_row(sym, h)
        # Not on today's list — the stock still has a scorecard, and a card
        # that renders the wrong thing beats a link that previews as a grey box.
        return og_cards.idea_card(row) if row else og_cards.stock_card(analyze(sym))

    try:
        png = og_cards.cached(f"idea:{sym}:{h}", build)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Could not render the card: {str(e)[:100]}")
    return Response(content=png, media_type="image/png", headers=_PNG_HEADERS)


def _tracked_row(sym: str):
    for row in (tracker.listing(source="", limit=800) or {}).get("rows") or []:
        if str(row.get("symbol") or "").upper() == sym:
            return row
    return None


@app.get("/og/holding.png")
def og_holding(ticker: str):
    """A tracked idea marked to market — return, alpha, days held."""
    if not ticker or len(ticker) > 20:
        raise HTTPException(400, "Provide a valid ticker symbol.")
    sym = ticker.strip().upper().replace(".NS", "").replace(".BO", "")

    def build():
        row = _tracked_row(sym)
        if not row:
            raise HTTPException(404, f"{sym} is not in the tracker.")
        return og_cards.holding_card(row)

    try:
        png = og_cards.cached(f"holding:{sym}", build)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Could not render the card: {str(e)[:100]}")
    return Response(content=png, media_type="image/png", headers=_PNG_HEADERS)


@app.get("/share/chart/{ticker}")
def share_chart(ticker: str, range: str = "1D"):
    if not ticker or len(ticker) > 20:
        raise HTTPException(400, "Provide a valid ticker symbol.")
    sym = ticker.strip().upper().replace(".NS", "").replace(".BO", "")
    rng = (range or "1D").strip()[:4]
    shape, label, name = None, "1 day", sym
    try:
        payload = _chart_card_payload(sym, rng)
        shape, label, name = payload["shape"], payload["timeframe"], payload["name"]
    except Exception:
        pass
    if shape:
        desc = (f"{name} on the {label} chart — {shape['name']}, {shape['status']}, "
                f"{shape['confidence']} shape match. Every check behind that reading, "
                "and how the same shape resolved here before, opens on the site.")
    else:
        desc = (f"{name} on the {label} chart. No textbook pattern right now — which is "
                "the usual answer, and a detector that always finds one has stopped "
                "detecting.")
    return Response(content=og_cards.share_page(
        f"{name} ({sym}) — {label} chart", desc,
        f"{SHARE_ORIGIN}/og/chart.png?ticker={sym}&range={rng}",
        f"{SITE_URL}/?q={sym}&go=charts&range={rng}"),
        media_type="text/html")


@app.get("/share/idea/{ticker}")
def share_idea(ticker: str, horizon: str = "short"):
    if not ticker or len(ticker) > 20:
        raise HTTPException(400, "Provide a valid ticker symbol.")
    sym = ticker.strip().upper().replace(".NS", "").replace(".BO", "")
    h = (horizon or "short").strip().lower()[:10]
    row = _idea_row(sym, h)
    if row:
        name = row.get("name") or sym
        desc = (f"{name} scores {row.get('conviction')}/100 conviction on the "
                f"{h}-term list — {row.get('setup') or 'no archetype'}, typical hold "
                f"{row.get('horizon') or '—'}. The seven weighted inputs that add up "
                "to that number are published beside it.")
    else:
        name, desc = sym, (f"{sym} is not on the current {h}-term list. The scorecard "
                           "and the arithmetic behind it are on the site.")
    return Response(content=og_cards.share_page(
        f"{name} ({sym}) — conviction {row.get('conviction') if row else '—'}/100",
        desc,
        f"{SHARE_ORIGIN}/og/idea.png?ticker={sym}&horizon={h}",
        f"{SITE_URL}/?q={sym}&go=ideas"),
        media_type="text/html")


@app.get("/share/holding/{ticker}")
def share_holding(ticker: str):
    if not ticker or len(ticker) > 20:
        raise HTTPException(400, "Provide a valid ticker symbol.")
    sym = ticker.strip().upper().replace(".NS", "").replace(".BO", "")
    row = _tracked_row(sym)
    if not row:
        raise HTTPException(404, f"{sym} is not in the tracker.")
    name = row.get("name") or sym

    def pct(v):
        return "—" if v is None else f"{float(v):+.2f}%".replace("+-", "-")

    desc = (f"{name}, recorded on {row.get('added_on')} and marked to market since: "
            f"{pct(row.get('return_pct'))} against {pct(row.get('bench_return_pct'))} "
            f"for the index — {pct(row.get('alpha_pct'))} alpha over "
            f"{row.get('days_held') or 0} days. Logged in advance, winners and losers "
            "alike.")
    return Response(content=og_cards.share_page(
        f"{name} ({sym}) — {pct(row.get('return_pct'))} since the idea was recorded",
        desc,
        f"{SHARE_ORIGIN}/og/holding.png?ticker={sym}",
        f"{SITE_URL}/?go=tracker"),
        media_type="text/html")


@app.get("/share/{ticker}")
def share_stock(ticker: str):
    if not ticker or len(ticker) > 20:
        raise HTTPException(400, "Provide a valid ticker symbol.")
    sym = ticker.strip().upper().replace(".NS", "").replace(".BO", "")
    try:
        payload = analyze(sym)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(404, f"Couldn't analyse '{sym}'.")
    _s, name, comp, label, tech, fund, _f, setup = og_cards._read(payload)
    score = "—" if comp is None else str(int(round(comp)))
    desc = (f"{name} scores {score}/100"
            + (f" ({label.lower()})" if label else "")
            + (f". Technical {int(tech)}, fundamental {int(fund)}."
               if tech is not None and fund is not None else ".")
            + (f" Setup: {setup}." if setup else "")
            + " Every number opens into the arithmetic behind it.")
    return Response(content=og_cards.share_page(
        f"{name} ({sym}) — Altaha Screener", desc,
        f"{SHARE_ORIGIN}/og/stock.png?ticker={sym}", f"{SITE_URL}/?q={sym}"),
        media_type="text/html")


@app.get("/score-history")
def score_history(ticker: str, limit: int = 400):
    """
    How this stock's own score has moved.

    Every universe scan banks a point-in-time snapshot of what the engine
    believed that day. Financial history is everywhere; a screener's own score
    history is not, and it is the natural extension of showing the working —
    it lets a reader see not just what the engine thinks but when it changed
    its mind.

    The record only goes back as far as the scans do, so a fresh deployment
    answers honestly with an empty series rather than inventing one.
    """
    if pit_store is None:
        return {"available": False, "message": "The point-in-time store is not available."}
    if not ticker or len(ticker) > 20:
        raise HTTPException(400, "Provide a valid ticker symbol.")
    sym = ticker.strip().upper().replace(".NS", "").replace(".BO", "")
    try:
        hist = pit_store.score_history(sym, limit=max(2, min(limit, 2000)))
        change = pit_store.score_change(sym, "composite")
    except Exception as e:
        raise HTTPException(503, f"Point-in-time store unavailable: {str(e)[:100]}")

    rows = hist.get("rows") or []
    if not rows:
        return {"available": False, "symbol": sym, "rows": [],
                "message": ("No scan has recorded this symbol yet. The history builds "
                            "one universe scan at a time — it cannot be backfilled, "
                            "because a score computed today is not what the engine "
                            "believed in March.")}
    return {"available": True, "symbol": sym, **hist, "change": change,
            "note": ("Each row is what the engine believed on that date, written at "
                     "the time and never rewritten. A gap in the dates is a day no "
                     "universe scan ran.")}


@app.get("/pit/coverage")
def pit_coverage():
    """
    How much point-in-time data has actually been banked, and if none, why.

    Answers 200 even when the store is broken. This endpoint exists to explain
    a failure; returning 503 with a bare sqlite string ("unable to open
    database file") told nobody whether DATA_DIR was unset, the directory was
    missing, or the disk was read-only — which is exactly the question being
    asked.
    """
    if pit_store is None:
        return {"available": False,
                "reason": "pit_store failed to import — the store records nothing."}
    return {"available": True, **pit_store.coverage_report()}


# ---------------------------------------------------------------------------
# The measurement stack
#
# A scoring engine that has never been scored is the one place this project's
# claim to show its working did not hold. These endpoints close that: what was
# believed, what happened next, and what the difference says about each factor.
# ---------------------------------------------------------------------------


@app.get("/pit/label")
def pit_label(limit_symbols: int = 0):
    """
    Attach forward returns to everything banked whose horizon has elapsed.

    Idempotent and safe to call repeatedly — it fills what is missing and
    leaves the rest. Normally driven by /cron/tick; exposed so it can be run
    by hand after a backfill.
    """
    if fwd_labels is None:
        raise HTTPException(503, "The labelling job is unavailable.")
    return fwd_labels.run(limit_symbols=limit_symbols or None)


@app.get("/pit/ic")
def pit_ic(horizon: int = 21, factor: Optional[str] = None,
           min_cross_section: int = 25):
    """
    The information coefficient: does a factor predict anything?

    On each date, rank every stock by the factor and by what it then did
    relative to the index, and correlate the two. A real, professionally
    traded equity factor runs 0.03 to 0.05 — right about 52% of the time. That
    is not a weak result, it is what this looks like when it works; the money
    comes from breadth, not from being right about any one name.

    Returns nothing rather than a number when the sample is too thin. An
    average built from three overlapping fortnights would be quoted forever
    and caveated once.
    """
    if factor_lab is None or pit_store is None:
        raise HTTPException(503, "The Factor Lab is unavailable.")
    h = max(1, min(int(horizon), 500))
    m = max(5, min(int(min_cross_section), 500))
    if factor:
        return factor_lab.evaluate(factor.strip()[:60], h, m)
    return factor_lab.sweep(h, min_cross_section=m)


@app.get("/pit/correlations")
def pit_correlations():
    if factor_lab is None:
        raise HTTPException(503, "The Factor Lab is unavailable.")
    return factor_lab.correlations()


@app.get("/pit/suggested-weights")
def pit_suggested_weights(horizon: int = 63):
    if factor_lab is None:
        raise HTTPException(503, "The Factor Lab is unavailable.")
    if horizon not in (5, 10, 21, 63, 126):
        raise HTTPException(400, "Use a supported session horizon.")
    return factor_lab.suggested_weights(horizon)


@app.get("/factors")
def factors_for(ticker: str, horizon: str = "short"):
    """
    The orthogonal factor block for one stock: momentum with the last month
    skipped, one-week reversal, trend quality, realised volatility, turnover
    shock, and — from the company's own XBRL filing — growth, margin
    direction, return on assets and earnings yield.

    Every fundamental factor respects the filing date, not the period end. A
    December quarter was not knowable in December.
    """
    if factor_lib is None:
        raise HTTPException(503, "The factor library is unavailable.")
    base = ticker.strip().upper().replace(".NS", "").replace(".BO", "")
    try:
        _sym, _t, hist = resolve(base)
    except NotFound:
        raise HTTPException(404, f"Couldn't find '{base}'.")
    except Exception:
        raise HTTPException(503, "The data provider is busy. Try again in a minute.")

    quarters = []
    if xbrl_source is not None:
        try:
            quarters = xbrl_source.scoring_statements(base)
        except Exception:
            quarters = []

    price = float(hist["Close"].dropna().iloc[-1]) if hist is not None and len(hist) else None
    values = factor_lib.compute(hist, quarters=quarters, price=price)

    # Whether the fundamental half was withheld, and why. NSE's XBRL results
    # index is frozen at the December 2024 quarter, so for most symbols it
    # currently is — and a caller must be able to tell "this company has no
    # value factor" from "we refused to compute one from a dead source".
    fundamentals = {
        "withheld": bool(values.get("_fundamentals_stale")),
        "reason": values.get("_fundamentals_note"),
        "quarters_available": len(quarters),
    }
    if xbrl_source is not None and quarters:
        try:
            fundamentals["freshness"] = xbrl_source.freshness(quarters, base)
        except Exception:
            pass

    return to_native({
        "symbol": base, "price": price, "horizon": horizon,
        "factors": values,
        "altaha_score_v4": _cached_v4(base),
        "fundamentals": fundamentals,
        "families": {n: {"family": factor_lib.REGISTRY[n][0],
                         "label": factor_lib.REGISTRY[n][1],
                         "value": values.get(n)} for n in factor_lib.REGISTRY},
        "note": ("Higher is better for every factor — volatility and reversal are "
                 "negated at source, so nothing downstream has to remember which "
                 "way each one points."),
        "disclaimer": DISCLAIMER,
    })


@app.get("/factors/rank")
def factors_rank(horizon: str = "short", limit: int = 50):
    """
    The whole scanned universe ranked against itself.

    Percentiles, not absolute scores: an absolute 0-100 scale saturates once
    everything that survives a scan already sits in the high eighties, which
    is why a live list could score eight names inside 3.4 points with a tie in
    it. And factors are averaged within their family before the families are
    weighted, so two measurements of the same thing sharpen one estimate
    instead of casting two votes.
    """
    if multifactor is None:
        raise HTTPException(503, "The ranking layer is unavailable.")
    p = _state["payload"]
    rows = (p or {}).get("rankings") or []
    if not rows:
        return {"available": False,
                "message": "No scan yet — generate the ranking first."}
    h = horizon if horizon in multifactor.WEIGHTS else "short"
    rows = (p or {}).get("factor_universe") or rows
    if rows and all(r.get("altaha_score_v4", {}).get("position") for r in rows):
        hz = {"short": "trade", "medium": "position"}.get(h, h)
        projected = []
        for original in rows:
            r = dict(original)
            v4 = r["altaha_score_v4"]
            score = v4[hz]
            r.update(factor_score=score["final_score"], final_factor_score=score["final_score"],
                     raw_factor_score=score["raw_score"], confidence_score=score["confidence"],
                     family_coverage_pct=score["family_coverage_pct"], families=score["pillars"])
            projected.append(r)
        projected.sort(key=lambda r: (-r["factor_score"], r["symbol"]))
        previous, rank_no = None, 0
        for i, r in enumerate(projected):
            if r["factor_score"] != previous: rank_no = i + 1
            r["factor_rank"] = rank_no
            previous = r["factor_score"]
        out = {"available": True, "horizon": h, "rows": projected,
               "universe": len(rows), "ranked": len(rows), "methodology_version": "v4",
               "families": factor_lib.FAMILIES, "weights": PR.V4_WEIGHTS[hz],
               "caveat": "Fixed prior weights; cached scan-date scores, not probabilities."}
    else:
        out = multifactor.rank(rows, horizon=h)
        out["input_status"] = "Unversioned legacy scan; preview only. Rescan to bank canonical v4 scores."
    if not out.get("available"):
        return out
    ranked = [r for r in out["rows"] if r.get("factor_score") is not None]
    ranked.sort(key=lambda r: -r["factor_score"])
    out["rows"] = ranked[:max(1, min(int(limit), 200))]
    out["scanned_at"] = (p or {}).get("scanned_at")
    out["disclaimer"] = DISCLAIMER
    return to_native(out)


# ---------------------------------------------------------------------------
# Bulk, block and short deals
#
# Exchange disclosures of who traded size, published through the day and
# complete after the close. Not a live trade feed — there is no such thing as
# a real-time bulk deal, because a bulk deal is a report about a trade rather
# than the trade itself.
# ---------------------------------------------------------------------------


@app.get("/deals")
def deals_board(min_value_cr: float = 1.0, limit: int = 40):
    """
    Today's disclosures, netted per stock and ranked by what was actually
    accumulated.

    The netting is the point. A stock with a large buy and an equally large
    sell saw its shares change hands, not demand arrive; and a substantial
    share of bulk-deal rows in small caps are proprietary desks providing
    liquidity, whose presence carries no view about the company. Both are
    separated out here rather than left for the reader to fall for.
    """
    if deals_source is None:
        raise HTTPException(503, "The deals feed is unavailable.")
    try:
        return to_native(deals_source.board(
            min_value_cr=max(0.0, float(min_value_cr)),
            limit=max(1, min(int(limit), 200))))
    except Exception as e:
        raise HTTPException(503, f"Deals feed unavailable: {str(e)[:120]}")


@app.get("/deals/{ticker}")
def deals_for(ticker: str, days: int = 90):
    """Every bulk and block disclosure for one stock, newest first."""
    if deals_source is None:
        raise HTTPException(503, "The deals feed is unavailable.")
    if not ticker or len(ticker) > 20:
        raise HTTPException(400, "Provide a valid ticker symbol.")
    try:
        out = deals_source.for_symbol(ticker, days=max(1, min(int(days), 365)))
    except Exception as e:
        raise HTTPException(503, f"Deals feed unavailable: {str(e)[:120]}")
    out["disclaimer"] = DISCLAIMER
    return to_native(out)


@app.get("/attention")
def attention_for(ticker: str):
    """
    Unusual retail attention, as a RISK flag and never as a buy signal.

    For Indian small and mid caps a mention spike is far more often a pump in
    progress than a discovery. This never touches a score; it sits beside one.
    """
    if attention_mod is None:
        raise HTTPException(503, "The attention module is unavailable.")
    base = ticker.strip().upper().replace(".NS", "").replace(".BO", "")
    hist = None
    try:
        _sym, _t, hist = resolve(base)
    except Exception:
        hist = None

    filings, stories = [], []
    try:
        filings = (ann.feed(limit=40, symbol=base) or {}).get("items") or []
    except Exception:
        filings = []
    try:
        stories = (ideas_engine._news_index(168)[0] or {}).get(base) or []
    except Exception:
        stories = []

    # Thin liquidity is what turns attention from interesting into dangerous,
    # so the tier is looked up when the scan knows it.
    tier = None
    try:
        for r in ((_state["payload"] or {}).get("rankings") or []):
            if str(r.get("symbol") or "").upper() == base:
                tier = ideas_engine.liquidity_tier(r.get("avg_turnover_cr"))[0]
                break
    except Exception:
        tier = None

    # A disclosed bulk or block deal is the hardest attention signal available
    # and it is free — the exchange publishes it. Failure is silent by design:
    # the flag is weaker without it, never absent.
    deal = None
    if deals_source is not None:
        try:
            deal = (deals_source.for_symbol(base, days=30) or {}).get("net")
        except Exception:
            deal = None

    return to_native(attention_mod.assess(base, df=hist, filings=filings,
                                          stories=stories, liquidity_tier=tier,
                                          deals=deal))


@app.get("/fundamentals/xbrl")
def fundamentals_xbrl(ticker: str, limit: int = 8, consolidated: Optional[bool] = None):
    """
    Quarterly results read from the company's own XBRL filing with the
    exchange, under LODR Regulation 33.

    This is the primary source rather than a scrape: the numbers are the ones
    the company filed, and the payload carries the URL of the filing each row
    came from so any figure can be checked against the document.

    It covers the income statement in full plus total assets and liabilities
    from the segment reconciliation. The rest of the balance sheet and the cash
    flow statement are not in a quarterly filing, and the response says so
    rather than leaving a reader to assume otherwise.
    """
    if xbrl_source is None:
        return {"available": False, "message": "The XBRL reader is not available."}
    if not ticker or len(ticker) > 20:
        raise HTTPException(400, "Provide a valid ticker symbol.")
    sym = ticker.strip().upper().replace(".NS", "").replace(".BO", "")
    try:
        return to_native(xbrl_source.summary(sym, limit=max(1, min(limit, 24)),
                                             consolidated=consolidated))
    except Exception as e:
        raise HTTPException(503, f"Could not read the filings: {str(e)[:110]}")


@app.get("/special")
def altaha_special(limit: int = 20):
    """
    Altaha Special — delivery-weighted momentum.

    Ranks on how much of a stock's advance happened on days when volume was
    actually DELIVERED rather than churned intraday. The delivery share is
    published by NSE per stock per day and does not exist in any OHLCV feed,
    which is the whole point: it is a signal the rest of the market's tooling
    cannot see.
    """
    if special_engine is None:
        raise HTTPException(503, "The Special engine is not loaded on this instance.")
    try:
        return to_native(special_engine.rank_universe(limit=max(5, min(int(limit), 50))))
    except Exception as e:
        raise HTTPException(503, f"Delivery data unavailable: {type(e).__name__}")


@app.get("/special/status")
def altaha_special_status():
    """Whether the delivery cache is deep enough to rank anything, and why not."""
    if special_engine is None:
        return {"ready": False, "error": "engine not loaded"}
    return to_native(special_engine.status())


@app.post("/special/refresh")
def altaha_special_refresh(days_back: int = 420,
                           x_admin_key: Optional[str] = Header(None, alias="X-Admin-Key")):
    """
    Extend the delivery cache. Incremental — it fetches only the sessions it is
    missing, so the first call is slow and every later one is quick.

    Behind the admin key because it walks a few hundred NSE files and a public
    button that does that is a public button that gets the instance blocked.
    """
    expected = os.getenv("ADMIN_KEY")
    if expected and x_admin_key != expected:
        raise HTTPException(status_code=401, detail="admin key required")
    if special_engine is None:
        raise HTTPException(503, "The Special engine is not loaded on this instance.")
    return to_native(special_engine.refresh(days_back=max(30, min(int(days_back), 1100))))


@app.get("/leaderboard")
def leaderboard(limit: int = 5):
    p = _state["payload"]
    if not p:
        return {"available": False, "status": _state["status"],
                "message": "No ranking generated yet."}
    return {
        "available": True,
        "status": _state["status"],
        "scanned_at": p.get("scanned_at"),
        "universe_size": p.get("universe_size"),
        "scored": p.get("scored"),
        "methodology": p.get("methodology"),
        "rankings": p.get("rankings", [])[: max(1, min(limit, 25))],
        "disclaimer": DISCLAIMER,
    }


# Portfolio jobs share bounded executors across requests on the 512 MB service.
# Slow providers may finish after a deadline, but cannot grow a new pool per job.
import portfolio_intelligence as PI
from datetime import datetime, timezone
from concurrent.futures import wait

_pf_workers = ThreadPoolExecutor(max_workers=PF_WORKERS, thread_name_prefix="portfolio")
_pf_enrichment = ThreadPoolExecutor(max_workers=2, thread_name_prefix="portfolio-enrichment")
_pf_jobs = {}
_pf_lock = threading.Lock()
PF_JOB_TTL = 900
PF_ANALYSIS_TIMEOUT = 100
PF_MAX_ACTIVE = 2
PF_MAX_JOBS = 20


def _pf_inputs(payload, limit=MAX_HOLDINGS):
    holdings = payload.get("holdings")
    if not isinstance(holdings, list) or not holdings or len(holdings) > limit:
        raise HTTPException(400, f"Provide 1–{limit} holdings.")
    if payload.get("policy") is not None and not isinstance(payload["policy"], dict):
        raise HTTPException(400, "Policy must be an object.")
    # Coalesce tax lots for concentration, preserving partial cost coverage by
    # withholding average cost if any lot is missing it.
    merged = {}
    import re
    for item in holdings:
        if not isinstance(item, dict):
            raise HTTPException(400, "Each holding must be an object.")
        symbol = str(item.get("symbol") or "").strip().upper()
        symbol = re.sub(r"\.NS$", "", symbol)
        if not re.fullmatch(r"[A-Z0-9][A-Z0-9&-]{0,24}", symbol):
            raise HTTPException(400, "Use an NSE symbol without a foreign exchange suffix.")
        qty = PI.number(item.get("qty"))
        raw_buy = item.get("buy_price")
        buy = PI.number(raw_buy)
        if qty is None or not 0 < qty <= 1e12:
            raise HTTPException(400, f"{symbol}: quantity must be positive and finite.")
        if raw_buy not in (None, "") and (buy is None or not 0 < buy <= 1e12):
            raise HTTPException(400, f"{symbol}: purchase price must be positive or omitted.")
        row = merged.setdefault(symbol, {"symbol":symbol, "qty":0., "_cost":0., "_complete":True})
        row["qty"] += qty
        row["_cost"] += qty*buy if buy is not None else 0.
        row["_complete"] = row["_complete"] and buy is not None
    return [{"symbol":r["symbol"], "qty":r["qty"],
             "buy_price":r["_cost"]/r["qty"] if r["_complete"] else None} for r in merged.values()]


def _pf_row(item, scan_row=None, quote=None, checked_at=None):
    scan_row, quote = scan_row or {}, quote or {}
    qprice = PI.number(quote.get("ltp"))
    price = qprice if qprice is not None and qprice > 0 else PI.number(scan_row.get("price"))
    v4 = scan_row.get("altaha_score_v4") or {}
    score = PI.number(v4.get("position", {}).get("final_score"))
    sec, src = sectors.resolve_sector(item["symbol"], scan_row)
    buy, qty = item.get("buy_price"), item["qty"]
    return {"symbol":item["symbol"], "name":scan_row.get("name") or item["symbol"],
            "qty":qty, "buy_price":buy, "price":price,
            "value":round(price*qty, 2) if price is not None and price > 0 else None,
            "cost":round(buy*qty, 2) if buy is not None else None,
            "sector":sec, "sector_source":src, "composite":score,
            "altaha_score_v4":v4, "technical":scan_row.get("technical"),
            "fundamental":scan_row.get("fundamental"), "setup":scan_row.get("setup"),
            "price_source":"Dhan quote (exchange time unavailable)" if qprice is not None and qprice > 0 else "Universe scan",
            "price_as_of":None if qprice is not None and qprice > 0 else checked_at,
            "price_checked_at":datetime.now(timezone.utc).isoformat(),
            "score_as_of":checked_at,
            "market_cap_bucket":None,
            "market_cap_note":"Official size classification unavailable; scan-relative size buckets are not SEBI classifications.",
            "error":None if price is not None and price > 0 else "Price unavailable", "warnings":[]}


def _analyse_holding(item, cached=None):
    # The initial quote/scan valuation survives a history or scoring failure.
    row = dict(cached or _pf_row(item))
    try:
        sym, t, hist = resolve(item["symbol"] + ".NS")
        if not sym.endswith(".NS"):
            raise ValueError("Only INR NSE listings are supported")
        price = PI.number(hist["Close"].iloc[-1])
        if price is not None and price > 0 and row.get("price_source") != "Dhan quote (exchange time unavailable)":
            row.update(price=price, value=round(item["qty"]*price,2), error=None,
                       price_source=hist.attrs.get("price_source", "Historical close (source unavailable)"),
                       price_as_of=str(hist.index[-1]) if hasattr(hist.index[-1], "date") else None)
        row["_history"] = hist
    except Exception:
        row["warnings"] = ["History unavailable; retained available quote or dated scan valuation."]
        return row
    try:
        tech = technical_score(hist)
        row.update(technical=tech.get("score"), technical_extras=tech.get("extras") or {},
                   technical_checks=tech.get("checks") or [])
        closes = hist['Close'].dropna()
        row['moving_averages'] = {str(n):round(100*(float(closes.iloc[-1])/float(closes.tail(n).mean())-1),2)
                                  for n in (20,50,200) if len(closes) >= n and closes.tail(n).mean() > 0}
        row['trend'] = 'Above 200-day average' if row['moving_averages'].get('200',0) > 0 else 'Below 200-day average' if '200' in row['moving_averages'] else 'Insufficient history'
    except Exception:
        row['warnings'] = row.get('warnings', []) + ['Technical scoring unavailable; position valuation retained.']
    try:
        fin, bs, cf, info = fundamentals(sym, t)
        fund = fundamental_score(fin, bs, cf, info)
        sec, source = sectors.resolve_sector(item['symbol'], info)
        row.update(name=info.get('longName') or info.get('shortName') or row['name'],
                   sector=sec, sector_source=source, fundamental=fund.get('score'),
                   fundamental_extras=fund.get('extras') or {}, fundamental_checks=fund.get('checks') or [],
                   fundamental_source='Provider annual statements; Altaha v4 factors use the dated universe scan / XBRL',
                   valuation={'pe':PI.number(info.get('trailingPE')), 'pb':PI.number(info.get('priceToBook')),
                              'market_cap':PI.number(info.get('marketCap'))})
    except Exception:
        row['warnings'] = row.get('warnings', []) + ['Fundamental enrichment unavailable.']
    return row


def _pf_news(holdings):
    items, status = [], {}
    try:
        # In-memory indexed joins, no per-holding network request. Do not cap
        # the global filing list before matching, which loses small holdings.
        for h in holdings:
            feed = ann.feed(limit=30, min_importance='low', symbol=h['symbol'])
            for raw in feed.get('rows') or []:
                item = dict(raw)
                url = item.get('pdf') or ''
                item['source'] = 'NSE filing' if 'nseindia' in url else 'BSE filing' if 'bseindia' in url else 'Exchange filing'
                items.append(item)
            status['filings'] = {'last_poll':feed.get('last_poll'), 'error':feed.get('error'), 'first_load':feed.get('first_load')}
    except Exception:
        status['filings'] = {'error':'Filing cache unavailable'}
    try:
        # One bulk cache read. Freshness is recalculated from published dates.
        items.extend(press.feed(limit=500, max_age_hours=168))
        status['press'] = press.status()
    except Exception:
        status['press'] = {'error':'Press cache unavailable'}
    return items, status


def _pf_sweep():
    now = time.time()
    with _pf_lock:
        for jid in [k for k,v in _pf_jobs.items() if v['status'] != 'running' and now-v.get('touched',now) > PF_JOB_TTL]:
            _pf_jobs.pop(jid, None)


def _pf_run(job_id, holdings, policy):
    scan = _state.get('payload') or {}
    scan_map = {r['symbol']:r for r in scan.get('factor_universe') or scan.get('rankings') or []}
    rows = [_pf_row(h, scan_map.get(h['symbol']), checked_at=scan.get('scanned_at')) for h in holdings]
    def publish(stage, report, done, final=False):
        report['stage'] = stage
        report['disclaimer'] = DISCLAIMER
        with _pf_lock:
            job = _pf_jobs.get(job_id)
            if job is not None:
                job.update(status='done' if final else 'running', report=to_native(report),
                           stage=stage, done=done, revision=job.get('revision',0)+1, touched=time.time())
    try:
        publish('Cached valuation', build_report(rows, scan, policy), 0)
        # Quotes are batched; their timeout cannot consume the report deadline.
        def quotes():
            import dhan_source
            return dhan_source.bulk_quotes([h['symbol'] for h in holdings]) if dhan_source.configured() else {}
        quote_task = _pf_enrichment.submit(quotes)
        ready, _ = wait([quote_task], timeout=8)
        try:
            quote_data = quote_task.result() if ready else {}
        except Exception:
            quote_data = {}
        rows = [_pf_row(h, scan_map.get(h['symbol']), quote_data.get(h['symbol']), scan.get('scanned_at')) for h in holdings]
        publish('Prices & scores', build_report(rows, scan, policy), 0)
        pending = {_pf_workers.submit(_analyse_holding, h, r):i for i,(h,r) in enumerate(zip(holdings, rows))}
        sector_task = _pf_enrichment.submit(sectors.momentum)
        deadline = time.monotonic()+PF_ANALYSIS_TIMEOUT
        histories, done = {}, 0
        while pending and time.monotonic() < deadline:
            ready, _ = wait(pending, timeout=min(1, max(0,deadline-time.monotonic())))
            for future in ready:
                i = pending.pop(future)
                try:
                    row = future.result()
                    history = row.pop('_history', None)
                    if history is not None: histories[row['symbol']] = history
                    rows[i] = row
                except Exception:
                    rows[i]['warnings'].append('Holding enrichment failed; available valuation retained.')
                done += 1
            with _pf_lock:
                if job_id in _pf_jobs: _pf_jobs[job_id].update(done=done, stage='Holding research', touched=time.time())
        for future,i in pending.items():
            future.cancel()
            rows[i]['warnings'].append('Enrichment deadline reached; available valuation retained. Retry to refresh.')
        try:
            sector_data = sector_task.result(timeout=0) if sector_task.done() else {'available':False, 'message':'Sector index enrichment timed out; allocation proxy remains available.'}
        except Exception:
            sector_data = {'available':False, 'message':'Sector index data unavailable.'}
        items, status = _pf_news(holdings)
        report = build_report(rows, scan, policy, sector_data, histories=histories, news_items=items, news_status=status)
        report['enrichment_incomplete'] = bool(pending)
        publish('Complete' if not pending else 'Complete with unavailable enrichment', report, done, True)
    except Exception:
        # A final enrichment error must never discard the earlier basic report.
        with _pf_lock:
            job = _pf_jobs.get(job_id)
            if job:
                if job.get('report'):
                    job['report']['enrichment_incomplete'] = True
                    job['report'].setdefault('data_quality',{}).setdefault('warnings',[]).append('Enrichment failed. Earlier valuation retained; retry for a fresh review.')
                    job.update(status='done', revision=job.get('revision',0)+1, touched=time.time())
                else:
                    job.update(status='error', error='Portfolio analysis unavailable. Please retry.', touched=time.time())


@app.post('/portfolio/start')
def portfolio_start(payload: dict = Body(...)):
    holdings = _pf_inputs(payload)
    policy = clean_policy(payload.get('policy'))
    _pf_sweep()
    with _pf_lock:
        if sum(j['status'] == 'running' for j in _pf_jobs.values()) >= PF_MAX_ACTIVE:
            raise HTTPException(429, 'Portfolio analysis is busy. Please retry shortly.')
        if len(_pf_jobs) >= PF_MAX_JOBS:
            finished = [k for k,v in _pf_jobs.items() if v['status'] != 'running']
            if finished: _pf_jobs.pop(min(finished,key=lambda k:_pf_jobs[k]['touched']))
        job_id = uuid.uuid4().hex
        _pf_jobs[job_id] = {'status':'running', 'done':0, 'total':len(holdings), 'report':None,
                            'error':None, 'stage':'Starting', 'revision':0, 'touched':time.time()}
    threading.Thread(target=_pf_run,args=(job_id,holdings,policy),daemon=True).start()
    return {'job_id':job_id, 'total':len(holdings), 'policy':policy}


@app.get('/portfolio/status')
def portfolio_status(job: str):
    with _pf_lock:
        state = _pf_jobs.get(job)
        if state is None: raise HTTPException(404, 'That analysis expired. Run it again.')
        state['touched'] = time.time()
        return dict(state)


@app.post('/portfolio')
def portfolio(payload: dict = Body(...)):
    # Backward-compatible synchronous result with the same arithmetic / contract.
    holdings = _pf_inputs(payload,20)
    scan = _state.get('payload') or {}
    scan_map = {r['symbol']:r for r in scan.get('factor_universe') or scan.get('rankings') or []}
    cached = [_pf_row(h,scan_map.get(h['symbol']),checked_at=scan.get('scanned_at')) for h in holdings]
    tasks = [_pf_workers.submit(_analyse_holding,h,r) for h,r in zip(holdings,cached)]
    ready,_ = wait(tasks,timeout=PF_ANALYSIS_TIMEOUT)
    rows,histories = [],{}
    for future,fallback in zip(tasks,cached):
        try: row = future.result() if future in ready else fallback
        except Exception: row = fallback
        if future not in ready: future.cancel()
        history = row.pop('_history',None)
        if history is not None: histories[row['symbol']] = history
        rows.append(row)
    items,status = _pf_news(holdings)
    report = build_report(rows,scan,payload.get('policy'),histories=histories,news_items=items,news_status=status)
    report['disclaimer'] = DISCLAIMER
    return to_native(report)


@app.get("/news/press")
def news_press(limit: int = 30, sector: str = "", symbol: str = ""):
    """
    Financial-press headlines, matched to sectors and symbols.

    Kept deliberately separate from /announcements, which is the exchange feed.
    A journalist's rewrite of a filing is not the filing, and nothing in this
    feed influences a score or an alert threshold.
    """
    try:
        syms = [symbol] if symbol else None
        return {"rows": press.feed(limit=limit, symbols=syms, sector=sector),
                "kind": "press",
                "disclaimer": ("Reporting about events, not the events themselves. "
                               "For the primary source see /announcements.")}
    except Exception as e:
        raise HTTPException(503, f"Press feed unavailable: {str(e)[:120]}")


@app.get("/news/status")
def news_status():
    """Which press sources are answering, and how stale the cache is."""
    try:
        return press.status()
    except Exception as e:
        raise HTTPException(503, f"Press status unavailable: {str(e)[:120]}")


@app.get("/sector/overview")
def sector_overview(window: str = "1D", stocks: bool = False):
    """
    Every sector ranked by strength relative to the Nifty 50.

    `stocks=1` also returns the constituents behind each sector, sorted best to
    worst. They come from the same bulk quote the aggregate was computed from,
    so asking for them costs one extra field rather than one extra request —
    and it is always the next thing a reader wants: not "materials is up 1.4%"
    but "which names in materials are doing that".
    """
    try:
        return SS.overview(window, with_stocks=bool(stocks))
    except Exception as e:
        raise HTTPException(503, f"Sector data unavailable: {str(e)[:120]}")


@app.get("/sector/story")
def sector_story(sector: str, window: str = "1D"):
    """Why one sector moved: contributors, breadth, and the filings behind it."""
    try:
        return SS.story(sector, window)
    except Exception as e:
        raise HTTPException(503, f"Sector story unavailable: {str(e)[:120]}")


@app.get("/sectors")
def sector_momentum(force: bool = False):
    """
    Sector index returns and relative strength versus the Nifty 50.

    Standalone so the Sector view can render before any holdings are entered,
    and so the six-hour cache gets warmed by the first visitor rather than by
    the first person to run a portfolio.
    """
    try:
        return to_native(sectors.momentum(force=force))
    except Exception:
        raise HTTPException(503, "Sector indices are unavailable right now.")


# ---------------------------------------------------------------------------
# The daily digest
#
# Content first, delivery later. This renders exactly what a subscriber would
# receive so it can be read, argued with and fixed BEFORE there is a mailing
# list, a scheduler or a per-message bill attached to it. An email nobody
# would open is cheaper to discover here than after it has been sent to five
# hundred inboxes.
#
# Holdings arrive in the query string — SYMBOL:QTY:AVG, comma separated —
# because there is nowhere to save them yet. When accounts exist this endpoint
# reads the same digest from a user's stored portfolio and nothing else about
# it changes.
# ---------------------------------------------------------------------------

def _parse_holdings(spec: str) -> list:
    """"INFY:10:1400,TCS:5" -> rows. Quantity required, average price optional."""
    out = []
    for chunk in (spec or "").split(","):
        bits = [b.strip() for b in chunk.split(":") if b.strip() != ""]
        if not bits:
            continue
        row = {"symbol": bits[0]}
        if len(bits) > 1:
            try:
                row["qty"] = float(bits[1])
            except ValueError:
                continue
        else:
            row["qty"] = 1
        if len(bits) > 2:
            try:
                row["avg_price"] = float(bits[2])
            except ValueError:
                pass
        out.append(row)
    return out


# ---------------------------------------------------------------------------
# Accounts
#
# Bearer tokens rather than cookies: the site is altahascreener.in and this API
# is on onrender.com, so a session cookie would need SameSite=None, credentialed
# CORS with an explicit origin allowlist in place of the "*" above, and a CSRF
# story. A token in an Authorization header sidesteps all of it, and no other
# site's page can attach it to a request.
# ---------------------------------------------------------------------------

def _bearer(authorization: Optional[str]) -> str:
    if not authorization:
        return ""
    parts = authorization.split(None, 1)
    return parts[1].strip() if len(parts) == 2 and parts[0].lower() == "bearer" else ""


def _require_user(authorization: Optional[str]):
    import accounts
    user = accounts.user_for_session(_bearer(authorization))
    if not user:
        raise HTTPException(401, "Sign in to use this.")
    return user


def _site() -> str:
    return os.environ.get("SITE_URL", "https://altahascreener.in").rstrip("/")


@app.post("/auth/request-link")
def auth_request_link(payload: dict = Body(...)):
    """Email a one-time sign-in link.

    The response is deliberately the same whether or not the address has an
    account: this endpoint is public, and a different answer for a known
    address turns it into a way to test who has signed up.
    """
    import accounts
    import mailer

    started = accounts.start_login(str(payload.get("email") or ""))
    if started.get("error"):
        raise HTTPException(400, started["error"])

    link = f"{_site()}/signin.html?token={started['token']}"
    subject, html, text = mailer.login_email(link, minutes=accounts.LOGIN_TTL_MINUTES)
    ok, detail = mailer.send(started["email"], subject, html, text)
    if not ok:
        print(f"[auth] link email failed for {started['email']}: {detail}", flush=True)

    out = {"sent": True,
           "message": "If that address can receive mail, a sign-in link is on its way."}
    # With no provider configured the link is printed to the log and would
    # otherwise be unusable. Handing it back on an ADMIN_KEY'd request is what
    # makes the flow testable on a fresh deploy without pasting a token out of
    # Render's log stream.
    if mailer.provider() == "console" and ADMIN_KEY and \
            str(payload.get("key") or "") == ADMIN_KEY:
        out["debug_link"] = link
    return out


@app.post("/auth/verify")
def auth_verify(payload: dict = Body(...)):
    """Spend the link, receive a session token to keep."""
    import accounts
    done = accounts.complete_login(str(payload.get("token") or ""))
    if done.get("error"):
        raise HTTPException(400, done["error"])
    return {"token": done["session"], "user": {"email": done["user"]["email"],
                                               "digest_opt_in": done["user"]["digest_opt_in"]}}


@app.get("/auth/me")
def auth_me(authorization: Optional[str] = Header(None)):
    user = _require_user(authorization)
    import accounts
    return {"email": user["email"], "digest_opt_in": user["digest_opt_in"],
            "created_at": user["created_at"],
            "holdings": len(accounts.get_holdings(user["id"]))}


@app.post("/auth/logout")
def auth_logout(authorization: Optional[str] = Header(None)):
    import accounts
    return {"ok": accounts.logout(_bearer(authorization))}


# ---------------------------------------------------------------------------
# The saved portfolio
# ---------------------------------------------------------------------------

@app.get("/me/portfolio")
def my_portfolio(authorization: Optional[str] = Header(None)):
    import accounts
    user = _require_user(authorization)
    return {"holdings": accounts.get_holdings(user["id"])}


@app.put("/me/portfolio")
def save_my_portfolio(payload: dict = Body(...),
                      authorization: Optional[str] = Header(None)):
    """Replace the saved portfolio.

    Replace, not merge: the screen shows a list and a Save button, and a merge
    would make a row somebody deleted come back — the most alarming thing a
    portfolio page can do.
    """
    import accounts
    user = _require_user(authorization)
    rows = payload.get("holdings")
    if not isinstance(rows, list):
        raise HTTPException(400, "Send holdings: [{symbol, qty, avg_price}].")
    result = accounts.save_holdings(user["id"], rows)
    return {"saved": result["saved"], "rejected": result["rejected"],
            "holdings": accounts.get_holdings(user["id"])}


@app.post("/me/digest/settings")
def my_digest_settings(payload: dict = Body(...),
                       authorization: Optional[str] = Header(None)):
    import accounts
    user = _require_user(authorization)
    accounts.set_digest_opt_in(user["id"], bool(payload.get("opt_in")))
    return {"digest_opt_in": bool(payload.get("opt_in"))}


@app.get("/unsubscribe")
def unsubscribe(token: str = ""):
    """One click, no login. Anything harder and people press the spam button
    instead — which costs the sending domain rather than one subscriber."""
    import accounts
    ok = accounts.unsubscribe_by_token(token)
    body = ("<p>You will not receive any more daily emails. "
            "Your account and portfolio are untouched.</p>" if ok else
            "<p>That unsubscribe link is not valid. Sign in and turn the daily "
            "email off from your account instead.</p>")
    return HTMLResponse(
        "<!doctype html><meta charset='utf-8'><title>Altaha Screener</title>"
        "<body style=\"font:400 15px/1.6 Arial,sans-serif;color:#1a1a1a;"
        "background:#faf9f7;padding:60px 20px;text-align:center\">" + body +
        f"<p><a href='{_site()}' style='color:#6b6b6b'>Back to Altaha Screener</a></p>")


@app.post("/unsubscribe")
def unsubscribe_post(token: str = ""):
    """List-Unsubscribe-Post — the one-click header Gmail and Yahoo look for
    sends a POST, not a GET."""
    import accounts
    return {"ok": accounts.unsubscribe_by_token(token)}


# ---------------------------------------------------------------------------
# The daily send
# ---------------------------------------------------------------------------

def _build_one_digest(holdings: list, index_pct=None):
    import digest as digest_mod
    ann_window = digest_mod.FILING_WINDOW_MINUTES

    def _filings(sym):
        try:
            return ann.recent_for(sym, minutes=ann_window)
        except Exception:
            return []

    return digest_mod.build_digest(holdings, resolve=resolve,
                                   filings_for=_filings, index_pct=index_pct)


def _index_day_pct():
    try:
        _s, _t, idx = resolve("^NSEI")
        closes = idx["Close"].dropna()
        if len(closes) >= 2:
            prev = float(closes.iloc[-2])
            return round(100 * (float(closes.iloc[-1]) - prev) / prev, 2) if prev else None
    except Exception:
        pass
    return None


def _market_data_date():
    """The session the daily feed has actually settled, as YYYY-MM-DD.

    This is what the digest is keyed on rather than the calendar date, and it
    solves two problems with one lookup. On a market holiday the last session
    is unchanged, so every subscriber is already marked sent and nobody is
    mailed yesterday's closes a second time. And when the feed lags — it did
    on 2026-09-10, still serving the 9th — the email is dated by the data
    rather than by the clock."""
    try:
        _s, _t, idx = resolve("^NSEI")
        return str(idx["Close"].dropna().index[-1])[:10]
    except Exception:
        return None


@app.post("/me/digest/send-test")
def send_my_digest_now(authorization: Optional[str] = Header(None)):
    """Send today's digest to yourself. The only honest way to check what a
    subscriber actually receives — a preview in a browser is not an inbox."""
    import accounts
    import email_render
    import mailer

    user = _require_user(authorization)
    holdings = accounts.get_holdings(user["id"])
    if not holdings:
        raise HTTPException(400, "Save a portfolio first.")

    d = _build_one_digest(holdings, _index_day_pct())
    unsub = f"{_site()}/unsubscribe?token={user['unsub_token']}"
    ok, detail = mailer.send(
        user["email"], email_render.subject(d),
        email_render.render_html(d, site=_site(), unsubscribe_url=unsub),
        email_render.render_text(d, site=_site(), unsubscribe_url=unsub),
        unsubscribe_url=unsub)
    return {"sent": ok, "detail": detail, "provider": mailer.provider(),
            "subject": email_render.subject(d)}


@app.post("/jobs/daily-digest")
def run_daily_digest(x_admin_key: Optional[str] = Header(None, alias="X-Admin-Key"),
                     key: str = "", dry_run: bool = False, limit: int = 500):
    """Send every subscriber their digest. Called by a scheduler, once, after
    the close.

    Guarded by ADMIN_KEY, idempotent through accounts.send_log — a retry after
    a crash re-sends to the people who were missed and to nobody else. The
    market data is fetched ONCE for the union of everybody's symbols, which is
    what keeps this affordable on a 512 MB instance.
    """
    import accounts
    import digest as digest_mod
    import email_render
    import mailer

    expected = ADMIN_KEY
    if expected and (x_admin_key or key) != expected:
        raise HTTPException(403, "Set X-Admin-Key.")

    # Keyed on the market's last session, not on today's date — see
    # _market_data_date(). A run on a holiday finds every subscriber already
    # marked for that session and mails nobody.
    today = _market_data_date() or _dt_mod.datetime.now(digest_mod.IST).date().isoformat()
    people = accounts.digest_recipients()[:max(1, limit)]
    index_pct = _index_day_pct()

    sent, skipped, failed = 0, 0, 0
    for person in people:
        if accounts.already_sent(person["id"], "daily", today):
            skipped += 1
            continue
        holdings = accounts.get_holdings(person["id"])
        if not holdings:
            skipped += 1
            continue
        try:
            d = _build_one_digest(holdings, index_pct)
        except Exception as e:
            failed += 1
            accounts.record_send(person["id"], "daily", today, False,
                                 f"build failed: {type(e).__name__}")
            continue
        if not digest_mod.is_worth_sending(d):
            skipped += 1
            continue
        if dry_run:
            sent += 1
            continue

        unsub = f"{_site()}/unsubscribe?token={person['unsub_token']}"
        ok, detail = mailer.send(
            person["email"], email_render.subject(d),
            email_render.render_html(d, site=_site(), unsubscribe_url=unsub),
            email_render.render_text(d, site=_site(), unsubscribe_url=unsub),
            unsubscribe_url=unsub)
        accounts.record_send(person["id"], "daily", today, ok, detail)
        sent += 1 if ok else 0
        failed += 0 if ok else 1

    return {"date": today, "session": today, "recipients": len(people),
            "sent": sent, "skipped": skipped, "failed": failed,
            "dry_run": dry_run, "provider": mailer.provider()}


@app.get("/digest/preview")
def digest_preview(holdings: str = "", format: str = "html", name: str = ""):
    """The daily portfolio email, rendered. format=html | text | json."""
    import digest as digest_mod
    import email_render

    rows = _parse_holdings(holdings)
    if not rows:
        raise HTTPException(400, "Pass holdings=SYMBOL:QTY:AVG,SYMBOL:QTY "
                                 "(average price optional).")
    if len(rows) > 40:
        raise HTTPException(400, "Forty holdings is the limit for a preview.")

    # The index line, for the comparison every holder makes anyway: was that
    # my stocks, or was that the market?
    index_pct = None
    try:
        _s, _t, idx = resolve("^NSEI")
        closes = idx["Close"].dropna()
        if len(closes) >= 2:
            index_pct = round(100 * (float(closes.iloc[-1]) - float(closes.iloc[-2]))
                              / float(closes.iloc[-2]), 2)
    except Exception:
        index_pct = None

    def _filings(sym):
        try:
            return ann.recent_for(sym, minutes=digest_mod.FILING_WINDOW_MINUTES)
        except Exception:
            return []

    try:
        d = digest_mod.build_digest(rows, resolve=resolve, filings_for=_filings,
                                    index_pct=index_pct)
    except Exception as e:
        raise HTTPException(503, f"Could not build the digest: {type(e).__name__}")

    site = os.environ.get("SITE_URL", "https://altahascreener.in")
    if format == "json":
        return to_native({"subject": email_render.subject(d),
                          "worth_sending": digest_mod.is_worth_sending(d),
                          "digest": d})
    if format == "text":
        return PlainTextResponse(email_render.render_text(d, site=site))
    return HTMLResponse(email_render.render_html(d, site=site, name=name))


@app.get("/portfolio/policy")
def portfolio_policy():
    """The default rulebook, so the UI can render it without hardcoding."""
    return {"defaults": DEFAULT_POLICY}


@app.get("/results")
def results(ticker: str):
    if not ticker or len(ticker) > 20:
        raise HTTPException(400, "Provide a valid ticker symbol.")
    try:
        sym, t, hist = resolve(ticker)
    except NotFound:
        raise HTTPException(404, f"Couldn't find '{ticker.upper()}'. Check the spelling.")
    except Exception:
        raise HTTPException(503, "The data provider is busy. Try again in a minute.")
    try:
        qfin = t.quarterly_financials
        info = {}
        try:
            info = t.info or {}
        except Exception:
            pass
        name = info.get("longName") or info.get("shortName") or sym.replace(".NS","").replace(".BO","")
        out = quarterly_results(qfin, name, sym)
    except Exception:
        out = {"available": False,
               "message": "Quarterly statements could not be retrieved for this stock."}
    out["disclaimer"] = DISCLAIMER
    return to_native(out)


# Two different questions arrive on the same `range=` parameter.
#
# The first seven keys are CANDLE SIZES — how much time one bar covers. That
# is what the charting workspace asks for, and "1D" there means daily bars
# (four hundred sessions of them), not today.
#
# The last five are WINDOWS — how much history to draw, at daily resolution.
# A stock page's range control asks this question: someone pressing "6M"
# wants six months of the stock, and has no opinion about bar size. Those
# keys did not exist, so the stock page's chart asked for a window and got a
# 400 back; 6M is its default range, which is why that chart never drew at
# all. Windows are daily-mode so they need no live feed to answer.
RANGES = {
    "1m":  {"mode": "intraday", "interval": "1",  "days": 4,   "label": "1 minute"},
    "5m":  {"mode": "intraday", "interval": "5",  "days": 10,  "label": "5 minute"},
    "15m": {"mode": "intraday", "interval": "15", "days": 25,  "label": "15 minute"},
    "1H":  {"mode": "intraday", "interval": "60", "days": 90,  "label": "1 hour"},
    "4H":  {"mode": "intraday", "interval": "60", "days": 240, "label": "4 hour",
            "resample": 4},
    "1D":  {"mode": "daily",    "sessions": 400,              "label": "1 day"},
    "1W":  {"mode": "daily",    "sessions": 1200, "resample_w": True, "label": "1 week"},

    "1M":  {"mode": "daily",    "sessions": 22,   "label": "1 month"},
    "3M":  {"mode": "daily",    "sessions": 63,   "label": "3 months"},
    "6M":  {"mode": "daily",    "sessions": 126,  "label": "6 months"},
    "1Y":  {"mode": "daily",    "sessions": 252,  "label": "1 year"},
    "5Y":  {"mode": "daily",    "sessions": 1260, "label": "5 years"},
}


def _pick_range(raw: str, fallback: str = None):
    """Resolve a `range=` value to (key, cfg), or (None, None).

    Case carries meaning for exactly one pair: "1m" is one-minute candles and
    "1M" is a one-month window. The old lookup was case-insensitive and took
    the first key that matched, so a request for a month of history quietly
    returned minute bars — or a 503, since minute bars need the live feed.
    An exact match therefore wins outright.

    The case-insensitive pass is kept for everything else, because callers do
    send "1d" and "1w" and always have, but it is only accepted when exactly
    one key matches: silently guessing between two meanings is the bug above.
    """
    raw = (raw or "").strip()
    if raw in RANGES:
        return raw, RANGES[raw]
    hits = [k for k in RANGES if k.lower() == raw.lower()]
    if len(hits) == 1:
        return hits[0], RANGES[hits[0]]
    if fallback:
        return fallback, RANGES[fallback]
    return None, None


def _resample_hours(df, factor: int):
    """Combine N consecutive candles into one (for 4H from 60m)."""
    out = df.resample(f"{factor}h", origin="start", label="left", closed="left").agg(
        {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"})
    return out.dropna(subset=["Close"])


def _resample_weeks(df):
    out = df.resample("W-FRI", label="left", closed="left").agg(
        {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"})
    return out.dropna(subset=["Close"])


def _day_move(base: str):
    """Today's move: the last close against the one before it.

    Deliberately NOT the return across the range being charted. "1D" in
    RANGES names a candle size — daily bars, four hundred sessions of them —
    not the day, so /chart's `change_pct` for range=1D is a year and a half
    of return. Printed under the price as "today" it read +26.37% on a day
    CAPLIPOINT moved +0.92%.

    Computed from the daily series alone, whatever range the caller asked
    for, because the day's move is a property of the stock and not of the
    timeframe someone is browsing. The daily series is also what sets the
    price the number sits under, so the two always agree: a live tick over a
    daily close would print a percentage that doesn't reconcile with the
    rupees above it.
    """
    try:
        _, _, hist = resolve(base)
        close = hist["Close"].dropna()
        if len(close) < 2:
            return None
        last, prev = float(close.iloc[-1]), float(close.iloc[-2])
    except Exception:
        return None
    if not prev:
        return None
    return {"last": round(last, 2), "prev_close": round(prev, 2),
            "change": round(last - prev, 2),
            "change_pct": round(100 * (last - prev) / prev, 2)}


@app.get("/chart")
def chart(ticker: str, range: str = "1D"):
    """Candles for one symbol at a chosen timeframe, with overlays."""
    from engine import ema, bollinger
    key, cfg = _pick_range(range or "1D")
    if not cfg:
        raise HTTPException(400, f"range must be one of {', '.join(RANGES)}")

    base = ticker.strip().upper().replace(".NS", "").replace(".BO", "")
    df, live = None, False

    if cfg["mode"] == "intraday":
        if dhan is None or not dhan.configured():
            raise HTTPException(503, "Intraday charts need the Dhan data feed. "
                                     "Longer timeframes are available without it.")
        try:
            df = dhan.intraday_ohlcv(base, interval=cfg["interval"], days=cfg["days"])
        except Exception:
            df = None
        if df is None or len(df) < 5:
            raise HTTPException(404, f"No intraday data available for {base}. "
                                     "It may be a holiday, or the symbol may be unlisted.")
        live = True
        if cfg.get("resample") and isinstance(df.index, pd.DatetimeIndex):
            df = _resample_hours(df, cfg["resample"])
    else:
        try:
            sym, t, hist = resolve(base)
        except NotFound:
            raise HTTPException(404, f"Couldn't find '{base}'.")
        except Exception:
            raise HTTPException(503, "The data provider is busy. Try again in a minute.")
        df = hist.tail(cfg["sessions"])
        if cfg.get("resample_w") and isinstance(df.index, pd.DatetimeIndex):
            df = _resample_weeks(df)

    close = df["Close"]
    e20, e50 = ema(close, 20), ema(close, 50)
    _, bup, blo, _, _ = bollinger(close)

    rows = []
    for i in df.index:
        try:
            ts = int(pd.Timestamp(i).timestamp()) if isinstance(df.index, pd.DatetimeIndex) else None
            rows.append([
                ts,
                round(float(df.at[i, "Open"]), 2), round(float(df.at[i, "High"]), 2),
                round(float(df.at[i, "Low"]), 2), round(float(df.at[i, "Close"]), 2),
                None if pd.isna(e20.get(i)) else round(float(e20.get(i)), 2),
                None if pd.isna(e50.get(i)) else round(float(e50.get(i)), 2),
                None if pd.isna(bup.get(i)) else round(float(bup.get(i)), 2),
                None if pd.isna(blo.get(i)) else round(float(blo.get(i)), 2),
                int(df.at[i, "Volume"]) if "Volume" in df.columns and not pd.isna(df.at[i, "Volume"]) else 0,
            ])
        except Exception:
            continue

    if not rows:
        raise HTTPException(500, "Chart data could not be assembled for this symbol.")

    first, last = float(close.iloc[0]), float(close.iloc[-1])

    # Support and resistance zones.
    #
    # compute_levels() was already being called by /analyse, but /chart — the
    # endpoint the charting workspace actually uses — never returned it. The
    # levels existed and were simply never sent to the chart that wanted them.
    #
    # Always computed from DAILY history, never from the displayed timeframe.
    # A support zone is a property of the stock, not of the candle size you
    # happen to be looking at: levels derived from 5-minute bars would move
    # every time you switched timeframe, which is exactly what makes a level
    # untrustworthy.
    lv = None
    try:
        _, _, daily = resolve(base)
        if daily is not None and len(daily) >= 60:
            lv = compute_levels(daily)
    except Exception:
        lv = None

    # `change_pct` is the move ACROSS THE RANGE DRAWN — a year of return on
    # range=1D, which is four hundred daily candles. `day_change_pct` is the
    # move today. They are different questions and now have different names;
    # the headline under the price wants the second one.
    day = _day_move(base)

    return to_native({
        "ticker": base, "range": key, "label": cfg["label"],
        "live": live, "source": "dhan" if live else "daily feed",
        "candles": rows,
        "last": round(last, 2),
        "change": round(last - first, 2),
        "change_pct": round(100 * (last - first) / first, 2) if first else None,
        "prev_close": (day or {}).get("prev_close"),
        "day_change": (day or {}).get("change"),
        "day_change_pct": (day or {}).get("change_pct"),
        "as_of": str(df.index[-1])[:19] if len(df) else None,
        "levels": lv,
    })


@app.get("/quote")
def quote(ticker: str):
    """Single live quote — used by the chart's live tick mode."""
    if dhan is None or not dhan.configured():
        raise HTTPException(503, "Live quotes need the Dhan feed.")
    base = ticker.strip().upper().replace(".NS", "").replace(".BO", "")
    try:
        q = dhan.bulk_quotes([base], mode="ltp")
    except Exception:
        raise HTTPException(503, "Quote feed busy.")
    row = q.get(base)
    if not row or not row.get("ltp"):
        raise HTTPException(404, f"No live quote for {base}.")
    return to_native({"ticker": base, "ltp": row["ltp"], "ts": int(time.time())})


@app.get("/options/expiries")
def options_expiries(ticker: str):
    if dhan is None or not dhan.configured():
        raise HTTPException(503, "Options data needs the Dhan feed.")
    ex = dhan.expiry_list(ticker)
    if not ex:
        raise HTTPException(404, f"No option expiries found for {ticker.upper()}. "
                                 "Indices (NIFTY, BANKNIFTY, FINNIFTY, SENSEX) and "
                                 "F&O-listed stocks are supported — non-F&O stocks "
                                 "have no options to show.")
    return {"ticker": ticker.upper(), "expiries": ex[:12]}


@app.get("/options/chain")
def options_chain(ticker: str, expiry: str):
    if dhan is None or not dhan.configured():
        raise HTTPException(503, "Options data needs the Dhan feed.")
    raw = dhan.option_chain(ticker, expiry)
    data = (raw or {}).get("data") or {}
    oc = data.get("oc") or {}
    if not oc:
        raise HTTPException(404, "No option chain returned for that expiry. Dhan "
                                 "allows one chain request every 3 seconds — wait a "
                                 "moment and pick the expiry again.")

    spot = data.get("last_price")
    rows, ce_oi, pe_oi, ce_vol, pe_vol = [], 0, 0, 0, 0
    for strike, legs in sorted(oc.items(), key=lambda kv: float(kv[0])):
        ce = (legs or {}).get("ce") or {}
        pe = (legs or {}).get("pe") or {}
        g_ce = ce.get("greeks") or {}
        g_pe = pe.get("greeks") or {}
        ce_oi += ce.get("oi") or 0
        pe_oi += pe.get("oi") or 0
        ce_vol += ce.get("volume") or 0
        pe_vol += pe.get("volume") or 0
        rows.append({
            "strike": round(float(strike), 2),
            "ce_ltp": ce.get("last_price"), "pe_ltp": pe.get("last_price"),
            "ce_oi": ce.get("oi"), "pe_oi": pe.get("oi"),
            "ce_vol": ce.get("volume"), "pe_vol": pe.get("volume"),
            "ce_iv": ce.get("implied_volatility"), "pe_iv": pe.get("implied_volatility"),
            "ce_delta": g_ce.get("delta"), "pe_delta": g_pe.get("delta"),
        })

    # Max pain: strike where combined option-writer loss is smallest
    max_pain, best = None, None
    for r in rows:
        k = r["strike"]
        pain = sum(max(0, k - x["strike"]) * (x["ce_oi"] or 0) +
                   max(0, x["strike"] - k) * (x["pe_oi"] or 0) for x in rows)
        if best is None or pain < best:
            best, max_pain = pain, k

    if spot:
        rows = sorted(rows, key=lambda r: abs(r["strike"] - float(spot)))[:21]
        rows.sort(key=lambda r: r["strike"])

    return to_native({
        "ticker": ticker.upper(), "expiry": expiry, "spot": spot,
        "pcr_oi": round(pe_oi / ce_oi, 3) if ce_oi else None,
        "pcr_volume": round(pe_vol / ce_vol, 3) if ce_vol else None,
        "total_ce_oi": ce_oi, "total_pe_oi": pe_oi,
        "max_pain": max_pain,
        "rows": rows,
        "note": ("Put-call ratio above ~1 means more puts are open than calls, often read as "
                 "hedging or bearish positioning; below ~0.7 leans bullish. Max pain is the "
                 "strike where option writers lose least. Both are sentiment gauges, not "
                 "forecasts."),
        "disclaimer": DISCLAIMER,
    })


def _cached_v4(symbol):
    payload = _state.get("payload") or {}
    rows = payload.get("factor_universe") or payload.get("rankings") or []
    row = next((r for r in rows if r.get("symbol") == symbol), {})
    result = row.get("altaha_score_v4")
    if result:
        return result
    return {"available": False, "methodology_version": "v4",
            "message": "No v4 universe score for this stock yet; run a new universe scan."}


@app.get("/analyze")
def analyze(ticker: str, horizon: str = "position"):
    if not ticker or len(ticker) > 20:
        raise HTTPException(400, "Provide a valid ticker symbol.")

    try:
        sym, t, hist = resolve(ticker)
    except NotFound:
        raise HTTPException(
            404,
            f"Couldn't find '{ticker.upper()}'. Check the spelling — "
            "try RELIANCE, TCS, INFY, NVDA or AAPL.",
        )
    except Exception:
        raise HTTPException(503, "The data provider is busy. Try again in a minute.")

    try:
        tech = technical_score(hist)
    except Exception:
        raise HTTPException(500, "Scoring failed for this ticker's price data.")

    fin = bs = cf = None
    try:
        fin, bs, cf, info = fundamentals(sym, t)
        fund = fundamental_score(fin, bs, cf, info)
    except Exception:
        info, fund = {}, {"score": None, "f_score": None, "checks": []}

    try:
        holding = shareholding(t)
    except Exception:
        holding = {"published": False}

    try:
        lv = compute_levels(hist)
    except Exception:
        lv = None
    try:
        plan = build_plan(hist, lv, tech)
    except Exception:
        plan = None
    # Percentile vs the scanned universe — makes the score mean something.
    pct = None
    try:
        rows = (_state.get("payload") or {}).get("factor_universe") or []
        base = sym.replace(".NS", "").replace(".BO", "")
        mine = next((r for r in rows if r.get("symbol") == base), None)
        field = (horizon if horizon in PR.HORIZONS else "position") + "_score"
        if mine and mine.get(field) is not None and len(rows) >= multifactor.MIN_PEERS:
            comps = [r[field] for r in rows if r.get(field) is not None]
            pct = round(sum(1 for c in comps if c < mine[field]) / len(comps) * 100)
    except Exception:
        pct = None

    verdict = composite(tech, fund)

    base = sym.replace(".NS", "").replace(".BO", "")
    v4 = _cached_v4(base)
    try:
        legacy_scoring = PR.score(tech, fund, info, fin, bs, cf, horizon=horizon)
    except Exception:
        legacy_scoring = None
    if "position" in v4:
        scoring = multifactor.presentation(v4, horizon)
        horizons = {h: multifactor.presentation(v4, h) for h in PR.HORIZONS}
    else:
        scoring = {"score": None, "methodology_version": "v4", "label": "AWAITING SCAN",
                   "basis": v4["message"], "summary": v4["message"], "confidence": 0}
        horizons = None

    try:
        setup = A.evaluate(tech, fund)
    except Exception:
        setup = None
    try:
        plain = {"verdict": plain_verdict(tech, fund, verdict, setup),
                 **highlights(tech, fund)}
    except Exception:
        plain = None
    currency = info.get("currency") or ("INR" if sym.endswith((".NS", ".BO")) else "USD")

    return to_native({
        "ticker": sym,
        "name": info.get("longName") or info.get("shortName") or sym.replace(".NS", "").replace(".BO", ""),
        "exchange": "NSE" if sym.endswith(".NS") else ("BSE" if sym.endswith(".BO") else info.get("exchange", "US")),
        "currency": currency,
        "price": tech["price"],
        "atr_pct": tech["atr_pct"],
        "volume_series": tech["volume_series"],
        "price_series": tech.get("price_series"),
        "shareholding": holding,
        "levels": lv,
        "plan": plan,
        "percentile": pct,
        "setup": setup,
        "plain": plain,
        "verdict": verdict,
        # Canonical v4 — weighted for the business model and chosen horizon.
        # `verdict` above is the old flat 50/50 and is kept only so nothing
        # reading the old field breaks; `scoring` is the number to show.
        "scoring": scoring,
        "altaha_score_v4": v4,
        "legacy_scoring": legacy_scoring,
        "horizons": horizons,
        # What the business actually does. The score answers "is this good";
        # it does not answer "what is this", and a reader who cannot answer the
        # second question has no business acting on the first. The source line
        # is not decoration: this text is written by the data provider, not by
        # us, and a tool built on traceable numbers should say where its words
        # came from too.
        "profile": {
            "description": ((info.get("longBusinessSummary") or "").strip()[:1400] or None),
            "sector": info.get("sector"),
            "industry": info.get("industry"),
            "employees": info.get("fullTimeEmployees"),
            "website": info.get("website"),
            "market_cap": info.get("marketCap"),
            "source": "Business description as published by the data provider",
        },
        "technical": {"score": tech["score"], "checks": tech["checks"]},
        "fundamental": {"score": fund["score"], "f_score": fund["f_score"],
                        "g_score": fund.get("g_score"), "checks": fund["checks"]},
        "disclaimer": DISCLAIMER,
    })


# ---------------------------------------------------------------------------
# Live intraday scanner
# ---------------------------------------------------------------------------

def _default_watchlist(limit=200):
    """Liquid names: prefer the scanned leaderboard, else the curated core."""
    rows = (_state.get("payload") or {}).get("rankings") or []
    syms = [r["symbol"] for r in rows if r.get("symbol")][:limit]
    if len(syms) < 40:
        syms = sorted({s for s in scanner.FALLBACK.split() if s})[:limit]
    return syms


@app.post("/intraday/start")
def intraday_start(limit: int = 200, key: str = ""):
    _require_admin(key)
    if dhan is None or not dhan.configured():
        raise HTTPException(503, "Dhan is not configured — the live scanner needs it for quotes.")
    wl = _default_watchlist(limit)
    intraday.start(wl)
    return {"started": True, "watchlist_size": len(wl),
            "alerts_configured": notify.configured(),
            "note": ("Scans every 60s while the market is open. Alerts go to Telegram when "
                     "TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are set.")}


@app.post("/intraday/stop")
def intraday_stop(key: str = ""):
    _require_admin(key)
    intraday.stop()
    return {"stopped": True}


@app.get("/intraday/status")
def intraday_status():
    return intraday.status()


@app.post("/intraday/scan")
def intraday_scan_now(key: str = ""):
    _require_admin(key)
    """Force one pass — useful for testing outside market hours."""
    if not intraday._state["watch"]:
        intraday.start(_default_watchlist())
    fired = intraday.scan_once()
    return {"fired": fired, "count": len(fired), "status": intraday.status()}


@app.get("/intraday/stats")
def intraday_stats():
    return intraday.stats()


@app.get("/intraday/diag")
def intraday_diag():
    """
    Why is nothing firing? Open this in a browser during market hours and it
    answers in one screen: is the thread alive, are quotes arriving, are the
    volume profiles built, is the regime filter suppressing longs, and which
    names came closest to the threshold without clearing it. Built because
    "no alerts" has at least eight distinct causes and guessing between them
    from the outside is miserable.
    """
    return intraday.diagnose()


@app.post("/intraday/mark")
def intraday_mark(key: str = ""):
    _require_admin(key)
    return {"marked": intraday.mark_outcomes(), "stats": intraday.stats()}


@app.get("/alerts/test")
def alerts_test(key: str = ""):
    _require_admin(key)
    return notify.test()


_track_day = {"on": None}


@app.get("/cron/tick")
def cron_tick():
    """
    Keep-alive + self-heal endpoint. Point an external cron (cron-job.org,
    UptimeRobot) at this every 5 minutes: it stops Render's free tier from
    sleeping AND restarts the scanner thread if a restart killed it.
    """
    try:
        ann.poll_if_stale()
    except Exception:
        pass

    # Attach forward returns to anything whose horizon has now elapsed. This
    # has to be unattended: a label can only be written days or months after
    # the snapshot it belongs to, so a job that needs a human to remember it
    # is a job that silently never runs.
    labelled = None
    if fwd_labels is not None:
        try:
            labelled = fwd_labels.run().get("written")
        except Exception:
            labelled = None

    revived = False
    if not intraday._state["running"]:
        _autostart_intraday()
        revived = intraday._state["running"]
    fired, marked = [], 0
    if intraday.market_open() and intraday._state["running"]:
        try:
            fired = intraday.scan_once()
        except Exception:
            pass
    else:
        # Outcome marking previously ran ONLY inside the scanner loop. If the
        # process restarted after the close, or the scanner was stopped, that
        # day's alerts stayed permanently unmarked and never reached the hit
        # rate. The cron tick now closes that gap; mark_outcomes is idempotent.
        try:
            if intraday.now_ist().hour >= 16:
                marked = intraday.mark_outcomes()
        except Exception:
            pass
        # Mark tracked ideas once after the close. Capped per tick so a single
        # cron call can never burn the Dhan daily quota.
        try:
            if intraday.now_ist().hour >= 16 and _track_day["on"] != intraday.now_ist().date():
                tracker.update_all(limit=150)
                _track_day["on"] = intraday.now_ist().date()
        except Exception:
            pass
    return {"awake": True, "scanner_running": intraday._state["running"],
            "revived": revived, "market_open": intraday.market_open(),
            "fired_now": len(fired), "outcomes_marked": marked,
            "forward_returns_labelled": labelled}


_autostart_intraday()


# ---------------------------------------------------------------------------
# Live price stream
# ---------------------------------------------------------------------------
# charts.js already opens EventSource("/stream/quotes?tickers=SYM") and falls
# back to polling when it 404s. This is the endpoint it was always looking for.
#
# The browser never receives a Dhan token — it talks only to this server, and
# this server holds one shared WebSocket to Dhan on behalf of every visitor.

@app.get("/stream/quotes")
def stream_quotes(tickers: str = ""):
    """Server-Sent Events price stream. One shared Dhan connection behind it."""
    if livefeed is None:
        raise HTTPException(503, "Live feed module not available")
    return StreamingResponse(
        livefeed.sse_quotes(tickers),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",   # stops proxies buffering the stream
        },
    )


@app.get("/stream/status")
def stream_status():
    """Diagnostics: is the feed on the WebSocket, on REST, or idle?"""
    if livefeed is None:
        return {"mode": "unavailable", "detail": "livefeed module not loaded"}
    return livefeed.FEED.status()
