"""
Company pages: /stock-SYMBOL, /stocks and /sitemap.xml.

What a search engine is sent is the one part of this site nobody looks at. A
page with an empty <h1>, a second <title>, a canonical pointing at the wrong
host or a sitemap that lists four addresses renders perfectly in a browser
and is found by nobody. So everything here reads the HTML as a crawler does:
as text, without running a script.

The failures being guarded, most expensive first:
  · an empty snapshot answered as "no such company" (every indexed page
    reported as taken down);
  · standalone and consolidated quarters in one table (FUNDAMENTALS.md);
  · a percentage printed across a loss;
  · stock.html edited so the page can no longer be filled in;
  · a rewrite in vercel.json for a route the API does not have.
"""

import json
import os
import re
import xml.etree.ElementTree as ET

import pytest

import company_pages as CP
from company_pages_fixture import (ACME, ACME_QUARTERS, API, CHEMS, DELTA, GAMMA, GIANT,
                                   REPO, ROWS, SITE, pages)


@pytest.fixture(scope="module")
def stock_html():
    with open(os.path.join(REPO, "frontend", "stock.html"), encoding="utf-8") as fh:
        return fh.read()


@pytest.fixture(scope="module")
def built():
    return pages()


def _text(html_text):
    """The words on the page: tags and scripts out, whitespace collapsed."""
    t = re.sub(r"<(script|style)\b.*?</\1>", " ", html_text, flags=re.S)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", t))


def _glance(html_text):
    m = re.search(r'<section class="stk-sec stk-glance".*?</section>', html_text, re.S)
    assert m, "the at-a-glance section is not in the page"
    return m.group(0)


# ── stock.html can still be filled in ───────────────────────────────────────

def test_stock_html_still_has_every_place_the_page_is_written(stock_html):
    """
    render_company() writes into stock.html by its markers and its ids. An
    edit that renames one does not raise anywhere: the page is simply sent
    without its name, or without its figures. This is where that fails.
    """
    for needle, what in [
        (CP.HEAD_MARK, "the head marker"),
        (CP.GLANCE_MARK, "the at-a-glance marker"),
        ("<title>", "a <title>"),
        ('<meta name="description" content="', "a meta description"),
        ('id="nm"', "the <h1>"),
        ('<span id="crumb">', "the breadcrumb"),
        ('id="tags"', "the tags row"),
        ('id="px"', "the price"),
    ]:
        assert stock_html.count(needle) == 1, "stock.html must have %s exactly once" % what
    assert CP._usable(stock_html)
    # The section must be outside #body, which is hidden until stock.js has
    # an answer: inside it, a crawler would read a page with nothing showing.
    body_at = stock_html.index('<div id="body" hidden>')
    assert stock_html.index(CP.GLANCE_MARK) > body_at
    assert "</main>" in stock_html[stock_html.index(CP.GLANCE_MARK):]


# ── One company ─────────────────────────────────────────────────────────────

def test_the_page_names_the_company_before_any_script_runs(built):
    page = built["company"]
    assert page.count("<title>") == 1
    assert "<title>Acme Chemicals Ltd (ACME) share price, score and fundamentals | Altaha Screener</title>" in page
    assert re.search(r'<h1[^>]*id="nm"[^>]*>Acme Chemicals Ltd</h1>', page)
    assert '<span id="crumb">ACME</span>' in page
    assert re.search(r'id="px">₹812\.50</div>', page)
    assert "skel" not in re.search(r"<h1.*?</h1>", page, re.S).group(0), "the <h1> is still a skeleton"
    assert CP.HEAD_MARK not in page and CP.GLANCE_MARK not in page


