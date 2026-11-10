"""What a reviewer records about a decision run. See "Review outcome" in docs/contracts.md."""

from datetime import datetime
from typing import Self
from uuid import UUID

from pydantic import model_validator

from flag_it.contracts.common import NonEmptyStr, RecordModel, RuleId
from flag_it.contracts.enums import ReviewFinal


class FlagReview(RecordModel):
    flag_id: UUID
    agree: bool
    note: str | None = None


class ReviewOutcome(RecordModel):
    review_id: UUID
    decision_id: UUID
    reviewer: NonEmptyStr
    final: ReviewFinal
    per_flag: tuple[FlagReview, ...] = ()
    missed_rule_ids: tuple[RuleId, ...] = ()
    reason: str | None = None
    created_at: datetime

    @model_validator(mode="after")
    def _each_flag_once(self) -> Self:
        ids = [f.flag_id for f in self.per_flag]
        if len(ids) != len(set(ids)):
            raise ValueError("each flag may be reviewed only once")
        return self
