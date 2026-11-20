"""
Altaha Screener — WOW orders: an order big enough to matter

THE IDEA IN ONE LINE
"Company wins Rs 450 crore order" is a headline. "Rs 450 crore, against a
market value of Rs 3,700 crore" is a fact about the company. The second one is
the product, and it is arithmetic on two published numbers, so it stays on the
factual side of the line this project is built inside.

WHY THE VALUE HAS TO COME OUT OF THE PDF
Measured over 800 announcements across six trading days: one headline in the
whole set carried a rupee figure, and none of the four order disclosures stated
a value in the headline. The exchange feed gives a subject line; the amount is
in the attachment. So this reads the attachment.

WHAT IT REUSES
The rupee-figure patterns and the crore normalisation already exist in
social_posts, written for the same problem, and they are imported rather than
written again. What is added here is WHERE to look: in a one-page order letter
the largest figure in the document is almost always the order, but in a longer
filing it may be turnover, or last year's order book, or the company's paid-up
capital. So a figure sitting next to an order-value phrase beats a bigger
figure that is not, and the basis for the choice travels with the number.

WHAT IS READ, AND FROM WHERE
  · The value, from the filed document: an amount with a unit ("Rs 450
    crore"), an amount written out in rupees ("Rs.1,24,00,00,000", which is
    how most small companies write it), or the size row of the table SEBI
    prescribes for an order disclosure.
  · Who awarded it, what it is for and by when, from that same table, in the
    company's words. The exchange headline says none of it.
  · The company's market value and last full year's sales, from the tables
    the screener keeps. An order is set against both.
  · What kind of filing it is. A lowest bid, a memorandum of understanding and
    an update to an order already filed are listed and never called WOW; a tax
    or court order is not listed at all; two filings of one order are one row.

WHAT IT REFUSES TO DO
  · No value in the filing means no value. Plenty of Reg 30 order disclosures
    quantify a contract in megawatts, containers or route-kilometres and never
    state a rupee amount — the live example this was built against is a Letter
    of Intent measured in containers. Those are listed as "value not disclosed"
    and are excluded from the ranking rather than given a guessed number.
  · No market cap means no percentage. The order value is still shown.
  · A foreign-currency order is marked as converted at an assumed rate, because
    it was.

None of this is a recommendation. An order is an event with a size, and the
size is the whole of what this claims.
"""

import datetime as dt
import os
import re
import threading
import time

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))

# An order worth this much of the company is what the feature is named after.
# Inspectable and configurable, and shown in the response so a reader knows
# what line they are looking at.
WOW_MIN_PCT = float(os.environ.get("WOW_MIN_PCT", "10") or 10)

# How far from an order-value phrase a figure may sit and still be read as the
# order's value. Two sentences, roughly.
NEAR = int(os.environ.get("WOW_NEAR_CHARS", "260") or 260)

MAX_PDFS = int(os.environ.get("WOW_MAX_PDFS", "40") or 40)
CACHE_TTL = int(os.environ.get("WOW_CACHE_TTL", "600") or 600)

_lock = threading.Lock()
_cache = {"at": 0.0, "rows": [], "note": ""}
_mcap_cache = {}


# ---------------------------------------------------------------------------
# The value of the order
# ---------------------------------------------------------------------------

# The version of the reading below. A value read by an older version is not
# counted in a quarter's total until this one has read the filing again: the
# first reader could not read an amount written out in rupees, and took an
# order book for an order.
READER = 2

# Rupees to the US dollar for an order stated only in dollars. Assumed, said
# so on the row, and a rupee figure in the same sentence is always preferred.
USD_INR = float(os.environ.get("WOW_USD_INR", "93.5") or 93.5)

# Phrases a filing uses immediately around the number that IS the order.
VALUE_CUE = re.compile(
    r"\b(order value|contract value|value of the (?:order|contract|project|work)"
    r"|total value|aggregate value|aggregating to|valued at|worth(?: of)?"
    r"|order (?:worth|of|for)|contract (?:worth|of|for)|consideration of"
    r"|estimated (?:value|cost)|project cost|size of the order"
    # The wording of the disclosure table SEBI prescribes, and of the letters
    # written around it.
    r"|size of (?:the )?(?:work order|contract|order ?\(s\))"
    r"|broad (?:commercial )?consideration|consideration value"
    r"|(?:EPC|quoted|bid|contract|accepted) price|price for the project"
    r"|amounting to|totall?ing|for a value of|award value|order amount"
    r"|letters? of (?:award|acceptance|intent)(?: \(lo[ai]\))? (?:for|of|worth)"
    r"|orders? (?:amounting|totall?ing|aggregating|valued))\b", re.I)

# Figures that are emphatically NOT the order, even when they are the largest
# number on the page.
ANTI_CUE = re.compile(
    r"\b(paid-?up|share capital|authorised capital|turnover|revenue from operations"
    r"|net worth|market capitali[sz]ation|order book|outstanding orders"
    r"|previous year|corresponding quarter|face value|authorized capital"
    # What a company says about its orders in general, beside the one order
    # the filing is about.
    r"|order inflows?|order intake|order backlog|unexecuted orders?|YTD"
    r"|year[- ]to[- ]date|bid pipeline|tender pipeline|L1 position"
    r"|favou?rably (?:placed|positioned)"
    # Money in an order letter that is not the order.
    r"|bank guarantee|performance guarantee|performance security|security deposit"
    r"|earnest money|net profit|profit after tax|tariff of|per unit)\b", re.I)

# A size band is not a size: "Rs 100 crore and above", "below Rs 50 crore".
_BAND_BEFORE = re.compile(r"\b(?:below|less than|up ?to|not exceeding|under)\s*(?:rs\.?|inr|₹)?\s*$", re.I)
_BAND_AFTER = re.compile(r"^\s*(?:and above|or above|or more|and more|to below|to less than)\b", re.I)

# Where a sentence ends. A full stop only counts when it is not a decimal
# point and not the tail of an abbreviation the next token is the object
# of. "Rs. 5,000 crore" is one clause, not two, and splitting it there detaches
# the figure from the words that say what it is — which is how a company's
# paid-up capital gets read as the value of its order.
_SENT_BREAK = re.compile(r"(?:(?<=[.;:!?])\s+(?!\d))|\n")
# A clause ends at a stop that something other than a number follows. "Rs. "
# at the very end of the text before a figure is the figure's own prefix.
_CLAUSE_END = re.compile(r"(?<!\bRs)(?<!\bNo)[.;!?•]\s+(?=[^\d\s])")

_UNIT = r"(?:crores?|cr\b|lakhs?|lacs?|millions?|mn\b|billions?|bn\b)"

