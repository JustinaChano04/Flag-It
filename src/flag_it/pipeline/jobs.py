"""Job names, deterministic job IDs, and the seam every enqueue goes through."""

from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

from flag_it.contracts.enums import RunTrigger
from flag_it.contracts.jobs import DecideJob, InvestigateJob, ReadReceiptJob, UnderstandJob

UNDERSTAND = "understand"
DECIDE = "decide"
INVESTIGATE = "investigate"
READ_RECEIPT = "read_receipt"


@dataclass(frozen=True)
class JobSpec:
    name: str
    payload: dict[str, Any]
    job_id: str


class StageQueue(Protocol):
    def enqueue(self, spec: JobSpec) -> None: ...


def job_id_understand(txn_id: UUID) -> str:
    return f"{UNDERSTAND}:{txn_id}"


def job_id_decide(txn_id: UUID, trigger: RunTrigger, after: UUID | None) -> str:
    """`after` is the run this one will replace, so two late receipts are two jobs."""
    return f"{DECIDE}:{txn_id}:{trigger.value}:{after or 'none'}"


def job_id_investigate(decision_id: UUID) -> str:
    return f"{INVESTIGATE}:{decision_id}"


def understand_spec(txn_id: UUID) -> JobSpec:
    return JobSpec(UNDERSTAND, UnderstandJob(txn_id=txn_id).model_dump(mode="json"), job_id_understand(txn_id))


def decide_spec(txn_id: UUID, trigger: RunTrigger, after: UUID | None = None) -> JobSpec:
    payload = DecideJob(txn_id=txn_id, trigger=trigger).model_dump(mode="json")
    return JobSpec(DECIDE, payload, job_id_decide(txn_id, trigger, after))


def investigate_spec(decision_id: UUID, snapshot_id: UUID, check_ids: tuple[str, ...]) -> JobSpec:
    payload = InvestigateJob(decision_id=decision_id, snapshot_id=snapshot_id, check_ids=check_ids)
    return JobSpec(INVESTIGATE, payload.model_dump(mode="json"), job_id_investigate(decision_id))


def read_receipt_spec(receipt_id: UUID, txn_id: UUID) -> JobSpec:
    payload = ReadReceiptJob(receipt_id=receipt_id, txn_id=txn_id).model_dump(mode="json")
    return JobSpec(READ_RECEIPT, payload, f"{READ_RECEIPT}:{receipt_id}")
