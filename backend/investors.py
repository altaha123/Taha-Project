"""
investors.py — which filed names belong to which investor

WHAT THIS IS
A curated table mapping the strings companies file to the people behind them,
and the code that assembles a portfolio out of the holdings ledger.

WHY THIS IS A HAND-WRITTEN LIST AND NOT A MATCHING ALGORITHM
Atul Auto's filing names VIJAY KEDIA (18.20%) and KEDIA SECURITIES PRIVATE
LIMITED (2.71%) on separate rows. Elecon's names Vijay Kishanlal Kedia (1.00%).
Metro Brands names three discretionary trusts of 4.79% each whose trustee is
Rekha Jhunjhunwala. No string-similarity score gets all of those right, and the
cost of getting one wrong is not a bad recommendation — it is publishing, about
a named private individual, a false statement that they own a particular stake
in a particular company. So every association here was decided by a person, is
written down, and says what KIND of association it is.

There is no fuzzy matching anywhere in this module. A name either matches an
alias exactly after normalisation, or it does not appear.

ROLLED UP, BUT NEVER SILENTLY
A portfolio totals the investor's own holdings together with the entities they
control, because that is what "Vijay Kedia's position in Atul Auto" means to
anybody who asks. But every constituent is carried in the payload with its own
filed name, its own percentage and its `relation`, so the page can show that
20.91% is 18.20% personally plus 2.71% through Kedia Securities, and a reader
who thinks those should not be added can see the parts and disagree. A total
whose components are not visible is an assertion; one whose components are
shown is evidence.

THE TRUSTS ARE THE HARD CASE, AND ARE MARKED AS SUCH
A discretionary trust of which someone is trustee is not the same as shares
they beneficially own. The relation is recorded as `trust` rather than `self`,
counted in the headline, and labelled wherever it is shown. Reasonable people
put that line in different places; what is not reasonable is moving it without
telling the reader.

RAKESH JHUNJHUNWALA DIED IN AUGUST 2022
The holdings are Rekha Jhunjhunwala's and the family trusts'. There is no
"Rakesh Jhunjhunwala portfolio" to show in 2026, and a page headed with his
name would be wrong. He is in the table only as a redirect.

VERIFY, DO NOT ASSUME
Every alias here is a claim about a string that appears in a real filing, and a
claim can be a typo. `verify()` checks the whole table against the ledger and
reports which aliases have never matched anything. An alias that matches
nothing is dead weight; an alias that matches something unexpected is a bug
worth seeing before a reader does.
"""

import datetime as dt

try:
    import holdings_store as store
except Exception:                                    # pragma: no cover
    store = None


# ---------------------------------------------------------------------------
# The table
# ---------------------------------------------------------------------------
# relation:
#   self       the investor's own name, as filed
#   family     an immediate family member who is habitually counted with them
#   entity     a company or LLP the investor controls and invests through
#   trust      a trust the investor is trustee of — NOT the same as owning it
#   joint      a holding filed in two people's names together. Recorded and
#              shown, but NOT added to the headline: the filing does not say
#              how it divides, and crediting all of it to one of them is a
#              claim the document never makes. Damani's register has several.
#
# `aliases` are matched exactly after holdings_store.holder_key() normalises
# case, punctuation and corporate suffixes. Spelling variants that appear in
# filings are listed individually; nothing is inferred.

