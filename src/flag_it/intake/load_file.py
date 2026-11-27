"""Load one monthly state export (CSV) into raw_transaction, txn, and normalized_transaction.

    python -m flag_it.intake.load_file data/raw/ok_pcard_2025-01.csv

Every row is saved as a raw row, exactly as written. A row that normalizes also gets a txn_id and a
normalized row. A row that doesn't stays raw only and is reported, so a later normalizer version
can pick it up. Rows are identified by (file name, line number): loading a file twice adds nothing.
Uses FLAG_IT_DATABASE_URL. With FLAG_IT_REDIS_URL set, queues an understand job for each new
transaction after the load commits.
"""

import argparse
import csv
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO
from uuid import UUID, uuid4

from flag_it.contracts.transactions import RawTransaction
from flag_it.db import records
from flag_it.db.connection import Conn, connect
from flag_it.intake.normalize import NormalizationError, normalize
from flag_it.intake.store import file_lines_loaded
from flag_it.pipeline.jobs import understand_spec
from flag_it.workers.queue import NoOpQueue, get_job_queue

# Export column -> raw_transaction field. Other columns (FISCAL_YEAR, SOURCE_FILE) are ignored.
COLUMNS = {
    "CALENDAR_YEAR": "calendar_year",
    "CALENDAR_MONTH": "calendar_month",
    "AGENCYNBR": "agencynbr",
    "AGENCYNAME": "agencyname",
    "LAST_NAME": "last_name",
    "FIRST_INITIAL": "first_initial",
    "ITEM_DESCR": "item_descr",
    "AMOUNT": "amount",
    "MERCHANT": "merchant_name",
    "TRANSACTION_DATE": "transaction_date",
    "POST_DATE": "post_date",
    "MCC_DESCRIPTION": "mcc_description",
    "ROWID": "source_rowid",
}


@dataclass(frozen=True)
class LoadReport:
    loaded: int
    skipped: int  # lines already loaded from this file
    not_normalized: tuple[tuple[int, str], ...]  # (line number, what was wrong)
    txn_ids: tuple[UUID, ...] = ()  # the transactions this load created, for the caller to queue


def load_rows(conn: Conn, source_file: str, lines: TextIO) -> LoadReport:
    """`source_file` is the file's name, stored on every row. Each row is its own savepoint."""
    already = file_lines_loaded(conn, source_file)
    reader = csv.DictReader(lines)
    reader.fieldnames = [name.lstrip("﻿").strip() for name in reader.fieldnames or []]
    loaded = skipped = 0
    not_normalized: list[tuple[int, str]] = []
    txn_ids: list[UUID] = []
    for row in reader:
        line = reader.line_num
        if line in already:
            skipped += 1
            continue
        fields = {COLUMNS[k]: v for k, v in row.items() if k in COLUMNS}
        raw = RawTransaction(raw_id=uuid4(), source_file=source_file, source_line_no=line, **fields)
        txn_id = uuid4()
        with conn.transaction():
            records.save_raw_transaction(conn, raw)
            try:
                txn = normalize(raw, txn_id)
            except NormalizationError as error:
                not_normalized.append((line, str(error)))
            else:
                records.save_txn(conn, txn_id, raw.raw_id)
                records.save_normalized_transaction(conn, txn)
                txn_ids.append(txn_id)
        loaded += 1
    return LoadReport(loaded=loaded, skipped=skipped, not_normalized=tuple(not_normalized), txn_ids=tuple(txn_ids))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m flag_it.intake.load_file")
    parser.add_argument("path", type=Path, help="a monthly export CSV, such as data/raw/ok_pcard_2025-01.csv")
    args = parser.parse_args(argv)
    with connect() as conn, args.path.open(encoding="utf-8-sig", newline="") as lines:
        report = load_rows(conn, args.path.name, lines)
    # Queue after the commit above, so a job never starts before its rows are visible.
    queue = get_job_queue()
    for txn_id in report.txn_ids:
        queue.enqueue(understand_spec(txn_id))
    if isinstance(queue, NoOpQueue) and report.txn_ids:
        print(f"FLAG_IT_REDIS_URL is not set: {len(report.txn_ids)} transactions were stored but not queued")
    print(f"{args.path.name}: {report.loaded} loaded, {report.skipped} already loaded, "
          f"{len(report.not_normalized)} kept raw only")
    for line, problem in report.not_normalized[:20]:
        print(f"  line {line}: {problem}")


if __name__ == "__main__":
    main()
