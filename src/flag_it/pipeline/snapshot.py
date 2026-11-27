"""Build and save the snapshot one decision run reads.

A snapshot is per run, never reused: a rerun gets a new one so the old run keeps the input it saw.
The parts (normalized transaction, category, anomaly, receipt) are read from what earlier stages saved.
"""

from datetime import datetime
from uuid import UUID

from flag_it.contracts.snapshot import CombinedExpense, CombinedExpenseSnapshot
from flag_it.db import records
from flag_it.db.connection import Conn


def build_snapshot(
    conn: Conn, txn_id: UUID, *, now: datetime, mcc_version: str, anomaly_version: str, reader_model: str
) -> CombinedExpenseSnapshot:
    """Save and return a new snapshot. Raises records.NotFound when a stage result is missing."""
    payload = CombinedExpense(
        transaction=records.load_normalized_transaction(conn, txn_id),
        receipt=records.latest_receipt(conn, txn_id, reader_model),
        category=records.load_category_result(conn, txn_id, mcc_version),
        anomaly=records.load_anomaly_result(conn, txn_id, anomaly_version),
    )
    snapshot = CombinedExpenseSnapshot.build(payload, created_at=now)
    records.save_snapshot(conn, snapshot)
    return snapshot
