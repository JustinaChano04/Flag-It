"""seed() saves every fixture, and every saved row reads back equal."""

from flag_it import fixtures
from flag_it.db import records
from flag_it.fixtures.seed import seed


def count(conn, table: str) -> int:
    return conn.execute(f"SELECT count(*) AS n FROM {table}").fetchone()["n"]


def test_seed_saves_every_fixture(conn):
    seed(conn)
    runs = fixtures.decision_runs()
    assert count(conn, "raw_transaction") == len(fixtures.raw_transactions())
    assert count(conn, "receipt_file") == len(fixtures.receipt_files())
    assert count(conn, "combined_expense_snapshot") == len(fixtures.snapshots())
    assert count(conn, "decision_run") == len(runs)
    assert count(conn, "flag") == sum(len(fixtures.flags(n)) for n in runs)
    assert count(conn, "agent_verdict") == sum(len(o.verdicts) for n, o in fixtures.agent_outputs().items() if n in runs)
    assert count(conn, "review_outcome") == len(fixtures.review_outcomes())


def test_saved_rows_read_back_equal(conn):
    seed(conn)
    for snap in fixtures.snapshots().values():
        assert records.load_snapshot(conn, snap.snapshot_id) == snap
    for name, run in fixtures.decision_runs().items():
        assert records.load_decision_run(conn, run.decision_id) == run
        assert records.load_flags(conn, run.decision_id) == tuple(sorted(fixtures.flags(name), key=lambda f: f.check_id))
    for review in fixtures.review_outcomes().values():
        assert review in records.load_review_outcomes(conn, review.decision_id)


def test_the_current_decision_is_the_end_of_each_chain(conn):
    seed(conn)
    for last in ("lodging_stay_2", "missing_document_2", "agent_flagged"):
        run = fixtures.decision_run(last)
        assert records.load_current_decision(conn, run.txn_id) == run


def test_the_waiting_run_can_be_finished(conn):
    seed(conn)
    run = fixtures.decision_run("agent_working")
    decided = records.fill_route(conn, run.decision_id, route="agent_approve", decided_by="agent")
    assert decided is not None and decided.route.value == "agent_approve"
