"""
Peer percentiles for the stock page's header grid.

The header grid prints nine public figures — the same nine every screener
prints, because they are the ones a reader checks first. What makes the page
ours rather than a copy of somebody's ratio table is the line under each one
saying where it sits among its sector, and that line is only worth printing if
it runs the right way round.

The trap is orientation. A P/E in the 90th percentile of its sector is the
EXPENSIVE end and a ROCE in the 90th is the profitable one; a debt/equity in
the 90th is the *least* indebted, because the good end of leverage is the
bottom. Reporting "90th percentile" for all three without saying which
direction was measured would be worse than reporting nothing, and an inversion
here is invisible — the bar still fills, the sentence still reads, and the
number is simply backwards. Hence a test per direction.
"""
import pytest


@pytest.fixture(scope="module")
def main_mod():
    import main
    return main


@pytest.fixture(autouse=True)
def _restore_scan_state(main_mod):
    """`_state` is module-global and shared with every other test in the run.

    These tests install a synthetic universe into it; without this they would
    leave whichever cohort they wrote last in place for the rest of the
    session, and the failure that eventually caused would surface in an
    unrelated file.
    """
    before = main_mod._state.get("payload")
    yield
    main_mod._state["payload"] = before


def _universe(values, field, sector="Specialty Chemicals"):
    """A scanned cohort carrying one banked figure per name."""
    return [{"symbol": f"PEER{i}", "sector": sector, "grid_ratios": {field: v}}
            for i, v in enumerate(values)]


def _install(main_mod, rows):
    main_mod._state["payload"] = {"factor_universe": rows}


def test_a_higher_is_better_figure_counts_the_peers_it_beats(main_mod):
    # Twelve peers, ten of them below 14.8.
    _install(main_mod, _universe([2, 4, 6, 8, 10, 11, 12, 13, 14, 14.5, 20, 30], "roce"))
    out = main_mod._peer_context("TEST.NS", "Specialty Chemicals", {"roce": 14.8})
    assert out["roce"]["percentile"] == round(100 * 10 / 12)
    assert out["roce"]["phrase"].startswith("higher than")
    assert out["roce"]["peers"] == 12
    assert out["roce"]["group"] == "Specialty Chemicals peers"


def test_a_cheap_price_earnings_ratio_is_the_top_of_the_distribution(main_mod):
    # A P/E of 8 against peers that are mostly dearer is a GOOD percentile, and
    # the sentence has to say "cheaper", not "lower".
    _install(main_mod, _universe([10, 12, 14, 16, 18, 20, 22, 24, 26, 28, 30, 6], "pe"))
    out = main_mod._peer_context("TEST.NS", "Specialty Chemicals", {"pe": 8.0})
    assert out["pe"]["percentile"] == round(100 * 11 / 12)
    assert out["pe"]["phrase"].startswith("cheaper than")


def test_an_expensive_multiple_reads_as_dearer_not_as_a_low_score(main_mod):
    _install(main_mod, _universe([4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15], "pe"))
    out = main_mod._peer_context("TEST.NS", "Specialty Chemicals", {"pe": 40.0})
    assert out["pe"]["percentile"] == 0
    assert out["pe"]["phrase"] == "dearer than 100%"


def test_low_leverage_is_the_good_end_of_debt_to_equity(main_mod):
    _install(main_mod, _universe([0.5, 0.6, 0.8, 1.0, 1.2, 1.4, 1.6, 2.0, 2.2, 2.4, 3.0, 0.05], "de"))
    out = main_mod._peer_context("TEST.NS", "Specialty Chemicals", {"debt_to_equity": 0.15})
    assert out["debt_to_equity"]["percentile"] == round(100 * 11 / 12)
    assert out["debt_to_equity"]["phrase"].startswith("less debt than")


def test_a_rupee_amount_gets_no_percentile(main_mod):
    # Book value per share is not comparable between two companies: it depends
    # on how many shares they happened to issue. A percentile on it would be
    # arithmetic that means nothing.
    _install(main_mod, _universe([100, 200, 300, 400, 500, 600, 700, 800, 900, 1000, 1100, 1200],
                                 "book_value"))
    out = main_mod._peer_context("TEST.NS", "Specialty Chemicals", {"book_value": 625.4})
    assert "book_value" not in out


def test_a_thin_sector_falls_back_to_the_whole_cohort_and_says_so(main_mod):
    # Three sector peers is not a distribution. The figure is still placed, but
    # against every scanned name, and the caption has to name that group so the
    # reader is not told "68th percentile" and left to assume it was sector.
    rows = _universe([5, 6, 7], "roce", sector="Tiny Sector")
    rows += _universe([1, 2, 3, 4, 8, 9, 10, 11, 12, 13, 14, 15], "roce", sector="Something Else")
    _install(main_mod, rows)
    out = main_mod._peer_context("TEST.NS", "Tiny Sector", {"roce": 14.8})
    assert out["roce"]["group"] == "scanned names"
    assert out["roce"]["peers"] == 15


def test_too_few_peers_anywhere_reports_nothing_rather_than_a_number(main_mod):
    _install(main_mod, _universe([5, 6, 7], "roce"))
    assert main_mod._peer_context("TEST.NS", "Specialty Chemicals", {"roce": 14.8}) == {}


def test_the_stock_itself_is_never_one_of_its_own_peers(main_mod):
    rows = _universe([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12], "roce")
    rows[0]["symbol"] = "TEST"
    _install(main_mod, rows)
    out = main_mod._peer_context("TEST.NS", "Specialty Chemicals", {"roce": 14.8})
    assert out["roce"]["peers"] == 11


def test_no_scan_yet_is_an_empty_block_not_a_crash(main_mod):
    _install(main_mod, [])
    assert main_mod._peer_context("TEST.NS", "Specialty Chemicals", {"roce": 14.8}) == {}


def test_unusable_peer_values_are_dropped_not_counted(main_mod):
    rows = _universe([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12], "roce")
    rows += [{"symbol": "BAD1", "sector": "Specialty Chemicals", "grid_ratios": {"roce": None}},
             {"symbol": "BAD2", "sector": "Specialty Chemicals", "grid_ratios": {"roce": "n/a"}},
             {"symbol": "BAD3", "sector": "Specialty Chemicals", "grid_ratios": {}},
             {"symbol": "BAD4", "sector": "Specialty Chemicals"}]
    _install(main_mod, rows)
    out = main_mod._peer_context("TEST.NS", "Specialty Chemicals", {"roce": 14.8})
    assert out["roce"]["peers"] == 12


def test_a_missing_figure_on_this_stock_is_simply_absent(main_mod):
    _install(main_mod, _universe([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12], "roce"))
    out = main_mod._peer_context("TEST.NS", "Specialty Chemicals", {"roce": None, "pe": None})
    assert out == {}
