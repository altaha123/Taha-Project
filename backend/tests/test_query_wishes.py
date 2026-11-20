"""
The screener's cards write query language (frontend/query.js, WISHES).

A reader taps "Makes good money" and the page runs `ROE > 12`. Those lines
are written in a JavaScript file and read by fundamentals_query's parser, and
nothing ties the two together: rename a field here and every card that uses
it comes back as "is not a field" to somebody who never typed anything.

So every line every card can write is put through the real parser, and every
ready-made idea is checked to switch on cards and settings that exist.
"""

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import fundamentals_query as Q  # noqa: E402

SRC = open(os.path.join(HERE, "..", "..", "frontend", "query.js"), encoding="utf-8").read()
WISHES = SRC[SRC.index("var WISHES = ["):SRC.index("var RECIPES = [")]
RECIPES = SRC[SRC.index("var RECIPES = ["):SRC.index("var pick = [];")]


def wishes():
    """{id: [[line, ...] per setting]} as the page declares them."""
    out = {}
    for block in re.split(r"\n    \{ id: '", WISHES)[1:]:
        wid = block[:block.index("'")]
        out[wid] = [re.findall(r"'([^']+)'", q) for q in re.findall(r"q: \[([^\]]+)\]", block)]
    return out


def test_the_cards_are_all_found():
    w = wishes()
    assert len(w) >= 8, "the cards could not be read out of query.js: %r" % sorted(w)
    for wid, levels in w.items():
        assert 1 <= len(levels) <= 3, "%s has %d settings" % (wid, len(levels))
        assert all(levels), "%s has a setting that writes nothing" % wid


def test_every_line_a_card_writes_is_a_query_the_server_reads():
    for wid, levels in wishes().items():
        for lines in levels:
            for line in lines:
                Q.parse(line)                       # raises on a field the server does not have
            Q.parse("\n".join(lines))


def test_every_choice_together_is_still_one_query():
    """The strictest setting of every card at once is the longest thing the page can write."""
    q = "\n".join(line for levels in wishes().values() for line in levels[-1])
    assert len(q) <= Q.MAX_QUERY_CHARS, "every card switched on is longer than the server accepts"
    Q.parse(q)


def test_ready_made_ideas_switch_on_cards_that_exist():
    w = wishes()
    sets = re.findall(r"set: \[(.*?)\] \}", RECIPES)
    assert len(sets) >= 4, "the ready-made ideas could not be read out of query.js"
    for s in sets:
        pairs = re.findall(r"\['([a-z]+)', (\d)\]", s)
        assert pairs, "a ready-made idea switches nothing on: %r" % s
        for wid, level in pairs:
            assert wid in w, "a ready-made idea names a card that is not there: %s" % wid
            assert int(level) < len(w[wid]), "%s has no setting %s" % (wid, level)
