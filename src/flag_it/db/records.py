"""Save and load records. One pair of functions per table; the models validate on the way in and out.

- Saves are plain INSERTs. Saving the same key twice raises psycopg.errors.UniqueViolation.
- Every table is append-only (see the migrations). The one allowed change is fill_route.
- The caller owns the transaction: nothing here commits.
"""

from collections.abc import Iterable
from enum import Enum
from typing import Any
from uuid import UUID

from psycopg import sql
from psycopg.types.json import Jsonb
from pydantic import BaseModel

from flag_it.contracts.decide import DecisionRun
from flag_it.contracts.enums import DecidedBy, Route
from flag_it.contracts.snapshot import CombinedExpenseSnapshot
from flag_it.contracts.snapshot import load_snapshot as _validate_snapshot
from flag_it.contracts.transactions import NormalizedTransaction, RawTransaction
from flag_it.contracts.understand import AnomalyResult, CategoryResult, ReceiptExtraction
from flag_it.db.connection import Conn
from flag_it.db.rows import ReceiptFile


class NotFound(LookupError):
    """No row has that key."""


def _row(record: BaseModel, *, json: Iterable[str] = (), exclude: Iterable[str] = ()) -> dict[str, Any]:
    """Column values for a record: `json` fields as jsonb, enums as their values, tuples as arrays."""
    json, exclude = set(json), set(exclude)
    row: dict[str, Any] = {}
    for name, value in record.model_dump(exclude=exclude | json).items():
        if isinstance(value, Enum):
            value = value.value
        elif isinstance(value, tuple):
            value = [v.value if isinstance(v, Enum) else v for v in value]
        row[name] = value
    if json:
        for name, value in record.model_dump(mode="json", include=json).items():
            row[name] = Jsonb(value)
    return row


def _insert(conn: Conn, table: str, row: dict[str, Any]) -> None:
    query = sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
        sql.Identifier(table),
        sql.SQL(", ").join(map(sql.Identifier, row)),
        sql.SQL(", ").join([sql.Placeholder()] * len(row)),
    )
    conn.execute(query, list(row.values()))


def _one(conn: Conn, query: str, *params: Any) -> dict[str, Any]:
    row = conn.execute(query, params).fetchone()
    if row is None:
        raise NotFound(f"no row for {params}")
    return row


# ---------------------------------------------------------------- intake


def save_raw_transaction(conn: Conn, raw: RawTransaction) -> None:
    _insert(conn, "raw_transaction", _row(raw))


def load_raw_transaction(conn: Conn, raw_id: UUID) -> RawTransaction:
    return RawTransaction.model_validate(_one(conn, "SELECT * FROM raw_transaction WHERE raw_id = %s", raw_id))


def save_txn(conn: Conn, txn_id: UUID, raw_id: UUID) -> None:
    """Give a raw row its transaction ID. Intake does this before normalization runs."""
    _insert(conn, "txn", {"txn_id": txn_id, "raw_id": raw_id})


def save_normalized_transaction(conn: Conn, txn: NormalizedTransaction) -> None:
    _insert(conn, "normalized_transaction", _row(txn))


def load_normalized_transaction(
    conn: Conn, txn_id: UUID, normalizer_version: str | None = None
) -> NormalizedTransaction:
    """One normalizer version, or the newest one when no version is given."""
    if normalizer_version is None:
        row = _one(
            conn,
            "SELECT * FROM normalized_transaction WHERE txn_id = %s ORDER BY created_at DESC LIMIT 1",
            txn_id,
        )
    else:
        row = _one(
            conn,
            "SELECT * FROM normalized_transaction WHERE txn_id = %s AND normalizer_version = %s",
            txn_id,
            normalizer_version,
        )
    return NormalizedTransaction.model_validate(row)


# ---------------------------------------------------------------- understand


def save_receipt_file(conn: Conn, file: ReceiptFile) -> None:
    _insert(conn, "receipt_file", _row(file))


def load_receipt_file(conn: Conn, receipt_id: UUID) -> ReceiptFile:
    return ReceiptFile.model_validate(_one(conn, "SELECT * FROM receipt_file WHERE receipt_id = %s", receipt_id))


def save_receipt_extraction(conn: Conn, receipt: ReceiptExtraction) -> None:
    _insert(conn, "receipt_extraction", _row(receipt, json=["line_items"]))


def load_receipt_extraction(conn: Conn, receipt_id: UUID, reader_model: str) -> ReceiptExtraction:
    row = _one(
        conn,
        "SELECT * FROM receipt_extraction WHERE receipt_id = %s AND reader_model = %s",
        receipt_id,
        reader_model,
    )
    return ReceiptExtraction.model_validate(row)


