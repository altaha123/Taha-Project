"""
What a search engine reads on the static side of the site.

test_company_pages.py covers the pages the API writes. This covers the files
the static host serves as they are: the homepage's own HTML, the three
reading pages (/glossary, /methodology, /planner), and the scripts that
decide what a crawler sees when the API is asleep. Everything is read as
text, the way a crawler first reads it.

The failures being guarded:
  · an address in the sitemap that the site answers with a 404;
  · a glossary page that no longer says what the glossary says;
  · a weights table that disagrees with the one beside the score;
  · "The engine is unreachable" quoted by a search engine as the page;
  · data-nosnippet on an element where it does nothing.
"""

import html
import json
import os
import re
import shutil
import subprocess

import pytest

import company_pages as CP
from company_pages_fixture import REPO, SITE

FRONT = os.path.join(REPO, "frontend")
READING = {"/glossary": "glossary.html", "/methodology": "methodology.html",
           "/planner": "planner.html"}


def _read(name):
    with open(os.path.join(FRONT, name), encoding="utf-8") as fh:
        return fh.read()


def _text(html_text):
    t = re.sub(r"<(script|style)\b.*?</\1>", " ", html_text, flags=re.S)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", t))


def _ld(html_text):
    return json.loads(re.search(r'<script type="application/ld\+json">(.*?)</script>',
                                html_text, re.S).group(1))


@pytest.fixture(scope="module")
def vercel():
    cfg = json.loads(_read("vercel.json"))
    return {r["source"]: r["destination"] for r in cfg["rewrites"]}


# ── Every address in the sitemap is a page ──────────────────────────────────

def test_every_site_page_in_the_sitemap_is_served(vercel):
    """
    SITE_PAGES is printed into sitemap.xml. An address there that the static
    host does not answer is a 404 handed to a search engine by name.
    """
    for path in CP.SITE_PAGES:
        if path == "/":
            assert os.path.isfile(os.path.join(FRONT, "index.html"))
            continue
        assert path in vercel, "%s is in the sitemap and vercel.json does not serve it" % path
        dest = vercel[path]
        if dest.startswith("https://"):
            continue        # proxied to the API: test_company_pages.py checks the route
        assert os.path.isfile(os.path.join(FRONT, dest.lstrip("/"))), dest + " does not exist"


def test_the_new_addresses_shadow_nothing(vercel):
    """
    The static host serves a file before it tries a rewrite, so /planner must
    not be the name of a file, and no rewrite may claim another's address.
    """
    sources = list(vercel)
    assert len(sources) == len(set(sources))
    for path in list(READING) + ["/stock", "/brief", "/advisors", "/wealth", "/pro", "/signin"]:
        assert vercel[path] == path + ".html"
        assert not os.path.exists(os.path.join(FRONT, path.lstrip("/"))), \
            "a file named %s would be served instead of the page" % path
    # A pattern must not swallow a fixed address: /stock-:symbol and /sector-:slug
    # need their hyphen, which none of the fixed ones has after the same word.
    for fixed in sources:
        if ":" in fixed:
            continue
        assert not fixed.startswith(("/stock-", "/sector-")), fixed
    assert not [n for n in os.listdir(FRONT) if n.startswith(("stock-", "sector-"))], \
        "a file whose name starts like a company or sector address"


# ── The three reading pages ─────────────────────────────────────────────────

@pytest.mark.parametrize("path", sorted(READING))
def test_a_reading_page_carries_what_a_crawler_reads(path):
    page = _read(READING[path])
    assert page.count("<title>") == 1 and page.count('<meta name="description"') == 1
    assert page.count('rel="canonical"') == 1
    assert '<link rel="canonical" href="%s%s" />' % (SITE, path) in page
    assert '<meta name="robots" content="index,follow" />' in page
    assert page.count("<h1") == 1
    title = re.search(r"<title>(.*?)</title>", page).group(1)
    assert title.endswith("| Altaha Screener") and 30 < len(title) < 110
    desc = re.search(r'<meta name="description" content="([^"]*)"', page).group(1)
    assert 80 < len(desc) < 260
    graph = _ld(page)["@graph"]
    assert graph[0]["@type"] == "BreadcrumbList"
    assert graph[0]["itemListElement"][-1]["item"] == SITE + path
    assert graph[1]["@type"] == {"/glossary": "DefinedTermSet", "/methodology": "Article",
                                 "/planner": "WebApplication"}[path]
    # The words are in the file. A page that needs a script to say anything
    # is the problem these pages exist to solve.
    assert len(_text(page[page.index("<main"):])) > 1500
    # The site's own header and footer, and addresses that work from the root.
    assert 'src="shell.js' in page and 'src="clean-url.js"' in page
    for junk in ("TODO", "lorem", "undefined"):
        assert junk not in page


