"""The screener scores a snapshot and either auto-approves it or sends it to the agent."""

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from flag_it import fixtures
from flag_it.contracts.decide import DecisionRun, ScreenerResult
from flag_it.contracts.enums import DecidedBy, Route
from flag_it.decide.screener import STAND_IN, Screener, StandInScreener, route_after_screening, screen

SNAPSHOT = fixtures.snapshot("cat_office_general_supplies")


@dataclass(frozen=True)
class Fixed:
    """A trained screener stand-in for tests: a fixed probability and threshold."""

    answer: float
    threshold: float = 0.2
    model_version: str = "test-model-1"

    def probability(self, snapshot) -> float:
        return self.answer


def test_the_stand_in_sends_everything_to_the_agent():
    result = screen(SNAPSHOT, STAND_IN)
    assert result == ScreenerResult(probability=1.0, threshold=0.5, model_version="stand-in-1")
    assert route_after_screening(result, needs_review=False) is None


def test_below_the_threshold_the_screener_auto_approves():
    result = screen(SNAPSHOT, Fixed(0.04))
    assert route_after_screening(result, needs_review=False) == (Route.AUTO_APPROVE, DecidedBy.SCREENER)


def test_a_run_whose_rule_checks_need_review_is_never_auto_approved():
    assert route_after_screening(screen(SNAPSHOT, Fixed(0.04)), needs_review=True) is None


def test_at_the_threshold_the_run_goes_to_the_agent():
    assert route_after_screening(screen(SNAPSHOT, Fixed(0.2)), needs_review=False) is None


def test_the_result_carries_the_models_own_threshold_and_version():
    result = screen(SNAPSHOT, Fixed(0.5, threshold=0.7, model_version="screener-lgbm-2"))
    assert (result.threshold, result.model_version) == (0.7, "screener-lgbm-2")


def test_a_probability_outside_zero_to_one_is_refused():
    with pytest.raises(ValidationError):
        screen(SNAPSHOT, Fixed(1.5))


def test_an_auto_approval_is_a_valid_decision_run():
    result = screen(SNAPSHOT, Fixed(0.04))
    route, decided_by = route_after_screening(result, needs_review=False)
    DecisionRun(
        decision_id=uuid4(), txn_id=SNAPSHOT.txn_id, snapshot_id=SNAPSHOT.snapshot_id, route=route,
        decided_by=decided_by, trigger="initial", screener=result, rules_version="test",
        created_at=datetime.now(timezone.utc),
    )


def test_both_screeners_have_the_interface():
    screeners: list[Screener] = [STAND_IN, StandInScreener(), Fixed(0.1)]
    assert all(0.0 <= s.probability(SNAPSHOT) <= 1.0 for s in screeners)


def test_the_fixtures_use_the_real_stand_in():
    assert fixtures.decision_run("agent_approved").screener == screen(SNAPSHOT, STAND_IN)
