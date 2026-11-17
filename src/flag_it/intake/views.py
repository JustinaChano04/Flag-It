"""The read side of intake: what GET /transactions/{txn_id} and .../decisions return."""

from uuid import UUID

from flag_it.contracts.api import DecisionHistory, TransactionView
from flag_it.db import records
from flag_it.db.connection import Conn
from flag_it.intake.store import txn_exists


def transaction_view(conn: Conn, txn_id: UUID) -> TransactionView | None:
    """The transaction, its newest run that has a route, and that run's flags.

    A run the agent is still working on has no route yet, so the view shows the run before it, or
    no decision at all for a new transaction.
    """
    if not txn_exists(conn, txn_id):
        return None
    try:
        transaction = records.load_normalized_transaction(conn, txn_id)
    except records.NotFound:
        transaction = None
    decision = next((run for run in records.load_decision_history(conn, txn_id) if run.route is not None), None)
    flags = records.load_flags(conn, decision.decision_id) if decision else ()
    return TransactionView(txn_id=txn_id, transaction=transaction, decision=decision, flags=flags)


def decision_history(conn: Conn, txn_id: UUID) -> DecisionHistory | None:
    if not txn_exists(conn, txn_id):
        return None
    return DecisionHistory(txn_id=txn_id, decisions=records.load_decision_history(conn, txn_id))
