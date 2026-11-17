"""Normalization: a raw row's text fields become a typed NormalizedTransaction. Pure: no I/O.

Bump NORMALIZER_VERSION whenever some input would normalize differently. Each normalized row keeps
the version that produced it, so re-normalizing adds a row instead of editing one.
"""

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from uuid import UUID

from pydantic import ValidationError

from flag_it.contracts.transactions import NormalizedTransaction, RawTransaction

NORMALIZER_VERSION = "1"

DATE_FORMATS = ("%d-%b-%y", "%Y-%m-%d")  # the state export, and ISO for API clients
CENT = Decimal("0.01")
_PLAIN_DECIMAL = re.compile(r"[+-]?\d+(\.\d+)?")  # no exponents ("1e30"), no NaN or Infinity

# Merchant cleanup, ported from canon_merchant in data_exploration/ok_pcard_exploration.ipynb.
_PROCESSOR_PREFIX = re.compile(r"^(SQ|TST|PP|PAYPAL|SP|GOOGLE)\s?\*\s?")
_AIRLINES = {"AMERICAN": ("AMERICAN AIRLINES", "AMERICAN AIR"), "UNITED": ("UNITED AIRLINES", "UNITED AIR")}
_BRANDS = [
    (r"^(AMAZON|AMZN)", "AMAZON"),
    (r"^(WAL-?MART|WM SUPERCENTER|WALMART|WM )", "WALMART"),
    (r"^LOWES", "LOWES"),
    (r"^(THE )?HOME DEPOT", "HOME DEPOT"),
    (r"^SAMS ?CLUB|^SAMSCLUB", "SAMS CLUB"),
    (r"^(AT&T|ATT )", "ATT"),
    (r"^SOUTHWES", "SOUTHWEST AIR"),
    (r"^DELTA AIR", "DELTA AIR"),
    (r"^HOLIDAY INN", "HOLIDAY INN"),
    (r"^HAMPTON", "HAMPTON INN"),
    (r"^HILTON", "HILTON"),
    (r"^MARRIOTT|^COURTYARD|^RESIDENCE INN|^FAIRFIELD", "MARRIOTT"),
    (r"^UBER", "UBER"),
    (r"^OFFICE DEPOT", "OFFICE DEPOT"),
    (r"^(TFS|FISHER)", "FISHER SCI"),
    (r"^FEDEX|^FED EX", "FEDEX"),
]


class NormalizationError(ValueError):
    """A raw row that can't be normalized. `errors` holds one (field, message) pair per problem."""

    def __init__(self, errors: list[tuple[str, str]]):
        self.errors = tuple(errors)
        super().__init__("; ".join(f"{field}: {message}" for field, message in self.errors))


def parse_amount(text: str) -> Decimal:
    text = text.strip()
    if not _PLAIN_DECIMAL.fullmatch(text):
        raise ValueError("not a number")
    value = Decimal(text)
    try:
        rounded = value.quantize(CENT)
    except InvalidOperation:  # more digits than Decimal's precision: no real charge is that large
        raise ValueError("too large") from None
    if value != rounded:
        raise ValueError("has fractions of a cent")
    return rounded


def parse_date(text: str) -> date:
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text.strip(), fmt).date()
        except ValueError:
            continue
    raise ValueError("not a date (expected dd-MON-yy or YYYY-MM-DD)")


def merchant_norm(merchant: str, mcc_description: str) -> str:
    """A cleaned merchant name, used to group charges: processor prefixes and reference numbers
    removed, big brands collapsed to one name, otherwise the first two words."""
    name = _PROCESSOR_PREFIX.sub("", merchant.strip().upper())
    mcc = " ".join(mcc_description.upper().split())
    for first_word, (airline_mcc, canonical) in _AIRLINES.items():
        if name.startswith(first_word) and mcc == airline_mcc:
            return canonical
    for pattern, canonical in _BRANDS:
        if re.match(pattern, name):
            return canonical
    words = [w for w in re.sub(r"[^A-Z0-9& ]", " ", name).split() if not any(c.isdigit() for c in w)]
    if words:
        return " ".join(words[:2])
    return " ".join(name.split()) or merchant.strip()


def normalize(raw: RawTransaction, txn_id: UUID) -> NormalizedTransaction:
    """Raises NormalizationError listing every field that is missing or can't be read."""
    errors: list[tuple[str, str]] = []

    def text(field: str, *, required: bool = True) -> str | None:
        value = getattr(raw, field)
        if value is None or not value.strip():
            if required:
                errors.append((field, "required"))
            return None
        return value.strip()

    def parsed(field: str, parse):
        value = text(field)
        if value is None:
            return None
        try:
            return parse(value)
        except ValueError as error:
            errors.append((field, str(error)))
            return None

    agency = text("agencynbr")
    last_name = text("last_name")
    last_letters = re.sub(r"[^A-Z]", "", last_name.upper()) if last_name else ""
    if last_name and not last_letters:
        errors.append(("last_name", "has no letters"))
    initial = (raw.first_initial or "").strip().upper()
    merchant = text("merchant_name")
    mcc_description = text("mcc_description")
    amount = parsed("amount", parse_amount)
    transaction_date = parsed("transaction_date", parse_date)
    post_date = parsed("post_date", parse_date)
    mcc_code = text("mcc_code", required=False)
    if mcc_code is not None and not re.fullmatch(r"\d{4}", mcc_code):
        errors.append(("mcc_code", "not a 4-digit code"))
    if errors:
        raise NormalizationError(errors)

    try:
        return NormalizedTransaction(
            txn_id=txn_id,
            raw_id=raw.raw_id,
            agency_id=agency,
            cardholder_id=f"{agency}|{last_letters}|{initial}",
            merchant_norm=merchant_norm(merchant, mcc_description),
            mcc_description=mcc_description,
            mcc_code=mcc_code,
            amount=amount,
            transaction_date=transaction_date,
            post_date=post_date,
            business_purpose=text("business_purpose", required=False),
            normalizer_version=NORMALIZER_VERSION,
        )
    except ValidationError as error:
        raise NormalizationError(
            [(str(e["loc"][0]) if e["loc"] else "item", e["msg"]) for e in error.errors()]
        ) from None
