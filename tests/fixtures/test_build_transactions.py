"""Fixture transactions: one per spend category, plus variants at the edges."""

from decimal import Decimal
from uuid import UUID

from flag_it.contracts.enums import AnomalyStatus, CategoryMethod
from flag_it.fixtures.build import (
    CATEGORY_TXNS,
    anomaly_result,
    category_result,
    fid,
    normalized_transaction,
    raw_transaction,
    transactions,
)


def test_fixture_ids_never_change():
    assert fid("txn", "cat_lodging") == UUID("c7c223ff-8d24-504f-85b8-b2dabbf3279e")


def test_one_transaction_per_spend_category(rules):
    assert sorted(spec.category for spec in CATEGORY_TXNS.values()) == sorted(rules.categories)
    for name, spec in CATEGORY_TXNS.items():
        assert name == f"cat_{spec.category}"


def test_limit_amounts_come_from_the_rule_params(rules):
    limit = Decimal(str(rules.rule("OSU-LIM-01").param("max_single_transaction")))
    txns = transactions(rules)
    assert Decimal(txns["over_single_limit"].amount) == limit + Decimal("0.01")
    assert Decimal(txns["at_single_limit"].amount) == limit


def test_raw_and_normalized_rows_agree(rules):
    for name, spec in transactions(rules).items():
        raw, txn = raw_transaction(name, spec), normalized_transaction(name, spec)
        assert (raw.raw_id, raw.external_id, raw.source) == (txn.raw_id, name, "fixtures")
        assert Decimal(raw.amount) == txn.amount
        assert txn.cardholder_id == f"01000|{raw.last_name}|{raw.first_initial}"
        assert txn.txn_id == fid("txn", name)


def test_edge_cases(rules):
    txns = transactions(rules)
    assert anomaly_result("new_cardholder", txns["new_cardholder"]).status is AnomalyStatus.INSUFFICIENT_HISTORY
    assert anomaly_result("unusual_amount", txns["unusual_amount"]).score > 3.5
    assert Decimal(txns["refund"].amount) < 0
    assert txns["with_purpose"].business_purpose and txns["with_purpose"].mcc_code
    unclear = category_result("cat_other_unclear", txns["cat_other_unclear"])
    assert unclear.method is CategoryMethod.MODEL and unclear.confidence < 0.5


def test_categories_exist_in_the_rules(rules):
    for name, spec in transactions(rules).items():
        assert rules.has_category(category_result(name, spec).category)
