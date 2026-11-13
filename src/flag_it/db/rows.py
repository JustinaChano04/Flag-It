"""Rows that exist only in the database. Contract records are in flag_it.contracts.

These aren't contract records because no stage hands them to another as JSON: each is written
and read through the database only.
"""

from datetime import datetime
from typing import Annotated, Self
from uuid import UUID

from pydantic import Field

from flag_it.contracts.common import CheckId, NonEmptyStr, RecordModel, UnitInterval
from flag_it.contracts.decide import AgentVerdict, Citation
from flag_it.contracts.enums import AgentResult


class ReceiptFile(RecordModel):
    """An uploaded receipt file. The upload endpoint writes it; the read_receipt worker reads it."""

    receipt_id: UUID
    txn_id: UUID
    storage_key: NonEmptyStr  # object key in the receipt store
    content_type: NonEmptyStr
    sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    size_bytes: Annotated[int, Field(gt=0)]
    uploaded_at: datetime


class StoredAgentVerdict(RecordModel):
    """One AgentVerdict as saved for a run. AgentVerdict rejects unknown fields because it comes
    from the LLM; the stored row is a record, so it ignores them like every other record."""

    decision_id: UUID
    check_id: CheckId
    result: AgentResult
    confidence: UnitInterval
    evidence: tuple[Citation, ...] = ()

    @classmethod
    def from_verdict(cls, decision_id: UUID, verdict: AgentVerdict) -> Self:
        return cls(decision_id=decision_id, **verdict.model_dump())
