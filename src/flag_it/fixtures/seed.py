"""Save every fixture into a database, in foreign-key order. For the review app and integration tests.

    from flag_it.fixtures.seed import seed
    seed(conn)   # the caller commits

Rows go through flag_it.db.records, so they are exactly what the pipeline will write. Seed an
empty database: every table is append-only, so seeding twice fails on the first duplicate key.
"""

from flag_it import fixtures
from flag_it.db import records
from flag_it.db.connection import Conn
from flag_it.db.rows import StoredAgentVerdict


def seed(conn: Conn) -> None:
    snaps = list(fixtures.snapshots().values())
    parts = [snap.payload for snap in snaps]

    for raw in fixtures.raw_transactions().values():
        records.save_raw_transaction(conn, raw)
    # Chain snapshots share their parts, so save each part once.
    for txn in {p.transaction.txn_id: p.transaction for p in parts}.values():
        records.save_txn(conn, txn.txn_id, txn.raw_id)
        records.save_normalized_transaction(conn, txn)
    for file in fixtures.receipt_files().values():
        records.save_receipt_file(conn, file)
    for receipt in {(p.receipt.receipt_id, p.receipt.reader_model): p.receipt for p in parts if p.receipt}.values():
        records.save_receipt_extraction(conn, receipt)
    for category in {(p.category.txn_id, p.category.model_version): p.category for p in parts}.values():
        records.save_category_result(conn, category)
    for anomaly in {(p.anomaly.txn_id, p.anomaly.model_version): p.anomaly for p in parts}.values():
        records.save_anomaly_result(conn, anomaly)

    runs = sorted(fixtures.decision_runs().items(), key=lambda item: item[1].created_at)
    for snap in snaps:
        records.save_snapshot(conn, snap)
    outputs = fixtures.agent_outputs()
    for name, run in runs:  # oldest first, so a rerun's predecessor already exists
        records.save_decision_run(conn, run)
        for flag in fixtures.flags(name):
            records.save_flag(conn, flag)
        if name in outputs:
            for verdict in outputs[name].verdicts:
                records.save_agent_verdict(conn, StoredAgentVerdict.from_verdict(run.decision_id, verdict))
    for review in fixtures.review_outcomes().values():
        records.save_review_outcome(conn, review)
