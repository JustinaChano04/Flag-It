"""decide_after_receipt: after a receipt is read, queue a late-receipt run if the current run missed it."""

from flag_it.contracts import examples as ex
from flag_it.contracts.enums import RunTrigger
from flag_it.contracts.jobs import DecideJob
from flag_it.db import records
from flag_it.pipeline.jobs import DECIDE, job_id_decide
from flag_it.understand.receipts.worker import decide_after_receipt
from tests.pipeline.helpers import NOW, Controls, context, save_receipt, save_results
from flag_it.pipeline.decide_job import handle_decide


def test_a_transaction_with_a_run_that_lacks_the_receipt_gets_a_late_receipt_job(conn):
    save_results(conn)
    handle_decide(conn, context(p=0.1), DecideJob(txn_id=ex.TXN_ID, trigger=RunTrigger.INITIAL).model_dump(mode="json"), now=NOW)
    run = records.load_current_decision(conn, ex.TXN_ID)
    save_receipt(conn)
    extraction = records.latest_receipt(conn, ex.TXN_ID, ex.receipt().reader_model)
    [spec] = decide_after_receipt(conn, extraction)
    assert spec.name == DECIDE
    assert spec.job_id == job_id_decide(ex.TXN_ID, RunTrigger.LATE_RECEIPT, run.decision_id)
    assert DecideJob.model_validate(spec.payload).trigger is RunTrigger.LATE_RECEIPT


def test_a_transaction_with_no_run_gets_no_job(conn):
    save_results(conn)
    save_receipt(conn)
    extraction = records.latest_receipt(conn, ex.TXN_ID, ex.receipt().reader_model)
    assert decide_after_receipt(conn, extraction) == ()


def test_a_run_that_already_has_the_receipt_gets_no_job(conn):
    save_results(conn)
    save_receipt(conn)
    extraction = records.latest_receipt(conn, ex.TXN_ID, ex.receipt().reader_model)
    handle_decide(conn, context(Controls(), p=0.1), DecideJob(txn_id=ex.TXN_ID, trigger=RunTrigger.INITIAL).model_dump(mode="json"), now=NOW)
    assert decide_after_receipt(conn, extraction) == ()
