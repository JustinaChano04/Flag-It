"""Flags, agent verdicts, and review outcomes.

Revision ID: 0004
Revises: 0003
"""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def append_only(table: str) -> list[str]:
    """Triggers that reject UPDATE, DELETE, and TRUNCATE on one table."""
    return [
        f"CREATE TRIGGER {table}_no_update_delete BEFORE UPDATE OR DELETE ON {table} "
        "FOR EACH ROW EXECUTE FUNCTION reject_change()",
        f"CREATE TRIGGER {table}_no_truncate BEFORE TRUNCATE ON {table} "
        "FOR EACH STATEMENT EXECUTE FUNCTION reject_change()",
    ]


UPGRADE = [
    """
    CREATE TABLE flag (
        flag_id uuid PRIMARY KEY,
        decision_id uuid NOT NULL,
        txn_id uuid NOT NULL,
        rule_id text NOT NULL,
        check_id text NOT NULL,
        result text NOT NULL CHECK (result IN ('fail', 'violation', 'unclear', 'pending', 'not_evaluated')),
        severity text NOT NULL CHECK (severity IN ('prohibited', 'conditional', 'documentation', 'guidance')),
        evidence jsonb NOT NULL CHECK (
            CASE WHEN jsonb_typeof(evidence) = 'array' THEN jsonb_array_length(evidence) > 0 ELSE false END
        ),
        score double precision NOT NULL CHECK (score BETWEEN 0 AND 1),
        source text NOT NULL CHECK (source IN ('code', 'llm')),
        due_at timestamptz,
        created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        CONSTRAINT flag_run FOREIGN KEY (decision_id, txn_id) REFERENCES decision_run (decision_id, txn_id),
        CONSTRAINT flag_one_per_check UNIQUE (decision_id, check_id),
        CONSTRAINT flag_check_of_rule CHECK (check_id ~ ('^' || rule_id || '[a-z]+$')),
        CONSTRAINT flag_due_at_iff_pending CHECK ((result = 'pending') = (due_at IS NOT NULL))
    )
    """,
    "COMMENT ON COLUMN flag.due_at IS 'When a pending check deadline passes. The deadline job reads it.'",
    "CREATE INDEX flag_rule_created ON flag (rule_id, created_at)",
    "CREATE INDEX flag_pending_due ON flag (due_at) WHERE result = 'pending'",
    """
    CREATE TABLE agent_verdict (
        decision_id uuid NOT NULL REFERENCES decision_run (decision_id),
        check_id text NOT NULL CHECK (check_id ~ '^[A-Z0-9]+(-[A-Z0-9]+)+[a-z]+$'),
        result text NOT NULL CHECK (result IN ('pass', 'fail', 'unsure')),
        confidence double precision NOT NULL CHECK (confidence BETWEEN 0 AND 1),
        evidence jsonb NOT NULL DEFAULT '[]' CHECK (jsonb_typeof(evidence) = 'array'),
        created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        PRIMARY KEY (decision_id, check_id)
    )
    """,
    "COMMENT ON TABLE agent_verdict IS 'The agent answer for one llm check in one run, as the guardrails received it.'",
    """
    CREATE TABLE review_outcome (
        review_id uuid PRIMARY KEY,
        decision_id uuid NOT NULL REFERENCES decision_run (decision_id),
        reviewer text NOT NULL CHECK (reviewer <> ''),
        final text NOT NULL CHECK (final IN ('approve', 'flag')),
        per_flag jsonb NOT NULL DEFAULT '[]' CHECK (jsonb_typeof(per_flag) = 'array'),
        missed_rule_ids text[] NOT NULL DEFAULT '{}',
        reason text,
        created_at timestamptz NOT NULL
    )
    """,
    "CREATE INDEX review_outcome_decision_created ON review_outcome (decision_id, created_at)",
    *append_only("flag"),
    *append_only("agent_verdict"),
    *append_only("review_outcome"),
]

DOWNGRADE = [
    "DROP TABLE review_outcome",
    "DROP TABLE agent_verdict",
    "DROP TABLE flag",
]


def upgrade() -> None:
    for statement in UPGRADE:
        op.execute(statement)


def downgrade() -> None:
    for statement in DOWNGRADE:
        op.execute(statement)
