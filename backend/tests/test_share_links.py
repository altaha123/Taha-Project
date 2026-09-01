"""
The share link must point somewhere the app understands.

This is a seam test, and it exists because the seam broke. /share/SYMBOL
shipped redirecting to ?ticker=SYMBOL — a parameter index.html has never
read. The card previewed perfectly, the crawler was satisfied, and every
human who clicked landed on an empty homepage.

Nothing in either half was wrong on its own, which is exactly why nothing
caught it. So the test reads the parameters the FRONTEND parses out of
index.html and asserts the backend only ever links with those.
"""
import os
import re

import pytest

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.dirname(BACKEND)
INDEX = os.path.join(REPO, "frontend", "index.html")
MAIN = os.path.join(BACKEND, "main.py")


FRONTEND = os.path.join(REPO, "frontend")


def _frontend_params():
    """
    Every query parameter the frontend reads via URLSearchParams.get().

    Scans the sibling modules as well as index.html. The chart deep link is
    parsed in charts.js, not in the page, and a test that only read the page
    would have called ?range= a dead parameter while it worked perfectly — the
    opposite of the failure this file exists to catch, and just as misleading.
    """
    found = set()
    files = [INDEX]
    if os.path.isdir(FRONTEND):
        files += [os.path.join(FRONTEND, f) for f in sorted(os.listdir(FRONTEND))
                  if f.endswith(".js")]
    for path in files:
        try:
            src = open(path, encoding="utf-8").read()
        except OSError:
            continue
        found |= set(re.findall(r'\.get\(\s*["\']([a-zA-Z_][\w-]*)["\']\s*\)', src))
    return found


def _share_target_urls():
    """Every SITE_URL link the share pages hand to a human, whole."""
    src = open(MAIN, encoding="utf-8").read()
    return re.findall(r'\{SITE_URL\}/\?(\S*?)"', src)


def _share_targets():
    """
    Every query parameter in every one of those links.

    BUGFIX: this used to capture only the FIRST parameter of each link, so
    /?q=SYM&go=charts&range=1D was checked for `q` and nothing else — and the
    two parameters that actually route the reader to the right tab and
    timeframe went unchecked. Multi-parameter links are now the common case,
    which is exactly when the old regex stopped covering anything.
    """
    out = []
    for url in _share_target_urls():
        out.extend(re.findall(r'(?:^|&)([a-zA-Z_][\w-]*)=', url))
    return out


def _js_views():
    """
    Views a frontend module builds at runtime rather than shipping as markup.

    The Charts tab is one: the workspace is an eval'd bundle that creates
    #view-charts and registers its own nav entry when it mounts, so nothing in
    index.html mentions it. A test that only reads the page would call
    ?go=charts a dead link — which it is not, and calling it dead is how a
    working feature gets "fixed" out of existence.
    """
    out = set()
    if not os.path.isdir(FRONTEND):
        return out
    for f in sorted(os.listdir(FRONTEND)):
        if not f.endswith(".js"):
            continue
        try:
            src = open(os.path.join(FRONTEND, f), encoding="utf-8").read()
        except OSError:
            continue
        out |= set(re.findall(r'\.id\s*=\s*\\?["\']view-([a-z]+)\\?["\']', src))
    return out


@pytest.mark.skipif(not os.path.exists(INDEX), reason="frontend not in this checkout")
def test_share_links_use_parameters_the_frontend_reads():
    params = _frontend_params()
    targets = _share_targets()
    assert targets, "no share targets found — did the links move?"
    for p in targets:
        assert p in params, (
            f"/share links to ?{p}= but index.html never reads it. "
            f"Parameters the frontend understands: {sorted(params)}")


@pytest.mark.skipif(not os.path.exists(INDEX), reason="frontend not in this checkout")
def test_the_tab_a_share_link_opens_exists():
    """?go=NAME resolves to an element with id tab-NAME, or it does nothing."""
    src = open(MAIN, encoding="utf-8").read()
    html = open(INDEX, encoding="utf-8").read()
    tabs = set(re.findall(r'id="tab-([a-z]+)"', html))
    # Not every tab is markup. The Charts tab is registered with the nav by
    # charts.js once its bundle mounts, so it has a #view- but no #tab-; the
    # deep-link handler falls back to AltahaNav.go() for exactly those. Both
    # routes are accepted, and a ?go= naming neither is still a dead link.
    views = set(re.findall(r'id="view-([a-z]+)"', html))
    views |= _js_views()
    for url in _share_target_urls():
        for tab in re.findall(r'(?:^|&)go=([a-z]+)', url):
            assert tab in tabs or tab in views, (
                f"share link opens ?go={tab} but there is neither #tab-{tab} "
                f"nor #view-{tab}")
