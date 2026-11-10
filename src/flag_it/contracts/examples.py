"""Small builders for valid example records. Each takes keyword overrides.

Used by this package's tests and by plan 03's fixtures. Not used by pipeline code.
"""

from datetime import date, datetime, timezone
from uuid import UUID

from flag_it.contracts.transactions import NormalizedTransaction, RawTransaction

TXN_ID = UUID("00000000-0000-0000-0000-000000000001")
RAW_ID = UUID("00000000-0000-0000-0000-000000000002")
DECISION_ID = UUID("00000000-0000-0000-0000-000000000003")
SNAPSHOT_ID = UUID("00000000-0000-0000-0000-000000000004")
FLAG_ID = UUID("00000000-0000-0000-0000-000000000005")
RECEIPT_ID = UUID("00000000-0000-0000-0000-000000000006")
AS_OF = datetime(2025, 1, 15, 12, 0, tzinfo=timezone.utc)


def raw_from_file(**over) -> RawTransaction:
    data = {
        "raw_id": RAW_ID,
        "source_file": "FY2025_01.csv",
        "source_line_no": 42,
        "agencynbr": " 01000",
        "last_name": "SMITH",
        "first_initial": "J",
        "amount": "412.00",
        "merchant_name": "SQ *JOES CAFE",
        "transaction_date": "14-JAN-25",
        "post_date": "15-JAN-25",
        "mcc_description": "EATING PLACES, RESTAURANTS",
    }
    return RawTransaction(**(data | over))


def normalized(**over) -> NormalizedTransaction:
    data = {
        "txn_id": TXN_ID,
        "raw_id": RAW_ID,
        "agency_id": "01000",
        "cardholder_id": "01000|SMITH|J",
        "merchant_norm": "JOES CAFE",
        "mcc_description": "EATING PLACES, RESTAURANTS",
        "amount": "412.00",
        "transaction_date": date(2025, 1, 14),
        "post_date": date(2025, 1, 15),
        "normalizer_version": "1",
    }
    return NormalizedTransaction(**(data | over))
