"""Receipt files and Understand-stage results round-trip through their tables."""

from uuid import uuid4

import pytest
from psycopg.errors import CheckViolation, ForeignKeyViolation, UniqueViolation

from flag_it.contracts.examples import RECEIPT_ID, TXN_ID, anomaly, category, receipt
from flag_it.db.examples import receipt_file, save_example_results, save_example_transaction
from flag_it.db.records import (
    load_anomaly_result,
    load_category_result,
    load_receipt_extraction,
    load_receipt_file,
    save_anomaly_result,
    save_receipt_extraction,
    save_receipt_file,
)


def test_every_result_round_trips(conn):
    save_example_results(conn)
    assert load_receipt_file(conn, RECEIPT_ID) == receipt_file()
    assert load_receipt_extraction(conn, RECEIPT_ID, "qwen3-vl:8b-q4_K_M") == receipt()
    assert load_category_result(conn, TXN_ID, "lookup-2025-10") == category()
    assert load_anomaly_result(conn, TXN_ID, "robust-z-1") == anomaly()


def test_an_unreadable_receipt_round_trips_with_empty_fields(conn):
    save_example_transaction(conn)
    save_receipt_file(conn, receipt_file())
    blank = receipt(match_status="unmatched", merchant=None, total=None, line_items=[])
    save_receipt_extraction(conn, blank)
    assert load_receipt_extraction(conn, RECEIPT_ID, blank.reader_model) == blank


def test_insufficient_history_round_trips_without_a_score(conn):
    save_example_transaction(conn)
    thin = anomaly(status="insufficient_history", score=None, history_length=2)
    save_anomaly_result(conn, thin)
    assert load_anomaly_result(conn, TXN_ID, thin.model_version) == thin


def test_a_second_reader_adds_a_row_and_the_same_reader_is_a_duplicate(conn):
    save_example_results(conn)
    save_receipt_extraction(conn, receipt(reader_model="nuextract3:4b"))
    with pytest.raises(UniqueViolation), conn.transaction():
        save_receipt_extraction(conn, receipt())


def test_an_extraction_must_name_its_file_and_the_file_transaction(conn):
    save_example_transaction(conn)
    with pytest.raises(ForeignKeyViolation), conn.transaction():
        save_receipt_extraction(conn, receipt())  # no receipt_file row yet
    save_receipt_file(conn, receipt_file())
    with pytest.raises(ForeignKeyViolation), conn.transaction():
        save_receipt_extraction(conn, receipt(txn_id=uuid4()))


def test_the_database_rejects_a_scored_anomaly_without_a_score(conn):
    save_example_transaction(conn)
    with pytest.raises(CheckViolation), conn.transaction():
        conn.execute(
            "INSERT INTO anomaly_result (txn_id, model_version, status, score, history_length, as_of)"
            " VALUES (%s, 'm', 'scored', NULL, 3, now())",
            (TXN_ID,),
        )
