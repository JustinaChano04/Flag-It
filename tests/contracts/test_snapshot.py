from uuid import uuid4

import pytest
from pydantic import ValidationError

from flag_it.contracts.common import CONTRACT_VERSION, IncompatibleContractVersion
from flag_it.contracts.snapshot import CombinedExpenseSnapshot, load_snapshot
from flag_it.contracts.examples import AS_OF, SNAPSHOT_ID, TXN_ID, anomaly, category, combined, receipt


def test_build_fills_ids_versions_and_stamp():
    snap = CombinedExpenseSnapshot.build(combined(receipt=receipt()), snapshot_id=SNAPSHOT_ID, created_at=AS_OF)
    assert snap.txn_id == TXN_ID
    assert snap.contract_version == CONTRACT_VERSION
    assert snap.source_versions.reader_model == "qwen3-vl:8b-q4_K_M"
    assert snap.source_versions.normalizer == "1"


def test_reader_model_is_empty_without_a_receipt():
    assert CombinedExpenseSnapshot.build(combined()).source_versions.reader_model is None


@pytest.mark.parametrize(
    "part",
    [
        lambda: {"category": category(txn_id=uuid4())},
        lambda: {"anomaly": anomaly(txn_id=uuid4())},
        lambda: {"receipt": receipt(txn_id=uuid4())},
    ],
)
def test_parts_must_belong_to_the_same_transaction(part):
    with pytest.raises(ValidationError, match="same transaction"):
        combined(**part())


def test_snapshot_txn_id_must_match_payload():
    snap = CombinedExpenseSnapshot.build(combined())
    with pytest.raises(ValidationError, match="txn_id"):
        CombinedExpenseSnapshot(**(snap.model_dump() | {"txn_id": uuid4()}))


@pytest.mark.parametrize("field, value", [("categorizer", "other"), ("reader_model", "other-reader")])
def test_source_versions_must_match_payload(field, value):
    snap = CombinedExpenseSnapshot.build(combined(receipt=receipt()))
    wrong = snap.source_versions.model_copy(update={field: value})
    with pytest.raises(ValidationError, match="source_versions must match"):
        CombinedExpenseSnapshot(**(snap.model_dump() | {"source_versions": wrong.model_dump()}))


def test_snapshot_survives_a_json_round_trip_through_load_snapshot():
    snap = CombinedExpenseSnapshot.build(combined(receipt=receipt()))
    assert load_snapshot(snap.model_dump(mode="json")) == snap


def test_load_snapshot_accepts_a_newer_minor_version_with_extra_fields():
    data = CombinedExpenseSnapshot.build(combined()).model_dump(mode="json")
    data["contract_version"] = "1.9.0"
    data["payload"]["transaction"]["added_later"] = "x"
    assert load_snapshot(data).contract_version == "1.9.0"


def test_load_snapshot_rejects_a_missing_or_incompatible_version():
    data = CombinedExpenseSnapshot.build(combined()).model_dump(mode="json")
    del data["contract_version"]
    with pytest.raises(IncompatibleContractVersion):
        load_snapshot(data)  # the default must not silently stamp old data
    data["contract_version"] = "2.0.0"
    with pytest.raises(IncompatibleContractVersion):
        load_snapshot(data)
