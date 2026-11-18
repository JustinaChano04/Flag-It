"""The risk screener: how likely a transaction that passed the rule checks is to break a rule.

Contracts.md step 6. Below the model's threshold the route is auto_approve, decided by the
screener. Otherwise the pipeline sends the run to the agent. The screener never creates flags:
its score isn't tied to a rule. It runs only on a run with no hard failure, and it never
auto-approves a run whose rule checks need review (plan 14's RuleCheckOutcome.needs_review).

Until there are review outcomes to train on, the stand-in answers 1.0, so every transaction
that passes the rule checks goes to the agent (decided 2026-11-05). A trained screener is any
object with the Screener interface. Its threshold is part of the model version, chosen when it
is trained, never a rules YAML param.

    result = screen(snapshot, STAND_IN)  # the caller always names the screener
    decided = route_after_screening(result, needs_review=outcome.needs_review)
    if decided is None: ...              # queue an investigate job
"""

from dataclasses import dataclass
from typing import Protocol

from flag_it.contracts.decide import ScreenerResult
from flag_it.contracts.enums import DecidedBy, Route
from flag_it.contracts.snapshot import CombinedExpenseSnapshot


class Screener(Protocol):
    @property
    def model_version(self) -> str: ...

    @property
    def threshold(self) -> float: ...

    def probability(self, snapshot: CombinedExpenseSnapshot) -> float:
        """How likely the snapshot's transaction is to break a rule, from 0 to 1."""
        ...


@dataclass(frozen=True)
class StandInScreener:
    """Sends everything to the agent. Any threshold works, since 1.0 is never below one."""

    model_version: str = "stand-in-1"
    threshold: float = 0.5

    def probability(self, snapshot: CombinedExpenseSnapshot) -> float:
        return 1.0


STAND_IN = StandInScreener()


def screen(snapshot: CombinedExpenseSnapshot, screener: Screener) -> ScreenerResult:
    """Score one snapshot. The result is saved on the decision run as `screener`. There is no default
    screener, so a trained model can't be bypassed by a caller that forgot to pass it."""
    return ScreenerResult(
        probability=screener.probability(snapshot),
        threshold=screener.threshold,
        model_version=screener.model_version,
    )


def route_after_screening(result: ScreenerResult, *, needs_review: bool) -> tuple[Route, DecidedBy] | None:
    """(auto_approve, screener) below the threshold; None when the run goes to the agent.
    needs_review (a rule check found suggestive evidence) always sends it to the agent. It has no
    default, so a caller can't forget it and auto-approve a run that needs review."""
    if result.sends_to_agent or needs_review:
        return None
    return Route.AUTO_APPROVE, DecidedBy.SCREENER
