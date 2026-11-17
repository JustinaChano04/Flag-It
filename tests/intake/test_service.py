"""submit_item: accepted, duplicate, or invalid, and only accepted items are stored."""

import logging
from decimal import Decimal

from flag_it.contracts.api import FieldError
from flag_it.contracts.enums import IntakeStatus
from flag_it.db.records import load_normalized_transaction
from flag_it.intake import service
from flag_it.intake.service import submit_item
from flag_it.intake.store import find_txn_id, txn_exists


def item(**over) -> dict:
    data = {
        "source": "erp",
        "external_id": "A-1001",
        "agencynbr": "01000",
        "last_name": "Smith",
        "first_initial": "J",
        "amount": "412.00",
        "merchant_name": "SQ *JOES CAFE",
        "transaction_date": "14-JAN-25",
        "post_date": "15-JAN-25",
        "mcc_description": "EATING PLACES, RESTAURANTS",
    }
    return data | over


def test_a_new_item_is_accepted_and_stored(conn):
    result = submit_item(conn, item())
    assert (result.index, result.status, result.external_id) == (0, IntakeStatus.ACCEPTED, "A-1001")
    txn = load_normalized_transaction(conn, result.txn_id)
    assert (txn.merchant_norm, txn.amount) == ("JOES CAFE", Decimal("412.00"))
    assert find_txn_id(conn, "erp", "A-1001") == result.txn_id
    assert txn_exists(conn, result.txn_id)


def test_the_same_item_twice_is_a_duplicate_with_the_first_txn_id(conn):
    first = submit_item(conn, item())
    second = submit_item(conn, item(amount="999.00"), index=4)
    assert (second.index, second.status, second.txn_id) == (4, IntakeStatus.DUPLICATE, first.txn_id)


def test_the_same_external_id_from_another_source_is_a_new_transaction(conn):
    first = submit_item(conn, item())
    other = submit_item(conn, item(source="travel-system"))
    assert other.status is IntakeStatus.ACCEPTED and other.txn_id != first.txn_id


def test_an_unknown_field_is_invalid(conn):
    result = submit_item(conn, item(colour="red"))
    assert result.status is IntakeStatus.INVALID
    assert [e.field for e in result.errors] == ["colour"]


def test_a_value_normalization_cannot_read_is_invalid_and_nothing_is_stored(conn):
    result = submit_item(conn, item(amount="abc"))
    assert (result.status, result.txn_id) == (IntakeStatus.INVALID, None)
    assert result.errors == (FieldError(field="amount", message="not a number"),)
    assert find_txn_id(conn, "erp", "A-1001") is None


def test_a_missing_external_id_is_reported_without_one(conn):
    data = item()
    del data["external_id"]
    result = submit_item(conn, data, index=2)
    assert (result.index, result.external_id, result.status) == (2, None, IntakeStatus.INVALID)
    assert [(e.field, e.message) for e in result.errors] == [("external_id", "required")]


def test_an_amount_in_exponent_form_is_invalid_not_an_error(conn, caplog):
    caplog.set_level(logging.INFO, logger="flag_it.intake")
    result = submit_item(conn, item(amount="1e30"), index=4)
    assert result.status is IntakeStatus.INVALID
    assert [(e.field, e.message) for e in result.errors] == [("amount", "not a number")]
    assert "(external_id 'A-1001') is invalid: amount: not a number" in caplog.text


def test_an_item_that_is_not_an_object_is_invalid(conn):
    result = submit_item(conn, ["not", "an", "object"], index=3)
    assert (result.index, result.status) == (3, IntakeStatus.INVALID)


def test_a_race_on_the_same_item_ends_as_a_duplicate(conn, monkeypatch):
    first = submit_item(conn, item())
    real = service.find_txn_id
    calls: list[tuple] = []

    def stale_on_first_call(*args):
        # Another request saved the item between this request's lookup and its insert.
        calls.append(args)
        return None if len(calls) == 1 else real(*args)

    monkeypatch.setattr(service, "find_txn_id", stale_on_first_call)
    second = submit_item(conn, item())
    assert (second.status, second.txn_id) == (IntakeStatus.DUPLICATE, first.txn_id)