def test_the_reading_pages_do_not_share_a_title_or_a_description():
    pages = [_read(f) for f in READING.values()] + [_read("index.html")]
    titles = [re.search(r"<title>(.*?)</title>", p).group(1) for p in pages]
    descs = [re.search(r'<meta name="description" content="([^"]*)"', p).group(1) for p in pages]
    assert len(set(titles)) == len(titles) and len(set(descs)) == len(descs)


def _vocab():
    """[(term, one-line meaning)] from the list index.html draws its glossary from."""
    src = re.search(r"const VOCAB = \[(.*?)\n\];", _read("index.html"), re.S).group(1)
    js = lambda s: json.loads('"%s"' % s)
    return [(js(t), js(s)) for t, s in
            re.findall(r'\bt:"((?:[^"\\]|\\.)*)".*?\bs:"((?:[^"\\]|\\.)*)"', src, re.S)]


def test_the_glossary_page_says_what_the_glossary_says():
    """
    Two copies of the definitions, one in a script and one in a page. The
    page is generated from the script's list (frontend/tools/build-glossary.cjs)
    and this fails when someone edits a term and does not run it.
    """
    terms = _vocab()
    assert len(terms) >= 24
    page = _read("glossary.html")
    shown = [(html.unescape(re.sub(r"\s*<span>.*?</span>", "", t)), html.unescape(s)) for t, s in
             re.findall(r'<h3>(.*?)</h3>\s*<p class="doc-def">(.*?)</p>', page, re.S)]
    assert shown == terms, "the glossary page and the glossary in index.html have drifted"
    assert page.count('class="doc-term"') == len(terms)
    for must in ("ROCE", "ROE", "Piotroski F-Score", "Mohanram G-Score", "Promoter pledging",
                 "Supertrend", "OBV"):
        assert must in dict(terms), must
    # Each term can be linked to, and no two share an anchor.
    ids = re.findall(r'\bid="([^"]+)"', page[page.index("<main"):])
    assert len(ids) == len(set(ids)), "two elements on the glossary page share an id"
    defined = _ld(page)["@graph"][1]["hasDefinedTerm"]
    assert [d["name"] for d in defined] == [t for t, _s in terms]
    assert [d["description"] for d in defined] == [s for _t, s in terms]
    assert all(d["@id"].split("#")[1] in ids for d in defined)


def test_the_glossary_generator_agrees_with_the_page():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    r = subprocess.run([node, os.path.join(FRONT, "tools", "build-glossary.cjs"), "--check"],
                       capture_output=True, text=True, cwd=REPO)
    assert r.returncode == 0, r.stderr or r.stdout


def _weights(html_text, marker):
    table = html_text[html_text.index(marker):]
    table = table[:table.index("</table>")]
    return re.findall(r'<tr><th scope="row">([^<]+)</th><td>[^<]*</td>'
                      r"<td>(\d+)</td><td>(\d+)</td><td>(\d+)</td></tr>", table)


def test_the_methodology_page_has_the_weights_the_score_tab_has():
    tab = _weights(_read("index.html"), '<table class="scr-weights">')
    page = _weights(_read("methodology.html"), 'id="weights"')
    assert len(tab) == 8 and page == tab, "the two weights tables disagree"
    for col in (1, 2, 3):
        assert sum(int(r[col]) for r in page) == 100, "a holding period's weights do not add to 100"
    # And the engine's own: the table is a statement about profiles.V4_WEIGHTS.
    import profiles
    for col, horizon in ((1, "trade"), (2, "position"), (3, "invest")):
        printed = {r[0].lower().replace(" ", "_"): int(r[col]) for r in page}
        assert printed == profiles.V4_WEIGHTS[horizon], "the %s weights are not the engine's" % horizon


def test_the_methodology_bands_are_the_engine_s():
    bands = pytest.importorskip("score_bands")
    words = _text(_read("methodology.html"))
    assert "Strong %d and above" % bands.STRONG in words
    assert "Good %d to %d" % (bands.GOOD, bands.STRONG) in words
    assert "Average %d to %d" % (bands.WEAK, bands.GOOD) in words
    assert "Weak %d to %d" % (bands.POOR, bands.WEAK) in words
    assert "Poor under %d" % bands.POOR in words


def test_the_planner_page_states_the_planner_s_own_defaults():
    math = _read("planner-math.js")
    d = dict(re.findall(r"(\w+): (\d+)", re.search(r"var DEFAULTS = \{([^}]*)\}", math).group(1)))
    words = _text(_read("planner.html")).replace("&times;", "×")
    assert "Return on investments %s%% a year" % d["ret"] in words
    assert "Inflation %s%% a year" % d["infl"] in words
    assert "%s × a year’s spending" % d["multiple"] in words.replace("&rsquo;", "’")
    assert "Saving raised by %s%% a year" % d["stepUp"] in words
    assert 'href="./#portfolio/planner"' in _read("planner.html"), "no way into the planner itself"
    # It is arithmetic, and says so: no promise and no product.
    for word in ("guarantee", "assured", "best fund", "we recommend"):
        assert word not in words.lower()


# ── The homepage's own HTML ─────────────────────────────────────────────────

