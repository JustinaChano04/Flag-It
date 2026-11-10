"""Records produced by the Decide stages. See "Decision run", "Flag", "Evidence", "Agent verdict"."""

from datetime import datetime
from typing import Annotated, Self
from uuid import UUID

from pydantic import Field, model_validator

from flag_it.contracts.common import (
    CheckId,
    EscalationReason,
    InputModel,
    JsonScalar,
    NonEmptyStr,
    RecordModel,
    RuleId,
    UnitInterval,
    check_belongs_to_rule,
)
from flag_it.contracts.enums import (
    AgentResult,
    DecidedBy,
    EvidenceKind,
    FlagResult,
    FlagSource,
    Route,
    RunTrigger,
    Severity,
)


class Citation(RecordModel):
    """One piece of evidence. The guardrails check that `ref` exists."""

    kind: EvidenceKind
    ref: NonEmptyStr
    value: JsonScalar = None
    note: str | None = None


class Flag(RecordModel):
    flag_id: UUID
    decision_id: UUID
    txn_id: UUID
    rule_id: RuleId
    check_id: CheckId
    result: FlagResult
    severity: Severity
    evidence: Annotated[tuple[Citation, ...], Field(min_length=1)]
    score: UnitInterval
    source: FlagSource
    due_at: datetime | None = None  # when a pending check's deadline passes

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if not check_belongs_to_rule(self.rule_id, self.check_id):
            raise ValueError(f"check_id {self.check_id} does not belong to rule {self.rule_id}")
        if self.source is FlagSource.CODE and self.score != 1.0:
            raise ValueError("flags from code checks must score 1.0")
        if (self.result is FlagResult.PENDING) != (self.due_at is not None):
            raise ValueError("due_at is required for pending flags, and only for them")
        return self


class AgentVerdict(InputModel):
    """The agent's answer for one llm check. The LLM's output is forced to AgentOutput."""

    check_id: CheckId
    result: AgentResult
    confidence: UnitInterval
    evidence: tuple[Citation, ...] = ()

    @model_validator(mode="after")
    def _evidence_backs_the_result(self) -> Self:
        if self.result is not AgentResult.PASS and not self.evidence:
            raise ValueError(f"a {self.result} verdict needs at least one citation")
        if self.result is AgentResult.FAIL and not any(
            c.kind is EvidenceKind.POLICY for c in self.evidence
        ):
            raise ValueError("a fail verdict must include a policy citation")
        return self


class AgentOutput(InputModel):
    verdicts: Annotated[tuple[AgentVerdict, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def _one_per_check(self) -> Self:
        ids = [v.check_id for v in self.verdicts]
        if len(ids) != len(set(ids)):
            raise ValueError("each check may appear only once")
        return self


class ScreenerResult(RecordModel):
    probability: UnitInterval
    threshold: UnitInterval  # copied from the model version's metadata
    model_version: NonEmptyStr

    @property
    def sends_to_agent(self) -> bool:
        return self.probability >= self.threshold


# Who may choose which route. Deliberately part of the contract: see decisions.md, 2026-11-07.
ROUTES_BY_DECIDER: dict[DecidedBy, frozenset[Route]] = {
    DecidedBy.RULES: frozenset({Route.FLAG}),
    DecidedBy.SCREENER: frozenset({Route.AUTO_APPROVE}),
    DecidedBy.AGENT: frozenset({Route.AGENT_APPROVE, Route.AGENT_FLAG}),
    DecidedBy.GUARDRAILS: frozenset({Route.HUMAN_REVIEW}),
    DecidedBy.RERUN: frozenset({Route.HUMAN_REVIEW}),
}


class DecisionRun(RecordModel):
    """One pass of the Decide stages over one snapshot. Route is empty while the agent works."""

    decision_id: UUID
    txn_id: UUID
    snapshot_id: UUID
    route: Route | None = None
    decided_by: DecidedBy | None = None
    trigger: RunTrigger
    replaces_decision_id: UUID | None = None
    screener: ScreenerResult | None = None
    escalation_reasons: tuple[EscalationReason, ...] = ()
    rules_version: NonEmptyStr
    created_at: datetime

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if (self.route is None) != (self.decided_by is None):
            raise ValueError("route and decided_by are set together")
        if self.decided_by is not None and self.route not in ROUTES_BY_DECIDER[self.decided_by]:
            raise ValueError(f"{self.decided_by} cannot choose route {self.route}")
        if self.decided_by is DecidedBy.SCREENER:
            if self.screener is None:
                raise ValueError("a screener decision needs the screener result")
            if self.screener.sends_to_agent:
                raise ValueError("the screener auto-approves only when its probability is below its threshold")
        if (self.route is Route.HUMAN_REVIEW) != bool(self.escalation_reasons):
            raise ValueError("escalation_reasons are required for human_review, and only for it")
        if (self.trigger is RunTrigger.INITIAL) != (self.replaces_decision_id is None):
            raise ValueError("replaces_decision_id is empty exactly when trigger is initial")
        if self.decided_by is DecidedBy.RERUN:
            if self.trigger is RunTrigger.INITIAL:
                raise ValueError("a rerun decision cannot come from an initial run")
            if "review_conflict" not in self.escalation_reasons:
                raise ValueError("a rerun decision needs the escalation reason review_conflict")
        return self
