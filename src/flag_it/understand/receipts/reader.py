"""The receipt reader: a vision model reads a receipt image into text fields, and to_fields types them.

The model's output schema is all text (Reading), so a misread amount can't arrive as a float, and
anything to_fields can't parse is left empty. An empty value is better than a confident wrong one.
The model is a setting, chosen by the bake-off (see docs/tech-stack.md).
"""

import base64
import io
import logging
import os
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol

import httpx
import pypdfium2 as pdfium
from PIL import Image
from pydantic import BaseModel, ConfigDict, ValidationError

from flag_it.contracts.enums import LineType
from flag_it.contracts.understand import ReceiptLineItem

DEFAULT_MODEL = "qwen3-vl:8b-q4_K_M"
MAX_PAGES = 3
MAX_PIXELS = 25_000_000  # per image sent to the model; larger pages are rendered smaller
CENT = Decimal("0.01")
MONEY_LIMIT = Decimal("1e10")  # Money holds 12 digits, 2 after the point
DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y")

PROMPT = """Read this receipt. Return JSON only, in the given schema.
- merchant: the business name as printed.
- receipt_date: the purchase date as YYYY-MM-DD.
- subtotal, tax, tip, total: amounts as text such as "12.34", without currency signs.
- line_items: one entry per printed line, with line_type one of item, tax, tip, fee, room, other.
Leave a field null if you cannot read it clearly. Never guess."""


class LineReading(BaseModel):
    model_config = ConfigDict(extra="ignore")

    description: str | None = None
    quantity: str | None = None
    unit_price: str | None = None
    amount: str | None = None
    line_type: str | None = None


class Reading(BaseModel):
    """What the model wrote, as text. Also the JSON schema the model is forced to follow."""

    model_config = ConfigDict(extra="ignore")

    merchant: str | None = None
    receipt_date: str | None = None
    subtotal: str | None = None
    tax: str | None = None
    tip: str | None = None
    total: str | None = None
    line_items: list[LineReading] = []


def _money(text: str | None) -> Decimal | None:
    if text is None:
        return None
    try:
        value = Decimal(re.sub(r"[$,\s]", "", text))
        if not value.is_finite() or abs(value) >= MONEY_LIMIT or value != value.quantize(CENT):
            return None
        return value.quantize(CENT)
    except InvalidOperation:
        return None


def _quantity(text: str | None) -> Decimal | None:
    if text is None:
        return None
    try:
        value = Decimal(text.strip())
        return value.quantize(Decimal("0.001")) if value.is_finite() and abs(value) < Decimal("1e9") else None
    except InvalidOperation:
        return None


def _date(text: str | None) -> date | None:
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime((text or "").strip(), fmt).date()
        except ValueError:
            continue
    return None


def _line_type(text: str | None) -> LineType:
    if text is None:
        return LineType.ITEM
    try:
        return LineType(text.strip().lower())
    except ValueError:
        return LineType.OTHER


def to_fields(reading: Reading) -> dict[str, Any]:
    """Typed receipt fields for ReceiptExtraction. Anything unparseable is None."""
    return {
        "merchant": (reading.merchant or "").strip() or None,
        "receipt_date": _date(reading.receipt_date),
        "subtotal": _money(reading.subtotal),
        "tax": _money(reading.tax),
        "tip": _money(reading.tip),
        "total": _money(reading.total),
        "line_items": tuple(
            ReceiptLineItem(
                description=(line.description or "").strip() or None,
                quantity=_quantity(line.quantity),
                unit_price=_money(line.unit_price),
                amount=_money(line.amount),
                line_type=_line_type(line.line_type),
            )
            for line in reading.line_items
        ),
    }


class ReceiptReader(Protocol):
    model_tag: str

    def read(self, content: bytes, content_type: str) -> Reading: ...


class StaticReader:
    """Returns the same reading for every file. For tests."""

    def __init__(self, model_tag: str, reading: Reading):
        self.model_tag, self.reading = model_tag, reading

    def read(self, content: bytes, content_type: str) -> Reading:
        return self.reading


log = logging.getLogger(__name__)


class UnreadableFile(ValueError):
    """The uploaded bytes can't be decoded as their type, or the image is too large to send."""


def to_images(content: bytes, content_type: str) -> list[bytes]:
    """Images the model can see: JPEG and PNG as they are, the first MAX_PAGES pages of a PDF as PNG.
    Raises UnreadableFile for bytes that don't decode, or an image over MAX_PIXELS."""
    if content_type in ("image/jpeg", "image/png"):
        try:
            with Image.open(io.BytesIO(content)) as image:
                width, height = image.size
                image.verify()
        except Exception as error:  # Pillow raises many types for bad input
            raise UnreadableFile(f"not a readable {content_type}: {error}") from None
        if width * height > MAX_PIXELS:
            raise UnreadableFile(f"image is {width}x{height}, over {MAX_PIXELS} pixels")
        return [content]
    if content_type != "application/pdf":
        raise ValueError(f"unsupported receipt type {content_type!r}")
    try:
        pdf = pdfium.PdfDocument(content)
    except pdfium.PdfiumError as error:
        raise UnreadableFile(f"not a readable PDF: {error}") from None
    images = []
    for index in range(min(len(pdf), MAX_PAGES)):
        page = pdf[index]
        width, height = page.get_size()
        scale = min(2.0, (MAX_PIXELS / max(width * height, 1.0)) ** 0.5)  # 2x, unless the page is huge
        buffer = io.BytesIO()
        page.render(scale=scale).to_pil().save(buffer, format="PNG")
        images.append(buffer.getvalue())
    return images


class OllamaReader:
    """A vision model served by Ollama, with thinking off and the output forced to Reading's schema."""

    def __init__(self, base_url: str, model_tag: str, client: httpx.Client | None = None, timeout: float = 120.0):
        self.base_url, self.model_tag, self.timeout = base_url.rstrip("/"), model_tag, timeout
        self.client = client or httpx.Client()

    def read(self, content: bytes, content_type: str) -> Reading:
        """Raises httpx errors (the job is retried). Unreadable output twice gives a blank reading."""
        images = [base64.b64encode(image).decode() for image in to_images(content, content_type)]
        body = {
            "model": self.model_tag,
            "stream": False,
            "think": False,
            "format": Reading.model_json_schema(),
            "options": {"temperature": 0},
            "messages": [{"role": "user", "content": PROMPT, "images": images}],
        }
        for attempt in (1, 2):
            response = self.client.post(f"{self.base_url}/api/chat", json=body, timeout=self.timeout)
            response.raise_for_status()
            try:
                return Reading.model_validate_json(response.json()["message"]["content"])
            except (ValidationError, KeyError, TypeError, ValueError) as error:
                # Kept in the log so a blank reading can later be told apart from a blank receipt.
                log.warning("%s gave unreadable output (try %d of 2): %s. Response began: %.500r",
                            self.model_tag, attempt, error, response.text)
        return Reading()


def reader_from_env() -> OllamaReader:
    return OllamaReader(
        os.environ.get("FLAG_IT_OLLAMA_URL", "http://localhost:11434"),
        os.environ.get("FLAG_IT_READER_MODEL", DEFAULT_MODEL),
    )
