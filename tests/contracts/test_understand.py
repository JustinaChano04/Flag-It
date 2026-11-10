import pytest
from pydantic import ValidationError

from flag_it.contracts.enums import LineType
from flag_it.contracts.examples import anomaly, category, receipt


def test_receipt_fields_may_be_empty_when_unreadable():
    r = receipt(merchant=None, total=None, line_items=[], match_status="unmatched")
    assert r.total is None
    assert r.line_items == ()


def test_receipt_line_item_defaults_to_item_type():
    assert receipt().line_items[0].line_type is LineType.ITEM


def test_category_confidence_is_bounded():
    with pytest.raises(ValidationError):
        category(confidence=1.5)


def test_anomaly_score_required_when_scored():
    with pytest.raises(ValidationError, match="score"):
        anomaly(score=None)


def test_anomaly_score_empty_when_history_is_insufficient():
    assert anomaly(status="insufficient_history", score=None, history_length=2).score is None
    with pytest.raises(ValidationError, match="score"):
        anomaly(status="insufficient_history", score=0.0)
