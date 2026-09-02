"""
Bulk, block and short deals.

The fetching is the easy half. What is protected here is the arithmetic that
makes the feed worth showing at all: netting buys against sells, spotting the
same counterparty on both sides, and separating proprietary desks from people
who actually built a position.

Printed raw, these rows mislead in exactly those three ways, and every finance
site in India prints them raw.
"""
import pytest

import deals as D


def _r(symbol, client, side, qty, price, kind="bulk", date="01-Sep-2026", name="Co"):
    return D._row(symbol, name, client, side, qty, price, date, kind)


# ---------------------------------------------------------------------------
# Normalising
# ---------------------------------------------------------------------------

def test_value_is_computed_and_reported_in_crore():
    r = _r("ACME", "Somebody", "BUY", 1_000_000, 250.0)
    assert r["value"] == 250_000_000
    assert r["value_cr"] == 25.0


def test_quantities_with_commas_survive():
    assert _r("ACME", "X", "BUY", "1,00,000", "12.50")["value"] == 1_250_000


def test_a_row_with_no_price_does_not_invent_a_value():
    r = _r("ACME", "X", "BUY", 1000, None)
    assert r["value"] is None and r["value_cr"] is None


def test_client_names_are_normalised_for_matching():
    """The same client appears with different spacing across rows; without
    normalising, a round trip looks like two different people."""
    a = _r("ACME", "  hrti   private  limited ", "BUY", 1, 1)
    b = _r("ACME", "HRTI PRIVATE LIMITED", "SELL", 1, 1)
    assert a["client"] == b["client"] == "HRTI PRIVATE LIMITED"


def test_proprietary_desks_are_recognised():
    assert D.is_prop_desk("HRTI PRIVATE LIMITED")
    assert D.is_prop_desk("Graviton Research Capital LLP")
    assert not D.is_prop_desk("LIFE INSURANCE CORPORATION OF INDIA")


def test_an_unknown_counterparty_is_treated_as_real():
    """Wrongly dismissing a genuine buyer is the more expensive mistake, so the
    prop list is conservative and anything unmatched counts."""
    assert not D.is_prop_desk("SOME NEW FUND LLP")


# ---------------------------------------------------------------------------
# The netting — the reason this module exists
# ---------------------------------------------------------------------------

def test_buys_and_sells_are_netted():
    """
    A stock with a ₹40cr buy and a ₹39cr sell did not see ₹40cr of demand.
    Reporting the buy side alone is the single most common way these rows are
    misread.
    """
    rows = [_r("ACME", "BUYER LLP", "BUY", 4_000_000, 100.0),
            _r("ACME", "SELLER LLP", "SELL", 3_900_000, 100.0)]
    out = D.net_by_symbol(rows)[0]
    assert out["buy_cr"] == 40.0
    assert out["sell_cr"] == 39.0
    assert out["net_cr"] == 1.0
    assert out["gross_cr"] == 79.0


def test_a_round_trip_is_marked_as_crossing_not_accumulation():
    """
    The same client on both sides ending flat opened and closed a position, or
    crossed stock between accounts. Counting the buy as conviction is wrong.
    """
    rows = [_r("ACME", "SAME PARTY LLP", "BUY", 1_000_000, 100.0),
            _r("ACME", "SAME PARTY LLP", "SELL", 1_000_000, 100.0)]
    out = D.net_by_symbol(rows)[0]
    assert out["crossed"] is True
    assert out["crossing_clients"] == ["SAME PARTY LLP"]
    assert out["top_buyers"] == [] and out["top_sellers"] == []
    assert "nobody built a position" in out["reading"]


def test_a_client_who_ends_meaningfully_long_is_not_a_crosser():
    """Buying ten and selling one is accumulation with some noise in it, not a
    cross — the threshold has to distinguish them."""
    rows = [_r("ACME", "REAL BUYER LLP", "BUY", 10_000_000, 100.0),
            _r("ACME", "REAL BUYER LLP", "SELL", 500_000, 100.0)]
    out = D.net_by_symbol(rows)[0]
    assert out["crossed"] is False
    assert out["top_buyers"][0]["client"] == "REAL BUYER LLP"


def test_proprietary_flow_is_separated_from_accumulation():
    """
    A market maker's inventory is not a view. Leaving it in the buy total is
    how a liquidity print gets read as institutional conviction.
    """
    rows = [_r("ACME", "HRTI PRIVATE LIMITED", "BUY", 5_000_000, 100.0),
            _r("ACME", "A REAL FUND LLP", "BUY", 1_000_000, 100.0)]
    out = D.net_by_symbol(rows)[0]
    assert out["prop_cr"] == 50.0
    assert out["buy_cr"] == 10.0, "prop flow leaked into the accumulation total"
    assert [b["client"] for b in out["top_buyers"]] == ["A REAL FUND LLP"]


def test_a_stock_that_is_only_proprietary_flow_says_so():
    rows = [_r("ACME", "HRTI PRIVATE LIMITED", "BUY", 5_000_000, 100.0),
            _r("ACME", "GRAVITON RESEARCH CAPITAL LLP", "SELL", 5_000_000, 100.0)]
    out = D.net_by_symbol(rows)[0]
    assert "market making" in out["reading"]
    assert out["buy_cr"] == 0.0 and out["sell_cr"] == 0.0


def test_short_disclosures_are_excluded_from_accumulation():
    """A short-sell disclosure is not somebody buying or selling a position in
    the sense this aggregate measures."""
    rows = [_r("ACME", "X LLP", "SELL", 1_000_000, 100.0, kind="short")]
    assert D.net_by_symbol(rows) == []


