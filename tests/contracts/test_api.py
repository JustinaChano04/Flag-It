import pytest
from pydantic import ValidationError

from flag_it.contracts.api import (
    BatchRequest,
    BatchResponse,
    DecisionHistory,
    IntakeItemResult,
    IntakeResponse,
    ReceiptAccepted,
    ReviewIn,
    ReviewQueue,
    TransactionIn,
    TransactionView,
)
from flag_it.contracts.common import CONTRACT_VERSION
from flag_it.contracts.examples import RECEIPT_ID, TXN_ID, decision_run, flag


def test_transaction_in_needs_source_and_external_id():
    txn = TransactionIn(source="works", external_id="A-1001", amount="12.00", business_purpose="Lunch")
    assert txn.business_purpose == "Lunch"
    with pytest.raises(ValidationError):
        TransactionIn(source="works", amount="12.00")
    with pytest.raises(ValidationError):
        TransactionIn(source="works", external_id="A-1", amout="12.00")  # typo: rejected


def test_batch_request_is_not_empty():
    with pytest.raises(ValidationError):
        BatchRequest(items=[])


def test_one_malformed_item_does_not_fail_the_batch():
    # The endpoint validates items one by one; the request body itself must still parse.
    batch = BatchRequest(items=[{"source": "works", "external_id": "A-1"}, {"amout": "x"}])
    results = []
    for index, item in enumerate(batch.items):
        try:
            TransactionIn.model_validate(item)
            results.append("accepted")
        except ValidationError:
            results.append("invalid")
    assert results == ["accepted", "invalid"]


def test_accepted_and_duplicate_items_carry_a_txn_id():
    assert IntakeItemResult(index=0, external_id="A-1", status="duplicate", txn_id=TXN_ID).txn_id == TXN_ID
    with pytest.raises(ValidationError, match="has a txn_id and no errors"):
        IntakeItemResult(index=0, external_id="A-1", status="accepted")
    with pytest.raises(ValidationError, match="has a txn_id and no errors"):
        IntakeItemResult(
            index=0, external_id="A-1", status="duplicate", txn_id=TXN_ID,
            errors=[{"field": "amount", "message": "x"}],
        )


def test_invalid_items_carry_errors_and_no_txn_id():
    item = IntakeItemResult(
        index=2, external_id="A-3", status="invalid", errors=[{"field": "amount", "message": "not a number"}]
    )
    assert item.errors[0].field == "amount"
    with pytest.raises(ValidationError, match="has errors and no txn_id"):
        IntakeItemResult(index=2, external_id="A-3", status="invalid")
    with pytest.raises(ValidationError, match="has errors and no txn_id"):
        IntakeItemResult(
            index=2, external_id="A-3", status="invalid", txn_id=TXN_ID,
            errors=[{"field": "amount", "message": "x"}],
        )


def test_an_item_missing_its_external_id_can_still_be_reported():
    item = IntakeItemResult(
        index=3, status="invalid", errors=[{"field": "external_id", "message": "required"}]
    )
    assert item.external_id is None
    with pytest.raises(ValidationError, match="external_id"):
        IntakeItemResult(index=0, status="accepted", txn_id=TXN_ID)


def test_responses_are_stamped():
    item = IntakeItemResult(index=0, external_id="A-1", status="accepted", txn_id=TXN_ID)
    assert BatchResponse(items=[item]).contract_version == CONTRACT_VERSION
    assert IntakeResponse(item=item).contract_version == CONTRACT_VERSION
    assert ReceiptAccepted(receipt_id=RECEIPT_ID, txn_id=TXN_ID).contract_version == CONTRACT_VERSION
    assert TransactionView(txn_id=TXN_ID, decision=decision_run(), flags=[flag()]).flags[0].score == 1.0
    assert DecisionHistory(txn_id=TXN_ID, decisions=[decision_run()]).decisions[0].route == "flag"
    assert ReviewQueue(items=[decision_run()]).contract_version == CONTRACT_VERSION


def test_review_in_rejects_unknown_fields():
    assert ReviewIn(reviewer="r7", final="approve", missed_rule_ids=["OSU-TRV-13"]).final == "approve"
    with pytest.raises(ValidationError):
        ReviewIn(reviewer="r7", final="approve", review_id=str(TXN_ID))  # the server assigns this
