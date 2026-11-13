"""The loader returns validated, read-only models for every committed fixture."""

import pytest

from flag_it import fixtures
from flag_it.contracts.decide import DecisionRun
from flag_it.contracts.snapshot import CombinedExpenseSnapshot


def test_every_collection_loads():
    # Named members and lower bounds, so adding a fixture never breaks this test.
    assert {"over_single_limit", "at_single_limit", "receipt_mismatch"} <= set(fixtures.snapshots())
    assert {"flag_over_limit", "agent_working", "lodging_stay_2"} <= set(fixtures.decision_runs())
    assert len(fixtures.review_outcomes()) >= 4
    assert len(fixtures.invalid_agent_outputs()) >= 6
    assert fixtures.raw_transactions() and fixtures.receipt_files() and fixtures.agent_outputs()
    assert fixtures.investigate_jobs() and fixtures.read_receipt_jobs()


def test_lookups_by_name():
    assert isinstance(fixtures.snapshot("receipt_mismatch"), CombinedExpenseSnapshot)
    run = fixtures.decision_run("agent_flagged")
    assert isinstance(run, DecisionRun)
    assert fixtures.snapshot_for(run) == fixtures.snapshot("cat_restricted_items")
    assert [f.check_id for f in fixtures.flags("agent_flagged")] == ["OSU-PRH-09a"]
    assert fixtures.flags("auto_approved") == ()  # exempt from the pending receipt flag; see "What the fixtures cover"


def test_unknown_names_list_the_known_ones():
    with pytest.raises(KeyError, match="receipt_mismatch"):
        fixtures.snapshot("no_such_snapshot")
    with pytest.raises(KeyError, match="agent_flagged"):
        fixtures.flags("no_such_run")


def test_collections_are_read_only():
    with pytest.raises(TypeError):
        fixtures.snapshots()["x"] = fixtures.snapshot("refund")  # type: ignore[index]


def test_the_fixtures_folder_can_be_moved(monkeypatch, tmp_path):
    monkeypatch.setenv("FLAG_IT_FIXTURES_PATH", str(tmp_path))
    assert fixtures.fixtures_dir() == tmp_path
