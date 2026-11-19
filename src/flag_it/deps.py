"""FastAPI dependencies shared by every stage's routes."""

from collections.abc import Iterator
from functools import lru_cache

from flag_it.contracts.rules import RuleSet, load_rules
from flag_it.db.connection import Conn, connect


def get_conn() -> Iterator[Conn]:
    """One connection per request. It commits when the request succeeds and rolls back when the
    request raises. Tests override this with their own rolled-back connection."""
    with connect() as conn:
        yield conn


@lru_cache
def get_rules() -> RuleSet:
    """The rules YAML, read once per process. Restart the API after editing it."""
    return load_rules()
