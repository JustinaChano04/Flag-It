"""Raw and normalized transactions. See "Raw transaction" and "Normalized transaction" in docs/contracts.md."""

from datetime import date
from typing import Annotated, Self
from uuid import UUID

from pydantic import Field, model_validator

from flag_it.contracts.common import Money, NonEmptyStr, RecordModel


class RawTransaction(RecordModel):
    """One source row exactly as received. Every source field is text."""

    raw_id: UUID
    # Origin: a file row, or an intake API submission. Exactly one is set.
    source_file: str | None = None
    source_line_no: Annotated[int, Field(ge=1)] | None = None
    source: str | None = None
    external_id: str | None = None

    source_rowid: str | None = None
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
    # Not in the public export. Intake API clients may send them.
    mcc_code: str | None = None
    business_purpose: str | None = None

    @model_validator(mode="after")
    def _exactly_one_origin(self) -> Self:
        # Setting any field of a pair claims that origin, and a claimed origin must be complete.
        file_pair = (self.source_file, self.source_line_no)
        api_pair = (self.source, self.external_id)
        claims_file = any(v is not None for v in file_pair)
        claims_api = any(v is not None for v in api_pair)
        complete = all(v is not None for v in (file_pair if claims_file else api_pair))
        if claims_file == claims_api or not complete:
            raise ValueError(
                "raw transaction needs exactly one origin, complete: "
                "(source_file, source_line_no) or (source, external_id)"
            )
        return self


class NormalizedTransaction(RecordModel):
    """The typed version of a raw row. Raw text stays in the raw row."""

    txn_id: UUID
    raw_id: UUID
    agency_id: NonEmptyStr
    cardholder_id: NonEmptyStr
    merchant_norm: NonEmptyStr
    mcc_description: NonEmptyStr
    mcc_code: Annotated[str, Field(pattern=r"^\d{4}$")] | None = None
    amount: Money
    transaction_date: date
    post_date: date
    business_purpose: str | None = None
    normalizer_version: NonEmptyStr
