"""
fund_workbook.py — reading an AMC's monthly portfolio disclosure

WHY THERE IS ONE PARSER AND NOT FIFTY-THREE
SEBI requires every asset manager to publish the full portfolio of every
scheme, monthly, within ten days of month end. AMFI does not aggregate them:
its portfolio-disclosure page is a DIRECTORY, one link per AMC, and all 53
links point at 53 different websites. There is no central feed of holdings
anywhere.

What IS common is the content. The regulation fixes the columns — name of the
instrument, ISIN, industry, quantity, market value, per cent to net assets —
even though the file layout, sheet naming and header position vary by AMC. So
this parses the CONTENT rather than the layout: it finds the header row by
looking for it, and anchors the columns on the one field that cannot be
mistaken for anything else.

ANCHORED ON ISIN, NOT ON COLUMN POSITION
Baroda BNP's workbook has eight header labels beginning "Name of the
Instrument", and its data rows begin with an internal scrip code and THEN the
name — so the header is off by one against the data it describes. Parsing by
position puts the scrip code in the name column and the name in the ISIN
column, and produces a table that looks entirely reasonable and is wrong in
every row. An ISIN matches INE/INF/IN9 followed by nine alphanumerics and
nothing else in these files does, so the ISIN column is found by looking at the
data, and the other columns are read relative to it.

ISIN IS ALSO WHY THE FUND SIDE IS SAFE
The individual-investor side has to match people by name, which is the whole
difficulty of that feature. Here there is a registered identifier on every row,
so a holding is joined to a listed company exactly or not at all. Nothing in
this module guesses.

THE SCALE TRAP
"% to Net Assets" is written as 0.0333 by some AMCs and as 3.33 by others for
the same holding. Taking either at face value is a hundredfold error in a
column readers compare across funds. The scale is detected per sheet by summing
the column: a full portfolio sums to about 1 or about 100, and those are far
enough apart to tell apart safely.

DEPENDENCIES: openpyxl, and it is the only thing in this module that is not
the standard library. It is declared in requirements.txt — which it was not,
for a release, with the result that every ingest on the deployed instance
raised ImportError and was swallowed as "could not read the workbook".
"""

import re
import zipfile

ISIN = re.compile(r"^(IN[EF0-9][0-9A-Z]{9})$")

# The header labels the regulation fixes, lowercased and stripped of
# punctuation so "Market/Fair Value\n (Rs. in Lakhs)" matches "market fair
# value". Each entry is a list of substrings, any of which identifies it.
COLUMNS = {
    "name":     ["name of the instrument", "name of instrument", "instrument name"],
    "industry": ["industry", "rating"],
    "quantity": ["quantity", "no of shares", "number of shares"],
    "value":    ["market value", "market fair value", "fair value", "market/fair"],
    "pct":      ["to net assets", "to nav", "of net assets"],
}

# Rows that are section headings or totals rather than holdings.
_SKIP = re.compile(
    r"^(equity|debt|money market|derivatives?|total|sub ?total|grand total|"
    r"net (current )?assets?|cash|treps|tri?party|reverse repo|repo |"
    r"listed|unlisted|margin|clearing corp|"
    r"a\)|b\)|c\)|\(a\)|\(b\)|\(c\)|others?|net receivab)", re.I)


