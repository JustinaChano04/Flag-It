"""Rows that exist only in the database. Contract records are in flag_it.contracts.

These aren't contract records because no stage hands them to another as JSON: each is written
and read through the database only.
"""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import Field

from flag_it.contracts.common import NonEmptyStr, RecordModel


class ReceiptFile(RecordModel):
    """An uploaded receipt file. The upload endpoint writes it; the read_receipt worker reads it."""

    receipt_id: UUID
    txn_id: UUID
    storage_key: NonEmptyStr  # object key in the receipt store
    content_type: NonEmptyStr
    sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    size_bytes: Annotated[int, Field(gt=0)]
    uploaded_at: datetime
