"""Connections: dict rows, UTC, and the URL forms psycopg and SQLAlchemy need."""

import pytest

from flag_it.db.connection import connect, database_url, sqlalchemy_url


def test_connect_returns_dict_rows_in_utc(db_url):
    with connect(db_url) as conn:
        row = conn.execute("SELECT 1 AS one, current_setting('TimeZone') AS tz").fetchone()
    assert row == {"one": 1, "tz": "UTC"}


def test_database_url_requires_the_env_var(monkeypatch):
    monkeypatch.delenv("FLAG_IT_DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError, match="FLAG_IT_DATABASE_URL"):
        database_url()


def test_sqlalchemy_url_names_the_driver():
    assert sqlalchemy_url("postgresql://u:p@h:5432/d") == "postgresql+psycopg://u:p@h:5432/d"
    assert sqlalchemy_url("postgres://u:p@h:5432/d") == "postgresql+psycopg://u:p@h:5432/d"
