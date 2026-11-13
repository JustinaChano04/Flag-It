"""Fixture decision runs and flags agree with the contract and the rules YAML."""

import pytest

from flag_it.contracts.enums import AgentResult, DecidedBy, FlagResult, FlagSource, Route, RunTrigger, Severity
from flag_it.fixtures.build import agent_outputs, decision_runs, flags, snapshots

HARD_SEVERITIES = {Severity.PROHIBITED, Severity.CONDITIONAL, Severity.DOCUMENTATION}


@pytest.fixture(scope="module")
def built(rules):
    snaps = snapshots(rules)
    runs = decision_runs(rules, snaps)
    outputs = agent_outputs()
    return snaps, runs, outputs, flags(rules, runs, outputs)


def is_hard_failure(flag) -> bool:
    return (
        flag.source is FlagSource.CODE
        and flag.result in (FlagResult.FAIL, FlagResult.VIOLATION)
        and flag.severity in HARD_SEVERITIES
    )


def test_every_route_decider_and_trigger_appears(built):
    _, runs, _, _ = built
    assert {r.route for r in runs.values()} == set(Route) | {None}
    assert {r.decided_by for r in runs.values()} == set(DecidedBy) | {None}
    assert {r.trigger for r in runs.values()} == set(RunTrigger)


def test_each_run_has_its_own_snapshot_of_its_transaction(built):
    snaps, runs, _, _ = built
    by_id = {s.snapshot_id: s for s in snaps.values()}
    assert len({r.snapshot_id for r in runs.values()}) == len(runs)
    for run in runs.values():
        assert by_id[run.snapshot_id].txn_id == run.txn_id


def test_reruns_form_one_chain_per_transaction(built):
    _, runs, _, _ = built
    by_id = {r.decision_id: r for r in runs.values()}
    initial = [r.txn_id for r in runs.values() if r.trigger is RunTrigger.INITIAL]
    assert len(initial) == len(set(initial))
    replaced = [r.replaces_decision_id for r in runs.values() if r.replaces_decision_id]
    assert len(replaced) == len(set(replaced))
    for run in runs.values():
        if run.replaces_decision_id:
            earlier = by_id[run.replaces_decision_id]
            assert earlier.txn_id == run.txn_id and earlier.created_at < run.created_at


def test_flags_match_their_rules_checks_and_runs(rules, built):
    snaps, runs, _, found = built
    by_id = {s.snapshot_id: s for s in snaps.values()}
    for run_name, run_flags in found.items():
        run = runs[run_name]
        category = by_id[run.snapshot_id].payload.category.category
        for flag in run_flags:
            rule, check = rules.check(flag.check_id)
            assert (flag.rule_id, flag.severity, flag.source.value) == (rule.id, rule.severity, check.method.value)
            assert "all" in rule.applies_to or category in rule.applies_to, flag.check_id
            assert (flag.decision_id, flag.txn_id) == (run.decision_id, run.txn_id)


def test_hard_failures_decide_exactly_the_rules_and_rerun_routes(built):
    _, runs, _, found = built
    for name, run in runs.items():
        hard = any(is_hard_failure(f) for f in found.get(name, ()))
        assert hard == (run.decided_by in (DecidedBy.RULES, DecidedBy.RERUN)), name


def test_agent_flags_copy_the_agent_verdicts(built):
    _, _, outputs, found = built
    for name, run_flags in found.items():
        for flag in run_flags:
            if flag.source is FlagSource.LLM:
                verdict = next(v for v in outputs[name].verdicts if v.check_id == flag.check_id)
                expected = FlagResult.FAIL if verdict.result is AgentResult.FAIL else FlagResult.UNCLEAR
                assert (flag.result, flag.score, flag.evidence) == (expected, verdict.confidence, verdict.evidence)


def test_escalation_reasons_point_at_agent_verdicts(built):
    _, runs, outputs, _ = built
    for name, run in runs.items():
        for reason in run.escalation_reasons:
            if ":" in reason:
                kind, check_id = reason.split(":")
                verdict = next(v for v in outputs[name].verdicts if v.check_id == check_id)
                assert kind != "unsure" or verdict.result is AgentResult.UNSURE


def test_pending_flags_are_due_at_signoff(built):
    _, _, _, found = built
    pending = [f for fs in found.values() for f in fs if f.result is FlagResult.PENDING]
    assert pending and all(f.due_at is not None for f in pending)
