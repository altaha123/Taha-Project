"""
Add the results list to frontend/tests/fixtures/picks.json.

The four price lists in that file are the live endpoint's answer for 9 Nov
2026, trimmed to what the page reads. The results list did not exist then, so
its entry is made here the way the site makes it: the real engine
(leaders.rank, ideas.select) run on the study's price panel and results table
for the same day. Two entries are written:

  results         the list as it stood on the panel's last session
  results_empty   the same day with no filings, which is every day between
                  results seasons

    IDEAS_DATA=/path/to/study/data python backend/tests/make_picks_fixture.py

It needs the data research/ideas_study.py --fetch and --build leave behind,
and says so and stops when that is not there.
"""

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "research"))
OUT = ROOT / "frontend" / "tests" / "fixtures" / "picks.json"

ROW_KEYS = ("symbol", "name", "price", "sector", "list", "setup", "setup_key", "horizon", "pick_rank",
            "young", "conviction", "conviction_band", "why", "evidence", "plan", "results", "order",
            "technicals", "chart", "news", "adverse_filing", "avg_turnover_cr", "liquidity_tier",
            "tracked", "composite", "technical", "fundamental", "f_score", "setup_fit", "call")
TOP_KEYS = ("available", "degraded", "method_key", "list", "horizon", "label", "idea", "hold_text",
            "exit_pct", "tested", "study", "scanned_at", "partial", "scored", "universe_source",
            "universe", "regime", "market_test", "chart_note", "empty_text", "event", "sector_mix",
            "sector_cap", "selection_notes", "excluded_adverse", "count", "considered", "method",
            "recipe_current")


def main():
    import ideas_study as S
    if not os.path.exists(os.path.join(S.DATA, "panel.pkl")) or not os.path.exists(S.RESULTS_CSV):
        print("No study data at %s. Run research/ideas_study.py --fetch --build first." % S.DATA)
        return 1
    import pandas as pd
    import ideas
    import leaders

    P = S.Panel()
    U = P.universe(10)
    R = S.load_results(P)
    Y, _m = S.young_universe(P, U)
    i = len(P.C) - 1
    day = P.C.index[i]
    names = pd.read_csv(S.RESULTS_CSV, usecols=["symbol", "company"]).drop_duplicates("symbol")
    names = dict(zip(names["symbol"], names["company"]))

    cands = S._engine_candidates(P, i, Y)
    known = R[R["i"] <= i].drop_duplicates("symbol", keep="last")
    filed = {r.symbol: {"filed_at": str(r.filed)[:19], "quarter": "Q2 FY27",
                        "pat_yoy_pct": None if pd.isna(r.pat_yoy_pct) else float(r.pat_yoy_pct),
                        "revenue_yoy_pct": None if pd.isna(r.revenue_yoy_pct) else float(r.revenue_yoy_pct)}
             for r in known.itertuples(index=False)}

    # The index against its own 200-day average that day, as the page is told it.
    n500 = P.N500
    vs200 = float((n500.iloc[i] / n500.rolling(200).mean().iloc[i] - 1) * 100)
    vs50 = float((n500.iloc[i] / n500.rolling(50).mean().iloc[i] - 1) * 100)
    regime = {"ok": vs50 >= 0, "stance": "Mixed", "pct_vs_50dma": round(vs50, 2),
              "pct_vs_200dma": round(vs200, 2), "label": "", "benchmark": "NIFTY 500"}
    ideas.sector_outlook = lambda: {}
    ideas.market_regime = lambda: regime
    ideas._news_index = lambda hours: ({}, [])
    ideas._filing_for = lambda sym, hours, cats: None
    ideas._order_for = lambda sym: None
    ideas.tracker = None

    def payload(results):
        blocks = leaders.rank(cands, results=results)
        rows = []
        for sym, b in blocks.items():
            if not leaders.best_rank(b) or leaders.best_rank(b) > 22:
                continue
            j = P.C.columns.get_loc(sym)
            rows.append({"symbol": sym, "name": names.get(sym, sym), "sector": None,
                         "price": round(float(P.RAW.iat[i, j]), 2), "composite": None,
                         "technical": None, "fundamental": None, "f_score": None, "trailing_eps": None,
                         "setup": None, "setup_key": None, "setup_fit": None,
                         "avg_turnover_cr": b["facts"]["turnover_cr"], "leader": b})
        return {"scanned_at": day.strftime("%d %b %Y") + ", 18:10", "universe_source": "NSE equity list",
                "scored": len(rows), "factor_universe": rows, "rankings": rows}

    def trimmed(sel):
        out = {k: sel.get(k) for k in TOP_KEYS}
        out["rows"] = [{k: r.get(k) for k in ROW_KEYS if k in r} for r in sel["rows"]]
        # When the fixture was made is not part of what it tests.
        out["staleness"] = {"days": 0, "hours": 2.0, "warn": False, "text": "Scanned today."}
        out["market_context"] = {"regime": regime, "leaders": [], "laggards": [], "headlines": []}
        return out

    fix = json.loads(OUT.read_text(encoding="utf-8"))
    full = ideas.select(payload(filed), horizon="results", limit=15)
    assert full["count"] == 15 and full["tested"], full.get("selection_notes")
    assert all(r["chart"] and r["results"] for r in full["rows"])
    fix["results"] = trimmed(full)
    empty = ideas.select(payload({}), horizon="results", limit=15)
    assert empty["count"] == 0 and empty["empty_text"]
    fix["results_empty"] = trimmed(empty)
    # The file's own layout (one value a line, no padding), so a regenerated
    # fixture differs from the last one only where the lists do.
    OUT.write_text(json.dumps(fix, indent=0, separators=(",", ":"), ensure_ascii=False) + "\n",
                   encoding="utf-8")
    print("wrote the results list for %s to %s: %s ... (%d reported)"
          % (day.date(), OUT.relative_to(ROOT), ", ".join(r["symbol"] for r in full["rows"][:5]),
             full["rows"][0]["results"]["reported"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
