"""The review endpoints, through FastAPI's test client, on the test's rolled-back connection."""

import pytest
from fastapi.testclient import TestClient

from flag_it import fixtures
from flag_it.api import create_app
from flag_it.contracts.common import CONTRACT_VERSION
from flag_it.deps import get_conn
from flag_it.fixtures.seed import put_sample_receipts, seed
from flag_it.understand.receipts.store import LocalStore
from flag_it.understand.receipts.upload import get_store


@pytest.fixture
def store(tmp_path):
    return LocalStore(tmp_path)


@pytest.fixture
def client(conn, store):
    seed(conn)
    app = create_app()
    app.dependency_overrides[get_conn] = lambda: conn
    app.dependency_overrides[get_store] = lambda: store
    return TestClient(app)


def run_id(name: str) -> str:
    return str(fixtures.decision_run(name).decision_id)


def test_the_queue_lists_waiting_runs(client):
    response = client.get("/reviews/queue")
    assert response.status_code == 200
    body = response.json()
    assert body["contract_version"] == CONTRACT_VERSION
    waiting = {run_id("guardrails_low_confidence"), run_id("agent_failed")}
    assert {item["decision_id"] for item in body["items"]} == waiting
    assert {summary["decision_id"] for summary in body["summaries"]} == waiting  # one request fills the screen
    assert all(summary["merchant"] and summary["amount"] for summary in body["summaries"])


def test_the_queue_limit_is_bounded(client):
    assert client.get("/reviews/queue?limit=0").status_code == 422
    assert len(client.get("/reviews/queue?limit=1").json()["items"]) == 1


def test_a_decision_detail(client):
    response = client.get(f"/decisions/{run_id('lodging_stay_2')}")
    assert response.status_code == 200
    body = response.json()
    assert body["run"]["decision_id"] == run_id("lodging_stay_2")
    assert [run["decision_id"] for run in body["history"]] == [run_id("lodging_stay_2"), run_id("lodging_stay_1")]
    assert body["snapshot"]["payload"]["receipt"] is not None


def test_an_unknown_decision_is_404(client):
    response = client.get("/decisions/00000000-0000-0000-0000-00000000dead")
    assert (response.status_code, response.json()["detail"]) == (404, "unknown decision_id")  # not FastAPI's "Not Found"


def test_posting_a_review_returns_the_outcome(client):
    body = {"reviewer": "Ana", "final": "approve", "reason": "Fine."}
    response = client.post(f"/decisions/{run_id('agent_failed')}/review", json=body)
    assert response.status_code == 201
    assert (response.json()["reviewer"], response.json()["decision_id"]) == ("ana", run_id("agent_failed"))  # the name is saved normalized
    assert run_id("agent_failed") not in {i["decision_id"] for i in client.get("/reviews/queue").json()["items"]}


def test_a_review_with_unknown_ids_is_422_with_each_problem(client):
    body = {"reviewer": "Ana", "final": "flag", "missed_rule_ids": ["OSU-XYZ-99"]}
    response = client.post(f"/decisions/{run_id('agent_failed')}/review", json=body)
    assert response.status_code == 422
    assert response.json()["detail"] == [{"loc": ["body", "missed_rule_ids", "0"], "msg": "OSU-XYZ-99 is not an active rule"}]


def test_a_malformed_review_is_422(client):
    response = client.post(f"/decisions/{run_id('agent_failed')}/review", json={"final": "maybe"})
    assert response.status_code == 422


def test_reviewing_a_run_without_a_route_is_409(client):
    response = client.post(f"/decisions/{run_id('agent_working')}/review", json={"reviewer": "Ana", "final": "approve"})
    assert response.status_code == 409


def test_reviewing_an_unknown_run_is_404(client):
    response = client.post("/decisions/00000000-0000-0000-0000-00000000dead/review", json={"reviewer": "Ana", "final": "approve"})
    assert response.status_code == 404 and response.json()["detail"].startswith("unknown decision_id")


def test_the_receipt_file_is_streamed_with_its_type(client, store):
    put_sample_receipts(store)
    file = fixtures.receipt_files()["receipt_matched"]
    response = client.get(f"/receipts/{file.receipt_id}/file")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.content.startswith(b"%PDF-")


def test_a_receipt_file_missing_from_storage_is_404(client):
    file = fixtures.receipt_files()["receipt_matched"]
    response = client.get(f"/receipts/{file.receipt_id}/file")
    assert (response.status_code, response.json()["detail"]) == (404, "the receipt file is missing from storage")


def test_an_unknown_receipt_is_404(client):
    response = client.get("/receipts/00000000-0000-0000-0000-00000000dead/file")
    assert (response.status_code, response.json()["detail"]) == (404, "unknown receipt_id")
