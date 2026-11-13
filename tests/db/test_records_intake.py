"""Raw and normalized transactions round-trip through their tables."""

from uuid import uuid4

import pytest
from psycopg.errors import CheckViolation, ForeignKeyViolation, UniqueViolation

from flag_it.contracts.examples import RAW_ID, TXN_ID, normalized, raw_from_file
from flag_it.contracts.transactions import RawTransaction
from flag_it.db.examples import save_example_transaction
from flag_it.db.records import (
    NotFound,
    load_normalized_transaction,
    load_raw_transaction,
    save_normalized_transaction,
    save_raw_transaction,
    save_txn,
)


def api_raw(**over) -> RawTransaction:
    data = {
        "raw_id": uuid4(),
        "source": "erp",
        "external_id": "A-1001",
        "amount": "12.50",
        "mcc_code": "5812",
        "business_purpose": "Lunch for a visiting speaker",
    }
    return RawTransaction(**(data | over))


def test_raw_from_a_file_round_trips(conn):
    raw = raw_from_file()
    save_raw_transaction(conn, raw)
    assert load_raw_transaction(conn, RAW_ID) == raw


def test_raw_from_the_api_round_trips(conn):
    raw = api_raw()
    save_raw_transaction(conn, raw)
    assert load_raw_transaction(conn, raw.raw_id) == raw


def test_the_same_api_item_twice_is_a_duplicate(conn):
    save_raw_transaction(conn, api_raw())
    with pytest.raises(UniqueViolation), conn.transaction():
        save_raw_transaction(conn, api_raw())


def test_the_same_file_row_twice_is_a_duplicate(conn):
    save_raw_transaction(conn, raw_from_file())
    with pytest.raises(UniqueViolation), conn.transaction():
        save_raw_transaction(conn, raw_from_file(raw_id=uuid4()))


def test_the_database_rejects_a_row_with_two_origins(conn):
    with pytest.raises(CheckViolation), conn.transaction():
        conn.execute(
            "INSERT INTO raw_transaction (raw_id, source_file, source_line_no, source, external_id)"
            " VALUES (%s, 'f.csv', 1, 'erp', 'A-1')",
            (uuid4(),),
        )


def test_normalized_round_trips_and_the_newest_version_wins(conn):
    save_example_transaction(conn)
    v2 = normalized(normalizer_version="2", merchant_norm="JOES CAFE AND CATERING")
    save_normalized_transaction(conn, v2)
    assert load_normalized_transaction(conn, TXN_ID, "1") == normalized()
    assert load_normalized_transaction(conn, TXN_ID) == v2


def test_a_raw_row_gets_one_txn_id(conn):
    save_example_transaction(conn)
    with pytest.raises(UniqueViolation), conn.transaction():
        save_txn(conn, uuid4(), RAW_ID)


def test_a_normalized_row_must_match_its_txn_raw_row(conn):
    save_example_transaction(conn)
    other = raw_from_file(raw_id=uuid4(), source_line_no=43)
    save_raw_transaction(conn, other)
    with pytest.raises(ForeignKeyViolation), conn.transaction():
        save_normalized_transaction(conn, normalized(raw_id=other.raw_id, normalizer_version="9"))


def test_loading_a_missing_row_raises_not_found(conn):
    with pytest.raises(NotFound):
        load_raw_transaction(conn, uuid4())
    with pytest.raises(NotFound):
        load_normalized_transaction(conn, uuid4())
