"""
The investor table and the portfolios built from it.

What is actually being guarded: this feature makes public, attributed claims
about what named private individuals own. The tests that matter are the ones
that stop it overstating a position, inventing one, or quietly folding
somebody else's shares into a person's total.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture()
def mods(tmp_path, monkeypatch):
    monkeypatch.setenv("ALTAHA_HOLDINGS_DB", str(tmp_path / "h.db"))
    for m in ("holdings_store", "investors"):
        sys.modules.pop(m, None)
    import holdings_store as store
    import investors as inv
    return store, inv


def _name(n, pct, shares=None, promoter=False):
    return {"name": n, "pct": pct, "shares": shares, "kind": "Other",
            "promoter": promoter}


# ---------------------------------------------------------------------------
# The table itself
# ---------------------------------------------------------------------------

def test_every_investor_is_well_formed(mods):
    _store, inv = mods
    ids = set()
    for i in inv.INVESTORS:
        assert i["id"] and i["id"] not in ids, "ids must be unique"
        ids.add(i["id"])
        assert i["id"] == i["id"].lower().strip()
        assert i["name"] and i.get("about")
        if i.get("kind") == "redirect":
            assert i.get("redirect_to") in ids or any(
                x["id"] == i["redirect_to"] for x in inv.INVESTORS)
            continue
        assert i["entities"], "%s has no aliases" % i["id"]
        for e in i["entities"]:
            assert e["relation"] in inv.RELATION_WORDS, \
                "%s: unknown relation %r" % (i["id"], e["relation"])
            assert e["alias"].strip() == e["alias"]


def test_no_alias_is_claimed_by_two_investors(mods):
    """An alias in two tables means one person's position is credited to
    somebody else as well."""
    store, inv = mods
    owner = {}
    for i in inv.INVESTORS:
        for e in i.get("entities") or []:
            k = store.holder_key(e["alias"])
            assert k not in owner, \
                "%r is claimed by both %s and %s" % (e["alias"], owner.get(k), i["id"])
            owner[k] = i["id"]


def test_no_alias_normalises_to_a_category_heading(mods):
    """An alias of "Mutual Funds" would hand an investor every fund position
    in the market."""
    store, inv = mods
    for i in inv.INVESTORS:
        for e in i.get("entities") or []:
            assert store.is_real_holder(e["alias"]), \
                "%s: %r is a category, not a holder" % (i["id"], e["alias"])


def test_a_dead_investor_redirects_rather_than_having_a_page(mods):
    """Rakesh Jhunjhunwala died in August 2022. A 2026 page headed with his
    name showing current holdings would simply be false."""
    _store, inv = mods
    target, redirected = inv.resolve("rakesh-jhunjhunwala")
    assert redirected is not None
    assert target["id"] == "rekha-jhunjhunwala"
    assert "2022" in redirected["about"]
    assert "rakesh-jhunjhunwala" not in {r["id"] for r in inv.listing()}


def test_an_unknown_id_is_answered_not_raised(mods):
    _store, inv = mods
    d = inv.portfolio("no-such-person")
    assert d["available"] is False and d["message"]


# ---------------------------------------------------------------------------
# Rolling up
# ---------------------------------------------------------------------------

def _atulauto(store):
    store.record_filing("ATULAUTO", "2026-06-30", [
        _name("VIJAY KEDIA", 18.20),
        _name("KEDIA SECURITIES PRIVATE LIMITED", 2.71),
    ], source_url="https://nsearchives.nseindia.com/x")


def test_a_person_and_their_company_are_added_and_the_parts_are_kept(mods):
    """The rolled-up total is what "Vijay Kedia's stake in Atul Auto" means.
    Showing it without its components would make it an assertion; the
    components are what make it evidence."""
    store, inv = mods
    _atulauto(store)
    d = inv.portfolio("vijay-kedia")
    pos = next(p for p in d["positions"] if p["symbol"] == "ATULAUTO")
    assert pos["pct"] == pytest.approx(20.91)
    assert pos["split"] is True
    assert {p["relation"] for p in pos["parts"]} == {"self", "entity"}
    assert sorted(p["pct"] for p in pos["parts"]) == [2.71, 18.20]


def test_two_folios_of_one_name_are_summed(mods):
    store, inv = mods
    store.record_filing("TITAN", "2026-03-31", [
        _name("Rekha Jhunjhunwala", 4.24), _name("Rekha Jhunjhunwala", 1.07)])
    d = inv.portfolio("rekha-jhunjhunwala")
    pos = next(p for p in d["positions"] if p["symbol"] == "TITAN")
    assert pos["pct"] == pytest.approx(5.31)
    assert len(pos["parts"]) == 2


def test_a_trust_is_counted_but_labelled_never_folded_in_silently(mods):
    """A discretionary trust someone is trustee of is not shares they own
    outright. It is included because that is what readers mean, and it is
    marked on the position and in the notes because it is a judgement."""
    store, inv = mods
    store.record_filing("METROBRAND", "2026-06-30", [
        _name("ARYAMAN JHUNJHUNWALA DISCRETIONARY TRUST (TRUSTEE - REKHA RAKESH JHUNJHUNWALA)", 4.79),
        _name("ARYAVIR JHUNJHUNWALA DISCRETIONARY TRUST (TRUSTEE - REKHA RAKESH JHUNJHUNWALA)", 4.79),
        _name("NISHTHA JHUNJHUNWALA DISCRETIONARY TRUST (TRUSTEE - REKHA RAKESH JHUNJHUNWALA)", 4.79),
    ])
    d = inv.portfolio("rekha-jhunjhunwala")
    pos = next(p for p in d["positions"] if p["symbol"] == "METROBRAND")
    assert pos["pct"] == pytest.approx(14.37)
    assert all(p["relation"] == "trust" for p in pos["parts"])
    assert any("trust" in n.lower() for n in d["notes"])


def test_a_joint_holding_is_shown_beside_the_total_not_inside_it(mods):
    """A stake filed in two people's names does not say how it divides.
    Crediting all of it to one of them is a claim the document never makes."""
    store, inv = mods
    inv.INVESTORS.append({
        "id": "test-joint", "name": "Test Person", "kind": "individual",
        "about": "fixture",
        "entities": [
            {"alias": "Test Person", "relation": "self"},
            {"alias": "Test Person And Someone Else", "relation": "joint"},
        ]})
    try:
        store.record_filing("X", "2026-06-30", [
            _name("Test Person", 3.0),
            _name("Test Person And Someone Else", 9.0)])
        d = inv.portfolio("test-joint")
        pos = next(p for p in d["positions"] if p["symbol"] == "X")
        assert pos["pct"] == pytest.approx(3.0), "the joint stake must not be added"
        assert len(pos["beside"]) == 1
        assert pos["beside"][0]["relation"] == "joint"
    finally:
        inv.INVESTORS[:] = [i for i in inv.INVESTORS if i["id"] != "test-joint"]


def test_a_promoter_stake_is_flagged_as_the_investors_own_company(mods):
    """Damani's 23% of Avenue Supermarts is the biggest line in his register
    and it is not a stock pick."""
    store, inv = mods
    store.record_filing("DMART", "2026-06-30", [
        _name("Radhakishan Shivkishan Damani", 22.97, promoter=True)])
    d = inv.portfolio("radhakishan-damani")
    pos = next(p for p in d["positions"] if p["symbol"] == "DMART")
    assert pos["promoter"] is True
    assert any("promoter" in n.lower() for n in d["notes"])


def test_an_unrelated_holder_never_enters_a_portfolio(mods):
    store, inv = mods
    store.record_filing("X", "2026-06-30", [
        _name("Vijay Kumar Sharma", 5.0),      # not Vijay Kedia
        _name("Kedia Textiles Private Limited", 4.0),   # not Kedia Securities
    ])
    d = inv.portfolio("vijay-kedia")
    assert d["available"] is False, "no position should have been found at all"


# ---------------------------------------------------------------------------
# Movement between quarters
# ---------------------------------------------------------------------------

def test_added_trimmed_held_and_new_are_told_apart(mods):
    store, inv = mods
    store.record_filing("A", "2026-03-31", [_name("VIJAY KEDIA", 5.0)])
    store.record_filing("B", "2026-03-31", [_name("VIJAY KEDIA", 5.0)])
    store.record_filing("C", "2026-03-31", [_name("VIJAY KEDIA", 5.0)])
    store.record_filing("A", "2026-06-30", [_name("VIJAY KEDIA", 6.0)])
    store.record_filing("B", "2026-06-30", [_name("VIJAY KEDIA", 4.0)])
    store.record_filing("C", "2026-06-30", [_name("VIJAY KEDIA", 5.0)])
    store.record_filing("D", "2026-06-30", [_name("VIJAY KEDIA", 2.0)])
    d = inv.portfolio("vijay-kedia")
    kinds = {p["symbol"]: p["change"]["kind"] for p in d["positions"]}
    assert kinds == {"A": "added", "B": "trimmed", "C": "held", "D": "new"}
    assert next(p for p in d["positions"] if p["symbol"] == "A")["change"]["delta"] \
        == pytest.approx(1.0)


def test_a_company_that_drops_out_is_not_called_a_sale(mods):
    """Below 1% the filing simply stops naming a holder. Calling that an exit
    is a claim the document does not make — the investor may hold 0.99% still."""
    store, inv = mods
    store.record_filing("GONE", "2026-03-31", [_name("VIJAY KEDIA", 3.0)])
    store.record_filing("KEPT", "2026-03-31", [_name("VIJAY KEDIA", 3.0)])
    store.record_filing("KEPT", "2026-06-30", [_name("VIJAY KEDIA", 3.0)])
    d = inv.portfolio("vijay-kedia")
    assert [x["symbol"] for x in d["no_longer_disclosed"]] == ["GONE"]
    assert all("sold" not in str(x).lower() for x in d["no_longer_disclosed"])
    assert any("does not say which" in n for n in d["notes"])


def test_the_first_quarter_on_record_has_nothing_to_compare_with(mods):
    store, inv = mods
    store.record_filing("A", "2026-06-30", [_name("VIJAY KEDIA", 5.0)])
    d = inv.portfolio("vijay-kedia")
    assert d["compared_with"] is None
    assert d["positions"][0]["change"]["kind"] == "unknown"


def test_the_disclosure_floor_and_the_lag_are_always_stated(mods):
    """Not only when they bite. A reader who takes this for a live portfolio
    has been misled even if every figure on it is right."""
    store, inv = mods
    _atulauto(store)
    d = inv.portfolio("vijay-kedia")
    joined = " ".join(d["notes"]).lower()
    assert "1%" in joined
    assert "quarter" in joined and "21 days" in joined


def test_an_investor_with_nothing_recorded_says_so_plainly(mods):
    _store, inv = mods
    d = inv.portfolio("dolly-khanna")
    assert d["available"] is False
    assert "Dolly Khanna" in d["message"]
    assert d["entities"], "the aliases being looked for are still worth showing"


# ---------------------------------------------------------------------------
# verify()
# ---------------------------------------------------------------------------

def test_verify_reports_an_alias_the_ledger_has_never_seen(mods):
    """The whole point: the table is a set of claims about strings in real
    filings, and a claim can be a typo. An untested table is an asserted one."""
    store, inv = mods
    _atulauto(store)
    v = inv.verify()
    matched = {"vijay kedia", "kedia securities"}
    assert v["matched"] == 2
    assert matched.isdisjoint({u["key"] for u in v["unmatched"]})
    assert any(u["investor"] == "dolly-khanna" for u in v["unmatched"])


def test_unclaimed_holders_exclude_the_ones_already_curated(mods):
    store, inv = mods
    _atulauto(store)
    store.record_filing("ATULAUTO", "2026-06-30", [], source_url="x")
    store.record_filing("OTHER", "2026-06-30", [_name("Some Big Holder", 7.0)])
    names = {r["holder_key"] for r in inv.unknown_big_holders(limit=50)}
    assert "some big holder" in names
    assert "vijay kedia" not in names


def test_unclaimed_holders_ignore_promoters(mods):
    """A company's own promoter is not a missing investor to add."""
    store, inv = mods
    store.record_filing("X", "2026-06-30", [
        _name("Founder Family Holdings", 60.0, promoter=True)])
    assert inv.unknown_big_holders(limit=50) == []


