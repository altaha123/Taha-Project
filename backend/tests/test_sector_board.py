"""
The live sector board.

Two things are protected. The aggregation, because a sector average that is
wrong is wrong on the homepage; and the contract between the backend's icon
KEY and the frontend's icon DRAWING, because that is a seam — both halves can
be individually correct while a sector silently renders with no icon, and
nothing raises.
"""
import os
import re

import pytest

import sector_story as SS


ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BOARD_JS = os.path.join(ROOT, "frontend", "sectors-live.js")


QUOTES = {
    "TCS": {"change_pct": 2.0, "ltp": 3900.0, "volume": 1e6},
    "INFY": {"change_pct": -1.0, "ltp": 1500.0, "volume": 2e6},
    "HCLTECH": {"change_pct": 0.0, "ltp": 1400.0, "volume": 3e5},
}


@pytest.fixture
def one_sector(monkeypatch):
    """A universe of exactly one sector with three known constituents."""
    monkeypatch.setattr(SS, "CONSTITUENTS",
                        {"Technology": ["TCS", "INFY", "HCLTECH"]})
    monkeypatch.setattr(SS, "_returns",
                        lambda syms, sessions: (QUOTES, 0.5, "dhan", None))


def test_the_sector_figure_is_the_equal_weight_average(one_sector):
    row = SS.overview("1D")["rows"][0]
    assert row["change_pct"] == pytest.approx(round((2.0 - 1.0 + 0.0) / 3, 2))


def test_breadth_counts_split_three_ways(one_sector):
    """
    A sector can be green while most of it falls. The up/down/flat split is
    the only thing on the tile that says so, and a flat name counted as up
    would quietly overstate it.
    """
    row = SS.overview("1D")["rows"][0]
    assert (row["up"], row["down"], row["flat"], row["total"]) == (1, 1, 1, 3)


def test_constituents_are_withheld_unless_asked_for(one_sector):
    assert "stocks" not in SS.overview("1D")["rows"][0]


def test_constituents_come_back_sorted_best_to_worst(one_sector):
    row = SS.overview("1D", with_stocks=True)["rows"][0]
    assert [s["symbol"] for s in row["stocks"]] == ["TCS", "HCLTECH", "INFY"]
    assert row["leader"]["symbol"] == "TCS"
    assert row["laggard"]["symbol"] == "INFY"
    # The price is what makes the panel readable; it must survive the trip.
    assert row["stocks"][0]["ltp"] == 3900.0


def test_a_constituent_with_no_quote_is_omitted_not_zeroed(monkeypatch):
    """A missing quote scored as 0% would drag the sector average toward zero
    and be counted as a flat stock that does not exist."""
    monkeypatch.setattr(SS, "CONSTITUENTS", {"Technology": ["TCS", "GONE"]})
    monkeypatch.setattr(SS, "_returns",
                        lambda s, n: ({"TCS": QUOTES["TCS"]}, 0.0, "dhan", None))
    row = SS.overview("1D", with_stocks=True)["rows"][0]
    assert row["total"] == 1
    assert [s["symbol"] for s in row["stocks"]] == ["TCS"]


def test_every_sector_carries_an_icon_key(one_sector):
    assert SS.overview("1D")["rows"][0]["icon"] == "chip"


def test_the_icon_map_covers_every_sector_that_has_constituents():
    missing = [s for s in SS.CONSTITUENTS if s not in SS.SECTOR_ICON]
    assert not missing, f"sectors with no icon key: {missing}"


def test_rows_are_ranked_by_strength_against_the_benchmark(monkeypatch):
    monkeypatch.setattr(SS, "CONSTITUENTS", {"Technology": ["A"], "Energy": ["B"],
                                             "Healthcare": ["C"]})
    monkeypatch.setattr(SS, "_returns", lambda s, n: (
        {"A": {"change_pct": -1.0}, "B": {"change_pct": 3.0},
         "C": {"change_pct": 1.0}}, 0.0, "dhan", None))
    rows = SS.overview("1D")["rows"]
    assert [r["sector"] for r in rows] == ["Energy", "Healthcare", "Technology"]


