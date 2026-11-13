"""The daily brief: parsing, the keyword reading, and one circular read once."""
import datetime as dt
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))

import policy_brief as pb  # noqa: E402

DGFT = """<table><tbody>
<tr><td>1</td><td>49/2026-27</td><td>2026-27</td>
<td>Amendment in Export Policy of Steel Scrap under ITC (HS) 7204 - export prohibited.</td>
<td>10/11/2026</td><td style="display:none">10/11/2026 21:32:54</td>
<td><a class="attachmentBtn" href="https://content.dgft.gov.in/x/Notification No. 49.pdf">Download</a></td></tr>
<tr><td>2</td><td>47</td><td>2026-27</td><td>Streamlining of Halal Certification Process</td>
<td>01/09/2026</td><td style="display:none">x</td><td></td></tr>
</tbody></table>"""
RSS = """\ufeff<?xml version="1.0" encoding="utf-8"?><rss version="2.0"><channel>
<item><title><![CDATA[RBI reduces repo rate by 25 basis points]]></title>
<description><![CDATA[<p>The MPC decided on a rate cut.</p>]]></description>
<link>https://rbi.example/1</link><pubDate>Tue, 10 Nov 2026 10:00:00 +0530</pubDate></item>
<item><title>Appeal No. 7141 of 2026 filed by A Person</title><link>https://x/2</link></item>
</channel></rss>"""
TODAY = dt.date(2026, 11, 12)


def _fetch():
    items = pb.parse_dgft(DGFT, "DGFT notification") + pb.parse_rss(RSS, "RBI press release")
    for it in items:
        it["id"] = pb._item_id(it["source"], it["title"], it.get("link") or "")
    return items, {"DGFT notification": 2, "RBI press release": 2}


def test_dgft_rows_are_read_with_their_date_and_pdf():
    rows = pb.parse_dgft(DGFT, "DGFT notification")
    assert len(rows) == 2 and rows[0]["date"] == "2026-11-10" and rows[0]["number"] == "49/2026-27"
    assert rows[0]["pdf"].endswith("Notification%20No.%2049.pdf") and rows[1]["pdf"] is None


def test_rss_is_read_past_a_byte_order_mark():
    rows = pb.parse_rss(RSS, "RBI press release")
    assert rows[0]["title"].startswith("RBI reduces repo rate") and rows[0]["date"] == "2026-11-10"
    assert "rate cut" in rows[0]["summary"]


def test_a_word_is_matched_as_a_word():
    r = pb.read_by_rules({"title": "Reporting requirement under FATCA", "summary": ""})
    assert r["sectors"] == [] and r["impact"] == "none"


def test_keywords_name_sectors_and_direction_but_never_a_stock():
    r = pb.read_by_rules({"title": "Export of steel scrap: export prohibited", "summary": ""})
    assert r["sectors"] == ["Metals & Mining"] and r["impact"] == "negative" and r["stocks"] == []
    assert r["read_by"] == "keywords"
    assert pb.read_by_rules({"title": "RBI reduces repo rate", "summary": "a rate cut"})["impact"] == "positive"


def test_procedural_items_are_not_read():
    assert not pb.worth_reading({"source": "SEBI", "title": "Appeal No. 7141 of 2026 filed by A Person"})
    assert not pb.worth_reading({"source": "PIB", "title": "Minister greets the nation"})
    assert pb.worth_reading({"source": "PIB", "title": "Cabinet approves PLI scheme for electronics"})


def test_each_circular_is_read_once_and_old_backlog_is_not_news(tmp_path, monkeypatch):
    monkeypatch.setattr(pb, "STORE", str(tmp_path / "brief.json"))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    first = pb.refresh(today=TODAY, fetch=_fetch)
    assert first["new"] == 2 and first["reader"] == "keywords"     # the September notice and the appeal are skipped
    assert pb.refresh(today=TODAY, fetch=_fetch)["new"] == 0
    b = pb.brief(days=1, today=TODAY)
    assert b["count"] == 2 and b["matter"] == 2 and b["note"]
    assert {s["sector"] for s in b["sectors"]} == {"Metals & Mining", "Financial Services"}
    assert len(pb.email_lines(b)) == 2


def test_a_reader_can_name_stocks_and_they_are_gathered_in_the_brief(tmp_path, monkeypatch):
    monkeypatch.setattr(pb, "STORE", str(tmp_path / "brief.json"))
    seen = []

    def reader(item, pdf_b64=None):
        seen.append((item["title"], pdf_b64))
        return {"read_by": "claude", "read_from": "the circular", "summary": "s", "impact": "negative",
                "importance": "high", "sectors": ["Metals & Mining"],
                "stocks": [{"symbol": "TATASTEEL", "direction": "helped", "reason": "cheaper scrap"}],
                "why": "w", "watch": ""}
    run = pb.refresh(today=TODAY, fetch=_fetch, reader=reader, pdf=lambda url: "UERG")
    assert run["reader"] == "claude" and seen[0][1] in ("UERG", None)
    b = pb.brief(days=1, today=TODAY)
    assert b["items"][0]["importance"] == "high" and b["stocks"][0]["symbol"] == "TATASTEEL"


def test_a_failed_read_falls_back_to_keywords(tmp_path, monkeypatch):
    monkeypatch.setattr(pb, "STORE", str(tmp_path / "brief.json"))
    pb.refresh(today=TODAY, fetch=_fetch, reader=lambda item, pdf_b64=None: None, pdf=lambda url: None)
    assert all(i["read_by"] == "keywords" for i in pb.brief(days=1, today=TODAY)["items"])