def test_the_head_carries_what_a_crawler_reads(built):
    page = built["company"]
    assert page.count('rel="canonical"') == 1
    assert '<link rel="canonical" href="https://altahascreener.in/stock-ACME" />' in page
    desc = re.search(r'<meta name="description" content="([^"]*)"', page).group(1)
    assert "Acme Chemicals Ltd (NSE: ACME)" in desc and "₹812.50" in desc
    assert page.count('<meta name="description"') == 1
    assert 'property="og:image" content="https://altahascreener.in/og/stock.png?ticker=ACME"' in page
    ld = json.loads(re.search(r'<script type="application/ld\+json">(.*?)</script>', page, re.S).group(1))
    crumbs = ld["@graph"][0]["itemListElement"]
    assert [c["item"] for c in crumbs] == [SITE + "/", SITE + "/stocks", SITE + "/stock-ACME"]
    assert ld["@graph"][1]["about"]["tickerSymbol"] == "NSE ACME"
    # What stock.js reads to know it must keep this title and this canonical.
    assert 'window.ALTAHA_SSR={"ticker":"ACME"};' in page


def test_the_section_states_the_filed_figures(built):
    g = _text(_glance(built["company"]))
    assert "Acme Chemicals Ltd at a glance" in g
    assert "on a consolidated basis" in g
    assert "Acme Chemicals Ltd (NSE: ACME) is listed on the National Stock Exchange of India" in g
    assert "classified under Specialty Chemicals in the Chemicals sector" in g
    assert "last close of ₹812.50 a share the company is valued at ₹12,500 crore, 24.1 times" in g
    assert "quarter ended 30 June 2026 it reported revenue of ₹1,180 crore, up 10.5% on a year earlier" in g
    assert "Over FY26, revenue was ₹4,200 crore with a profit after tax of ₹518 crore" in g
    assert "Promoters hold 61.42% of the company, with none of it pledged" in g
    assert "Altaha Score: 61 out of 100" in g
    for label in ("Market cap", "P/E", "ROE", "ROCE", "Promoter holding"):
        assert label in g


def test_quarters_are_on_one_accounting_basis(built):
    """
    The store returns standalone and consolidated side by side. Acme's
    standalone revenue is less than half its consolidated: one of each in the
    table reads as revenue falling by sixty per cent in a quarter.
    """
    rows = re.findall(r"<tr><th scope=\"row\">(.*?)</th><td>(.*?)</td><td>(.*?)</td><td>(.*?)</td><td>(.*?)</td></tr>",
                      _glance(built["company"]))
    assert [r[0] for r in rows] == ["Q1 FY27", "Q4 FY26", "Q3 FY26", "Q2 FY26"]
    assert [r[1] for r in rows] == ["1,180", "1,106", "1,040", "1,010"]
    assert "470" not in [r[1] for r in rows], "a standalone quarter is in a consolidated table"
    assert rows[2][2] == "−12.5" and rows[2][3] == "−1.02", "a loss must read as a loss"
    assert rows[0][4] == "+10.5%" and rows[2][4] == "−2.4%" and rows[3][4] == "—"

    only = CP.quarters_for({"symbol": "ACME", "basis": "standalone"}, ACME_QUARTERS)
    assert {q["basis"] for q in only} == {"standalone"} and len(only) == 2
    # No basis on the row: whichever comes first is kept for the whole table.
    assert len({q["basis"] for q in CP.quarters_for({"symbol": "ACME"}, ACME_QUARTERS)}) == 1


def test_no_percentage_is_printed_across_a_loss():
    g = _text(CP.glance_html(GAMMA, ROWS))
    assert "it reported revenue of ₹190 crore and a loss of ₹4,300 crore" in g
    assert "on a year earlier" not in g, "growth was unknown and a direction was printed anyway"
    assert "with a loss of ₹24.0 crore" in g
    assert "Profit after tax (FY26) −₹24.0 crore" in g, "the minus belongs before the rupee sign"
    assert "times its earnings" not in g, "a P/E was printed for a company with none"
    assert "and 12.50% of all shares are pledged" in g


def test_a_thinly_covered_company_gets_a_shorter_page_not_a_broken_one():
    page = CP.render_plain(DELTA, ROWS, SITE, API)
    text = _text(page)
    for junk in ("None", "nan", "NaN", "₹—", "undefined"):
        assert junk not in text, "%r reached the page" % junk
    assert "Delta Infra Ltd (NSE: DELTA) is listed" in text
    assert "last close" not in text and "quarter ended" not in text and "Promoters hold" not in text
    assert "Quarterly results" not in text
    assert "ROCE" in text, "the one figure it does have is missing"


