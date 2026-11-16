"""POST /transactions/{txn_id}/receipt stores the file, records it, and queues one read_receipt job."""

import hashlib
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from flag_it.api import create_app
from flag_it.contracts.examples import TXN_ID
from flag_it.db import records
from flag_it.db.examples import save_example_transaction
from flag_it.deps import get_conn
from flag_it.understand.receipts import upload
from flag_it.understand.receipts.store import LocalStore


class RecordingQueue:
    def __init__(self):
        self.jobs = []

    def enqueue_read_receipt(self, job):
        self.jobs.append(job)


@pytest.fixture
def setup(conn, tmp_path):
    save_example_transaction(conn)
    store, queue = LocalStore(tmp_path), RecordingQueue()
    app = create_app()
    app.dependency_overrides[get_conn] = lambda: conn
    app.dependency_overrides[upload.get_store] = lambda: store
    app.dependency_overrides[upload.get_queue] = lambda: queue
    return TestClient(app), conn, store, queue


def post(client, txn_id=TXN_ID, content=b"%PDF-1.7 receipt", content_type="application/pdf"):
    return client.post(f"/transactions/{txn_id}/receipt", files={"file": ("receipt.pdf", content, content_type)})


def test_an_upload_is_stored_recorded_and_queued(setup):
    client, conn, store, queue = setup
    response = post(client)
    assert response.status_code == 202
    receipt_id = UUID(response.json()["receipt_id"])
    file = records.load_receipt_file(conn, receipt_id)
    assert file.storage_key == f"receipts/{TXN_ID}/{receipt_id}.pdf"
    assert (file.sha256, file.size_bytes) == (hashlib.sha256(b"%PDF-1.7 receipt").hexdigest(), 16)
    assert store.get(file.storage_key) == b"%PDF-1.7 receipt"
    assert [(j.receipt_id, j.txn_id) for j in queue.jobs] == [(receipt_id, TXN_ID)]


def test_a_second_upload_is_a_new_receipt(setup):
    client, _, _, queue = setup
    first, second = post(client).json(), post(client).json()
    assert first["receipt_id"] != second["receipt_id"] and len(queue.jobs) == 2


def test_an_unknown_transaction_is_404(setup):
    client, _, _, queue = setup
    assert post(client, txn_id="00000000-0000-0000-0000-0000000000ff").status_code == 404
    assert queue.jobs == []


@pytest.mark.parametrize(
    ("content", "content_type", "code"),
    [
        (b"hi", "text/plain", 415),
        (b"", "application/pdf", 422),
        (b"hello, not a pdf", "application/pdf", 415),  # the declared type is only the client's word
        (b"%PDF-1.7 receipt", "image/png", 415),
    ],
)
def test_a_bad_file_is_refused(setup, content, content_type, code):
    client, _, _, queue = setup
    assert post(client, content=content, content_type=content_type).status_code == code
    assert queue.jobs == []


def test_a_file_over_the_limit_is_refused(setup, monkeypatch):
    client, _, _, queue = setup
    monkeypatch.setattr(upload, "MAX_BYTES", 8)
    assert post(client, content=b"123456789").status_code == 413
    assert queue.jobs == []
