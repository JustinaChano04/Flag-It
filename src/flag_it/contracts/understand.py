"""Results of the Understand stages. See "Receipt extraction", "Category result", "Anomaly result"."""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Self
from uuid import UUID

from pydantic import Field, model_validator

from flag_it.contracts.common import Money, NonEmptyStr, RecordModel, UnitInterval
from flag_it.contracts.enums import AnomalyStatus, CategoryMethod, LineType, MatchStatus


class ReceiptLineItem(RecordModel):
    description: str | None = None
    quantity: Annotated[Decimal, Field(max_digits=12, decimal_places=3)] | None = None
    unit_price: Money | None = None
    amount: Money | None = None
    line_type: LineType = LineType.ITEM


class ReceiptExtraction(RecordModel):
    """What the reader got from one receipt file. Unreadable fields stay empty."""

    receipt_id: UUID
    txn_id: UUID
    reader_model: NonEmptyStr
    match_status: MatchStatus
    merchant: str | None = None
    receipt_date: date | None = None
    subtotal: Money | None = None
    tax: Money | None = None
    tip: Money | None = None
    total: Money | None = None
    line_items: tuple[ReceiptLineItem, ...] = ()


class CategoryResult(RecordModel):
    txn_id: UUID
    model_version: NonEmptyStr
    # A category ID from the rules YAML. The categorizer checks it with RuleSet.has_category (Task 9).
    category: NonEmptyStr
    confidence: UnitInterval
    method: CategoryMethod


class AnomalyResult(RecordModel):
    txn_id: UUID
    model_version: NonEmptyStr
    status: AnomalyStatus
    score: float | None = None
    history_length: Annotated[int, Field(ge=0)]
    as_of: datetime

    @model_validator(mode="after")
    def _score_matches_status(self) -> Self:
        scored = self.status is AnomalyStatus.SCORED
        if scored and self.score is None:
            raise ValueError("score is required when status is scored")
        if not scored and self.score is not None:
            raise ValueError("score must be empty when status is insufficient_history")
        return self