def test_large_values_read_in_lakh_crore():
    assert "valued at ₹16.21 lakh crore" in _text(CP.glance_html(GIANT, ROWS))
    assert CP.group_in(1234567.5, 2) == "12,34,567.50"
    assert CP.group_in(999) == "999" and CP.group_in(1000) == "1,000" and CP.group_in(-100000) == "−1,00,000"


def test_nothing_on_the_page_is_an_instruction():
    """Figures, not advice: the line the stock page has always held."""
    for row in (ACME, GAMMA, DELTA, GIANT):
        words = _text(CP.glance_html(row, ROWS, ACME_QUARTERS, 61.4)).lower()
        for word in (" buy", " sell", "target", "stop loss", "recommend", "should", "undervalued",
                     "overvalued", "multibagger"):
            assert word not in words, "%r is in %s's page" % (word, row["symbol"])


def test_a_hostile_name_cannot_leave_its_element():
    row = dict(ACME, symbol="EVIL", name='Evil </title><script>alert(1)</script> & "Co"',
               industry="A<b>B")
    for page in (CP.render_plain(row, ROWS + [row], SITE, API),
                 CP.render_directory(ROWS + [row], SITE, API)):
        assert "<script>alert(1)" not in page and "</title><script>" not in page
        assert "Evil &lt;/title&gt;&lt;script&gt;alert(1)&lt;/script&gt; &amp; &quot;Co&quot;" in page
    head = CP.head_tags(row, SITE)
    block = re.search(r'<script type="application/ld\+json">(.*?)</script>', head, re.S).group(1)
    assert "<" not in block and json.loads(block)["@graph"][1]["about"]["name"] == row["name"]


# ── Neighbours ──────────────────────────────────────────────────────────────

def test_peers_are_the_nearest_in_size_not_the_largest():
    smallest = CP.peers(CHEMS[0], ROWS)
    assert len(smallest) == 12
    assert "CHEM14" not in [p["symbol"] for p in smallest], \
        "the smallest company links to the largest instead of its neighbours"
    assert all(p["symbol"] != "CHEM01" for p in smallest), "a company is its own peer"
    assert {p["industry"] for p in smallest} == {"Specialty Chemicals"}


def test_every_company_with_a_neighbour_is_linked_from_one():
    """If the links only ran one way, the small companies' pages would have
    no way in except the sitemap."""
    chem = [r for r in ROWS if r.get("industry") == "Specialty Chemicals"]
    linked = {p["symbol"] for r in chem for p in CP.peers(r, ROWS)}
    assert linked == {r["symbol"] for r in chem}


def test_a_company_alone_in_its_industry_has_no_peer_section():
    assert CP.peers(GIANT, ROWS) == []
    assert "Other Refineries companies" not in CP.glance_html(GIANT, ROWS)
    assert 'href="/stocks"' in CP.glance_html(GIANT, ROWS), "and still links to the full list"


# ── Addresses ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw, want", [
    ("RELIANCE", "RELIANCE"), ("reliance.ns", "RELIANCE"), (" tcs ", "TCS"),
    ("M&M", "M&M"), ("BAJAJ-AUTO", "BAJAJ-AUTO"), ("3MINDIA", "3MINDIA"),
    ("", None), (None, None), ("../etc/passwd", None), ("A" * 21, None),
    ("<script>", None), ("A B", None), ("-X", None),
])
def test_only_a_symbol_is_a_symbol(raw, want):
    assert CP.clean_symbol(raw) == want


def test_an_ampersand_is_escaped_in_the_address():
    assert CP.path_for("M&M") == "/stock-M%26M"
    assert CP.path_for("BAJAJ-AUTO") == "/stock-BAJAJ-AUTO"
    assert 'href="/stock-G%26S"' in CP.render_directory(ROWS, SITE, API)


# ── The list and the sitemap ────────────────────────────────────────────────

