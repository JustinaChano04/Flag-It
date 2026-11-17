"""The reader: the model's text becomes typed fields, unreadable values stay empty, and the Ollama
request asks for forced JSON with thinking off."""

import base64
import io
import json
from datetime import date
from decimal import Decimal

import httpx
import pypdfium2 as pdfium
import pytest
from PIL import Image

from flag_it.contracts.enums import LineType
from flag_it.understand.receipts import reader as reader_module
from flag_it.understand.receipts.reader import (
    DEFAULT_MODEL,
    LineReading,
    OllamaReader,
    Reading,
    StaticReader,
    UnreadableFile,
    reader_from_env,
    to_fields,
    to_images,
)

def tiny_png() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (4, 4), "white").save(buffer, format="PNG")
    return buffer.getvalue()


PNG = tiny_png()


def one_page_pdf() -> bytes:
    pdf = pdfium.PdfDocument.new()
    pdf.new_page(200, 200)
    buffer = io.BytesIO()
    pdf.save(buffer)
    return buffer.getvalue()


def test_fields_are_typed():
    reading = Reading(
        merchant=" Joe's Cafe ",
        receipt_date="2025-01-14",
        subtotal="$1,000.00",
        tax="80.00",
        tip=None,
        total="1080.00",
        line_items=[LineReading(description="Catering tray", quantity="2", unit_price="500", amount="1000", line_type="ITEM")],
    )
    fields = to_fields(reading)
    assert fields["merchant"] == "Joe's Cafe"
    assert fields["receipt_date"] == date(2025, 1, 14)
    assert (fields["subtotal"], fields["tax"], fields["tip"], fields["total"]) == (
        Decimal("1000.00"), Decimal("80.00"), None, Decimal("1080.00"))
    item = fields["line_items"][0]
    assert (item.quantity, item.amount, item.line_type) == (Decimal("2"), Decimal("1000.00"), LineType.ITEM)


@pytest.mark.parametrize("text", ["abc", "12.345", "NaN", "", "99999999999.00"])
def test_unparseable_money_is_left_empty(text):
    assert to_fields(Reading(total=text))["total"] is None


@pytest.mark.parametrize(("text", "expected"), [("01/14/2025", date(2025, 1, 14)), ("1/14/25", date(2025, 1, 14)), ("soon", None)])
def test_dates_in_common_receipt_forms(text, expected):
    assert to_fields(Reading(receipt_date=text))["receipt_date"] == expected


@pytest.mark.parametrize(("text", "expected"), [(None, LineType.ITEM), ("tax", LineType.TAX), ("Room", LineType.ROOM), ("discount", LineType.OTHER)])
def test_line_types(text, expected):
    assert to_fields(Reading(line_items=[LineReading(line_type=text)]))["line_items"][0].line_type is expected


def test_an_empty_reading_is_all_blank():
    fields = to_fields(Reading())
    assert all(value is None for key, value in fields.items() if key != "line_items")
    assert fields["line_items"] == ()


def test_a_static_reader_returns_its_reading():
    reader = StaticReader("fake-1", Reading(total="5.00"))
    assert (reader.model_tag, reader.read(b"x", "image/png").total) == ("fake-1", "5.00")


def test_images_pass_through_and_pdf_pages_become_png():
    assert to_images(PNG, "image/png") == [PNG]
    pages = to_images(one_page_pdf(), "application/pdf")
    assert len(pages) == 1 and pages[0].startswith(b"\x89PNG")


def test_other_types_are_refused():
    with pytest.raises(ValueError, match="unsupported"):
        to_images(b"x", "text/plain")


@pytest.mark.parametrize(
    ("content", "content_type"),
    [(b"%PDF-1.7 not really a pdf", "application/pdf"), (b"\x89PNG\r\n\x1a\n" + b"\x00" * 16, "image/png"), (b"\xff\xd8\xff junk", "image/jpeg")],
)
def test_bytes_that_do_not_decode_are_unreadable(content, content_type):
    with pytest.raises(UnreadableFile):
        to_images(content, content_type)


def test_a_huge_page_is_rendered_smaller_and_a_huge_image_is_refused(monkeypatch):
    monkeypatch.setattr(reader_module, "MAX_PIXELS", 10_000)  # a 200x200 pt page at 2x would be 160,000
    page = Image.open(io.BytesIO(to_images(one_page_pdf(), "application/pdf")[0]))
    assert page.width * page.height <= 10_000
    monkeypatch.setattr(reader_module, "MAX_PIXELS", 10)
    with pytest.raises(UnreadableFile, match="pixels"):
        to_images(PNG, "image/png")


def ollama(contents: list[str], seen: list[dict]):
    """A fake Ollama /api/chat that answers with each content in turn and records the requests."""
    answers = iter(contents)

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"message": {"role": "assistant", "content": next(answers)}})

    return httpx.Client(transport=httpx.MockTransport(handle))


def test_the_ollama_request_forces_json_with_thinking_off():
    seen: list[dict] = []
    reader = OllamaReader("http://gpu:11434", "qwen3-vl:8b-q4_K_M", client=ollama(['{"total": "12.00"}'], seen))
    assert reader.read(PNG, "image/png").total == "12.00"
    body = seen[0]
    assert (body["model"], body["stream"], body["think"], body["options"]["temperature"]) == ("qwen3-vl:8b-q4_K_M", False, False, 0)
    assert body["format"] == Reading.model_json_schema()
    assert body["messages"][0]["images"] == [base64.b64encode(PNG).decode()]


def test_unreadable_output_is_retried_once_then_blank_and_logged(caplog):
    seen: list[dict] = []
    reader = OllamaReader("http://gpu:11434", "m", client=ollama(["not json", '{"total": 3}'], seen))
    assert reader.read(PNG, "image/png") == Reading()
    assert len(seen) == 2
    assert "try 1 of 2" in caplog.text and "try 2 of 2" in caplog.text and "not json" in caplog.text


def test_the_reader_comes_from_settings(monkeypatch):
    monkeypatch.delenv("FLAG_IT_READER_MODEL", raising=False)
    monkeypatch.setenv("FLAG_IT_OLLAMA_URL", "http://gpu:11434")
    reader = reader_from_env()
    assert (reader.base_url, reader.model_tag) == ("http://gpu:11434", DEFAULT_MODEL)
