from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

import hashlib

from flag_it.contracts.enums import CheckMethod
from flag_it.contracts.rules import DEFAULT_RULES_PATH, UnknownParamError, default_rules_path, load_rules


@pytest.fixture(scope="module")
def rules():
    return load_rules(DEFAULT_RULES_PATH)


def _write(tmp_path: Path, data: dict) -> Path:
    path = tmp_path / "rules.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    return path


def _minimal() -> dict:
    return {
        "policy": {"name": "Test", "version": "1", "source_file": "x.pdf", "scope": "test"},
        "categories": {"lodging": "Lodging"},
        "rules": [
            {
                "id": "T-LIM-01",
                "title": "Limit",
                "topic": "limits",
                "text": "At most 10.",
                "source": {"section": "S", "page": 1},
                "severity": "prohibited",
                "applies_to": ["all"],
                "params": {"max_amount": 10},
                "checks": [
                    {
                        "id": "T-LIM-01a",
                        "ask": "Amount is at most max_amount",
                        "pattern": "threshold",
                        "method": "code",
                        "requires": ["transaction"],
                        "scope": "transaction",
                    }
                ],
            }
        ],
    }


def test_real_rules_file_loads_every_rule_and_check(rules):
    # Compare with the raw YAML, not fixed numbers, so editing the policy file doesn't break this.
    raw = yaml.safe_load(DEFAULT_RULES_PATH.read_text())
    assert len(rules.rules) == len(raw["rules"])
    raw_checks = [c for r in raw["rules"] for c in r["checks"]]
    checks = [c for r in rules.rules for c in r.checks]
    assert len(checks) == len(raw_checks)
    assert sum(c.method is CheckMethod.LLM for c in checks) == sum(c["method"] == "llm" for c in raw_checks)


def test_rules_version_is_policy_version_plus_file_hash(rules, tmp_path):
    digest = hashlib.sha256(DEFAULT_RULES_PATH.read_bytes()).hexdigest()[:12]
    assert rules.rules_version == f"{rules.policy.version}+{digest}"
    first = load_rules(_write(tmp_path, _minimal())).rules_version
    data = _minimal()
    data["rules"][0]["text"] = "At most 11."
    assert load_rules(_write(tmp_path, data)).rules_version != first


def test_lookups(rules):
    rule, check = rules.check("OSU-LIM-01a")
    assert rule.id == "OSU-LIM-01"
    assert rule.param("max_single_transaction") == 10000
    with pytest.raises(UnknownParamError):
        rule.param("max_single_transacton")


def test_has_category(rules):
    assert rules.has_category("lodging")
    assert not rules.has_category("hotels")


def test_checks_for_includes_rules_that_apply_to_all(rules):
    code_checks = rules.checks_for("lodging", CheckMethod.CODE)
    assert ("OSU-LIM-01", "OSU-LIM-01a") in {(r.id, c.id) for r, c in code_checks}


def test_rules_path_can_be_overridden(monkeypatch, tmp_path):
    monkeypatch.setenv("FLAG_IT_RULES_PATH", str(tmp_path / "x.yaml"))
    assert default_rules_path() == tmp_path / "x.yaml"


@pytest.mark.parametrize("text", ["", "- just a list\n", "policy: {}\n"])
def test_malformed_files_raise_validation_errors(tmp_path, text):
    path = tmp_path / "rules.yaml"
    path.write_text(text)
    with pytest.raises(ValidationError):
        load_rules(path)


@pytest.mark.parametrize("where", ["rule", "policy"])
def test_unknown_keys_are_rejected_on_rules_and_policy(tmp_path, where):
    data = _minimal()
    target = data["rules"][0] if where == "rule" else data["policy"]
    target["threshold"] = 10
    with pytest.raises(ValidationError, match="threshold"):
        load_rules(_write(tmp_path, data))


def test_unknown_key_is_rejected(tmp_path):
    data = _minimal()
    data["rules"][0]["checks"][0]["threshold"] = 10
    with pytest.raises(ValidationError, match="threshold"):
        load_rules(_write(tmp_path, data))


def test_check_id_must_extend_rule_id(tmp_path):
    data = _minimal()
    data["rules"][0]["checks"][0]["id"] = "T-LIM-02a"
    with pytest.raises(ValidationError, match="T-LIM-02a"):
        load_rules(_write(tmp_path, data))


def test_applies_to_must_name_a_category(tmp_path):
    data = _minimal()
    data["rules"][0]["applies_to"] = ["hotels"]
    with pytest.raises(ValidationError, match="hotels"):
        load_rules(_write(tmp_path, data))


def test_when_must_reference_an_existing_check(tmp_path):
    data = _minimal()
    data["rules"][0]["checks"][0]["when"] = {"check": "T-LIM-01z", "result": True}
    with pytest.raises(ValidationError, match="T-LIM-01z"):
        load_rules(_write(tmp_path, data))


def test_llm_checks_need_purpose_and_decision(tmp_path):
    data = _minimal()
    data["rules"][0]["checks"][0]["method"] = "llm"
    with pytest.raises(ValidationError, match="llm"):
        load_rules(_write(tmp_path, data))


def test_retired_rules_are_skipped_by_checks_for(tmp_path):
    data = _minimal()
    data["rules"][0]["status"] = "retired"
    rules = load_rules(_write(tmp_path, data))
    assert rules.checks_for("lodging", CheckMethod.CODE) == []
