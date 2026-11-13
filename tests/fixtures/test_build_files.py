"""The committed fixtures are exactly what the builder produces."""

import json

from flag_it.fixtures import fixtures_dir
from flag_it.fixtures.build import build, check

FILES = {
    "raw_transactions.json",
    "receipt_files.json",
    "snapshots.json",
    "decision_runs.json",
    "flags.json",
    "agent_outputs.json",
    "agent_outputs_invalid.json",
    "jobs.json",
    "review_outcomes.json",
    "catalog.md",
}


def test_build_writes_every_file_and_is_deterministic():
    first = build()
    assert set(first) == FILES
    assert build() == first
    for name, text in first.items():
        if name.endswith(".json"):
            json.loads(text)


def test_the_catalog_lists_every_snapshot_and_run():
    files = build()
    catalog = files["catalog.md"]
    for name in json.loads(files["snapshots.json"]) | json.loads(files["decision_runs.json"]):
        assert f"`{name}`" in catalog


def test_committed_fixtures_match_a_fresh_build():
    assert check(fixtures_dir()) == [], "fixtures/ is stale. Run: .venv/bin/python -m flag_it.fixtures.build"


def test_check_reports_a_stale_and_an_unknown_file(tmp_path):
    for name, text in build().items():
        (tmp_path / name).write_text(text)
    (tmp_path / "flags.json").write_text("{}\n")
    (tmp_path / "old.json").write_text("{}\n")
    assert check(tmp_path) == ["flags.json differs from a fresh build", "old.json is not built by build.py"]
