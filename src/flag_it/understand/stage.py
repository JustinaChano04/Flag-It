"""Run the categorizer and the anomaly detector for one transaction and save their results.

Results are append-only and keyed on (txn_id, version). A result already saved for this version is
returned as it is, so plan 21 can call this again after a retry without a duplicate-key error. If a
concurrent run saves the same result first, its result is kept and returned.
"""

from collections.abc import Callable
from typing import TypeVar

from psycopg.errors import UniqueViolation

from flag_it.contracts.transactions import NormalizedTransaction
from flag_it.contracts.understand import AnomalyResult, CategoryResult
from flag_it.db import records
from flag_it.db.connection import Conn
from flag_it.understand.anomaly import AnomalyConfig, score_anomaly
from flag_it.understand.categorize import MccLookup, categorize

R = TypeVar("R")


def _keep_first(conn: Conn, result: R, save: Callable[[Conn, R], None], reload: Callable[[], R]) -> R:
    """Save result, or return the one a concurrent run saved first. The savepoint keeps a duplicate
    key from aborting the caller's transaction."""
    try:
        with conn.transaction():
            save(conn, result)
    except UniqueViolation:
        return reload()
    return result


def understand(
    conn: Conn, txn: NormalizedTransaction, lookup: MccLookup, config: AnomalyConfig
) -> tuple[CategoryResult, AnomalyResult]:
    def saved_category() -> CategoryResult:
        return records.load_category_result(conn, txn.txn_id, lookup.version)

    def saved_anomaly() -> AnomalyResult:
        return records.load_anomaly_result(conn, txn.txn_id, config.version)

    try:
        category = saved_category()
    except records.NotFound:
        category = _keep_first(conn, categorize(txn, lookup), records.save_category_result, saved_category)
    try:
        anomaly = saved_anomaly()
    except records.NotFound:
        anomaly = _keep_first(conn, score_anomaly(conn, txn, config), records.save_anomaly_result, saved_anomaly)
    return category, anomaly
