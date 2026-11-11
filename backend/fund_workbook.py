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

THREE LAYOUTS, ONE TABLE
Measured across the largest houses in November 2026:
  · a sheet per scheme with an index sheet naming them (SBI, Nippon India,
    Aditya Birla Sun Life, Baroda BNP) — the common case;
  · a workbook per scheme, each with its name in a title row (HDFC, and ICICI
    Prudential inside a zip);
  · the whole house in ONE sheet, scheme after scheme, each block opened by a
    "SCHEME: ..." line (UTI). Read as one table, that turns ninety schemes into
    one and sums their positions.
All three come out of this module as the same list of per-scheme packs.

DEPENDENCIES: openpyxl for xlsx, and xlrd for the legacy binary .xls format
that Aditya Birla Sun Life still publishes. Both are declared in
requirements.txt — openpyxl was not, for a release, with the result that every
ingest on the deployed instance raised ImportError and was swallowed as "could
not read the workbook".
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
    # SBI and Aditya Birla head the column "% to AUM". Missing it left every
    # weight in their packs empty while the rows themselves read fine.
    "pct":      ["to net assets", "to nav", "of net assets", "to aum", "of aum"],
}

# A sheet longer than this is a data dump rather than a portfolio. UTI's whole
# house in one sheet runs to about 9,400 rows, so the cap sits well above it —
# the old cap of 6,000 silently cut that house off a third of the way down.
MAX_ROWS = 20000

OLE2 = b"\xd0\xcf\x11\xe0"

# Rows that are section headings or totals rather than holdings.
_SKIP = re.compile(
    r"^(equity|debt|money market|derivatives?|total|sub ?total|grand total|"
    r"net (current )?assets?|cash|treps|tri?party|reverse repo|repo |"
    r"listed|unlisted|margin|clearing corp|"
    r"a\)|b\)|c\)|\(a\)|\(b\)|\(c\)|others?|net receivab)", re.I)
_EQ_PREFIX = re.compile(r"^(?:EQ|EQUITY)\s+-\s+", re.I)


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


def looks_like_xls(blob: bytes) -> bool:
    """The legacy binary format (an OLE2 compound file). Aditya Birla Sun
    Life's monthly pack is one, inside a zip."""
    return blob[:4] == OLE2


def book_kind(path):
    """'xlsx', 'xls', or None — from the bytes, never the filename."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(8)
    except Exception:
        return None
    if looks_like_xlsx(head):
        return "xlsx"
    if looks_like_xls(head):
        return "xls"
    return None


def iter_sheets(path, max_sheets=400, max_rows=MAX_ROWS):
    """
    (sheet name, rows) for every sheet, one sheet in memory at a time.

    Rows are tuples, as openpyxl's iter_rows(values_only=True) yields; xlrd's
    rows are converted to the same shape, with its '' for an empty cell left
    as it is (every reader below treats '' and None alike).
    """
    kind = book_kind(path)
    if kind == "xlsx":
        if not zipfile.is_zipfile(path):
            raise ValueError("not an xlsx workbook (the file is damaged)")
        import openpyxl
        # Opened from a handle rather than a path: openpyxl refuses a path by
        # its extension, and these arrive as temporary files and zip members.
        fh = open(path, "rb")
        wb = openpyxl.load_workbook(fh, read_only=True, data_only=True)
        try:
            for name in wb.sheetnames[:max_sheets]:
                rows = []
                for r in wb[name].iter_rows(values_only=True):
                    rows.append(r)
                    if len(rows) >= max_rows:
                        break
                yield name, rows
                del rows
        finally:
            try:
                wb.close()
            finally:
                fh.close()
        return
    if kind == "xls":
        try:
            import xlrd
        except ImportError:
            raise ValueError("the legacy .xls format needs the xlrd package, "
                             "which is not installed")
        try:
            wb = xlrd.open_workbook(path, on_demand=True)
        except Exception as e:
            raise ValueError(("could not read the legacy .xls workbook: %s"
                              % e)[:160])
        try:
            for i, name in enumerate(wb.sheet_names()[:max_sheets]):
                sh = wb.sheet_by_index(i)
                rows = [tuple(sh.row_values(r))
                        for r in range(min(sh.nrows, max_rows))]
                wb.unload_sheet(i)
                yield name, rows
                del rows
        finally:
            wb.release_resources()
        return
    raise ValueError("not an xlsx workbook (nor the legacy .xls format)")


def sheet_list(path):
    """Every sheet name, without reading any rows."""
    kind = book_kind(path)
    if kind == "xlsx":
        import openpyxl
        with open(path, "rb") as fh:
            wb = openpyxl.load_workbook(fh, read_only=True, data_only=True)
            try:
                return list(wb.sheetnames)
            finally:
                wb.close()
    if kind == "xls":
        import xlrd
        wb = xlrd.open_workbook(path, on_demand=True)
        try:
            return list(wb.sheet_names())
        finally:
            wb.release_resources()
    return []


# ---------------------------------------------------------------------------
# Scheme names
# ---------------------------------------------------------------------------

# "(An open ended equity scheme ...)", "(Formerly known as ...)", "(Erstwhile
# known as ...)": the regulatory description every AMC appends to a scheme's
# name. Useful in a prospectus, noise in a column of names.
_DESCRIPTION = re.compile(r"\s*\(\s*(?:an?\s|formerly|erstwhile|earlier)\b.*$",
                          re.I | re.S)
_BRAND_DASH = re.compile(r"^([A-Z]{2,})\s+-\s+")


def clean_scheme_name(text):
    """A scheme's display name from however the pack writes it."""
    if text is None:
        return None
    s = str(text).strip().split("\n")[0]
    s = _DESCRIPTION.sub("", s)
    s = _BRAND_DASH.sub(r"\1 ", s)        # "UTI - Large Cap Fund"
    s = re.sub(r"\s+", " ", s).strip(" .-:")
    return s or None


