from decimal import Decimal

import pytest
from pydantic import ValidationError

from flag_it.contracts.common import (
    CONTRACT_VERSION,
    CheckId,
    EscalationReason,
    IncompatibleContractVersion,
    InputModel,
    Money,
    RecordModel,
    RuleId,
    UnitInterval,
    check_belongs_to_rule,
    ensure_compatible,
    major,
    require_version,
)
from flag_it.contracts.enums import Route


class _Sample(InputModel):
    amount: Money
    score: UnitInterval
    rule_id: RuleId
    check_id: CheckId


class _Record(RecordModel):
    amount: Money
    reasons: tuple[EscalationReason, ...] = ()


def _sample(**over):
    data = {"amount": "412.00", "score": 0.5, "rule_id": "OSU-LIM-01", "check_id": "OSU-LIM-01a"}
    return _Sample(**(data | over))


def test_money_accepts_strings_and_rejects_floats():
    assert _sample(amount="412.00").amount == Decimal("412.00")
    with pytest.raises(ValidationError, match="must not be a float"):
        _sample(amount=412.0)


def test_money_rejects_more_than_two_decimal_places_and_non_finite():
    for bad in ("1.005", "NaN", "Infinity"):
        with pytest.raises(ValidationError):
            _sample(amount=bad)


def test_unit_interval_bounds():
    with pytest.raises(ValidationError):
        _sample(score=1.01)
    with pytest.raises(ValidationError):
        _sample(score=-0.01)


def test_check_belongs_to_rule():
    assert check_belongs_to_rule("OSU-LIM-01", "OSU-LIM-01a")
    assert not check_belongs_to_rule("OSU-LIM-01", "OSU-LIM-012")
    assert not check_belongs_to_rule("OSU-LIM-01", "OSU-LIM-02a")


def test_rule_and_check_id_patterns():
    with pytest.raises(ValidationError):
        _sample(rule_id="osu-lim-01")
    with pytest.raises(ValidationError):
        _sample(check_id="OSU-LIM-01")  # missing the check letter


def test_input_models_reject_unknown_fields_and_are_frozen():
    with pytest.raises(ValidationError) as excinfo:
        _sample(surprise=1)
    assert excinfo.value.errors()[0]["type"] == "extra_forbidden"
    sample = _sample()
    with pytest.raises(ValidationError):
        sample.score = 0.9


def test_record_models_ignore_unknown_fields_and_are_frozen():
    # A reader on an older minor version must still read a record with a new optional field.
    record = _Record(amount="1.00", added_in_a_later_minor_version="x")
    assert not hasattr(record, "added_in_a_later_minor_version")
    with pytest.raises(ValidationError):
        record.amount = "2.00"


def test_escalation_reasons_are_a_fixed_list():
    ok = ("unsure:OSU-TRV-13b", "low_confidence:OSU-TRV-13b", "citation_unresolved",
          "invalid_output", "agent_failed", "review_conflict")
    assert _Record(amount="1.00", reasons=ok).reasons == ok
    for bad in ("unsure", "unsure:OSU-TRV-13", "something_else"):
        with pytest.raises(ValidationError):
            _Record(amount="1.00", reasons=(bad,))


def test_version_helpers():
    assert major("2.4.1") == 2
    ensure_compatible(CONTRACT_VERSION)
    ensure_compatible(f"{major(CONTRACT_VERSION)}.99.7")  # same major: compatible
    with pytest.raises(IncompatibleContractVersion):
        ensure_compatible(f"{major(CONTRACT_VERSION) + 1}.0.0")
    with pytest.raises(IncompatibleContractVersion):
        ensure_compatible("not-a-version")


def test_require_version_needs_a_stamp():
    require_version({"contract_version": CONTRACT_VERSION})
    with pytest.raises(IncompatibleContractVersion):
        require_version({})


def test_enum_values_match_contract():
    assert [r.value for r in Route] == [
        "flag", "auto_approve", "agent_approve", "agent_flag", "human_review",
    ]
