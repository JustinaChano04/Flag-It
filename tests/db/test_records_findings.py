"""Flags, agent verdicts, and review outcomes round-trip through their tables."""

from datetime import timedelta
from uuid import uuid4

import pytest
from psycopg.errors import CheckViolation, ForeignKeyViolation, UniqueViolation

from flag_it.contracts import examples as ex
from flag_it.contracts.decide import AgentVerdict
from flag_it.db.examples import agent_verdict, review_outcome, save_example_decision, save_example_review
from flag_it.db.records import (
    load_agent_verdicts,
    load_flags,
    load_review_outcomes,
    save_agent_verdict,
    save_flag,
    save_review_outcome,
)
from flag_it.db.rows import StoredAgentVerdict

PENDING = {
    "flag_id": uuid4(),
    "rule_id": "OSU-GEN-04",
    "check_id": "OSU-GEN-04a",
    "result": "pending",
    "severity": "documentation",
    "due_at": ex.AS_OF + timedelta(days=30),
    "evidence": [{"kind": "field", "ref": "receipt", "value": None, "note": "missing input: receipt"}],
}


@pytest.fixture
def decided(conn):
    save_example_decision(conn)
    return conn


def test_flags_round_trip_in_check_order(decided):
    fail, pending = ex.flag(), ex.flag(**PENDING)
    save_flag(decided, fail)
    save_flag(decided, pending)
    assert load_flags(decided, ex.DECISION_ID) == (pending, fail)  # OSU-GEN-04a sorts before OSU-LIM-01a


def test_a_check_flags_once_per_run(decided):
    save_flag(decided, ex.flag())
    with pytest.raises(UniqueViolation), decided.transaction():
        save_flag(decided, ex.flag(flag_id=uuid4()))


def test_a_flag_must_belong_to_its_run_transaction(decided):
    with pytest.raises(ForeignKeyViolation), decided.transaction():
        save_flag(decided, ex.flag(txn_id=uuid4()))


@pytest.mark.parametrize(
    ("columns", "why"),
    [
        ("'OSU-GEN-04', 'OSU-GEN-04a', 'pending', NULL", "pending without due_at"),
        ("'OSU-GEN-04', 'OSU-LIM-01a', 'fail', NULL", "check of another rule"),
    ],
)
def test_the_database_rejects_inconsistent_flags(decided, columns, why):
    with pytest.raises(CheckViolation), decided.transaction():
        decided.execute(
            "INSERT INTO flag (flag_id, decision_id, txn_id, rule_id, check_id, result, due_at,"
            " severity, evidence, score, source)"
            f" VALUES (%s, %s, %s, {columns}, 'documentation', '[{{}}]', 1.0, 'code')",
            (uuid4(), ex.DECISION_ID, ex.TXN_ID),
        )


def test_agent_verdicts_round_trip(decided):
    fail = AgentVerdict(
        check_id="OSU-PRH-09a",
        result="fail",
        confidence=0.92,
        evidence=[ex.citation(kind="policy", ref="OSU-PRH-09", value=None), ex.citation()],
    )
    stored = StoredAgentVerdict.from_verdict(ex.DECISION_ID, fail)
    save_agent_verdict(decided, agent_verdict())
    save_agent_verdict(decided, stored)
    assert load_agent_verdicts(decided, ex.DECISION_ID) == (agent_verdict(), stored)


def test_a_check_gets_one_verdict_per_run(decided):
    save_agent_verdict(decided, agent_verdict())
    with pytest.raises(UniqueViolation), decided.transaction():
        save_agent_verdict(decided, agent_verdict(result="pass"))


def test_review_outcomes_round_trip_oldest_first(decided):
    save_flag(decided, ex.flag())
    first = review_outcome()
    second = review_outcome(review_id=uuid4(), final="approve", per_flag=[], created_at=ex.AS_OF + timedelta(hours=1))
    save_review_outcome(decided, second)
    save_review_outcome(decided, first)
    assert load_review_outcomes(decided, ex.DECISION_ID) == (first, second)


def test_every_table_gets_a_row_from_the_full_example(conn):
    save_example_review(conn)
    counts = conn.execute(
        "SELECT (SELECT count(*) FROM flag) AS flags, (SELECT count(*) FROM agent_verdict) AS verdicts,"
        " (SELECT count(*) FROM review_outcome) AS reviews"
    ).fetchone()
    assert counts == {"flags": 1, "verdicts": 1, "reviews": 1}