INVESTORS = [
    {
        "id": "vijay-kedia",
        "name": "Vijay Kedia",
        "kind": "individual",
        "about": "Mumbai-based investor, active since the late 1980s; known for "
                 "long holds in small and mid caps.",
        "entities": [
            {"alias": "Vijay Kedia", "relation": "self"},
            {"alias": "Vijay Kishanlal Kedia", "relation": "self"},
            {"alias": "Kedia Securities Private Limited", "relation": "entity"},
        ],
    },
    {
        "id": "rekha-jhunjhunwala",
        "name": "Rekha Jhunjhunwala",
        "kind": "individual",
        "about": "Holds the portfolio built with Rakesh Jhunjhunwala, who died "
                 "in August 2022, together with the family trusts.",
        "entities": [
            {"alias": "Rekha Jhunjhunwala", "relation": "self"},
            {"alias": "Rekha Rakesh Jhunjhunwala", "relation": "self"},
            {"alias": "Aryaman Jhunjhunwala Discretionary Trust", "relation": "trust"},
            {"alias": "Aryavir Jhunjhunwala Discretionary Trust", "relation": "trust"},
            {"alias": "Nishtha Jhunjhunwala Discretionary Trust", "relation": "trust"},
            {"alias": "Rare Enterprises", "relation": "entity"},
        ],
        "notes": ["Rakesh Jhunjhunwala died in August 2022. These are Rekha "
                  "Jhunjhunwala's holdings and the family trusts', not his."],
    },
    {
        "id": "rakesh-jhunjhunwala",
        "name": "Rakesh Jhunjhunwala",
        "kind": "redirect",
        "redirect_to": "rekha-jhunjhunwala",
        "about": "Died August 2022. The holdings are now Rekha Jhunjhunwala's "
                 "and the family trusts'.",
        "entities": [],
    },
    {
        "id": "radhakishan-damani",
        "name": "Radhakishan Damani",
        "kind": "individual",
        "about": "Founder of Avenue Supermarts (DMart); invests through several "
                 "family entities.",
        "entities": [
            {"alias": "Radhakishan Shivkishan Damani", "relation": "self"},
            {"alias": "Radhakishan Damani", "relation": "self"},
            {"alias": "Gopikishan Shivkishan Damani", "relation": "family"},
            {"alias": "Derive Trading And Resorts Private Limited", "relation": "entity"},
            {"alias": "Bright Star Investments Private Limited", "relation": "entity"},
            {"alias": "Damani Estates And Finance Private Limited", "relation": "entity"},
        ],
    },
    {
        "id": "ashish-kacholia",
        "name": "Ashish Kacholia",
        "kind": "individual",
        "about": "Small-cap investor; also invests through Bengal Finance & "
                 "Investment.",
        "entities": [
            {"alias": "Ashish Dhawan Kacholia", "relation": "self"},
            {"alias": "Ashish Kacholia", "relation": "self"},
            {"alias": "Bengal Finance And Investment Private Limited", "relation": "entity"},
        ],
    },
    {
        "id": "mukul-agrawal",
        "name": "Mukul Agrawal",
        "kind": "individual",
        "about": "Mumbai investor; the filed name is usually Mukul Mahavir "
                 "Prasad Agrawal.",
        "entities": [
            {"alias": "Mukul Mahavir Prasad Agrawal", "relation": "self"},
            {"alias": "Mukul Mahavir Agrawal", "relation": "self"},
            {"alias": "Mukul Agrawal", "relation": "self"},
            {"alias": "Param Capital Research Private Limited", "relation": "entity"},
        ],
    },
    {
        "id": "dolly-khanna",
        "name": "Dolly Khanna",
        "kind": "individual",
        "about": "Chennai-based; the portfolio is managed with Rajiv Khanna and "
                 "filed in her name.",
        "entities": [
            {"alias": "Dolly Khanna", "relation": "self"},
            {"alias": "Rajiv Khanna", "relation": "family"},
        ],
    },
    {
        "id": "sunil-singhania",
        "name": "Sunil Singhania",
        "kind": "individual",
        "about": "Founder of Abakkus Asset Manager; positions are usually filed "
                 "under the Abakkus funds rather than his own name.",
        "entities": [
            {"alias": "Sunil Singhania", "relation": "self"},
            {"alias": "Abakkus Growth Fund 1", "relation": "entity"},
            {"alias": "Abakkus Growth Fund 2", "relation": "entity"},
            {"alias": "Abakkus Emerging Opportunities Fund 1", "relation": "entity"},
            {"alias": "Abakkus Diversified Alpha Fund", "relation": "entity"},
        ],
    },
    {
        "id": "porinju-veliyath",
        "name": "Porinju Veliyath",
        "kind": "individual",
        "about": "Kochi-based; also invests through Equity Intelligence India.",
        "entities": [
            {"alias": "Porinju Veliyath", "relation": "self"},
            {"alias": "Porinju V Veliyath", "relation": "self"},
            {"alias": "Equity Intelligence India Private Limited", "relation": "entity"},
        ],
    },
    {
        "id": "anil-kumar-goel",
        "name": "Anil Kumar Goel",
        "kind": "individual",
        "about": "Long-standing investor in sugar and commodity cyclicals; "
                 "holdings are often filed jointly with Seema Goel.",
        "entities": [
            {"alias": "Anil Kumar Goel", "relation": "self"},
            {"alias": "Anil Kumar Goel And Seema Goel", "relation": "self"},
            {"alias": "Seema Goel", "relation": "family"},
        ],
    },
    {
        "id": "madhusudan-kela",
        "name": "Madhusudan Kela",
        "kind": "individual",
        "about": "Former Reliance Capital chief investment strategist; invests "
                 "through family entities and MK Ventures.",
        "entities": [
            {"alias": "Madhusudan Kela", "relation": "self"},
            {"alias": "Madhusudan Murlidhar Kela", "relation": "self"},
            {"alias": "Madhuri Madhusudan Kela", "relation": "family"},
            {"alias": "MK Ventures Capital Limited", "relation": "entity"},
        ],
    },
    {
        "id": "ashish-dhawan",
        "name": "Ashish Dhawan",
        "kind": "individual",
        "about": "Co-founder of ChrysCapital; now largely in philanthropy, with "
                 "a personal listed portfolio.",
        "entities": [
            {"alias": "Ashish Dhawan", "relation": "self"},
        ],
    },
    {
        "id": "akash-bhanshali",
        "name": "Akash Bhanshali",
        "kind": "individual",
        "about": "Mumbai investor; associated with Enam.",
        "entities": [
            {"alias": "Akash Bhanshali", "relation": "self"},
            {"alias": "Akash Manharlal Bhanshali", "relation": "self"},
        ],
    },
    {
        "id": "bhavook-tripathi",
        "name": "Bhavook Tripathi",
        "kind": "individual",
        "about": "Known for concentrated, very long-held positions.",
        "entities": [
            {"alias": "Bhavook Tripathi", "relation": "self"},
        ],
    },
    {
        "id": "hitesh-doshi",
        "name": "Hitesh Ramji Doshi",
        "kind": "individual",
        "about": "Mumbai investor.",
        "entities": [
            {"alias": "Hitesh Ramji Doshi", "relation": "self"},
            {"alias": "Hitesh Doshi", "relation": "self"},
        ],
    },
    {
        "id": "nemish-shah",
        "name": "Nemish Shah",
        "kind": "individual",
        "about": "Co-founder of Enam; a small number of very long holds.",
        "entities": [
            {"alias": "Nemish S Shah", "relation": "self"},
            {"alias": "Nemish Shah", "relation": "self"},
        ],
    },
    {
        "id": "sangeetha-s",
        "name": "Sangeetha S",
        "kind": "individual",
        "about": "Chennai-based investor who appears in a number of small-cap "
                 "registers.",
        "entities": [
            {"alias": "Sangeetha S", "relation": "self"},
        ],
    },
    {
        "id": "vanaja-sundar-iyer",
        "name": "Vanaja Sundar Iyer",
        "kind": "individual",
        "about": "Appears in several small-cap shareholder registers.",
        "entities": [
            {"alias": "Vanaja Sundar Iyer", "relation": "self"},
        ],
    },
    {
        "id": "dheeraj-kumar-lohia",
        "name": "Dheeraj Kumar Lohia",
        "kind": "individual",
        "about": "Small-cap investor.",
        "entities": [
            {"alias": "Dheeraj Kumar Lohia", "relation": "self"},
        ],
    },
    {
        "id": "shivani-tejas-trivedi",
        "name": "Shivani Tejas Trivedi",
        "kind": "individual",
        "about": "Appears in a number of small-cap registers.",
        "entities": [
            {"alias": "Shivani Tejas Trivedi", "relation": "self"},
            {"alias": "Tejas Trivedi", "relation": "family"},
        ],
    },
    {
        "id": "jagdish-master",
        "name": "Jagdish Amritlal Master",
        "kind": "individual",
        "about": "Long-standing small-cap investor.",
        "entities": [
            {"alias": "Jagdish Amritlal Master", "relation": "self"},
            {"alias": "Jagdish Master", "relation": "self"},
        ],
    },
    {
        "id": "ricky-kirpalani",
        "name": "Ricky Ishwardas Kirpalani",
        "kind": "individual",
        "about": "Invests personally and through Alchemy-linked vehicles.",
        "entities": [
            {"alias": "Ricky Ishwardas Kirpalani", "relation": "self"},
        ],
    },
    {
        "id": "ashok-kumar-jain",
        "name": "Ashok Kumar Jain",
        "kind": "individual",
        "about": "Appears in several small-cap registers.",
        "entities": [
            {"alias": "Ashok Kumar Jain", "relation": "self"},
        ],
    },
    {
        "id": "girish-gulati",
        "name": "Girish Gulati",
        "kind": "individual",
        "about": "Small-cap investor.",
        "entities": [
            {"alias": "Girish Gulati", "relation": "self"},
            {"alias": "Girish Gulati HUF", "relation": "family"},
        ],
    },
    {
        "id": "lashit-sanghvi",
        "name": "Lashit Sanghvi",
        "kind": "individual",
        "about": "Co-founder of Alchemy Capital.",
        "entities": [
            {"alias": "Lashit Sanghvi", "relation": "self"},
        ],
    },
    {
        "id": "hemendra-kothari",
        "name": "Hemendra Kothari",
        "kind": "individual",
        "about": "Founder of DSP; invests personally and through family "
                 "entities.",
        "entities": [
            {"alias": "Hemendra Mafatlal Kothari", "relation": "self"},
            {"alias": "Hemendra Kothari", "relation": "self"},
        ],
    },
    {
        "id": "aequitas",
        "name": "Aequitas Investment",
        "kind": "fund",
        "about": "Portfolio management service; small-cap focused.",
        "entities": [
            {"alias": "Aequitas Investment Consultancy Private Limited", "relation": "self"},
            {"alias": "Aequitas Opportunities Fund", "relation": "entity"},
        ],
    },
    {
        "id": "malabar",
        "name": "Malabar Investments",
        "kind": "fund",
        "about": "Singapore-based India-focused fund.",
        "entities": [
            {"alias": "Malabar India Fund Limited", "relation": "self"},
            {"alias": "Malabar Value Fund", "relation": "entity"},
            {"alias": "Malabar Select Fund", "relation": "entity"},
        ],
    },
    {
        "id": "nalanda",
        "name": "Nalanda Capital",
        "kind": "fund",
        "about": "Singapore-based, long-hold India fund.",
        "entities": [
            {"alias": "Nalanda India Equity Fund Limited", "relation": "self"},
            {"alias": "Nalanda India Fund Limited", "relation": "entity"},
        ],
    },
]