def test_the_directory_links_every_company_once(built):
    page = built["directory"]
    hrefs = re.findall(r'<li data-k="[^"]*"><a href="([^"]+)"', page)
    want = sorted(CP.path_for(s) for s in CP.index(ROWS))
    assert sorted(hrefs) == want and len(hrefs) == len(set(hrefs)) == 18
    assert "NONAME" not in page, "a company with no name was listed"
    assert '<link rel="canonical" href="https://altahascreener.in/stocks" />' in page
    assert "18 NSE-listed companies" in _text(page)
    # A name that starts with a digit has somewhere to go, and it is first.
    assert page.index('id="l-0"') < page.index('id="l-A"')
    assert '<a href="#l-0">0–9</a>' in page


def test_an_empty_directory_says_so(built):
    page = CP.render_directory([], SITE, API)
    assert "being read" in _text(page) and not re.search(r"<li\b", page)


def test_the_sitemap_is_valid_and_complete(built):
    root = ET.fromstring(built["sitemap"])
    locs = [e.text for e in root.iter("{http://www.sitemaps.org/schemas/sitemap/0.9}loc")]
    assert locs[:4] == [SITE + "/", SITE + "/stocks", SITE + "/brief", SITE + "/advisors"]
    assert set(locs[4:]) == {SITE + CP.path_for(s) for s in CP.index(ROWS)}
    assert len(locs) == len(set(locs)) == 22
    assert SITE + "/stock-G%26S" in locs
    assert "NONAME" not in built["sitemap"]
    assert all(u.startswith(SITE + "/") for u in locs), "the sitemap names another host"


def test_the_missing_page_is_not_for_indexing(built):
    page = built["missing"]
    assert '<meta name="robots" content="noindex,follow" />' in page
    assert 'rel="canonical"' not in page
    assert 'href="/stocks"' in page and 'href="/stock?ticker=NOSUCH"' in page
    assert 'href="/stock?ticker=' not in CP.render_missing("<bad>", SITE, API)


# ── The routes ──────────────────────────────────────────────────────────────

@pytest.fixture()
def main(monkeypatch, stock_html):
    import main as M
    monkeypatch.setattr(M, "_company_rows", lambda: ROWS)
    monkeypatch.setattr(M, "_company_quarters", lambda sym: ACME_QUARTERS if sym == "ACME" else [])
    monkeypatch.setattr(M, "_company_score", lambda sym: 61.4 if sym == "ACME" else None)
    monkeypatch.setattr(CP, "template", lambda site, now=None: stock_html)
    return M


def _body(resp):
    return resp.body.decode("utf-8")


def test_a_company_is_served_and_may_be_cached(main):
    r = main.company_page("acme")
    assert r.status_code == 200 and r.media_type == "text/html"
    assert "s-maxage=3600" in r.headers["cache-control"]
    assert '<link rel="canonical" href="https://altahascreener.in/stock-ACME" />' in _body(r)
    assert "Q1 FY27" in _body(r)


def test_an_unknown_company_is_a_404_and_says_noindex(main):
    for raw in ("NOSUCH", "NONAME", "../x", "A" * 40):
        r = main.company_page(raw)
        assert r.status_code == 404, raw
        assert r.headers["x-robots-tag"] == "noindex"
        assert "noindex" in _body(r)


def test_an_empty_snapshot_is_a_503_never_a_404(main, monkeypatch):
    """
    The expensive one. After a deploy, or with the tables unreadable, there
    are no rows. Answering 404 tells a search engine that every company it
    had indexed is gone; 503 with Retry-After tells it to come back.
    """
    monkeypatch.setattr(main, "_company_rows", lambda: [])
    for r in (main.company_page("ACME"), main.sitemap_xml()):
        assert r.status_code == 503
        assert r.headers["retry-after"] == "300" and r.headers["cache-control"] == "no-store"
    d = main.company_directory()
    assert d.status_code == 200 and d.headers["cache-control"] == "no-store"


