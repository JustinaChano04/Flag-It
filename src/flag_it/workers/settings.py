"""The Arq worker: runs every stage of the pipeline from the queue, and the sweeps on a timer.

    .venv/bin/python -m arq flag_it.workers.settings.WorkerSettings

Each job function is a thin wrapper. It opens a connection, runs the stage's handler (which does its work
in that transaction and returns the next jobs instead of enqueuing them), commits, and only then enqueues
the returned jobs, so a job never starts before the rows it needs are visible. Handlers and enqueues are
synchronous, so they run in `asyncio.to_thread`: a blocking database call must not stall the worker.

Retries: Arq retries a job only when it raises Retry. understand and read_receipt retry while their rows
are not visible yet (the request that queued them has not committed). A failed investigation is retried
with a delay until max_tries, then ended in human_review with agent_failed by the last-try hook below. The
stuck-run sweep is the backstop for a worker that crashed. Every job has a deterministic job ID, and
keep_result is 60 seconds, so a repeated enqueue is ignored briefly and every handler is a no-op on a repeat.

The rules are loaded when this module is imported, because Arq reads max_tries then.
Settings: FLAG_IT_REDIS_URL and FLAG_IT_DATABASE_URL, plus the stage settings (FLAG_IT_JUDGE_MODEL,
FLAG_IT_OLLAMA_URL, FLAG_IT_READER_MODEL, the receipt store's, ANTHROPIC_API_KEY).
"""

import asyncio
import dataclasses
import logging
import os
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from typing import Any

from arq.connections import RedisSettings
from arq.cron import cron
from arq.worker import Retry, func

from flag_it.contracts.decide import DecisionRun
from flag_it.contracts.enums import DecidedBy, Route
from flag_it.contracts.jobs import InvestigateJob, load_job
from flag_it.contracts.rules import load_rules
from flag_it.db import records
from flag_it.db.connection import connect
from flag_it.decide.agent.anthropic_client import default_client
from flag_it.decide.agent.guardrails import GuardrailResult
from flag_it.decide.agent.handler import handle_investigate
from flag_it.decide.checks.calendar import load_calendar
from flag_it.decide.checks.deployment import load_deployment
from flag_it.decide.screener import STAND_IN
from flag_it.pipeline import sweeps
from flag_it.pipeline.decide_job import DecideContext, handle_decide
from flag_it.pipeline.jobs import DECIDE, INVESTIGATE, READ_RECEIPT, UNDERSTAND, JobSpec
from flag_it.pipeline.reconcile import prior_final, reconcile
from flag_it.pipeline.understand_job import handle_understand
from flag_it.understand.anomaly import load_anomaly_config
from flag_it.understand.categorize import load_lookup
from flag_it.understand.receipts.matching import load_match_config
from flag_it.understand.receipts.reader import reader_from_env
from flag_it.understand.receipts.store import store_from_env
from flag_it.understand.receipts.worker import decide_after_receipt, handle_read_receipt
from flag_it.workers.queue import REDIS_URL_ENV, ArqStageQueue

log = logging.getLogger(__name__)

RULES = load_rules()
PIPELINE = RULES.pipeline_settings()
KEEP_RESULT = 60  # seconds a finished job's ID stays blocked; handlers are no-ops on a repeat anyway
INVESTIGATE_RETRY_DEFER = 30  # seconds

Ctx = dict[str, Any]


def _now(ctx: Ctx) -> datetime:
    return ctx["clock"]() if "clock" in ctx else datetime.now(timezone.utc)


async def _enqueue(ctx: Ctx, specs: Sequence[JobSpec]) -> None:
    """Called after the commit. A failure here fails the job; the sweeps find the lost work."""
    for spec in specs:
        await asyncio.to_thread(ctx["queue"].enqueue, spec)


async def _run(ctx: Ctx, work: Callable[[Any], Sequence[JobSpec]]) -> None:
    """Run `work(conn)` in a thread on its own connection, commit, then enqueue what it returned."""

    def in_transaction() -> Sequence[JobSpec]:
        with ctx["connect"]() as conn:  # commits when the block ends without an error
            return work(conn)

    specs = await asyncio.to_thread(in_transaction)
    await _enqueue(ctx, specs)


# ---------------------------------------------------------------- stage jobs


async def understand_job(ctx: Ctx, payload: dict[str, Any]) -> None:
    await _run(ctx, lambda conn: handle_understand(conn, ctx["lookup"], ctx["anomaly_config"], payload))


async def decide_job(ctx: Ctx, payload: dict[str, Any]) -> None:
    await _run(ctx, lambda conn: handle_decide(conn, ctx["decide_context"], payload, now=_now(ctx)))


async def read_receipt_job(ctx: Ctx, payload: dict[str, Any]) -> None:
    def work(conn) -> Sequence[JobSpec]:
        extraction = handle_read_receipt(conn, ctx["store"], ctx["reader"], ctx["match_config"], payload)
        return decide_after_receipt(conn, extraction)

    await _run(ctx, work)


