"""The read_receipt job: read one uploaded receipt, verify it against its transaction, save the result.

Plan 21 registers handle_read_receipt under JOB_NAME and runs it from the queue, and starts a new
decision run after a receipt is read. The handler is safe to run twice: a repeat returns the saved
extraction, so the caller can still start that run after a crash.

The upload queues the job before its transaction commits, so a worker can see the job first.
ReceiptNotReady is Arq's Retry: Arq runs the job again after NOT_READY_DEFER seconds, up to the
worker's max_tries. Any other exception fails the job without a retry (Arq 0.28).
"""

import logging
from collections.abc import Mapping
from typing import Any

from arq.worker import Retry
from psycopg.errors import UniqueViolation

from flag_it.contracts.jobs import ReadReceiptJob, load_job
from flag_it.contracts.understand import ReceiptExtraction
from flag_it.db import records
from flag_it.db.connection import Conn
from flag_it.understand.receipts.matching import MatchConfig, match
from flag_it.understand.receipts.reader import Reading, ReceiptReader, UnreadableFile, to_fields
from flag_it.understand.receipts.store import ReceiptStore

JOB_NAME = "read_receipt"
NOT_READY_DEFER = 5  # seconds

log = logging.getLogger(__name__)


class ReceiptNotReady(Retry):
    """The receipt_file row isn't visible yet: the upload's transaction hasn't committed."""

    def __init__(self, receipt_id) -> None:
        super().__init__(defer=NOT_READY_DEFER)
        self.receipt_id = receipt_id


def handle_read_receipt(
    conn: Conn, store: ReceiptStore, reader: ReceiptReader, config: MatchConfig, payload: Mapping[str, Any]
) -> ReceiptExtraction:
    """Returns the saved extraction. If this reader model already read this receipt, returns that one."""
    job = load_job(ReadReceiptJob, payload)  # rejects a job from another major contract version
    try:
        return records.load_receipt_extraction(conn, job.receipt_id, reader.model_tag)
    except records.NotFound:
        pass
    try:
        file = records.load_receipt_file(conn, job.receipt_id)
    except records.NotFound:
        raise ReceiptNotReady(job.receipt_id) from None
    if file.txn_id != job.txn_id:
        raise ValueError(f"job txn_id {job.txn_id} does not match the receipt's transaction {file.txn_id}")

    txn = records.load_normalized_transaction(conn, job.txn_id)
    try:
        reading = reader.read(store.get(file.storage_key), file.content_type)
    except UnreadableFile as error:  # retrying can't help: save it blank and say why
        log.warning("receipt %s can't be read: %s", job.receipt_id, error)
        reading = Reading()
    fields = to_fields(reading)
    extraction = ReceiptExtraction(
        receipt_id=job.receipt_id,
        txn_id=job.txn_id,
        reader_model=reader.model_tag,
        match_status=match(fields, txn, config),
        **fields,
    )
    try:
        with conn.transaction():  # a savepoint, so a concurrent duplicate doesn't abort the caller
            records.save_receipt_extraction(conn, extraction)
    except UniqueViolation:  # the same job ran twice at once: keep the one already saved
        return records.load_receipt_extraction(conn, job.receipt_id, reader.model_tag)
    return extraction
