"""Limits, percentages, totals, and receipt completeness, at and around each threshold."""

import pytest

from flag_it.decide.checks import amounts
from flag_it.decide.checks.base import CannotTell, Finding, NeedsReview, NoFinding
from tests.decide.checks.helpers import context, line, receipt


@pytest.mark.parametrize(
    ("amount", "expected"),
    [("9999.99", NoFinding), ("10000.00", NoFinding), ("10000.01", Finding), ("-20000.00", NoFinding)],
)
def test_single_transaction_limit_reads_the_param(rules, amount, expected):
    limit = rules.rule("OSU-LIM-01").param("max_single_transaction")
    assert limit == 10000  # the cases above sit around this value
    assert isinstance(amounts.single_transaction_limit(context(rules, "OSU-LIM-01a", amount=amount)), expected)


def test_over_the_limit_cites_the_amount_and_the_param(rules):
    outcome = amounts.single_transaction_limit(context(rules, "OSU-LIM-01a", amount="10000.01"))
    assert [(c.ref, c.value) for c in outcome.evidence] == [
        ("transaction.amount", "10000.01"), ("params.max_single_transaction", "10000.00")]
    assert outcome.evidence[1].note == "Over by 0.01"


def test_a_complete_receipt_passes_and_blank_parts_cannot_tell(rules):
    full = receipt(receipt_date="2025-02-27", merchant="Chisholm Books", total="47.25",
                   line_items=[line("Field guide", "47.25")])
    assert isinstance(amounts.itemized_receipt(context(rules, "OSU-GEN-04a", receipt=full)), NoFinding)
    partial = receipt(merchant="Chisholm Books", line_items=[line("Field guide")])
    outcome = amounts.itemized_receipt(context(rules, "OSU-GEN-04a", receipt=partial))
    assert isinstance(outcome, CannotTell)
    assert [c.ref for c in outcome.evidence] == ["receipt.receipt_date", "receipt.total", "receipt.line_items[0].amount"]


def test_a_mismatched_receipt_never_fails_the_total_check(rules):
    ctx = context(rules, "OSU-GEN-04b", amount="40.00", receipt=receipt(total="47.25", match_status="mismatch"))
    assert isinstance(amounts.receipt_total_matches_charge(ctx), NeedsReview)


@pytest.mark.parametrize(
    ("charged", "receipt_fields", "expected"),
    [
        ("47.25", {"total": "47.25"}, NoFinding),
        ("47.75", {"total": "47.25"}, NoFinding),  # within total_tolerance (0.50): a misread cent isn't a flag
        ("-47.25", {"total": "47.25"}, NoFinding),  # a refund compares by size
        ("57.25", {"total": "47.25", "tip": "10.00"}, NoFinding),  # the tip explains the difference
        ("63.25", {"total": "47.25"}, NeedsReview),  # charged more, no tip read: maybe a tip added later
        ("40.00", {"total": "47.25"}, Finding),  # charged less than the receipt: no tip explains that
        ("63.25", {"total": "47.25", "tip": "5.00"}, Finding),  # a tip was read and still doesn't explain it
        ("47.25", {}, CannotTell),
    ],
)
def test_receipt_total_must_equal_the_charge(rules, charged, receipt_fields, expected):
    assert rules.rule("OSU-GEN-04").param("total_tolerance") == 0.5  # the cases above sit around it
    ctx = context(rules, "OSU-GEN-04b", amount=charged, receipt=receipt(**receipt_fields))
    assert isinstance(amounts.receipt_total_matches_charge(ctx), expected)


@pytest.mark.parametrize(
    ("status", "expected"), [("matched", NoFinding), ("mismatch", NeedsReview), ("unmatched", CannotTell)]
)
def test_a_receipt_that_does_not_match_its_charge_needs_review(rules, status, expected):
    ctx = context(rules, "OSU-GEN-04c", receipt=receipt(match_status=status))
    assert isinstance(amounts.receipt_belongs_to_charge(ctx), expected)


@pytest.mark.parametrize(
    ("fee", "expected"),
    [("4.00", NoFinding), ("4.01", Finding)],  # max_fee_pct is 4 on a subtotal of 100.00
)
def test_processing_fee_share(rules, fee, expected):
    r = receipt(subtotal="100.00", line_items=[line("Registration", "100.00"), line("Convenience fee", fee)])
    assert isinstance(amounts.processing_fee_share(context(rules, "OSU-RST-04a", receipt=r)), expected)


def test_a_share_just_over_the_limit_is_over_even_if_it_rounds_to_the_limit(rules):
    r = receipt(subtotal="333.33", line_items=[line("Registration", "333.33"), line("Convenience fee", "13.34")])
    assert isinstance(amounts.processing_fee_share(context(rules, "OSU-RST-04a", receipt=r)), Finding)  # 4.002%


def test_processing_fee_without_fee_lines_or_without_a_subtotal(rules):
    no_fee = receipt(subtotal="100.00", line_items=[line("Registration", "100.00")])
    assert isinstance(amounts.processing_fee_share(context(rules, "OSU-RST-04a", receipt=no_fee)), NoFinding)
    no_subtotal = receipt(line_items=[line("Card processing fee", "9.00")])
    assert isinstance(amounts.processing_fee_share(context(rules, "OSU-RST-04a", receipt=no_subtotal)), CannotTell)


@pytest.mark.parametrize(
    ("receipt_fields", "expected"),
    [
        ({"subtotal": "50.00", "tip": "10.00"}, NoFinding),  # exactly 20%
        ({"subtotal": "50.00", "tip": "10.01"}, Finding),
        ({"subtotal": "50.00", "line_items": [line("Meal", "50.00"), line("Tip", "12.00", "tip")]}, Finding),
        ({"subtotal": "50.00"}, NoFinding),  # no tip at all
        ({"tip": "10.00"}, CannotTell),  # no subtotal to compare with
    ],
)
def test_tip_share(rules, receipt_fields, expected):
    ctx = context(rules, "OSU-RST-17a", receipt=receipt(**receipt_fields))
    assert isinstance(amounts.tip_share(ctx), expected)
