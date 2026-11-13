"""Understand-stage results and receipt files.

Revision ID: 0002
Revises: 0001
"""

from alembic import op

revision = "0002"
down_revision = "0001"
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
    CREATE TABLE receipt_file (
        receipt_id uuid PRIMARY KEY,
        txn_id uuid NOT NULL REFERENCES txn (txn_id),
        storage_key text NOT NULL CHECK (storage_key <> ''),
        content_type text NOT NULL CHECK (content_type <> ''),
        sha256 text NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
        size_bytes bigint NOT NULL CHECK (size_bytes > 0),
        uploaded_at timestamptz NOT NULL,
        CONSTRAINT receipt_file_txn_pair UNIQUE (receipt_id, txn_id)
    )
    """,
    "COMMENT ON TABLE receipt_file IS 'An uploaded receipt. The read_receipt worker finds the file by receipt_id.'",
    "COMMENT ON COLUMN receipt_file.storage_key IS 'Object key in the receipt store (MinIO).'",
    """
    CREATE TABLE receipt_extraction (
        receipt_id uuid NOT NULL,
        reader_model text NOT NULL CHECK (reader_model <> ''),
        txn_id uuid NOT NULL,
        match_status text NOT NULL CHECK (match_status IN ('matched', 'mismatch', 'unmatched')),
        merchant text,
        receipt_date date,
        subtotal numeric(12, 2),
        tax numeric(12, 2),
        tip numeric(12, 2),
        total numeric(12, 2),
        line_items jsonb NOT NULL DEFAULT '[]' CHECK (jsonb_typeof(line_items) = 'array'),
        created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        PRIMARY KEY (receipt_id, reader_model),
        CONSTRAINT receipt_extraction_file FOREIGN KEY (receipt_id, txn_id)
            REFERENCES receipt_file (receipt_id, txn_id)
    )
    """,
    "COMMENT ON TABLE receipt_extraction IS 'What one reader model read from one receipt. Unreadable fields are null.'",
    """
    CREATE TABLE category_result (
        txn_id uuid NOT NULL REFERENCES txn (txn_id),
        model_version text NOT NULL CHECK (model_version <> ''),
        category text NOT NULL CHECK (category <> ''),
        confidence double precision NOT NULL CHECK (confidence BETWEEN 0 AND 1),
        method text NOT NULL CHECK (method IN ('lookup', 'model')),
        created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        PRIMARY KEY (txn_id, model_version)
    )
    """,
    "COMMENT ON COLUMN category_result.category IS 'A category ID from the rules YAML.'",
    """
    CREATE TABLE anomaly_result (
        txn_id uuid NOT NULL REFERENCES txn (txn_id),
        model_version text NOT NULL CHECK (model_version <> ''),
        status text NOT NULL CHECK (status IN ('scored', 'insufficient_history')),
        score double precision,
        history_length integer NOT NULL CHECK (history_length >= 0),
        as_of timestamptz NOT NULL,
        created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        PRIMARY KEY (txn_id, model_version),
        CONSTRAINT anomaly_result_score_matches_status CHECK ((status = 'scored') = (score IS NOT NULL))
    )
    """,
    "COMMENT ON COLUMN anomaly_result.as_of IS 'Only history before this time was used.'",
    *append_only("receipt_file"),
    *append_only("receipt_extraction"),
    *append_only("category_result"),
    *append_only("anomaly_result"),
]

DOWNGRADE = [
    "DROP TABLE anomaly_result",
    "DROP TABLE category_result",
    "DROP TABLE receipt_extraction",
    "DROP TABLE receipt_file",
]


def upgrade() -> None:
    for statement in UPGRADE:
        op.execute(statement)


def downgrade() -> None:
    for statement in DOWNGRADE:
        op.execute(statement)
