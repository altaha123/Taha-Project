"""
The stock page's own endpoints: named peers, the press, a company's filings,
and the fields /analyze gained for the score.

The failures that matter are the quiet ones:
  · three quarters added up and called a year, so every P/E reads a third dear
  · a P/E printed against a loss, or a P/B against negative equity
  · a small company "compared" with its industry's five giants
  · a headline about a different company on this company's page
  · a search engine's outage reading as "no news"
  · a refused exchange read reading as "this company filed nothing"
  · a script URL from a feed reaching an href
"""

import datetime as dt
import sys
import time

import pytest

TODAY = dt.date(2026, 9, 25)
QS = ["2026-06-30", "2026-03-31", "2025-12-31", "2025-09-30"]


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("ALTAHA_FUNDAMENTALS_DB", str(tmp_path / "f.db"))
    for m in ("fundamentals_store", "stock_page"):
        sys.modules.pop(m, None)
    import fundamentals_store
    return fundamentals_store


def _q(store, sym, end, rev, pat, opm=20.0, basis="consolidated"):
    import fundamentals as F
    e = dt.date.fromisoformat(end)
    row = store.to_row("income", {
        "symbol": sym, "company": sym.title() + " Ltd", "basis": basis,
        "freq": "quarterly", "label": F.quarter_label(e),
        "period_from": (e - dt.timedelta(days=90)).isoformat(), "period_end": end,
        "months": 3, "filed_at": "2026-08-01", "audited": "Unaudited",
        "source_url": "https://x/%s-%s.xml" % (sym, end)},
        {"revenue": rev * 1e7, "pat": pat * 1e7, "ebitda": rev * opm / 100 * 1e7})
    row["opm_pct"] = opm
    return row


def _year(store, sym, end, rev, pat, basis="consolidated"):
    return store.to_row("income", {
        "symbol": sym, "company": sym.title() + " Ltd", "basis": basis, "freq": "annual",
        "label": "FY%s" % end[2:4], "period_end": end, "months": 12,
        "filed_at": "2026-05-01", "source_url": "https://x/%s-y.xml" % sym},
        {"revenue": rev * 1e7, "pat": pat * 1e7})


def _sheet(store, sym, end, equity, debt, basis="consolidated"):
    return store.to_row("balance", {
        "symbol": sym, "company": sym.title() + " Ltd", "basis": basis,
        "label": end, "period_end": end, "filed_at": "2026-05-01",
        "source_url": "https://x/%s-b.xml" % sym},
        {"total_assets": equity * 3e7, "total_equity": equity * 1e7,
         "total_borrowings": debt * 1e7, "debt_equity_x": round(debt / equity, 2)})


def _company(store, sym, cap_cr, pat_q=100, equity=2000, quarters=QS, website=None):
    """A company with a profile, `quarters` of results, a year and a sheet."""
    store.record_yf_profile(sym, {
        "longName": sym.title() + " Ltd", "industry": "Widgets", "sector": "Industrials",
        "sharesOutstanding": 1e7, "currentPrice": cap_cr, "marketCap": cap_cr * 1e7,
        "currency": "INR", "website": website})
    store.upsert("income", [_q(store, sym, e, 1000, pat_q) for e in quarters]
                 + [_year(store, sym, "2026-03-31", 4000, pat_q * 4)])
    store.upsert("balance", [_sheet(store, sym, "2026-03-31", equity, 500)])


# ── 1. The trailing year ───────────────────────────────────────────────────

def test_four_quarters_in_a_row_make_a_year_and_three_do_not(store):
    store.upsert("income", [_q(store, "FULL", e, 1000, 100) for e in QS])
    store.upsert("income", [_q(store, "SHORT", e, 1000, 100) for e in QS[:3]])
    # Four rows, but with a quarter missing in the middle: the oldest is a
    # year and a quarter back, and adding them up is not twelve months.
    gap = [QS[0], QS[1], QS[2], "2025-06-30"]
    store.upsert("income", [_q(store, "GAP", e, 1000, 100) for e in gap])
    out = store.trailing_year(["FULL", "SHORT", "GAP", "NOBODY"])
    assert set(out) == {"FULL"}
    assert out["FULL"]["revenue_cr"] == 4000 and out["FULL"]["pat_cr"] == 400
    assert out["FULL"]["through"] == "2026-06-30"


