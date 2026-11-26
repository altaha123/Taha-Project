"""
The backfill script: that it keeps asking until nothing remains, stops when a
source is refusing it instead of looping for ever, and stops at once on a
wrong key. The slices themselves are money_flow.run_backfill, tested in
test_money_flow.py; here they are played back from a list.
"""
import backfill_money_flow as B


def _play(monkeypatch, answers):
    calls = []

    def local(months, limit):
        calls.append((months, limit))
        return answers[min(len(calls) - 1, len(answers) - 1)]
    monkeypatch.setattr(B, "_local", local)
    monkeypatch.setattr(B.time, "sleep", lambda s: None)
    return calls


def _slice(remaining, **steps):
    return {"ok": True, "remaining": remaining, "errors": [], "steps": steps}


def test_it_runs_until_nothing_remains(monkeypatch, capsys):
    calls = _play(monkeypatch, [_slice(120), _slice(60), _slice(0)])
    assert B.main(["--months", "12", "--limit", "50"]) == 0
    assert calls == [(12, 50)] * 3
    assert "Done. Nothing remains." in capsys.readouterr().out


def test_no_progress_in_three_slices_is_a_stop_not_a_loop(monkeypatch, capsys):
    calls = _play(monkeypatch, [_slice(40)])
    assert B.main([]) == 1
    assert len(calls) == 4                        # the first, then three the same
    assert "no progress in three slices" in capsys.readouterr().out


def test_progress_resets_the_count(monkeypatch):
    calls = _play(monkeypatch, [_slice(40), _slice(40), _slice(30), _slice(30), _slice(0)])
    assert B.main([]) == 0 and len(calls) == 5


def test_a_wrong_key_stops_at_once(monkeypatch, capsys):
    monkeypatch.setattr(B, "_remote", lambda api, key, months, limit: {
        "ok": False, "remaining": None, "fatal": True, "errors": ["HTTP 401: needs the admin key"]})
    monkeypatch.setattr(B.time, "sleep", lambda s: None)
    assert B.main(["--api", "https://example.invalid", "--key", "nope"]) == 2
    assert "HTTP 401" in capsys.readouterr().out


def test_a_busy_server_is_waited_for(monkeypatch):
    calls = _play(monkeypatch, [{"busy": True}, {"busy": True}, _slice(0)])
    assert B.main([]) == 0 and len(calls) == 3


def test_a_slice_is_one_line_a_person_can_read():
    line = B._line(_slice(12, nsdl={"read": 2, "rows": 96, "remaining": 0},
                          indices={"stored": 40, "absent": 18, "blocked": 1, "remaining": 12},
                          deals_history={"new": 300, "refused": True},
                          compute={"sectors_scored": 19, "as_of": "2026-11-20"}))
    assert line == ("nsdl +2 reports (96 rows, 0 left) | index +40 days (18 absent, 1 refused, 12 left) | "
                    "deals +300 (refused) | scored 19 sectors as of 2026-11-20")
