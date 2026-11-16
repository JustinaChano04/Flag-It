"""Matching verifies a receipt against its transaction: total, date, and merchant within tolerances."""

from decimal import Decimal

import pytest

from flag_it.contracts.enums import MatchStatus
from flag_it.contracts.examples import normalized
from flag_it.understand.receipts.matching import MatchConfig, load_match_config, match, merchant_similarity
from flag_it.understand.receipts.reader import Reading, to_fields

CONFIG = MatchConfig(total_tolerance=Decimal("0.50"), date_tolerance_days=3, merchant_min_similarity=0.6)
TXN = normalized()  # JOES CAFE, 412.00, 2025-01-14


def status(**reading) -> MatchStatus:
    return match(to_fields(Reading(**reading)), TXN, CONFIG)


def test_the_packaged_settings_load():
    config = load_match_config()
    assert config.total_tolerance >= 0 and config.date_tolerance_days >= 0 and 0 < config.merchant_min_similarity <= 1


def test_a_receipt_that_agrees_is_matched():
    assert status(merchant="Joe's Cafe", receipt_date="2025-01-13", total="412.25") is MatchStatus.MATCHED


@pytest.mark.parametrize(
    "reading",
    [
        {"merchant": "Joe's Cafe", "receipt_date": "2025-01-14", "total": "450.00"},  # total off by 38
        {"merchant": "Joe's Cafe", "receipt_date": "2025-01-02", "total": "412.00"},  # 12 days apart
        {"merchant": "Grand Hotel Tulsa", "receipt_date": "2025-01-14", "total": "412.00"},  # another merchant
    ],
)
def test_a_field_outside_its_tolerance_is_a_mismatch(reading):
    assert status(**reading) is MatchStatus.MISMATCH


@pytest.mark.parametrize(
    "reading",
    [{}, {"merchant": "Joe's Cafe", "receipt_date": "2025-01-14"}, {"total": "412.00"}],
)
def test_too_little_to_compare_is_unmatched(reading):
    assert status(**reading) is MatchStatus.UNMATCHED


def test_a_total_and_one_other_field_are_enough():
    assert status(total="412.00", receipt_date="2025-01-14") is MatchStatus.MATCHED


def test_a_tip_on_the_receipt_can_make_up_the_charge():
    assert status(total="400.00", tip="12.00", receipt_date="2025-01-14") is MatchStatus.MATCHED
    assert status(total="400.00", tip="5.00", receipt_date="2025-01-14") is MatchStatus.MISMATCH


def test_a_refund_compares_amounts_without_sign():
    refund = normalized(amount="-412.00")
    assert match(to_fields(Reading(total="412.00", merchant="Joes Cafe")), refund, CONFIG) is MatchStatus.MATCHED


@pytest.mark.parametrize(
    ("a", "b", "at_least"),
    [("Joe's Cafe", "JOES CAFE", 1.0), ("Amazon.com Services LLC", "AMAZON", 1.0), ("Hampton Inn & Suites", "HAMPTON INN", 1.0)],
)
def test_merchant_names_compare_after_cleaning(a, b, at_least):
    assert merchant_similarity(a, b) >= at_least