_SCHEME_LINE = re.compile(r"^\s*scheme(?:\s*name)?\s*[:\-]\s*(.*)$", re.I | re.S)
_TITLE_NOISE = re.compile(r"mutual fund\s*$|portfolio|statement|as\s+(?:on|at|of)\b"
                          r"|back to|^index$|^total", re.I)
_TITLE_WORD = re.compile(r"\b(fund|plan|etf|fof|scheme|index)\b", re.I)


def sheet_title(rows, limit=None):
    """
    The scheme a sheet describes, from the lines above its table.

    Either an explicit "SCHEME NAME : X" / "SCHEME: X" line (SBI, UTI), or the
    first line that reads like a scheme's name — "HDFC Flexi Cap Fund (An open
    ended ...)" on HDFC's sheets, "ICICI Prudential Flexi Cap Fund" under the
    house name on ICICI's. Returns None rather than guessing at a line that is
    neither.
    """
    top = rows[:limit if limit is not None else 12]
    for row in top:
        cells = [c for c in (row or ()) if c not in (None, "")]
        for j, c in enumerate(cells):
            m = _SCHEME_LINE.match(str(c))
            if not m:
                continue
            name = m.group(1).strip() or (str(cells[j + 1]) if j + 1 < len(cells) else "")
            name = clean_scheme_name(name)
            if name:
                return name
    for row in top:
        for c in (row or ()):
            if c in (None, "") or not isinstance(c, str):
                continue
            s = c.strip()
            if not (6 <= len(s) <= 400) or _TITLE_NOISE.search(s.split("\n")[0]):
                continue
            if "isin" in _norm(s).split():
                return None               # reached the table
            if _TITLE_WORD.search(s.split("(")[0]):
                return clean_scheme_name(s)
    return None


def split_sections(rows):
    """
    A sheet holding several schemes, cut into one block per scheme.

    UTI publishes its whole house in one sheet: every scheme opens with a
    "SCHEME: UTI - Flexi Cap Fund" line, then its own header and holdings.
    Parsed as one table, ninety schemes become one and a company held by
    forty of them shows as a single position. A sheet with fewer than two
    such lines is returned whole.
    """
    starts = []
    for i, row in enumerate(rows):
        for c in (row or ())[:3]:
            if c not in (None, "") and _SCHEME_LINE.match(str(c)):
                starts.append(i)
                break
    if len(starts) < 2:
        return [rows]
    # Each block keeps the few lines before its marker too — the "as on" line
    # sometimes sits above "SCHEME:" rather than below it.
    out = []
    for k, s in enumerate(starts):
        end = starts[k + 1] if k + 1 < len(starts) else len(rows)
        out.append(rows[s:end])
    return out


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
    # "for the period ended October 31, 2026" is Quantum's wording.
    r"(?:as\s+(?:on|at|of)|period\s+ended)\s*[:\-]?\s*"
    r"(\d{1,2}[-/. ][A-Za-z0-9]{2,9}[-/. ]\d{2,4}"
    r"|\d{4}[-/]\d{1,2}[-/]\d{1,2}"
    # "October 31,2026" (Nippon India), "Oct 31,2026" (ICICI Prudential)
    r"|[A-Za-z]{3,9}\.?\s+\d{1,2}(?:st|nd|rd|th)?\s*,\s*\d{4}"
    r"|[A-Za-z]{3,9}\s+\d{4})", re.I)


