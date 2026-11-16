"""Robust z-score: only earlier purchases by the same cardholder, and too little history is not a 0."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from flag_it.contracts.enums import AnomalyStatus
from flag_it.contracts.examples import TXN_ID, normalized, raw_from_file
from flag_it.db import records
from flag_it.understand.anomaly import (
    AnomalyConfig,
    cardholder_history,
    load_anomaly_config,
    robust_z,
    score_anomaly,
)

SCORED_DATE = date(2025, 1, 14)
CONFIG = AnomalyConfig(version="robust-z-test", min_history=10, mad_floor=Decimal("1.00"))
# Median 109, absolute deviations 9 7 5 3 1 1 3 5 7 9, so the MAD is 5.
TEN = [Decimal(a) for a in ("100", "102", "104", "106", "108", "110", "112", "114", "116", "118")]
_lines = iter(range(1000, 100000))


def save_txn(conn, amount, on: date, *, cardholder_id: str = "01000|SMITH|J", renormalized_amount=None):
    """One history transaction: its raw row, txn row, and normalized row (version 1). With
    `renormalized_amount`, a later version 2 row with that amount is saved too."""
    raw = raw_from_file(raw_id=uuid4(), source_line_no=next(_lines))
    txn_id = uuid4()
    records.save_raw_transaction(conn, raw)
    records.save_txn(conn, txn_id, raw.raw_id)
    versions = [("1", amount)] + ([("2", renormalized_amount)] if renormalized_amount is not None else [])
    for version, version_amount in versions:
        records.save_normalized_transaction(
            conn,
            normalized(txn_id=txn_id, raw_id=raw.raw_id, amount=str(version_amount), transaction_date=on,
                       cardholder_id=cardholder_id, normalizer_version=version),
        )
    return txn_id


def save_history(conn, amounts=TEN):
    for i, amount in enumerate(amounts):
        save_txn(conn, amount, SCORED_DATE - timedelta(days=30 - i))


def scored(amount="412.00"):
    return normalized(txn_id=TXN_ID, amount=amount, transaction_date=SCORED_DATE)


def test_robust_z_uses_the_median_and_the_mad():
    assert robust_z(Decimal("412.00"), TEN, Decimal("1.00")) == pytest.approx(0.6745 * 303 / 5)


def test_constant_spending_uses_the_mad_floor_instead_of_dividing_by_zero():
    assert robust_z(Decimal("52"), [Decimal("50")] * 10, Decimal("1.00")) == pytest.approx(0.6745 * 2)


def test_the_packaged_settings_load():
    config = load_anomaly_config()
    assert config.version and config.min_history >= 1 and config.mad_floor > 0


def test_a_cardholder_with_enough_history_is_scored(conn):
    save_history(conn)
    result = score_anomaly(conn, scored(), CONFIG)
    assert (result.status, result.history_length, result.model_version) == (AnomalyStatus.SCORED, 10, "robust-z-test")
    assert result.score == pytest.approx(0.6745 * 303 / 5)
    assert result.as_of == datetime(2025, 1, 14, tzinfo=timezone.utc)


def test_too_little_history_is_insufficient_not_zero(conn):
    save_history(conn, TEN[:9])
    result = score_anomaly(conn, scored(), CONFIG)
    assert (result.status, result.score, result.history_length) == (AnomalyStatus.INSUFFICIENT_HISTORY, None, 9)


def test_transactions_on_or_after_the_date_are_never_used(conn):
    save_history(conn)
    save_txn(conn, "10000", SCORED_DATE)  # same day
    save_txn(conn, "10000", SCORED_DATE + timedelta(days=1))  # later
    result = score_anomaly(conn, scored(), CONFIG)
    assert result.history_length == 10
    assert result.score == pytest.approx(0.6745 * 303 / 5)


def test_other_cardholders_and_refunds_are_not_history(conn):
    save_history(conn)
    save_txn(conn, "5000", SCORED_DATE - timedelta(days=3), cardholder_id="01000|JONES|K")
    save_txn(conn, "-30", SCORED_DATE - timedelta(days=3))
    assert len(cardholder_history(conn, scored())) == 10


def test_a_renormalized_transaction_counts_once_with_its_newest_amount(conn):
    save_history(conn, TEN[:9])
    save_txn(conn, "120", SCORED_DATE - timedelta(days=1), renormalized_amount="130")
    history = cardholder_history(conn, scored())
    assert len(history) == 10
    assert Decimal("130.00") in history and Decimal("120.00") not in history


def test_the_scored_transaction_is_not_its_own_history(conn):
    save_history(conn)
    # The scored transaction itself, already saved with an earlier date by a re-normalization.
    raw = raw_from_file(raw_id=uuid4(), source_line_no=next(_lines))
    records.save_raw_transaction(conn, raw)
    records.save_txn(conn, TXN_ID, raw.raw_id)
    records.save_normalized_transaction(
        conn, normalized(txn_id=TXN_ID, raw_id=raw.raw_id, transaction_date=SCORED_DATE - timedelta(days=5))
    )
    assert len(cardholder_history(conn, scored())) == 10
