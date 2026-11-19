"""The investigate job: judge one waiting decision run with the agent, then fill in its route.

Plan 21 registers handle_investigate under JOB_NAME and passes default_client(). The handler is safe to
run twice: a run that already has a route is left alone and the model is not called. A run that a later run
replaced saves nothing (fill_route returns None), though it may still cost one model call. A model that can't be reached after the SDK's retries, or an answer that is invalid after one
retry, ends the run in human_review (agent_failed, invalid_output). Any other exception is a bug: it
propagates, and plan 21's retry policy applies.

Everything is written in the caller's transaction, route first: if fill_route reports the run is already
decided or replaced, nothing else is saved.
"""

import logging
from collections.abc import Mapping, Sequence
from typing import Any

from flag_it.contracts.decide import DecisionRun, Flag
from flag_it.contracts.enums import CheckMethod, FlagResult, FlagSource
from flag_it.contracts.jobs import InvestigateJob, load_job
from flag_it.contracts.rules import RuleSet
from flag_it.db import records
from flag_it.db.connection import Conn
from flag_it.db.rows import StoredAgentVerdict
from flag_it.decide.agent.guardrails import GuardrailResult, apply_guardrails, escalate
from flag_it.decide.agent.llm import LlmClient, LlmUnavailable
from flag_it.decide.agent.loop import InvalidOutput, run_agent
from flag_it.decide.agent.prompt import SYSTEM_PROMPT, build_user_message
from flag_it.decide.agent.tools import ToolBox, ToolLedger

JOB_NAME = "investigate"

log = logging.getLogger(__name__)


def _unclear_code_flags(conn: Conn, rules: RuleSet, run: DecisionRun, check_ids: Sequence[str]) -> tuple[Flag, ...]:
    """Check the job's check IDs. Each is an llm check, or a code check this run flagged as unclear."""
    unclear = {
        f.check_id: f
        for f in records.load_flags(conn, run.decision_id)
        if f.source is FlagSource.CODE and f.result is FlagResult.UNCLEAR
    }
    found: list[Flag] = []
    for check_id in check_ids:
        try:
            _, check = rules.check(check_id)
        except KeyError:
            raise ValueError(f"the job names an unknown check: {check_id}") from None
        if check.method is CheckMethod.LLM:
            continue
        if check_id not in unclear:
            raise ValueError(f"{check_id} is a code check with no unclear flag in run {run.decision_id}")
        found.append(unclear[check_id])
    return tuple(found)


def handle_investigate(conn: Conn, client: LlmClient, rules: RuleSet, payload: Mapping[str, Any]) -> DecisionRun | None:
    """The run with its route filled in, or None when it already had a route or a later run replaced it."""
    job = load_job(InvestigateJob, payload)  # rejects a job from another major contract version
    run = records.load_decision_run(conn, job.decision_id)
    if run.route is not None:
        return None
    if run.snapshot_id != job.snapshot_id:
        raise ValueError(f"job snapshot {job.snapshot_id} is not run {run.decision_id}'s snapshot {run.snapshot_id}")
    snapshot = records.load_snapshot(conn, job.snapshot_id)
    unclear = _unclear_code_flags(conn, rules, run, job.check_ids)
    settings = rules.agent_settings()

    ledger = ToolLedger()
    output = None
    try:
        output = run_agent(
            client,
            system=SYSTEM_PROMPT,
            user_message=build_user_message(snapshot, rules, job.check_ids, unclear),
            toolbox=ToolBox(conn, snapshot, rules, ledger),
            settings=settings,
            check_ids=job.check_ids,
        )
    except LlmUnavailable as error:
        log.error("run %s: the model is unavailable (%s): %s", run.decision_id, client.model_tag, error)
        result = escalate("agent_failed")
    except InvalidOutput as error:
        log.error("run %s: the model's answer is invalid (%s): %s", run.decision_id, client.model_tag, error)
        result = escalate("invalid_output")
    else:
        result = apply_guardrails(
            output, snapshot=snapshot, rules=rules, ledger=ledger, settings=settings, decision_id=run.decision_id
        )
    return _save(conn, run, output, result)


def _save(conn: Conn, run: DecisionRun, output, result: GuardrailResult) -> DecisionRun | None:
    decided = records.fill_route(
        conn,
        run.decision_id,
        route=result.route,
        decided_by=result.decided_by,
        escalation_reasons=result.escalation_reasons,
    )
    if decided is None:
        return None
    for verdict in output.verdicts if output is not None else ():
        records.save_agent_verdict(conn, StoredAgentVerdict.from_verdict(run.decision_id, verdict))
    for flag in result.flags:
        records.save_flag(conn, flag)
    return decided
