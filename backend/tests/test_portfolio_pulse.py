"""
The portfolio pulse: winners, losers, and where each holding's news leans.

What these pin is mostly what the lean must NOT do — count a results filing as
good news, turn an unverified headline into sentiment, call a stock with no
news at all "positive" because its score is fine — and that every point it
does count is listed with the reason behind it.
"""
import datetime as dt

import portfolio_pulse as P


NOW = dt.datetime(2026, 10, 29, 12, 0, tzinfo=dt.timezone.utc)


def holding(sym, pnl_pct=None, day=None, score=None, ma200=None, weight=10.0):
    r = {"symbol": sym, "name": sym.title(), "weight_pct": weight, "pnl_pct": pnl_pct,
         "pnl": None if pnl_pct is None else pnl_pct * 100, "day_change_pct": day,
         "composite": score, "price": 100.0, "buy_price": 90.0}
    if ma200 is not None:
        r["moving_averages"] = {"200": ma200}
    return r


def filing(sym, category, importance="high", mapping="company"):
    return {"symbols": [sym], "mapping": mapping, "source": "NSE filing", "category": category,
            "materiality": importance, "headline": f"{sym}: {category}", "url": "https://nse/x.pdf",
            "published_at": "2026-10-28T10:00:00+00:00", "group": "Neutral / Informational"}


def press(sym, group="Neutral / Informational"):
    return {"symbols": [sym], "mapping": "company", "source": "Economic Times", "category": "Market development",
            "materiality": "medium", "headline": f"{sym} in the news", "url": "https://et/x",
            "published_at": "2026-10-28T10:00:00+00:00", "group": group}


def test_winners_and_losers_are_split_and_ordered_by_return():
    rows = [holding("A", 12.0), holding("B", -4.0), holding("C", 30.0), holding("D", -20.0), holding("E")]
    out = P.build(rows, [], NOW)
    assert out["winners"] == ["C", "A"]
    assert out["losers"] == ["D", "B"]
    assert out["no_cost"] == ["E"]


def test_today_counts_and_names_the_best_and_worst():
    rows = [holding("A", day=1.2), holding("B", day=-2.5), holding("C", day=0.4), holding("D")]
    t = P.build(rows, [], NOW)["today"]
    assert (t["up"], t["down"]) == (2, 1)
    assert t["best"] == "A" and t["worst"] == "B"


def test_an_order_win_leans_positive_and_says_why():
    out = P.build([holding("ABB")], [filing("ABB", "Order win")], NOW)["holdings"]["ABB"]
    assert out["lean"] == "positive" and out["news_backed"]
    top = out["reasons"][0]
    assert top["sign"] == 1 and top["points"] == 2.5 and "counts for" in top["why"]


def test_a_regulatory_action_leans_negative():
    out = P.build([holding("XYZ", score=80)], [filing("XYZ", "Regulatory action", "critical")], NOW)
    h = out["holdings"]["XYZ"]
    assert h["lean"] == "negative"
    assert h["points"] == round(-2.5 * 1.5 + 1, 2)
    assert out["leans"]["negative"] == ["XYZ"]


def test_results_are_listed_but_never_scored_as_good_or_bad():
    h = P.build([holding("TCS")], [filing("TCS", "Results")], NOW)["holdings"]["TCS"]
    assert h["points"] == 0 and h["lean"] == "mixed"
    assert h["reasons"][0]["sign"] == 0 and "Open the filing" in h["reasons"][0]["why"]


def test_an_unverified_headline_is_not_sentiment():
    h = P.build([holding("INFY")], [press("INFY")], NOW)["holdings"]["INFY"]
    assert h["points"] == 0 and h["lean"] == "quiet"
    assert h["reasons"][0]["kind"] == "press" and h["reasons"][0]["sign"] == 0


def test_verified_press_does_count():
    h = P.build([holding("INFY", score=75)], [press("INFY", "Positive Catalyst")], NOW)["holdings"]["INFY"]
    assert h["points"] == 2.0 and h["lean"] == "positive"


def test_no_news_needs_score_and_trend_to_agree_and_is_labelled_as_such():
    agree = P.build([holding("A", score=78, ma200=6.0)], [], NOW)["holdings"]["A"]
    assert agree["lean"] == "positive" and not agree["news_backed"]
    assert agree["lean_label"] == "Leaning positive · no fresh news"
    split = P.build([holding("B", score=78, ma200=-3.0)], [], NOW)["holdings"]["B"]
    assert split["lean"] == "quiet" and split["lean_label"] == "Quiet"


def test_sector_context_does_not_move_a_single_stock():
    h = P.build([holding("SBIN")], [filing("SBIN", "Order win", mapping="sector context")], NOW)["holdings"]["SBIN"]
    assert h["points"] == 0 and h["reasons"] == []


def test_scored_reasons_come_first_strongest_first():
    events = [press("ABB"), filing("ABB", "Dividend", "low"), filing("ABB", "Order win", "critical")]
    reasons = P.build([holding("ABB", score=72)], events, NOW)["holdings"]["ABB"]["reasons"]
    assert [r["points"] for r in reasons] == [3.0, 1.2, 1.0, 0.0]


def test_the_report_carries_the_pulse(monkeypatch):
    """Wired through portfolio_intelligence.enrich, and a failure there costs
    only the pulse."""
    import portfolio_intelligence as PI
    monkeypatch.setattr(P, "build", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    from portfolio import build_report
    rows = [{"symbol": "ABB", "qty": 1, "buy_price": 90, "price": 100, "value": 100.0, "cost": 90.0,
             "sector": "Capital Goods", "composite": 70}]
    report = build_report(rows, {}, histories={}, news_items=[], now=NOW)
    assert report["pulse"]["available"] is False
    assert "RuntimeError" in report["pulse"]["reason"]
    assert report["holdings"][0]["symbol"] == "ABB"


def test_a_real_report_has_a_pulse_for_every_priced_holding():
    from portfolio import build_report
    rows = [{"symbol": "ABB", "qty": 1, "buy_price": 90, "price": 100, "value": 100.0, "cost": 90.0,
             "sector": "Capital Goods", "composite": 70, "day_change_pct": 1.4},
            {"symbol": "TCS", "qty": 1, "buy_price": 120, "price": 100, "value": 100.0, "cost": 120.0,
             "sector": "IT", "composite": 35, "day_change_pct": -0.6}]
    pulse = build_report(rows, {}, histories={}, news_items=[], now=NOW)["pulse"]
    assert pulse["winners"] == ["ABB"] and pulse["losers"] == ["TCS"]
    assert pulse["holdings"]["TCS"]["reasons"][0]["kind"] == "score"
    assert pulse["today"]["best"] == "ABB"
