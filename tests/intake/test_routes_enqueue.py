"""Intake queues an understand job for each transaction it accepts, and for nothing else."""

import io

import pytest
from fastapi.testclient import TestClient

from flag_it.api import create_app
from flag_it.contracts.jobs import UnderstandJob
from flag_it.deps import get_conn
from flag_it.intake.load_file import load_rows
from flag_it.pipeline.jobs import UNDERSTAND, job_id_understand
from flag_it.workers.queue import get_job_queue
from tests.intake.test_load_file import BAD, FILE, GOOD, HEADER
from tests.intake.test_service import item
from tests.pipeline.helpers import RecordingQueue


@pytest.fixture
def queue():
    return RecordingQueue()


@pytest.fixture
def client(conn, queue):
    app = create_app()
    app.dependency_overrides[get_conn] = lambda: conn
    app.dependency_overrides[get_job_queue] = lambda: queue
    return TestClient(app)


def test_an_accepted_transaction_enqueues_one_understand_job(client, queue):
    txn_id = client.post("/transactions", json=item()).json()["item"]["txn_id"]
    [spec] = queue.specs
    assert spec.name == UNDERSTAND
    assert UnderstandJob.model_validate(spec.payload).txn_id == __import__("uuid").UUID(txn_id)
    assert spec.job_id == job_id_understand(UnderstandJob.model_validate(spec.payload).txn_id)


def test_a_duplicate_or_invalid_transaction_enqueues_nothing_more(client, queue):
    client.post("/transactions", json=item())
    assert len(queue.specs) == 1
    client.post("/transactions", json=item())  # duplicate
    client.post("/transactions", json=item(external_id="B-1", amount="abc"))  # invalid
    assert len(queue.specs) == 1


def test_a_batch_enqueues_one_job_per_accepted_item(client, queue):
    items = [item(external_id="A-1"), item(external_id="A-2", amount="abc"), item(external_id="A-3"), item(external_id="A-1")]
    response = client.post("/transactions/batch", json={"items": items}).json()
    accepted = [i["txn_id"] for i in response["items"] if i["status"] == "accepted"]
    assert sorted(str(UnderstandJob.model_validate(s.payload).txn_id) for s in queue.specs) == sorted(accepted)
    assert len(queue.specs) == 2


def test_the_loader_reports_the_txn_ids_it_created(conn):
    report = load_rows(conn, FILE, io.StringIO(HEADER + GOOD + BAD))
    assert len(report.txn_ids) == 1  # the row that didn't normalize has no txn_id
    assert load_rows(conn, FILE, io.StringIO(HEADER + GOOD + BAD)).txn_ids == ()  # nothing new on a reload