# An amount written out in rupees, with no unit after it: "Rs. 1,24,00,00,000",
# "Rs.90740000/-". This is how most small companies state an order, and they
# are the companies an order is largest against.
PLAIN_RUPEES = re.compile(
    r"(?:rs\.?|inr|₹)\s*((?:\d{1,3}(?:,\d{2,3})+|\d{6,})(?:\.\d+)?)"
    r"(?![,.]?\d)(?!\s*(?:/-\s*)?" + _UNIT + ")", re.I)

_DOLLARS = [
    (re.compile(r"(?:usd|us\$|\$)\s*((?:\d{1,3}(?:,\d{2,3})*|\d+)(?:\.\d+)?)\s*(?:million|mn\b)", re.I), 0.1),
    (re.compile(r"(?:usd|us\$|\$)\s*((?:\d{1,3}(?:,\d{2,3})*|\d+)(?:\.\d+)?)\s*(?:billion|bn\b)", re.I), 100.0),
]


def _sentence_spans(text: str):
    """
    Sentence boundaries for the whole document, computed once.

    Deliberately not done per match with re's pos/endpos arguments: those
    truncate the string the pattern can see, so a lookahead sitting at the
    boundary succeeds against nothing and "Rs. 5,000 crore" splits after the
    "Rs." after all. That detaches every figure from the words describing it,
    which is precisely how a company's paid-up capital gets read as the value
    of its order.
    """
    spans, left = [], 0
    for m in _SENT_BREAK.finditer(text):
        if m.end() > left:
            spans.append((left, m.start()))
            left = m.end()
    spans.append((left, len(text)))
    return spans


def _sentence_at(text: str, spans, start: int) -> str:
    for a, b in spans:
        if a <= start < b:
            return text[a:b]
    return text[max(0, start - 200):start + 200]


def _patterns():
    """The rupee patterns, borrowed from social_posts rather than rewritten."""
    import social_posts
    return social_posts.MONEY_PATTERNS


def _is_foreign(pattern) -> bool:
    return "usd" in pattern.pattern.lower() or r"\$" in pattern.pattern


def _flat(text: str) -> str:
    return re.sub(r"\s+", " ", text or "")


# In the size row of the table an amount may carry no "Rs." at all:
# "10,99,79,910 (Rupees Ten Crore Ninety-Nine Lakh ...)".
_BARE_IN_TABLE = re.compile(r"(?<![\d,.])(\d{1,3}(?:,\d{2,3}){2,}(?:\.\d+)?)(?![,.]?\d)"
                            r"\s*(?:/-)?\s*\(?\s*(?:rupees|rs\b)", re.I)


def _figures(text: str, sizes=()):
    """Every money figure in the text: (start, end, crore, in dollars)."""
    out = []
    for a, b, _t in sizes:
        for m in _BARE_IN_TABLE.finditer(text, a, b):
            try:
                out.append((m.start(1), m.end(1), float(m.group(1).replace(",", "")) / 1e7, False))
            except ValueError:
                continue
    for rx, mult in _patterns():
        if _is_foreign(rx):
            continue                    # dollars are read below, at USD_INR
        for m in rx.finditer(text):
            try:
                out.append((m.start(), m.end(), float(m.group(1).replace(",", "")) * mult, False))
            except (ValueError, IndexError):
                continue
    for m in PLAIN_RUPEES.finditer(text):
        try:
            rupees = float(m.group(1).replace(",", ""))
        except ValueError:
            continue
        if rupees >= 100000:            # under a lakh is a fee, a rate, a clause number
            out.append((m.start(), m.end(), rupees / 1e7, False))
    for rx, mult in _DOLLARS:
        for m in rx.finditer(text):
            try:
                out.append((m.start(), m.end(),
                            float(m.group(1).replace(",", "")) * mult * USD_INR, True))
            except ValueError:
                continue
    return out


def _around(text: str, start: int, end: int):
    """
    The sentence a figure sits in, whole words, for a reader to check — and
    whether it IS a sentence, which a line of letterhead is not.
    """
    left = _flat(text[max(0, start - 260):start])
    cut = [m.end() for m in _CLAUSE_END.finditer(left)]
    whole = bool(cut) or start <= 260
    if cut:
        left = left[cut[-1]:]
    elif start > 260:
        left = "…" + left[-110:].split(" ", 1)[-1]
    right = _flat(text[end:end + 260])
    stop = _CLAUSE_END.search(right)
    if stop:
        right = right[:stop.start() + 1]
    elif len(text) > end + 260:
        right = right[:110].rsplit(" ", 1)[0] + "…"
        whole = False
    return (left + _flat(text[start:end]) + right).strip(), whole


def tidy(text: str) -> str:
    """
    A filing's text with the damage a PDF does to it undone: ligatures split
    back into letters, the two glyphs some fonts print "ti" and "tt" as, and
    the words of the prescribed table that a justified column breaks in two.
    """
    if not text:
        return ""
    import unicodedata
    text = unicodedata.normalize("NFKC", text).replace("Ɵ", "ti").replace("Ʃ", "tt")
    text = re.sub(r"\b(considerati)\s+(ons?)\b", r"\1\2", text, flags=re.I)
    return re.sub(r"\b(condition)\s+(s)\b", r"\1\2", text, flags=re.I)


