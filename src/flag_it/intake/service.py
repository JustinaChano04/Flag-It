"""Submitting one transaction: validate it, check for a duplicate, normalize it, save it.

The raw row, its txn row, and its normalized row are saved inside one savepoint, so an item is
either fully stored or not at all, and a failure never aborts the caller's other items.
"""

import logging
from typing import Any
from uuid import uuid4

from psycopg.errors import UniqueViolation
from pydantic import ValidationError

from flag_it.contracts.api import FieldError, IntakeItemResult, TransactionIn
from flag_it.contracts.enums import IntakeStatus
from flag_it.contracts.transactions import RawTransaction
from flag_it.db import records
from flag_it.db.connection import Conn
from flag_it.intake.normalize import NormalizationError, normalize
from flag_it.intake.store import find_txn_id

log = logging.getLogger(__name__)


def _external_id(data: Any) -> str | None:
    value = data.get("external_id") if isinstance(data, dict) else None
    return value if isinstance(value, str) and value else None


def _validation_errors(error: ValidationError) -> list[tuple[str, str]]:
    """(field, message) pairs. A missing field says "required", as in contracts.md, not Pydantic's wording."""
    return [
        (".".join(str(part) for part in e["loc"]) or "item", "required" if e["type"] == "missing" else e["msg"])
        for e in error.errors()
    ]


def submit_item(conn: Conn, data: Any, index: int = 0) -> IntakeItemResult:
    """`data` is one item as the client sent it. `index` is its position in a batch, 0 for one item."""
    external_id = _external_id(data)

    def result(status: IntakeStatus, **fields) -> IntakeItemResult:
        return IntakeItemResult(index=index, external_id=external_id, status=status, **fields)

    def invalid(errors) -> IntakeItemResult:
        log.info("item %d (external_id %r) is invalid: %s", index, external_id, "; ".join(f"{f}: {m}" for f, m in errors))
        return result(IntakeStatus.INVALID, errors=tuple(FieldError(field=f, message=m) for f, m in errors))

    try:
        item = TransactionIn.model_validate(data)
    except ValidationError as error:
        return invalid(_validation_errors(error))

    existing = find_txn_id(conn, item.source, item.external_id)
    if existing is not None:
        return result(IntakeStatus.DUPLICATE, txn_id=existing)

    raw = RawTransaction(raw_id=uuid4(), **item.model_dump())
    txn_id = uuid4()
    try:
        txn = normalize(raw, txn_id)
    except NormalizationError as error:
        return invalid(error.errors)

    try:
        with conn.transaction():
            records.save_raw_transaction(conn, raw)
            records.save_txn(conn, txn_id, raw.raw_id)
            records.save_normalized_transaction(conn, txn)
    except UniqueViolation:
        # A concurrent request stored the same (source, external_id) after our lookup.
        existing = find_txn_id(conn, item.source, item.external_id)
        if existing is None:
            raise
        log.info("item %d (external_id %r) lost a race with a concurrent submit: duplicate", index, external_id)
        return result(IntakeStatus.DUPLICATE, txn_id=existing)
    return result(IntakeStatus.ACCEPTED, txn_id=txn_id)
