"""
The holdings ledger.

The failures worth a test file here are the ones that produce a plausible
number rather than an error — a position that reads a fifth of its real size,
or a category heading that becomes an investor holding four hundred companies.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture()
def store(tmp_path, monkeypatch):
    """A fresh ledger per test, on disk, with the module's own state reset."""
    monkeypatch.setenv("ALTAHA_HOLDINGS_DB", str(tmp_path / "h.db"))
    for mod in ("holdings_store",):
        sys.modules.pop(mod, None)
    import holdings_store as s
    return s


def _name(n, pct, shares=None, kind="Other", promoter=False):
    return {"name": n, "pct": pct, "shares": shares, "kind": kind,
            "promoter": promoter}


# ---------------------------------------------------------------------------
# Normalising a name
# ---------------------------------------------------------------------------

def test_case_and_spacing_are_folded(store):
    """Filings are wildly inconsistent. Titan writes "Rekha Jhunjhunwala",
    Metro Brands writes it in capitals, and one register has three spaces in
    the middle of the name."""
    a = store.holder_key("REKHA JHUNJHUNWALA")
    b = store.holder_key("Rekha Jhunjhunwala")
    c = store.holder_key("REKHA   RAKESH       JHUNJHUNWALA")
    assert a == b == "rekha jhunjhunwala"
    assert c == "rekha rakesh jhunjhunwala"


def test_corporate_suffixes_are_not_identity(store):
    for n in ("KEDIA SECURITIES PRIVATE LIMITED", "Kedia Securities Pvt Ltd",
              "Kedia Securities Limited", "kedia securities"):
        assert store.holder_key(n) == "kedia securities"


def test_honorifics_are_dropped(store):
    assert store.holder_key("Mr. Vijay Kedia") == store.holder_key("Vijay Kedia")


def test_a_middle_name_is_NOT_folded(store):
    """The line this module refuses to cross. "Vijay Kedia" and "Vijay
    Kishanlal Kedia" are the same man, but "Ashish Kumar Jain" and "Ashish
    Jain" are routinely not — so the decision belongs to a curated table where
    a person made it, never to a string function."""
    assert store.holder_key("Vijay Kedia") != store.holder_key("Vijay Kishanlal Kedia")


def test_a_bracketed_annotation_is_stripped_only_in_the_base_form(store):
    """Metro Brands files the trustee inside the name and the wording is not
    stable between companies. The base form absorbs that; the exact key does
    not, so nothing is merged unless a curated alias asks for it."""
    long = "ARYAMAN JHUNJHUNWALA DISCRETIONARY TRUST (TRUSTEE - REKHA RAKESH JHUNJHUNWALA)"
    short = "Aryaman Jhunjhunwala Discretionary Trust"
    assert store.holder_key(long) != store.holder_key(short)
    assert store.holder_base(long) == store.holder_base(short)
    assert store.holder_base(short) == "aryaman jhunjhunwala discretionary trust"


def test_nested_brackets_are_removed(store):
    assert store.holder_base("Some Fund (a (nested) note)") == "some fund"


def test_a_joint_holding_does_not_collapse_to_either_person(store):
    """"Gopikishan S. Damani And Radhakishan S. Damani (On behalf of ...)" is
    its own holder. Folding it onto either man would credit one of them with a
    stake the filing never gives them alone."""
    joint = store.holder_base("Gopikishan S. Damani And Radhakishan S. Damani (On behalf of X)")
    assert joint == "gopikishan s damani and radhakishan s damani"
    assert joint != store.holder_key("Radhakishan Shivkishan Damani")


@pytest.mark.parametrize("heading", [
    "Foreign Institutional Investors", "Mutual Funds", "Bodies Corporate",
    "Resident Individuals", "Public", "Banks", "Trusts",
])
def test_category_headings_are_not_holders(store, heading):
    """The exchange format puts these through the same element as a real name.
    Left in, "Foreign Institutional Investors" becomes an investor holding
    several hundred companies."""
    assert store.is_real_holder(heading) is False


def test_a_real_name_is_a_holder(store):
    for n in ("Vijay Kedia", "Rekha Jhunjhunwala", "Kedia Securities Private Limited"):
        assert store.is_real_holder(n) is True


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------

def test_two_folios_of_one_name_stay_two_rows(store):
    """THE bug this schema exists to prevent. Titan's March 2026 filing names
    Rekha Jhunjhunwala twice, 4.24% and 1.07%. Keyed without a slot the second
    overwrites the first and the position reads a fifth of its real size."""
    store.record_filing("TITAN", "2026-03-31", [
        _name("Rekha Jhunjhunwala", 4.24),
        _name("Life Insurance Corporation Of India", 2.34, kind="Insurance"),
        _name("Rekha Jhunjhunwala", 1.07),
    ])
    rows = store.positions_for_keys(["rekha jhunjhunwala"])
    assert len(rows) == 2
    assert round(sum(r["pct"] for r in rows), 2) == 5.31


