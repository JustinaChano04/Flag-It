"""Builders for rule-check tests: a receipt, a check context, and a snapshot, from the shared fixtures."""

from datetime import datetime
from decimal import Decimal
from uuid import uuid4

from flag_it import fixtures
from flag_it.contracts.rules import RuleSet
from flag_it.contracts.snapshot import CombinedExpenseSnapshot
from flag_it.contracts.understand import ReceiptExtraction
from flag_it.decide.checks.base import CheckContext

BASE = "cat_office_general_supplies"  # an office-supplies charge of 47.25 with no receipt


def line(description: str | None, amount: str | None = None, line_type: str = "item") -> dict:
    return {"description": description, "amount": amount, "line_type": line_type}


def receipt(**fields) -> ReceiptExtraction:
    """A receipt for the BASE transaction, matched unless given match_status. Fields not given are blank."""
    return ReceiptExtraction(
        receipt_id=uuid4(),
        txn_id=fixtures.snapshot(BASE).txn_id,
        reader_model="test-reader",
        **{"match_status": "matched", **fields},
    )


def snapshot(
    *, receipt: ReceiptExtraction | None = None, amount: str | None = None, category: str | None = None,
    base: str = BASE, taken_at: datetime | None = None,
) -> CombinedExpenseSnapshot:
    """A fixture snapshot with its receipt, amount, category, or time changed."""
    snap = fixtures.snapshot(base)
    payload = snap.payload
    txn = payload.transaction if amount is None else payload.transaction.model_copy(update={"amount": Decimal(amount)})
    cat = payload.category if category is None else payload.category.model_copy(update={"category": category})
    payload = payload.model_copy(update={"transaction": txn, "category": cat, "receipt": receipt})
    return snap.model_copy(update={"payload": payload, "created_at": taken_at or snap.created_at})


def context(rules: RuleSet, check_id: str, **changes) -> CheckContext:
    rule, check = rules.check(check_id)
    return CheckContext(snapshot(**changes).payload, rule, check)
