"""
Altaha Score v4 for a company the universe scan did not analyse.

The scan analyses a cohort — about two hundred names: the strongest technical
candidates plus a stratified random control group — and v4 ranks each of them
against the others. Every company outside that cohort used to get no score at
all. That covered roughly nine names in ten on the exchange, including the
ones people search for most: Reliance, TCS and HDFC Bank all read "NOT
SCORED" on a site whose first sentence promises a score for any stock.

A v4 score is a position inside a peer distribution, so a company outside the
cohort can be given one honestly by asking exactly one question: *where would
it have ranked had the scan included it?* That is what this module answers,
and it answers it with the scan's own machinery rather than a lookalike:

  * the SAME ranker. `multifactor.rank` is called on the cohort plus this one
    row. There is no second implementation of percentiles, pools, weights or
    confidence to drift out of step with the first.
  * the SAME inputs. The row is built the way `scan.deep_score` builds one:
    `factors.compute` over the price history and the stored XBRL quarters,
    `factors.data_quality` over the same quarters, and the four classification
    fields `multifactor._model` reads.
  * the SAME date. Prices and filings are cut off at the cohort's own as-of
    date, so a company is never measured on today's prices against peers
    measured on the scan's. A score from a scan three days old is a score as
    of three days ago, for members and non-members alike.

And it keeps the cohort clean:

  * the cohort is never modified. `rank` works on copies; the scored row is
    not added to the scan payload, the point-in-time store or the ideas list.
    Research built on the scan's sampling design (ranked vs control) cannot
    be contaminated by whoever happened to open which stock page.
  * members keep their cached score. A company in the cohort is never
    re-ranked here, so the two paths can never disagree about it.

Indian listings only. The cohort is NSE companies; ranking a US company's
valuation and growth against them would be a number without a peer group.

The first request for a company does real work (a filings read and one rank
of ~200 rows, well under a second when the filings are stored), so it runs on
a small pool with a short wait. A request that outlasts the wait gets an
honest "being scored" answer while the work finishes and lands in the cache
for the next reader.
"""
import os
import threading
from collections import Counter, OrderedDict
from concurrent.futures import ThreadPoolExecutor, TimeoutError as _FutureTimeout

import factors as F
import multifactor as M

INDIAN_SUFFIXES = (".NS", ".BO")

# The scan's own floor (scan.MIN_ROWS, and the literal in deep_score): a
# company with less price history than this is not scored there, so it is not
# scored here either. Ranking it anyway would print a 50 with no confidence
# behind it, which reads as a middling company rather than an unknown one.
MIN_ROWS = 120

# Momentum skips the last month of a twelve-month window: 252 + a margin.
# `factors.momentum_12_1` refuses anything shorter, and a history too short to
# measure it would quietly score a company without its momentum pillar.
MIN_HISTORY_ROWS = 260

# One entry is one v4 dict with its factor ledger, a few KB. 256 of them is a
# megabyte or two on an instance that has half a gigabyte and uses most of it.
CACHE_MAX = int(os.environ.get("SCORE_ON_REQUEST_CACHE", "256") or 256)

# How long a page request waits for a first-time score before answering
# without one. Long enough for a stored-filings company (the usual case),
# short enough that a company whose filings must be read from the exchange
# never holds the whole stock page hostage.
WAIT_SECONDS = float(os.environ.get("SCORE_ON_REQUEST_WAIT", "12") or 12)


def _base(symbol):
    return str(symbol or "").upper().replace(".NS", "").replace(".BO", "")


def is_indian(symbol):
    s = str(symbol or "").upper()
    return s.endswith(INDIAN_SUFFIXES) and not s.startswith("^")


def cohort_of(payload):
    """
    (rows, key, as_of) for the scan's analysed cohort, or None.

    None when there is no usable cohort: no scan yet, a legacy payload whose
    rows carry no factor block, or fewer rows than the ranker's peer minimum.
    `key` identifies the cohort, so a new scan invalidates every cached score
    without anyone having to remember to clear anything.
    """
    rows = [r for r in ((payload or {}).get("factor_universe") or [])
            if isinstance(r, dict) and r.get("symbol") and isinstance(r.get("factors"), dict)]
    if len(rows) < M.MIN_PEERS:
        return None
    dates = Counter((r.get("data_quality") or {}).get("as_of") for r in rows)
    dates.pop(None, None)
    if not dates:
        return None
    # One scan, one date. The most common one is the scan's; a checkpoint
    # that straddled midnight is the only way to see two.
    as_of = dates.most_common(1)[0][0]
    key = ((payload or {}).get("scanned_at"), len(rows), as_of)
    return rows, key, as_of


def build_row(symbol, hist, quarters, info, as_of):
    """
    The row `scan.deep_score` banks for a company, from the same inputs,
    as of the cohort's date. Only the fields `multifactor.rank` reads.
    """
    info = info or {}
    return {
        "symbol": _base(symbol),
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "market_cap": info.get("marketCap"),
        "trailing_eps": info.get("trailingEps"),
        "factors": F.compute(hist, quarters=quarters or [], as_of=as_of),
        "data_quality": F.data_quality(quarters or [], as_of=as_of),
    }


