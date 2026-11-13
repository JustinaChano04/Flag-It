"""Run the migrations.

    python -m flag_it.db.migrate upgrade            # to the newest revision
    python -m flag_it.db.migrate downgrade base     # undo everything

Uses FLAG_IT_DATABASE_URL. To write a new migration, from the repo root:
    alembic revision --rev-id 0005 -m "what it does"
then fill in its UPGRADE and DOWNGRADE lists by hand.
"""

import argparse
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy.engine import make_url

from flag_it.db.connection import sqlalchemy_url

MIGRATIONS = Path(__file__).parent / "migrations"


def alembic_config(url: str | None = None) -> Config:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS))
    # Config values go through configparser, which treats % as special.
    config.set_main_option("sqlalchemy.url", sqlalchemy_url(url).replace("%", "%%"))
    return config


def upgrade(url: str | None = None, revision: str = "head") -> None:
    command.upgrade(alembic_config(url), revision)


def downgrade(url: str | None = None, revision: str = "base") -> None:
    command.downgrade(alembic_config(url), revision)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m flag_it.db.migrate")
    parser.add_argument("action", choices=["upgrade", "downgrade"])
    parser.add_argument("revision", nargs="?")
    parser.add_argument("--force", action="store_true", help="allow a downgrade of a database not named *_test")
    args = parser.parse_args(argv)
    if args.action == "upgrade":
        upgrade(revision=args.revision or "head")
    elif args.revision is None:
        parser.error("downgrade needs a revision, such as base or 0002")
    elif not args.force and not (make_url(sqlalchemy_url()).database or "").endswith("_test"):
        # DROP TABLE skips the append-only triggers, so a downgrade erases history without a trace.
        parser.error("downgrade drops tables; run it on a *_test database, or pass --force")
    else:
        downgrade(revision=args.revision)


if __name__ == "__main__":
    main()
