"""Request and response bodies for the intake and review APIs. See "Intake API" and "Review API"."""

from typing import Annotated, Any, Self
from uuid import UUID

from pydantic import Field, model_validator

from flag_it.contracts.common import CONTRACT_VERSION, InputModel, NonEmptyStr, RecordModel, RuleId, SemVer
from flag_it.contracts.decide import DecisionRun, Flag
from flag_it.contracts.enums import IntakeStatus, ReviewFinal
from flag_it.contracts.review import FlagReview
from flag_it.contracts.transactions import NormalizedTransaction


class TransactionIn(InputModel):
    """One submitted transaction. Fields are text, as in the raw row; normalization types them."""

    source: NonEmptyStr
    external_id: NonEmptyStr
    calendar_year: str | None = None
    calendar_month: str | None = None
    agencynbr: str | None = None
    agencyname: str | None = None
    last_name: str | None = None
    first_initial: str | None = None
    item_descr: str | None = None
    amount: str | None = None
    merchant_name: str | None = None
    transaction_date: str | None = None
    post_date: str | None = None
    mcc_description: str | None = None
    mcc_code: str | None = None
    business_purpose: str | None = None


class BatchRequest(InputModel):
    """Items stay raw JSON objects here. The endpoint validates each one with TransactionIn,
    so one malformed item becomes one `invalid` result instead of failing the whole batch."""

    items: Annotated[tuple[dict[str, Any], ...], Field(min_length=1)]


class FieldError(RecordModel):
    field: NonEmptyStr
    message: NonEmptyStr


class IntakeItemResult(RecordModel):
    index: Annotated[int, Field(ge=0)]  # position in the request; 0 for a single submission
    external_id: str | None = None  # empty only when the item itself had none
    status: IntakeStatus
    txn_id: UUID | None = None
    errors: tuple[FieldError, ...] = ()

    @model_validator(mode="after")
    def _shape_matches_status(self) -> Self:
        if self.status is IntakeStatus.INVALID:
            if not self.errors or self.txn_id is not None:
                raise ValueError("an invalid item has errors and no txn_id")
        else:
            if self.txn_id is None or self.errors:
                raise ValueError("an accepted or duplicate item has a txn_id and no errors")
            if not self.external_id:
                raise ValueError("an accepted or duplicate item has an external_id")
        return self


class IntakeResponse(RecordModel):
    contract_version: SemVer = CONTRACT_VERSION
    item: IntakeItemResult


class BatchResponse(RecordModel):
    contract_version: SemVer = CONTRACT_VERSION
    items: tuple[IntakeItemResult, ...]


class ReceiptAccepted(RecordModel):
    contract_version: SemVer = CONTRACT_VERSION
    receipt_id: UUID
    txn_id: UUID


class TransactionView(RecordModel):
    """GET /transactions/{txn_id}. `decision` is empty until the first run has a route."""

    contract_version: SemVer = CONTRACT_VERSION
    txn_id: UUID
    transaction: NormalizedTransaction | None = None
    decision: DecisionRun | None = None
    flags: tuple[Flag, ...] = ()


class DecisionHistory(RecordModel):
    """GET /transactions/{txn_id}/decisions, newest first."""

    contract_version: SemVer = CONTRACT_VERSION
    txn_id: UUID
    decisions: tuple[DecisionRun, ...]


class ReviewQueue(RecordModel):
    """GET /reviews/queue."""

    contract_version: SemVer = CONTRACT_VERSION
    items: tuple[DecisionRun, ...]


class ReviewIn(InputModel):
    """Body of POST /decisions/{decision_id}/review. The server adds the IDs and timestamp."""

    reviewer: NonEmptyStr
    final: ReviewFinal
    per_flag: tuple[FlagReview, ...] = ()
    missed_rule_ids: tuple[RuleId, ...] = ()
    reason: str | None = None
