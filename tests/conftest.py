"""Fixtures shared by every test folder. Database tests run against a real Postgres.

Start it with: docker compose -f deploy/compose.laptop.yaml up -d --wait postgres
Then set FLAG_IT_TEST_DATABASE_URL (see CLAUDE.md). Without it, database tests are skipped
locally and fail in CI, so CI can never pass by skipping them.
"""

import os

import psycopg
import pytest

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