def order_value_cr(text: str, company: str = ""):
    """
    The order's value in crore, with the basis for believing it.

    Returns a dict, or None when the filing does not state one. Never a guess.
    """
    if not text:
        return None
    text = tidy(text)
    spans = _sentence_spans(text)
    sizes = disclosure(text, company).get("_sizes") or []
    hits = []
    for start, end, val, foreign in _figures(text, sizes):
        if val <= 0 or val > 5_000_000:          # > Rs 50 lakh crore is a typo
            continue
        # Whitespace is flattened before a phrase is looked for: a PDF wraps
        # "size of the / order" across two lines, and "executable order /
        # book" too.
        before = _flat(text[max(0, start - NEAR):start])
        after = _flat(text[end:end + 90])
        cut = [m.end() for m in _CLAUSE_END.finditer(before)]
        clause = before[cut[-1]:] if cut else before[-160:]
        # A number in a sentence about paid-up capital is not the order.
        # Scoped to the SENTENCE, not a character window: a filing that
        # states its share capital one sentence before the order would
        # otherwise disqualify the order too, which is the exact shape of
        # a real disclosure.
        if ANTI_CUE.search(_sentence_at(text, spans, start)) or ANTI_CUE.search(clause):
            continue
        if _BAND_BEFORE.search(clause) or _BAND_AFTER.search(after):
            continue
        table = next((i for i, (a, b, _t) in enumerate(sizes) if a <= start < b), None)
        excerpt, whole = _around(text, start, end)
        hits.append({
            "cr": round(val, 2),
            "near_cue": bool(VALUE_CUE.search(before) or VALUE_CUE.search(after[:70])),
            "table": table, "foreign": foreign, "at": start,
            "excerpt": excerpt, "whole": whole,
        })
    if not hits:
        return None

    def prose(h):
        # A sentence is mostly lower-case letters. A title, an address block
        # and a table header are not.
        e = h["excerpt"]
        return round(sum(c.islower() for c in e) / float(len(e) or 1), 2)

    def pick(pool):
        # The largest; among equals, the one in a sentence over the one in a
        # title or a letterhead, so the words shown beside it can be read.
        return max(pool, key=lambda h: (h["cr"], h["whole"], prose(h), -h["at"]))

    tabled = [h for h in hits if h["table"] is not None]
    cued = [h for h in hits if h["near_cue"]]
    total = None
    if tabled:
        best = pick(tabled)
        basis = "stated as the size of the order in the filing's disclosure table"
        # A filing for several orders has a table for each, or one table with
        # a column for each. Their sum is the filing's value when the filing
        # has one table per order, or says that sum itself.
        per = {}
        for h in tabled:
            per[h["table"]] = max(per.get(h["table"], 0), h["cr"])
        apart = sorted(set(per.values()))
        if len(per) > 1 and len(apart) > 1:
            total = round(sum(apart), 2)
            basis = "the sum of the %d orders this filing discloses" % len(apart)
        else:
            inside = sorted({h["cr"] for h in tabled})
            said = [h for h in cued if h["table"] is None and len(inside) > 1
                    and abs(h["cr"] - sum(inside)) <= 0.01 * sum(inside)]
            if said:
                best = pick(said)
                basis = "stated in the filing as the total of the orders it discloses"
        if best["table"] is not None:
            best = dict(best, excerpt=sizes[best["table"]][2])
    elif cued:
        best = pick(cued)
        basis = "stated next to an order-value phrase in the filing"
    else:
        best = pick(hits)
        basis = ("largest rupee figure in the filing; the filing does not label "
                 "it as the order value")
    if best["foreign"]:
        # "USD 272 million (INR 2,332 crore)": the company's own conversion
        # beats an assumed rate.
        own = [h for h in hits if not h["foreign"] and abs(h["at"] - best["at"]) < 200
               and 0.7 * best["cr"] <= h["cr"] <= 1.3 * best["cr"]]
        if own:
            best = min(own, key=lambda h: abs(h["at"] - best["at"]))
    return {
        "value_cr": total if total is not None else best["cr"],
        "basis": basis,
        "confident": bool(tabled or cued),
        "currency_converted": best["foreign"],
        "fx_rate": USD_INR if best["foreign"] else None,
        "excerpt": best["excerpt"][:420],
    }


# ---------------------------------------------------------------------------
# What the order is
#
# Since 2023 an order disclosure carries a table SEBI prescribes: who awarded
# it, what it is for, by when it is to be executed, and its size. The exchange
# headline is one sentence of boilerplate ("has informed the Exchange about
# Bagging/Receiving of orders/contracts"), so the table is where a reader finds
# out what actually happened — and it is the company's own wording throughout.
# ---------------------------------------------------------------------------

_OC = (r"(?:work\s+)?order\s*(?:\(\s*s\s*\))?\s*,?\s*/?\s*"
       r"(?:con\w{1,3}act\s*(?:\(\s*s\s*\))?)?")
_FIELDS = [
    ("customer", r"name\s+of\s+(?:the\s+)?(?:entity\s+awarding|part(?:y|ies)\s+to)\s+the\s+" + _OC),
    ("terms", r"significant\s+terms\s+(?:and|&)\s+conditions?\s+(?:(?:of|or)\s+)?(?:the\s+)?"
              + _OC + r"(?:\s*awarded)?(?:\s*,?\s*in\s+brief)?"),
    ("origin", r"awarded\s+by\s+(?:a\s+)?domestic\s*(?:/|or)\s*international\s+entity"),
    ("nature", r"nature\s+of\s+(?:the\s+)?" + _OC),
    ("where", r"whether\s+domestic\s+or\s+international"),
    ("period", r"time\s+period\s+by\s+which\s+the\s+" + _OC + r"\s*(?:is\s+)?to\s+(?:be\s+)?executed"),
    ("size", r"broad\s+(?:commercial\s+)?considerations?\s+(?:or|and|&|/)\s+size\s+of\s+(?:the\s+)?"
             + _OC + r"(?:\s*inclusive\s+tax)?"
             r"|broad\s+consideration\s+" + _OC + r"\s*or\s+size\s+of\s+the\s+" + _OC
             + r"|size\s+of\s+the\s+" + _OC + r"\s*/\s*broad\s+consideration"
             r"|size\s+of\s+order\s*:"),
    ("promoter", r"whether\s+(?:the\s+)?promoter"),
    ("related", r"(?:would\s+fall|falls?)\s+within\s+related\s+party"),
]
_FIELDS_C = [(k, re.compile(v, re.I)) for k, v in _FIELDS]
# What is left of a table row once its label is taken off: the punctuation
# after the label, and the number of the next row.
_LEAD = re.compile(r"^[\s;:.\-–—?]+")
_ROW_NO = r"(?:\(?[ivx]{1,4}\)|\(?[a-j]\)|[a-j]\.|\d{1,2}[.)]|s(?:r|l)?\.?\s*no\.?)"
_TAIL = re.compile(r"(?:\s+" + _ROW_NO + r")+\s*$|\s+whether$", re.I)
# Rows numbered "7" or "g" with nothing after the number. Taken off only in a
# table that numbers its rows that way: "wagon type ACT 3" ends in a number
# that is part of what was ordered.
_TAIL_BARE = re.compile(r"\s+(?:\d{1,2}|[a-j])$")
_BARE_BEFORE = re.compile(r"(?:^|\s)(?:\d{1,2}|[a-j])\s*$")
# Where the next row, or the foot of the page, has run into a value.
_SPILL = re.compile(
    r"\s+(?:" + _ROW_NO + r"|\d{1,2}|[a-j])\s+(?:significant|whether|nature|time period|broad|name of)\b"
    r"|\s+(?:this is for your information|yours (?:faithfully|sincerely|truly)|thanking you"
    r"|for and on behalf|reg(?:d|istered)\.?\s+office|corporate office|\bCIN\b|to,\s)", re.I)
_NOTHING = re.compile(r"^(?:n\.?\s*a\.?|not applicable|nil|none|no|-+|—)\.?$", re.I)
SECRET = re.compile(r"confidential|cannot be disclosed|not (?:be(?:ing)? )?disclos\w+ (?:due|owing|as per)"
                    r"|non[- ]disclosure", re.I)


_OWN_HEADER = re.compile(r"\s+(?:[A-Z][A-Z&.()]+\s+){1,6}(?:LIMITED|LTD)\b")


