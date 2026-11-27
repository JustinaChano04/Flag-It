"""The decide job: one decision run for one transaction (contracts.md steps 4-9).

Triggers: `initial` (the first run), `late_receipt` (a receipt arrived after the current run's snapshot),
`deadline` (a pending check's due time has passed). The handler first checks there is work to do, so a
repeated job is a no-op without relying on Arq alone. It then builds a new snapshot, runs the rule checks,
decides the route when it can (hard failure, or the screener says approve), and runs the result through the
review-conflict rule. A run that needs the agent is saved without a route and an `investigate` job is
returned. The handler never enqueues: the worker enqueues what it returns, after committing.

Everything runs in the caller's transaction. The run, its snapshot and its flags are written in one
savepoint, so a concurrent job that already saved the run leaves nothing behind.
"""

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import uuid4

from psycopg.errors import UniqueViolation

from flag_it.contracts.decide import DecisionRun
from flag_it.contracts.enums import CheckMethod, DecidedBy, FlagResult, FlagSource, Route, RunTrigger
from flag_it.contracts.jobs import DecideJob, load_job
from flag_it.contracts.rules import RuleSet
from flag_it.db import records
from flag_it.db.connection import Conn
from flag_it.decide.checks.base import Checker
from flag_it.decide.checks.calendar import BillingCalendar
from flag_it.decide.checks.deployment import Deployment
from flag_it.decide.checks.engine import RuleCheckOutcome, run_rule_checks
from flag_it.decide.checks.registry import CHECKERS, UNSUPPORTED
from flag_it.decide.screener import Screener, route_after_screening, screen
from flag_it.pipeline.jobs import JobSpec, investigate_spec
from flag_it.pipeline.reconcile import prior_final, reconcile
from flag_it.pipeline.snapshot import build_snapshot
from flag_it.pipeline.versions import stamp

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class DecideContext:
    """Everything the decide job needs that doesn't change between jobs. The worker builds it once."""

    rules: RuleSet
    deployment: Deployment
    calendar: BillingCalendar
    screener: Screener
    mcc_version: str
    anomaly_version: str
    reader_model: str
    checkers: Mapping[str, Checker] = CHECKERS
    unsupported: Mapping[str, str] = UNSUPPORTED


def _has_work(conn: Conn, ctx: DecideContext, job: DecideJob, current: DecisionRun | None, now: datetime) -> bool:
    if job.trigger is RunTrigger.INITIAL:
        return current is None
    if current is None:  # a rerun replaces a run, so there must be one
        return False
    if job.trigger is RunTrigger.LATE_RECEIPT:
        latest = records.latest_receipt(conn, job.txn_id, ctx.reader_model)
        if latest is None:
            return False
        have = records.load_snapshot(conn, current.snapshot_id).payload.receipt
        return have is None or have.receipt_id != latest.receipt_id
    return any(  # deadline
        f.result is FlagResult.PENDING and f.due_at is not None and f.due_at <= now
        for f in records.load_flags(conn, current.decision_id)
    )


def _investigation_checks(ctx: DecideContext, category: str, outcome: RuleCheckOutcome) -> tuple[str, ...]:
    """The applicable llm checks, then each code check this run found unclear."""
    ids = [check.id for _, check in ctx.rules.checks_for(category, CheckMethod.LLM)]
    ids += [f.check_id for f in outcome.flags if f.source is FlagSource.CODE and f.result is FlagResult.UNCLEAR]
    return tuple(dict.fromkeys(ids))


def _decide(
    conn: Conn, ctx: DecideContext, job: DecideJob, current: DecisionRun | None, now: datetime
) -> tuple[JobSpec, ...]:
    decision_id = uuid4()
    snapshot = build_snapshot(
        conn, job.txn_id, now=now, mcc_version=ctx.mcc_version, anomaly_version=ctx.anomaly_version,
        reader_model=ctx.reader_model,
    )
    outcome = run_rule_checks(
        snapshot, ctx.rules, decision_id=decision_id, deployment=ctx.deployment, calendar=ctx.calendar,
        checkers=ctx.checkers, unsupported=ctx.unsupported,
    )
    prior = prior_final(conn, job.txn_id) if current is not None else None

    screened = None
    decided: tuple[Route, DecidedBy, tuple[str, ...]] | None
    if outcome.hard_failure:
        decided = (Route.FLAG, DecidedBy.RULES, ())
    else:
        screened = screen(snapshot, ctx.screener)
        approved = route_after_screening(screened, needs_review=outcome.needs_review)
        decided = (*approved, ()) if approved else None
    if decided is not None:
        decided = reconcile(*decided, prior)

    run = DecisionRun(
        decision_id=decision_id,
        txn_id=job.txn_id,
        snapshot_id=snapshot.snapshot_id,
        route=decided[0] if decided else None,
        decided_by=decided[1] if decided else None,
        trigger=job.trigger,
        replaces_decision_id=current.decision_id if current else None,
        screener=screened,
        escalation_reasons=decided[2] if decided else (),
        rules_version=stamp(ctx.rules, ctx.deployment, ctx.calendar, ctx.checkers, ctx.unsupported),
        created_at=now,
    )
    records.save_decision_run(conn, run)
    for flag in outcome.flags:
        records.save_flag(conn, flag)
    if decided is not None:
        return ()
    check_ids = _investigation_checks(ctx, snapshot.payload.category.category, outcome)
    if not check_ids:  # nothing for the agent to judge: a person looks at it
        log.error("run %s needs the agent but has no checks to give it", decision_id)
        records.fill_route(
            conn, decision_id, route=Route.HUMAN_REVIEW, decided_by=DecidedBy.GUARDRAILS,
            escalation_reasons=("agent_failed",),
        )
        return ()
    return (investigate_spec(decision_id, snapshot.snapshot_id, check_ids),)


def handle_decide(conn: Conn, ctx: DecideContext, payload: Mapping[str, Any], *, now: datetime) -> tuple[JobSpec, ...]:
    """Returns the jobs to enqueue next: one `investigate` job, or none."""
    job = load_job(DecideJob, payload)  # rejects a job from another major contract version
    current = records.load_current_decision(conn, job.txn_id)
    if not _has_work(conn, ctx, job, current, now):
        return ()
    try:
        with conn.transaction():  # a savepoint: the snapshot, run and flags are saved together or not at all
            return _decide(conn, ctx, job, current, now)
    except UniqueViolation:
        # Two jobs for one transaction passed the check above together; the other one's run stands.
        # Any other duplicate key is a real failure, so confirm the other run exists.
        if current is None:
            row = conn.execute("SELECT 1 FROM decision_run WHERE txn_id = %s", (job.txn_id,)).fetchone()
        else:
            row = conn.execute(
                "SELECT 1 FROM decision_run WHERE replaces_decision_id = %s", (current.decision_id,)
            ).fetchone()
        if row is None:
            raise
        log.info("decide %s for %s lost the race to another run", job.trigger.value, job.txn_id)
        return ()