def test_a_recrawl_writes_nothing_and_does_not_double_the_position(store):
    names = [_name("Vijay Kedia", 18.20), _name("Kedia Securities Private Limited", 2.71)]
    first = store.record_filing("ATULAUTO", "2026-06-30", names)
    again = store.record_filing("ATULAUTO", "2026-06-30", names)
    assert first == 2
    assert again == 0, "the ledger is append-only; a re-crawl must be a no-op"
    assert len(store.positions_for_keys(["vijay kedia"])) == 1


def test_a_zero_or_negative_stake_is_not_a_position(store):
    """A named row at 0.00% is a disclosure artefact. Kept, it puts companies
    into a portfolio the investor does not hold."""
    store.record_filing("X", "2026-06-30", [
        _name("Vijay Kedia", 0.0), _name("Someone Else", -1.0),
        _name("Real Holder", 2.0),
    ])
    assert store.positions_for_keys(["vijay kedia"]) == []
    assert len(store.holders_of("X")) == 1


def test_headings_are_filtered_on_write(store):
    store.record_filing("X", "2026-06-30", [
        _name("Foreign Institutional Investors", 12.0),
        _name("Vijay Kedia", 3.0),
    ])
    assert len(store.holders_of("X")) == 1


def test_the_filed_string_is_kept_verbatim(store):
    """Normalisation is for the index. What gets shown is what the company
    actually wrote."""
    store.record_filing("X", "2026-06-30", [_name("VIJAY KEDIA", 3.0)])
    assert store.holders_of("X")[0]["holder_raw"] == "VIJAY KEDIA"


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------

def test_a_curated_alias_matches_through_the_bracket(store):
    store.record_filing("METROBRAND", "2026-06-30", [
        _name("ARYAMAN JHUNJHUNWALA DISCRETIONARY TRUST (TRUSTEE - REKHA RAKESH JHUNJHUNWALA)", 4.79),
    ])
    key = store.holder_key("Aryaman Jhunjhunwala Discretionary Trust")
    rows = store.positions_for_keys([key])
    assert len(rows) == 1
    assert rows[0]["matched_on"] == "name-without-bracket"


def test_an_exact_match_says_it_was_exact(store):
    store.record_filing("ATULAUTO", "2026-06-30", [_name("VIJAY KEDIA", 18.2)])
    rows = store.positions_for_keys(["vijay kedia"])
    assert rows[0]["matched_on"] == "name"


def test_quarters_come_back_newest_first(store):
    for p, pct in (("2025-12-31", 1.0), ("2026-06-30", 3.0), ("2026-03-31", 2.0)):
        store.record_filing("X", p, [_name("Vijay Kedia", pct)])
    rows = store.positions_for_keys(["vijay kedia"])
    assert [r["period_end"] for r in rows] == ["2026-06-30", "2026-03-31", "2025-12-31"]


def test_holders_of_defaults_to_the_newest_quarter(store):
    store.record_filing("X", "2026-03-31", [_name("A Holder", 1.0)])
    store.record_filing("X", "2026-06-30", [_name("A Holder", 2.0), _name("B Holder", 1.5)])
    rows = store.holders_of("X")
    assert {r["period_end"] for r in rows} == {"2026-06-30"}
    assert len(rows) == 2


def test_an_unknown_symbol_is_empty_not_an_error(store):
    assert store.holders_of("NOSUCH") == []
    assert store.positions_for_keys(["nobody"]) == []
    assert store.positions_for_keys([]) == []


# ---------------------------------------------------------------------------
# The crawl queue
# ---------------------------------------------------------------------------

def test_never_tried_symbols_come_first(store):
    store.mark_coverage("SEEN", "ok", ok=True)
    due = store.due_symbols(["SEEN", "FRESH", "ALSONEW"], limit=10)
    assert due[0] in ("FRESH", "ALSONEW")
    assert "SEEN" not in due, "a company read minutes ago is not due again"


def test_the_queue_is_bounded(store):
    assert len(store.due_symbols([f"S{i}" for i in range(500)], limit=25)) == 25


def test_coverage_accumulates_rather_than_replacing(store):
    store.mark_coverage("X", "ok", rows_written=10, quarters=2, ok=True)
    store.mark_coverage("X", "ok", rows_written=5, quarters=4, ok=True)
    conn = store._connect()
    row = conn.execute("SELECT * FROM coverage WHERE symbol='X'").fetchone()
    assert row["rows_written"] == 15
    assert row["quarters"] == 4


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------

