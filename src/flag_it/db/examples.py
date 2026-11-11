"""Builders for database-only rows, and helpers that save one valid row per table.

Each save_example_* helper saves everything the previous one does, plus one more stage. They
use the records in flag_it.contracts.examples. For tests and plan 03's fixtures; not pipeline code.
"""

from flag_it.contracts import examples as ex
from flag_it.db import records
from flag_it.db.connection import Conn


def save_example_transaction(conn: Conn) -> None:
    records.save_raw_transaction(conn, ex.raw_from_file())
    records.save_txn(conn, ex.TXN_ID, ex.RAW_ID)
    records.save_normalized_transaction(conn, ex.normalized())