def _cell(raw: str, limit: int, company: str = "", bare: bool = False) -> str:
    val = re.sub(r"^awarded by\s*[-:]?\s*", "", _LEAD.sub("", _flat(raw)), flags=re.I)
    spill = _SPILL.search(val)
    if spill:
        val = val[:spill.start()]
    # The filer's own name in a cell is the letterhead of the next page.
    own = (company or "").strip()
    at = val.lower().find(own.lower()) if len(own) > 5 else -1
    head = _OWN_HEADER.search(val)
    for cut in (at, head.start() if head else -1):
        if cut > 12:
            val = val[:cut]
    val = _TAIL.sub("", val.strip())
    if bare:
        val = _TAIL_BARE.sub("", val)
    val = val.strip(" ;:,")
    # A two-column table read straight across says everything twice.
    twice = re.match(r"^(.{6,}?)\s+\1$", val)
    if twice:
        val = twice.group(1)
    if len(val) > limit:
        val = val[:limit].rsplit(" ", 1)[0].rstrip(" ,;:(") + "…"
    return "" if _NOTHING.match(val) else val


def disclosure(text: str, company: str = "") -> dict:
    """
    The rows of the prescribed table, in the company's words: customer,
    nature, period, size. Empty when the filing does not carry the table.

    A filing for several orders repeats the table. The first one is described;
    `_sizes` holds the size row of every one, as (start, end, text), because
    the value of the filing is all of them.
    """
    if not text:
        return {}
    found = []
    for key, rx in _FIELDS_C:
        for m in rx.finditer(text):
            found.append((m.start(), m.end(), key))
    if len({k for _a, _b, k in found}) < 3:
        return {}
    found.sort()
    bare = sum(1 for a, _b, _k in found if _BARE_BEFORE.search(text[max(0, a - 6):a])) >= 2
    out, sizes, customers = {}, [], []
    for i, (_a, end, key) in enumerate(found):
        nxt = found[i + 1][0] if i + 1 < len(found) else min(len(text), end + 320)
        if nxt < end:                            # one label inside another
            continue
        if key == "size":
            sizes.append((end, nxt, _cell(text[end:nxt], 260, company, bare)))
        if key not in ("customer", "nature", "period", "size"):
            continue
        val = _cell(text[end:nxt], 110 if key == "customer" else 200, company, bare)
        if key == "customer" and val and val.lower() not in [c.lower() for c in customers]:
            customers.append(val)
        if val and key not in out:
            out[key] = val
    out["_sizes"] = sizes
    if len(customers) > 1:
        out["customer"] = "%s and %d more" % (customers[0], len(customers) - 1)
    return out


# Not an order win, whatever the word "order" is doing in the headline.
NOT_A_WIN = re.compile(
    r"order[- ]in[- ](?:appeal|original)|income[- ]?tax|tax (?:authorit|department|demand)"
    r"|\bGST (?:order|demand|authorit\w+|department|notice)"
    r"|rectification order|assessment order|demand order|penalt|show[- ]cause|adjudicat"
    r"|tribunal|\bNCLT\b|\bNCLAT\b|court order|order (?:of|from|by) the (?:hon\S*ble )?\w* ?court"
    r"|commissioner of (?:central|income|state|customs|gst)|commissionerate"
    r"|stay order|\bSEBI order|settlement order", re.I)

_L1 = re.compile(r"\bL[- ]?1\b|lowest bidder", re.I)
_MOU = re.compile(r"memorandum of understanding|\bMoU\b", re.I)
_AWARD = re.compile(r"letters? of (?:award|acceptance)|\bLoA\b|work order|purchase order"
                    r"|notification of award|has been awarded|have been awarded"
                    r"|receiv\w+ (?:an? |the )?(?:new |additional |repeat )?order|secured|bagged", re.I)
# A filing about an order already filed: an update, a correction, a resend.
_UPDATE = re.compile(r"^\s*(?:update|updates|clarification|corrigendum|addendum)\b"
                     r"|update on (?:our|the) earlier|revised submission"
                     r"|(?:company'?s|our) (?:earlier )?intimation dated", re.I)
_SUBJECT = re.compile(r"\bsub(?:ject)?\.?\s*:\s*(.{0,160})", re.I)
_KINDS = [
    ("Lowest bidder (L1)", _L1),
    ("Memorandum of understanding", _MOU),
    ("Letter of award", re.compile(r"letters? of (?:award|acceptance)|\bLoA\b|notification of award", re.I)),
    ("Letter of intent", re.compile(r"letters? of intent|\bLoI\b", re.I)),
    ("Purchase order", re.compile(r"purchase order", re.I)),
    ("Work order", re.compile(r"work ?order", re.I)),
    ("Power purchase agreement", re.compile(r"power purchase agreement", re.I)),
    ("Contract", re.compile(r"\bcontract\b", re.I)),
]

_ORG = (r"(?:Limited|Ltd\.?|Corporation|Authority|Railways?|Nigam|Board"
        r"|Ministry of [A-Z][a-z]+|Government of [A-Z][a-z]+)")
_FROM = re.compile(r"\b(?:from|by)\s+(?:M/[sS]\.?\s*)?((?:[A-Z][A-Za-z0-9&.'’\-]*\s+){0,7}?" + _ORG + r")")
_AWARDED_BY = re.compile(r"((?:[A-Z][A-Za-z0-9&.'’\-]*\s+){1,7}?" + _ORG + r")\s+has\s+awarded")
_NOT_A_CUSTOMER = re.compile(r"\bBSE\b|stock exchange|exchange of india|securities and exchange"
                             r"|exchange board", re.I)

STAGES = ("order", "l1", "mou", "update")


def describe(text: str, headline: str = "", company: str = "") -> dict:
    """
    What a filing says the order is, beyond its value: the stage it is at, who
    awarded it, what it is for and by when. Everything is the company's own
    wording or nothing; no field is inferred.
    """
    text = tidy(text)
    head = _flat(text[:2600])
    table = disclosure(text, company)
    subject = _SUBJECT.search(head)
    about = "%s %s" % (headline or "", subject.group(1) if subject else "")
    both = "%s %s" % (about, head)

    if _UPDATE.search(about):
        stage = "update"
    elif _L1.search(about) or (_L1.search(head) and not _AWARD.search(head)):
        stage = "l1"
    elif _MOU.search(about) or _MOU.search(table.get("nature") or ""):
        stage = "mou"
    else:
        stage = "order"
    firm = {"Lowest bidder (L1)": "l1", "Memorandum of understanding": "mou"}
    kind = next((name for name, rx in _KINDS
                 if firm.get(name, stage) == stage and rx.search(both)), None)

    customer = table.get("customer")
    if not customer:
        own = (company or "").lower().replace("limited", "").replace("ltd", "").strip(" .")
        for rx in (_AWARDED_BY, _FROM):
            for m in rx.finditer(head):
                name = m.group(1).strip()
                if _NOT_A_CUSTOMER.search(name) or (own and own in name.lower()):
                    continue
                customer = name
                break
            if customer:
                break
    sizes = table.get("_sizes") or []
    size = table.get("size") or (sizes[0][2] if sizes else None)
    return {
        "stage": stage, "kind": kind,
        "customer": customer or None,
        "nature": table.get("nature"),
        "period": table.get("period"),
        # The size as the company gave it, for the orders it sized in
        # megawatts or tonnes rather than rupees.
        "size_text": size or None,
        "confidential": bool(SECRET.search(size or "")),
    }


