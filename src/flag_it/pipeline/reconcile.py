"""The review-conflict rule (contracts.md step 9): a rerun may not silently overturn a person.

If a reviewer already made a final call on any run of this transaction and the new run's route
disagrees with it, the new run goes back to human_review with reason review_conflict. An agreeing
route is kept. A human_review route needs no change: a person looks at it anyway.
"""

from uuid import UUID

from flag_it.contracts.enums import DecidedBy, ReviewFinal, Route
from flag_it.db.connection import Conn

_AGREES = {
    ReviewFinal.APPROVE: frozenset({Route.AUTO_APPROVE, Route.AGENT_APPROVE}),
    ReviewFinal.FLAG: frozenset({Route.FLAG, Route.AGENT_FLAG}),
}


def prior_final(conn: Conn, txn_id: UUID) -> ReviewFinal | None:
    """The final call of the most recent review on any run of this transaction."""
    row = conn.execute(
        "SELECT o.final FROM review_outcome o JOIN decision_run r ON r.decision_id = o.decision_id"
        " WHERE r.txn_id = %s ORDER BY o.created_at DESC, o.review_id DESC LIMIT 1",
        (txn_id,),
    ).fetchone()
    return ReviewFinal(row["final"]) if row else None


def reconcile(
    route: Route, decided_by: DecidedBy, reasons: tuple[str, ...], prior: ReviewFinal | None
) -> tuple[Route, DecidedBy, tuple[str, ...]]:
    if prior is None or route is Route.HUMAN_REVIEW or route in _AGREES[prior]:
        return route, decided_by, reasons
    return Route.HUMAN_REVIEW, DecidedBy.RERUN, ("review_conflict",)
