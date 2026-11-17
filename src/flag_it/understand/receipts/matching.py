"""Receipt matching. In v1 every receipt is uploaded against a known transaction, so matching only
verifies it: total, date, and merchant must each be within tolerance.

- unmatched: the total is unreadable, or both the date and the merchant are.
- mismatch: a readable field is outside its tolerance. A mismatch is a finding.
- matched: every readable field is within tolerance.
"""

import re
from collections.abc import Mapping
from decimal import Decimal
from difflib import SequenceMatcher
from pathlib import Path
from typing import Annotated, Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

from flag_it.contracts.enums import MatchStatus
from flag_it.contracts.transactions import NormalizedTransaction

CONFIG_PATH = Path(__file__).with_name("matching.yaml")


class MatchConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    total_tolerance: Annotated[Decimal, Field(ge=0)]
    date_tolerance_days: Annotated[int, Field(ge=0)]
    merchant_min_similarity: Annotated[float, Field(gt=0, le=1)]


def load_match_config(path: Path = CONFIG_PATH) -> MatchConfig:
    return MatchConfig.model_validate(yaml.safe_load(path.read_text()))


def canon_merchant(name: str) -> str:
    """Upper case, punctuation removed, spaces collapsed: "Joe's Cafe" -> "JOES CAFE"."""
    return " ".join(re.sub(r"[^A-Z0-9 ]", "", name.upper().replace("&", " ")).split())


def merchant_similarity(a: str, b: str) -> float:
    a, b = canon_merchant(a), canon_merchant(b)
    if not a or not b:
        return 0.0
    if a in b or b in a:
        return 1.0
    return SequenceMatcher(None, a, b).ratio()


def match(fields: Mapping[str, Any], txn: NormalizedTransaction, config: MatchConfig) -> MatchStatus:
    """`fields` is to_fields' output: typed values, None where unreadable."""
    total, when, merchant = fields["total"], fields["receipt_date"], fields["merchant"]
    if total is None or (when is None and merchant is None):
        return MatchStatus.UNMATCHED
    charged, tip = abs(txn.amount), fields.get("tip")

    def near(value):
        return abs(abs(value) - charged) <= config.total_tolerance

    # A tip may be written in after the total prints, so total plus tip also counts.
    if not (near(total) or (tip is not None and near(abs(total) + abs(tip)))):
        return MatchStatus.MISMATCH
    if when is not None and abs((when - txn.transaction_date).days) > config.date_tolerance_days:
        return MatchStatus.MISMATCH
    if merchant is not None and merchant_similarity(merchant, txn.merchant_norm) < config.merchant_min_similarity:
        return MatchStatus.MISMATCH
    return MatchStatus.MATCHED