def _norm(v):
    """A header cell, flattened for comparison."""
    s = str(v if v is not None else "").lower()
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _num(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        f = float(v)
        return f if f == f else None
    s = str(v).strip().replace(",", "").replace("%", "")
    if not s or s in ("-", "--", "NA", "N.A.", "nil", "Nil"):
        return None
    try:
        f = float(s)
        return f if f == f else None
    except ValueError:
        return None


def looks_like_xlsx(blob: bytes) -> bool:
    """AMCs routinely serve an .xlsx under an .xls filename — Baroda BNP's
    monthly pack is one. Sniff the container rather than trusting the name."""
    return blob[:2] == b"PK"


def _header_row(rows):
    """
    The index of the header row, and the label -> column-index map it yields.

    Searched rather than assumed: the disclosures put a title, a blank line and
    a "Monthly Portfolio Statement as on ..." line above it, and how many
    varies.
    """
    for i, row in enumerate(rows[:30]):
        cells = [_norm(c) for c in row]
        joined = " | ".join(cells)
        # An ISIN label is what identifies the table. The regulation requires
        # the column, so a sheet without one is not a portfolio — and guessing
        # at a table with no anchor is how an index sheet becomes holdings.
        if "isin" not in joined:
            continue
        found = {}
        for key, needles in COLUMNS.items():
            for j, c in enumerate(cells):
                if c and any(n in c for n in needles):
                    found.setdefault(key, j)
        if "name" in found and "quantity" in found:
            return i, found
    return None, {}


def _isin_column(rows, start):
    """
    The column the ISINs are actually in.

    Found from the data, not from the header, because at least one AMC's header
    is offset by a column against its own rows. Whichever column holds the most
    well-formed ISINs wins.
    """
    counts = {}
    for row in rows[start:start + 400]:
        for j, c in enumerate(row):
            if c is not None and ISIN.match(str(c).strip().upper()):
                counts[j] = counts.get(j, 0) + 1
    if not counts:
        return None
    return max(counts, key=counts.get)


def _pct_scale(values):
    """
    1 if the column is already a percentage, 100 if it is a fraction.

    A full portfolio's weights sum to roughly 100% either way, so the sum is
    about 100 or about 1 and there is no ambiguous middle to get wrong. When
    the sheet is partial or the column is missing, the scale is left alone
    rather than guessed.
    """
    vals = [v for v in values if v is not None]
    if len(vals) < 3:
        return 1.0
    total = sum(abs(v) for v in vals)
    if 0.5 <= total <= 1.8:
        return 100.0
    if 50 <= total <= 180:
        return 1.0
    # Neither shape — a sheet holding one slice of a portfolio, say. Fall back
    # on the largest single weight: nothing legitimately holds 150% of itself.
    return 100.0 if max(abs(v) for v in vals) <= 1.0 else 1.0


# "Monthly Portfolio Statement as on 31-Aug-2026" and its many wordings. Sits
# in the two or three rows above the header, and is the only statement of the
# month inside a pack whose filename does not carry one.
_AS_ON = re.compile(
    r"as\s+(?:on|at|of)\s*[:\-]?\s*(\d{1,2}[-/ ][A-Za-z0-9]{2,9}[-/ ]\d{2,4}"
    r"|\d{4}[-/]\d{1,2}[-/]\d{1,2}"
    r"|[A-Za-z]{3,9}\s+\d{4})", re.I)


def as_on_hint(rows, limit=12):
    """
    Whatever the sheet says about which month it describes.

    Returned raw for the caller to normalise, because roughly one AMC in eight
    names its workbook without a date anywhere in the filename and this line is
    then the only thing standing between the pack and being filed under the
    wrong month.
    """
    for row in rows[:limit]:
        for cell in row or ():
            if cell is None:
                continue
            m = _AS_ON.search(str(cell))
            if m:
                return m.group(1).strip()
    return None


def parse_sheet(rows, scheme=None):
    """
    One scheme sheet -> its listed-equity holdings.

    `rows` is a list of tuples, as openpyxl's iter_rows(values_only=True)
    yields. Returns [] for a sheet that is not a portfolio — an index sheet, a
    disclaimer, a debt-only scheme with no ISINs.
    """
    hdr, cols = _header_row(rows)
    if hdr is None:
        return []
    icol = _isin_column(rows, hdr + 1)
    if icol is None:
        return []

    # The header may be offset against the data. Measured once, from the
    # difference between where the header says ISIN is and where it is.
    hisin = None
    for j, c in enumerate(rows[hdr]):
        if _norm(c) == "isin":
            hisin = j
            break
    shift = (icol - hisin) if hisin is not None else 0

    def at(row, key):
        j = cols.get(key)
        if j is None:
            return None
        j += shift
        return row[j] if 0 <= j < len(row) else None

    out = []
    for row in rows[hdr + 1:]:
        if not row:
            continue
        raw = row[icol] if icol < len(row) else None
        code = str(raw).strip().upper() if raw is not None else ""
        if not ISIN.match(code):
            continue
        name = at(row, "name")
        name = str(name).strip() if name is not None else ""
        if not name or _SKIP.match(name):
            continue
        qty = _num(at(row, "quantity"))
        # A holding with no quantity is a heading that happens to carry an
        # ISIN, or a row for an instrument the scheme has exited.
        if qty is None or qty <= 0:
            continue
        out.append({
            "isin": code,
            "name": name[:160],
            "industry": (str(at(row, "industry") or "").strip() or None),
            "quantity": qty,
            "value_lakh": _num(at(row, "value")),
            "pct_nav": _num(at(row, "pct")),
            "scheme": scheme,
        })

    scale = _pct_scale([r["pct_nav"] for r in out])
    if scale != 1.0:
        for r in out:
            if r["pct_nav"] is not None:
                r["pct_nav"] = round(r["pct_nav"] * scale, 4)
    return out


def parse_workbook(path, max_sheets=400, on_sheet=None):
    """
    Every scheme in one AMC's monthly pack.

    Streamed sheet by sheet in openpyxl's read-only mode: these workbooks run
    to fifteen megabytes and fifty sheets, and loading one whole on a 512 MB
    instance is how a worker dies.
    """
    import openpyxl
    if not zipfile.is_zipfile(path):
        raise ValueError("not an xlsx workbook (the legacy .xls format is not read)")
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        out = []
        for sheet in wb.sheetnames[:max_sheets]:
            ws = wb[sheet]
            rows = []
            for r in ws.iter_rows(values_only=True):
                rows.append(r)
                # A portfolio sheet is a few hundred rows. Anything far past
                # that is a data dump this does not need to hold in memory.
                if len(rows) > 6000:
                    break
            holdings = parse_sheet(rows, scheme=sheet)
            if holdings:
                out.append({"sheet": sheet, "holdings": holdings,
                            "as_on": as_on_hint(rows)})
            if on_sheet:
                try:
                    on_sheet(sheet, len(holdings))
                except Exception:
                    pass
            del rows
        return out
    finally:
        try:
            wb.close()
        except Exception:
            pass


def scheme_names(path):
    """
    The pack's index sheet, mapping a sheet's short code to the scheme's real
    name.

    Sheet names are internal codes — "T0ME02" rather than "Baroda BNP Paribas
    Mid Cap Fund" — and a page showing the code would be useless.
    """
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        for sheet in wb.sheetnames[:3]:
            rows = []
            for i, r in enumerate(wb[sheet].iter_rows(values_only=True)):
                rows.append(r)
                if i > 400:
                    break
            hdr = None
            for i, r in enumerate(rows[:12]):
                cells = [_norm(c) for c in r]
                if any("scheme name" in c for c in cells):
                    hdr = i
                    break
            if hdr is None:
                continue
            cells = [_norm(c) for c in rows[hdr]]
            try:
                ncol = next(j for j, c in enumerate(cells) if "scheme name" in c)
            except StopIteration:
                continue
            scol = next((j for j, c in enumerate(cells)
                         if "short name" in c or c == "code"), None)
            out = {}
            for r in rows[hdr + 1:]:
                if not r or ncol >= len(r):
                    continue
                name = str(r[ncol] or "").strip()
                key = str(r[scol] or "").strip() if scol is not None and scol < len(r) else ""
                if name and key:
                    out[key] = name
            if out:
                return out
    finally:
        try:
            wb.close()
        except Exception:
            pass
    return {}
