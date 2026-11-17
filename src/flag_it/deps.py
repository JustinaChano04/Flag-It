"""FastAPI dependencies shared by every stage's routes."""

from collections.abc import Iterator

from flag_it.db.connection import Conn, connect


def get_conn() -> Iterator[Conn]:
    """One connection per request. It commits when the request succeeds and rolls back when the
    request raises. Tests override this with their own rolled-back connection."""
    with connect() as conn:
        yield conn
