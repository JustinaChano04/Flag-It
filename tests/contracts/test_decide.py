"""Flags, agent verdicts, the screener result, and decision-run routing rules."""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from flag_it.contracts.decide import ROUTES_BY_DECIDER, AgentOutput, AgentVerdict, ScreenerResult
from flag_it.contracts.enums import DecidedBy, Route
from flag_it.contracts.examples import AS_OF, citation, decision_run, flag

POLICY = citation(kind="policy", ref="OSU-GEN-02", value=None)
SCREENER_LOW = ScreenerResult(probability=0.1, threshold=0.2, model_version="m1")


def _verdict(**over) -> AgentVerdict:
    data = {"check_id": "OSU-GEN-02b", "result": "pass", "confidence": 0.9}
    return AgentVerdict(**(data | over))


# Flags


def test_flag_check_id_must_belong_to_rule():
    with pytest.raises(ValidationError, match="does not belong to rule"):
        flag(check_id="OSU-LIM-02a")


def test_flag_needs_evidence():
    with pytest.raises(ValidationError):
        flag(evidence=[])


# A code check is pass or fail, so its flag scores 1.0. Only the agent gives partial scores.
def test_code_flags_score_one():
    with pytest.raises(ValidationError, match="must score 1.0"):
        flag(score=0.8)
    assert flag(source="llm", score=0.8).score == 0.8


# Only code checks and the agent create flags, so FlagSource has no screener value.
def test_the_screener_cannot_create_flags():
    with pytest.raises(ValidationError):
        flag(source="model")


# due_at is when the deadline passes.
def test_pending_flags_carry_due_at_and_only_they_do():
    assert flag(result="pending", due_at=AS_OF).due_at == AS_OF
    with pytest.raises(ValidationError, match="due_at"):
        flag(result="pending")
    with pytest.raises(ValidationError, match="due_at"):
        flag(result="fail", due_at=AS_OF)


def test_flag_evidence_is_a_tuple():
    assert isinstance(flag().evidence, tuple)


# Agent verdicts


# A fail verdict must point at the policy text it relies on.
def test_agent_fail_must_cite_the_policy():
    with pytest.raises(ValidationError, match="policy citation"):
        _verdict(result="fail", evidence=[citation()])
    assert _verdict(result="fail", evidence=[POLICY]).result == "fail"


@pytest.mark.parametrize("result", ["fail", "unsure"])
def test_non_pass_verdicts_need_evidence(result):
    with pytest.raises(ValidationError, match="at least one citation"):
        _verdict(result=result, evidence=[])


def test_pass_may_have_no_evidence():
    assert _verdict().evidence == ()


def test_agent_output_needs_one_verdict_per_check():
    with pytest.raises(ValidationError, match="only once"):
        AgentOutput(verdicts=[_verdict(), _verdict()])


def test_agent_output_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        AgentOutput(verdicts=[_verdict()], comment="extra text from the model")


# Screener


def test_screener_threshold_boundary():
    # Only a probability below the threshold auto-approves.
    assert ScreenerResult(probability=0.2, threshold=0.2, model_version="m1").sends_to_agent
    assert ScreenerResult(probability=1.0, threshold=0.2, model_version="stand-in-1").sends_to_agent
    assert not SCREENER_LOW.sends_to_agent


# Decision runs


def test_decision_run_route_and_decider_set_together():
    assert decision_run(route=None, decided_by=None).route is None
    with pytest.raises(ValidationError, match="together"):
        decision_run(route=None)
    with pytest.raises(ValidationError, match="together"):
        decision_run(decided_by=None)


def _valid_extras(decider: DecidedBy, route: Route) -> dict:
    """The other fields a run with this decider and route needs, so only the pairing is tested."""
    extras: dict = {}
    if decider is DecidedBy.SCREENER:
        extras["screener"] = SCREENER_LOW
    if route is Route.HUMAN_REVIEW:
        extras["escalation_reasons"] = ["review_conflict" if decider is DecidedBy.RERUN else "agent_failed"]
    if decider is DecidedBy.RERUN:
        extras |= {"trigger": "late_receipt", "replaces_decision_id": uuid4()}
    return extras


@pytest.mark.parametrize("decider", list(DecidedBy))
@pytest.mark.parametrize("route", list(Route))
# Every decider and route pair: allowed only if listed in ROUTES_BY_DECIDER.
def test_decider_can_only_choose_its_own_routes(decider, route):
    run = lambda: decision_run(route=route, decided_by=decider, **_valid_extras(decider, route))
    if route in ROUTES_BY_DECIDER[decider]:
        assert run().route is route
    else:
        with pytest.raises(ValidationError, match="cannot choose route"):
            run()


# Auto-approve needs a screener result with probability below its threshold.
def test_screener_decision_needs_a_low_screener_result():
    with pytest.raises(ValidationError, match="screener result"):
        decision_run(route="auto_approve", decided_by="screener")
    high = ScreenerResult(probability=0.9, threshold=0.2, model_version="m1")
    with pytest.raises(ValidationError, match="below its threshold"):
        decision_run(route="auto_approve", decided_by="screener", screener=high)


def test_human_review_needs_reasons_and_only_human_review_has_them():
    with pytest.raises(ValidationError, match="escalation_reasons"):
        decision_run(route="human_review", decided_by="guardrails")
    with pytest.raises(ValidationError, match="escalation_reasons"):
        decision_run(escalation_reasons=["agent_failed"])
    run = decision_run(route="human_review", decided_by="guardrails", escalation_reasons=["unsure:OSU-GEN-02b"])
    assert run.escalation_reasons == ("unsure:OSU-GEN-02b",)


def test_escalation_reasons_are_checked():
    with pytest.raises(ValidationError):
        decision_run(route="human_review", decided_by="guardrails", escalation_reasons=["felt_off"])


def test_initial_runs_replace_nothing_and_reruns_replace_something():
    with pytest.raises(ValidationError, match="replaces_decision_id"):
        decision_run(trigger="initial", replaces_decision_id=uuid4())
    with pytest.raises(ValidationError, match="replaces_decision_id"):
        decision_run(trigger="deadline")
    assert decision_run(trigger="deadline", replaces_decision_id=uuid4()).trigger == "deadline"


# decided_by=rerun goes with the review_conflict reason, and a rerun can't come from an initial run.
def test_a_review_conflict_is_a_rerun_decision():
    with pytest.raises(ValidationError, match="review_conflict"):
        decision_run(
            route="human_review", decided_by="rerun", escalation_reasons=["agent_failed"],
            trigger="late_receipt", replaces_decision_id=uuid4(),
        )
    with pytest.raises(ValidationError, match="initial"):
        decision_run(route="human_review", decided_by="rerun", escalation_reasons=["review_conflict"])
