"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}

Hand-written SQL. One statement per list item. No % characters and no :name tokens
(SQLAlchemy's text() reads them as parameters). Use r-strings for statements with a backslash.
Every new table gets the two append-only triggers; see 0001_intake.py.
"""

from alembic import op

revision = ${repr(up_revision)}
down_revision = ${repr(down_revision)}
branch_labels = None
depends_on = None

UPGRADE: list[str] = []

DOWNGRADE: list[str] = []


def upgrade() -> None:
    for statement in UPGRADE:
        op.execute(statement)


def downgrade() -> None:
    for statement in DOWNGRADE:
        op.execute(statement)
