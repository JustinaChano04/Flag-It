"""Alembic environment. Migrations are hand-written SQL: there is no SQLAlchemy model metadata."""

from alembic import context
from sqlalchemy import create_engine, pool

from flag_it.db.connection import sqlalchemy_url

if context.is_offline_mode():
    raise SystemExit("offline (SQL script) mode is not supported; run against a database")

url = context.config.get_main_option("sqlalchemy.url") or sqlalchemy_url()
engine = create_engine(url, poolclass=pool.NullPool)
with engine.connect() as connection:
    context.configure(connection=connection, target_metadata=None, transaction_per_migration=True)
    with context.begin_transaction():
        context.run_migrations()