# ---------------------------------------------------------------------------
# The company the order is measured against
# ---------------------------------------------------------------------------

_facts = {"at": 0.0, "by": {}}


def _pos(v):
    try:
        f = float(v)
        return f if f == f and f > 0 else None
    except (TypeError, ValueError):
        return None


def company_facts(symbol: str) -> dict:
    """
    Market value and last full year's sales, in crore, from the tables the
    screener already keeps: price times issued shares, and revenue as filed.

    This is the first place asked, because it is the one that answers. The
    price feeds below it are refused from the server's address, and for months
    every order on this page was listed with no market value and so none could
    ever be called WOW.
    """
    sym = (symbol or "").strip().upper()
    if not sym:
        return {}
    now = time.time()
    with _lock:
        stale = now - _facts["at"] > 3600 or not _facts["by"]
    if stale:
        by = {}
        try:
            import fundamentals_query
            rows, _built = fundamentals_query.snapshot()
            by = {str(r.get("symbol") or "").upper(): r for r in (rows or [])}
        except Exception:
            by = {}
        with _lock:
            if by or not _facts["by"]:
                _facts["by"] = by
            _facts["at"] = now
    with _lock:
        row = _facts["by"].get(sym) or {}
    return {"market_cap_cr": _pos(row.get("market_cap")), "sales_cr": _pos(row.get("sales")),
            "sales_year": row.get("fy") or None}


def market_cap_cr(symbol: str):
    """
    Market capitalisation in crore: the stored tables, then Dhan, then the
    provider.

    Cached for the life of the process: it moves with the price, and a figure
    that is a day stale changes "12% of market value" to "12.4% of market
    value", which is not a difference this feature turns on.
    """
    if not symbol:
        return None
    with _lock:
        hit = _mcap_cache.get(symbol)
    if hit and time.time() - hit[0] < 6 * 3600:
        return hit[1]

    value = None
    try:
        value = company_facts(symbol).get("market_cap_cr")
    except Exception:
        value = None
    if value is None:
        try:
            import social_posts
            value = social_posts._market_cap_cr(symbol)
        except Exception:
            value = None
    if value is None:
        try:
            from data_source import resolve
            t, _ = resolve(symbol)
            raw = (getattr(t, "info", None) or {}).get("marketCap")
            if raw:
                value = float(raw) / 1e7        # rupees -> crore
        except Exception:
            value = None
    with _lock:
        _mcap_cache[symbol] = (time.time(), value)
    return value


# ---------------------------------------------------------------------------
# Fiscal quarters — the Indian ones
# ---------------------------------------------------------------------------

def fiscal_quarter(day: dt.date):
    """(label, start, end) for the Indian fiscal quarter a date falls in."""
    y, m = day.year, day.month
    if m <= 3:
        q, start, fy = "Q4", dt.date(y, 1, 1), y
    elif m <= 6:
        q, start, fy = "Q1", dt.date(y, 4, 1), y + 1
    elif m <= 9:
        q, start, fy = "Q2", dt.date(y, 7, 1), y + 1
    else:
        q, start, fy = "Q3", dt.date(y, 10, 1), y + 1
    end = dt.date(start.year + (1 if start.month == 10 else 0),
                  (start.month + 3 - 1) % 12 + 1, 1) - dt.timedelta(days=1)
    return "%s FY%02d" % (q, fy % 100), start, end


def previous_quarter(day: dt.date):
    _, start, _ = fiscal_quarter(day)
    return fiscal_quarter(start - dt.timedelta(days=1))


# ---------------------------------------------------------------------------
# The scan
# ---------------------------------------------------------------------------

def _order_items(days: int):
    """Order announcements from the feed the app already polls."""
    try:
        import announcements
    except Exception:
        return [], "The announcements feed is not available."
    try:
        announcements.poll(days=days)
    except Exception as e:
        return [], "Could not refresh announcements: %s" % str(e)[:90]
    return list(announcements.orders(days)), ""


def _as_date(iso):
    try:
        return dt.datetime.fromisoformat(str(iso)).astimezone(IST).date()
    except Exception:
        return None


def read_filing(item: dict, text: str) -> dict:
    """
    One order filing as the page shows it. `text` is the filing's text, or
    None when it has not been read; nothing here touches the network.
    """
    day = _as_date(item.get("at"))
    symbol = (item.get("symbol") or "").strip().upper()
    company = item.get("company") or ""
    headline = item.get("headline") or ""
    row = {
        "symbol": symbol or None, "company": company, "headline": headline,
        "at": item.get("at"),
        "date": day.isoformat() if day else None,
        "quarter": fiscal_quarter(day)[0] if day else None,
        "pdf": item.get("pdf"),
        "read": bool(text),
        "stage": "order", "kind": None, "customer": None, "nature": None,
        "period": None, "size_text": None,
        "value_cr": None, "value_state": "unread" if not text else "not_stated",
        "value_basis": None, "value_confident": False,
        "currency_converted": False, "fx_rate": None, "excerpt": None,
        "market_cap_cr": None, "pct_of_market_cap": None,
        "sales_cr": None, "sales_year": None, "pct_of_sales": None,
        "months_of_sales": None,
        "wow": False, "outsized": False, "filings": 1, "reader": READER,
    }
    # The headline is read as well as the document: a small company often
    # puts the amount in the subject line and attaches a scan.
    found = order_value_cr(text, company) if text else None
    if not found and headline:
        found = order_value_cr(headline, company)
        if found:
            found["basis"] = "stated in the exchange's headline for the filing"
    told = describe(text or headline, headline, company)
    row.update({k: told[k] for k in ("stage", "kind", "customer", "nature", "period", "size_text")})
    if found:
        row.update({
            "value_cr": found["value_cr"], "value_state": "stated",
            "value_basis": found["basis"], "value_confident": found["confident"],
            "currency_converted": found["currency_converted"],
            "fx_rate": found.get("fx_rate"), "excerpt": found["excerpt"],
        })
    elif text and told["confidential"]:
        row["value_state"] = "confidential"
    return row


