"""
The pages a search engine reads. Checked here:

  - a page is built only from what is stored (no network: conftest refuses it);
  - it says what the application would say, with the date, and nothing more;
  - no page carries advice;
  - an unknown or malformed symbol is a real 404, and is not kept;
  - the sitemap lists every page and nothing that is not one.
"""
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pages

HISTORY = [
    {"date": "2026-11-11", "composite": 45.2, "label": "MIXED", "price": 1320.0, "sector": "Energy", "f_score": 6.0},
    {"date": "2026-11-13", "composite": 47.3, "label": "MIXED", "price": 1331.3, "sector": "Energy", "f_score": 6.0},
]
QUARTERS = [
    {"period_end": "2026-09-30", "label": "Q2 FY27", "basis": "consolidated", "company": "Reliance Industries Limited",
     "revenue_cr": 258898.0, "pat_cr": 22146.0, "net_margin_pct": 8.6, "revenue_yoy_pct": 9.9, "pat_yoy_pct": 14.3},
    {"period_end": "2026-06-30", "label": "Q1 FY27", "basis": "consolidated",
     "revenue_cr": 248660.0, "pat_cr": 30783.0, "net_margin_pct": 12.4, "revenue_yoy_pct": 5.1, "pat_yoy_pct": -2.0},
]
INDUSTRIES = {
    "RELIANCE": {"name": "Reliance Industries Ltd.", "industry": "Oil Gas & Consumable Fuels", "isin": "INE002A01018"},
    "ONGC": {"name": "Oil & Natural Gas Corporation Ltd.", "industry": "Oil Gas & Consumable Fuels", "isin": "INE213A01029"},
    "M&M": {"name": "Mahindra & Mahindra Ltd.", "industry": "Automobile and Auto Components", "isin": "INE101A01026"},
}
SCORES = {"RELIANCE": {"score": 47.3, "label": "MIXED", "price": 1331.3, "date": "2026-11-13"},
          "ONGC": {"score": 61.0, "label": "CONSTRUCTIVE", "price": 250.0, "date": "2026-11-13"}}


@pytest.fixture()
def stored(monkeypatch):
    monkeypatch.setattr(pages, "industries", lambda: INDUSTRIES)
    monkeypatch.setattr(pages, "_history", lambda s: HISTORY if s == "RELIANCE" else [])
    monkeypatch.setattr(pages, "_quarters", lambda s, limit=5: QUARTERS if s == "RELIANCE" else [])
    monkeypatch.setattr(pages, "latest_scores", lambda: SCORES)
    monkeypatch.setattr(pages, "scored_symbols", lambda: ["RELIANCE", "ONGC", "ZOMATO"])


def _text(doc):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", doc))


def test_symbols_are_cleaned_or_refused():
    assert pages.clean_symbol(" reliance.ns ") == "RELIANCE"
    assert pages.clean_symbol("M&M") == "M&M"
    assert pages.clean_symbol("BAJAJ-AUTO") == "BAJAJ-AUTO"
    for bad in ("", "A" * 21, "REL<script>", "../etc", "A B", None):
        assert pages.clean_symbol(bad) is None


def test_a_stock_page_says_what_is_stored_with_its_date(stored):
    doc = pages.stock_page("reliance")
    text = _text(doc)
    assert "<h1>Reliance Industries Ltd.</h1>" in doc
    assert "On 13 Nov 2026 its Altaha score was 47 out of 100, a mixed profile, up 2 points since 11 Nov 2026." in text
    assert "Its Piotroski F-score, a nine-point check of financial health, is 6." in text
    assert ("In the quarter ended 30 Sep 2026 Reliance Industries Ltd. reported revenue of ₹2,58,898 cr, "
            "up 9.9% on a year earlier, and net profit of ₹22,146 cr, up 14.3%.") in text
    assert "Q1 FY27" in doc and "−2.0%" in doc
    assert '<link rel="canonical" href="https://altahascreener.in/stock/RELIANCE">' in doc
    assert 'href="https://altahascreener.in/stock.html?ticker=RELIANCE"' in doc
    assert "<title>Reliance Industries Ltd. (RELIANCE) share: score 47/100, results and peers | Altaha Screener</title>" in doc
    # peers link to their own pages, best score first
    assert 'href="https://altahascreener.in/stock/ONGC"' in doc
    assert "M&amp;M" not in doc                       # another industry
    # machine-readable questions match the visible ones
    assert '"@type": "FAQPage"' in doc and "What is the Altaha score of Reliance Industries Ltd.?" in doc
    assert "<script src" not in doc                   # nothing to run


def test_a_company_with_no_score_says_so(stored):
    doc = pages.stock_page("ONGC")
    text = _text(doc)
    assert "has not been through the nightly scan yet" in text
    assert "out of 100" not in text.split("Other Oil Gas")[0]
    assert "<title>Oil &amp; Natural Gas Corporation Ltd. (ONGC) share: score, results and peers | Altaha Screener</title>" in doc


def test_an_unknown_company_has_no_page(stored):
    assert pages.stock_page("NOSUCHCO") is None
    assert pages.stock_page("<script>") is None
    assert 'content="noindex"' in pages.not_found()


