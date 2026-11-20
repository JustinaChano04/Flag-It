"""Each sweep, with a case inside the window and a case outside it.

Transactions, receipts and extractions are stamped by the database's clock, so the cases are built
relative to the real time: "inside" is now, "outside" is now plus ten minutes (past the 5-minute grace).
"""

from datetime import datetime, timedelta, timezone

from flag_it.contracts import examples as ex
from flag_it.contracts.enums import DecidedBy, Route, RunTrigger
from flag_it.contracts.jobs import DecideJob
from flag_it.contracts.rules import PipelineSettings
from flag_it.db import records
from flag_it.decide.checks.calendar import BillingCalendar
from flag_it.pipeline.decide_job import handle_decide
from flag_it.pipeline.jobs import DECIDE, READ_RECEIPT, UNDERSTAND, job_id_decide, job_id_understand
from flag_it.pipeline.sweeps import due_reruns, lost_receipts, stuck_runs, unread_receipts, unrun_transactions
from tests.pipeline.helpers import READER, SIGNOFF, context, save_receipt, save_results

NO_CYCLES = BillingCalendar(cycles=[])  # no deadline is known, so a missing receipt is not a failure
SETTINGS = PipelineSettings(max_tries=5, stuck_after_minutes=30, sweep_grace_minutes=5)
REAL_NOW = lambda: datetime.now(timezone.utc)  # noqa: E731
LATER = lambda: REAL_NOW() + timedelta(minutes=10)  # noqa: E731


def decide(conn, trigger=RunTrigger.INITIAL, now=None, p=0.1, calendar=None):
    payload = DecideJob(txn_id=ex.TXN_ID, trigger=trigger).model_dump(mode="json")
    return handle_decide(conn, context(p=p, calendar=calendar), payload, now=now or REAL_NOW())


def ids(specs):
    return [s.job_id for s in specs]


def test_due_reruns_find_a_pending_check_past_its_deadline(conn):
    save_results(conn)
    decide(conn, now=SIGNOFF - timedelta(days=5))  # pending until SIGNOFF
    run = records.load_current_decision(conn, ex.TXN_ID)
    assert due_reruns(conn, SIGNOFF - timedelta(hours=1), SETTINGS) == ()  # not yet due
    assert due_reruns(conn, SIGNOFF + timedelta(minutes=1), SETTINGS) == ()  # due, but inside the grace
    specs = due_reruns(conn, SIGNOFF + timedelta(minutes=6), SETTINGS)
    assert ids(specs) == [job_id_decide(ex.TXN_ID, RunTrigger.DEADLINE, run.decision_id)]
    assert specs[0].name == DECIDE
    assert ids(due_reruns(conn, SIGNOFF + timedelta(minutes=6), SETTINGS)) == ids(specs)  # twice: same IDs


def test_due_reruns_skip_a_run_that_was_replaced(conn):
    save_results(conn)
    decide(conn, now=SIGNOFF - timedelta(days=5))
    decide(conn, RunTrigger.DEADLINE, now=SIGNOFF + timedelta(hours=1))  # the deadline run replaces it
    assert due_reruns(conn, SIGNOFF + timedelta(days=1), SETTINGS) == ()


def test_unrun_transactions_find_an_old_transaction_with_no_run(conn):
    save_results(conn)
    assert unrun_transactions(conn, REAL_NOW(), SETTINGS) == ()  # inside the grace
    specs = unrun_transactions(conn, LATER(), SETTINGS)
    assert ids(specs) == [job_id_understand(ex.TXN_ID)] and specs[0].name == UNDERSTAND
    assert ids(unrun_transactions(conn, LATER(), SETTINGS)) == ids(specs)
    decide(conn)
    assert unrun_transactions(conn, LATER(), SETTINGS) == ()  # a transaction with a run is skipped


def test_unread_receipts_skip_a_receipt_with_an_extraction(conn):
    save_results(conn)
    from flag_it.db.examples import receipt_file

    records.save_receipt_file(conn, receipt_file(uploaded_at=REAL_NOW() - timedelta(minutes=20)))
    specs = unread_receipts(conn, REAL_NOW(), SETTINGS, READER)
    assert [s.name for s in specs] == [READ_RECEIPT] and ids(specs) == [f"read_receipt:{ex.RECEIPT_ID}"]
    assert unread_receipts(conn, REAL_NOW() - timedelta(hours=1), SETTINGS, READER) == ()  # inside the grace
    assert unread_receipts(conn, REAL_NOW(), SETTINGS, "another-reader") != ()  # per reader model
    records.save_receipt_extraction(conn, ex.receipt())
    assert unread_receipts(conn, REAL_NOW(), SETTINGS, READER) == ()


def test_lost_receipts_find_a_current_run_that_missed_the_latest_extraction(conn):
    save_results(conn)
    decide(conn)
    run = records.load_current_decision(conn, ex.TXN_ID)
    assert lost_receipts(conn, LATER(), SETTINGS, READER) == ()  # no receipt at all
    save_receipt(conn)  # committed after the run's snapshot
    assert lost_receipts(conn, REAL_NOW(), SETTINGS, READER) == ()  # inside the grace
    specs = lost_receipts(conn, LATER(), SETTINGS, READER)
    assert ids(specs) == [job_id_decide(ex.TXN_ID, RunTrigger.LATE_RECEIPT, run.decision_id)]
    assert ids(lost_receipts(conn, LATER(), SETTINGS, READER)) == ids(specs)
    decide(conn, RunTrigger.LATE_RECEIPT)  # the rerun's snapshot has the receipt
    assert lost_receipts(conn, LATER(), SETTINGS, READER) == ()


def test_stuck_runs_end_a_routeless_run_older_than_the_limit(conn):
    save_results(conn)
    decide(conn, now=REAL_NOW() - timedelta(minutes=45), p=1.0, calendar=NO_CYCLES)  # sent to the agent: no route
    assert records.load_current_decision(conn, ex.TXN_ID).route is None
    assert stuck_runs(conn, REAL_NOW() - timedelta(minutes=40), SETTINGS) == ()  # still young
    [ended] = stuck_runs(conn, REAL_NOW(), SETTINGS)
    assert (ended.route, ended.decided_by, ended.escalation_reasons) == (
        Route.HUMAN_REVIEW, DecidedBy.GUARDRAILS, ("agent_failed",))
    assert stuck_runs(conn, REAL_NOW(), SETTINGS) == ()  # twice: nothing more to end


def test_a_fresh_routeless_run_is_left_alone(conn):
    save_results(conn)
    decide(conn, p=1.0, calendar=NO_CYCLES)
    assert stuck_runs(conn, REAL_NOW(), SETTINGS) == ()
    assert records.load_current_decision(conn, ex.TXN_ID).route is None


def test_a_sweep_returns_at_most_the_limit_oldest_first(conn):
    from uuid import uuid4

    save_results(conn)
    for n in range(2):  # two more old transactions: three in all
        raw_id, txn_id = uuid4(), uuid4()
        records.save_raw_transaction(conn, ex.raw_from_file(raw_id=raw_id, source_line_no=100 + n))
        records.save_txn(conn, txn_id, raw_id)
        records.save_normalized_transaction(conn, ex.normalized(txn_id=txn_id, raw_id=raw_id))
    assert len(unrun_transactions(conn, LATER(), SETTINGS)) == 3
    first = unrun_transactions(conn, LATER(), SETTINGS, limit=1)
    assert ids(first) == [job_id_understand(ex.TXN_ID)]  # the oldest row
    assert len(unrun_transactions(conn, LATER(), SETTINGS, limit=2)) == 2
