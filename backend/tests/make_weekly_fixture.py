"""
Writes frontend/tests/fixtures/weekly-brief.json from the real weekly_brief
module, so frontend/tests/weekly-browser.cjs draws what the API would send.

    python backend/tests/make_weekly_fixture.py
"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

import weekly_brief as W                                   # noqa: E402
from test_weekly_brief import SOURCES, WEEK                # noqa: E402

with tempfile.TemporaryDirectory() as d:
    W.STORE = os.path.join(d, "weekly.json")
    published = W.publish(WEEK, SOURCES)
    W.add_topic(WEEK, "What the budget could change for banks",
                "Three things to read in the budget speech.\n\n- Credit guarantee schemes\n- Deposit tax rules\n"
                "- Recapitalisation\n\nMore at https://example.com/budget-notes.", "HDFCBANK, SBIN")
    published = W.with_topics(W.load()["issues"][WEEK])
    draft = W.issue("", today=__import__("datetime").date(2026, 11, 25), sources={})
    out = {"published": published, "draft": draft, "issues": {"issues": W.issues(), "current": draft["week"]}}

path = os.path.join(os.path.dirname(HERE), "..", "frontend", "tests", "fixtures", "weekly-brief.json")
with open(os.path.normpath(path), "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=1)
print("wrote", os.path.normpath(path))