# ---------------------------------------------------------------------------
# The seam
# ---------------------------------------------------------------------------

def _frontend_icons():
    """Icon names the board can actually draw."""
    src = open(BOARD_JS, encoding="utf-8").read()
    block = re.search(r"var ICONS = \{(.*?)\n  \};", src, re.S)
    assert block, "the ICONS registry moved — this test cannot see it any more"
    return set(re.findall(r"^\s{4}([a-z]+):", block.group(1), re.M))


@pytest.mark.skipif(not os.path.exists(BOARD_JS), reason="frontend not in this checkout")
def test_every_icon_key_the_backend_sends_can_be_drawn():
    """
    The seam. The backend sends a key; the frontend owns the drawing. Both
    halves can be perfectly correct while a sector renders with a blank space
    where its icon should be, and nothing anywhere raises — which is precisely
    how this project's worst bugs have always looked.
    """
    drawable = _frontend_icons()
    assert drawable, "no icons found in the frontend registry"
    unknown = sorted(set(SS.SECTOR_ICON.values()) - drawable)
    assert not unknown, (
        f"the backend sends icon keys the board cannot draw: {unknown}. "
        f"It knows how to draw: {sorted(drawable)}")


@pytest.mark.skipif(not os.path.exists(BOARD_JS), reason="frontend not in this checkout")
def test_there_is_a_fallback_icon_for_an_unknown_sector():
    """A sector added to the backend before its icon exists must render a mark,
    not a hole."""
    assert "dot" in _frontend_icons()
    src = open(BOARD_JS, encoding="utf-8").read()
    assert "ICONS.dot" in src, "no fallback when the key is unknown"


@pytest.mark.skipif(not os.path.exists(BOARD_JS), reason="frontend not in this checkout")
def test_the_board_owns_every_class_it_styles():
    """
    The collision guard, scoped to this component.

    The board first shipped using `.secgrid`, which index.html's inline styles
    already defined for the Sectors tab — two columns, no gap. Both stylesheets
    were correct, the inline one won because it is parsed later, and the
    homepage grid silently rendered at 2 columns instead of 5. That is the
    third name collision in this project after `.tk` twice.

    A repo-wide rule would be wrong here: altaha-polish.css and altaha-skin.css
    are deliberate override layers whose whole job is to restyle classes
    defined elsewhere. So the rule is scoped to this component instead — every
    class the board defines as a selector of its own must be defined nowhere
    else.
    """
    css_dir = os.path.join(ROOT, "frontend")
    board_css = os.path.join(css_dir, "sectors-live.css")
    if not os.path.exists(board_css):
        pytest.skip("board stylesheet not in this checkout")

    def solo(css):
        css = re.sub(r"@keyframes[^{]*\{(?:[^{}]|\{[^{}]*\})*\}", "", css)
        css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
        out = set()
        for block in re.findall(r"([^{}]+)\{", css):
            for sel in block.split(","):
                m = re.fullmatch(r"\.(-?[_a-zA-Z][\w-]*)", sel.strip())
                if m:
                    out.add(m.group(1))
        return out

    mine = solo(open(board_css, encoding="utf-8").read())
    assert mine, "the board defines no classes — did the stylesheet move?"

    # Shared modifier words are shared on purpose and are always used compound.
    mine -= {"up", "dn", "on", "open", "flat"}

    html = open(os.path.join(ROOT, "frontend", "index.html"), encoding="utf-8").read()
    others = solo("\n".join(re.findall(r"<style[^>]*>(.*?)</style>", html, re.S)))
    for name in sorted(os.listdir(css_dir)):
        if name.endswith(".css") and name != "sectors-live.css":
            others |= solo(open(os.path.join(css_dir, name), encoding="utf-8").read())

    clash = sorted(mine & others)
    assert not clash, (
        f"the sector board claims class names something else already owns: "
        f"{clash}. Whichever stylesheet parses later wins, silently.")
