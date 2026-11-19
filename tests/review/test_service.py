"""record_review checks a review against its run and the rules, then saves it."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from flag_it import fixtures
from flag_it.contracts.api import ReviewIn
from flag_it.contracts.rules import load_rules
from flag_it.db import records
from flag_it.fixtures.seed import seed
from flag_it.review.service import InvalidReview, NotDecided, UnknownRun, normalize_reviewer, record_review

RULES = load_rules()
NOW = datetime(2026, 11, 17, 12, 0, tzinfo=timezone.utc)


def review(**over) -> ReviewIn:
    return ReviewIn.model_validate({"reviewer": "Ana", "final": "approve", "reason": "Fine."} | over)


def test_a_review_is_saved_and_returned(conn):
    seed(conn)
    run = fixtures.decision_run("guardrails_unsure")
    flag = fixtures.flags("guardrails_unsure")[0]
    body = review(final="flag", per_flag=[{"flag_id": str(flag.flag_id), "agree": True, "note": "No purpose given."}],
                  missed_rule_ids=["OSU-LIM-01"])
    outcome = record_review(conn, run.decision_id, body, RULES, now=NOW)
    assert (outcome.decision_id, outcome.reviewer, outcome.final, outcome.created_at) == (run.decision_id, "ana", "flag", NOW)  # names are saved normalized
    assert outcome in records.load_review_outcomes(conn, run.decision_id)


def test_a_run_may_be_reviewed_again(conn):
    seed(conn)
    run = fixtures.decision_run("guardrails_unsure")  # the fixtures already hold one review of it
    record_review(conn, run.decision_id, review(final="flag"), RULES, now=NOW)
    assert [r.final for r in records.load_review_outcomes(conn, run.decision_id)] == ["approve", "flag"]


def test_any_route_can_be_reviewed(conn):
    seed(conn)
    record_review(conn, fixtures.decision_run("auto_approved").decision_id, review(), RULES, now=NOW)


def test_an_unknown_run_is_refused(conn):
    with pytest.raises(UnknownRun):
        record_review(conn, uuid4(), review(), RULES, now=NOW)


def test_a_run_the_agent_is_still_working_on_is_refused(conn):
    seed(conn)
    with pytest.raises(NotDecided):
        record_review(conn, fixtures.decision_run("agent_working").decision_id, review(), RULES, now=NOW)


def test_flags_of_another_run_and_unknown_rules_are_refused(conn):
    seed(conn)
    other = fixtures.flags("flag_over_limit")[0]
    body = review(per_flag=[{"flag_id": str(other.flag_id), "agree": True}], missed_rule_ids=["OSU-XYZ-99"])
    with pytest.raises(InvalidReview) as refused:
        record_review(conn, fixtures.decision_run("guardrails_unsure").decision_id, body, RULES, now=NOW)
    assert refused.value.errors == (
        ("per_flag.0.flag_id", "not a flag of this run"),
        ("missed_rule_ids.0", "OSU-XYZ-99 is not an active rule"),
    )


def test_one_flag_answered_twice_is_refused(conn):
    seed(conn)
    flag = fixtures.flags("guardrails_unsure")[0]
    answer = {"flag_id": str(flag.flag_id), "agree": True}
    with pytest.raises(InvalidReview, match="already answered"):
        record_review(conn, fixtures.decision_run("guardrails_unsure").decision_id,
                      review(per_flag=[answer, answer]), RULES, now=NOW)


def test_answering_every_flag_is_optional(conn):
    seed(conn)
    record_review(conn, fixtures.decision_run("lodging_stay_2").decision_id, review(per_flag=[]), RULES, now=NOW)


@pytest.mark.parametrize(
    "typed, saved",
    [("Ana", "ana"), ("  Ana  ", "ana"), ("Ana   Lopez", "ana lopez"), ("ANA\tLOPEZ", "ana lopez")],
)
def test_the_reviewer_name_is_saved_normalized(conn, typed, saved):
    assert normalize_reviewer(typed) == saved
    seed(conn)
    run = fixtures.decision_run("guardrails_unsure")
    assert record_review(conn, run.decision_id, review(reviewer=typed), RULES, now=NOW).reviewer == saved


def test_a_blank_reviewer_name_is_refused(conn):
    seed(conn)
    run = fixtures.decision_run("guardrails_unsure")
    before = records.load_review_outcomes(conn, run.decision_id)
    with pytest.raises(InvalidReview) as refused:
        record_review(conn, run.decision_id, review(reviewer="   "), RULES, now=NOW)
    assert refused.value.errors == (("reviewer", "must not be blank"),)
    assert records.load_review_outcomes(conn, run.decision_id) == before  # nothing was saved
