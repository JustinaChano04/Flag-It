"""Sweeps: periodic read-only queries that find work the normal path lost or is waiting on.

Each sweep returns the jobs to enqueue (or, for stuck_runs, the runs it ended). They only read, except
stuck_runs, which fills the route of a run nobody is working on. Every job a sweep returns has a
deterministic job ID and a handler that is a no-op when the work is already done, so running a sweep twice,
or while the normal path is still working, creates no duplicates.

All of them ignore work younger than `sweep_grace_minutes`, so a sweep doesn't race the normal path.
"Now" is passed in. Rows stamped by the database's own clock (created_at defaults) are compared with it,
so callers pass the real time.
"""

from datetime import datetime, timedelta

from flag_it.contracts.decide import DecisionRun
from flag_it.contracts.enums import DecidedBy, Route, RunTrigger
from flag_it.contracts.rules import PipelineSettings
from flag_it.db import records
from flag_it.db.connection import Conn
from flag_it.pipeline.jobs import JobSpec, decide_spec, read_receipt_spec, understand_spec

_CURRENT = "NOT EXISTS (SELECT 1 FROM decision_run later WHERE later.replaces_decision_id = r.decision_id)"


def _grace(now: datetime, settings: PipelineSettings) -> datetime:
    return now - timedelta(minutes=settings.sweep_grace_minutes)


def due_reruns(conn: Conn, now: datetime, settings: PipelineSettings) -> tuple[JobSpec, ...]:
    """A current run has a pending check whose deadline passed: one deadline decide job each."""
    rows = conn.execute(
        f"SELECT DISTINCT r.txn_id, r.decision_id FROM decision_run r JOIN flag f ON f.decision_id = r.decision_id"
        f" WHERE f.result = 'pending' AND f.due_at <= %s AND {_CURRENT} ORDER BY r.decision_id",
        (_grace(now, settings),),
    ).fetchall()
    return tuple(decide_spec(r["txn_id"], RunTrigger.DEADLINE, r["decision_id"]) for r in rows)


def unrun_transactions(conn: Conn, now: datetime, settings: PipelineSettings) -> tuple[JobSpec, ...]:
    """Accepted transactions older than the grace with no decision run: one understand job each."""
    rows = conn.execute(
        "SELECT t.txn_id FROM txn t JOIN normalized_transaction n ON n.txn_id = t.txn_id"
        " WHERE t.created_at <= %s AND NOT EXISTS (SELECT 1 FROM decision_run r WHERE r.txn_id = t.txn_id)"
        " GROUP BY t.txn_id ORDER BY t.txn_id",
        (_grace(now, settings),),
    ).fetchall()
    return tuple(understand_spec(r["txn_id"]) for r in rows)


def unread_receipts(
    conn: Conn, now: datetime, settings: PipelineSettings, reader_model: str
) -> tuple[JobSpec, ...]:
    """Receipt files older than the grace that this reader model has not read: one read_receipt job each."""
    rows = conn.execute(
        "SELECT f.receipt_id, f.txn_id FROM receipt_file f WHERE f.uploaded_at <= %s"
        " AND NOT EXISTS (SELECT 1 FROM receipt_extraction e WHERE e.receipt_id = f.receipt_id AND e.reader_model = %s)"
        " ORDER BY f.receipt_id",
        (_grace(now, settings), reader_model),
    ).fetchall()
    return tuple(read_receipt_spec(r["receipt_id"], r["txn_id"]) for r in rows)


def lost_receipts(
    conn: Conn, now: datetime, settings: PipelineSettings, reader_model: str
) -> tuple[JobSpec, ...]:
    """Current runs whose snapshot receipt is not the transaction's latest extraction (the extraction
    committed after the run built its snapshot): one late_receipt decide job each."""
    rows = conn.execute(
        f"""
        SELECT r.txn_id, r.decision_id
        FROM decision_run r
        JOIN combined_expense_snapshot s ON s.snapshot_id = r.snapshot_id
        JOIN LATERAL (
            SELECT e.receipt_id, e.created_at FROM receipt_extraction e
            WHERE e.txn_id = r.txn_id AND e.reader_model = %s
            ORDER BY e.created_at DESC, e.receipt_id DESC LIMIT 1
        ) latest ON true
        WHERE {_CURRENT}
          AND latest.created_at <= %s
          AND latest.receipt_id::text IS DISTINCT FROM s.payload -> 'receipt' ->> 'receipt_id'
        ORDER BY r.decision_id
        """,
        (reader_model, _grace(now, settings)),
    ).fetchall()
    return tuple(decide_spec(r["txn_id"], RunTrigger.LATE_RECEIPT, r["decision_id"]) for r in rows)


def stuck_runs(conn: Conn, now: datetime, settings: PipelineSettings) -> tuple[DecisionRun, ...]:
    """Runs with no route after stuck_after_minutes (a lost or crashed investigation) are ended in
    human_review with agent_failed. Returns the runs it ended."""
    cutoff = now - timedelta(minutes=settings.stuck_after_minutes)
    rows = conn.execute(
        f"SELECT r.decision_id FROM decision_run r WHERE r.route IS NULL AND r.created_at <= %s AND {_CURRENT}"
        " ORDER BY r.decision_id",
        (cutoff,),
    ).fetchall()
    ended = []
    for row in rows:
        run = records.fill_route(
            conn, row["decision_id"], route=Route.HUMAN_REVIEW, decided_by=DecidedBy.GUARDRAILS,
            escalation_reasons=("agent_failed",),
        )
        if run is not None:
            ended.append(run)
    return tuple(ended)
