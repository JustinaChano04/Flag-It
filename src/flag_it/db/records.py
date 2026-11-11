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

from flag_it.contracts.transactions import NormalizedTransaction, RawTransaction
from flag_it.db.connection import Conn


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
