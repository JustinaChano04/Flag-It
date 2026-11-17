"""Intake endpoints. Logic is in service.py and views.py; these only translate HTTP."""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException

from flag_it.contracts.api import BatchRequest, BatchResponse, DecisionHistory, IntakeResponse, TransactionView
from flag_it.db.connection import Conn
from flag_it.deps import get_conn
from flag_it.intake.service import submit_item
from flag_it.intake.views import decision_history, transaction_view

router = APIRouter(tags=["intake"])

DbConn = Annotated[Conn, Depends(get_conn)]


@router.post("/transactions", status_code=202, response_model=IntakeResponse)
def submit_one(body: Annotated[Any, Body()], conn: DbConn) -> IntakeResponse:
    """The body is validated item by item, as in a batch, so an invalid item is a 202 result, not a 422."""
    return IntakeResponse(item=submit_item(conn, body, 0))


@router.post("/transactions/batch", status_code=202, response_model=BatchResponse)
def submit_batch(body: BatchRequest, conn: DbConn) -> BatchResponse:
    return BatchResponse(items=tuple(submit_item(conn, data, index) for index, data in enumerate(body.items)))


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