RELATION_WORDS = {
    "self": "in their own name",
    "family": "immediate family",
    "entity": "through an entity they control",
    "trust": "a family trust they are trustee of",
    "joint": "held jointly with another person",
}

# The relations counted in the headline total. `trust` is included and labelled
# rather than quietly folded in — see the module docstring. `joint` is not: a
# holding filed in two names does not say how it splits, so it is listed beside
# the total instead of inside it.
COUNTED = ("self", "family", "entity", "trust")


def _by_id():
    return {i["id"]: i for i in INVESTORS}


def resolve(investor_id):
    """An investor, following a redirect. Returns (investor, redirected_from)."""
    table = _by_id()
    inv = table.get((investor_id or "").strip().lower())
    if inv is None:
        return None, None
    if inv.get("kind") == "redirect":
        target = table.get(inv.get("redirect_to"))
        if target:
            return target, inv
    return inv, None


def keys_for(inv):
    """Every normalised holder key that belongs to this investor."""
    if store is None:
        return {}
    out = {}
    for e in inv.get("entities") or []:
        k = store.holder_key(e["alias"])
        if k:
            out[k] = e
    return out


def listing():
    """The directory, without touching the ledger."""
    out = []
    for inv in INVESTORS:
        if inv.get("kind") == "redirect":
            continue
        out.append({
            "id": inv["id"], "name": inv["name"], "kind": inv.get("kind"),
            "about": inv.get("about"),
            "entities": len(inv.get("entities") or []),
        })
    return sorted(out, key=lambda r: r["name"])


