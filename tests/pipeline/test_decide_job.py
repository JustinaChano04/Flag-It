from datetime import timedelta
from uuid import uuid4

import pytest

from flag_it.contracts import examples as ex
from flag_it.contracts.decide import Citation
from flag_it.contracts.enums import CheckMethod, DecidedBy, FlagResult, ReviewFinal, Route, RunTrigger
from flag_it.contracts.jobs import DecideJob, InvestigateJob
from flag_it.contracts.review import ReviewOutcome
from flag_it.db import records
from flag_it.decide.checks.base import Finding, NeedsReview
from flag_it.pipeline import decide_job
from flag_it.pipeline.decide_job import handle_decide
from flag_it.pipeline.jobs import INVESTIGATE, job_id_investigate
from flag_it.pipeline.versions import stamp
from tests.pipeline.helpers import NOW, RULES, SIGNOFF, Controls, context, save_receipt, save_results

FOUND = Finding((Citation(kind="field", ref="transaction.amount", value="412.00"),))
MAYBE = NeedsReview((Citation(kind="field", ref="transaction.amount", value="412.00"),))


def payload(trigger=RunTrigger.INITIAL):
    return DecideJob(txn_id=ex.TXN_ID, trigger=trigger).model_dump(mode="json")


def current(conn):
    return records.load_current_decision(conn, ex.TXN_ID)


def runs(conn):
    return records.load_decision_history(conn, ex.TXN_ID)


def review(run, final, hours=1):
    return ReviewOutcome(
        review_id=uuid4(), decision_id=run.decision_id, reviewer="pat", final=final,
        created_at=NOW + timedelta(hours=hours),
    )


def test_a_hard_failure_routes_flag_decided_by_rules(conn):
    save_results(conn)
    controls = Controls(limit=FOUND)
    assert handle_decide(conn, context(controls), payload(), now=NOW) == ()
    run = current(conn)
    assert (run.route, run.decided_by, run.screener) == (Route.FLAG, DecidedBy.RULES, None)
    assert any(f.check_id == "OSU-LIM-01a" for f in records.load_flags(conn, run.decision_id))


def test_a_clean_transaction_auto_approves_only_when_the_screener_says_so(conn):
    save_results(conn)
    assert handle_decide(conn, context(p=0.1), payload(), now=NOW) == ()
    run = current(conn)
    assert (run.route, run.decided_by) == (Route.AUTO_APPROVE, DecidedBy.SCREENER)
    assert run.screener.probability == 0.1


def test_the_stand_in_screener_sends_it_to_the_agent_with_the_check_ids(conn):
    save_results(conn)
    (spec,) = handle_decide(conn, context(Controls(limit=MAYBE), p=1.0), payload(), now=NOW)
    run = current(conn)
    assert run.route is None and run.screener is not None
    assert (spec.name, spec.job_id) == (INVESTIGATE, job_id_investigate(run.decision_id))
    job = InvestigateJob.model_validate(spec.payload)
    assert (job.decision_id, job.snapshot_id) == (run.decision_id, run.snapshot_id)
    llm = [c.id for _, c in RULES.checks_for("meals_refreshments", CheckMethod.LLM)]
    assert list(job.check_ids) == llm + ["OSU-LIM-01a"] or set(job.check_ids) == set(llm) | {"OSU-LIM-01a"}


def test_the_agent_path_without_unclear_flags_lists_only_the_llm_checks(conn):
    save_results(conn)
    (spec,) = handle_decide(conn, context(p=1.0), payload(), now=NOW)
    job = InvestigateJob.model_validate(spec.payload)
    llm = [c.id for _, c in RULES.checks_for("meals_refreshments", CheckMethod.LLM)]
    assert list(job.check_ids) == llm


def test_needs_review_is_never_auto_approved(conn):
    save_results(conn)
    handle_decide(conn, context(Controls(limit=MAYBE), p=0.0), payload(), now=NOW)
    assert current(conn).route is None


def test_a_repeated_initial_job_creates_one_run(conn):
    save_results(conn)
    handle_decide(conn, context(p=0.1), payload(), now=NOW)
    assert handle_decide(conn, context(p=0.1), payload(), now=NOW) == ()
    assert len(runs(conn)) == 1


def test_a_late_receipt_makes_a_second_run_and_a_repeat_does_nothing(conn):
    save_results(conn)
    handle_decide(conn, context(p=0.1), payload(), now=NOW)
    first = current(conn)
    assert handle_decide(conn, context(p=0.1), payload(RunTrigger.LATE_RECEIPT), now=NOW) == ()  # no receipt yet
    save_receipt(conn)
    later = NOW + timedelta(hours=1)
    handle_decide(conn, context(p=0.1), payload(RunTrigger.LATE_RECEIPT), now=later)
    second = current(conn)
    assert (second.trigger, second.replaces_decision_id) == (RunTrigger.LATE_RECEIPT, first.decision_id)
    assert records.load_snapshot(conn, second.snapshot_id).payload.receipt is not None
    handle_decide(conn, context(p=0.1), payload(RunTrigger.LATE_RECEIPT), now=later)
    assert len(runs(conn)) == 2


