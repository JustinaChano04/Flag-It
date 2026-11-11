"""Each enum column's CHECK lists exactly the values of its Python enum."""

import re
from enum import StrEnum

import pytest

from flag_it.contracts.enums import (
    AgentResult,
    AnomalyStatus,
    CategoryMethod,
    DecidedBy,
    FlagResult,
    FlagSource,
    MatchStatus,
    ReviewFinal,
    Route,
    RunTrigger,
    Severity,
)

ENUM_COLUMNS: list[tuple[str, str, type[StrEnum]]] = [
    ("receipt_extraction", "match_status", MatchStatus),
    ("category_result", "method", CategoryMethod),
    ("anomaly_result", "status", AnomalyStatus),
    ("decision_run", "route", Route),
    ("decision_run", "decided_by", DecidedBy),
    ("decision_run", "trigger", RunTrigger),
    ("flag", "result", FlagResult),
    ("flag", "severity", Severity),
    ("flag", "source", FlagSource),
    ("agent_verdict", "result", AgentResult),
    ("review_outcome", "final", ReviewFinal),
]


def allowed_values(conn, table: str, column: str) -> set[str]:
    """The quoted values in the single-column CHECK on table.column."""
    rows = conn.execute(
        """
        SELECT pg_get_constraintdef(c.oid) AS definition
        FROM pg_constraint c
        JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = c.conkey[1]
        WHERE c.contype = 'c' AND c.conrelid = %s::regclass AND a.attname = %s AND cardinality(c.conkey) = 1
        """,
        (table, column),
    ).fetchall()
    assert len(rows) == 1, f"expected one CHECK on {table}.{column}, found {len(rows)}"
    return set(re.findall(r"'([a-z_]+)'::text", rows[0]["definition"]))


@pytest.mark.parametrize(("table", "column", "enum"), ENUM_COLUMNS, ids=[f"{t}.{c}" for t, c, _ in ENUM_COLUMNS])
def test_check_matches_the_enum(conn, table, column, enum):
    assert allowed_values(conn, table, column) == {member.value for member in enum}
