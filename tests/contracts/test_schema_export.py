"""JSON Schema export and the CONTRACT_VERSION guard."""

import json

import pytest

from flag_it.contracts import SCHEMA_MODELS
from flag_it.contracts import schema_export
from flag_it.contracts.common import CONTRACT_VERSION


def _manifest(path):
    return json.loads((path / "manifest.json").read_text())


def _rewrite_manifest(path, **changes):
    manifest = _manifest(path) | changes
    (path / "manifest.json").write_text(json.dumps(manifest))


# Fails when a model changed but the schema files weren't regenerated.
def test_committed_schemas_are_current():
    assert schema_export.check() == []


def test_every_model_has_a_schema_file():
    files = schema_export.generate()
    assert set(files) == {f"{name}.json" for name in SCHEMA_MODELS}


def test_records_export_money_as_a_string():
    schema = json.loads(schema_export.generate()["NormalizedTransaction.json"])
    assert schema["properties"]["amount"]["type"] == "string"


def test_init_then_check_is_clean(tmp_path):
    schema_export.write(tmp_path, init=True)
    assert schema_export.check(tmp_path) == []
    assert _manifest(tmp_path)["contract_version"] == CONTRACT_VERSION


def test_write_refuses_changed_schemas_without_a_version_bump(tmp_path):
    schema_export.write(tmp_path, init=True)
    _rewrite_manifest(tmp_path, fingerprint="0" * 64)  # pretend the committed schemas were different
    with pytest.raises(SystemExit, match="CONTRACT_VERSION did not"):
        schema_export.write(tmp_path)


def test_write_accepts_changed_schemas_after_a_version_bump(tmp_path):
    schema_export.write(tmp_path, init=True)
    _rewrite_manifest(tmp_path, fingerprint="0" * 64, contract_version="0.9.0")
    schema_export.write(tmp_path)
    assert _manifest(tmp_path)["contract_version"] == CONTRACT_VERSION
    assert schema_export.check(tmp_path) == []


def test_write_refuses_when_the_manifest_was_deleted(tmp_path):
    schema_export.write(tmp_path, init=True)
    (tmp_path / "manifest.json").unlink()
    with pytest.raises(SystemExit, match="manifest"):
        schema_export.write(tmp_path)


def test_check_reports_stale_missing_and_extra_files(tmp_path):
    schema_export.write(tmp_path, init=True)
    (tmp_path / "Flag.json").write_text("{}\n")
    (tmp_path / "DecisionRun.json").unlink()
    (tmp_path / "Leftover.json").write_text("{}\n")
    problems = schema_export.check(tmp_path)
    assert "out of date: Flag.json" in problems
    assert "missing DecisionRun.json" in problems
    assert "no model for Leftover.json" in problems


def test_check_reports_a_manifest_version_mismatch(tmp_path):
    schema_export.write(tmp_path, init=True)
    _rewrite_manifest(tmp_path, contract_version="0.0.1")
    assert any("manifest.json has version" in p for p in schema_export.check(tmp_path))


# Mirrors CI: changed schemas need a version higher than main's.
def test_check_against_main_needs_a_higher_version_when_schemas_changed(tmp_path):
    schema_export.write(tmp_path, init=True)
    current = _manifest(tmp_path)
    same_version = {"contract_version": CONTRACT_VERSION, "fingerprint": "0" * 64}
    lower_version = {"contract_version": "0.1.0", "fingerprint": "0" * 64}
    assert any("not higher than main" in p for p in schema_export.check(tmp_path, base_manifest=same_version))
    assert schema_export.check(tmp_path, base_manifest=lower_version) == []
    assert schema_export.check(tmp_path, base_manifest=current) == []  # nothing changed


def test_main_check_exits_nonzero_on_drift_and_rejects_unknown_flags(tmp_path, monkeypatch):
    schema_export.write(tmp_path, init=True)
    (tmp_path / "Flag.json").write_text("{}\n")
    monkeypatch.setattr(schema_export, "SCHEMA_DIR", tmp_path)
    assert schema_export.main(["--check"]) == 1
    with pytest.raises(SystemExit):
        schema_export.main(["--chek"])  # a typo must not silently regenerate the schemas
