"""
Risk profiling.

Under the Investment Advisers Regulations the profile is not a preamble to the
advice; it is what makes the advice defensible. So the tests here are less
about arithmetic than about the two decisions that arithmetic encodes: that the
lower of capacity and tolerance wins, and that what somebody answered is kept
rather than replaced.
"""
import os
import tempfile

import pytest

import accounts as A
import risk_profile as R


@pytest.fixture(autouse=True)
def fresh_db():
    with tempfile.TemporaryDirectory() as d:
        A.reset_for_tests(os.path.join(d, "accounts.db"))
        yield
        A.reset_for_tests(os.path.join(d, "accounts.db"))


def answers(**over):
    base = {"age": "25_34", "horizon": "10plus", "surplus": "25_40",
            "emergency": "6_12", "emi": "under20", "dependents": "0",
            "drawdown_action": "hold_plan", "max_fall": "30",
            "priority": "mostly_grow", "experience": "3_10",
            "purpose": "retirement", "mode": "sip", "amount": 25000}
    base.update(over)
    return base


def login(email="reader@example.com"):
    return A.complete_login(A.start_login(email)["token"])["user"]["id"]


# ── The rule that matters ────────────────────────────────────────────────────

def test_the_lower_of_capacity_and_tolerance_decides():
    """Advising to capacity past tolerance builds a portfolio somebody sells at
    the bottom. Advising to tolerance past capacity recommends a risk they
    cannot afford. Neither is a compromise worth splitting."""
    out = R.assess(answers(drawdown_action="sell_all", max_fall="any",
                           priority="protect", experience="none"))
    assert out["capacity"] > out["tolerance"]
    assert out["score"] == out["tolerance"]
    assert out["binding"] == "tolerance"


def test_a_willing_investor_with_no_room_is_held_to_the_room():
    out = R.assess(answers(horizon="1_3", surplus="none", emergency="none",
                           emi="over60", dependents="5plus", age="55_64"))
    assert out["tolerance"] > out["capacity"]
    assert out["score"] == out["capacity"]
    assert out["binding"] == "capacity"


def test_the_distance_between_the_two_is_reported():
    """The gap is the conversation worth having, so it cannot be left to be
    inferred from two numbers."""
    out = R.assess(answers(drawdown_action="sell_all", max_fall="any"))
    assert out["gap"] == round(abs(out["capacity"] - out["tolerance"]), 1)
    assert out["gap"] > 0
    assert out["binding_note"]


def test_agreement_is_said_out_loud_too():
    out = R.assess(answers())
    assert out["binding"] in ("capacity", "tolerance", "both")
    assert out["binding_note"]


# ── Scoring behaves the way the questions claim ──────────────────────────────

def test_horizon_moves_capacity_more_than_anything_else():
    """Money needed inside a year cannot sit in something that has taken three
    years to recover, whatever else is true about the person."""
    long_h = R.assess(answers(horizon="10plus"))["capacity"]
    short_h = R.assess(answers(horizon="under1"))["capacity"]
    assert long_h - short_h > 20


def test_someone_who_sells_at_the_bottom_is_not_called_aggressive():
    out = R.assess(answers(drawdown_action="sell_all", max_fall="any",
                           priority="protect", experience="none"))
    assert out["band"] in ("Conservative", "Moderately conservative")


def test_every_band_is_reachable():
    """A band nothing can land in is a band that misleads whoever reads the
    scale."""
    seen = {R.band(s)[0] for s in (5, 25, 50, 70, 95)}
    assert seen == {b[2] for b in R.BANDS}


def test_the_working_is_handed_back_with_the_answer():
    """An opaque number about somebody's own money is not worth having."""
    out = R.assess(answers())
    ids = {d["id"] for d in out["detail"]["capacity"] + out["detail"]["tolerance"]}
    assert {"age", "horizon", "drawdown_action", "max_fall"} <= ids
    for row in out["detail"]["capacity"]:
        assert row["answer"] and row["weight"] > 0


# ── Refusing to guess ────────────────────────────────────────────────────────

def test_an_incomplete_questionnaire_is_not_scored():
    out = R.assess({"age": "25_34"})
    assert out.get("error")
    assert "horizon" in out["missing"]


def test_an_answer_that_is_not_on_the_list_is_not_accepted():
    out = R.assess(answers(max_fall="whatever"))
    assert "max_fall" in out["missing"]


@pytest.mark.parametrize("bad", [0, -5, "", None, "lots"])
def test_an_amount_has_to_be_a_positive_number(bad):
    assert "amount" in R.assess(answers(amount=bad))["missing"]


def test_the_optional_target_really_is_optional():
    assert "target" not in R.required_ids()
    assert not R.assess(answers()).get("error")


def test_context_answers_are_recorded_even_though_they_score_nothing():
    out = R.assess(answers(purpose="house", mode="lumpsum"))
    assert out["context"]["purpose"] == "house"
    assert out["context"]["mode"] == "lumpsum"


# ── The record ───────────────────────────────────────────────────────────────

def test_a_reassessment_does_not_destroy_the_earlier_one():
    """An adviser has to be able to say what the basis was on the day the
    advice was given. An UPDATE here would erase exactly that."""
    me = login()
    first = answers()
    A.save_risk_profile(me, first, R.assess(first))
    second = answers(drawdown_action="sell_all", max_fall="any", priority="protect")
    A.save_risk_profile(me, second, R.assess(second))

    history = A.risk_profile_history(me)
    assert len(history) == 2
    assert history[0]["answers"]["drawdown_action"] == "sell_all"   # newest
    assert history[1]["answers"]["drawdown_action"] == "hold_plan"  # kept
    assert A.latest_risk_profile(me)["answers"] == second


def test_the_answers_come_back_exactly_as_they_went_in():
    me = login()
    given = answers(target=10000000)
    A.save_risk_profile(me, given, R.assess(given))
    assert A.latest_risk_profile(me)["answers"] == given


def test_one_persons_profile_is_not_anothers():
    mine, theirs = login("a@example.com"), login("b@example.com")
    A.save_risk_profile(mine, answers(), R.assess(answers()))
    assert A.latest_risk_profile(mine) is not None
    assert A.latest_risk_profile(theirs) is None


def test_somebody_with_no_profile_yet_is_not_an_error():
    assert A.latest_risk_profile(login()) is None
    assert A.risk_profile_history(login()) == []
