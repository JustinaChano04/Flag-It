"""Snapshots and decision runs. A run's route may be filled in once, when the agent finishes.

Revision ID: 0003
Revises: 0002
"""

from alembic import op

revision = "0003"
down_revision = "0002"
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
    r"""
    CREATE TABLE combined_expense_snapshot (
        snapshot_id uuid PRIMARY KEY,
        txn_id uuid NOT NULL REFERENCES txn (txn_id),
        payload jsonb NOT NULL,
        source_versions jsonb NOT NULL,
        contract_version text NOT NULL CHECK (contract_version ~ '^\d+\.\d+\.\d+$'),
        created_at timestamptz NOT NULL,
        CONSTRAINT combined_expense_snapshot_txn_pair UNIQUE (snapshot_id, txn_id),
        CONSTRAINT combined_expense_snapshot_payload_txn CHECK (payload -> 'transaction' ->> 'txn_id' = txn_id::text)
    )
    """,
    "COMMENT ON TABLE combined_expense_snapshot IS 'The frozen input to one decision run.'",
    """
    CREATE TABLE decision_run (
        decision_id uuid PRIMARY KEY,
        txn_id uuid NOT NULL REFERENCES txn (txn_id),
        snapshot_id uuid NOT NULL,
        route text CHECK (route IN ('flag', 'auto_approve', 'agent_approve', 'agent_flag', 'human_review')),
        decided_by text CHECK (decided_by IN ('rules', 'screener', 'agent', 'guardrails', 'rerun')),
        trigger text NOT NULL CHECK (trigger IN ('initial', 'late_receipt', 'deadline')),
        replaces_decision_id uuid,
        screener_probability double precision CHECK (screener_probability BETWEEN 0 AND 1),
        screener_threshold double precision CHECK (screener_threshold BETWEEN 0 AND 1),
        screener_model_version text,
        escalation_reasons text[] NOT NULL DEFAULT '{}',
        rules_version text NOT NULL CHECK (rules_version <> ''),
        created_at timestamptz NOT NULL,
        CONSTRAINT decision_run_txn_pair UNIQUE (decision_id, txn_id),
        CONSTRAINT decision_run_one_per_snapshot UNIQUE (snapshot_id),
        CONSTRAINT decision_run_replaced_once UNIQUE (replaces_decision_id),
        CONSTRAINT decision_run_snapshot FOREIGN KEY (snapshot_id, txn_id)
            REFERENCES combined_expense_snapshot (snapshot_id, txn_id),
        CONSTRAINT decision_run_replaces FOREIGN KEY (replaces_decision_id, txn_id)
            REFERENCES decision_run (decision_id, txn_id),
        CONSTRAINT decision_run_route_with_decider CHECK ((route IS NULL) = (decided_by IS NULL)),
        CONSTRAINT decision_run_replaces_unless_initial CHECK ((trigger = 'initial') = (replaces_decision_id IS NULL)),
        CONSTRAINT decision_run_screener_complete CHECK (
            num_nonnulls(screener_probability, screener_threshold, screener_model_version) IN (0, 3)
        ),
        CONSTRAINT decision_run_escalation_iff_human_review CHECK (
            (coalesce(route, '') = 'human_review') = (cardinality(escalation_reasons) > 0)
        )
    )
    """,
    "COMMENT ON TABLE decision_run IS 'One pass of the Decide stages over one snapshot. Reruns form one chain per transaction.'",
    "COMMENT ON COLUMN decision_run.route IS 'Null while the agent works, then filled in once.'",
    "CREATE UNIQUE INDEX decision_run_one_initial ON decision_run (txn_id) WHERE trigger = 'initial'",
    "CREATE INDEX decision_run_txn_created ON decision_run (txn_id, created_at)",
    """
    CREATE FUNCTION decision_run_fill_route_once() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        IF TG_OP = 'DELETE' THEN
            RAISE EXCEPTION USING
                MESSAGE = 'decision_run is append-only: DELETE is not allowed',
                ERRCODE = 'restrict_violation';
        END IF;
        IF OLD.route IS NOT NULL THEN
            RAISE EXCEPTION USING
                MESSAGE = 'decision_run is append-only: the route is already set',
                ERRCODE = 'restrict_violation';
        END IF;
        -- Every column except the three fillable ones must be unchanged. Comparing whole rows
        -- means a column added by a later migration is protected without editing this function.
        IF NEW.route IS NULL
           OR (to_jsonb(NEW) - ARRAY['route', 'decided_by', 'escalation_reasons'])
              IS DISTINCT FROM
              (to_jsonb(OLD) - ARRAY['route', 'decided_by', 'escalation_reasons'])
        THEN
            RAISE EXCEPTION USING
                MESSAGE = 'decision_run is append-only: an update may only fill in route, decided_by and escalation_reasons',
                ERRCODE = 'restrict_violation';
        END IF;
        RETURN NEW;
    END
    $$
    """,
    "CREATE TRIGGER decision_run_no_update_delete BEFORE UPDATE OR DELETE ON decision_run "
    "FOR EACH ROW EXECUTE FUNCTION decision_run_fill_route_once()",
    "CREATE TRIGGER decision_run_no_truncate BEFORE TRUNCATE ON decision_run "
    "FOR EACH STATEMENT EXECUTE FUNCTION reject_change()",
    *append_only("combined_expense_snapshot"),
]

DOWNGRADE = [
    "DROP TABLE decision_run",
    "DROP FUNCTION decision_run_fill_route_once()",
    "DROP TABLE combined_expense_snapshot",
]


def upgrade() -> None:
    for statement in UPGRADE:
        op.execute(statement)


def downgrade() -> None:
    for statement in DOWNGRADE:
        op.execute(statement)
