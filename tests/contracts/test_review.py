from uuid import uuid4

import pytest
from pydantic import ValidationError

from flag_it.contracts.review import ReviewOutcome
from flag_it.contracts.examples import AS_OF, DECISION_ID, FLAG_ID


def _outcome(**over) -> ReviewOutcome:
    data = {
        "review_id": uuid4(),
        "decision_id": DECISION_ID,
        "reviewer": "reviewer-7",
        "final": "approve",
        "per_flag": [{"flag_id": FLAG_ID, "agree": False, "note": "Approved in advance"}],
        "missed_rule_ids": ["OSU-TRV-13"],
        "reason": "Prior approval on file",
        "created_at": AS_OF,
    }
    return ReviewOutcome(**(data | over))


def test_review_outcome_is_valid():
    assert _outcome().per_flag[0].agree is False


def test_each_flag_is_reviewed_at_most_once():
    twice = [{"flag_id": FLAG_ID, "agree": True}, {"flag_id": FLAG_ID, "agree": False}]
    with pytest.raises(ValidationError, match="once"):
        _outcome(per_flag=twice)


def test_missed_rule_ids_must_be_rule_ids():
    with pytest.raises(ValidationError):
        _outcome(missed_rule_ids=["OSU-TRV-13a"])