def test_the_homepage_links_to_companies_without_a_script():
    """
    Everything else on the homepage that leads to a company is drawn by a
    script. These are in the file, where a crawler reading it as text finds
    them and passes the homepage's standing on.
    """
    page = _read("index.html")
    static = re.sub(r"<script\b.*?</script>", "", page, flags=re.S)
    hrefs = re.findall(r'<a\b[^>]*\bhref="([^"]+)"', static)
    for must in ("/stocks", "/glossary", "/methodology", "/planner",
                 "/stock-RELIANCE", "/stock-TCS", "/stock-HDFCBANK", "/stock-INFY"):
        assert must in hrefs, must + " is not a plain link on the homepage"
    assert '<a href="/stocks">All NSE Companies (A&ndash;Z)</a>' in static
    companies = [h for h in hrefs if h.startswith("/stock-")]
    assert len(set(companies)) >= 12
    for h in companies:
        sym = h[len("/stock-"):]
        assert CP.clean_symbol(sym) == sym and CP.path_for(sym) == h, h
    # The "Try" line is links for the NSE names and still runs the analysis.
    hint = re.search(r'<p class="hint">.*?</p>', static, re.S).group(0)
    assert hint.count('<a href="/stock-') == 3 and 'data-t="RELIANCE"' in hint
    assert '.hint [data-t]' in page


def test_owner_controls_are_not_shown_to_a_visitor():
    page = _read("index.html")
    assert re.search(r'<div id="lowner" class="la-owner" hidden>', page), \
        "the live scanner's owner controls are showing by default"
    assert '$("lowner").hidden = !isOwner();' in page


# ── What a search engine may quote ──────────────────────────────────────────

SNIPPET_TAGS = {"div", "span", "section"}


def test_nosnippet_is_only_put_where_it_works():
    """
    data-nosnippet is honoured on div, span and section. On a <nav>, a <p> or
    a <footer> it is valid HTML that does nothing, and nothing would say so.
    """
    seen = 0
    for name in sorted(os.listdir(FRONT)):
        if not name.endswith((".html", ".js")):
            continue
        for tag in re.findall(r"<([a-zA-Z0-9]+)\b[^<>]*\bdata-nosnippet", _read(name)):
            seen += 1
            assert tag.lower() in SNIPPET_TAGS, "%s: data-nosnippet on <%s>" % (name, tag)
    assert seen >= 12


@pytest.mark.parametrize("name", ["wow.js", "special.js", "investors.js", "funds.js", "concalls.js"])
def test_an_unreachable_engine_is_not_quoted_as_the_page(name):
    src = _read(name)
    lines = [l for l in src.splitlines() if "engine is unreachable" in l and "//" not in l.split("'")[0]]
    assert lines, name + " no longer has the message this test is about"
    for line in lines:
        assert "data-nosnippet" in line, name + ": " + line.strip()


def test_the_menus_are_not_quoted_as_the_page():
    shell = _read("shell.js")
    assert "chrome.setAttribute('data-nosnippet', '')" in shell
    assert '<div class="sh-fin" data-nosnippet>' in shell and '<div class="sh-fbase" data-nosnippet>' in shell
    home = _read("index.html")
    assert '<div class="tabnav" data-nosnippet>' in home
    assert re.search(r'<section class="site-links"[^>]*data-nosnippet', home)
    # The filings list's "engine unreachable" note. There were two: the
    # other belonged to the Tracker tab, which merged into the Track record.
    assert home.count('class="ideas-note" data-nosnippet') == 1


def test_a_company_s_own_page_never_talks_about_the_server():
    """
    On /stock-SYMBOL the figures are already in the page and a search engine
    runs the script. The wait must be a skeleton with no sentence, and a
    failure one quiet line (company-page-browser.cjs opens it for real).
    """
    js = _read("stock.js")
    assert "(SSR ? '' : '<p class=\"sk-note\"" in js, "the waking sentence is written on a company page"
    assert "if (SSR) {\n            liveOff(" in js
    assert '<div class="stk-live-off" data-nosnippet role="status">' in js
    assert '<div class="stk-loading" aria-busy="true" aria-label="Loading" data-nosnippet>' in js
    assert '<div class="stk-state" data-nosnippet>' in js
    off = js[js.index("function liveOff"):js.index("function liveOff") + 500]
    for word in ("engine", "wake", "thirty seconds", "unreachable"):
        assert word not in off.lower()


def test_the_planet_credit_is_shown_only_with_the_planets():
    css = _read("universe-scan.css")
    assert ".su-texture-credit{display:none" in css
    assert ".su-textured .su-texture-credit{display:block}" in css
    assert "if(renderer)host.classList.add('su-textured')" in _read("universe-voyage.js")
    scan = _read("universe-scan.js")
    assert "node('div','su-texture-credit')" in scan and "credit.setAttribute('data-nosnippet','')" in scan
    assert "Solar System Scope · CC BY 4.0" in scan, "the textures are CC BY: the credit must stay"