def _investigate(ctx: Ctx, payload: dict[str, Any]) -> None:
    with ctx["connect"]() as conn:

        def review_conflict(run: DecisionRun, result: GuardrailResult) -> GuardrailResult:
            route, decided_by, reasons = reconcile(
                result.route, result.decided_by, result.escalation_reasons, prior_final(conn, run.txn_id)
            )
            return dataclasses.replace(result, route=route, decided_by=decided_by, escalation_reasons=reasons)

        handle_investigate(conn, ctx["llm"], ctx["rules"], payload, reconcile=review_conflict)


def _end_run(ctx: Ctx, payload: dict[str, Any]) -> None:
    """The last-try hook: send the run to a person. A run that already has a route is left alone."""
    job = load_job(InvestigateJob, payload)
    with ctx["connect"]() as conn:
        records.fill_route(
            conn, job.decision_id, route=Route.HUMAN_REVIEW, decided_by=DecidedBy.GUARDRAILS,
            escalation_reasons=("agent_failed",),
        )


async def investigate_job(ctx: Ctx, payload: dict[str, Any]) -> None:
    try:
        await asyncio.to_thread(_investigate, ctx, payload)
    except Retry:
        raise
    except Exception as error:
        tries, max_tries = ctx.get("job_try", 1), ctx.get("max_tries", PIPELINE.max_tries)
        if tries < max_tries:
            log.warning("investigate failed on try %d of %d, retrying: %r", tries, max_tries, error)
            raise Retry(defer=INVESTIGATE_RETRY_DEFER) from error
        log.exception("investigate failed on its last try (%d); ending the run in human_review", tries)
        await asyncio.to_thread(_end_run, ctx, payload)


# ---------------------------------------------------------------- sweeps (cron)


async def _sweep(ctx: Ctx, find: Callable[[Any, datetime], Sequence[JobSpec]]) -> None:
    now = _now(ctx)
    await _run(ctx, lambda conn: find(conn, now))


async def sweep_due_reruns(ctx: Ctx) -> None:
    await _sweep(ctx, lambda conn, now: sweeps.due_reruns(conn, now, PIPELINE))


async def sweep_unrun_transactions(ctx: Ctx) -> None:
    await _sweep(ctx, lambda conn, now: sweeps.unrun_transactions(conn, now, PIPELINE))


async def sweep_unread_receipts(ctx: Ctx) -> None:
    await _sweep(ctx, lambda conn, now: sweeps.unread_receipts(conn, now, PIPELINE, ctx["reader"].model_tag))


async def sweep_lost_receipts(ctx: Ctx) -> None:
    await _sweep(ctx, lambda conn, now: sweeps.lost_receipts(conn, now, PIPELINE, ctx["reader"].model_tag))


async def sweep_stuck_runs(ctx: Ctx) -> None:
    def end_stuck(conn, now) -> Sequence[JobSpec]:
        for run in sweeps.stuck_runs(conn, now, PIPELINE):
            log.error("run %s for %s had no route after %d minutes: sent to human_review",
                      run.decision_id, run.txn_id, PIPELINE.stuck_after_minutes)
        return ()

    await _sweep(ctx, end_stuck)


# ---------------------------------------------------------------- worker


async def startup(ctx: Ctx) -> None:
    """Load everything that doesn't change between jobs, once."""
    lookup, anomaly_config, reader = load_lookup(RULES), load_anomaly_config(), reader_from_env()
    ctx.update(
        connect=connect,
        queue=ArqStageQueue(os.environ[REDIS_URL_ENV]),
        rules=RULES,
        max_tries=PIPELINE.max_tries,
        lookup=lookup,
        anomaly_config=anomaly_config,
        decide_context=DecideContext(
            rules=RULES,
            deployment=load_deployment(),
            calendar=load_calendar(),
            screener=STAND_IN,
            mcc_version=lookup.version,
            anomaly_version=anomaly_config.version,
            reader_model=reader.model_tag,
        ),
        llm=default_client(),
        store=store_from_env(),
        reader=reader,
        match_config=load_match_config(),
    )


async def shutdown(ctx: Ctx) -> None:
    if "queue" in ctx:
        await asyncio.to_thread(ctx["queue"].close)


def _stage(coroutine, name: str):
    return func(coroutine, name=name, keep_result=KEEP_RESULT)


class WorkerSettings:
    functions = [
        _stage(understand_job, UNDERSTAND),
        _stage(decide_job, DECIDE),
        _stage(investigate_job, INVESTIGATE),
        _stage(read_receipt_job, READ_RECEIPT),
    ]
    cron_jobs = [  # every minute, on the minute; each needs its own name
        cron(sweep_due_reruns, name="sweep_due_reruns"),
        cron(sweep_unrun_transactions, name="sweep_unrun_transactions"),
        cron(sweep_unread_receipts, name="sweep_unread_receipts"),
        cron(sweep_lost_receipts, name="sweep_lost_receipts"),
        cron(sweep_stuck_runs, name="sweep_stuck_runs"),
    ]
    on_startup = startup
    on_shutdown = shutdown
    max_tries = PIPELINE.max_tries
    keep_result = KEEP_RESULT
    redis_settings = RedisSettings.from_dsn(os.environ.get(REDIS_URL_ENV, "redis://localhost:6379"))