def test_a_year_is_on_one_basis(store):
    store.upsert("income", [_q(store, "MIX", e, 1000, 100) for e in QS])
    store.upsert("income", [_q(store, "MIX", e, 400, 40, basis="standalone") for e in QS])
    assert store.trailing_year(["MIX"])["MIX"]["pat_cr"] == 400     # consolidated only


def test_a_website_is_kept_and_an_older_store_gains_the_column(store):
    import sqlite3
    store.record_yf_profile("ACME", {"industry": "Widgets", "website": "https://www.acme.example/"})
    assert store.profiles_for(["ACME", "NOBODY"])["ACME"]["website"] == "https://www.acme.example/"
    # A database made before the column existed.
    path = store._state["active_path"]
    store._local.conn.close()
    store._local.conn = None
    store._ready["done"] = False
    conn = sqlite3.connect(path)
    conn.executescript("DROP TABLE yf_profile; CREATE TABLE yf_profile (symbol TEXT PRIMARY KEY,"
                       " company TEXT, sector TEXT, industry TEXT, shares REAL, price REAL,"
                       " market_cap REAL, currency TEXT, updated_utc TEXT NOT NULL);")
    conn.commit()
    conn.close()
    assert store.record_yf_profile("OLD", {"industry": "Widgets", "website": "old.example"})
    assert store.yf_profile("OLD")["website"] == "old.example"


# ── 2. The named peers ─────────────────────────────────────────────────────

def test_peers_are_worked_out_one_way_and_blanks_stay_blank(store):
    import stock_page as S
    for i, s in enumerate(["P1", "P2", "P3", "P4"]):
        _company(store, s, cap_cr=1000 * (i + 1))
    _company(store, "ACME", cap_cr=2400, website="https://www.acme.example/about")
    _company(store, "LOSS", cap_cr=500, pat_q=-50)
    _company(store, "THREEQ", cap_cr=700, quarters=QS[:3])
    out = S.peer_table("ACME.NS", "Widgets", ["P1", "P2", "P3", "P4", "ACME", "LOSS", "THREEQ"],
                       scores={"P2": 61.26, "ACME": 44.0}, today=TODAY)
    assert out["available"]
    rows = {r["symbol"]: r for r in out["rows"]}
    me = rows["ACME"]
    assert me["is_self"] and sum(r["is_self"] for r in out["rows"]) == 1
    # 2,400 crore of market value over 400 crore of trailing profit.
    assert me["pe"] == 6.0 and me["pb"] == 1.2 and me["roe_pct"] == 20.0
    assert me["domain"] == "acme.example" and me["score"] == 44.0 and me["band"] == "Average"
    assert rows["P2"]["band"] == "Strong" and rows["P1"]["score"] is None
    assert rows["LOSS"]["pe"] is None, "a P/E was printed against a loss"
    assert rows["THREEQ"]["pe"] is None, "three quarters were called a year"
    assert rows["THREEQ"]["pb"] is not None
    # Largest first, and the medians leave the company itself out.
    caps = [r["market_cap_cr"] for r in out["rows"]]
    assert caps == sorted(caps, reverse=True)
    assert out["medians"]["market_cap_cr"] == _median([1000, 2000, 3000, 4000, 500, 700])
    assert out["peers_shown"] == 6 and out["industry_members"] == 6


def _median(vals):
    vals = sorted(vals)
    mid = len(vals) // 2
    return vals[mid] if len(vals) % 2 else (vals[mid - 1] + vals[mid]) / 2.0


def test_a_large_industry_shows_the_neighbours_not_the_giants(store):
    import stock_page as S
    names = ["C%02d" % i for i in range(30)]
    for i, s in enumerate(names):
        _company(store, s, cap_cr=100 * (i + 1))           # C00 smallest, C29 largest
    out = S.peer_table("C03", "Widgets", names, today=TODAY, limit=6)
    shown = [r["symbol"] for r in out["rows"]]
    assert "C03" in shown and len(shown) == 7
    assert "C29" not in shown, "a small company was set beside the industry's largest"
    assert all(abs(int(s[1:]) - 3) <= 6 for s in shown)
    assert "nearest to it in market value" in out["selection"]
    # The largest company's window is the top of the list.
    top = [r["symbol"] for r in S.peer_table("C29", "Widgets", names, today=TODAY, limit=6)["rows"]]
    assert top[0] == "C29" and len(top) == 7


