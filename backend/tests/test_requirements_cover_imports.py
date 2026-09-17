"""
Every third-party module the backend imports must be in requirements.txt.

openpyxl was imported by fund_workbook.py and declared nowhere. It was
installed on the development machine, so the parser was written and tested
against a real workbook and worked perfectly — and the deployed instance had
no such module. Every ingest raised ImportError, `except Exception` turned it
into "could not read the workbook", and the nightly job reported success while
writing nothing at all. A whole feature, shipped dead, with green tests.

This is the check that would have caught it in CI rather than in production.
"""

import ast
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]

# Modules that ship with Python, plus the ones another requirement pulls in
# and the local modules of this project.
STDLIB = set(sys.stdlib_module_names) | {"__future__"}

# import name -> the distribution that provides it, where they differ.
ALIASES = {
    "PIL": "Pillow",
    "dateutil": "python-dateutil",
    "yaml": "PyYAML",
    "curl_cffi": "curl_cffi",
    "sentry_sdk": "sentry-sdk",
    "fitz": "PyMuPDF",
    "bs4": "beautifulsoup4",
    "sklearn": "scikit-learn",
}

# Imported only inside a test, or provided by the platform.
IGNORE = {"pytest", "conftest"}


def _declared():
    out = set()
    for line in (BACKEND / "requirements.txt").read_text().splitlines():
        line = line.split("#")[0].strip()
        if not line:
            continue
        name = line.split("==")[0].split(">=")[0].split("[")[0].strip()
        out.add(name.lower().replace("_", "-"))
    return out


def _local_modules():
    return {p.stem for p in BACKEND.glob("*.py")} | {"tests"}


def _imports():
    """Every top-level module imported anywhere in backend/, including inside
    a function — which is exactly where openpyxl was hiding."""
    found = {}
    local = _local_modules()
    for path in BACKEND.glob("*.py"):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:                                  # pragma: no cover
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                if node.level:                # a relative import is local
                    continue
                names = [(node.module or "").split(".")[0]]
            else:
                continue
            for n in names:
                if not n or n in STDLIB or n in local or n in IGNORE:
                    continue
                found.setdefault(n, set()).add(path.name)
    return found


def test_every_third_party_import_is_declared():
    declared = _declared()
    missing = {}
    for mod, files in _imports().items():
        dist = ALIASES.get(mod, mod).lower().replace("_", "-")
        if dist not in declared and mod.lower().replace("_", "-") not in declared:
            missing[mod] = sorted(files)
    assert not missing, (
        "imported but not in requirements.txt — these work on a machine that "
        "happens to have them and fail silently on the deployed instance: %s"
        % missing)
