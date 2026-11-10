import pytest
from pydantic import ValidationError

from flag_it.contracts.common import IncompatibleContractVersion
from flag_it.contracts.jobs import InvestigateJob, ReadReceiptJob, load_job
from flag_it.contracts.examples import DECISION_ID, RECEIPT_ID, SNAPSHOT_ID, TXN_ID


def test_jobs_are_stamped_and_round_trip():
    job = InvestigateJob(decision_id=DECISION_ID, snapshot_id=SNAPSHOT_ID, check_ids=["OSU-GEN-02b"])
    assert load_job(InvestigateJob, job.model_dump(mode="json")) == job


def test_a_worker_reads_a_newer_minor_version_with_a_new_field():
    data = ReadReceiptJob(receipt_id=RECEIPT_ID, txn_id=TXN_ID).model_dump(mode="json")
    data |= {"contract_version": "1.1.0", "priority": "high"}
    assert load_job(ReadReceiptJob, data).receipt_id == RECEIPT_ID


def test_load_job_rejects_another_major_version():
    data = ReadReceiptJob(receipt_id=RECEIPT_ID, txn_id=TXN_ID).model_dump(mode="json")
    data["contract_version"] = "99.0.0"
    with pytest.raises(IncompatibleContractVersion):
        load_job(ReadReceiptJob, data)


def test_load_job_rejects_a_missing_version():
    with pytest.raises(IncompatibleContractVersion):
        load_job(ReadReceiptJob, {"receipt_id": str(RECEIPT_ID), "txn_id": str(TXN_ID)})


def test_investigate_needs_at_least_one_check():
    with pytest.raises(ValidationError):
        InvestigateJob(decision_id=DECISION_ID, snapshot_id=SNAPSHOT_ID, check_ids=[])