def test_too_few_peers_and_no_industry_say_so(store):
    import stock_page as S
    _company(store, "ACME", 1000)
    _company(store, "P1", 900)
    few = S.peer_table("ACME", "Widgets", ["ACME", "P1"], today=TODAY)
    assert not few["available"] and "Too few" in few["message"]
    none = S.peer_table("ACME", None, [], today=TODAY)
    assert not none["available"] and "not held" in none["message"]


def test_a_fresh_close_replaces_a_stale_profile_price(store):
    import pandas as pd
    import stock_page as S
    for s in ["ACME", "P1", "P2", "P3"]:
        _company(store, s, cap_cr=1000)
    panel = {"close": pd.DataFrame(
        {"ACME": [1900.0, 2000.0], "P1": [float("nan"), float("nan")]},
        index=pd.to_datetime(["2026-09-23", "2026-09-24"]))}
    closes = S.closes_from_panel(panel, {"ACME", "P1", "P2"})
    assert closes == {"ACME": (2000.0, "2026-09-24")}
    out = S.peer_table("ACME", "Widgets", ["ACME", "P1", "P2", "P3"], closes=closes, today=TODAY)
    me = next(r for r in out["rows"] if r["is_self"])
    assert me["price"] == 2000.0 and me["market_cap_cr"] == 2000 and me["pe"] == 5.0
    # The peers are priced from their stored profiles, written today; the
    # company from the exchange's file. The table states both ends.
    assert out["prices_oldest"] == "2026-09-24" and out["prices_as_of"] >= out["prices_oldest"]
    assert S.closes_from_panel(None, {"ACME"}) == {} and S.closes_from_panel({}, {"ACME"}) == {}


# ── 3. Logos ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("website, want", [
    ("https://www.sbi.co.in/web/home", "sbi.co.in"),
    ("http://ril.com", "ril.com"),
    ("WWW.TCS.COM/", "tcs.com"),
    ("https://user:pw@real.example:8443/x", "real.example"),
    ("javascript:alert(1)", None),
    ("https://exa mple.com", None),
    ("localhost", None),
    ("", None), (None, None),
    ('x.com"><script>', None),
])
def test_only_a_plain_hostname_becomes_a_logo_domain(website, want):
    import stock_page as S
    assert S.domain_of(website) == want


def test_the_stored_website_wins_over_the_curated_table():
    import stock_page as S
    assert S.domain_for("SBIN.NS") == "sbi.co.in"
    assert S.domain_for("SBIN", "https://bank.sbi/") == "bank.sbi"
    assert S.domain_for("NOSUCHCO") is None
    assert all(S.domain_of(d) == d for d in S.KNOWN_DOMAINS.values())


# ── 4. The press ───────────────────────────────────────────────────────────

def _rss(items):
    now = dt.datetime.now(dt.timezone.utc)
    body = "".join(
        "<item><title>%s</title><link>%s</link><pubDate>%s</pubDate>"
        "<source url=\"https://p\">%s</source></item>"
        % (t, u, (now - dt.timedelta(hours=h)).strftime("%a, %d %b %Y %H:%M:%S GMT"), src)
        for t, u, h, src in items)
    return ("<rss><channel>%s</channel></rss>" % body).encode()


def test_a_search_result_is_parsed_as_published():
    import stock_news as N
    rows = N.parse(_rss([
        ("SBI raises ₹7,500 crore via bonds - Mint", "https://news.example/a", 2, "Mint"),
        ("Dash - in a headline &amp; an entity - Business Standard", "https://news.example/b", 30, "Business Standard"),
        ("A script link", "javascript:alert(1)", 1, "Bad"),
        ("", "https://news.example/c", 1, "Empty"),
    ]))
    assert [r["headline"] for r in rows] == ["SBI raises ₹7,500 crore via bonds",
                                             "Dash - in a headline & an entity"]
    assert rows[0]["source"] == "Mint" and rows[0]["kind"] == "press"
    assert 100 <= rows[0]["age_minutes"] <= 130
    assert N.parse(b"<html>blocked</html>") == [] and N.parse(b"not xml") == []


