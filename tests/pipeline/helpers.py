"""Shared builders for the pipeline tests: a saved example transaction and a decide context."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import uuid4

from flag_it.contracts import examples as ex
from flag_it.contracts.rules import load_rules
from flag_it.db import records
from flag_it.db.examples import receipt_file, save_example_transaction
from flag_it.decide.checks.base import NoFinding
from flag_it.decide.checks.calendar import BillingCalendar
from flag_it.decide.checks.deployment import load_deployment
from flag_it.pipeline.decide_job import DecideContext

NOW = datetime(2025, 1, 20, 9, 0, tzinfo=timezone.utc)
SIGNOFF = datetime(2025, 2, 10, 23, 59, tzinfo=timezone.utc)
# The example transaction posts 2025-01-15; this cycle sets its sign-off cutoff.
CALENDAR = BillingCalendar.model_validate(
    {"cycles": [{"start": "2025-01-01", "end": "2025-01-31", "signoff_due": SIGNOFF}]}
)
RULES = load_rules()
READER = ex.receipt().reader_model


@dataclass(frozen=True)
class FakeScreener:
    p: float = 1.0
    model_version: str = "fake-1"
    threshold: float = 0.5

    def probability(self, snapshot) -> float:
        return self.p


@dataclass
class Controls:
    """What the fake checker for the single-transaction limit answers. Tests change it between runs."""

    limit: object = field(default_factory=NoFinding)

    def checkers(self):
        return {"OSU-LIM-01a": lambda ctx: self.limit}


def save_results(conn) -> None:
    save_example_transaction(conn)
    records.save_category_result(conn, ex.category())
    records.save_anomaly_result(conn, ex.anomaly())


def save_receipt(conn) -> None:
    rid = uuid4()
    records.save_receipt_file(conn, receipt_file(receipt_id=rid, storage_key=f"receipts/{rid}.pdf"))
    records.save_receipt_extraction(conn, ex.receipt(receipt_id=rid))


def context(controls: Controls | None = None, *, p: float = 1.0, calendar=None) -> DecideContext:
    controls = controls or Controls()
    return DecideContext(
        rules=RULES,
        deployment=load_deployment(),
        calendar=CALENDAR if calendar is None else calendar,
        screener=FakeScreener(p),
        mcc_version=ex.category().model_version,
        anomaly_version=ex.anomaly().model_version,
        reader_model=READER,
        checkers=controls.checkers(),
    )
