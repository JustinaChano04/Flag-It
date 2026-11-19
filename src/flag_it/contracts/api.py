"""Request and response bodies for the intake and review APIs. See "Intake API" and "Review API"."""

from datetime import date
from typing import Annotated, Any, Self
from uuid import UUID

from pydantic import Field, model_validator

from flag_it.contracts.common import CONTRACT_VERSION, InputModel, Money, NonEmptyStr, RecordModel, RuleId, SemVer
from flag_it.contracts.decide import AgentVerdict, DecisionRun, Flag
from flag_it.contracts.enums import IntakeStatus, ReviewFinal, Severity
from flag_it.contracts.review import FlagReview, ReviewOutcome
from flag_it.contracts.snapshot import CombinedExpenseSnapshot
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


class QueueSummary(RecordModel):
    """What a queue row shows about one waiting run, so the screen needs no further requests."""

    decision_id: UUID
    merchant: NonEmptyStr
    amount: Money
    transaction_date: date


class ReviewQueue(RecordModel):
    """GET /reviews/queue. `summaries` describe the items (read from each run's own snapshot); the route sends one per item."""

    contract_version: SemVer = CONTRACT_VERSION
    items: tuple[DecisionRun, ...]
    summaries: tuple[QueueSummary, ...] = ()

    @model_validator(mode="after")
    def _summaries_match_items(self) -> Self:
        listed = {run.decision_id for run in self.items}
        if any(summary.decision_id not in listed for summary in self.summaries):
            raise ValueError("every summary must belong to one of the listed runs")
        return self


class ReviewIn(InputModel):
    """Body of POST /decisions/{decision_id}/review. The server adds the IDs and timestamp."""

    reviewer: NonEmptyStr
    final: ReviewFinal
    per_flag: tuple[FlagReview, ...] = ()
    missed_rule_ids: tuple[RuleId, ...] = ()
    reason: str | None = None


class CitedRule(RecordModel):
    """A rule a flag or an agent verdict cites, as the reviewer reads it."""

    rule_id: RuleId
    title: NonEmptyStr
    text: NonEmptyStr
    severity: Severity
    source_section: NonEmptyStr
    source_page: NonEmptyStr


class ReviewDetail(RecordModel):
    """GET /decisions/{decision_id}: everything a reviewer needs to judge one run.

    `rules` holds every rule the flags and verdicts cite, in rules-file order. `history` is the
    transaction's run chain, newest first, and `reviews` every review of any run in it, oldest
    first, so a rerun that conflicts with an earlier review shows that review.
    """

    contract_version: SemVer = CONTRACT_VERSION
    run: DecisionRun
    snapshot: CombinedExpenseSnapshot
    flags: tuple[Flag, ...]
    agent_verdicts: tuple[AgentVerdict, ...] = ()
    rules: tuple[CitedRule, ...] = ()
    history: tuple[DecisionRun, ...]
    reviews: tuple[ReviewOutcome, ...] = ()

    @model_validator(mode="after")
    def _one_run(self) -> Self:
        run = self.run
        if self.snapshot.snapshot_id != run.snapshot_id:
            raise ValueError("snapshot must be the run's snapshot")
        if any(flag.decision_id != run.decision_id for flag in self.flags):
            raise ValueError("every flag must belong to the run")
        if run.decision_id not in {r.decision_id for r in self.history}:
            raise ValueError("history must include the run")
        return self