@pytest.mark.parametrize("symbol, name, headline, want", [
    ("SBIN", "State Bank of India", "SBI Q2 profit rises 10%", True),
    ("SBIN", "State Bank of India", "State Bank of India to raise funds", True),
    ("SBIN", "State Bank of India", "State Bank of Pakistan holds rates", False),
    ("BANKBARODA", "Bank of Baroda Limited", "Bank of Maharashtra cuts MCLR", False),
    ("ADANIGREEN", "Adani Green Energy Limited", "Adani Green commissions 500 MW", True),
    ("ADANIGREEN", "Adani Green Energy Limited", "Adani Ports volumes rise", False),
    ("DRREDDY", "Dr. Reddy's Laboratories Limited", "Dr Reddy's gets USFDA nod", True),
    ("VEDL", "Vedanta Limited", "Medanta hospital chain expands", False),
    ("ACME", "Acme Chemicals Ltd", "Acme Chemicals wins export order", True),
    ("ACME", "Acme Chemicals Ltd", "Chemicals sector under pressure", False),
])
def test_a_headline_must_name_the_company(symbol, name, headline, want):
    import stock_news as N
    patterns, _ = N.aliases_for(symbol, name)
    assert N.mentions(headline, patterns) is want


def test_the_company_search_asks_for_the_name_and_its_short_form():
    import stock_news as N
    q = N.company_query("SBIN", "State Bank of India")
    assert q.startswith('"State Bank of India"') and '"SBI"' in q and "when:" in q
    assert N.company_query("ACME", "Acme Chemicals Ltd").startswith('"Acme Chemicals"')
    assert N.clean_name("Acme Chemicals (India) Ltd.") == "Acme Chemicals (India)"
    assert N.company_query("X", "") is None


@pytest.mark.parametrize("sector, industry, label", [
    ("Financial Services", "Banks - Regional", "Banks"),
    ("Financial Services", "Private Sector Bank", "Banks"),
    ("Financial Services", "Insurance - Life", "Insurance"),
    ("Financial Services", "Credit Services", "Lenders and NBFCs"),
    ("Financial Services", "Capital Markets", "Capital markets"),
    ("Technology", "Information Technology Services", "IT services"),
    ("Healthcare", "Drug Manufacturers - Specialty & Generic", "Pharma"),
    ("Energy", "Oil & Gas Refining & Marketing", "Oil and gas"),
    ("Basic Materials", "Steel", "Metals and mining"),
    ("Basic Materials", "Specialty Chemicals", "Chemicals"),
    ("Consumer Cyclical", "Auto Manufacturers", "Automobiles"),
    ("Industrials", "Electrical Equipment & Parts", "Capital goods and infrastructure"),
    ("Utilities", "Utilities - Regulated Electric", "Power and utilities"),
    ("Real Estate", None, "Real estate"),
    ("Odd Sector", "Space Tourism", "Space Tourism"),
])
def test_an_industry_is_read_as_its_kind_of_business(sector, industry, label):
    import stock_news as N
    got, query, _drivers = N.group_for(sector, industry)
    assert got == label and query
    assert N.group_for(None, None) == (None, None, [])


def test_the_two_lists_are_kept_apart_and_tagged():
    import stock_news as N
    N._memo.clear()
    answers = {
        "company": _rss([
            ("SBI Q2 net profit rises 10% - Mint", "https://n.example/1", 3, "Mint"),
            ("State Bank of Pakistan holds rates - Dawn", "https://n.example/2", 4, "Dawn"),
            ("SBI Q2 net profit rises 10% - Moneycontrol", "https://n.example/3", 5, "Moneycontrol"),
            ("SBI to hire 5,000 - ET", "https://n.example/old", 24 * 40, "ET"),
        ]),
        "industry": _rss([
            ("Banks' credit growth slows to 11% - Business Standard", "https://n.example/4", 10, "Business Standard"),
            ("RBI keeps repo rate unchanged - Mint", "https://n.example/5", 20, "Mint"),
            ("Bank holidays this week - ET", "https://n.example/6", 1, "ET"),
            ("SBI chairman on deposit growth - ET", "https://n.example/7", 2, "ET"),
        ]),
    }
    asked = []

    def fetch(query):
        asked.append(query)
        return N.parse(answers["company" if "State Bank of India" in query else "industry"])

    out = N.for_stock("SBIN.NS", "State Bank of India", "Financial Services", "Banks - Regional",
                      fetch=fetch)
    assert len(asked) == 2
    company = [r["headline"] for r in out["company"]["rows"]]
    assert company == ["SBI Q2 net profit rises 10%"], company     # deduped, verified, fresh
    industry = out["industry"]["rows"]
    heads = [r["headline"] for r in industry]
    assert "SBI chairman on deposit growth" not in heads, "a company story is in the industry list"
    assert out["industry"]["label"] == "Banks"
    tagged = {r["headline"]: r["driver"] for r in industry}
    assert tagged["RBI keeps repo rate unchanged"] == "Interest rates"
    assert tagged["Banks' credit growth slows to 11%"] == "Credit and deposits"
    assert tagged["Bank holidays this week"] is None
    assert heads[-1] == "Bank holidays this week", "an untagged headline is above a tagged one"
    assert out["kind"] == "press" and all(r["kind"] == "press" for r in industry)
    # Remembered: the same page view again asks nobody.
    N.for_stock("SBIN", "State Bank of India", "Financial Services", "Banks - Regional", fetch=fetch)
    assert len(asked) == 2