def test_markup_in_a_name_cannot_reach_the_page(stored, monkeypatch):
    evil = {"EVIL": {"name": 'Evil <img src=x onerror=alert(1)> "Ltd"', "industry": "Tech", "isin": ""}}
    monkeypatch.setattr(pages, "industries", lambda: evil)
    doc = pages.stock_page("EVIL")
    assert "<img src=x" not in doc
    assert "Evil &lt;img src=x onerror=alert(1)&gt; &quot;Ltd&quot;" in doc


def test_no_page_gives_advice(stored):
    import daily
    story = daily.story({"status": "closed", "indices": [
        {"label": "NIFTY 50", "level": 25144.3, "change_pct": -0.61}]})
    docs = [pages.stock_page("RELIANCE"), pages.stocks_page(), pages.today_page(story)]
    for doc in docs:
        text = _text(doc.split('<p class="note">')[0]).lower()     # the disclaimer names the words
        for word in (" buy ", " sell ", "target", "stop loss", "should you", "recommend"):
            assert word not in text, word
        assert "Nothing on this page is investment advice" in doc


def test_the_index_lists_every_company_by_industry(stored):
    doc = pages.stocks_page()
    assert "<h2>Oil Gas &amp; Consumable Fuels</h2>" in doc
    assert 'href="https://altahascreener.in/stock/M&amp;M"' in doc
    assert 'href="https://altahascreener.in/stock/ZOMATO"' in doc        # scored, not in the list
    assert "4 NSE companies" in _text(doc)
    assert re.search(r'stock/ONGC">[^<]+</a> <span>61</span>', doc)


def test_today_is_the_daily_summary_with_its_tables(stored):
    import daily
    sectors = {"rows": [
        {"sector": "Energy", "change_pct": 1.2, "up": 3, "total": 4,
         "stocks": [{"symbol": s, "change_pct": c} for s, c in
                    (("RELIANCE", 1.5), ("ONGC", 2.5), ("A", 0.1), ("B", -0.2), ("C", 0.3))]},
        {"sector": "Technology", "change_pct": -0.4, "up": 1, "total": 5,
         "stocks": [{"symbol": s, "change_pct": c} for s, c in
                    (("TCS", -1.1), ("INFY", -3.0), ("D", 0.2), ("E", -0.1), ("F", 0.0))]},
        {"sector": "Utilities", "change_pct": -0.9, "up": 0, "total": 2, "stocks": []}]}
    story = daily.story({"status": "closed", "indices": [
        {"label": "NIFTY 50", "level": 25144.3, "change_pct": -0.61}]}, sectors)
    doc = pages.today_page(story, sectors)
    text = _text(doc)
    assert "<h1>Markets fell</h1>" in doc
    assert "Nifty 50 closed at 25,144, down 0.61%." in text
    assert "Energy led, up 1.20%." in text
    assert "Biggest gainers" in doc and 'stock/ONGC">Oil &amp; Natural Gas Corporation Ltd.' in doc
    assert "Biggest fallers" in doc and "stock/INFY" in doc
    assert '<link rel="canonical" href="https://altahascreener.in/today">' in doc
    empty = pages.today_page(daily.story())
    assert "not in yet" in empty


def test_the_sitemap_lists_every_page_once(stored):
    xml = pages.sitemap(today="2026-11-14")
    locs = re.findall(r"<loc>([^<]+)</loc>", xml)
    assert locs[:4] == ["https://altahascreener.in/", "https://altahascreener.in/today",
                        "https://altahascreener.in/stocks", "https://altahascreener.in/brief.html"]
    assert "https://altahascreener.in/stock/M%26M" in locs
    assert "https://altahascreener.in/stock/ZOMATO" in locs
    assert len(locs) == len(set(locs)) == 4 + 4
    assert "<lastmod>2026-11-13</lastmod>" in xml


def test_the_carried_industry_list_loads():
    pages._ind["rows"] = None
    rows = pages.__dict__["industries"]()
    assert len(rows) > 500 and rows["RELIANCE"]["name"].startswith("Reliance")


def test_routes_serve_pages_and_real_404s(stored, monkeypatch):
    from fastapi.testclient import TestClient
    import main
    import swr
    swr.forget()
    client = TestClient(main.app)
    r = client.get("/p/stock/RELIANCE")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    assert "s-maxage=3600" in r.headers["cache-control"]
    assert "<h1>Reliance Industries Ltd.</h1>" in r.text
    r = client.get("/p/stock/NOSUCHCO")
    assert r.status_code == 404 and "noindex" in r.text and r.headers["cache-control"] == "no-store"
    assert "page:stock:NOSUCHCO" not in swr.stats()["keys"]
    assert client.get("/p/stock/a%20b").status_code == 404
    assert client.get("/p/stocks").status_code == 200
    r = client.get("/p/sitemap.xml")
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/xml")
    import xml.dom.minidom
    xml.dom.minidom.parseString(r.text)
    monkeypatch.setattr(main, "_market_now", lambda: {
        "indices": [{"label": "NIFTY 50", "level": 25144.3, "change": -155.0, "change_pct": -0.61}],
        "status": "closed", "ist": ""})
    r = client.get("/p/today")
    assert r.status_code == 200 and "Nifty 50 closed at 25,144" in r.text
    swr.forget()


def test_a_move_that_rounds_to_nothing_has_no_sign():
    assert pages._pct(-0.04) == "0.0%"
    assert pages._pct(-0.04, 2) == "−0.04%"
    assert pages._pct(1.72, 2) == "+1.72%"
    assert pages._pct(None) == "—"
