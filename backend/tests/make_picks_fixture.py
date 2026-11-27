"""
Make frontend/tests/fixtures/picks.json: what /ideas answers for each list
the Stock picks page draws, made by the real engine.

Every list is made the way the site makes it, by leaders.rank and
ideas.select, run on the study's price panel for its last session. The
engine is told what the scan tells it: each stock's chart, its NSE industry,
the results that had reached the exchange by that day's close, and each
company's fundamentals snapshot, which the three lists by holding time are
ranked on.

The snapshot is the one research/fundamental_ideas_lab.py replays the engine
with (load_pit, snapshot_at): for each liquid company, fund_snapshot.build
(the code the scan's own fundamental_snapshot() runs) on its rows of the
study's copies of the four fundamentals tables that had reached the exchange
by that day's close, priced at that close. So the breakdown, the facts and the
figures each pick carries are worked out from what the company had filed by
then. The facts only the live site has (pledges, the promoter's and
institutions' changes in holding, delivery surges, orders, the industry's
Money Flow quadrant) have no history to read and stay unknown, as in the lab:
no figure is made up about a named company. A test that needs one sets it on
a row itself.

Entries written:

  month, results, long    the three lists by holding time
  results_empty           the After results list on the last session between
                          two results seasons, where it says when the next
                          season starts
  short, breakout, technical, quick, flow, emerging
                          the setup lists, the same day as the three
  short_empty             the short list as it reads on a day nothing passes
  legacy                  kept as it is: a scan from before the tested lists

The lists the three replaced (week, momentum) are taken out: the page has no
tab for them, and the server answers their names with month and long.

    IDEAS_DATA=/path/to/study/data python backend/tests/make_picks_fixture.py

needs what research/ideas_study.py --fetch and --build leave behind, and the
four tables beside them; it says so and stops when they are not there.

    python backend/tests/make_picks_fixture.py --marks

needs none of it. It refreshes the two things the page shows that come from
leaders.py and the study file alone: the mark above each pick's price
(plan.aim) and what the study found on selling there (target_test). Both are
written by the real functions, onto the lists as the file already has them.
"""

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "research"))
OUT = ROOT / "frontend" / "tests" / "fixtures" / "picks.json"
# NSE's industry list ships with the backend. The study's data folder is used
# when it has its own copy.
SECTORS_FALLBACK = ROOT / "backend" / "nse_industries.csv"
# Lists that no longer exist, taken out of the file when it is remade.
RETIRED = ("week", "momentum")

ROW_KEYS = ("symbol", "name", "price", "sector", "list", "setup", "setup_key", "horizon", "pick_rank",
            "young", "conviction", "conviction_band", "why", "pattern", "catalysts", "evidence", "plan", "results", "order",
            "technicals", "chart", "news", "adverse_filing", "avg_turnover_cr", "liquidity_tier",
            "tracked", "composite", "technical", "fundamental", "f_score", "setup_fit", "call")
TOP_KEYS = ("available", "degraded", "method_key", "list", "horizon", "label", "idea", "hold_text",
            "exit_pct", "tested", "target_test", "study", "scanned_at", "partial", "scored", "universe_source",
            "universe", "regime", "market_test", "chart_note", "empty_text", "event", "sector_mix",
            "sector_cap", "selection_notes", "excluded_adverse", "count", "considered", "method",
            "recipe_current", "study_current", "weights", "primary", "kind", "sell_rule", "sector_flow",
            "flow_sectors", "watch", "lists")


def marks(fix):
    """
    plan.aim on every pick and target_test on every list, from the functions
    the endpoint uses. A list sent no tested record (ranked with an older
    recipe, or not yet measured on its own) is sent no target test either.
    """
    import leaders
    n = 0
    for name, entry in fix.items():
        if not isinstance(entry, dict) or entry.get("method_key") != "tested_lists":
            continue
        key = entry.get("list") or entry.get("horizon")
        entry["target_test"] = (leaders.target_tested(key)
                                if entry.get("tested") and entry.get("recipe_current") is not False else None)
        for r in entry.get("rows") or []:
            old = r.get("plan") or {}
            new = leaders.plan(key, old.get("entry") if old.get("entry") is not None else r.get("price"))
            if old.get("style") == "hold" and new:
                old["aim"], old["aim_pct"] = new["aim"], new["aim_pct"]
                n += 1
    return n


def write(fix):
    # The file's own layout (one value a line, no padding), so a regenerated
    # fixture differs from the last one only where the lists do.
    OUT.write_text(json.dumps(fix, indent=0, separators=(",", ":"), ensure_ascii=False) + "\n",
                   encoding="utf-8")


