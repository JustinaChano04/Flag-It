"""Invalid agent outputs fail as expected; jobs and reviews point at real runs and flags."""

import pytest
from pydantic import ValidationError

from flag_it.contracts.decide import AgentOutput
from flag_it.contracts.enums import CheckMethod, DecidedBy, ReviewFinal
from flag_it.fixtures.build import (
    INVALID_AGENT_OUTPUTS,
    agent_outputs,
    decision_runs,
    flags,
    investigate_jobs,
    read_receipt_jobs,
    receipts,
    review_outcomes,
    snapshots,
)


@pytest.fixture(scope="module")
def built(rules):
    snaps = snapshots(rules)
    runs = decision_runs(rules, snaps)
    found = flags(rules, runs, agent_outputs())
    return snaps, runs, found, review_outcomes(runs, found)


@pytest.mark.parametrize("name", sorted(INVALID_AGENT_OUTPUTS))
def test_invalid_agent_outputs_fail_with_their_error(name):
    case = INVALID_AGENT_OUTPUTS[name]
    with pytest.raises(ValidationError, match=case["error"]):
        AgentOutput.model_validate(case["output"])


def test_investigate_jobs_are_exactly_the_runs_sent_to_the_agent(built):
    _, runs, _, _ = built
    sent = {n for n, r in runs.items() if r.screener is not None and r.screener.sends_to_agent}
    assert set(investigate_jobs(runs)) == sent
    assert {n for n in agent_outputs() if n in runs} <= sent


def test_job_checks_are_llm_checks_for_the_category_and_match_the_answers(rules, built):
    snaps, runs, _, _ = built
    by_id = {s.snapshot_id: s for s in snaps.values()}
    outputs = agent_outputs()
    for name, job in investigate_jobs(runs).items():
        category = by_id[job.snapshot_id].payload.category.category
        allowed = {c.id for _, c in rules.checks_for(category, CheckMethod.LLM)}
        assert set(job.check_ids) <= allowed
        if name in outputs:
            assert {v.check_id for v in outputs[name].verdicts} == set(job.check_ids)


def test_a_read_receipt_job_per_receipt():
    jobs = read_receipt_jobs()
    assert {(j.receipt_id, j.txn_id) for j in jobs.values()} == {(r.receipt_id, r.txn_id) for r in receipts().values()}


def test_reviews_point_at_runs_and_their_flags(rules, built):
    _, runs, found, reviews = built
    by_id = {r.decision_id: (n, r) for n, r in runs.items()}
    for review in reviews.values():
        name, run = by_id[review.decision_id]
        assert review.created_at > run.created_at
        assert {f.flag_id for f in review.per_flag} == {f.flag_id for f in found.get(name, ())}
        for rule_id in review.missed_rule_ids:
            rules.rule(rule_id)


def test_the_rerun_conflict_contradicts_an_earlier_review(built):
    _, runs, _, reviews = built
    for name, run in runs.items():
        if run.decided_by is DecidedBy.RERUN:
            earlier = [r for r in reviews.values() if r.decision_id == run.replaces_decision_id]
            assert earlier and earlier[-1].final is ReviewFinal.APPROVE, name
            assert earlier[-1].created_at < run.created_at
