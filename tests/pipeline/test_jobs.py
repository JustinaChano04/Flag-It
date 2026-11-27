from uuid import uuid4

from flag_it.contracts.enums import RunTrigger
from flag_it.contracts.jobs import DecideJob, UnderstandJob, load_job
from flag_it.pipeline.jobs import JobSpec, job_id_decide, job_id_investigate, job_id_understand


def test_job_ids_are_deterministic_and_distinguish_what_must_differ():
    txn, after = uuid4(), uuid4()
    assert job_id_understand(txn) == job_id_understand(txn)
    assert job_id_decide(txn, RunTrigger.INITIAL, None) != job_id_decide(txn, RunTrigger.LATE_RECEIPT, after)
    # the same trigger after a different earlier run is a different job (a second late receipt)
    assert job_id_decide(txn, RunTrigger.LATE_RECEIPT, after) != job_id_decide(txn, RunTrigger.LATE_RECEIPT, uuid4())
    assert job_id_investigate(after).startswith("investigate:")


def test_new_jobs_carry_the_contract_version_and_reject_another_major():
    job = DecideJob(txn_id=uuid4(), trigger=RunTrigger.DEADLINE)
    assert load_job(DecideJob, job.model_dump(mode="json")) == job
    stale = {**job.model_dump(mode="json"), "contract_version": "2.0.0"}
    try:
        load_job(DecideJob, stale)
    except ValueError:
        pass
    else:
        raise AssertionError("a job from another major version must be rejected")


def test_a_job_spec_is_plain_data():
    spec = JobSpec("understand", UnderstandJob(txn_id=uuid4()).model_dump(mode="json"), "understand:x")
    assert spec.name == "understand" and spec.job_id == "understand:x"