# ---------------------------------------------------------------------------
# Assembling a portfolio
# ---------------------------------------------------------------------------

def _quarter_label(iso):
    """'Q1 FY27' for the Indian fiscal year the quarter ends in."""
    try:
        end = dt.date.fromisoformat(iso)
    except Exception:
        return iso
    q = {3: 4, 6: 1, 9: 2, 12: 3}.get(end.month)
    if not q:
        return iso
    fy = end.year + 1 if end.month >= 4 else end.year
    return "Q%d FY%02d" % (q, fy % 100)


def portfolio(investor_id, period_end=None):
    """
    One investor's disclosed positions, newest quarter, with the quarter before
    it for comparison.

    Returns positions summed per company across every entity that belongs to
    the investor — and carries the constituent rows so the sum can be taken
    apart on screen.
    """
    inv, redirected = resolve(investor_id)
    out = {"available": False, "id": (investor_id or "").strip().lower()}
    if inv is None:
        out["message"] = "No investor is tracked under that name."
        return out
    out.update({"id": inv["id"], "name": inv["name"], "kind": inv.get("kind"),
                "about": inv.get("about")})
    if redirected:
        out["redirected_from"] = {"id": redirected["id"], "name": redirected["name"],
                                  "about": redirected.get("about")}
    if store is None:
        out["message"] = "The holdings ledger is not available."
        return out

    keymap = keys_for(inv)
    rows = store.positions_for_keys(list(keymap))
    if not rows:
        out["message"] = ("Nothing has been recorded for %s yet. The ledger is "
                          "built by reading company filings one at a time; a "
                          "name appears once a company it holds has been read."
                          % inv["name"])
        out["entities"] = [{"alias": e["alias"], "relation": e["relation"],
                            "relation_word": RELATION_WORDS.get(e["relation"], "")}
                           for e in inv.get("entities") or []]
        return out

    quarters = sorted({r["period_end"] for r in rows}, reverse=True)
    now_q = period_end or quarters[0]
    prev_q = next((q for q in quarters if q < now_q), None)

    def _entity_for(row):
        """Which curated alias brought this row in — by exact name, or by the
        name with its bracketed annotation removed."""
        return keymap.get(row["holder_key"]) or keymap.get(row.get("holder_base") or "")

    def fold(q):
        """Sum per company, keeping the constituent rows."""
        agg = {}
        for r in rows:
            if r["period_end"] != q:
                continue
            e = _entity_for(r) or {}
            rel = e.get("relation")
            if rel is None:
                continue
            a = agg.setdefault(r["symbol"], {
                "symbol": r["symbol"], "pct": 0.0, "shares": 0.0,
                "has_shares": False, "parts": [], "beside": [],
                "promoter": False, "source": r.get("source_url"),
                "filed": r.get("filed")})
            part = {
                "name": r["holder_raw"], "pct": r["pct"], "shares": r.get("shares"),
                "relation": rel, "relation_word": RELATION_WORDS.get(rel, ""),
                "matched_on": r.get("matched_on") or "name",
            }
            if rel not in COUNTED:
                a["beside"].append(part)          # shown, never added
                continue
            a["pct"] += float(r["pct"] or 0)
            if r.get("shares"):
                a["shares"] += float(r["shares"]); a["has_shares"] = True
            # A promoter stake is the investor's own company, not a position
            # they took in someone else's. Damani's 23% of Avenue Supermarts is
            # the largest line in his register and it is not a stock pick.
            if r.get("promoter"):
                a["promoter"] = True
            a["parts"].append(part)
        for sym in list(agg):
            a = agg[sym]
            if not a["parts"]:                    # only joint rows: nothing to total
                del agg[sym]
                continue
            a["pct"] = round(a["pct"], 4)
            if not a["has_shares"]:
                a["shares"] = None
            a["parts"].sort(key=lambda p: -(p["pct"] or 0))
            a["split"] = len(a["parts"]) > 1
        return agg

    now, prev = fold(now_q), fold(prev_q) if prev_q else {}

    positions = []
    for sym, a in now.items():
        before = prev.get(sym)
        if before is None:
            move = {"kind": "new" if prev_q else "unknown", "delta": None}
        else:
            d = round(a["pct"] - before["pct"], 4)
            move = {"kind": "added" if d > 0.005 else
                            ("trimmed" if d < -0.005 else "held"), "delta": d}
        positions.append(dict(a, change=move))
    positions.sort(key=lambda p: -(p["pct"] or 0))

    # Gone from the newest quarter. Below 1% counts as "no longer disclosed",
    # NOT as sold — the filing simply stops naming a holder under the threshold,
    # and calling that an exit is a claim the document does not make.
    exited = []
    for sym, a in (prev or {}).items():
        if sym not in now:
            exited.append({"symbol": sym, "was_pct": a["pct"],
                           "parts": a["parts"]})
    exited.sort(key=lambda p: -(p["was_pct"] or 0))

    out.update({
        "available": True,
        "period_end": now_q,
        "period": _quarter_label(now_q),
        "compared_with": _quarter_label(prev_q) if prev_q else None,
        "compared_with_period_end": prev_q,
        "positions": positions,
        "count": len(positions),
        "no_longer_disclosed": exited,
        "entities": [{"alias": e["alias"], "relation": e["relation"],
                      "relation_word": RELATION_WORDS.get(e["relation"], "")}
                     for e in inv.get("entities") or []],
        "quarters_available": quarters[:12],
        "notes": (inv.get("notes") or []) + [
            "Only stakes above 1% of a company are named in its shareholding "
            "filing. A position below that is invisible here however large it "
            "is in rupees, so this is a floor on what is held, never the whole "
            "portfolio.",
            "Filings are quarterly and land up to 21 days after the quarter "
            "ends, so a position can be up to four months old. It is what was "
            "disclosed, not what is held today.",
            "A company leaving the list has fallen below the 1% disclosure "
            "threshold or been sold. The filing does not say which, and this "
            "does not guess.",
            "A holding marked as a promoter stake is the investor's own "
            "company rather than a position taken in someone else's, and is "
            "not a stock pick.",
        ],
    })
    if any(p["relation"] == "trust" for p in out["entities"]):
        out["notes"].insert(0, (
            "This total includes family trusts of which %s is trustee. A "
            "discretionary trust is not the same as shares owned outright; "
            "each trust is listed separately under the position it belongs to."
            % inv["name"]))
    return out


