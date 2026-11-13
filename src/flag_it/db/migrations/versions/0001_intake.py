"""Intake tables, and the trigger function that makes tables append-only.

Revision ID: 0001
Revises:
"""

from alembic import op

revision = "0001"
down_revision = None
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
    CREATE FUNCTION reject_change() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        RAISE EXCEPTION USING
            MESSAGE = TG_TABLE_NAME || ' is append-only: ' || TG_OP || ' is not allowed',
            ERRCODE = 'restrict_violation';
    END
    $$
    """,
    """
    CREATE TABLE raw_transaction (
        raw_id uuid PRIMARY KEY,
        source_file text,
        source_line_no integer CHECK (source_line_no >= 1),
        source text,
        external_id text,
        source_rowid text,
        calendar_year text,
        calendar_month text,
        agencynbr text,
        agencyname text,
        last_name text,
        first_initial text,
        item_descr text,
        amount text,
        merchant_name text,
        transaction_date text,
        post_date text,
        mcc_description text,
        mcc_code text,
        business_purpose text,
        loaded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        CONSTRAINT raw_transaction_one_origin CHECK (
            (source_file IS NOT NULL AND source_line_no IS NOT NULL AND source IS NULL AND external_id IS NULL)
            OR (source_file IS NULL AND source_line_no IS NULL AND source IS NOT NULL AND external_id IS NOT NULL)
        ),
        CONSTRAINT raw_transaction_file_row UNIQUE (source_file, source_line_no),
        CONSTRAINT raw_transaction_api_item UNIQUE (source, external_id)
    )
    """,
    "COMMENT ON TABLE raw_transaction IS 'One source row exactly as received. Every source field is text.'",
    "COMMENT ON COLUMN raw_transaction.source_rowid IS 'State ROWID. Not an identifier: reused across monthly files.'",
    """
    CREATE TABLE txn (
        txn_id uuid PRIMARY KEY,
        raw_id uuid NOT NULL REFERENCES raw_transaction (raw_id),
        created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        CONSTRAINT txn_one_per_raw UNIQUE (raw_id),
        CONSTRAINT txn_raw_pair UNIQUE (txn_id, raw_id)
    )
    """,
    "COMMENT ON TABLE txn IS 'Transaction identity. Intake assigns txn_id before normalization runs.'",
    r"""
    CREATE TABLE normalized_transaction (
        txn_id uuid NOT NULL,
        normalizer_version text NOT NULL CHECK (normalizer_version <> ''),
        raw_id uuid NOT NULL,
        agency_id text NOT NULL CHECK (agency_id <> ''),
        cardholder_id text NOT NULL CHECK (cardholder_id <> ''),
        merchant_norm text NOT NULL CHECK (merchant_norm <> ''),
        mcc_description text NOT NULL CHECK (mcc_description <> ''),
        mcc_code text CHECK (mcc_code ~ '^\d{4}$'),
        amount numeric(12, 2) NOT NULL,
        transaction_date date NOT NULL,
        post_date date NOT NULL,
        business_purpose text,
        created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        PRIMARY KEY (txn_id, normalizer_version),
        CONSTRAINT normalized_transaction_txn FOREIGN KEY (txn_id, raw_id) REFERENCES txn (txn_id, raw_id)
    )
    """,
    "COMMENT ON TABLE normalized_transaction IS 'Typed version of a raw row, one row per normalizer version.'",
    "COMMENT ON COLUMN normalized_transaction.cardholder_id IS 'Stand-in key agency_id|LASTNAME|I until a real card ID exists.'",
    "CREATE INDEX normalized_transaction_cardholder_date ON normalized_transaction (cardholder_id, transaction_date)",
    "CREATE INDEX normalized_transaction_cardholder_merchant_date "
    "ON normalized_transaction (cardholder_id, merchant_norm, transaction_date)",
    "CREATE INDEX normalized_transaction_agency_date ON normalized_transaction (agency_id, transaction_date)",
    *append_only("raw_transaction"),
    *append_only("txn"),
    *append_only("normalized_transaction"),
]

DOWNGRADE = [
    "DROP TABLE normalized_transaction",
    "DROP TABLE txn",
    "DROP TABLE raw_transaction",
    "DROP FUNCTION reject_change()",
]


def upgrade() -> None:
    for statement in UPGRADE:
        op.execute(statement)


def downgrade() -> None:
    for statement in DOWNGRADE:
        op.execute(statement)
