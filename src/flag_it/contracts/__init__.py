"""Records, API bodies, and queue jobs shared by every stage. See docs/contracts.md."""

from flag_it.contracts.api import (
    BatchRequest,
    BatchResponse,
    DecisionHistory,
    IntakeResponse,
    ReceiptAccepted,
    ReviewDetail,
    ReviewIn,
    ReviewQueue,
    TransactionIn,
    TransactionView,
)
from flag_it.contracts.common import CONTRACT_VERSION, ContractModel, InputModel, RecordModel
from flag_it.contracts.decide import AgentOutput, DecisionRun, Flag
from flag_it.contracts.jobs import DecideJob, InvestigateJob, ReadReceiptJob, UnderstandJob
from flag_it.contracts.review import ReviewOutcome
from flag_it.contracts.snapshot import CombinedExpenseSnapshot
from flag_it.contracts.transactions import NormalizedTransaction, RawTransaction
from flag_it.contracts.understand import AnomalyResult, CategoryResult, ReceiptExtraction

# Top-level models that get a committed JSON Schema file. Nested models appear inside them.
SCHEMA_MODELS: dict[str, type[ContractModel]] = {
    model.__name__: model
    for model in (
        RawTransaction,
        NormalizedTransaction,
        ReceiptExtraction,
        CategoryResult,
        AnomalyResult,
        CombinedExpenseSnapshot,
        DecisionRun,
        Flag,
        AgentOutput,
        ReviewOutcome,
        TransactionIn,
        BatchRequest,
        IntakeResponse,
        BatchResponse,
        ReceiptAccepted,
        TransactionView,
        DecisionHistory,
        ReviewQueue,
        ReviewIn,
        ReviewDetail,
        ReadReceiptJob,
        InvestigateJob,
        UnderstandJob,
        DecideJob,
    )
}

__all__ = ["CONTRACT_VERSION", "ContractModel", "InputModel", "RecordModel", "SCHEMA_MODELS", *SCHEMA_MODELS]
