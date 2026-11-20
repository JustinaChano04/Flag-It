"""The understand job: categorize one transaction, score its anomaly, and hand it to decide.

The intake request queues this job before its transaction commits, so the transaction row may not be
visible yet. That is a Retry (like ReceiptNotReady), not a failure. The stage saves are idempotent, so
a repeat returns the same decide job.
"""

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from arq.worker import Retry

from flag_it.contracts.enums import RunTrigger
from flag_it.contracts.jobs import DecideJob, UnderstandJob, load_job
from flag_it.db import records
from flag_it.db.connection import Conn
from flag_it.pipeline.jobs import DECIDE, JobSpec, job_id_decide
from flag_it.understand.anomaly import AnomalyConfig
from flag_it.understand.categorize import MccLookup
from flag_it.understand.stage import understand

NOT_READY_DEFER = 5  # seconds


class TransactionNotReady(Retry):
    """The transaction row isn't visible yet: the intake request hasn't committed."""

    def __init__(self, txn_id: UUID) -> None:
        super().__init__(defer=NOT_READY_DEFER)
        self.txn_id = txn_id


def decide_spec(txn_id: UUID, trigger: RunTrigger, after: UUID | None = None) -> JobSpec:
    return JobSpec(DECIDE, DecideJob(txn_id=txn_id, trigger=trigger).model_dump(mode="json"), job_id_decide(txn_id, trigger, after))


def handle_understand(
    conn: Conn, lookup: MccLookup, config: AnomalyConfig, payload: Mapping[str, Any]
) -> tuple[JobSpec, ...]:
    job = load_job(UnderstandJob, payload)  # rejects a job from another major contract version
    try:
        txn = records.load_normalized_transaction(conn, job.txn_id)
    except records.NotFound:
        raise TransactionNotReady(job.txn_id) from None
    understand(conn, txn, lookup, config)
    return (decide_spec(job.txn_id, RunTrigger.INITIAL),)
