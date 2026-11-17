"""Intake's own queries. Saving goes through flag_it.db.records."""

from uuid import UUID

from flag_it.db.connection import Conn


def find_txn_id(conn: Conn, source: str, external_id: str) -> UUID | None:
    """The txn_id already given to (source, external_id), if any."""
    row = conn.execute(
        "SELECT t.txn_id FROM raw_transaction r JOIN txn t ON t.raw_id = r.raw_id"
        " WHERE r.source = %s AND r.external_id = %s",
        (source, external_id),
    ).fetchone()
    return row["txn_id"] if row else None


def txn_exists(conn: Conn, txn_id: UUID) -> bool:
    return conn.execute("SELECT 1 FROM txn WHERE txn_id = %s", (txn_id,)).fetchone() is not None


def file_lines_loaded(conn: Conn, source_file: str) -> set[int]:
    """Line numbers of a file that already have a raw row."""
    rows = conn.execute("SELECT source_line_no FROM raw_transaction WHERE source_file = %s", (source_file,))
    return {row["source_line_no"] for row in rows.fetchall()}
