"""Tables the migrations must create. Each migration task adds its tables here."""

ALL_TABLES = {
    "alembic_version",
    "raw_transaction",
    "txn",
    "normalized_transaction",
    "receipt_file",
    "receipt_extraction",
    "category_result",
    "anomaly_result",
    "combined_expense_snapshot",
    "decision_run",
}
