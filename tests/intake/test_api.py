"""The intake endpoints, through FastAPI's test client, on the test's rolled-back connection."""

import pytest
from fastapi.testclient import TestClient

from flag_it.api import create_app
from flag_it.contracts import examples as ex
from flag_it.contracts.common import CONTRACT_VERSION
from flag_it.db import records
from flag_it.db.examples import save_example_results, save_example_review, snapshot
from flag_it.deps import get_conn
from tests.intake.test_service import item


@pytest.fixture
def client(conn):
    app = create_app()
    app.dependency_overrides[get_conn] = lambda: conn
    return TestClient(app)


def test_submitting_one_returns_202_with_its_result(client):
    response = client.post("/transactions", json=item())
    assert response.status_code == 202
    body = response.json()
    assert body["contract_version"] == CONTRACT_VERSION
    assert (body["item"]["index"], body["item"]["status"]) == (0, "accepted")


def test_submitting_one_invalid_item_still_returns_202(client):
    response = client.post("/transactions", json=item(amount="abc"))
    assert response.status_code == 202
    assert response.json()["item"]["errors"] == [{"field": "amount", "message": "not a number"}]


def test_a_batch_with_bad_items_accepts_the_others(client):
    items = [item(external_id="A-1"), item(external_id="A-2", amount="abc"), {"source": "erp"}, item(external_id="A-1")]
    response = client.post("/transactions/batch", json={"items": items})
    assert response.status_code == 202
    results = [(i["index"], i["status"]) for i in response.json()["items"]]
    assert results == [(0, "accepted"), (1, "invalid"), (2, "invalid"), (3, "duplicate")]


def test_an_empty_batch_is_refused(client):
    assert client.post("/transactions/batch", json={"items": []}).status_code == 422


def test_a_transaction_before_any_decision(client):
    txn_id = client.post("/transactions", json=item()).json()["item"]["txn_id"]
    response = client.get(f"/transactions/{txn_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["transaction"]["merchant_norm"] == "JOES CAFE"
    assert (body["decision"], body["flags"]) == (None, [])


def test_a_transaction_shows_its_decided_run_and_that_run_flags(client, conn):
    save_example_review(conn)
    body = client.get(f"/transactions/{ex.TXN_ID}").json()
    assert body["decision"]["decision_id"] == str(ex.DECISION_ID)
    assert [f["check_id"] for f in body["flags"]] == ["OSU-LIM-01a"]


def test_a_run_still_waiting_for_the_agent_is_not_shown_as_the_decision(client, conn):
    save_example_results(conn)
    records.save_snapshot(conn, snapshot())
    working = {"route": None, "decided_by": None, "screener": {"probability": 1.0, "threshold": 0.5, "model_version": "stand-in-1"}}
    records.save_decision_run(conn, ex.decision_run(**working))
    assert client.get(f"/transactions/{ex.TXN_ID}").json()["decision"] is None


def test_the_decision_history_lists_every_run(client, conn):
    save_example_review(conn)
    body = client.get(f"/transactions/{ex.TXN_ID}/decisions").json()
    assert [d["decision_id"] for d in body["decisions"]] == [str(ex.DECISION_ID)]


@pytest.mark.parametrize("path", ["/transactions/{}", "/transactions/{}/decisions"])
def test_an_unknown_transaction_is_404(client, path):
    assert client.get(path.format("00000000-0000-0000-0000-0000000000ff")).status_code == 404
