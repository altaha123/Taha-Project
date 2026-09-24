"""
lens_job.py — the nightly Lenses compute

One pass over every company in the fundamentals tables:

  1  read the lens config and work out which metrics the live lenses need;
  2  for each company, reduce its statements to those metrics (lens_metrics);
  3  compute the peer-relative metrics over the whole set;
  4  apply every live lens to every company (lens_engine);
  5  write the results as one run, which is what the endpoints read.

A coming-soon lens is not computed: it has no results, so no page can show a
stock under it.

Driven by .github/workflows/lenses.yml after the fundamentals crawl, through
POST /admin/lenses/compute. It runs inside the API process because the
tables live on the API's disk, and it is bounded: a few seconds of SQLite and
arithmetic per thousand companies, no network.
"""

import time

import lens_engine
import lens_metrics
import lens_store

try:
    import fundamentals_store
except Exception:        # pragma: no cover - the store is part of the app
    fundamentals_store = None


def universe():
    try:
        import fundamentals_crawl
        return fundamentals_crawl.universe()
    except Exception:
        return []


def compute(cfg=None, today=None, prices=None, universe_size=None):
    started = time.time()
    cfg = cfg or lens_engine.load_config()
    live = [l for l in cfg["lenses"] if l.get("status", "live") == "live"]
    required = lens_engine.required_metrics(cfg)
    unknown = sorted({f for f, _lb in required} - lens_metrics.fields_known())
    if unknown:
        raise ValueError("lenses.json names fields no metric computes: %s" % ", ".join(unknown))
    if fundamentals_store is None:
        raise RuntimeError("The fundamentals tables are not available")

    profiles = lens_store.companies()
    holdings = lens_store.shareholding()
    prices = lens_metrics.latest_prices() if prices is None else prices
    if universe_size is None:
        universe_size = len(universe()) or len(profiles)
    default_cov = (cfg.get("defaults") or {}).get("min_coverage",
                                                  lens_engine.DEFAULT_MIN_COVERAGE)

    run_id = lens_store.start_run(cfg.get("version"), universe_size)
    try:
        own, summaries = {}, []
        conn = fundamentals_store._connect()
        for sym, inc, bal, cfs in lens_metrics.iter_companies(conn):
            c = lens_metrics.Company(sym, inc, bal, cfs, today=today)
            ctx = {"company": profiles.get(sym), "shareholding": holdings.get(sym),
                   "prices": prices}
            metrics, summary = lens_metrics.company_metrics(c, required, ctx)
            own[sym] = metrics
            summaries.append(summary)

        peers = lens_metrics.peer_metrics(summaries, required, profiles, universe_size)

        rows, written = [], 0
        for s in summaries:
            metrics = dict(own[s["symbol"]])
            metrics.update(peers.get(s["symbol"]) or {})
            for lens in live:
                res = lens_engine.evaluate_lens(lens, metrics, default_cov)
                res.update({"lens_id": lens["id"], "symbol": s["symbol"],
                            "company": s["company"], "industry": s["industry"]})
                rows.append(res)
            if len(rows) >= 2000:
                written += lens_store.write_results(run_id, rows)
                rows = []
        written += lens_store.write_results(run_id, rows)
        lens_store.finish_run(run_id, companies=len(summaries), status="ok",
                              note="%d results in %.1fs" % (written, time.time() - started))
    except Exception as e:
        lens_store.finish_run(run_id, status="error", note="%s: %s" % (type(e).__name__, e))
        raise
    return {"run_id": run_id, "companies": len(summaries), "results": written,
            "lenses": [l["id"] for l in live], "seconds": round(time.time() - started, 1),
            "counts": lens_store.status_counts(run_id)}
