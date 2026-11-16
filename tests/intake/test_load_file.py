"""The monthly export loads once, row by row; rows that don't normalize stay raw and are reported."""

import io
from decimal import Decimal

from flag_it.intake.load_file import load_rows

HEADER = (
    "CALENDAR_YEAR,CALENDAR_MONTH,AGENCYNBR,AGENCYNAME,LAST_NAME,FIRST_INITIAL,ITEM_DESCR,AMOUNT,MERCHANT,"
    "TRANSACTION_DATE,POST_DATE,MCC_DESCRIPTION,ROWID,FISCAL_YEAR\n"
)
GOOD = (
    "2025,01, 01000,OKLAHOMA STATE UNIVERSITY,Schmitt,A,GENERAL PURCHASE,"
    "75.000000000000000000000000000000000000000000000000000,JOURNYHSE   RIGBY,31-Dec-24,02-Jan-25,"
    "TRAVEL AGENCIES,AAAJGhAANAANABYAAJ,FY2025\n"
)
BAD = (
    "2025,01, 01000,OKLAHOMA STATE UNIVERSITY,Schmitt,A,AIR TRAVEL,not-a-number,AMERICAN AI 0010616917604,"
    "30-Dec-24,02-Jan-25,AMERICAN AIRLINES,AAAJGhAANAANABYAAK,FY2025\n"
)
FILE = "ok_pcard_2025-01.csv"


def test_rows_load_and_bad_rows_stay_raw(conn):
    report = load_rows(conn, FILE, io.StringIO(HEADER + GOOD + BAD))
    assert (report.loaded, report.skipped) == (2, 0)
    assert report.not_normalized == ((3, "amount: not a number"),)
    rows = conn.execute(
        "SELECT r.source_line_no, r.agencynbr, r.amount AS raw_amount, n.merchant_norm, n.amount"
        " FROM raw_transaction r LEFT JOIN normalized_transaction n USING (raw_id)"
        " WHERE r.source_file = %s ORDER BY r.source_line_no",
        (FILE,),
    ).fetchall()
    assert [(r["source_line_no"], r["agencynbr"], r["merchant_norm"], r["amount"]) for r in rows] == [
        (2, " 01000", "JOURNYHSE RIGBY", Decimal("75.00")),
        (3, " 01000", None, None),
    ]
    assert rows[1]["raw_amount"] == "not-a-number"  # the raw row keeps the text exactly


def test_loading_the_same_file_again_adds_nothing(conn):
    load_rows(conn, FILE, io.StringIO(HEADER + GOOD + BAD))
    again = load_rows(conn, FILE, io.StringIO(HEADER + GOOD + BAD))
    assert (again.loaded, again.skipped, again.not_normalized) == (0, 2, ())


def test_a_file_with_a_byte_order_mark_loads(conn):
    report = load_rows(conn, FILE, io.StringIO("﻿" + HEADER + GOOD))
    assert report.loaded == 1
