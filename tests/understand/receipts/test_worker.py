"""handle_read_receipt: one extraction per receipt and reader model, and bad jobs are rejected."""

from decimal import Decimal
from uuid import uuid4

import pytest

from flag_it.contracts.common import IncompatibleContractVersion
from flag_it.contracts.enums import MatchStatus
from flag_it.contracts.examples import RECEIPT_ID, TXN_ID
from flag_it.contracts.jobs import ReadReceiptJob
from flag_it.db import records
from flag_it.db.examples import receipt_file, save_example_transaction
from flag_it.understand.receipts.matching import MatchConfig
from arq.worker import Retry

from flag_it.understand.receipts.reader import LineReading, Reading, StaticReader, UnreadableFile
from flag_it.understand.receipts.store import LocalStore
from flag_it.understand.receipts.worker import ReceiptNotReady, handle_read_receipt

CONFIG = MatchConfig(total_tolerance=Decimal("0.50"), date_tolerance_days=3, merchant_min_similarity=0.6)
GOOD = Reading(
    merchant="Joe's Cafe", receipt_date="2025-01-14", total="412.00",
    line_items=[LineReading(description="Catering tray", quantity="1", amount="412.00")],
)


@pytest.fixture
def store(tmp_path):
    return LocalStore(tmp_path)


@pytest.fixture
def uploaded(conn, store):
    """The example transaction with its receipt file uploaded and stored."""
    save_example_transaction(conn)
    file = receipt_file()
    store.put(file.storage_key, b"%PDF fake bytes", file.content_type)
    records.save_receipt_file(conn, file)
    return conn


def job(**over) -> dict:
    return ReadReceiptJob(receipt_id=RECEIPT_ID, txn_id=TXN_ID).model_dump(mode="json") | over


def test_a_receipt_is_read_matched_and_saved(uploaded, store):
    extraction = handle_read_receipt(uploaded, store, StaticReader("fake-1", GOOD), CONFIG, job())
    assert extraction.match_status is MatchStatus.MATCHED
    assert (extraction.reader_model, extraction.total, extraction.merchant) == ("fake-1", Decimal("412.00"), "Joe's Cafe")
    assert records.load_receipt_extraction(uploaded, RECEIPT_ID, "fake-1") == extraction


def test_a_repeated_job_returns_the_saved_extraction_without_reading_again(uploaded, store):
    first = handle_read_receipt(uploaded, store, StaticReader("fake-1", GOOD), CONFIG, job())
    # A different reading proves the reader wasn't called again; the caller can still start the rerun.
    assert handle_read_receipt(uploaded, store, StaticReader("fake-1", Reading()), CONFIG, job()) == first


def test_a_concurrent_duplicate_keeps_the_extraction_already_saved(uploaded, store):
    class Racing:
        """Saves another worker's extraction while 'reading', as a duplicate job running at once would."""

        model_tag = "fake-1"

        def read(self, content, content_type):
            handle_read_receipt(uploaded, store, StaticReader("fake-1", GOOD), CONFIG, job())
            return Reading()

    result = handle_read_receipt(uploaded, store, Racing(), CONFIG, job())
    assert result.total == Decimal("412.00")  # the first save won; the second was a no-op


def test_a_file_that_cannot_be_decoded_is_saved_blank_and_logged(uploaded, store, caplog):
    class Undecodable:
        model_tag = "fake-1"

        def read(self, content, content_type):
            raise UnreadableFile("not a readable PDF")

    extraction = handle_read_receipt(uploaded, store, Undecodable(), CONFIG, job())
    assert extraction.match_status is MatchStatus.UNMATCHED and extraction.total is None
    assert "not a readable PDF" in caplog.text


def test_another_reader_model_adds_its_own_row(uploaded, store):
    handle_read_receipt(uploaded, store, StaticReader("fake-1", GOOD), CONFIG, job())
    second = handle_read_receipt(uploaded, store, StaticReader("fake-2", GOOD), CONFIG, job())
    assert second is not None and second.reader_model == "fake-2"


def test_an_unreadable_receipt_is_saved_blank_and_unmatched(uploaded, store):
    extraction = handle_read_receipt(uploaded, store, StaticReader("fake-1", Reading()), CONFIG, job())
    assert extraction.match_status is MatchStatus.UNMATCHED
    assert (extraction.merchant, extraction.total, extraction.line_items) == (None, None, ())


def test_a_receipt_that_disagrees_is_a_mismatch(uploaded, store):
    wrong_total = GOOD.model_copy(update={"total": "450.00"})
    extraction = handle_read_receipt(uploaded, store, StaticReader("fake-1", wrong_total), CONFIG, job())
    assert extraction.match_status is MatchStatus.MISMATCH


def test_a_job_from_another_major_version_is_rejected(uploaded, store):
    with pytest.raises(IncompatibleContractVersion):
        handle_read_receipt(uploaded, store, StaticReader("fake-1", GOOD), CONFIG, job(contract_version="2.0.0"))


def test_a_job_before_its_upload_is_committed_is_retried_by_arq(conn, store):
    save_example_transaction(conn)
    with pytest.raises(ReceiptNotReady) as caught:
        handle_read_receipt(conn, store, StaticReader("fake-1", GOOD), CONFIG, job())
    # Arq retries only Retry; any other exception would fail the job for good.
    assert isinstance(caught.value, Retry) and caught.value.defer_score == 5000


def test_a_job_naming_another_transaction_is_rejected(uploaded, store):
    with pytest.raises(ValueError, match="does not match"):
        handle_read_receipt(uploaded, store, StaticReader("fake-1", GOOD), CONFIG, job(txn_id=str(uuid4())))