def size_up(row: dict) -> dict:
    """The order against the company: market value, and a year of its sales."""
    if not row.get("value_cr") or not row.get("symbol"):
        return row
    facts = {}
    try:
        facts = company_facts(row["symbol"]) or {}
    except Exception:
        facts = {}
    cap = facts.get("market_cap_cr") or market_cap_cr(row["symbol"])
    if cap and cap > 0:
        row["market_cap_cr"] = round(cap, 2)
        row["pct_of_market_cap"] = round(100.0 * row["value_cr"] / cap, 2)
        # WOW is said of an order, not of a bid that may yet lose or a
        # memorandum that binds nobody, and not twice of the same order.
        row["wow"] = row["stage"] == "order" and row["pct_of_market_cap"] >= WOW_MIN_PCT
        # An order worth more than the whole company happens, to small
        # companies. It is also what a misread figure looks like, so the row
        # says to open the filing.
        row["outsized"] = row["pct_of_market_cap"] >= 100
    sales = facts.get("sales_cr")
    if sales and sales > 0:
        row["sales_cr"] = round(sales, 2)
        row["sales_year"] = facts.get("sales_year")
        row["pct_of_sales"] = round(100.0 * row["value_cr"] / sales, 1)
        row["months_of_sales"] = round(12.0 * row["value_cr"] / sales, 1)
    return row


def _same_order(a: dict, b: dict) -> bool:
    if not a.get("symbol") or a.get("symbol") != b.get("symbol"):
        return False
    va, vb = a.get("value_cr"), b.get("value_cr")
    return bool(va and vb and abs(va - vb) <= 0.005 * max(va, vb))


def merge_repeats(rows):
    """
    One row per order. A company files the same order more than once — the
    letter and then the press release, the lowest bid and then the award — and
    counting each would double what it won. The firmest filing is kept, then
    the latest, and it says how many filings it stands for.
    """
    rank = {"order": 0, "mou": 1, "l1": 2, "update": 3}
    kept = []
    newest = sorted(rows, key=lambda r: r["at"] or "", reverse=True)
    for r in sorted(newest, key=lambda r: rank.get(r["stage"], 9)):
        twin = next((k for k in kept if _same_order(k, r)), None)
        if twin is None:
            kept.append(r)
            continue
        twin["filings"] += r.get("filings", 1)
        # Same stage: the later filing is the fuller one as often as not, but
        # the one with a customer and a nature is the one worth showing.
        if rank.get(r["stage"]) == rank.get(twin["stage"]):
            for k in ("customer", "nature", "period", "kind"):
                if not twin.get(k) and r.get(k):
                    twin[k] = r[k]
    return kept


def _order(rows):
    """WOW first, then by size against the company, then by rupees, then new."""
    def key(r):
        pct, val = r.get("pct_of_market_cap"), r.get("value_cr")
        firm = r.get("stage") == "order"
        return (0 if r.get("wow") else 1,
                0 if firm else 1,
                0 if pct is not None else (1 if val is not None else 2),
                -(pct or 0), -(val or 0),
                "" if r.get("at") is None else "".join(chr(255 - ord(c)) for c in r["at"]))
    return sorted(rows, key=key)


_scan_lock = threading.Lock()
_reading = {"on": False, "started": 0.0, "error": ""}


def scan(days: int = 7, force: bool = False) -> dict:
    """
    Recent order wins, sized against the company that won them.

    Every row carries the filing it was read from, the excerpt the value came
    out of, and whether the filing labelled that figure as the order's value.
    Slow when filings have to be fetched, so a page is answered by `feed`,
    which runs this behind the answer.
    """
    now = time.time()
    if not force and _cache["rows"] and now - _cache["at"] < CACHE_TTL:
        return _payload(_cache["rows"], _cache["note"])

    with _scan_lock:
        orders, note = _order_items(days)
        rows, read = [], 0

        try:
            import filings_text
            can_read = filings_text.available()
        except Exception:
            filings_text, can_read = None, False

        for item in orders:
            if NOT_A_WIN.search(item.get("headline") or ""):
                continue
            text = None
            if can_read and item.get("pdf"):
                text = filings_text.cached(item["pdf"])
                if text is None and read < MAX_PDFS:
                    read += 1
                    text = filings_text.extract(item["pdf"])
            rows.append(size_up(read_filing(item, text)))

        rows = _order(merge_repeats(rows))
        if not can_read:
            note = ("The PDF reader is not installed on this instance, so order "
                    "values could not be read from the filings.")
        # Every live scan also writes down what it saw. This is how the ledger
        # fills up in normal operation — the quarter comparison reads from
        # there, not from a feed that only remembers three days.
        try:
            record(rows)
            today = dt.datetime.now(IST).date()
            mark_covered([today - dt.timedelta(days=b) for b in range(days)])
            reread()
        except Exception:
            pass
        with _lock:
            _cache.update({"at": time.time(), "rows": rows, "note": note})
        return _payload(rows, note)


def _scan_behind(days):
    try:
        scan(days=days, force=True)
        _reading["error"] = ""
    except Exception as e:
        _reading["error"] = "The filings could not be read just now: %s" % str(e)[:90]
    finally:
        _reading["on"] = False


def feed(days: int = 7, refresh: bool = False) -> dict:
    """
    What a page is given: whatever has been read, at once.

    Reading the filings takes as long as the exchange takes to hand over forty
    PDFs, which used to be how long the page sat on "Reading the filings…".
    Now a stale list is returned as it is while a fresh one is read behind it,
    and `reading` with `poll_seconds` tells an open page to ask again.
    """
    now = time.time()
    with _lock:
        rows, note, at = list(_cache["rows"]), _cache["note"], _cache["at"]
    # Fresh by when it was last read, not by whether anything was found: a
    # week with no orders must not be read again on every visit. And a read
    # that has just failed is not retried by every page that asks.
    fresh = at > 0 and now - at < CACHE_TTL
    failed = bool(_reading["error"]) and now - _reading["started"] < 60
    if (refresh or not fresh) and not _reading["on"] and not failed:
        _reading.update(on=True, started=now)
        threading.Thread(target=_scan_behind, args=(days,), daemon=True,
                         name="wow-scan").start()
    out = _payload(rows, note)
    out["reading"] = bool(_reading["on"])
    out["poll_seconds"] = 4 if _reading["on"] else None
    out["read_at"] = (dt.datetime.fromtimestamp(at, IST).isoformat(timespec="seconds")
                      if at else None)
    if _reading["error"] and not _reading["on"]:
        out["note"] = out["note"] or _reading["error"]
    return out


