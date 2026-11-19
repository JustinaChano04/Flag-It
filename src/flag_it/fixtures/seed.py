"""Save every fixture into a database, in foreign-key order. For the review app and integration tests.

    from flag_it.fixtures.seed import seed
    seed(conn)   # the caller commits

    python -m flag_it.fixtures.seed   # FLAG_IT_DATABASE_URL, plus sample receipt files in the store

Rows go through flag_it.db.records, so they are exactly what the pipeline will write. Seed an
empty database: every table is append-only, so seeding twice fails on the first duplicate key.
"""

import io
import sys

from PIL import Image, ImageDraw

from flag_it import fixtures
from flag_it.contracts.understand import ReceiptExtraction
from flag_it.db import records
from flag_it.db.connection import Conn, connect
from flag_it.db.rows import StoredAgentVerdict
from flag_it.understand.receipts.store import ReceiptStore, store_from_env


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


def _text(value) -> str:
    return "" if value is None else str(value)


def sample_receipt_pdf(title: str, receipt: ReceiptExtraction | None) -> bytes:
    """A one-page PDF that prints what the fixture's reading says, so the review app has a file to
    show. It is not the file the fixture's sha256 and size describe: those are made up."""
    lines = [f"SAMPLE RECEIPT ({title})", ""]
    if receipt is not None:
        lines += [receipt.merchant or "(no merchant)", str(receipt.receipt_date or "(no date)"), ""]
        lines += [f"{line.description or '?':<28} {_text(line.amount)}" for line in receipt.line_items]
        lines += ["", f"{'SUBTOTAL':<28} {_text(receipt.subtotal)}", f"{'TAX':<28} {_text(receipt.tax)}"]
        lines += [f"{'TIP':<28} {_text(receipt.tip)}", f"{'TOTAL':<28} {_text(receipt.total)}"]
    image = Image.new("RGB", (420, 40 + 16 * len(lines)), "white")
    draw = ImageDraw.Draw(image)
    for row, text in enumerate(lines):
        draw.text((20, 20 + 16 * row), text, fill="black")
    buffer = io.BytesIO()
    image.save(buffer, format="PDF")
    return buffer.getvalue()


def put_sample_receipts(store: ReceiptStore) -> int:
    """Put a sample file in the store for every fixture receipt file. Returns how many."""
    readings = {
        snap.payload.receipt.receipt_id: snap.payload.receipt
        for snap in fixtures.snapshots().values()
        if snap.payload.receipt is not None
    }
    files = fixtures.receipt_files()
    for name, file in files.items():
        store.put(file.storage_key, sample_receipt_pdf(name, readings.get(file.receipt_id)), file.content_type)
    return len(files)


def main() -> None:
    with connect() as conn:
        if conn.execute("SELECT 1 FROM decision_run LIMIT 1").fetchone() is not None:
            sys.exit("the database already has decision runs; seed only an empty, migrated database")
        seed(conn)
    count = put_sample_receipts(store_from_env())
    print(f"seeded {len(fixtures.decision_runs())} decision runs and {count} sample receipt files")


if __name__ == "__main__":
    main()
