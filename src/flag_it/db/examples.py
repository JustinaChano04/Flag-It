"""Builders for database-only rows, and helpers that save one valid row per table.

Each save_example_* helper saves everything the previous one does, plus one more stage. They
use the records in flag_it.contracts.examples. For tests and plan 03's fixtures; not pipeline code.
"""

from flag_it.contracts import examples as ex
from flag_it.contracts.snapshot import CombinedExpenseSnapshot
from flag_it.db import records
from flag_it.db.connection import Conn
from flag_it.db.rows import ReceiptFile


def save_example_transaction(conn: Conn) -> None:
    records.save_raw_transaction(conn, ex.raw_from_file())
    records.save_txn(conn, ex.TXN_ID, ex.RAW_ID)
    records.save_normalized_transaction(conn, ex.normalized())


def receipt_file(**over) -> ReceiptFile:
    data = {
        "receipt_id": ex.RECEIPT_ID,
        "txn_id": ex.TXN_ID,
        "storage_key": f"receipts/{ex.RECEIPT_ID}.pdf",
        "content_type": "application/pdf",
        "sha256": "0" * 64,
        "size_bytes": 2048,
        "uploaded_at": ex.AS_OF,
    }
    return ReceiptFile(**(data | over))


def save_example_results(conn: Conn) -> None:
    save_example_transaction(conn)
    records.save_receipt_file(conn, receipt_file())
    records.save_receipt_extraction(conn, ex.receipt())
    records.save_category_result(conn, ex.category())
    records.save_anomaly_result(conn, ex.anomaly())


def snapshot(**over) -> CombinedExpenseSnapshot:
    """The example transaction with its receipt, as the snapshot SNAPSHOT_ID."""
    snap = CombinedExpenseSnapshot.build(ex.combined(receipt=ex.receipt()), snapshot_id=ex.SNAPSHOT_ID, created_at=ex.AS_OF)
    return snap.model_copy(update=over) if over else snap


def save_example_decision(conn: Conn) -> None:
    save_example_results(conn)
    records.save_snapshot(conn, snapshot())
    records.save_decision_run(conn, ex.decision_run())