def test_a_block_deal_is_labelled_as_negotiated():
    rows = [_r("ACME", "BIG FUND LLP", "BUY", 1_000_000, 1000.0, kind="block")]
    out = D.net_by_symbol(rows)[0]
    assert out["block"] is True
    assert "negotiated block" in out["reading"]


def test_small_stocks_can_be_filtered_out_by_value():
    rows = [_r("BIG", "F LLP", "BUY", 1_000_000, 1000.0),
            _r("TINY", "G LLP", "BUY", 100, 10.0)]
    syms = [r["symbol"] for r in D.net_by_symbol(rows, min_value_cr=1.0)]
    assert syms == ["BIG"]


def test_symbols_are_ranked_by_how_much_actually_moved():
    rows = [_r("SMALL", "A LLP", "BUY", 100_000, 100.0),
            _r("BIG", "B LLP", "SELL", 10_000_000, 100.0)]
    assert [r["symbol"] for r in D.net_by_symbol(rows)] == ["BIG", "SMALL"]


def test_netting_never_raises_on_junk():
    for bad in (None, [], [{}], [{"symbol": None}],
                [_r("A", "X", "BUY", None, None)]):
        D.net_by_symbol(bad)


# ---------------------------------------------------------------------------
# The board
# ---------------------------------------------------------------------------

@pytest.fixture
def offline(monkeypatch):
    monkeypatch.setattr(D, "_api", lambda *a, **k: None)
    D._cache.clear()


def test_a_dead_feed_explains_itself_rather_than_erroring(offline):
    out = D.board()
    assert out["available"] is False
    assert "after the close" in out["message"]


def test_the_board_always_carries_its_timing_and_its_caveat(monkeypatch):
    D._cache.clear()
    monkeypatch.setattr(D, "_api", lambda *a, **k: {
        "as_on_date": "01-Sep-2026", "BULK_DEALS": 1, "BLOCK_DEALS": 0, "SHORT_DEALS": 0,
        "BULK_DEALS_DATA": [{"symbol": "ACME", "name": "Acme", "clientName": "A FUND LLP",
                             "buySell": "BUY", "qty": "1000000", "watp": "100",
                             "date": "01-Sep-2026", "remarks": "-"}],
        "BLOCK_DEALS_DATA": [], "SHORT_DEALS_DATA": []})
    out = D.board(min_value_cr=0.0)
    assert out["available"] is True
    assert out["as_on"] == "01-Sep-2026"
    assert out["symbols"][0]["symbol"] == "ACME"
    # The honesty about what "live" means has to survive to the API.
    assert "not a live trade feed" in out["timing"]
    assert "who traded, not whether they were right" in out["caveat"]
    D._cache.clear()


def test_the_feed_is_cached_rather_than_refetched_per_request(monkeypatch):
    D._cache.clear()
    calls = {"n": 0}

    def once(*a, **k):
        calls["n"] += 1
        return {"as_on_date": "01-Sep-2026", "BULK_DEALS_DATA": [],
                "BLOCK_DEALS_DATA": [], "SHORT_DEALS_DATA": [],
                "BULK_DEALS": 0, "BLOCK_DEALS": 0, "SHORT_DEALS": 0}

    monkeypatch.setattr(D, "_api", once)
    D.today(); D.today(); D.today()
    assert calls["n"] == 1, "NSE was hit once per request instead of once per window"
    D._cache.clear()


# ---------------------------------------------------------------------------
# The collision guard
# ---------------------------------------------------------------------------

import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CSS_DIR = os.path.join(ROOT, "frontend")


def _solo_classes(css):
    """Classes defined as a whole selector of their own — `.foo{...}`.

    A modifier used compound (`.dl-net.up`) shares a name on purpose. Only a
    bare `.foo` claims the name outright, and that is the collision that
    silently reskins somebody else's component.
    """
    css = re.sub(r"@keyframes[^{]*\{(?:[^{}]|\{[^{}]*\})*\}", "", css)
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    out = set()
    for block in re.findall(r"([^{}]+)\{", css):
        for sel in block.split(","):
            m = re.fullmatch(r"\.(-?[_a-zA-Z][\w-]*)", sel.strip())
            if m:
                out.add(m.group(1))
    return out


@pytest.mark.skipif(not os.path.isdir(CSS_DIR), reason="frontend not in this checkout")
def test_the_deals_module_owns_every_class_it_styles():
    """
    Three name collisions in this project so far — `.tk` twice and `.secgrid`
    once — and every time both stylesheets were individually correct, the one
    parsed later silently won, and the result looked like a layout mystery
    rather than a name clash.

    Scoped to this module on purpose: altaha-polish.css and altaha-skin.css are
    deliberate override layers whose whole job is restyling classes defined
    elsewhere, so a repo-wide rule would be wrong and would be switched off
    within a day.
    """
    mine_path = os.path.join(CSS_DIR, "deals.css")
    if not os.path.exists(mine_path):
        pytest.skip("deals stylesheet not in this checkout")
    mine = _solo_classes(open(mine_path, encoding="utf-8").read())
    assert mine, "the module defines no classes — did the stylesheet move?"
    mine -= {"up", "dn", "on", "open", "flat"}

    html = open(os.path.join(CSS_DIR, "index.html"), encoding="utf-8").read()
    others = _solo_classes("\n".join(re.findall(r"<style[^>]*>(.*?)</style>", html, re.S)))
    for name in sorted(os.listdir(CSS_DIR)):
        if name.endswith(".css") and name != "deals.css":
            others |= _solo_classes(open(os.path.join(CSS_DIR, name), encoding="utf-8").read())

    clash = sorted(mine & others)
    assert not clash, (
        f"the deals module claims class names something else already owns: "
        f"{clash}. Whichever stylesheet parses later wins, silently.")
