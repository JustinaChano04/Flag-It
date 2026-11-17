"""Score receipt reader models on a labeled set (see "Receipt reader bake-off" in docs/tech-stack.md).

    python -m flag_it.understand.receipts.bakeoff --labels receipts/labels.json \\
        --model qwen3-vl:8b-q4_K_M --model qwen2.5vl:7b --ollama-url http://gpu:11434

labels.json is a list of {"file", "total", "receipt_date", "merchant"}, with file paths relative to it
and null for a value the receipt doesn't show. Prints one JSON report per model. Record the exact
model tag and quantization with every result.

Measured here: exact field accuracy, honest blanks (of the answers that weren't right, how many were
left empty rather than wrong), and arithmetic (subtotal + tax + tip = total). Line-item recall, the
split by receipt condition, and agreement with the card transaction need richer labels and are left
to the bake-off notebook.
"""

import argparse
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from flag_it.understand.receipts.matching import canon_merchant
from flag_it.understand.receipts.reader import OllamaReader, ReceiptReader, to_fields

CONTENT_TYPES = {".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}
FIELDS = ("total", "receipt_date", "merchant")


@dataclass(frozen=True)
class Case:
    path: Path
    content_type: str
    total: Decimal | None
    receipt_date: date | None
    merchant: str | None


def load_cases(labels: Path) -> list[Case]:
    cases = []
    for entry in json.loads(labels.read_text()):
        path = labels.parent / entry["file"]
        cases.append(
            Case(
                path=path,
                content_type=CONTENT_TYPES[path.suffix.lower()],
                total=Decimal(entry["total"]) if entry.get("total") is not None else None,
                receipt_date=date.fromisoformat(entry["receipt_date"]) if entry.get("receipt_date") else None,
                merchant=entry.get("merchant"),
            )
        )
    return cases


def _same(field: str, expected: Any, got: Any) -> bool:
    if field == "merchant":
        return canon_merchant(expected) == canon_merchant(got)
    return expected == got


def score(reader: ReceiptReader, cases: Sequence[Case]) -> dict[str, Any]:
    counts = {field: {"right": 0, "wrong": 0, "blank": 0} for field in FIELDS}
    arithmetic = {"checked": 0, "consistent": 0}
    for case in cases:
        fields = to_fields(reader.read(case.path.read_bytes(), case.content_type))
        for field in FIELDS:
            expected, got = getattr(case, field), fields[field]
            if expected is None:
                continue  # nothing to compare against
            outcome = "blank" if got is None else "right" if _same(field, expected, got) else "wrong"
            counts[field][outcome] += 1
        if fields["subtotal"] is not None and fields["total"] is not None:
            arithmetic["checked"] += 1
            parts = fields["subtotal"] + (fields["tax"] or 0) + (fields["tip"] or 0)
            arithmetic["consistent"] += parts == fields["total"]
    blank = sum(c["blank"] for c in counts.values())
    not_right = blank + sum(c["wrong"] for c in counts.values())
    return {
        "model": reader.model_tag,
        "cases": len(cases),
        "fields": counts,
        "honest_blank_rate": blank / not_right if not_right else None,
        "arithmetic": arithmetic,
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m flag_it.understand.receipts.bakeoff")
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--model", action="append", required=True, help="an Ollama model tag; repeat to compare")
    parser.add_argument("--ollama-url", default="http://localhost:11434")
    args = parser.parse_args(argv)
    cases = load_cases(args.labels)
    for model in args.model:
        print(json.dumps(score(OllamaReader(args.ollama_url, model), cases)))


if __name__ == "__main__":
    main()
