"""The frozen input to one decision run. See "Combined expense snapshot" in docs/contracts.md."""

from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any, Self
from uuid import UUID, uuid4

from pydantic import model_validator

from flag_it.contracts.common import CONTRACT_VERSION, NonEmptyStr, RecordModel, SemVer, require_version
from flag_it.contracts.transactions import NormalizedTransaction
from flag_it.contracts.understand import AnomalyResult, CategoryResult, ReceiptExtraction


class SourceVersions(RecordModel):
    normalizer: NonEmptyStr
    reader_model: str | None = None
    categorizer: NonEmptyStr
    anomaly: NonEmptyStr


class CombinedExpense(RecordModel):
    """Everything known about one transaction. Parts stay nested so each keeps its version."""

    transaction: NormalizedTransaction
    receipt: ReceiptExtraction | None = None
    category: CategoryResult
    anomaly: AnomalyResult

    @model_validator(mode="after")
    def _one_transaction(self) -> Self:
        txn_id = self.transaction.txn_id
        parts = [self.category, self.anomaly] + ([self.receipt] if self.receipt is not None else [])
        if any(part.txn_id != txn_id for part in parts):
            raise ValueError("every part must belong to the same transaction")
        return self

    def source_versions(self) -> SourceVersions:
        return SourceVersions(
            normalizer=self.transaction.normalizer_version,
            reader_model=self.receipt.reader_model if self.receipt is not None else None,
            categorizer=self.category.model_version,
            anomaly=self.anomaly.model_version,
        )


class CombinedExpenseSnapshot(RecordModel):
    snapshot_id: UUID
    txn_id: UUID
    payload: CombinedExpense
    source_versions: SourceVersions
    contract_version: SemVer = CONTRACT_VERSION
    created_at: datetime

    @model_validator(mode="after")
    def _consistent_with_payload(self) -> Self:
        if self.txn_id != self.payload.transaction.txn_id:
            raise ValueError("txn_id must match payload.transaction.txn_id")
        if self.source_versions != self.payload.source_versions():
            raise ValueError("source_versions must match the versions inside payload")
        return self

    @classmethod
    def build(
        cls,
        payload: CombinedExpense,
        *,
        snapshot_id: UUID | None = None,
        created_at: datetime | None = None,
    ) -> Self:
        return cls(
            snapshot_id=snapshot_id or uuid4(),
            txn_id=payload.transaction.txn_id,
            payload=payload,
            source_versions=payload.source_versions(),
            created_at=created_at or datetime.now(timezone.utc),
        )


def load_snapshot(data: Mapping[str, Any]) -> CombinedExpenseSnapshot:
    """Read a saved snapshot. The stamp must be present and share this code's major version."""
    require_version(data)
    return CombinedExpenseSnapshot.model_validate(data)
