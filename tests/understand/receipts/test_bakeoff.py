"""The bake-off scores a reader on labeled receipts: exact fields, honest blanks, and arithmetic."""

import json
from datetime import date
from decimal import Decimal

from flag_it.understand.receipts.bakeoff import Case, load_cases, score
from flag_it.understand.receipts.reader import LineReading, Reading, StaticReader


def cases(tmp_path) -> list[Case]:
    (tmp_path / "a.png").write_bytes(b"\x89PNG a")
    (tmp_path / "b.pdf").write_bytes(b"%PDF b")
    labels = [
        {"file": "a.png", "total": "412.00", "receipt_date": "2025-01-14", "merchant": "Joe's Cafe"},
        {"file": "b.pdf", "total": "20.00", "receipt_date": None, "merchant": "Hampton Inn"},
    ]
    (tmp_path / "labels.json").write_text(json.dumps(labels))
    return load_cases(tmp_path / "labels.json")


def test_cases_load_with_typed_labels_and_content_types(tmp_path):
    loaded = cases(tmp_path)
    assert [(c.path.name, c.content_type) for c in loaded] == [("a.png", "image/png"), ("b.pdf", "application/pdf")]
    assert (loaded[0].total, loaded[0].receipt_date, loaded[1].receipt_date) == (Decimal("412.00"), date(2025, 1, 14), None)


def test_a_reader_is_scored_per_field(tmp_path):
    reading = Reading(
        merchant="JOES CAFE", receipt_date="2025-01-14", subtotal="400.00", tax="12.00", total="412.00",
        line_items=[LineReading(amount="400.00")],
    )
    report = score(StaticReader("fake-1", reading), cases(tmp_path))
    assert (report["model"], report["cases"]) == ("fake-1", 2)
    # Case a: all three right. Case b: total and merchant wrong; its date has no label, so it isn't scored.
    assert report["fields"]["total"] == {"right": 1, "wrong": 1, "blank": 0}
    assert report["fields"]["receipt_date"] == {"right": 1, "wrong": 0, "blank": 0}
    assert report["fields"]["merchant"] == {"right": 1, "wrong": 1, "blank": 0}
    assert report["arithmetic"] == {"checked": 2, "consistent": 2}


def test_blanks_are_counted_apart_from_wrong_answers(tmp_path):
    report = score(StaticReader("fake-blank", Reading()), cases(tmp_path))
    assert report["fields"]["total"] == {"right": 0, "wrong": 0, "blank": 2}
    assert report["honest_blank_rate"] == 1.0
    assert report["arithmetic"] == {"checked": 0, "consistent": 0}
