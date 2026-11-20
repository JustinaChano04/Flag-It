from datetime import datetime, timezone
from uuid import UUID

import pytest

from flag_it.contracts import examples as ex
from flag_it.db import records
from flag_it.db.examples import receipt_file, save_example_transaction
from flag_it.pipeline.snapshot import build_snapshot

NOW = datetime(2026, 11, 20, 9, 0, tzinfo=timezone.utc)
RECEIPT_2 = UUID("00000000-0000-0000-0000-0000000000a6")


def _build(conn, **over):
    args = {"now": NOW, "mcc_version": ex.category().model_version, "anomaly_version": ex.anomaly().model_version}
    args["reader_model"] = ex.receipt().reader_model
    return build_snapshot(conn, ex.TXN_ID, **(args | over))


def _save_results(conn):
    save_example_transaction(conn)
    records.save_category_result(conn, ex.category())
    records.save_anomaly_result(conn, ex.anomaly())


def test_a_snapshot_without_a_receipt_is_saved(conn):
    _save_results(conn)
    snap = _build(conn)
    assert snap.payload.receipt is None
    assert records.load_snapshot(conn, snap.snapshot_id) == snap


def test_the_receipt_is_included_when_the_reader_model_read_one(conn):
    _save_results(conn)
    records.save_receipt_file(conn, receipt_file())
    records.save_receipt_extraction(conn, ex.receipt())
    assert _build(conn).payload.receipt == ex.receipt()


def test_a_receipt_read_by_another_model_is_ignored(conn):
    _save_results(conn)
    records.save_receipt_file(conn, receipt_file())
    records.save_receipt_extraction(conn, ex.receipt(reader_model="another-model"))
    assert _build(conn).payload.receipt is None


def test_the_newest_extraction_wins(conn):
    _save_results(conn)
    records.save_receipt_file(conn, receipt_file())
    records.save_receipt_extraction(conn, ex.receipt())
    records.save_receipt_file(conn, receipt_file(receipt_id=RECEIPT_2, storage_key="receipts/two.pdf"))
    records.save_receipt_extraction(conn, ex.receipt(receipt_id=RECEIPT_2))
    assert _build(conn).payload.receipt.receipt_id == RECEIPT_2


def test_two_calls_make_two_snapshots_from_the_same_parts(conn):
    _save_results(conn)
    one, two = _build(conn), _build(conn)
    assert one.snapshot_id != two.snapshot_id
    assert one.payload == two.payload


def test_a_missing_category_result_raises_not_found(conn):
    save_example_transaction(conn)
    records.save_anomaly_result(conn, ex.anomaly())
    with pytest.raises(records.NotFound):
        _build(conn)


def test_created_at_is_the_clock_passed_in(conn):
    _save_results(conn)
    assert _build(conn).created_at == NOW
