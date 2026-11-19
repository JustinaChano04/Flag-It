"""Recording a review: check it against the run and the rules, then save it.

Reviews are append-only. A run may be reviewed more than once, and the newest review is the
one that counts (a reviewer's mistake is answered by a later review, never an edit). Any run
with a route can be reviewed, not only human_review runs: those outcomes are labels too.

There is no login in v1, so `reviewer` is typed text: it is saved trimmed, with inner whitespace collapsed
and case folded (so "Ana " and "ana" are one reviewer), and a blank name is refused. It is a label, not an
identity. Nothing stops two reviewers from opening the same run; the newest review counts.
"""

import logging
from datetime import datetime
from uuid import UUID, uuid4

from flag_it.contracts.api import ReviewIn
from flag_it.contracts.review import ReviewOutcome
from flag_it.contracts.rules import RuleSet
from flag_it.db import records
from flag_it.db.connection import Conn

log = logging.getLogger(__name__)


class ReviewRefused(Exception):
    """The review can't be recorded. `status` is the HTTP status the API answers with."""

    status = 400


class UnknownRun(ReviewRefused):
    status = 404


class NotDecided(ReviewRefused):
    """The run has no route yet: the agent is still working on it."""

    status = 409


class InvalidReview(ReviewRefused):
    """The review names flags or rules that don't fit. `errors` holds (field, message) pairs."""

    status = 422

    def __init__(self, errors: list[tuple[str, str]]):
        self.errors = tuple(errors)
        super().__init__("; ".join(f"{field}: {message}" for field, message in self.errors))


def normalize_reviewer(name: str) -> str:
    """Trim, collapse inner whitespace, and fold case: "Ana " and "ana" are one reviewer."""
    return " ".join(name.split()).casefold()


def review_errors(review: ReviewIn, flag_ids: set[UUID], rules: RuleSet) -> list[tuple[str, str]]:
    """The name must not be blank; every flag must belong to the run and appear once; every missed rule
    must be an active rule."""
    errors: list[tuple[str, str]] = []
    if not normalize_reviewer(review.reviewer):
        errors.append(("reviewer", "must not be blank"))
    seen: set[UUID] = set()
    for index, answer in enumerate(review.per_flag):
        if answer.flag_id not in flag_ids:
            errors.append((f"per_flag.{index}.flag_id", "not a flag of this run"))
        elif answer.flag_id in seen:
            errors.append((f"per_flag.{index}.flag_id", "this flag is already answered in this review"))
        seen.add(answer.flag_id)
    active = {rule.id for rule in rules.rules if rule.status == "active"}
    for index, rule_id in enumerate(review.missed_rule_ids):
        if rule_id not in active:
            errors.append((f"missed_rule_ids.{index}", f"{rule_id} is not an active rule"))
    return errors


def record_review(conn: Conn, decision_id: UUID, review: ReviewIn, rules: RuleSet, *, now: datetime) -> ReviewOutcome:
    try:
        run = records.load_decision_run(conn, decision_id)
    except records.NotFound:
        raise UnknownRun(f"unknown decision_id {decision_id}") from None
    if run.route is None:
        raise NotDecided(f"run {decision_id} has no route yet; review it once the agent has finished")
    flag_ids = {flag.flag_id for flag in records.load_flags(conn, decision_id)}
    errors = review_errors(review, flag_ids, rules)
    if errors:
        raise InvalidReview(errors)
    fields = review.model_dump() | {"reviewer": normalize_reviewer(review.reviewer)}
    outcome = ReviewOutcome(review_id=uuid4(), decision_id=decision_id, created_at=now, **fields)
    records.save_review_outcome(conn, outcome)
    log.info("review %s of run %s by %r: %s", outcome.review_id, decision_id, outcome.reviewer, review.final.value)
    return outcome
