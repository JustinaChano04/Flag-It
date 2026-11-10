"""Queue job payloads: IDs only, plus the contract version. See "Queue jobs" in docs/contracts.md.

Idempotency: a worker may receive the same job twice (Arq retries). `receipt_id` identifies a
read_receipt job and `decision_id` an investigate job. Plan 21 makes the handlers no-ops on a repeat.
"""

from collections.abc import Mapping
from typing import Annotated, Any, TypeVar
from uuid import UUID

from pydantic import Field

from flag_it.contracts.common import CONTRACT_VERSION, CheckId, RecordModel, SemVer, require_version


class ReadReceiptJob(RecordModel):
    receipt_id: UUID
    txn_id: UUID
    contract_version: SemVer = CONTRACT_VERSION


class InvestigateJob(RecordModel):
    decision_id: UUID
    snapshot_id: UUID
    check_ids: Annotated[tuple[CheckId, ...], Field(min_length=1)]
    contract_version: SemVer = CONTRACT_VERSION


J = TypeVar("J", ReadReceiptJob, InvestigateJob)


def load_job(model: type[J], data: Mapping[str, Any]) -> J:
    """Validate a job from the queue. Rejects jobs with no stamp or another major version."""
    require_version(data)
    return model.model_validate(data)