def quarter_label(period_end):
    """A quarter's name as the tables write it: 30 Sep 2026 is "Q2 FY27"."""
    m, y = period_end.month, period_end.year
    return "Q%d FY%02d" % ((m - 4) % 12 // 3 + 1, (y + (m >= 4)) % 100)


def main():
    if "--marks" in sys.argv:
        fix = json.loads(OUT.read_text(encoding="utf-8"))
        print("marked %d picks" % marks(fix))
        write(fix)
        return 0
    import ideas_study as S
    import fundamental_ideas_lab as L
    need = ([os.path.join(S.DATA, "panel.pkl"), S.RESULTS_CSV]
            + [os.path.join(S.DATA, t) for t in L.TABLE_FILES.values()])
    missing = [p for p in need if not os.path.exists(p)]
    if missing:
        print("No study data at %s (missing %s). Run research/ideas_study.py --fetch --build first."
              % (S.DATA, ", ".join(os.path.basename(p) for p in missing)))
        return 1
    if not os.path.exists(S.SECTORS_CSV):
        S.SECTORS_CSV = str(SECTORS_FALLBACK)
    import pandas as pd
    import ideas
    import leaders

    P = S.Panel()
    pit = L.load_pit(P)
    U = P.universe(10)
    R = S.load_results(P)
    Y, _m = S.young_universe(P, U)
    sectors = S.load_sectors()
    names = pd.read_csv(S.RESULTS_CSV, usecols=["symbol", "company"]).drop_duplicates("symbol")
    names = dict(zip(names["symbol"], names["company"]))
    # How long each company has traded, as the replay tells the engine (its
    # frames hold 300 sessions; the emerging list needs to see further).
    S._AGE["age"] = S.listing_ages(P)

    # The feeds the lists read beside the scan. None of them has a history,
    # so each says nothing; the regime is the index's own, set per day below.
    ideas.sector_outlook = lambda: {}
    ideas._news_index = lambda hours: ({}, [])
    ideas._filing_for = lambda sym, hours, cats: None
    ideas._order_for = lambda sym: None
    ideas.tracker = None

    made = {}

    def scan(i, filings=True):
        """The scan payload the site would have held on the evening of
        session i, and the market regime it would have been told."""
        day = P.C.index[i]
        if i not in made:
            cands = S._engine_candidates(P, i, Y)
            liquid = [c["symbol"] for c in cands if leaders.in_universe(c["leader_sig"])]
            made[i] = (cands, L.snapshot_at(pit, i, day.date(), liquid, sectors, P.RAW))
        cands, snap = made[i]
        known = R[R["i"] <= i].drop_duplicates("symbol", keep="last")

        def num(v):
            return None if pd.isna(v) else float(v)
        filed = ({r.symbol: {"filed_at": str(r.filed)[:19], "quarter": quarter_label(r.period_end),
                             "pat_yoy_pct": num(r.pat_yoy_pct), "revenue_yoy_pct": num(r.revenue_yoy_pct)}
                  for r in known.itertuples(index=False)} if filings else {})
        # Each company's last quarter as the setup lists read it
        # (scan.latest_growth): a hundred sessions back at most.
        growth = {r.symbol: {"pat_yoy_pct": num(r.pat_yoy_pct), "revenue_yoy_pct": num(r.revenue_yoy_pct),
                             "pat_cr": num(r.pat_cr), "quarter": quarter_label(r.period_end)}
                  for r in known[known["i"] >= i - 100].itertuples(index=False)}
        # The index against its own averages that day, as the page is told it.
        n500 = P.N500
        vs200 = float((n500.iloc[i] / n500.rolling(200).mean().iloc[i] - 1) * 100)
        vs50 = float((n500.iloc[i] / n500.rolling(50).mean().iloc[i] - 1) * 100)
        regime = {"ok": vs50 >= 0, "stance": "Mixed", "pct_vs_50dma": round(vs50, 2),
                  "pct_vs_200dma": round(vs200, 2), "label": "", "benchmark": "NIFTY 500"}
        ideas.market_regime = lambda: regime
        blocks = leaders.rank(cands, results=filed, sectors=sectors, fundamentals=growth,
                              benchmark=S.benchmark_at(P, i), snapshot=snap)
        flow = {}
        for b in blocks.values():
            if b.get("sector_flow"):
                flow[b["sector_flow"]["sector"]] = b["sector_flow"]
        rows = []
        for sym, b in blocks.items():
            if not leaders.best_rank(b) or leaders.best_rank(b) > 22:
                continue
            j = P.C.columns.get_loc(sym)
            rows.append({"symbol": sym, "name": names.get(sym, sym), "sector": b.get("sector"),
                         "price": round(float(P.RAW.iat[i, j]), 2), "composite": None,
                         "technical": None, "fundamental": None, "f_score": None, "trailing_eps": None,
                         "setup": None, "setup_key": None, "setup_fit": None,
                         "avg_turnover_cr": b["facts"]["turnover_cr"], "leader": b})
        return ({"scanned_at": day.strftime("%d %b %Y") + ", 18:10", "universe_source": "NSE equity list",
                 "scored": len(rows), "factor_universe": rows, "rankings": rows,
                 "sector_flow": sorted(flow.values(), key=lambda r: r["rank"]),
                 "breakout_watch": leaders.breakout_watch(blocks), "short_watch": leaders.short_watch(blocks)},
                regime)

    def trimmed(sel, regime):
        out = {k: sel.get(k) for k in TOP_KEYS}
        out["rows"] = []
        for r in sel["rows"]:
            row = {k: r.get(k) for k in ROW_KEYS if k in r}
            # Of the leader block the page reads one thing: what the
            # company's filings say (block["fundamentals"]).
            f = (r.get("leader") or {}).get("fundamentals")
            if f is not None:
                row["leader"] = {"fundamentals": f}
            out["rows"].append(row)
        # When the fixture was made is not part of what it tests.
        out["staleness"] = {"days": 0, "hours": 2.0, "warn": False, "text": "Scanned today."}
        out["market_context"] = {"regime": regime, "leaders": [], "laggards": [], "headlines": []}
        return out

    fix = json.loads(OUT.read_text(encoding="utf-8"))
    for key in RETIRED:
        fix.pop(key, None)
    i = len(P.C) - 1
    day = P.C.index[i]
    p, regime = scan(i)

    # The three lists by holding time, each read the way the page reads it:
    # facts beside a pick, and a ledger that adds up to its score.
    counts = []
    for key, least in (("month", 10), ("results", 8), ("long", 10)):
        sel = ideas.select(p, horizon=key, limit=15)
        assert sel["method_key"] == "tested_lists" and sel["count"] >= least, (key, sel.get("selection_notes"))
        mix = set(leaders.mix_of(key))
        for r in sel["rows"]:
            assert 1 <= len(r["why"]) <= leaders.WHY_MAX, (key, r["symbol"], r["why"])
            keys = [e.get("key") for e in r["evidence"]]
            assert keys and set(keys) <= mix, (key, r["symbol"], keys)
            assert abs(sum(e["points"] for e in r["evidence"]) - r["conviction"]) < 0.5, (key, r["symbol"])
        assert all(r["chart"] for r in sel["rows"]), key
        if key == "results":
            assert all(r["results"] for r in sel["rows"]), key
        fix[key] = trimmed(sel, regime)
        counts.append("%s %d" % (key, sel["count"]))
    print("lists by holding time on %s: %s" % (day.date(), ", ".join(counts)))

    # The results list between two seasons: the last session before the
    # season that is running began (or this one, if none is running). With
    # the results that had reached the exchange by then, it is empty and
    # says when companies report again; were it not, with none at all.
    off = next(k for k in range(i, 0, -1) if not leaders.next_results_season(P.C.index[k].date())[1])
    p_off, regime_off = scan(off)
    empty = ideas.select(p_off, horizon="results", limit=15)
    if empty["count"]:
        p_off, regime_off = scan(off, filings=False)
        empty = ideas.select(p_off, horizon="results", limit=15)
    assert empty["count"] == 0 and empty["empty_text"], empty.get("selection_notes")
    fix["results_empty"] = trimmed(empty, regime_off)
    print("results between seasons, %s: %s" % (P.C.index[off].date(), empty["empty_text"]))

    # The setup lists, as they stood the same day as the three.
    ideas.market_regime = lambda: regime
    made_setups = []
    for key in leaders.SETUPS:
        sel = ideas.select(p, horizon=key, limit=15)
        assert sel["tested"] and sel["kind"] == "setup", key
        fix[key] = trimmed(sel, regime)
        made_setups.append("%s %d" % (key, sel["count"]))
    print("setup lists: " + ", ".join(made_setups))
    # The short list as it reads on a day nothing passes.
    fix["short_empty"] = dict(fix["short"], rows=[], count=0, watch=fix["short"].get("watch"),
                              empty_text=ideas.SETUP_EMPTY["short"],
                              selection_notes=[ideas.SETUP_EMPTY["short"]])
    marks(fix)
    write(fix)
    res = fix["results"]["rows"]
    print("wrote %s: results %s ... (%d reported, %d passed every test)"
          % (OUT.relative_to(ROOT), ", ".join(r["symbol"] for r in res[:5]),
             res[0]["results"]["reported"], res[0]["results"].get("qualified") or 0))
    return 0


if __name__ == "__main__":
    sys.exit(main())