def test_without_the_template_the_figures_are_still_served_and_not_cached(main, monkeypatch):
    monkeypatch.setattr(CP, "template", lambda site, now=None: None)
    r = main.company_page("ACME")
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    page = _body(r)
    assert "<h1 class=\"stk-name\">Acme Chemicals Ltd</h1>" in page
    assert page.count('rel="canonical"') == 1 and "Q1 FY27" in page
    assert 'href="/stock?ticker=ACME"' in page, "no way through to the full page"


def test_the_sitemap_route(main):
    r = main.sitemap_xml()
    assert r.status_code == 200 and r.media_type == "application/xml"
    assert ET.fromstring(_body(r)).tag.endswith("urlset")


def test_an_escaped_ampersand_reaches_the_route_as_a_symbol(main):
    """
    The one place the address is decoded by the framework and not by this
    code. /stock-G%26S is proxied as /pages/company/G%26S; if the route saw
    "G%26S" the page for every company with an ampersand would be a 404.
    Through the real app, HEAD included, since that is how some crawlers ask.
    """
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient
    c = TestClient(main.app)
    r = c.get("/pages/company/G%26S")
    assert r.status_code == 200 and "Gamma &amp; Sons Ltd" in r.text
    assert 'href="https://altahascreener.in/stock-G%26S"' in r.text
    assert r.headers["content-type"].startswith("text/html")
    assert c.get("/pages/company/BAJAJ-AUTO").status_code == 404
    assert c.head("/pages/company/ACME").status_code == 200
    assert c.get("/pages/stocks").status_code == 200
    assert c.get("/sitemap.xml").headers["content-type"].startswith("application/xml")


def test_the_real_helpers_never_raise_without_data():
    """No scan, no tables, no network: each answers empty, and the routes
    turn that into a 503 or a page without a table."""
    import main as M
    assert M._company_score("ACME") is None
    assert isinstance(M._company_quarters("ACME"), list)
    assert isinstance(M._company_rows(), list)


def test_the_real_tables_make_a_page(monkeypatch, tmp_path, stock_html):
    """
    Everything above hands the routes made-up rows. This one fills the real
    store, lets the real snapshot build the row and the real route read the
    quarters, so a column renamed in either is caught here and not by a page
    that quietly loses its table. Nothing is asserted about the latest
    quarter's sentence: the snapshot drops a quarter once it is five months
    old, and a test that passes until January is not a test.
    """
    import sys
    monkeypatch.setenv("ALTAHA_FUNDAMENTALS_DB", str(tmp_path / "f.db"))
    monkeypatch.delitem(sys.modules, "fundamentals_store", raising=False)
    import fundamentals_store as store
    import fundamentals_query as Q
    import main as M
    from test_fundamentals_query import _fill, _quarter

    _fill(store)
    # The same quarter filed standalone too, at well under half the size.
    alone = _quarter(store, "ACME", "2026-06-30", 150, 12, 1.2)
    alone["basis"] = "standalone"
    store.upsert("income", [alone])

    monkeypatch.setattr(Q, "store", store)
    monkeypatch.setattr(Q.LM, "latest_prices", lambda: {"ACME": 320.0})
    monkeypatch.setattr(Q, "_profiles", lambda: (
        {"ACME": {"company": "Acme Ltd", "industry": "Chemicals", "issued_shares": 1e8}}, {}))
    monkeypatch.setattr(Q, "_cache", {"at": 0.0, "key": None, "rows": None, "built_utc": None})
    monkeypatch.setattr(M, "fundamentals_store", store)
    monkeypatch.setattr(CP, "template", lambda site, now=None: stock_html)

    r = M.company_page("ACME")
    assert r.status_code == 200
    page = _body(r)
    assert re.search(r'<h1[^>]*id="nm"[^>]*>Acme Ltd</h1>', page)
    assert re.search(r'id="px">₹320\.00</div>', page)
    assert "valued at ₹3,200 crore" in _text(page)
    revenue = re.findall(r'<tr><th scope="row">[^<]*</th><td>([^<]*)</td>', _glance(page))
    assert revenue == ["400", "400", "400", "400", "320"], revenue
    assert "on a consolidated basis" in _text(page)

    # A company with no price and no profile still has a name and a page.
    assert M.company_page("LOSS").status_code == 200
    locs = _body(M.sitemap_xml())
    assert "/stock-ACME</loc>" in locs and "/stock-LOSS</loc>" in locs