def test_a_ledger_from_an_earlier_version_gains_the_new_column(tmp_path, monkeypatch):
    """CREATE TABLE IF NOT EXISTS does nothing to a table that already exists,
    so without a migration step a live ledger keeps its old shape and every
    query naming a new column fails — on the one dataset that cannot simply be
    rebuilt."""
    import sqlite3
    db = tmp_path / "old.db"
    conn = sqlite3.connect(db)
    conn.executescript("""
      CREATE TABLE holdings (
        symbol TEXT NOT NULL, period_end TEXT NOT NULL, slot INTEGER NOT NULL,
        holder_raw TEXT NOT NULL, holder_key TEXT NOT NULL, pct REAL,
        shares REAL, kind TEXT, promoter INTEGER NOT NULL DEFAULT 0,
        filed TEXT, source_url TEXT, first_seen_utc TEXT NOT NULL,
        PRIMARY KEY (symbol, period_end, slot));
      CREATE TABLE coverage (symbol TEXT PRIMARY KEY, last_try_utc TEXT,
        last_ok_utc TEXT, latest_period TEXT, quarters INTEGER NOT NULL DEFAULT 0,
        rows_written INTEGER NOT NULL DEFAULT 0, status TEXT, note TEXT);
    """)
    conn.execute(
        "INSERT INTO holdings VALUES ('METROBRAND','2026-06-30',0,"
        "'ARYAMAN JHUNJHUNWALA DISCRETIONARY TRUST (TRUSTEE - REKHA)',"
        "'aryaman jhunjhunwala discretionary trust trustee rekha',4.79,NULL,"
        "'Other',0,NULL,NULL,'2026-07-01T00:00:00+00:00')")
    conn.commit()
    conn.close()

    monkeypatch.setenv("ALTAHA_HOLDINGS_DB", str(db))
    sys.modules.pop("holdings_store", None)
    import holdings_store as s

    assert s.stats()["rows"] == 1, "the existing row must survive the migration"
    # The new column exists but is empty on the old row until it is backfilled.
    key = s.holder_key("Aryaman Jhunjhunwala Discretionary Trust")
    assert s.positions_for_keys([key]) == []
    assert s.backfill_base_keys() == 1
    assert len(s.positions_for_keys([key])) == 1
    assert s.backfill_base_keys() == 0, "backfilling twice must be a no-op"


# ---------------------------------------------------------------------------
# Quarter ends
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("iso,ok", [
    ("2026-03-31", True), ("2026-06-30", True),
    ("2026-09-30", True), ("2026-12-31", True),
    ("2026-07-01", False),      # the one that actually happened
    ("2026-06-29", False), ("2026-03-30", False), ("2026-12-30", False),
    ("2026-02-28", False), ("", False), (None, False), ("nonsense", False),
])
def test_only_a_real_quarter_end_counts_as_a_quarter(store, iso, ok):
    assert store.is_quarter_end(iso) is ok


def test_an_interim_filing_never_reaches_the_ledger(store):
    """Regulation 31 also requires a filing within ten days of a capital
    change. It is a real disclosure and it is not a quarter, and the crawler
    only ever sees the INDEX's date — the document can date itself differently."""
    assert store.record_filing("RAMBHAJO", "2026-07-01",
                               [_name("A Holder", 5.0)]) == 0
    assert store.holders_of("RAMBHAJO") == []


def test_one_stray_date_cannot_become_the_current_quarter(store):
    """
    The bug this exists for, end to end.

    One company filed under 1 July. That became MAX(period_end), so every
    caller asking for the current quarter got a period containing a single
    company — and the investor directory, which counts holdings in the current
    quarter, showed all twenty-seven names as holding nothing while their
    portfolio pages were full.
    """
    for i in range(30):
        store.record_filing("CO%d" % i, "2026-06-30", [_name("A Holder", 2.0)])
    # Written straight past record_filing's guard, the way the old crawler did.
    conn = store._connect()
    conn.execute(
        "INSERT INTO holdings (symbol, period_end, slot, holder_raw, holder_key,"
        " holder_base, pct, promoter, first_seen_utc)"
        " VALUES ('STRAY','2026-07-01',0,'A Holder','a holder','a holder',5.0,0,'x')")
    conn.commit()

    assert store.latest_period() == "2026-06-30", \
        "the newest QUARTER, not the newest date"
    assert store.purge_non_quarter_rows() == 1
    assert store.purge_non_quarter_rows() == 0, "repairing twice is a no-op"
    assert store.latest_period() == "2026-06-30"


def test_the_purge_leaves_every_real_quarter_alone(store):
    """It is a repair for one defect, not licence to prune the ledger."""
    for p in ("2026-06-30", "2026-03-31", "2021-12-31"):
        store.record_filing("X", p, [_name("A Holder", 2.0)])
    assert store.purge_non_quarter_rows() == 0
    assert len(store.positions_for_keys(["a holder"])) == 3
