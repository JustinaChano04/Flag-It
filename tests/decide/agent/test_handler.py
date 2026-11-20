"""The investigate job end to end, with a scripted model and a real database."""

from uuid import uuid4

import pytest

from flag_it.contracts import examples as ex
from flag_it.contracts.enums import DecidedBy, FlagResult, FlagSource, Route
from flag_it.contracts.jobs import InvestigateJob
from flag_it.contracts.rules import load_rules
from flag_it.db import examples as db_ex
from flag_it.db import records
from flag_it.decide.agent.handler import JOB_NAME, handle_investigate
from flag_it.decide.agent.llm import LlmUnavailable
from tests.decide.agent.fakes import ScriptedClient, reply, submit, use, verdict

RULES = load_rules()
POLICY = {"kind": "policy", "ref": "OSU-PRH-09"}
FIELD = {"kind": "field", "ref": "transaction.amount"}
BOTH = ("OSU-GEN-06a", "OSU-PRH-09a")


def waiting_run(conn):
    """The example transaction, snapshot and a run the agent is working on (no route yet)."""
    db_ex.save_example_results(conn)
    records.save_snapshot(conn, db_ex.snapshot())
    run = ex.decision_run(route=None, decided_by=None)
    records.save_decision_run(conn, run)
    return run


def job(run, check_ids=BOTH, **over):
    payload = InvestigateJob(
        decision_id=run.decision_id, snapshot_id=run.snapshot_id, check_ids=check_ids
    ).model_dump(mode="json")
    return payload | over


def passes(*ids):
    return submit(*(verdict(c, "pass", 0.9) for c in ids))


def test_the_job_name_is_the_contracts():
    assert JOB_NAME == "investigate"


def test_all_pass_approves_and_saves_the_verdicts(conn):
    run = waiting_run(conn)
    decided = handle_investigate(conn, ScriptedClient(passes(*BOTH)), RULES, job(run))
    assert (decided.route, decided.decided_by, decided.escalation_reasons) == (Route.AGENT_APPROVE, DecidedBy.AGENT, ())
    assert records.load_decision_run(conn, run.decision_id).route is Route.AGENT_APPROVE
    assert [v.check_id for v in records.load_agent_verdicts(conn, run.decision_id)] == list(BOTH)
    assert records.load_flags(conn, run.decision_id) == ()


def test_a_fail_flags_with_the_agents_evidence(conn):
    run = waiting_run(conn)
    client = ScriptedClient(submit(verdict("OSU-GEN-06a", "pass", 0.9), verdict("OSU-PRH-09a", "fail", 0.8, POLICY, FIELD)))
    decided = handle_investigate(conn, client, RULES, job(run))
    assert decided.route is Route.AGENT_FLAG
    [flag] = records.load_flags(conn, run.decision_id)
    assert (flag.check_id, flag.result, flag.source, flag.score) == ("OSU-PRH-09a", FlagResult.FAIL, FlagSource.LLM, 0.8)


def test_an_unsure_verdict_goes_to_a_person_with_the_reason_and_an_unclear_flag(conn):
    run = waiting_run(conn)
    client = ScriptedClient(submit(verdict("OSU-GEN-06a", "unsure", 0.9, FIELD), verdict("OSU-PRH-09a", "pass", 0.9)))
    decided = handle_investigate(conn, client, RULES, job(run))
    assert (decided.route, decided.decided_by, decided.escalation_reasons) == (
        Route.HUMAN_REVIEW, DecidedBy.GUARDRAILS, ("unsure:OSU-GEN-06a",)
    )
    assert [(f.check_id, f.result) for f in records.load_flags(conn, run.decision_id)] == [("OSU-GEN-06a", FlagResult.UNCLEAR)]


def test_a_cited_tool_call_resolves_through_the_ledger(conn):
    run = waiting_run(conn)
    client = ScriptedClient(
        reply(use("tu_1", "cardholder_history")),
        submit(
            verdict("OSU-GEN-06a", "pass", 0.9),
            verdict("OSU-PRH-09a", "fail", 0.9, POLICY, {"kind": "tool_result", "ref": "tu_1"}),
        ),
    )
    assert handle_investigate(conn, client, RULES, job(run)).route is Route.AGENT_FLAG


def test_a_tool_call_that_was_never_made_cannot_be_cited(conn):
    run = waiting_run(conn)
    forged = ScriptedClient(submit(
        verdict("OSU-GEN-06a", "pass", 0.9),
        verdict("OSU-PRH-09a", "fail", 0.9, POLICY, {"kind": "tool_result", "ref": "never_called"}),
    ))
    decided = handle_investigate(conn, forged, RULES, job(run))
    assert decided.route is Route.HUMAN_REVIEW and decided.escalation_reasons == ("citation_unresolved",)