def as_on_hint(rows, limit=12):
    """
    Whatever the sheet says about which month it describes.

    Returned raw for the caller to normalise, because roughly one AMC in eight
    names its workbook without a date anywhere in the filename and this line is
    then the only thing standing between the pack and being filed under the
    wrong month.

    Read across the whole row, not cell by cell: SBI writes "PORTFOLIO
    STATEMENT AS ON :" in one cell and the date, as a real date, in the next.
    """
    for row in rows[:limit]:
        text = " ".join(str(c) for c in (row or ()) if c not in (None, ""))
        if not text:
            continue
        m = _AS_ON.search(text)
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
        # UTI prefixes every share with its asset class: "EQ - ETERNAL LIMITED".
        name = _EQ_PREFIX.sub("", name)
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
    Every scheme in one AMC's monthly pack, xlsx or legacy .xls.

    Streamed sheet by sheet (openpyxl's read-only mode, xlrd on demand): these
    workbooks run to fifteen megabytes and a hundred sheets, and loading one
    whole on a 512 MB instance is how a worker dies.

    Each pack carries `sheet` (the sheet's code, with "#n" for the n-th scheme
    of a sheet that holds several), `title` (the scheme's name as the sheet
    itself states it, when it does) and `as_on` (the sheet's own date line).
    """
    out = []
    for sheet, rows in iter_sheets(path, max_sheets=max_sheets):
        blocks = split_sections(rows)
        found = 0
        for k, block in enumerate(blocks):
            holdings = parse_sheet(block, scheme=sheet)
            if not holdings:
                continue
            found += len(holdings)
            out.append({"sheet": sheet if len(blocks) == 1 else "%s#%d" % (sheet, k + 1),
                        "holdings": holdings,
                        "as_on": as_on_hint(block) or as_on_hint(rows),
                        "title": sheet_title(block)})
        if on_sheet:
            try:
                on_sheet(sheet, found)
            except Exception:
                pass
    return out


def scheme_names(path, max_index_sheets=3):
    """
    The pack's index sheet, mapping a sheet's short code to the scheme's real
    name.

    Sheet names are internal codes — "T0ME02" rather than "Baroda BNP Paribas
    Mid Cap Fund" — and a page showing the code would be useless.

    Found by matching rather than by header wording, because the wording
    varies and one house has none: SBI's index has "Scheme Short code",
    Baroda BNP's "Short Name", Nippon India's is two bare columns. What every
    index shares is a column whose cells ARE the workbook's sheet names, next
    to a column of long names — so the pair of columns with the most such
    rows is the index.
    """
    try:
        sheets = sheet_list(path)
    except Exception:
        return {}
    if len(sheets) < 2:
        return {}
    lookup = {s.strip().lower(): s for s in sheets}
    best = {}
    for i, (sheet, rows) in enumerate(iter_sheets(path, max_sheets=max_index_sheets,
                                                  max_rows=800)):
        if i >= max_index_sheets:
            break
        pairs = {}
        for row in rows:
            cells = [("" if c is None else str(c).strip()) for c in (row or ())]
            for j, c in enumerate(cells):
                code = lookup.get(c.lower())
                if not code or code == sheet:
                    continue
                # The name: the longest text in the row that is not a code.
                k = max((x for x in range(len(cells))
                         if x != j and cells[x] and cells[x].lower() not in lookup
                         and re.search(r"[A-Za-z]{3}", cells[x])),
                        key=lambda x: len(cells[x]), default=None)
                if k is None or len(cells[k]) <= len(c):
                    continue
                pairs.setdefault((j, k), {})[code] = clean_scheme_name(cells[k])
        for found in pairs.values():
            if len(found) > len(best):
                best = found
    # One coincidental match is not an index: in ICICI's two-sheet workbooks a
    # holdings row happens to contain the word "Derivative", which is also the
    # second sheet's name. A workbook with one scheme is named by its title.
    return {k: v for k, v in best.items() if v} if len(best) >= 2 else {}
