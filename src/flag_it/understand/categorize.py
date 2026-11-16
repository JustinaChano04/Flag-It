"""The lookup categorizer: the MCC description decides the spend category.

The lookup file maps each MCC description seen in the OSU data to a category display name from the
rules YAML and a confidence label. It is a copy of data_exploration/mcc_to_category.csv; edit this
copy, and the lookup version (a hash of the file) changes with it.
"""

import csv
import hashlib
import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from flag_it.contracts.enums import CategoryMethod
from flag_it.contracts.rules import RuleSet
from flag_it.contracts.transactions import NormalizedTransaction
from flag_it.contracts.understand import CategoryResult

LOOKUP_PATH = Path(__file__).with_name("mcc_to_category.csv")
FALLBACK_CATEGORY = "other_unclear"

# How sure the lookup is, by the label in the file. "unmapped" rows are MCCs no rule covers yet.
CONFIDENCE = {"high": 0.9, "medium": 0.7, "low": 0.5, "unmapped": 0.0}


def mcc_key(text: str) -> str:
    """The lookup key: upper case, punctuation as spaces, runs of spaces collapsed.

    The export writes "EATING PLACES  RESTAURANTS"; other sources may write "EATING PLACES, RESTAURANTS".
    """
    return " ".join(re.sub(r"[^A-Z0-9&]", " ", text.upper()).split())


@dataclass(frozen=True)
class MccLookup:
    version: str
    entries: Mapping[str, tuple[str, float]]  # mcc_key -> (category ID, confidence)

    def get(self, mcc_description: str) -> tuple[str, float] | None:
        return self.entries.get(mcc_key(mcc_description))


def load_lookup(rules: RuleSet, path: Path = LOOKUP_PATH) -> MccLookup:
    """Reads the lookup file and checks every row against the rules YAML's categories."""
    ids_by_name = {name: category_id for category_id, name in rules.categories.items()}
    content = path.read_bytes()
    entries: dict[str, tuple[str, float]] = {}
    for line, row in enumerate(csv.DictReader(content.decode("utf-8-sig").splitlines()), start=2):
        name, label = row["category"].strip(), row["confidence"].strip()
        if name not in ids_by_name:
            raise ValueError(f"{path.name} line {line}: {name!r} is not a category in the rules YAML")
        if label not in CONFIDENCE:
            raise ValueError(f"{path.name} line {line}: unknown confidence {label!r}; use one of {sorted(CONFIDENCE)}")
        key, entry = mcc_key(row["MCC_DESCRIPTION"]), (ids_by_name[name], CONFIDENCE[label])
        if entries.get(key, entry) != entry:
            raise ValueError(f"{path.name} line {line}: two rows for {key!r} disagree")
        entries[key] = entry
    version = "lookup-" + hashlib.sha256(content).hexdigest()[:12]
    return MccLookup(version=version, entries=entries)


log = logging.getLogger(__name__)


def categorize(txn: NormalizedTransaction, lookup: MccLookup) -> CategoryResult:
    found = lookup.get(txn.mcc_description)
    if found is None:  # logged so new MCCs get added to the lookup instead of staying unclear
        log.warning("MCC %r is not in lookup %s: categorized as %s", txn.mcc_description, lookup.version, FALLBACK_CATEGORY)
    category, confidence = found or (FALLBACK_CATEGORY, 0.0)
    return CategoryResult(
        txn_id=txn.txn_id,
        model_version=lookup.version,
        category=category,
        confidence=confidence,
        method=CategoryMethod.LOOKUP,
    )
