import pytest
from arq.worker import Retry

from flag_it.contracts import examples as ex
from flag_it.contracts.enums import RunTrigger
from flag_it.contracts.jobs import DecideJob, UnderstandJob
from flag_it.contracts.rules import load_rules
from flag_it.db import records
from flag_it.db.examples import save_example_transaction
from flag_it.pipeline.jobs import DECIDE, job_id_decide
from flag_it.pipeline.understand_job import handle_understand
from flag_it.understand.categorize import load_lookup
from tests.understand.test_stage import CONFIG


def _payload(txn_id=ex.TXN_ID):
    return UnderstandJob(txn_id=txn_id).model_dump(mode="json")


def test_a_saved_transaction_gets_both_results_and_one_decide_job(conn):
    save_example_transaction(conn)
    lookup = load_lookup(load_rules())
    (spec,) = handle_understand(conn, lookup, CONFIG, _payload())
    assert records.load_category_result(conn, ex.TXN_ID, lookup.version).category == "meals_refreshments"
    records.load_anomaly_result(conn, ex.TXN_ID, CONFIG.version)
    assert spec.name == DECIDE
    assert spec.job_id == job_id_decide(ex.TXN_ID, RunTrigger.INITIAL, None)
    assert DecideJob.model_validate(spec.payload) == DecideJob(txn_id=ex.TXN_ID, trigger=RunTrigger.INITIAL)


def test_a_repeat_saves_nothing_new_and_returns_the_same_job(conn):
    save_example_transaction(conn)
    lookup = load_lookup(load_rules())
    first = handle_understand(conn, lookup, CONFIG, _payload())
    count = conn.execute("SELECT count(*) AS n FROM category_result").fetchone()["n"]
    assert handle_understand(conn, lookup, CONFIG, _payload()) == first
    assert conn.execute("SELECT count(*) AS n FROM category_result").fetchone()["n"] == count


def test_an_unknown_transaction_is_retried_later(conn):
    lookup = load_lookup(load_rules())
    with pytest.raises(Retry) as caught:
        handle_understand(conn, lookup, CONFIG, _payload())
    assert caught.value.defer_score == 5000


def test_a_job_from_another_major_version_is_rejected(conn):
    lookup = load_lookup(load_rules())
    with pytest.raises(ValueError):
        handle_understand(conn, lookup, CONFIG, {**_payload(), "contract_version": "2.0.0"})
