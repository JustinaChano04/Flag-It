"""Snapshots and decision runs: round trips, the fill-route-once rule, and the rerun chain."""

from datetime import timedelta
from uuid import uuid4

import pytest
from psycopg.errors import CheckViolation, ForeignKeyViolation, RestrictViolation, UniqueViolation
from pydantic import ValidationError

from flag_it.contracts import examples as ex
from flag_it.contracts.common import IncompatibleContractVersion
from flag_it.contracts.decide import DecisionRun
from flag_it.contracts.enums import Route
from flag_it.contracts.snapshot import CombinedExpenseSnapshot
from flag_it.db.examples import save_example_results, snapshot
from flag_it.db.records import (
    fill_route,
    load_current_decision,
    load_decision_history,
    load_decision_run,
    load_snapshot,
    save_decision_run,
    save_snapshot,
)

AGENT_WORKING = {
    "route": None,
    "decided_by": None,
    "screener": {"probability": 1.0, "threshold": 0.5, "model_version": "stand-in-1"},
}


def new_run(conn, **over) -> DecisionRun:
    """Save a new snapshot of the example transaction, and a run over it."""
    snap = CombinedExpenseSnapshot.build(ex.combined(), created_at=ex.AS_OF)
    save_snapshot(conn, snap)
    run = ex.decision_run(decision_id=uuid4(), snapshot_id=snap.snapshot_id, **over)
    save_decision_run(conn, run)
    return run


@pytest.fixture
def results(conn):
    save_example_results(conn)
    return conn


def test_a_snapshot_round_trips(results):
    save_snapshot(results, snapshot())
    assert load_snapshot(results, ex.SNAPSHOT_ID) == snapshot()


def test_a_snapshot_from_another_major_version_is_refused(results):
    save_snapshot(results, snapshot(contract_version="2.0.0"))
    with pytest.raises(IncompatibleContractVersion):
        load_snapshot(results, ex.SNAPSHOT_ID)


def test_the_database_rejects_a_snapshot_whose_payload_names_another_transaction(results):
    with pytest.raises(CheckViolation), results.transaction():
        results.execute(
            "INSERT INTO combined_expense_snapshot"
            " (snapshot_id, txn_id, payload, source_versions, contract_version, created_at)"
            """ VALUES (%s, %s, '{"transaction": {"txn_id": "x"}}', '{}', '1.0.0', now())""",
            (uuid4(), ex.TXN_ID),
        )


@pytest.mark.parametrize(
    "over",
    [
        {},
        AGENT_WORKING,
        {
            "route": "auto_approve",
            "decided_by": "screener",
            "screener": {"probability": 0.04, "threshold": 0.2, "model_version": "screener-lgbm-1"},
        },
        {"route": "human_review", "decided_by": "guardrails", "escalation_reasons": ["unsure:OSU-GEN-06a"]},
    ],
    ids=["flag", "agent-working", "auto-approve", "human-review"],
)
def test_a_decision_run_round_trips(results, over):
    run = new_run(results, **over)
    assert load_decision_run(results, run.decision_id) == run


def test_fill_route_sets_the_route_once(results):
    run = new_run(results, **AGENT_WORKING)
    decided = fill_route(results, run.decision_id, route="agent_flag", decided_by="agent")
    assert decided is not None and decided.route is Route.AGENT_FLAG
    assert load_decision_run(results, run.decision_id) == decided
    # A repeated investigate job is a no-op.
    assert fill_route(results, run.decision_id, route="agent_approve", decided_by="agent") is None
    assert load_decision_run(results, run.decision_id).route is Route.AGENT_FLAG


def test_fill_route_can_send_the_run_to_a_person(results):
    run = new_run(results, **AGENT_WORKING)
    decided = fill_route(
        results, run.decision_id, route="human_review", decided_by="guardrails", escalation_reasons=["agent_failed"]
    )
    assert load_decision_run(results, run.decision_id) == decided
    assert decided.escalation_reasons == ("agent_failed",)


def test_fill_route_validates_before_writing(results):
    run = new_run(results, **AGENT_WORKING)
    with pytest.raises(ValidationError, match="cannot choose route"):
        fill_route(results, run.decision_id, route="flag", decided_by="agent")
    assert load_decision_run(results, run.decision_id).route is None


def test_fill_route_skips_a_run_that_a_rerun_has_replaced(results):
    run = new_run(results, **AGENT_WORKING)
    new_run(results, trigger="late_receipt", replaces_decision_id=run.decision_id)
    # The late receipt started a rerun while the agent was working. The old job must not decide the old run.
    assert fill_route(results, run.decision_id, route="agent_approve", decided_by="agent") is None
    assert load_decision_run(results, run.decision_id).route is None