def test_a_second_receipt_after_a_late_receipt_run_makes_a_third_run(conn):
    save_results(conn)
    handle_decide(conn, context(p=0.1), payload(), now=NOW)
    save_receipt(conn)
    handle_decide(conn, context(p=0.1), payload(RunTrigger.LATE_RECEIPT), now=NOW)
    save_receipt(conn)
    handle_decide(conn, context(p=0.1), payload(RunTrigger.LATE_RECEIPT), now=NOW)
    handle_decide(conn, context(p=0.1), payload(RunTrigger.LATE_RECEIPT), now=NOW)
    assert len(runs(conn)) == 3


def test_an_earlier_approve_and_a_rerun_that_flags_is_a_review_conflict(conn):
    save_results(conn)
    controls = Controls()
    handle_decide(conn, context(controls, p=0.1), payload(), now=NOW)
    records.save_review_outcome(conn, review(current(conn), ReviewFinal.APPROVE))
    controls.limit = FOUND
    save_receipt(conn)
    handle_decide(conn, context(controls, p=0.1), payload(RunTrigger.LATE_RECEIPT), now=NOW)
    run = current(conn)
    assert (run.route, run.decided_by, run.escalation_reasons) == (
        Route.HUMAN_REVIEW, DecidedBy.RERUN, ("review_conflict",))


def test_an_earlier_approve_and_a_rerun_that_approves_keeps_its_route(conn):
    save_results(conn)
    handle_decide(conn, context(p=0.1), payload(), now=NOW)
    records.save_review_outcome(conn, review(current(conn), ReviewFinal.APPROVE))
    save_receipt(conn)
    handle_decide(conn, context(p=0.1), payload(RunTrigger.LATE_RECEIPT), now=NOW)
    assert current(conn).route is Route.AUTO_APPROVE


def test_a_deadline_rerun_happens_only_after_due_at(conn):
    save_results(conn)
    ctx = context(p=0.1)
    handle_decide(conn, ctx, payload(), now=NOW)
    pending = [f for f in records.load_flags(conn, current(conn).decision_id) if f.result is FlagResult.PENDING]
    assert [f.due_at for f in pending] == [SIGNOFF]
    assert handle_decide(conn, ctx, payload(RunTrigger.DEADLINE), now=SIGNOFF - timedelta(minutes=1)) == ()
    assert len(runs(conn)) == 1
    handle_decide(conn, ctx, payload(RunTrigger.DEADLINE), now=SIGNOFF)
    run = current(conn)
    assert run.trigger is RunTrigger.DEADLINE
    assert records.load_snapshot(conn, run.snapshot_id).created_at >= SIGNOFF
    assert (run.route, run.decided_by) == (Route.FLAG, DecidedBy.RULES)  # the missing receipt is now a failure
    assert handle_decide(conn, ctx, payload(RunTrigger.DEADLINE), now=SIGNOFF) == ()  # nothing pending now
    assert len(runs(conn)) == 2


def test_the_run_records_the_stamp(conn):
    save_results(conn)
    ctx = context(p=0.1)
    handle_decide(conn, ctx, payload(), now=NOW)
    assert current(conn).rules_version == stamp(ctx.rules, ctx.deployment, ctx.calendar, ctx.checkers, ctx.unsupported)


def test_a_concurrent_initial_job_that_loses_the_race_returns_nothing(conn, monkeypatch):
    save_results(conn)
    handle_decide(conn, context(p=0.1), payload(), now=NOW)
    snapshots = conn.execute("SELECT count(*) AS n FROM combined_expense_snapshot").fetchone()["n"]
    # the loser read "no run yet" before the winner committed
    monkeypatch.setattr(decide_job.records, "load_current_decision", lambda conn, txn_id: None)
    assert handle_decide(conn, context(p=0.1), payload(), now=NOW) == ()
    assert len(runs(conn)) == 1
    assert conn.execute("SELECT count(*) AS n FROM combined_expense_snapshot").fetchone()["n"] == snapshots


def test_a_job_from_another_major_version_is_rejected(conn):
    with pytest.raises(ValueError):
        handle_decide(conn, context(), {**payload(), "contract_version": "2.0.0"}, now=NOW)


def test_a_duplicate_key_that_is_not_a_lost_race_is_raised(conn, monkeypatch):
    from psycopg.errors import UniqueViolation

    save_results(conn)
    real = decide_job.run_rule_checks

    def two_flags_for_one_check(*args, **kwargs):
        outcome = real(*args, **kwargs)
        return type(outcome)(
            flags=outcome.flags + outcome.flags[:1], gates=outcome.gates, skipped=outcome.skipped
        )

    monkeypatch.setattr(decide_job, "run_rule_checks", two_flags_for_one_check)
    with pytest.raises(UniqueViolation):
        handle_decide(conn, context(Controls(limit=FOUND), p=0.1), payload(), now=NOW)


def test_the_stamp_follows_the_checkers_the_context_carries():
    import dataclasses

    one = context(Controls())
    other = dataclasses.replace(one, checkers={**one.checkers, "OSU-GEN-04b": lambda ctx: None})
    assert stamp(one.rules, one.deployment, one.calendar, one.checkers, one.unsupported) != stamp(
        other.rules, other.deployment, other.calendar, other.checkers, other.unsupported
    )
