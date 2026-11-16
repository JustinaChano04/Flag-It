"""Run every applicable code check on one snapshot and turn the results into flags (contracts.md step 5).

- A check applies when its rule is active and covers the snapshot's category.
- A check that needs an input this deployment doesn't have is skipped: no flag.
- A deployed input this snapshot lacks (no receipt yet) gives not_evaluated, except for a
  document_presence check, whose subject is the missing document: then that is its finding.
- A receipt that doesn't match its charge (match_status mismatch) may not be this charge's
  receipt, so only the cross_reference checks that compare the two judge it.
- Certain evidence is fail; suggestive evidence is unclear, which is never a hard failure but
  means the agent or a person must look (RuleCheckOutcome.needs_review).
- A check with `timing` reports a finding as pending until its deadline passes, then as fail.
- A checker that raises reports not_evaluated and is logged; the other checks still run.
- Gates (role: gate) only decide whether the checks that name them in `when` run. Never flags.
- Flags from code score 1.0, take severity from the rule, and get an ID derived from the run and
  the check, so running the same snapshot for the same run twice gives the same flags.
"""

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from uuid import UUID, uuid5

from flag_it.contracts.decide import Citation, Flag
from flag_it.contracts.enums import CheckMethod, FlagResult, FlagSource, MatchStatus, Severity
from flag_it.contracts.rules import Check, Rule, RuleSet
from flag_it.contracts.snapshot import CombinedExpenseSnapshot
from flag_it.decide.checks.base import (
    CannotTell,
    Checker,
    CheckContext,
    Finding,
    NeedsReview,
    NoFinding,
    Outcome,
    field,
    policy,
    receipt_ref,
)
from flag_it.decide.checks.calendar import BillingCalendar, due_at
from flag_it.decide.checks.deployment import Deployment
from flag_it.decide.checks.registry import CHECKERS, UNSUPPORTED

log = logging.getLogger(__name__)

HARD_SEVERITIES = frozenset({Severity.PROHIBITED, Severity.CONDITIONAL, Severity.DOCUMENTATION})


def is_hard_failure(flag: Flag) -> bool:
    """A failed code check on a rule that isn't guidance. See "Hard failure" in contracts.md."""
    return (
        flag.source is FlagSource.CODE
        and flag.result in (FlagResult.FAIL, FlagResult.VIOLATION)
        and flag.severity in HARD_SEVERITIES
    )


@dataclass(frozen=True)
class RuleCheckOutcome:
    flags: tuple[Flag, ...]
    gates: Mapping[str, bool | None]  # gate check ID -> what it found; None when it couldn't tell
    skipped: tuple[str, ...]  # checks this deployment can't run, in rules-file order

    @property
    def hard_failure(self) -> bool:
        return any(is_hard_failure(flag) for flag in self.flags)

    @property
    def needs_review(self) -> bool:
        """Some check found suggestive evidence: the run must not be auto-approved."""
        return any(flag.result is FlagResult.UNCLEAR for flag in self.flags)


def _missing_receipt() -> Citation:
    return field("receipt", None, "missing input: receipt")


def _gate_allows(check: Check, gates: Mapping[str, bool | None], skipped: set[str]) -> bool | None | str:
    """Whether a dependent check runs: True, False (not applicable), None (can't tell), or 'skipped'."""
    if check.when is None:
        return True
    refs = check.when.referenced()
    if any(ref in skipped for ref in refs):
        return "skipped"
    wanted = check.when.result
    if not isinstance(wanted, bool):
        return None  # a code check can't depend on an llm result
    found = [gates.get(ref, False) for ref in refs]  # a gate that doesn't apply found nothing
    if any(value is wanted for value in found):
        return True
    if any(value is None for value in found):
        return None
    return False