def save_category_result(conn: Conn, result: CategoryResult) -> None:
    _insert(conn, "category_result", _row(result))


def load_category_result(conn: Conn, txn_id: UUID, model_version: str) -> CategoryResult:
    row = _one(conn, "SELECT * FROM category_result WHERE txn_id = %s AND model_version = %s", txn_id, model_version)
    return CategoryResult.model_validate(row)


def save_anomaly_result(conn: Conn, result: AnomalyResult) -> None:
    _insert(conn, "anomaly_result", _row(result))


def load_anomaly_result(conn: Conn, txn_id: UUID, model_version: str) -> AnomalyResult:
    row = _one(conn, "SELECT * FROM anomaly_result WHERE txn_id = %s AND model_version = %s", txn_id, model_version)
    return AnomalyResult.model_validate(row)


# ---------------------------------------------------------------- decide


def save_snapshot(conn: Conn, snapshot: CombinedExpenseSnapshot) -> None:
    _insert(conn, "combined_expense_snapshot", _row(snapshot, json=["payload", "source_versions"]))


def load_snapshot(conn: Conn, snapshot_id: UUID) -> CombinedExpenseSnapshot:
    """Refuses a snapshot written under another major contract version."""
    return _validate_snapshot(_one(conn, "SELECT * FROM combined_expense_snapshot WHERE snapshot_id = %s", snapshot_id))


_SCREENER_COLUMNS = {
    "screener_probability": "probability",
    "screener_threshold": "threshold",
    "screener_model_version": "model_version",
}


def save_decision_run(conn: Conn, run: DecisionRun) -> None:
    row = _row(run, exclude=["screener"])
    for column, field in _SCREENER_COLUMNS.items():
        row[column] = getattr(run.screener, field) if run.screener else None
    _insert(conn, "decision_run", row)


def _decision_run(row: dict[str, Any]) -> DecisionRun:
    screener = {field: row.pop(column) for column, field in _SCREENER_COLUMNS.items()}
    return DecisionRun.model_validate({**row, "screener": screener if screener["model_version"] else None})


def load_decision_run(conn: Conn, decision_id: UUID) -> DecisionRun:
    return _decision_run(_one(conn, "SELECT * FROM decision_run WHERE decision_id = %s", decision_id))


def fill_route(
    conn: Conn,
    decision_id: UUID,
    *,
    route: Route | str,
    decided_by: DecidedBy | str,
    escalation_reasons: Iterable[str] = (),
) -> DecisionRun | None:
    """Record the route of a run the agent was working on: the only change ever made to a saved run.

    Returns the decided run, or None when the run already had a route or a later run has replaced it,
    so a repeated or stale job is a no-op. A replaced run may keep a null route forever.
    The model validates the new route before anything is written.
    """
    current = load_decision_run(conn, decision_id)
    if current.route is not None:
        return None
    decided = DecisionRun.model_validate(
        {
            **current.model_dump(),
            "route": route,
            "decided_by": decided_by,
            "escalation_reasons": tuple(escalation_reasons),
        }
    )
    updated = conn.execute(
        "UPDATE decision_run SET route = %s, decided_by = %s, escalation_reasons = %s"
        " WHERE decision_id = %s AND route IS NULL"
        " AND NOT EXISTS (SELECT 1 FROM decision_run later WHERE later.replaces_decision_id = %s)",
        (decided.route.value, decided.decided_by.value, list(decided.escalation_reasons), decision_id, decision_id),
    )
    return decided if updated.rowcount == 1 else None


def load_current_decision(conn: Conn, txn_id: UUID) -> DecisionRun | None:
    """The run that no later run replaces. Reruns form one chain per transaction, so there is at most one."""
    row = conn.execute(
        "SELECT * FROM decision_run r WHERE r.txn_id = %s"
        " AND NOT EXISTS (SELECT 1 FROM decision_run later WHERE later.replaces_decision_id = r.decision_id)",
        (txn_id,),
    ).fetchone()
    return _decision_run(row) if row else None


def load_decision_history(conn: Conn, txn_id: UUID) -> tuple[DecisionRun, ...]:
    """Every run for a transaction, newest first. Walks the rerun chain from the initial run, so the
    order never depends on `created_at`, which the caller sets and which can tie or run backwards."""
    rows = conn.execute(
        """
        WITH RECURSIVE chain AS (
            SELECT r.*, 0 AS depth FROM decision_run r WHERE r.txn_id = %s AND r.replaces_decision_id IS NULL
            UNION ALL
            SELECT n.*, c.depth + 1 FROM decision_run n JOIN chain c ON n.replaces_decision_id = c.decision_id
        )
        SELECT * FROM chain ORDER BY depth DESC
        """,
        (txn_id,),
    ).fetchall()
    return tuple(_decision_run(row) for row in rows)
