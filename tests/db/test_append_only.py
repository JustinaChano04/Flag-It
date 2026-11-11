"""Every table rejects UPDATE, DELETE, and TRUNCATE. decision_run's one allowed update is tested
in test_records_decision.py."""

import pytest
from psycopg import sql
from psycopg.errors import RestrictViolation

from flag_it.db.examples import save_example_review
from tests.db.expected import ALL_TABLES

TABLES = sorted(ALL_TABLES - {"alembic_version"})


def test_every_table_has_both_guard_triggers(conn):
    triggers = {row["tgname"] for row in conn.execute("SELECT tgname FROM pg_trigger WHERE NOT tgisinternal")}
    missing = [t for t in TABLES if not {f"{t}_no_update_delete", f"{t}_no_truncate"} <= triggers]
    assert missing == []


@pytest.mark.parametrize("table", [t for t in TABLES if t != "decision_run"])
def test_update_and_delete_are_rejected(conn, table):
    save_example_review(conn)
    column = conn.execute(
        "SELECT attname FROM pg_attribute WHERE attrelid = %s::regclass AND attnum = 1", (table,)
    ).fetchone()["attname"]
    with pytest.raises(RestrictViolation, match="append-only"), conn.transaction():
        conn.execute(sql.SQL("UPDATE {t} SET {c} = {c}").format(t=sql.Identifier(table), c=sql.Identifier(column)))
    with pytest.raises(RestrictViolation, match="append-only"), conn.transaction():
        conn.execute(sql.SQL("DELETE FROM {}").format(sql.Identifier(table)))


@pytest.mark.parametrize("table", TABLES)
def test_truncate_is_rejected(conn, table):
    save_example_review(conn)
    with pytest.raises(RestrictViolation, match="append-only"), conn.transaction():
        conn.execute(sql.SQL("TRUNCATE {} CASCADE").format(sql.Identifier(table)))
