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


def _frontend_params():
    """Every query parameter index.html reads via URLSearchParams.get()."""
    html = open(INDEX, encoding="utf-8").read()
    return set(re.findall(r'\.get\(\s*["\']([a-zA-Z_][\w-]*)["\']\s*\)', html))


def _share_targets():
    """Every SITE_URL link the share pages hand to a human."""
    src = open(MAIN, encoding="utf-8").read()
    return re.findall(r'\{SITE_URL\}/\?([a-zA-Z_][\w-]*)=', src)


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
    for tab in re.findall(r'\{SITE_URL\}/\?go=([a-z]+)', src):
        assert tab in tabs, f"share link opens ?go={tab} but there is no #tab-{tab}"