def test_an_unanswered_search_is_not_no_news():
    import stock_news as N
    N._memo.clear()
    out = N.for_stock("ACME", "Acme Chemicals Ltd", "Basic Materials", "Specialty Chemicals",
                      fetch=lambda q: None)
    assert out["company"]["rows"] == [] and out["company"]["searched"] is False
    assert out["industry"]["searched"] is False and out["industry"]["label"] == "Chemicals"
    N._memo.clear()
    out = N.for_stock("ACME", "Acme Chemicals Ltd", "Basic Materials", "Specialty Chemicals",
                      fetch=lambda q: [])
    assert out["company"]["searched"] is True


# ── 5. A company's filings ─────────────────────────────────────────────────

def _filing(sym, head, days_ago, cat="Results"):
    at = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days_ago)
    return {"symbol": sym, "scrip_code": "", "company": sym, "headline": head,
            "exchange_category": cat, "category": cat, "importance": "critical", "weight": 5,
            "at": at.isoformat(), "epoch": at.timestamp(), "pdf": "https://nse.example/x.pdf"}


def test_a_companys_filings_join_both_sources_once():
    import announcements as A
    A._company_memo.clear()
    before = dict(A._state["by_symbol"])
    try:
        shared = _filing("ACME", "Financial results for the quarter", 2)
        A._state["by_symbol"] = {"ACME": [shared, _filing("ACME", "Board meeting intimation", 1, "Board meeting")]}
        calls = []

        def fetch(sym, days):
            calls.append(sym)
            return [dict(shared), _filing("ACME", "Dividend declared", 90, "Dividend"),
                    _filing("ACME", "An old filing", 500, "Other")]

        out = A.for_company("acme.ns", fetch=fetch)
        assert out["available"] and out["symbol"] == "ACME"
        heads = [r["headline"] for r in out["rows"]]
        assert heads == ["Board meeting intimation", "Financial results for the quarter",
                         "Dividend declared"], heads
        assert {c["name"]: c["count"] for c in out["categories"]} == \
            {"Results": 1, "Board meeting": 1, "Dividend": 1}
        assert out["source"].startswith("NSE")
        A.for_company("ACME", fetch=fetch)
        assert calls == ["ACME"], "the exchange was asked twice inside the memo"
    finally:
        A._state["by_symbol"] = before
        A._company_memo.clear()


def test_a_refused_read_is_not_a_company_with_no_filings():
    import announcements as A
    A._company_memo.clear()
    before = dict(A._state["by_symbol"])
    try:
        A._state["by_symbol"] = {}
        calls = []

        def refuse(sym, days):
            calls.append(sym)
            return None

        out = A.for_company("ACME", fetch=refuse)
        assert not out["available"] and out["rows"] == [] and "could not be read" in out["message"]
        # Remembered for a minute, not a quarter of an hour.
        A._company_memo["ACME"] = (time.time() - A.COMPANY_TTL - 1, None)
        A.for_company("ACME", fetch=refuse)
        assert len(calls) == 2
        # Answered and empty is a different fact.
        A._company_memo.clear()
        quiet = A.for_company("ACME", fetch=lambda s, d: [])
        assert quiet["available"] and quiet["rows"] == [] and "message" not in quiet
    finally:
        A._state["by_symbol"] = before
        A._company_memo.clear()


def test_an_nse_row_becomes_a_filing():
    import announcements as A
    item = A._nse_item({"symbol": "acme", "sm_name": "Acme Ltd", "desc": "Updates",
                        "attchmntText": "Acme has <b>received</b> a letter of award worth Rs 500 crore",
                        "an_dt": "10-Nov-2026 18:01:02", "attchmntFile": "https://nse.example/a.pdf"})
    assert item["symbol"] == "ACME" and item["category"] == "Order win"
    assert "<b>" not in item["headline"] and item["pdf"].endswith("a.pdf")
    assert A._nse_item({"symbol": "", "desc": "x"}) is None and A._nse_item("nope") is None


