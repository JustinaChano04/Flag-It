"""The guardrails on the agent's answer (contracts.md step 7).

The run goes to a person (human_review, decided by the guardrails) when a verdict is unsure, a confidence
is below the rules YAML's agent.min_confidence, or a citation points to something that doesn't exist.
(The fourth condition, an answer that fails schema validation after one retry, is the loop's: it never
reaches this module.) Otherwise the route is agent_flag if any verdict is a fail, else agent_approve.

Flags: a fail or unsure verdict on an llm check is a flag (source llm, score = confidence), unless one of
its citations is unresolved. A verdict on a code check, which the agent judges when that check was
unclear, never makes a flag: the check already has one, and flags are unique per run and check.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid5

from flag_it.contracts.decide import AgentOutput, AgentVerdict, Citation, Flag
from flag_it.contracts.enums import AgentResult, CheckMethod, DecidedBy, EvidenceKind, FlagResult, FlagSource, Route
from flag_it.contracts.rules import AgentSettings, RuleSet
from flag_it.contracts.snapshot import CombinedExpenseSnapshot
from flag_it.decide.agent.tools import ToolLedger

_ROOTS = ("transaction", "receipt", "category", "anomaly")
_ROOT = re.compile(r"[a-z_]+")
_STEP = re.compile(r"\.([A-Za-z_][A-Za-z0-9_]*)|\[(\d+)\]")


@dataclass(frozen=True)
class GuardrailResult:
    route: Route
    decided_by: DecidedBy
    escalation_reasons: tuple[str, ...]
    flags: tuple[Flag, ...]


def escalate(reason: str) -> GuardrailResult:
    """Send the run to a person for one reason that has no verdicts behind it (agent_failed, invalid_output)."""
    return GuardrailResult(Route.HUMAN_REVIEW, DecidedBy.GUARDRAILS, (reason,), ())


def _path_exists(payload: Mapping[str, Any], ref: str) -> bool:
    root = _ROOT.match(ref)
    if root is None or root.group() not in _ROOTS:
        return False
    node: Any = payload[root.group()]
    if node is None:
        return False
    pos = root.end()
    while pos < len(ref):
        step = _STEP.match(ref, pos)
        if step is None:
            return False
        name, index = step.groups()
        if name is not None:
            if not isinstance(node, dict) or name not in node:
                return False
            node = node[name]
        else:
            if not isinstance(node, list) or int(index) >= len(node):
                return False
            node = node[int(index)]
        pos = step.end()
    return True


def _policy_exists(ref: str, rules: RuleSet) -> bool:
    if ref.startswith("params."):
        name = ref.removeprefix("params.")
        return any(name in rule.params for rule in rules.rules)
    for lookup in (rules.rule, rules.check):
        try:
            lookup(ref)
            return True
        except KeyError:
            continue
    return False


def unresolved_citation(citation: Citation, payload: Mapping[str, Any], rules: RuleSet, ledger: ToolLedger) -> bool:
    """True when the citation points to something that doesn't exist."""
    match citation.kind:
        case EvidenceKind.FIELD | EvidenceKind.RECEIPT:
            return not _path_exists(payload, citation.ref)
        case EvidenceKind.POLICY:
            return not _policy_exists(citation.ref, rules)
        case EvidenceKind.TOOL_RESULT:
            return not ledger.has(citation.ref)
        case EvidenceKind.HISTORY:
            return not ledger.has_history(citation.ref)
    return True


def _flag(verdict: AgentVerdict, rules: RuleSet, snapshot: CombinedExpenseSnapshot, decision_id: UUID) -> Flag | None:
    rule, check = rules.check(verdict.check_id)
    if check.method is not CheckMethod.LLM or verdict.result is AgentResult.PASS:
        return None
    return Flag(
        flag_id=uuid5(decision_id, check.id),
        decision_id=decision_id,
        txn_id=snapshot.txn_id,
        rule_id=rule.id,
        check_id=check.id,
        result=FlagResult.FAIL if verdict.result is AgentResult.FAIL else FlagResult.UNCLEAR,
        severity=rule.severity,
        evidence=verdict.evidence,
        score=verdict.confidence,
        source=FlagSource.LLM,
    )


def apply_guardrails(
    output: AgentOutput,
    *,
    snapshot: CombinedExpenseSnapshot,
    rules: RuleSet,
    ledger: ToolLedger,
    settings: AgentSettings,
    decision_id: UUID,
) -> GuardrailResult:
    """Every verdict's check ID must be a known check (the loop checks this before calling here)."""
    payload = snapshot.payload.model_dump(mode="json")
    reasons: list[str] = []
    flags: list[Flag] = []
    for verdict in sorted(output.verdicts, key=lambda v: v.check_id):
        unresolved = any(unresolved_citation(c, payload, rules, ledger) for c in verdict.evidence)
        if verdict.result is AgentResult.UNSURE:
            reasons.append(f"unsure:{verdict.check_id}")
        if verdict.confidence < settings.min_confidence:
            reasons.append(f"low_confidence:{verdict.check_id}")
        if unresolved and "citation_unresolved" not in reasons:
            reasons.append("citation_unresolved")
        if not unresolved and (flag := _flag(verdict, rules, snapshot, decision_id)) is not None:
            flags.append(flag)
    if reasons:
        return GuardrailResult(Route.HUMAN_REVIEW, DecidedBy.GUARDRAILS, tuple(reasons), tuple(flags))
    failed = any(v.result is AgentResult.FAIL for v in output.verdicts)
    return GuardrailResult(Route.AGENT_FLAG if failed else Route.AGENT_APPROVE, DecidedBy.AGENT, (), tuple(flags))
