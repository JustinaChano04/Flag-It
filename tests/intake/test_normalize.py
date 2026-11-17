"""Normalization: raw text in, typed fields out, every problem reported at once."""

from datetime import date
from decimal import Decimal

import pytest

from flag_it.contracts.examples import TXN_ID, normalized, raw_from_file
from flag_it.intake.normalize import (
    NORMALIZER_VERSION,
    NormalizationError,
    merchant_norm,
    normalize,
    parse_amount,
    parse_date,
)


def test_the_example_row_normalizes_to_the_example_record():
    assert normalize(raw_from_file(), TXN_ID) == normalized(normalizer_version=NORMALIZER_VERSION)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("412.00", "412.00"),
        ("75.000000000000000000000000000000000000000000000000000", "75.00"),  # as the state export writes it
        (" -12.5 ", "-12.50"),
        ("0", "0.00"),
    ],
)
def test_amounts_become_decimals_with_two_places(text, expected):
    assert parse_amount(text) == Decimal(expected)


@pytest.mark.parametrize("text", ["abc", "1.005", "NaN", "Infinity", "", "1e30", "1E+3", "1" * 40, "12.", "$5.00"])
def test_bad_amounts_are_refused(text):
    with pytest.raises(ValueError):
        parse_amount(text)


@pytest.mark.parametrize(
    ("text", "expected"),
    [("31-Dec-24", date(2024, 12, 31)), ("02-JAN-25", date(2025, 1, 2)), ("2025-01-14", date(2025, 1, 14))],
)
def test_dates_in_the_export_form_and_iso(text, expected):
    assert parse_date(text) == expected


def test_other_date_forms_are_refused():
    with pytest.raises(ValueError, match="not a date"):
        parse_date("2025/01/14")


@pytest.mark.parametrize(
    ("merchant", "mcc", "expected"),
    [
        ("SQ *JOES CAFE", "EATING PLACES, RESTAURANTS", "JOES CAFE"),
        ("AMERICAN AI 0010616917604", "AMERICAN AIRLINES", "AMERICAN AIR"),
        ("AMZN Mktp US*2K4AB1C23", "BOOK STORES", "AMAZON"),
        ("JOURNYHSE   RIGBY", "TRAVEL AGENCIES", "JOURNYHSE RIGBY"),
        ("HAMPTON INN STILLWATER", "HOTELS, MOTELS, AND RESORTS", "HAMPTON INN"),
        ("0010616917604", "AIRLINES", "0010616917604"),
    ],
)
def test_merchant_names_are_cleaned_for_grouping(merchant, mcc, expected):
    assert merchant_norm(merchant, mcc) == expected


def test_the_cardholder_key_keeps_letters_only():
    txn = normalize(raw_from_file(last_name="O'Brien-Smith", first_initial=" j "), TXN_ID)
    assert txn.cardholder_id == "01000|OBRIENSMITH|J"


def test_optional_fields_are_typed_or_left_empty():
    txn = normalize(raw_from_file(mcc_code="5812", business_purpose="   "), TXN_ID)
    assert (txn.mcc_code, txn.business_purpose) == ("5812", None)


def test_every_problem_is_reported_at_once():
    raw = raw_from_file(amount="abc", transaction_date="yesterday", merchant_name="  ", last_name=None, mcc_code="58")
    with pytest.raises(NormalizationError) as caught:
        normalize(raw, TXN_ID)
    assert dict(caught.value.errors) == {
        "amount": "not a number",
        "transaction_date": "not a date (expected dd-MON-yy or YYYY-MM-DD)",
        "merchant_name": "required",
        "last_name": "required",
        "mcc_code": "not a 4-digit code",
    }


def test_a_value_the_contract_refuses_is_reported_by_field():
    with pytest.raises(NormalizationError) as caught:
        normalize(raw_from_file(amount="12345678901.00"), TXN_ID)  # 13 digits; Money allows 12
    assert [field for field, _ in caught.value.errors] == ["amount"]
