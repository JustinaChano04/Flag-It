"""Fixtures shared by every test folder. Database tests run against a real Postgres.

Start it with: docker compose -f deploy/compose.laptop.yaml up -d --wait postgres
Then set FLAG_IT_TEST_DATABASE_URL (see CLAUDE.md). Without it, database tests are skipped
locally and fail in CI, so CI can never pass by skipping them.
"""

import os

import psycopg
import pytest

from flag_it.db.connection import connect
from flag_it.db.migrate import upgrade

TEST_URL_ENV = "FLAG_IT_TEST_DATABASE_URL"


@pytest.fixture(scope="session")
def db_url() -> str:
    url = os.environ.get(TEST_URL_ENV)
    if not url:
        if os.environ.get("CI"):
            pytest.fail(f"{TEST_URL_ENV} is not set; CI must run the database tests")
        pytest.skip(f"{TEST_URL_ENV} is not set; start Postgres (see tests/conftest.py)")
    if not psycopg.conninfo.conninfo_to_dict(url).get("dbname", "").endswith("_test"):
        pytest.fail(f"{TEST_URL_ENV} must name a database ending in _test: these tests drop its schema")
    return url


def reset_schema(url: str) -> None:
    with psycopg.connect(url, autocommit=True) as admin:
        admin.execute("DROP SCHEMA public CASCADE")
        admin.execute("CREATE SCHEMA public")


@pytest.fixture(scope="session")
def migrated(db_url: str) -> str:
    """The test database, emptied and migrated to head once per test session."""
    reset_schema(db_url)
    upgrade(db_url)
    return db_url


@pytest.fixture
def conn(migrated: str):
    """One connection per test, rolled back at the end, so tests never see each other's rows.

    A statement that fails aborts the transaction. Wrap an expected failure in a savepoint:
        with pytest.raises(SomeError), conn.transaction():
            conn.execute(...)
    """
    with connect(migrated) as connection:
        yield connection
        connection.rollback()