def _payload(rows, note):
    firm = [r for r in rows if r.get("stage", "order") == "order"]
    priced = [r for r in rows if r["value_cr"] is not None]
    wow = [r for r in rows if r["wow"]]
    state = lambda r: r.get("value_state") or ("stated" if r["value_cr"] is not None else "not_stated")
    return {
        "available": True,
        "threshold_pct": WOW_MIN_PCT,
        "rows": rows,
        "counts": {
            "orders": len(rows),
            "firm": len(firm),
            "with_value": len(priced),
            "sized": sum(1 for r in rows if r.get("pct_of_market_cap") is not None),
            "value_not_disclosed": sum(1 for r in rows if state(r) in ("not_stated", "confidential")),
            "unread": sum(1 for r in rows if state(r) == "unread"),
            "not_firm": len(rows) - len(firm),
            "wow": len(wow),
        },
        "note": note or "",
        "source": ("Exchange corporate announcements (BSE, or NSE when BSE is "
                   "unreachable), Regulation 30. Order values "
                   "are read from the filed document, not the headline."),
        "explain": (
            "An order is called WOW when its disclosed value is at least %g%% "
            "of the company's market capitalisation. Orders whose value the "
            "company did not disclose are listed but never ranked, and never "
            "given an assumed figure." % WOW_MIN_PCT),
    }


# ---------------------------------------------------------------------------
# Quarter on quarter
# ---------------------------------------------------------------------------

def quarter_comparison(today: dt.date = None) -> dict:
    """
    Disclosed order inflow this fiscal quarter against the previous one.

    Read from the ledger, not from the live feed: the announcements feed keeps
    three days, so a quarter compared out of it would be three days against
    nothing. The response says what date recording actually started, because
    a quarter that began before this instance did is a partial quarter and a
    reader is entitled to know that before drawing a conclusion from it.

    Only orders whose value the company disclosed are counted, which makes
    every total a floor rather than an estimate. How many were left out is
    reported alongside.
    """
    today = today or dt.datetime.now(IST).date()
    this_label, this_start, this_end = fiscal_quarter(today)
    prev_label, prev_start, prev_end = previous_quarter(today)
    since = recording_since()

    def bucket(start, end, label):
        seen = [r for r in history(start, end) if (r.get("stage") or "order") != "not_order"]
        # A value read by an older reader is not added up until this one has
        # read the filing again; a bid, a memorandum and a second filing of
        # the same order are not order inflow.
        stale = [r for r in seen if (r.get("reader") or 1) < READER]
        got = merge_repeats([dict(r, stage=r.get("stage") or "order", filings=1)
                             for r in seen])
        valued = [r for r in got if r.get("value_cr") and (r.get("reader") or 1) >= READER
                  and r["stage"] == "order"]
        wanted = _business_days(start, end, today)
        have = covered_days(start, end)
        missing = [d for d in wanted if d.isoformat() not in have]
        # A handful of missing days is a holiday or a blip; a quarter that is
        # mostly unseen is not a quarter. The line is drawn at a tenth.
        partial = bool(wanted) and len(missing) > max(2, len(wanted) // 10)
        return {
            "label": label,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "orders": len(got),
            "with_value": len(valued),
            "value_not_disclosed": len(got) - len(valued),
            "total_cr": round(sum(r["value_cr"] for r in valued), 2) if valued else 0.0,
            "companies": len({r["symbol"] for r in got if r.get("symbol")}),
            "biggest": max(
                ({"symbol": r["symbol"], "company": r["company"],
                  "value_cr": r["value_cr"],
                  "pct_of_market_cap": r["pct_of_market_cap"]} for r in valued),
                key=lambda r: r["value_cr"], default=None),
            # A quarter that started before this instance began recording is
            # not a quarter, and comparing against it would understate it.
            "partial": partial,
            "trading_days": len(wanted),
            "days_not_recorded": len(missing),
            "awaiting_reread": len(stale),
        }

    now_b = bucket(this_start, this_end, this_label)
    prev_b = bucket(prev_start, prev_end, prev_label)
    change = None
    if prev_b["total_cr"] > 0 and not prev_b["partial"]:
        change = round(100.0 * (now_b["total_cr"] - prev_b["total_cr"])
                       / prev_b["total_cr"], 1)

    comparable = not (now_b["partial"] or prev_b["partial"])
    return {
        "this_quarter": now_b,
        "previous_quarter": prev_b,
        "change_pct": change,
        "change_cr": round(now_b["total_cr"] - prev_b["total_cr"], 2),
        "comparable": comparable,
        "recording_since": since,
        "caveat": (
            "Counts only orders whose value the company disclosed, so every "
            "total is a floor on order inflow rather than a complete order "
            "book." + ("" if comparable else
                       " One of these quarters began before this service "
                       "started recording, so the two are not yet comparable "
                       "and no percentage change is shown.")
            + ("" if not (now_b["awaiting_reread"] or prev_b["awaiting_reread"]) else
               " %d earlier filings are still to be read again by the current "
               "reader and are not in these totals yet."
               % (now_b["awaiting_reread"] + prev_b["awaiting_reread"]))),
    }


# ---------------------------------------------------------------------------
# The ledger
#
# The announcements feed keeps three days. A quarter-on-quarter comparison over
# a three-day memory is not a comparison, so order events are written down as
# they are seen and never rewritten — the same append-only discipline the
# point-in-time store uses, and for the same reason: a number that can be
# revised after the fact is a number you cannot check.
#
# The table is small. A busy quarter is a few hundred rows.
# ---------------------------------------------------------------------------

import sqlite3
from contextlib import contextmanager

DATA_DIR = (os.environ.get("DATA_DIR", "").strip()
            or os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(DATA_DIR, "wow_orders.db")

_db_lock = threading.Lock()
_db_ready = {"done": False}


@contextmanager
def _db():
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    try:
        if not _db_ready["done"]:
            with _db_lock:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS orders (
                        key            TEXT PRIMARY KEY,
                        seen_at        TEXT NOT NULL,
                        date           TEXT,
                        at             TEXT,
                        symbol         TEXT,
                        company        TEXT,
                        headline       TEXT,
                        pdf            TEXT,
                        value_cr       REAL,
                        value_confident INTEGER,
                        currency_converted INTEGER,
                        market_cap_cr  REAL,
                        pct_of_market_cap REAL
                    )""")
                conn.execute("CREATE INDEX IF NOT EXISTS orders_date ON orders(date)")
                # Which reader produced the row, and what kind of filing it
                # was. Rows written before these columns existed were read by
                # the first reader.
                have = {r[1] for r in conn.execute("PRAGMA table_info(orders)").fetchall()}
                if "reader" not in have:
                    conn.execute("ALTER TABLE orders ADD COLUMN reader INTEGER DEFAULT 1")
                if "stage" not in have:
                    conn.execute("ALTER TABLE orders ADD COLUMN stage TEXT")
                # Which days this service has actually looked at.
                #
                # Without this, "the earliest order we hold" has to stand in
                # for "when we started watching", and those are different
                # facts: a quarter with no orders in its first six weeks looks
                # identical to a quarter we were not recording for. One of
                # those is a real lull worth comparing; the other is a hole.
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS coverage (
                        day     TEXT PRIMARY KEY,
                        seen_at TEXT NOT NULL
                    )""")
                conn.commit()
                _db_ready["done"] = True
        yield conn
    finally:
        conn.close()


def _key(row) -> str:
    import hashlib
    raw = (row.get("pdf") or "") or "%s|%s|%s" % (
        row.get("company") or "", row.get("date") or "", (row.get("headline") or "")[:120])
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:24]