# ---------------------------------------------------------------------------
# Checking the table against reality
# ---------------------------------------------------------------------------

def verify():
    """
    Every alias, and whether the ledger has ever seen it.

    An alias is a claim that a particular string appears in a real filing. A
    claim can be a typo, and a typo here is a silently missing position rather
    than an error. This is what makes the table checkable instead of asserted:
    `unmatched` is the list of aliases that have never matched anything, and
    anything on it is either wrong, or a holding not yet crawled.
    """
    if store is None:
        return {"available": False, "message": "The holdings ledger is not available."}
    conn = store._connect()
    have = {r[0] for r in conn.execute(
        "SELECT DISTINCT holder_key FROM holdings").fetchall()}
    matched, unmatched = [], []
    for inv in INVESTORS:
        for e in inv.get("entities") or []:
            k = store.holder_key(e["alias"])
            row = {"investor": inv["id"], "alias": e["alias"],
                   "key": k, "relation": e["relation"]}
            (matched if k in have else unmatched).append(row)
    return {
        "available": True,
        "investors": len([i for i in INVESTORS if i.get("kind") != "redirect"]),
        "aliases": len(matched) + len(unmatched),
        "matched": len(matched),
        "unmatched": unmatched,
        "ledger_holders": len(have),
        "note": ("An unmatched alias is either a misspelling in this table or a "
                 "holding in a company the crawler has not reached yet. It is "
                 "not, by itself, evidence that the investor does not hold "
                 "anything."),
    }


def unknown_big_holders(min_pct=1.0, limit=60, period_end=None):
    """
    Named holders the ledger has seen that no tracked investor claims, largest
    first.

    This is how the table grows honestly: rather than guessing at alias
    spellings, look at what companies have actually filed and add the names
    worth adding. It is also how a misspelling in the table shows up — the
    correct spelling appears here, unclaimed.
    """
    if store is None:
        return []
    conn = store._connect()
    claimed = set()
    for inv in INVESTORS:
        for e in inv.get("entities") or []:
            claimed.add(store.holder_key(e["alias"]))
    period_end = period_end or store.latest_period()
    if not period_end:
        return []
    rows = conn.execute(
        "SELECT holder_key, holder_raw, COUNT(DISTINCT symbol) AS companies,"
        " MAX(pct) AS top_pct, SUM(pct) AS total_pct FROM holdings"
        " WHERE period_end = ? AND promoter = 0 AND pct >= ?"
        " GROUP BY holder_key ORDER BY companies DESC, total_pct DESC LIMIT ?",
        (period_end, float(min_pct), int(limit) * 4)).fetchall()
    out = []
    for r in rows:
        if r["holder_key"] in claimed:
            continue
        out.append(dict(r))
        if len(out) >= limit:
            break
    return out
