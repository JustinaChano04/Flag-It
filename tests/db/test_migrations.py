"""Migrations build every table from an empty database and can be undone."""

import pytest

from flag_it.db.connection import Conn, connect
from flag_it.db.migrate import downgrade, main, upgrade
from tests.db.expected import ALL_TABLES


def tables(conn: Conn) -> set[str]:
    rows = conn.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public'").fetchall()
    return {row["tablename"] for row in rows}


def test_upgrade_creates_every_table(conn):
    assert tables(conn) == ALL_TABLES


def test_downgrade_to_base_and_back(migrated):
    # This empties the session's shared database, so always put it back, even if an assertion fails.
    try:
        downgrade(migrated, "base")
        with connect(migrated) as conn:
            assert tables(conn) == {"alembic_version"}
    finally:
        upgrade(migrated)
    with connect(migrated) as conn:
        assert tables(conn) == ALL_TABLES


def test_the_downgrade_command_refuses_a_database_not_named_test(monkeypatch):
    monkeypatch.setenv("FLAG_IT_DATABASE_URL", "postgresql://u:p@localhost:5432/flag_it")
    with pytest.raises(SystemExit):
        main(["downgrade", "base"])
