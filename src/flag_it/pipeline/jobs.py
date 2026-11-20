"""Job names, deterministic job IDs, and the seam every enqueue goes through."""

from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

from flag_it.contracts.enums import RunTrigger

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
