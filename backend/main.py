"""
Altaha Screener — API  (v2.1 — on-demand scanning)
Start command on Render:  uvicorn main:app --host 0.0.0.0 --port $PORT
"""

import json
import os
import threading
import time

from fastapi import FastAPI, HTTPException, Body, Response, Header
from typing import Optional
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
import numpy as np
import pandas as pd

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
    import xbrl as xbrl_source
except Exception:
    xbrl_source = None
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

app = FastAPI(title="Altaha Screener API", version="2.1")

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

DISCLAIMER = (
    "Altaha Screener is an educational analysis tool. Scores are objective "
    "computations from public data using disclosed formulas. Nothing here is "
    "investment advice or a recommendation to buy or sell any security. "
    "Rankings reflect scores on the stated date and change as prices and "
    "filings change. Markets carry risk of loss. Do your own research or "
    "consult a SEBI-registered adviser."
)

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
    if isinstance(obj, dict):
        return {k: to_native(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_native(v) for v in obj]
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        v = float(obj)
        return None if (v != v or v in (float("inf"), float("-inf"))) else v
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

    now = _dt.datetime.utcnow() + _dt.timedelta(hours=5, minutes=30)
    mins = now.hour * 60 + now.minute
    weekday = now.weekday() < 5
    if not weekday:
        status = "closed"
    elif 555 <= mins < 915:          # 09:15 - 15:30
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


@app.get("/health")
def health():
    try:
        sym, t, h = resolve("AAPL")
        return {"data_layer": "ok", "rows": len(h), "last_close": round(float(h["Close"].iloc[-1]), 2)}
    except Exception as e:
        return {"data_layer": "unreachable", "detail": str(e)[:200]}


@app.post("/scan/start")
@app.get("/scan/start")
def scan_start(force: bool = False, key: str = ""):
    """Kick off a background scan. Returns immediately."""
    _require_admin(key)
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
        out["scanned_at"] = _state["payload"].get("scanned_at")
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
        return {"available": False, "status": _state["status"],
                "message": "No scan yet — generate the ranking first.",
                "market_context": _safe_context(horizon)}
    try:
        return {**ideas_engine.select(p, horizon=horizon,
                                      limit=max(1, min(limit, 25)),
                                      min_tier=min_tier,
                                      include_thin=bool(include_thin),
                                      min_conviction=min_conviction),
                "disclaimer": DISCLAIMER}
    except ValueError as e:
        raise HTTPException(400, str(e))


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
    return {"available": True, **ctx}


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
    for r in sel["rows"]:
        # Flatten the two nested objects the CSV wants a column for; a
        # DictWriter would otherwise print the whole dict into one cell.
        w.writerow({**r,
                    "sector_state": (r.get("sector_outlook") or {}).get("state"),
                    "catalyst_category": (r.get("catalyst") or {}).get("category")})
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
    raw = (range or "1D").strip()
    key = next((k for k in RANGES if k.lower() == raw.lower()), None)
    cfg = RANGES.get(key) if key else None
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

SITE_URL = os.environ.get("SITE_URL", "https://taha-project-one.vercel.app").rstrip("/")
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
    key = next((k for k in RANGES if k.lower() == (raw or "1D").strip().lower()), None)
    cfg = RANGES.get(key) if key else None
    if not cfg:
        key, cfg = "1D", RANGES["1D"]

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
            quarters = (xbrl_source.summary(base) or {}).get("quarters") or []
        except Exception:
            quarters = []

    price = float(hist["Close"].dropna().iloc[-1]) if hist is not None and len(hist) else None
    values = factor_lib.compute(hist, quarters=quarters, price=price)
    return to_native({
        "symbol": base, "price": price, "horizon": horizon,
        "factors": values,
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
    out = multifactor.rank(
        [{"symbol": r.get("symbol"), "name": r.get("name"),
          "sector": r.get("sector"), "price": r.get("price"),
          "composite": r.get("composite"),
          "factors": r.get("factors") or {}} for r in rows],
        horizon=h)
    if not out.get("available"):
        return out
    ranked = [r for r in out["rows"] if r.get("factor_score") is not None]
    ranked.sort(key=lambda r: -r["factor_score"])
    out["rows"] = ranked[:max(1, min(int(limit), 200))]
    out["scanned_at"] = (p or {}).get("scanned_at")
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

    return to_native(attention_mod.assess(base, df=hist, filings=filings,
                                          stories=stories, liquidity_tier=tier))


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


def _analyse_holding(item):
    sym_in = str(item.get("symbol", "")).strip().upper()
    qty = float(item.get("qty") or 0)
    buy = item.get("buy_price")
    buy = float(buy) if buy not in (None, "",) else None
    if not sym_in or qty <= 0:
        return {"symbol": sym_in or "?", "error": "missing symbol or quantity",
                "value": 0.0, "cost": None}
    try:
        sym, t, hist = resolve(sym_in)
    except NotFound:
        return {"symbol": sym_in, "error": "symbol not found", "value": 0.0, "cost": None}
    except Exception:
        return {"symbol": sym_in, "error": "data provider busy", "value": 0.0, "cost": None}
    try:
        tech = technical_score(hist)
    except Exception:
        return {"symbol": sym_in, "error": "scoring failed", "value": 0.0, "cost": None}
    try:
        fin, bs, cf, info = fundamentals(sym, t)
        fund = fundamental_score(fin, bs, cf, info)
    except Exception:
        info, fund = {}, {"score": None, "f_score": None, "g_score": None, "checks": [], "extras": {}}
    v = composite(tech, fund)
    try:
        setup = A.evaluate(tech, fund)
    except Exception:
        setup = None
    price = float(tech["price"])
    clean_sym = sym.replace(".NS", "").replace(".BO", "")
    sector, sector_source = sectors.resolve_sector(clean_sym, info)
    return {
        "symbol": clean_sym,
        "name": info.get("longName") or info.get("shortName") or sym_in,
        "sector": sector, "sector_source": sector_source,
        "qty": qty, "buy_price": buy, "price": price,
        "value": round(qty * price, 2),
        "cost": round(qty * buy, 2) if buy is not None else None,
        "pnl_pct": round(100 * (price - buy) / buy, 2) if buy else None,
        "composite": v["score"], "tone": v["tone"],
        "technical": tech["score"], "fundamental": fund["score"],
        "setup": (setup or {}).get("name"), "setup_fit": (setup or {}).get("fit"),
        "horizon": (setup or {}).get("horizon"),
        "error": None,
    }


# ---------------------------------------------------------------------------
# Portfolio review — job-based
# ---------------------------------------------------------------------------
#
# A fifty-holding book takes long enough that a synchronous request is at the
# mercy of whatever proxy sits in front of the app. The work therefore runs on
# a background thread and the client polls: progress arrives immediately,
# holdings appear as they finish, and no single request stays open long enough
# to be killed. Jobs are in-memory and expire — nothing about a user's
# holdings is ever written to disk.

_pf_jobs = {}
_pf_lock = threading.Lock()
PF_JOB_TTL = 900             # fifteen minutes is well past any real session


def _pf_sweep():
    """Drop finished jobs past their TTL. Called on every job creation."""
    now = time.time()
    with _pf_lock:
        for jid in [k for k, v in _pf_jobs.items()
                    if now - v.get("touched", now) > PF_JOB_TTL]:
            _pf_jobs.pop(jid, None)


def _pf_run(job_id: str, holdings: list, policy: dict):
    """Score every holding, then assemble the report. Errors stay per-row."""
    rows = [None] * len(holdings)

    def record(i, value):
        rows[i] = value
        with _pf_lock:
            job = _pf_jobs.get(job_id)
            if job is not None:
                job["done"] = sum(1 for r in rows if r is not None)
                job["touched"] = time.time()

    try:
        with ThreadPoolExecutor(max_workers=PF_WORKERS) as pool:
            futures = {pool.submit(_analyse_holding, h): i
                       for i, h in enumerate(holdings)}
            for fut in as_completed(futures):
                i = futures[fut]
                try:
                    record(i, fut.result())
                except Exception:
                    record(i, {"symbol": str(holdings[i].get("symbol", "?")),
                               "error": "analysis failed", "value": 0.0, "cost": None})

        # Sector momentum is cached for six hours, so this is usually free.
        # A failure here must not cost the user the rest of the report.
        try:
            sector_data = sectors.momentum()
        except Exception:
            sector_data = {"available": False,
                           "message": "Sector indices could not be retrieved."}

        # The filing feed is already in memory from the Filings module — this
        # is a join, not a fetch. A holding with a high-importance filing in
        # the window gets that surfaced beside its score, which is exactly
        # the context a score alone cannot carry.
        news_map = {}
        try:
            for r in rows:
                if not r or r.get("error") or not r.get("symbol"):
                    continue
                hits = ann.feed(limit=3, min_importance="medium",
                                symbol=r["symbol"]).get("rows") or []
                if hits:
                    top = hits[0]
                    news_map[r["symbol"]] = {
                        "category": top.get("category"),
                        "importance": top.get("importance"),
                        "headline": top.get("headline"),
                        "pdf": top.get("pdf"),
                        "when": top.get("when") or top.get("date"),
                        "count": len(hits),
                    }
        except Exception:
            news_map = {}

        report = build_report(rows, _state.get("payload"), policy,
                              sector_data, news_map)
        report["disclaimer"] = DISCLAIMER

        with _pf_lock:
            job = _pf_jobs.get(job_id)
            if job is not None:
                job.update(status="done", report=to_native(report),
                           finished_at=time.time(), touched=time.time())
    except Exception as exc:                              # pragma: no cover
        with _pf_lock:
            job = _pf_jobs.get(job_id)
            if job is not None:
                job.update(status="error", error=str(exc)[:200],
                           touched=time.time())


@app.post("/portfolio/start")
def portfolio_start(payload: dict = Body(...)):
    """Queue a portfolio analysis. Returns a job id to poll."""
    holdings = payload.get("holdings") or []
    if not isinstance(holdings, list) or not holdings:
        raise HTTPException(400, "Provide a holdings list.")
    if len(holdings) > MAX_HOLDINGS:
        raise HTTPException(400, f"Maximum {MAX_HOLDINGS} holdings per analysis — "
                                 "split larger portfolios into batches.")

    policy = clean_policy(payload.get("policy"))
    _pf_sweep()

    job_id = uuid.uuid4().hex[:16]
    with _pf_lock:
        _pf_jobs[job_id] = {"status": "running", "done": 0, "total": len(holdings),
                            "report": None, "error": None,
                            "started_at": time.time(), "touched": time.time()}

    threading.Thread(target=_pf_run, args=(job_id, holdings, policy),
                     daemon=True).start()

    return {"job_id": job_id, "total": len(holdings), "policy": policy}


@app.get("/portfolio/status")
def portfolio_status(job: str):
    """Progress, then the finished report. Poll until status leaves 'running'."""
    with _pf_lock:
        state = _pf_jobs.get(job)
        if state is None:
            raise HTTPException(404, "That analysis has expired. Run it again.")
        state["touched"] = time.time()
        snapshot = dict(state)

    out = {"status": snapshot["status"], "done": snapshot["done"],
           "total": snapshot["total"], "error": snapshot["error"]}
    if snapshot["status"] == "done":
        out["report"] = snapshot["report"]
    return out


@app.post("/portfolio")
def portfolio(payload: dict = Body(...)):
    """
    Synchronous analysis, kept for anything already calling this path.

    New clients should use /portfolio/start — this route blocks for as long as
    the book takes and is capped well below MAX_HOLDINGS to keep that bounded.
    """
    holdings = payload.get("holdings") or []
    if not isinstance(holdings, list) or not holdings:
        raise HTTPException(400, "Provide a holdings list.")
    if len(holdings) > 20:
        raise HTTPException(400, "This route handles up to 20 holdings. Use "
                                 "/portfolio/start for larger books.")

    policy = clean_policy(payload.get("policy"))
    rows = [None] * len(holdings)
    with ThreadPoolExecutor(max_workers=PF_WORKERS) as pool:
        futures = {pool.submit(_analyse_holding, h): i for i, h in enumerate(holdings)}
        for fut in as_completed(futures):
            i = futures[fut]
            try:
                rows[i] = fut.result()
            except Exception:
                rows[i] = {"symbol": str(holdings[i].get("symbol", "?")),
                           "error": "analysis failed", "value": 0.0, "cost": None}
    try:
        sector_data = sectors.momentum()
    except Exception:
        sector_data = {"available": False}
    report = build_report(rows, _state.get("payload"), policy, sector_data)
    report["disclaimer"] = DISCLAIMER
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
def sector_overview(window: str = "1D"):
    """Every sector ranked by strength relative to the Nifty 50."""
    try:
        return SS.overview(window)
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


RANGES = {
    "1m":  {"mode": "intraday", "interval": "1",  "days": 4,   "label": "1 minute"},
    "5m":  {"mode": "intraday", "interval": "5",  "days": 10,  "label": "5 minute"},
    "15m": {"mode": "intraday", "interval": "15", "days": 25,  "label": "15 minute"},
    "1H":  {"mode": "intraday", "interval": "60", "days": 90,  "label": "1 hour"},
    "4H":  {"mode": "intraday", "interval": "60", "days": 240, "label": "4 hour",
            "resample": 4},
    "1D":  {"mode": "daily",    "sessions": 400,              "label": "1 day"},
    "1W":  {"mode": "daily",    "sessions": 1200, "resample_w": True, "label": "1 week"},
}


def _resample_hours(df, factor: int):
    """Combine N consecutive candles into one (for 4H from 60m)."""
    out = df.resample(f"{factor}h", origin="start", label="left", closed="left").agg(
        {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"})
    return out.dropna(subset=["Close"])


def _resample_weeks(df):
    out = df.resample("W-FRI", label="left", closed="left").agg(
        {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"})
    return out.dropna(subset=["Close"])


@app.get("/chart")
def chart(ticker: str, range: str = "1D"):
    """Candles for one symbol at a chosen timeframe, with overlays."""
    from engine import ema, bollinger
    raw = (range or "1D").strip()
    key = next((k for k in RANGES if k.lower() == raw.lower()), None)
    cfg = RANGES.get(key) if key else None
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

    return to_native({
        "ticker": base, "range": key, "label": cfg["label"],
        "live": live, "source": "dhan" if live else "daily feed",
        "candles": rows,
        "last": round(last, 2),
        "change": round(last - first, 2),
        "change_pct": round(100 * (last - first) / first, 2) if first else None,
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
        rows = (_state.get("payload") or {}).get("rankings") or []
        base = sym.replace(".NS", "").replace(".BO", "")
        mine = next((r for r in rows if r.get("symbol") == base), None)
        if mine and mine.get("composite") is not None and len(rows) >= 50:
            comps = [r["composite"] for r in rows if r.get("composite") is not None]
            pct = round(sum(1 for c in comps if c < mine["composite"]) / len(comps) * 100)
    except Exception:
        pct = None

    verdict = composite(tech, fund)

    # Scoring v3. The headline number is now weighted for the kind of business
    # this is and for the horizon the reader picked, instead of a flat 50/50
    # that treated a bank and a steel mill as the same object. composite() is
    # kept and still returned as `verdict` so nothing that reads the old field
    # breaks, but `profile` is what the page should show.
    try:
        scoring = PR.score(tech, fund, info, fin, bs, cf, horizon=horizon)
    except Exception:
        scoring = None
    try:
        horizons = PR.compare_horizons(tech, fund, info, fin, bs, cf)
    except Exception:
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
        # Scoring v3 — weighted for the business model and the chosen horizon.
        # `verdict` above is the old flat 50/50 and is kept only so nothing
        # reading the old field breaks; `scoring` is the number to show.
        "scoring": scoring,
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