# ── 6. The score's word, and its rank at every horizon ─────────────────────

def test_the_score_carries_the_sites_one_scale():
    import multifactor as M
    rows = [{"symbol": "S%02d" % i, "factors": {n: float(i) for n in M.F.REGISTRY}}
            for i in range(40)]
    ranked = M.rank(rows, "position")["rows"]
    top = max(ranked, key=lambda r: r["position_score"])
    shown = M.presentation(top["altaha_score_v4"], "position")
    import score_bands
    assert shown["band"] == score_bands.band(shown["score"])
    assert shown["band"] in {b for _f, b in score_bands.BANDS}
    assert "label" in shown, "the older word other screens read was dropped"


# ── 7. Through the routes ──────────────────────────────────────────────────

@pytest.fixture()
def api(store, monkeypatch):
    import main
    import stock_page
    before = main._state.get("payload")
    monkeypatch.setattr(main, "stock_page", stock_page)
    monkeypatch.setattr(main, "fundamentals_store", store)
    yield main
    main._state["payload"] = before


def test_the_peers_route_names_the_industry_and_carries_scan_scores(api, monkeypatch):
    for i, s in enumerate(["P1", "P2", "P3", "ACME"]):
        _company(store_of(api), s, cap_cr=1000 * (i + 1))
    monkeypatch.setattr(api, "_industry_members",
                        lambda sym: ("NSE", "Widgets", ["P1", "P2", "P3", "ACME"]))
    api._state["payload"] = {"factor_universe": [
        {"symbol": "P1", "position_score": 63.0}, {"symbol": "P2", "position_score": None}]}
    # Dated against the real clock here, so the fixture's quarters must be
    # recent enough to count; pin the store's freshness window open.
    import fundamentals as F
    monkeypatch.setattr(F, "STORE_FRESH_DAYS", 100000)
    out = api.stock_peers("acme.ns")
    assert out["available"] and out["industry"] == "Widgets" and out["classifier"] == "NSE"
    rows = {r["symbol"]: r for r in out["rows"]}
    assert rows["ACME"]["is_self"] and rows["P1"]["score"] == 63.0 and rows["P1"]["band"] == "Strong"
    assert rows["P2"]["score"] is None
    with pytest.raises(api.HTTPException):
        api.stock_peers("")


def store_of(api):
    return api.fundamentals_store


def test_the_news_route_searches_only_for_a_company_the_server_knows(api, monkeypatch):
    """A request names any string it likes. The words that become a search are
    the server's own record of the company, and a company it has never heard
    of is not searched for at all."""
    import stock_news
    seen = []

    def for_stock(sym, name=None, sector=None, industry=None, free_industry=True):
        seen.append(dict(sym=sym, name=name, sector=sector, industry=industry, free=free_industry))
        return {"symbol": sym, "kind": "press", "company": {"rows": []}, "industry": {"rows": []}}

    monkeypatch.setattr(stock_news, "for_stock", for_stock)
    monkeypatch.setattr(api, "stock_news", stock_news)
    monkeypatch.setattr(api.scanner, "universe_with_names",
                        lambda: [{"s": "LISTED", "n": "Listed Only Ltd", "x": "NSE"}])
    api._state["payload"] = {"factor_universe": [
        {"symbol": "SCANNED", "name": "Scanned Co Ltd", "sector": "Energy", "industry": "Steel"},
        {"symbol": "BARE", "name": "BARE", "sector": "Energy", "industry": "Steel"}]}

    # Unknown everywhere: nothing goes out, and the answer says nobody looked.
    out = api.stock_news_view("NOSUCHCO", sector="Energy", industry='x" OR anything')
    assert seen == [] and out["company"]["searched"] is False and out["industry"]["rows"] == []

    # In the scan: the scan's own name and industry, whatever the request says.
    api.stock_news_view("scanned.ns", sector="Technology", industry="Software")
    assert seen[-1] == dict(sym="SCANNED", name="Scanned Co Ltd", sector="Energy",
                            industry="Steel", free=True)

    # A stored profile fills what the scan does not hold.
    store_of(api).record_yf_profile("ACME", {"longName": "Acme Stored Ltd", "sector": "Industrials",
                                             "industry": "Widgets"})
    api.stock_news_view("ACME")
    assert seen[-1]["name"] == "Acme Stored Ltd" and seen[-1]["industry"] == "Widgets"

    # Only on the exchange's list: its name from there, and the page's sector
    # and industry accepted as a hint that may choose a search, not write one.
    api.stock_news_view("LISTED", sector="Financial Services", industry="Banks - Regional")
    assert seen[-1] == dict(sym="LISTED", name="Listed Only Ltd", sector="Financial Services",
                            industry="Banks - Regional", free=False)

    # A scan row that carries its ticker for a name is not searched by it.
    api.stock_news_view("BARE")
    assert seen[-1]["name"] is None and seen[-1]["industry"] == "Steel"