def test_a_decided_run_cannot_be_changed(results):
    run = new_run(results)
    with pytest.raises(RestrictViolation, match="already set"), results.transaction():
        results.execute("UPDATE decision_run SET route = 'auto_approve' WHERE decision_id = %s", (run.decision_id,))


def test_only_the_route_fields_of_a_working_run_can_be_filled(results):
    run = new_run(results, **AGENT_WORKING)
    with pytest.raises(RestrictViolation, match="may only fill in"), results.transaction():
        results.execute("UPDATE decision_run SET rules_version = 'x' WHERE decision_id = %s", (run.decision_id,))
    # Filling the route while also changing another column is refused too.
    with pytest.raises(RestrictViolation, match="may only fill in"), results.transaction():
        results.execute(
            "UPDATE decision_run SET route = 'agent_flag', decided_by = 'agent', rules_version = 'x'"
            " WHERE decision_id = %s",
            (run.decision_id,),
        )
    # Changing exactly the fillable columns is allowed.
    results.execute(
        "UPDATE decision_run SET route = 'agent_flag', decided_by = 'agent' WHERE decision_id = %s",
        (run.decision_id,),
    )
    assert load_decision_run(results, run.decision_id).route is Route.AGENT_FLAG


def test_a_run_cannot_be_deleted(results):
    run = new_run(results)
    with pytest.raises(RestrictViolation, match="append-only"), results.transaction():
        results.execute("DELETE FROM decision_run WHERE decision_id = %s", (run.decision_id,))


def test_reruns_form_one_chain_and_the_last_is_current(results):
    first = new_run(results, route="agent_approve", decided_by="agent")
    second = new_run(
        results,
        trigger="late_receipt",
        replaces_decision_id=first.decision_id,
        created_at=ex.AS_OF + timedelta(days=2),
    )
    third = new_run(
        results,
        trigger="deadline",
        replaces_decision_id=second.decision_id,
        created_at=ex.AS_OF + timedelta(days=30),
    )
    assert load_current_decision(results, ex.TXN_ID) == third
    assert load_decision_history(results, ex.TXN_ID) == (third, second, first)


def test_history_follows_the_chain_not_the_clock(results):
    # Equal and backwards timestamps, as can happen when reruns start in the same instant.
    first = new_run(results, route="agent_approve", decided_by="agent", created_at=ex.AS_OF)
    second = new_run(results, trigger="late_receipt", replaces_decision_id=first.decision_id, created_at=ex.AS_OF)
    third = new_run(
        results,
        trigger="deadline",
        replaces_decision_id=second.decision_id,
        created_at=ex.AS_OF - timedelta(days=1),
    )
    assert load_decision_history(results, ex.TXN_ID) == (third, second, first)
    assert load_current_decision(results, ex.TXN_ID) == third


def test_no_decision_yet(results):
    assert load_current_decision(results, ex.TXN_ID) is None
    assert load_decision_history(results, ex.TXN_ID) == ()


def test_a_run_can_be_replaced_only_once(results):
    first = new_run(results)
    new_run(results, trigger="late_receipt", replaces_decision_id=first.decision_id)
    with pytest.raises(UniqueViolation), results.transaction():
        new_run(results, trigger="deadline", replaces_decision_id=first.decision_id)


def test_a_transaction_has_one_initial_run(results):
    new_run(results)
    with pytest.raises(UniqueViolation), results.transaction():
        new_run(results)


def test_a_snapshot_feeds_one_run(results):
    run = new_run(results)
    rerun = ex.decision_run(
        decision_id=uuid4(),
        snapshot_id=run.snapshot_id,
        trigger="deadline",
        replaces_decision_id=run.decision_id,
    )
    with pytest.raises(UniqueViolation), results.transaction():
        save_decision_run(results, rerun)


def test_a_rerun_must_replace_a_run_of_the_same_transaction(results):
    with pytest.raises(ForeignKeyViolation), results.transaction():
        new_run(results, trigger="late_receipt", replaces_decision_id=uuid4())
    # The key covers the transaction too, so a run of another transaction can't be replaced.
    definition = results.execute(
        "SELECT pg_get_constraintdef(oid) AS definition FROM pg_constraint WHERE conname = 'decision_run_replaces'"
    ).fetchone()["definition"]
    assert "(replaces_decision_id, txn_id)" in definition and "(decision_id, txn_id)" in definition
