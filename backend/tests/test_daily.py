"""Today in a minute: every sentence comes from a figure, and a missing figure
leaves its sentence out rather than leaving a hole in one."""
import datetime as dt

import daily

NOW = dt.datetime(2026, 11, 13, 16, 0, tzinfo=daily.IST)

MARKET = {"status": "closed", "indices": [
    {"label": "NIFTY 50", "level": 25144.3, "change": -155.05, "change_pct": -0.61},
    {"label": "SENSEX", "level": 81592.45, "change": -318.55, "change_pct": -0.39},
    {"label": "BANK NIFTY", "level": 61034.1, "change": -484.4, "change_pct": -0.79}]}


def _sector(name, chg, stocks):
    return {"sector": name, "change_pct": chg,
            "stocks": [{"symbol": s, "change_pct": c} for s, c in stocks]}


SECTORS = {"rows": [
    _sector("Real Estate", 1.72, [("PHOENIXLTD", 5.57), ("SOBHA", 4.4), ("DLF", 0.2), ("LODHA", -0.3)]),
    _sector("Technology", -0.04, [("TCS", 0.1), ("INFY", -0.2), ("WIPRO", -0.4), ("HCLTECH", 0.3)]),
    _sector("Utilities", -1.19, [("NTPC", -1.0), ("POWERGRID", -0.8), ("ADANIPOWER", -3.1), ("TATAPOWER", 0.1)]),
]}

WEEK = {"sessions": [
    {"date": "2026-11-12", "label": "Thu 12 Nov", "flows": {"fii": {"net": -100.0}, "dii": {"net": 50.0}}},
    {"date": "2026-11-13", "label": "Fri 13 Nov",
     "flows": {"fii": {"net": 5736.55}, "dii": {"net": -2253.58}}}]}

CALENDAR = {"available": True, "days": [
    {"date": "2026-11-13", "declared": 238, "pending": 12},
    {"date": "2026-11-14", "declared": 8, "pending": 184}]}


def _by_key(out):
    return {l["key"]: l["text"] for l in out["lines"]}


def test_indian_grouping():
    assert daily.indian(25144.3) == "25,144"
    assert daily.indian(12345678.9) == "1,23,45,679"
    assert daily.indian(999) == "999"
    assert daily.indian(-5736.55) == "-5,737"
    assert daily.indian(None) == "—"


def test_the_whole_story():
    out = daily.story(MARKET, SECTORS, WEEK, CALENDAR, {"matter": 2}, now=NOW)
    t = _by_key(out)
    assert t["market"] == ("Nifty 50 closed at 25,144, down 0.61%. "
                           "Sensex fell 0.39% and Bank Nifty fell 0.79%.")
    assert t["sectors"] == ("Real Estate led, up 1.72%. Utilities was weakest, down 1.19%. "
                            "1 of 3 sectors rose.")
    assert t["movers"] == ("PHOENIXLTD gained most among large companies, up 5.57%. "
                           "ADANIPOWER fell most, down 3.10%.")
    assert t["flows"] == ("Foreign investors bought ₹5,737 crore of shares; "
                          "Indian funds sold ₹2,254 crore.")
    assert t["results"] == "250 companies report results today; 238 filed so far."
    assert t["brief"] == "2 new government or regulator circulars matter for listed companies today."
    assert out["headline"] == "Markets fell"
    assert out["day"] == "13 Nov 2026" and out["weekday"] == "Friday"
    assert out["share_text"].startswith("Indian market today, 13 Nov 2026\n\n• Nifty 50 closed")
    assert out["share_text"].endswith("More at https://altahascreener.in/today")


def test_an_open_market_is_described_as_still_moving():
    live = dict(MARKET, status="open")
    out = daily.story(live, now=NOW)
    assert _by_key(out)["market"].startswith("Nifty 50 is at 25,144, down 0.61% so far today.")
    assert out["headline"] == "Markets are down"


def test_missing_parts_leave_their_sentences_out():
    out = daily.story(MARKET, None, None, None, None, now=NOW)
    assert [l["key"] for l in out["lines"]] == ["market"]
    empty = daily.story(now=NOW)
    assert empty["lines"] == [] and empty["share_text"] == ""
    assert empty["headline"] == "Today in the market"


def test_flows_from_an_earlier_session_say_which_day():
    monday = dt.datetime(2026, 11, 16, 9, 0, tzinfo=daily.IST)
    t = _by_key(daily.story(MARKET, None, WEEK, None, None, now=monday))
    assert t["flows"].endswith("(Fri 13 Nov.)")


def test_both_sides_buying_reads_as_and_not_as_a_contrast():
    week = {"sessions": [{"date": "2026-11-13", "flows": {"fii": {"net": 100.0}, "dii": {"net": 200.0}}}]}
    t = _by_key(daily.story(None, None, week, None, None, now=NOW))
    assert t["flows"] == "Foreign investors bought ₹100 crore of shares and Indian funds bought ₹200 crore."


def test_a_day_when_everything_fell():
    rows = {"rows": [_sector("A", -0.2, []), _sector("B", -0.9, []), _sector("C", -1.5, [])]}
    t = _by_key(daily.story(None, rows, None, None, None, now=NOW))
    assert t["sectors"] == "Every sector fell. A held up best, down 0.20%; C fell most, 1.50%."


def test_no_results_day_and_no_circulars_say_nothing():
    cal = {"available": True, "days": [{"date": "2026-11-13", "declared": 0, "pending": 0}]}
    out = daily.story(None, None, None, cal, {"matter": 0}, now=NOW)
    assert out["lines"] == []


def test_no_sentence_gives_advice():
    out = daily.story(MARKET, SECTORS, WEEK, CALENDAR, {"matter": 2}, now=NOW)
    text = " ".join(l["text"] for l in out["lines"]).lower()
    for word in ("buy ", "sell ", "target", "should", "recommend", "stop loss"):
        assert word not in text


def test_company_names_replace_symbols_where_known():
    names = {"PHOENIXLTD": "The Phoenix Mills Ltd.", "ADANIPOWER": "Adani Power Limited"}
    t = _by_key(daily.story(None, SECTORS, None, None, None, now=NOW, names=names))
    assert t["movers"] == ("The Phoenix Mills gained most among large companies, up 5.57%. "
                           "Adani Power fell most, down 3.10%.")
    assert daily.short_name("Tata Consultancy Services Ltd") == "Tata Consultancy Services"
    assert daily.short_name(None) == ""