def _evaluate(
    rule: Rule,
    check: Check,
    snapshot: CombinedExpenseSnapshot,
    checkers: Mapping[str, Checker],
    unsupported: Mapping[str, str],
) -> Outcome:
    receipt = snapshot.payload.receipt
    if "receipt" in check.requires and receipt is None:
        if check.pattern == "document_presence":
            return Finding((_missing_receipt(),))
        return CannotTell((_missing_receipt(),))
    if (
        "receipt" in check.requires
        and receipt.match_status is MatchStatus.MISMATCH
        and check.pattern != "cross_reference"
    ):
        return CannotTell((receipt_ref("receipt.match_status", "mismatch", "the receipt may not be this charge's"),))
    if check.id in unsupported:
        return CannotTell((policy(rule.id, None, f"not evaluated: {unsupported[check.id]}"),))
    checker = checkers.get(check.id)
    if checker is None:
        return CannotTell((policy(rule.id, None, "not evaluated: no checker is implemented for this check"),))
    try:
        return checker(CheckContext(snapshot.payload, rule, check))
    except Exception as error:  # one broken checker must not stop the other checks
        log.exception("checker for %s failed on snapshot %s", check.id, snapshot.snapshot_id)
        return CannotTell((policy(rule.id, None, f"not evaluated: checker error ({type(error).__name__})"),))


def _flag(
    rule: Rule,
    check: Check,
    outcome: Outcome,
    snapshot: CombinedExpenseSnapshot,
    decision_id: UUID,
    calendar: BillingCalendar,
) -> Flag | None:
    if isinstance(outcome, NoFinding):
        return None
    evidence, due = outcome.evidence, None
    if isinstance(outcome, CannotTell):
        result = FlagResult.NOT_EVALUATED
    elif isinstance(outcome, NeedsReview):
        result = FlagResult.UNCLEAR
    elif check.timing is None:
        result = FlagResult.FAIL
    else:
        deadline = due_at(check.timing.due, snapshot.payload.transaction, calendar)
        if deadline is None:
            result = FlagResult.NOT_EVALUATED
            post_date = snapshot.payload.transaction.post_date.isoformat()
            evidence += (policy("billing_cycles", post_date, "deadline unknown: no billing cycle covers this post date"),)
        elif snapshot.created_at < deadline:
            result, due = FlagResult.PENDING, deadline
        else:
            result = FlagResult.FAIL
    return Flag(
        flag_id=uuid5(decision_id, check.id),
        decision_id=decision_id,
        txn_id=snapshot.txn_id,
        rule_id=rule.id,
        check_id=check.id,
        result=result,
        severity=rule.severity,
        evidence=evidence,
        score=1.0,
        source=FlagSource.CODE,
        due_at=due,
    )


def run_rule_checks(
    snapshot: CombinedExpenseSnapshot,
    rules: RuleSet,
    *,
    decision_id: UUID,
    deployment: Deployment,
    calendar: BillingCalendar,
    checkers: Mapping[str, Checker] = CHECKERS,
    unsupported: Mapping[str, str] = UNSUPPORTED,
) -> RuleCheckOutcome:
    """Flags for every applicable code check. "Now" is the snapshot's created_at, so a rerun of an
    old snapshot gives the same answer. The caller saves the flags and picks the route."""
    applicable = rules.checks_for(snapshot.payload.category.category, CheckMethod.CODE)
    ordered = sorted(applicable, key=lambda pair: pair[1].role != "gate")  # gates first, file order kept
    gates: dict[str, bool | None] = {}
    skipped: list[str] = []
    flags: list[Flag] = []
    for rule, check in ordered:
        if deployment.missing(check):
            skipped.append(check.id)
            continue
        allowed = _gate_allows(check, gates, set(skipped))
        if allowed == "skipped":
            skipped.append(check.id)
            continue
        if allowed is False:
            continue
        if allowed is None:
            gate_ids = ", ".join(check.when.referenced())
            outcome: Outcome = CannotTell((policy(rule.id, None, f"not evaluated: depends on {gate_ids}, which couldn't tell"),))
        else:
            outcome = _evaluate(rule, check, snapshot, checkers, unsupported)
        if check.role == "gate":
            gates[check.id] = {Finding: True, NoFinding: False}.get(type(outcome))
            continue
        flag = _flag(rule, check, outcome, snapshot, decision_id, calendar)
        if flag is not None:
            flags.append(flag)
    order = {check.id: i for i, (_, check) in enumerate(applicable)}
    return RuleCheckOutcome(
        flags=tuple(sorted(flags, key=lambda f: order[f.check_id])),
        gates=MappingProxyType(gates),
        skipped=tuple(sorted(skipped, key=order.__getitem__)),
    )
