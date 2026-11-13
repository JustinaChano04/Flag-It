"""docs/schema.dbml is generated from the migrated database and must be current."""

from flag_it.db.dbml import DBML_PATH, render
from tests.db.expected import ALL_TABLES


def test_every_table_is_rendered(conn):
    text = render(conn)
    for table in ALL_TABLES - {"alembic_version"}:
        assert f"Table {table} {{" in text
    assert "alembic_version" not in text


def test_composite_keys_and_refs_are_rendered(conn):
    text = render(conn)
    assert "(txn_id, normalizer_version) [pk]" in text
    assert "Ref decision_run_replaces: decision_run.(replaces_decision_id, txn_id) > decision_run.(decision_id, txn_id)" in text


def test_schema_dbml_is_current(conn):
    assert DBML_PATH.read_text() == render(conn), (
        "docs/schema.dbml is out of date. Run: .venv/bin/python -m flag_it.db.dbml --url $FLAG_IT_TEST_DATABASE_URL"
    )
