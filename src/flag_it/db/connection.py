"""Database connections. The URL is in libpq form (postgresql://user:pass@host:port/db)."""

import os
from typing import Any

import psycopg
from psycopg.rows import dict_row

URL_ENV = "FLAG_IT_DATABASE_URL"

Conn = psycopg.Connection[dict[str, Any]]


def database_url() -> str:
    url = os.environ.get(URL_ENV)
    if not url:
        raise RuntimeError(f"set {URL_ENV}, e.g. postgresql://flag_it:flag_it@localhost:5432/flag_it")
    return url


def connect(url: str | None = None) -> Conn:
    """A connection that returns rows as dicts and reads timestamps in UTC. The caller commits."""
    return psycopg.connect(url or database_url(), row_factory=dict_row, options="-c timezone=UTC")


def sqlalchemy_url(url: str | None = None) -> str:
    """Alembic runs on SQLAlchemy, which names the driver in the URL scheme."""
    rest = (url or database_url()).split("://", 1)[1]
    return f"postgresql+psycopg://{rest}"