def test_a_requests_industry_can_choose_a_search_but_not_write_one():
    import stock_news as N
    assert N.group_for("Odd", "Space Tourism", free=False) == (None, None, [])
    assert N.group_for("Odd", "Space Tourism")[0] == "Space Tourism"
    assert N.group_for("Financial Services", 'Banks" OR secret', free=False)[0] == "Banks"
    N._memo.clear()
    asked = []
    out = N.for_stock("ACME", None, "Odd", 'anything" OR else', free_industry=False,
                      fetch=lambda q: asked.append(q) or [])
    assert asked == [], "words from a request became a search: %s" % asked
    assert out["company"]["searched"] is False and out["industry"]["label"] is None


def test_the_search_rests_after_three_unanswered(monkeypatch):
    import stock_news as N
    N._memo.clear()
    N._trip.update(fails=0, until=0.0)
    calls = []
    monkeypatch.setattr(N, "_fetch", lambda q: calls.append(q) or None)
    try:
        for i in range(5):
            assert N.search("query %d" % i) is None
        assert len(calls) == N.TRIP_AFTER, "a search engine that is not answering was asked %d times" % len(calls)
        # An answer clears the count.
        N._trip.update(fails=0, until=0.0)
        monkeypatch.setattr(N, "_fetch", lambda q: [])
        assert N.search("fresh") == [] and N._trip["fails"] == 0
    finally:
        N._trip.update(fails=0, until=0.0)
        N._memo.clear()


def test_the_filings_route_reads_one_company_the_server_knows(api, monkeypatch):
    asked = {}
    monkeypatch.setattr(api.ann, "poll_if_stale", lambda *a, **k: None)
    monkeypatch.setattr(api.ann, "for_company",
                        lambda sym, limit=60, ask=True: asked.update(sym=sym, limit=limit, ask=ask) or
                        {"symbol": sym, "available": True, "rows": [], "count": 0})
    monkeypatch.setattr(api.scanner, "universe_with_names", lambda: [{"s": "ACME", "n": "Acme Ltd"}])
    api._state["payload"] = {"factor_universe": []}
    out = api.stock_filings("acme.ns", limit=5000)
    assert out["symbol"] == "ACME" and asked == {"sym": "ACME", "limit": 200, "ask": True}
    # A string the server has never heard of is not put to the exchange.
    api.stock_filings("ZZZZ9999")
    assert asked["ask"] is False
    # Nor is anything, for the page's first screen: held=1 reads memory only.
    api.stock_filings("ACME", held=True)
    assert asked["sym"] == "ACME" and asked["ask"] is False


def test_an_unknown_symbol_reads_only_what_is_held_and_a_refusal_rests_the_exchange(monkeypatch):
    import sys, types
    import announcements as A
    A._company_memo.clear()
    A._company_trip["until"] = 0.0
    before = dict(A._state["by_symbol"])
    calls = []

    class Resp:
        def json(self):
            return None

    fake = types.SimpleNamespace(get=lambda *a, **k: calls.append(k.get("params")) or None)
    monkeypatch.setitem(sys.modules, "nse_http", fake)
    try:
        A._state["by_symbol"] = {}
        out = A.for_company("ZZZZ9999", ask=False)
        assert calls == [] and not out["available"]
        # A refusal: asked once, not a second way, and then nobody is asked.
        assert A.for_company("ACME")["available"] is False
        assert len(calls) == 1 and calls[0]["symbol"] == "ACME" and "from_date" in calls[0]
        A.for_company("OTHER")
        assert len(calls) == 1, "the exchange was asked again while it was refusing"
        assert A._company_trip["until"] > time.time()
    finally:
        A._state["by_symbol"] = before
        A._company_memo.clear()
        A._company_trip["until"] = 0.0