def record(rows) -> int:
    """
    Write down what was seen. The first record of an event wins and a later
    re-scan by the same reader can never restate it.

    The one thing that replaces a row is a newer reader. That is a correction
    of how the filing was read, not a revision of what happened: the event,
    its date and its filing stay as they were first written.
    """
    if not rows:
        return 0
    now = dt.datetime.now(IST).isoformat()
    written = 0
    try:
        with _db() as conn:
            for r in rows:
                if not r.get("date"):
                    continue
                cur = conn.execute(
                    "INSERT INTO orders (key, seen_at, date, at, symbol,"
                    " company, headline, pdf, value_cr, value_confident,"
                    " currency_converted, market_cap_cr, pct_of_market_cap,"
                    " reader, stage)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
                    " ON CONFLICT(key) DO UPDATE SET"
                    " value_cr = excluded.value_cr,"
                    " value_confident = excluded.value_confident,"
                    " currency_converted = excluded.currency_converted,"
                    " market_cap_cr = excluded.market_cap_cr,"
                    " pct_of_market_cap = excluded.pct_of_market_cap,"
                    " reader = excluded.reader, stage = excluded.stage"
                    " WHERE excluded.reader > COALESCE(orders.reader, 1)",
                    (_key(r), now, r.get("date"), r.get("at"), r.get("symbol"),
                     r.get("company"), r.get("headline"), r.get("pdf"),
                     r.get("value_cr"), 1 if r.get("value_confident") else 0,
                     1 if r.get("currency_converted") else 0,
                     r.get("market_cap_cr"), r.get("pct_of_market_cap"),
                     int(r.get("reader") or READER), r.get("stage") or "order"))
                written += cur.rowcount or 0
            conn.commit()
    except Exception:
        return 0
    return written


def reread(limit: int = 400) -> int:
    """
    Read again, with this reader, the filings an older one wrote down.

    Only from text already on disk: nothing is fetched, so this is safe to run
    after every scan. A row whose filing is no longer held stays as it is and
    stays out of the quarter's total, which is what `awaiting_reread` counts.
    """
    try:
        import filings_text
        with _db() as conn:
            old = [dict(r) for r in conn.execute(
                "SELECT * FROM orders WHERE COALESCE(reader, 1) < ? ORDER BY date DESC LIMIT ?",
                (READER, int(limit))).fetchall()]
    except Exception:
        return 0
    done = []
    for r in old:
        if NOT_A_WIN.search(r.get("headline") or ""):
            done.append(dict(r, value_cr=None, value_confident=False, currency_converted=False,
                             market_cap_cr=None, pct_of_market_cap=None,
                             stage="not_order", reader=READER))
            continue
        try:
            text = filings_text.cached(r["pdf"]) if r.get("pdf") else None
        except Exception:
            text = None
        if not text:
            continue
        row = size_up(read_filing(r, text))
        done.append(dict(row, date=r.get("date"), reader=READER))
    return record(done)


def history(start: dt.date, end: dt.date):
    try:
        with _db() as conn:
            rows = conn.execute(
                "SELECT * FROM orders WHERE date >= ? AND date <= ? ORDER BY date DESC",
                (start.isoformat(), end.isoformat())).fetchall()
            return [dict(r) for r in rows]
    except Exception:
        return []


def mark_covered(days):
    """Write down which days were actually fetched."""
    if not days:
        return
    now = dt.datetime.now(IST).isoformat()
    try:
        with _db() as conn:
            conn.executemany(
                "INSERT OR IGNORE INTO coverage (day, seen_at) VALUES (?,?)",
                [(d.isoformat(), now) for d in days])
            conn.commit()
    except Exception:
        pass


def covered_days(start: dt.date, end: dt.date):
    try:
        with _db() as conn:
            rows = conn.execute(
                "SELECT day FROM coverage WHERE day >= ? AND day <= ?",
                (start.isoformat(), end.isoformat())).fetchall()
            return {r["day"] for r in rows}
    except Exception:
        return set()


def _business_days(start: dt.date, end: dt.date, today: dt.date):
    """Weekdays in the range that have already happened."""
    out, day = [], start
    stop = min(end, today)
    while day <= stop:
        if day.weekday() < 5:
            out.append(day)
        day += dt.timedelta(days=1)
    return out


def recording_since():
    try:
        with _db() as conn:
            row = conn.execute("SELECT MIN(day) AS d FROM coverage").fetchone()
            return row["d"] if row and row["d"] else None
    except Exception:
        return None


def backfill(days: int = 45, max_days: int = 120) -> dict:
    """
    Walk back through the exchange's announcement archive and record order
    events this instance never saw live.

    Bounded and explicit: this is a few hundred requests, so it belongs in a
    background job or an admin call, never in a page load. Weekends are
    skipped because the exchanges are shut.
    """
    try:
        import announcements
    except Exception:
        return {"ok": False, "error": "announcements unavailable"}
    try:
        import filings_text
        can_read = filings_text.available()
    except Exception:
        filings_text, can_read = None, False

    days = max(1, min(int(days or 45), max_days))
    announcements._build_maps()
    today = dt.datetime.now(IST).date()
    seen, recorded, pdfs = 0, 0, 0

    for back in range(days):
        day = today - dt.timedelta(days=back)
        if day.weekday() >= 5:
            continue
        seen_day = False
        for page in range(1, 4):
            raw_rows, _note = announcements._fetch_day(day, page)
            if not raw_rows:
                break
            seen_day = True
            batch = []
            for raw in raw_rows:
                item = announcements._norm(raw)
                if not item or item.get("category") != "Order win":
                    continue
                seen += 1
                if NOT_A_WIN.search(item.get("headline") or ""):
                    continue
                text = None
                if can_read and item.get("pdf"):
                    text = filings_text.cached(item["pdf"])
                    if text is None and pdfs < MAX_PDFS:
                        pdfs += 1
                        text = filings_text.extract(item["pdf"])
                row = size_up(read_filing(item, text))
                row["date"] = row["date"] or day.isoformat()
                batch.append(row)
            recorded += record(batch)
        if seen_day:
            mark_covered([day])
    return {"ok": True, "days": days, "orders_seen": seen,
            "newly_recorded": recorded, "pdfs_read": pdfs}