def test_an_unclear_code_check_is_judged_and_makes_no_second_flag(conn):
    run = waiting_run(conn)
    records.save_flag(conn, ex.flag(
        rule_id="OSU-PRH-14", check_id="OSU-PRH-14a", result="unclear", source="code", score=1.0,
        evidence=[{"kind": "receipt", "ref": "receipt.line_items[0]", "value": "Interest - Nov"}],
    ))
    client = ScriptedClient(passes("OSU-GEN-06a", "OSU-PRH-14a"))
    decided = handle_investigate(conn, client, RULES, job(run, ("OSU-GEN-06a", "OSU-PRH-14a")))
    assert decided.route is Route.AGENT_APPROVE
    assert [f.source for f in records.load_flags(conn, run.decision_id)] == [FlagSource.CODE]
    assert "why_unclear" in client.calls[0]["messages"][0].text


def test_a_code_check_without_an_unclear_flag_is_refused(conn):
    run = waiting_run(conn)
    with pytest.raises(ValueError, match="OSU-PRH-14a"):
        handle_investigate(conn, ScriptedClient(), RULES, job(run, ("OSU-GEN-06a", "OSU-PRH-14a")))
    with pytest.raises(ValueError, match="NOPE-99a"):
        handle_investigate(conn, ScriptedClient(), RULES, job(run, ("NOPE-99a",)))


def test_an_unreachable_model_ends_in_agent_failed(conn):
    run = waiting_run(conn)
    decided = handle_investigate(conn, ScriptedClient(LlmUnavailable("down")), RULES, job(run))
    assert (decided.route, decided.decided_by, decided.escalation_reasons) == (
        Route.HUMAN_REVIEW, DecidedBy.GUARDRAILS, ("agent_failed",)
    )
    assert records.load_agent_verdicts(conn, run.decision_id) == ()


def test_an_invalid_answer_after_one_retry_ends_in_invalid_output(conn):
    run = waiting_run(conn)
    decided = handle_investigate(conn, ScriptedClient(submit(), submit()), RULES, job(run))
    assert decided.escalation_reasons == ("invalid_output",)
    assert records.load_agent_verdicts(conn, run.decision_id) == ()


def test_a_repeated_job_is_a_no_op_and_does_not_call_the_model(conn):
    run = waiting_run(conn)
    handle_investigate(conn, ScriptedClient(passes(*BOTH)), RULES, job(run))
    again = ScriptedClient()  # any call would raise IndexError
    assert handle_investigate(conn, again, RULES, job(run)) is None
    assert again.calls == [] and len(records.load_agent_verdicts(conn, run.decision_id)) == 2


def test_a_replaced_run_saves_nothing(conn):
    run = waiting_run(conn)
    later_snapshot = db_ex.snapshot(snapshot_id=uuid4())  # a run has its own snapshot: the table allows one run each
    records.save_snapshot(conn, later_snapshot)
    later = ex.decision_run(
        decision_id=uuid4(), snapshot_id=later_snapshot.snapshot_id, trigger="late_receipt",
        replaces_decision_id=run.decision_id, route=None, decided_by=None,
    )
    records.save_decision_run(conn, later)
    assert handle_investigate(conn, ScriptedClient(passes(*BOTH)), RULES, job(run)) is None
    assert records.load_agent_verdicts(conn, run.decision_id) == ()
    assert records.load_decision_run(conn, run.decision_id).route is None


def test_a_job_for_another_snapshot_or_major_version_is_rejected(conn):
    run = waiting_run(conn)
    with pytest.raises(ValueError, match="snapshot"):
        handle_investigate(conn, ScriptedClient(), RULES, job(run, snapshot_id=str(uuid4())))
    with pytest.raises(Exception):
        handle_investigate(conn, ScriptedClient(), RULES, job(run, contract_version="2.0.0"))


def test_a_reconcile_hook_rewrites_the_route_before_it_is_saved(conn):
    from flag_it.contracts.enums import ReviewFinal
    from flag_it.decide.agent.guardrails import GuardrailResult
    from flag_it.pipeline.reconcile import reconcile

    db_ex.save_example_decision(conn)  # an earlier run, flagged
    second = ex.decision_run(
        decision_id=uuid4(), snapshot_id=uuid4(), route=None, decided_by=None, trigger="late_receipt",
        replaces_decision_id=ex.DECISION_ID,
    )
    records.save_snapshot(conn, db_ex.snapshot(snapshot_id=second.snapshot_id))
    records.save_decision_run(conn, second)

    def conflict_rule(run, result):
        route, by, reasons = reconcile(result.route, result.decided_by, result.escalation_reasons, ReviewFinal.APPROVE)
        return GuardrailResult(route, by, reasons, result.flags)

    client = ScriptedClient(submit(verdict("OSU-GEN-06a", "pass", 0.9), verdict("OSU-PRH-09a", "fail", 0.8, POLICY, FIELD)))
    decided = handle_investigate(conn, client, RULES, job(second), reconcile=conflict_rule)
    assert (decided.route, decided.decided_by, decided.escalation_reasons) == (
        Route.HUMAN_REVIEW, DecidedBy.RERUN, ("review_conflict",))
    assert records.load_decision_run(conn, second.decision_id).route is Route.HUMAN_REVIEW
    assert [f.check_id for f in records.load_flags(conn, second.decision_id)] == ["OSU-PRH-09a"]
