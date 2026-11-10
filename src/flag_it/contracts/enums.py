"""Every fixed set of values in the contract. Values match docs/contracts.md exactly."""

from enum import StrEnum


class Route(StrEnum):
    FLAG = "flag"
    AUTO_APPROVE = "auto_approve"
    AGENT_APPROVE = "agent_approve"
    AGENT_FLAG = "agent_flag"
    HUMAN_REVIEW = "human_review"


class DecidedBy(StrEnum):
    RULES = "rules"
    SCREENER = "screener"
    AGENT = "agent"
    GUARDRAILS = "guardrails"
    RERUN = "rerun"  # the run disagreed with an earlier review


class RunTrigger(StrEnum):
    INITIAL = "initial"
    LATE_RECEIPT = "late_receipt"
    DEADLINE = "deadline"


class Severity(StrEnum):
    PROHIBITED = "prohibited"
    CONDITIONAL = "conditional"
    DOCUMENTATION = "documentation"
    GUIDANCE = "guidance"


class CheckMethod(StrEnum):
    CODE = "code"
    LLM = "llm"


class FlagSource(StrEnum):
    CODE = "code"  # a rule check
    LLM = "llm"  # the agent. The screener never creates flags.


class FlagResult(StrEnum):
    FAIL = "fail"
    VIOLATION = "violation"
    UNCLEAR = "unclear"
    PENDING = "pending"
    NOT_EVALUATED = "not_evaluated"


class MatchStatus(StrEnum):
    MATCHED = "matched"
    MISMATCH = "mismatch"
    UNMATCHED = "unmatched"


class AnomalyStatus(StrEnum):
    SCORED = "scored"
    INSUFFICIENT_HISTORY = "insufficient_history"


class CategoryMethod(StrEnum):
    LOOKUP = "lookup"
    MODEL = "model"


class EvidenceKind(StrEnum):
    FIELD = "field"
    RECEIPT = "receipt"
    POLICY = "policy"
    TOOL_RESULT = "tool_result"
    HISTORY = "history"


class AgentResult(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    UNSURE = "unsure"


class ReviewFinal(StrEnum):
    APPROVE = "approve"
    FLAG = "flag"


class IntakeStatus(StrEnum):
    ACCEPTED = "accepted"
    DUPLICATE = "duplicate"
    INVALID = "invalid"


class LineType(StrEnum):
    ITEM = "item"
    TAX = "tax"
    TIP = "tip"
    FEE = "fee"
    ROOM = "room"
    OTHER = "other"
