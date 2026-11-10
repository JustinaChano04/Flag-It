from decimal import Decimal

import pytest
from pydantic import ValidationError

from flag_it.contracts.examples import normalized, raw_from_file


def test_raw_from_file_is_valid():
    assert raw_from_file().merchant_name == "SQ *JOES CAFE"


def test_raw_from_api_is_valid():
    raw = raw_from_file(source_file=None, source_line_no=None, source="works", external_id="A-1001")
    assert raw.external_id == "A-1001"


def test_raw_needs_exactly_one_origin():
    with pytest.raises(ValidationError, match="exactly one origin"):
        raw_from_file(source_file=None, source_line_no=None)
    with pytest.raises(ValidationError, match="exactly one origin"):
        raw_from_file(source="works", external_id="A-1001")


def test_raw_rejects_a_half_filled_origin():
    # A stray source_file next to a complete API origin is still two origins.
    with pytest.raises(ValidationError, match="exactly one origin"):
        raw_from_file(source_line_no=None, source="works", external_id="A-1001")
    with pytest.raises(ValidationError, match="exactly one origin"):
        raw_from_file(source="works")


def test_raw_from_api_may_carry_mcc_code_and_purpose():
    raw = raw_from_file(
        source_file=None, source_line_no=None, source="works", external_id="A-1",
        mcc_code="5812", business_purpose="Team lunch",
    )
    assert raw.business_purpose == "Team lunch"


def test_normalized_rejects_a_float_amount():
    with pytest.raises(ValidationError, match="must not be a float"):
        normalized(amount=412.0)


def test_normalized_types_amount_and_allows_refunds():
    assert normalized().amount == Decimal("412.00")
    assert normalized(amount="-20.00").amount == Decimal("-20.00")


def test_normalized_optional_fields_default_to_none():
    txn = normalized()
    assert txn.mcc_code is None
    assert txn.business_purpose is None


def test_normalized_mcc_code_is_four_digits():
    assert normalized(mcc_code="5812").mcc_code == "5812"
    with pytest.raises(ValidationError):
        normalized(mcc_code="581")


def test_normalized_survives_a_json_round_trip():
    txn = normalized()
    assert type(txn).model_validate_json(txn.model_dump_json()) == txn