# ---------------------------------------------------------------------------
# The directory, and what an empty portfolio says
# ---------------------------------------------------------------------------

def test_the_directory_says_how_many_holdings_each_name_has(mods):
    """A card that gives no warning, clicked, lands on an empty page and reads
    as a broken feature. The same emptiness labelled beforehand reads as a
    ledger still being filled."""
    store, inv = mods
    _atulauto(store)
    rows = {r["id"]: r for r in inv.listing()}
    assert rows["vijay-kedia"]["positions"] == 1
    assert rows["dolly-khanna"]["positions"] == 0


def test_names_with_holdings_are_listed_first(mods):
    """A first screen of empty cards teaches a reader that the whole feature
    is empty."""
    store, inv = mods
    _atulauto(store)
    assert inv.listing()[0]["id"] == "vijay-kedia"


def test_a_position_is_counted_once_however_many_entities_hold_it(mods):
    """Atul Auto is on the register twice — him and his company. That is one
    holding, not two."""
    store, inv = mods
    _atulauto(store)
    assert {r["id"]: r for r in inv.listing()}["vijay-kedia"]["positions"] == 1


def test_a_joint_holding_is_not_counted_in_the_directory(mods):
    """It is excluded from the total on the portfolio page, so counting it on
    the card would promise a holding the page then declines to show."""
    store, inv = mods
    inv.INVESTORS.append({
        "id": "test-joint2", "name": "Test Two", "kind": "individual",
        "about": "fixture",
        "entities": [{"alias": "Test Two And Another", "relation": "joint"}]})
    try:
        store.record_filing("X", "2026-06-30", [_name("Test Two And Another", 9.0)])
        assert {r["id"]: r for r in inv.listing()}["test-joint2"]["positions"] == 0
    finally:
        inv.INVESTORS[:] = [i for i in inv.INVESTORS if i["id"] != "test-joint2"]


def test_an_empty_portfolio_blames_the_ledger_not_the_investor(mods):
    """Without this, a reader concludes the person holds nothing. The ledger
    having read 43 of 2,300 companies is the fact that explains the page."""
    store, inv = mods
    _atulauto(store)
    d = inv.portfolio("dolly-khanna")
    assert d["available"] is False
    assert "have not been reached" in d["message"]
    assert "not that there are none" in d["message"]
    assert d["coverage"]["companies_read"] == 1


def test_the_directory_works_before_anything_has_been_crawled(mods):
    """The first load of a brand-new instance. Every count is zero and nothing
    raises."""
    _store, inv = mods
    rows = inv.listing()
    tracked = [i for i in inv.INVESTORS if i.get("kind") != "redirect"]
    assert len(rows) == len(tracked)
    assert all(r["positions"] == 0 for r in rows), \
        "an un-crawled ledger must report zero, not omit the count"