def score_against(cohort_rows, row):
    """
    v4 for `row`, ranked alongside the cohort exactly as `rank` would have
    placed it had the scan included it. None when the ranker declines.
    """
    if any(r.get("symbol") == row["symbol"] for r in cohort_rows):
        raise ValueError("A cohort member keeps its scan score; it is never re-ranked on request")
    out = M.rank(list(cohort_rows) + [row], "position")
    if not out.get("available"):
        return None
    mine = next((r for r in out["rows"] if r.get("symbol") == row["symbol"]), None)
    return None if mine is None else mine.get("altaha_score_v4")


def unavailable(message, **extra):
    return {"available": False, "methodology_version": "v4", "message": message, **extra}


def _cohort_note(key, n, on_request):
    scanned = key[0] or "the last scan"
    if on_request:
        return (f"Not in the scan's analysed cohort, so ranked on request against its {n} "
                f"companies, using prices and filings as of {key[2]} — the same date its "
                f"peers were measured on (scan of {scanned}).")
    return f"Analysed in the universe scan of {scanned}, ranked against its {n} companies."


def with_cohort(v4, key, n, on_request):
    """A copy of `v4` carrying where its peer group came from."""
    return {**v4, "cohort": {"basis": "on_request" if on_request else "scan",
                             "scanned_at": key[0], "as_of": key[2], "peers": n,
                             "note": _cohort_note(key, n, on_request)}}


class OnRequestScorer:
    """Bounded cache + single-flight + short wait around `score_against`."""

    def __init__(self, wait=WAIT_SECONDS, cache_max=CACHE_MAX, workers=2):
        self.wait = wait
        self.cache_max = max(1, int(cache_max))
        self.workers = workers
        self._lock = threading.Lock()
        self._cache = OrderedDict()      # (symbol, cohort key) -> v4
        self._inflight = {}              # same key -> Future
        self._pool = None

    def _executor(self):
        with self._lock:
            if self._pool is None:
                self._pool = ThreadPoolExecutor(max_workers=self.workers,
                                                thread_name_prefix="altaha-v4")
            return self._pool

    def cached(self, symbol, key):
        with self._lock:
            v = self._cache.get((_base(symbol), key))
            if v is not None:
                self._cache.move_to_end((_base(symbol), key))
            return v

    def _store(self, ck, v4):
        with self._lock:
            self._cache[ck] = v4
            self._cache.move_to_end(ck)
            while len(self._cache) > self.cache_max:
                self._cache.popitem(last=False)

    def score(self, symbol, payload, fetch, wait=None):
        """
        v4 for an Indian listing outside the cohort, or an `unavailable` dict
        saying why not. `fetch()` returns (hist, quarters, info) and is only
        called on a cache miss; it may block on the network.
        """
        if not is_indian(symbol):
            return unavailable(
                "Altaha Score v4 ranks Indian companies against their NSE peers. "
                "US listings have no peer cohort yet, so this page shows the "
                "technical and fundamental checks without a headline score.",
                reason="no_cohort_for_market")
        cohort = cohort_of(payload)
        if cohort is None:
            return unavailable("No v4 universe score for this stock yet; run a new universe scan.",
                               reason="no_cohort")
        rows, key, as_of = cohort
        base = _base(symbol)
        ck = (base, key)
        hit = self.cached(base, key)
        if hit is not None:
            return hit

        def work():
            try:
                hist, quarters, info = fetch()
                closes = None if hist is None or "Close" not in getattr(hist, "columns", []) \
                    else hist["Close"].dropna()
                if closes is None or len(closes) < MIN_ROWS:
                    return None
                v4 = score_against(rows, build_row(base, hist, quarters, info, as_of))
                if v4 is not None:
                    v4 = with_cohort(v4, key, len(rows), on_request=True)
                    self._store(ck, v4)
                return v4
            finally:
                with self._lock:
                    self._inflight.pop(ck, None)

        pool = self._executor()
        # Submit and register under one lock: `work` unregisters itself under
        # the same lock, so it cannot finish and unregister before it has been
        # registered — which would leave a finished future behind that every
        # later request for this company would be handed instead of a retry.
        with self._lock:
            fut = self._inflight.get(ck)
            if fut is None:
                fut = pool.submit(work)
                self._inflight[ck] = fut
        try:
            v4 = fut.result(timeout=self.wait if wait is None else wait)
        except _FutureTimeout:
            return unavailable(
                f"Scoring {base} against the scan's {len(rows)} companies — this "
                "takes a few seconds the first time. Refresh in a moment.",
                reason="pending", pending=True)
        except Exception:
            return unavailable(
                "This company's prices or filings could not be read just now, so it "
                "could not be ranked against the scan. Try again in a minute.",
                reason="fetch_failed")
        if v4 is None:
            return unavailable(
                "Not enough published data to rank this company against the scan's peers.",
                reason="insufficient_data")
        return v4
