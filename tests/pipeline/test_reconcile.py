import pytest

from flag_it.contracts import examples as ex
from flag_it.contracts.enums import DecidedBy, ReviewFinal, Route
from flag_it.db import records
from flag_it.db.examples import REVIEW_ID, save_example_decision
from flag_it.contracts.review import ReviewOutcome
from flag_it.pipeline.reconcile import prior_final, reconcile

APPROVE, FLAG = ReviewFinal.APPROVE, ReviewFinal.FLAG
AGREES = {
    (Route.AUTO_APPROVE, APPROVE), (Route.AGENT_APPROVE, APPROVE), (Route.FLAG, FLAG), (Route.AGENT_FLAG, FLAG),
}
DECIDER = {
    Route.FLAG: DecidedBy.RULES, Route.AUTO_APPROVE: DecidedBy.SCREENER, Route.AGENT_APPROVE: DecidedBy.AGENT,
    Route.AGENT_FLAG: DecidedBy.AGENT, Route.HUMAN_REVIEW: DecidedBy.GUARDRAILS,
}


@pytest.mark.parametrize("route", list(Route))
@pytest.mark.parametrize("prior", [APPROVE, FLAG, None])
def test_the_full_table(route, prior):
    reasons = ("some_reason",)
    result = reconcile(route, DECIDER[route], reasons, prior)
    if prior is None or route is Route.HUMAN_REVIEW or (route, prior) in AGREES:
        assert result == (route, DECIDER[route], reasons)
    else:
        assert result == (Route.HUMAN_REVIEW, DecidedBy.RERUN, ("review_conflict",))


def _review(**over) -> ReviewOutcome:
    data = {"review_id": REVIEW_ID, "decision_id": ex.DECISION_ID, "reviewer": "pat", "final": "approve", "created_at": ex.AS_OF}
    return ReviewOutcome(**(data | over))


def test_no_review_means_no_prior_final(conn):
    save_example_decision(conn)
    assert prior_final(conn, ex.TXN_ID) is None


def test_the_most_recent_review_counts(conn):
    from datetime import timedelta
    from uuid import UUID

    save_example_decision(conn)
    records.save_review_outcome(conn, _review())
    later = _review(review_id=UUID("00000000-0000-0000-0000-0000000000b1"), final="flag", created_at=ex.AS_OF + timedelta(hours=1))
    records.save_review_outcome(conn, later)
    assert prior_final(conn, ex.TXN_ID) is FLAG
