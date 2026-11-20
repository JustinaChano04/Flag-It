"""Intake endpoints. Logic is in service.py and views.py; these only translate HTTP."""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException

from flag_it.contracts.api import BatchRequest, BatchResponse, DecisionHistory, IntakeResponse, TransactionView
from flag_it.contracts.enums import IntakeStatus
from flag_it.db.connection import Conn
from flag_it.deps import get_conn
from flag_it.intake.service import submit_item
from flag_it.intake.views import decision_history, transaction_view
from flag_it.pipeline.jobs import StageQueue, understand_spec
from flag_it.workers.queue import get_job_queue

router = APIRouter(tags=["intake"])

DbConn = Annotated[Conn, Depends(get_conn)]
JobQueue = Annotated[StageQueue, Depends(get_job_queue)]


def _queue_accepted(queue: StageQueue, items) -> None:
    """Queue the understand job for each accepted item. This runs before get_conn commits, so the job may
    start first: its Retry covers that. If the queue is down this raises and the request rolls back."""
    for item in items:
        if item.status is IntakeStatus.ACCEPTED:
            queue.enqueue(understand_spec(item.txn_id))


@router.post("/transactions", status_code=202, response_model=IntakeResponse)
def submit_one(body: Annotated[Any, Body()], conn: DbConn, queue: JobQueue) -> IntakeResponse:
    """The body is validated item by item, as in a batch, so an invalid item is a 202 result, not a 422."""
    item = submit_item(conn, body, 0)
    _queue_accepted(queue, [item])
    return IntakeResponse(item=item)


@router.post("/transactions/batch", status_code=202, response_model=BatchResponse)
def submit_batch(body: BatchRequest, conn: DbConn, queue: JobQueue) -> BatchResponse:
    items = tuple(submit_item(conn, data, index) for index, data in enumerate(body.items))
    _queue_accepted(queue, items)
    return BatchResponse(items=items)


@router.get("/transactions/{txn_id}", response_model=TransactionView)
def get_transaction(txn_id: UUID, conn: DbConn) -> TransactionView:
    view = transaction_view(conn, txn_id)
    if view is None:
        raise HTTPException(status_code=404, detail="unknown txn_id")
    return view


@router.get("/transactions/{txn_id}/decisions", response_model=DecisionHistory)
def get_decisions(txn_id: UUID, conn: DbConn) -> DecisionHistory:
    history = decision_history(conn, txn_id)
    if history is None:
        raise HTTPException(status_code=404, detail="unknown txn_id")
    return history
