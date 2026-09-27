"""market_week: flows parsing, weekly assembly and the synopsis sentence."""
import market_week as mw


def test_parse_flows_reads_nse_rows():
    body = [{"buyValue": "14035.77", "category": "DII", "date": "25-Sep-2026",
             "netValue": "2838.17", "sellValue": "11197.6"},
            {"buyValue": "12327.36", "category": "FII/FPI", "date": "25-Sep-2026",
             "netValue": "-3693.93", "sellValue": "16021.29"}]
    day, flows = mw.parse_flows(body)
    assert day == "2026-09-25"
    assert flows["fii"]["net"] == -3693.93 and flows["dii"]["net"] == 2838.17


def test_parse_flows_rejects_empty():
    assert mw.parse_flows(None) is None
    assert mw.parse_flows([{"category": "X"}]) is None


def test_build_week_keeps_last_five_sessions_and_marks_missing_flows():
    days = ["2026-09-18", "2026-09-21", "2026-09-22", "2026-09-23", "2026-09-24", "2026-09-25"]
    nifty = {d: 100 + i for i, d in enumerate(days)}
    flows = {"2026-09-25": {"fii": {"net": -3693.93}, "dii": {"net": 2838.17}}}
    out = mw.build_week({"NIFTY 50": nifty}, flows)
    assert [s["weekday"] for s in out] == ["Mon", "Tue", "Wed", "Thu", "Fri"]
    assert out[0]["indices"]["NIFTY 50"]["change_pct"] == 1.0
    assert out[0]["flows"] is None and "FII" not in out[0]["synopsis"]
    assert "absorbing 77% of the selling" in out[-1]["synopsis"]
    assert out[-1]["mood"] == "up"


def test_synopsis_flat_and_vix():
    s = mw.synopsis({"close": 25000, "change_pct": 0.01}, None, {"change_pct": 10})
    assert s.startswith("Nifty was flat to 25,000.") and "VIX jumped 10.0%" in s
