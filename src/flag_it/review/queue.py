"""The review queue: decision runs waiting for a person.

A run is waiting when its route is human_review, no later run replaces it, and nobody has
reviewed it yet. A replaced run drops out: its rerun is the one that decides now.
Oldest first, so nothing waits forever behind newer work.

Each row shows the merchant, amount and date. They come from the run's own snapshot, in one query for
all rows, so the screen makes one request however long the queue is.
"""

from collections.abc import Sequence

from flag_it.contracts.api import QueueSummary
from flag_it.contracts.decide import DecisionRun
from flag_it.db import records
from flag_it.db.connection import Conn

_WAITING = """
SELECT r.decision_id FROM decision_run r
WHERE r.route = 'human_review'
  AND NOT EXISTS (SELECT 1 FROM decision_run later WHERE later.replaces_decision_id = r.decision_id)
  AND NOT EXISTS (SELECT 1 FROM review_outcome o WHERE o.decision_id = r.decision_id)
ORDER BY r.created_at, r.decision_id
LIMIT %s
"""


def review_queue(conn: Conn, limit: int = 100) -> tuple[DecisionRun, ...]:
    rows = conn.execute(_WAITING, (limit,)).fetchall()
    return tuple(records.load_decision_run(conn, row["decision_id"]) for row in rows)


_SUMMARIES = """
SELECT r.decision_id,
       s.payload -> 'transaction' ->> 'merchant_norm' AS merchant,
       s.payload -> 'transaction' ->> 'amount' AS amount,
       s.payload -> 'transaction' ->> 'transaction_date' AS transaction_date
FROM decision_run r JOIN combined_expense_snapshot s ON s.snapshot_id = r.snapshot_id
WHERE r.decision_id = ANY(%s)
"""


def queue_summaries(conn: Conn, runs: Sequence[DecisionRun]) -> tuple[QueueSummary, ...]:
    if not runs:
        return ()
    rows = conn.execute(_SUMMARIES, ([run.decision_id for run in runs],)).fetchall()
    by_run = {row["decision_id"]: row for row in rows}
    return tuple(QueueSummary.model_validate(dict(by_run[run.decision_id])) for run in runs)
