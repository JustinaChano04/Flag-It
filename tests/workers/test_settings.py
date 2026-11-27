"""The worker's job functions: names, commit-before-enqueue, the last-try hook, and one chained run."""

import asyncio
import dataclasses
from uuid import uuid4

import psycopg
import pytest
from arq.worker import Retry

from flag_it.contracts import examples as ex
from flag_it.contracts.enums import CheckMethod, DecidedBy, Route
from flag_it.contracts.jobs import InvestigateJob, UnderstandJob
from flag_it.db import records
from flag_it.db.connection import connect
from flag_it.db.examples import save_example_transaction, snapshot, save_example_results
from flag_it.db.migrate import upgrade
from flag_it.decide.checks.calendar import BillingCalendar
from flag_it.pipeline.jobs import DECIDE, INVESTIGATE, READ_RECEIPT, UNDERSTAND
from flag_it.workers import settings as worker
from flag_it.workers.settings import WorkerSettings
from tests.conftest import reset_schema
from tests.decide.agent.fakes import ScriptedClient, submit, verdict
from tests.pipeline.helpers import RULES, RecordingQueue, context
from tests.understand.test_stage import CONFIG
from flag_it.contracts.rules import load_rules
from flag_it.understand.categorize import load_lookup


class Borrowed:
    """Lends the test's rolled-back connection to a job function without closing or committing it."""

    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self.conn

    def __exit__(self, *exc):
        return False


def base_ctx(conn=None, **extra):
    ctx = {
        "queue": RecordingQueue(),
        "rules": RULES,
        "lookup": load_lookup(load_rules()),
        "anomaly_config": CONFIG,
        "max_tries": 3,
    }
    if conn is not None:
        ctx["connect"] = lambda: Borrowed(conn)
    return ctx | extra


def test_the_functions_are_the_job_names_and_the_sweeps_are_named_cron_jobs():
    assert [f.name for f in WorkerSettings.functions] == [UNDERSTAND, DECIDE, INVESTIGATE, READ_RECEIPT]
    names = [job.name for job in WorkerSettings.cron_jobs]
    assert len(names) == len(set(names)) == 5
    assert WorkerSettings.max_tries == RULES.pipeline_settings().max_tries
    assert WorkerSettings.keep_result == 60


@pytest.fixture
def committed_db(migrated):
    """A test that really commits: the schema is rebuilt afterwards, because the append-only triggers
    block TRUNCATE and a committed row would leak into the next test."""
    yield migrated
    reset_schema(migrated)
    upgrade(migrated)


def test_the_wrapper_commits_before_it_enqueues(committed_db):
    txn_id, raw_id = uuid4(), uuid4()
    with connect(committed_db) as setup:
        records.save_raw_transaction(setup, ex.raw_from_file(raw_id=raw_id))
        records.save_txn(setup, txn_id, raw_id)
        records.save_normalized_transaction(setup, ex.normalized(txn_id=txn_id, raw_id=raw_id))
    seen = []

    class CheckingQueue:
        def enqueue(self, spec):
            with psycopg.connect(committed_db) as other:  # a second connection sees only committed rows
                n = other.execute("SELECT count(*) FROM category_result WHERE txn_id = %s", (txn_id,)).fetchone()[0]
            seen.append((spec.name, n))

    ctx = base_ctx(connect=lambda: connect(committed_db), queue=CheckingQueue())
    asyncio.run(worker.understand_job(ctx, UnderstandJob(txn_id=txn_id).model_dump(mode="json")))
    assert seen == [(DECIDE, 1)]


def _waiting_run(conn):
    save_example_results(conn)
    records.save_snapshot(conn, snapshot())
    run = ex.decision_run(route=None, decided_by=None)
    records.save_decision_run(conn, run)
    return run


def _investigate_payload(run):
    check_ids = tuple(c.id for _, c in RULES.checks_for("meals_refreshments", CheckMethod.LLM))
    return InvestigateJob(decision_id=run.decision_id, snapshot_id=run.snapshot_id, check_ids=check_ids).model_dump(mode="json")


def test_an_early_failure_of_investigate_is_retried(conn):
    run = _waiting_run(conn)
    ctx = base_ctx(conn, llm=ScriptedClient(RuntimeError("bug")), job_try=1)
    with pytest.raises(Retry):
        asyncio.run(worker.investigate_job(ctx, _investigate_payload(run)))
    assert records.load_decision_run(conn, run.decision_id).route is None


def test_a_failure_on_the_last_try_ends_the_run_in_human_review(conn):
    run = _waiting_run(conn)
    ctx = base_ctx(conn, llm=ScriptedClient(RuntimeError("bug")), job_try=3)
    asyncio.run(worker.investigate_job(ctx, _investigate_payload(run)))  # returns: nothing to retry
    ended = records.load_decision_run(conn, run.decision_id)
    assert (ended.route, ended.decided_by, ended.escalation_reasons) == (
        Route.HUMAN_REVIEW, DecidedBy.GUARDRAILS, ("agent_failed",))


def test_one_transaction_is_driven_from_understand_to_a_route(conn):
    save_example_transaction(conn)
    queue = RecordingQueue()
    llm_ids = [c.id for _, c in RULES.checks_for("meals_refreshments", CheckMethod.LLM)]
    ctx = base_ctx(
        conn,
        queue=queue,
        decide_context=context(p=1.0, calendar=BillingCalendar(cycles=[])),
        llm=ScriptedClient(submit(*(verdict(c, "pass", 0.9) for c in llm_ids))),
    )
    ctx["decide_context"] = dataclasses.replace(
        ctx["decide_context"], mcc_version=ctx["lookup"].version, anomaly_version=CONFIG.version
    )
    functions = {f.name: f.coroutine for f in WorkerSettings.functions}
    asyncio.run(functions[UNDERSTAND](ctx, UnderstandJob(txn_id=ex.TXN_ID).model_dump(mode="json")))
    for _ in range(3):  # understand -> decide -> investigate
        for spec in list(queue.specs):
            queue.specs.remove(spec)
            asyncio.run(functions[spec.name](ctx, spec.payload))
    run = records.load_current_decision(conn, ex.TXN_ID)
    assert (run.route, run.decided_by) == (Route.AGENT_APPROVE, DecidedBy.AGENT)


def test_startup_and_the_redis_settings_share_one_default(monkeypatch):
    from flag_it.workers.queue import DEFAULT_REDIS_URL

    monkeypatch.delenv("FLAG_IT_REDIS_URL", raising=False)
    ctx = {}
    asyncio.run(worker.startup(ctx))  # used to raise KeyError
    assert ctx["queue"].redis_url == DEFAULT_REDIS_URL
    assert WorkerSettings.redis_settings.host == "localhost" and WorkerSettings.redis_settings.port == 6379
