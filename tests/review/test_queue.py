"""The review queue holds current, unreviewed human_review runs, oldest first."""

from datetime import timedelta
from uuid import uuid4

from flag_it import fixtures
from flag_it.contracts.decide import DecisionRun
from flag_it.contracts.review import ReviewOutcome
from flag_it.db import records
from flag_it.fixtures.seed import seed
from flag_it.review.queue import queue_summaries, review_queue


def names(runs) -> list[str]:
    by_id = {run.decision_id: name for name, run in fixtures.decision_runs().items()}
    return [by_id[run.decision_id] for run in runs]


def test_the_queue_holds_current_unreviewed_human_review_runs_oldest_first(conn):
    seed(conn)
    # guardrails_unsure and lodging_stay_2 are human_review too, but already reviewed.
    # Ties on created_at are broken by decision_id, so the order never changes between calls.
    expected = sorted(
        ["guardrails_low_confidence", "agent_failed"],
        key=lambda n: (fixtures.decision_run(n).created_at, str(fixtures.decision_run(n).decision_id)),
    )
    assert names(review_queue(conn)) == expected


def test_a_reviewed_run_leaves_the_queue(conn):
    seed(conn)
    run = fixtures.decision_run("agent_failed")
    records.save_review_outcome(
        conn,
        ReviewOutcome(review_id=uuid4(), decision_id=run.decision_id, reviewer="Ana", final="approve",
                      created_at=run.created_at + timedelta(days=1)),
    )
    assert "agent_failed" not in names(review_queue(conn))


def test_a_replaced_run_leaves_the_queue(conn):
    seed(conn)
    old = fixtures.decision_run("guardrails_low_confidence")
    snapshot = fixtures.snapshot_for(old).model_copy(update={"snapshot_id": uuid4()})  # one run per snapshot
    records.save_snapshot(conn, snapshot)
    rerun = DecisionRun.model_validate({
        **old.model_dump(), "decision_id": uuid4(), "snapshot_id": snapshot.snapshot_id, "trigger": "late_receipt",
        "replaces_decision_id": old.decision_id, "route": None, "decided_by": None, "escalation_reasons": (),
        "created_at": old.created_at + timedelta(days=1),
    })
    records.save_decision_run(conn, rerun)
    assert "guardrails_low_confidence" not in names(review_queue(conn))


def test_the_queue_is_limited(conn):
    seed(conn)
    assert len(review_queue(conn, limit=1)) == 1


def test_an_empty_database_has_an_empty_queue(conn):
    assert review_queue(conn) == ()


def test_each_summary_comes_from_its_runs_own_snapshot(conn):
    seed(conn)
    runs = review_queue(conn)
    summaries = queue_summaries(conn, runs)
    assert [s.decision_id for s in summaries] == [run.decision_id for run in runs]
    for run, summary in zip(runs, summaries):
        txn = fixtures.snapshot_for(run).payload.transaction
        assert (summary.merchant, summary.amount, summary.transaction_date) == (
            txn.merchant_norm, txn.amount, txn.transaction_date
        )


def test_no_runs_have_no_summaries(conn):
    assert queue_summaries(conn, ()) == ()