# ── The template ────────────────────────────────────────────────────────────

@pytest.fixture()
def fresh_template(monkeypatch):
    monkeypatch.setattr(CP, "_tpl", {"at": 0.0, "html": None, "source": None, "failed_at": 0.0})
    return monkeypatch


def test_the_template_is_read_from_the_repository_when_it_is_there(fresh_template, stock_html):
    fresh_template.setattr(CP, "_site_template", lambda site: pytest.fail("went to the network"))
    assert CP.template(SITE, now=1000.0) == stock_html
    assert CP.template_status()["source"] == "file"


def test_a_failed_read_is_not_repeated_for_every_request(fresh_template):
    calls = []
    fresh_template.setattr(CP, "_local_template", lambda: (None, None))
    fresh_template.setattr(CP, "_site_template", lambda site: (calls.append(site), (None, None))[1])
    assert CP.template(SITE, now=1000.0) is None
    assert CP.template(SITE, now=1030.0) is None
    assert len(calls) == 1, "a crawler would have turned one failed fetch into hundreds"
    assert CP.template(SITE, now=1000.0 + CP.TEMPLATE_RETRY + 1) is None
    assert len(calls) == 2


def test_a_good_copy_outlives_a_bad_read(fresh_template, stock_html):
    answers = [(stock_html, "site"), ("<html>502 Bad Gateway</html>", "site"), (None, None)]
    fresh_template.setattr(CP, "_local_template", lambda: (None, None))
    fresh_template.setattr(CP, "_site_template", lambda site: answers.pop(0))
    assert CP.template(SITE, now=1000.0) == stock_html
    later = 1000.0 + CP.TEMPLATE_TTL + 1
    assert CP.template(SITE, now=later) == stock_html, "an error page replaced the template"
    assert CP.template(SITE, now=later + CP.TEMPLATE_RETRY + 1) == stock_html
    assert answers == []


def test_the_stock_html_of_an_older_deploy_is_not_a_template(stock_html):
    """Its stock.js cannot read the company from /stock-SYMBOL. Better the
    plain page for ten minutes than an empty one."""
    old = stock_html.replace(CP.HEAD_MARK, "").replace(CP.GLANCE_MARK, "")
    assert 'id="nm"' in old and not CP._usable(old)
    assert not CP._usable("") and not CP._usable(None)


# ── The seam with the static host ───────────────────────────────────────────

def test_every_proxied_page_has_a_route_behind_it():
    """
    /stock-ACME on the site is a 404 unless vercel.json sends it to the API,
    and a 404 again unless the API has that route. Each half is right on its
    own; this checks they meet. (test_share_endpoints.py does the same for
    /share and /og.)
    """
    import main as M
    cfg = json.load(open(os.path.join(REPO, "frontend", "vercel.json"), encoding="utf-8"))
    by_source = {r["source"]: r["destination"] for r in cfg["rewrites"]}
    routes = {getattr(r, "path", None) for r in M.app.routes}
    for source, api_path in [("/stock-:symbol", "/pages/company/:symbol"),
                             ("/stocks", "/pages/stocks"),
                             ("/sitemap.xml", "/sitemap.xml")]:
        assert source in by_source, "vercel.json no longer proxies " + source
        dest = by_source[source]
        assert dest.startswith("https://") and dest.endswith(api_path), dest
        assert re.sub(r":(\w+)", r"{\1}", api_path) in routes, "the API has no route for " + api_path
    # /stock (the static page) and /stock-ACME (this one) must not shadow each other.
    assert by_source["/stock"] == "/stock.html"


def test_robots_txt_names_the_sitemap():
    text = open(os.path.join(REPO, "frontend", "robots.txt"), encoding="utf-8").read()
    assert "Sitemap: https://altahascreener.in/sitemap.xml" in text
    assert "Disallow" not in text
    assert not os.path.exists(os.path.join(REPO, "frontend", "sitemap.xml")), \
        "a static sitemap.xml would be served instead of the live one"
