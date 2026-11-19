"""Review endpoints. Logic is in queue.py, detail.py and service.py; these only translate HTTP.

There is no login in v1: the reviewer's name is what the client sends. The API must stay bound
to this machine until login and roles exist (decided 2026-11-17).
"""

from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse, Response
from minio.error import S3Error

from flag_it.contracts.api import ReviewDetail, ReviewIn, ReviewQueue
from flag_it.contracts.review import ReviewOutcome
from flag_it.contracts.rules import RuleSet
from flag_it.db import records
from flag_it.db.connection import Conn
from flag_it.deps import get_conn, get_rules
from flag_it.review.detail import review_detail
from flag_it.review.queue import queue_summaries, review_queue
from flag_it.review.service import InvalidReview, ReviewRefused, record_review
from flag_it.understand.receipts.store import ReceiptStore
from flag_it.understand.receipts.upload import get_store

router = APIRouter(tags=["review"])

DbConn = Annotated[Conn, Depends(get_conn)]
Rules = Annotated[RuleSet, Depends(get_rules)]


@router.get("/reviews/queue", response_model=ReviewQueue)
def get_queue(conn: DbConn, limit: Annotated[int, Query(ge=1, le=500)] = 100) -> ReviewQueue:
    runs = review_queue(conn, limit)
    return ReviewQueue(items=runs, summaries=queue_summaries(conn, runs))


@router.get("/decisions/{decision_id}", response_model=ReviewDetail)
def get_decision(decision_id: UUID, conn: DbConn, rules: Rules) -> ReviewDetail:
    detail = review_detail(conn, decision_id, rules)
    if detail is None:
        raise HTTPException(status_code=404, detail="unknown decision_id")
    return detail


@router.post("/decisions/{decision_id}/review", status_code=201, response_model=ReviewOutcome)
def post_review(decision_id: UUID, body: ReviewIn, conn: DbConn, rules: Rules):
    try:
        return record_review(conn, decision_id, body, rules, now=datetime.now(timezone.utc))
    except InvalidReview as refused:
        # The same shape as FastAPI's own 422s, so the client handles both one way.
        detail = [{"loc": ["body", *field.split(".")], "msg": message} for field, message in refused.errors]
        return JSONResponse(status_code=422, content={"detail": detail})
    except ReviewRefused as refused:
        raise HTTPException(status_code=refused.status, detail=str(refused)) from None


@router.get("/receipts/{receipt_id}/file")
def get_receipt_file(
    receipt_id: UUID, conn: DbConn, store: Annotated[ReceiptStore, Depends(get_store)]
) -> Response:
    """The uploaded file itself, so a reviewer can check what the reader read."""
    try:
        file = records.load_receipt_file(conn, receipt_id)
    except records.NotFound:
        raise HTTPException(status_code=404, detail="unknown receipt_id") from None
    try:
        content = store.get(file.storage_key)
    except (OSError, S3Error):  # LocalStore raises FileNotFoundError; MinioStore raises S3Error
        raise HTTPException(status_code=404, detail="the receipt file is missing from storage") from None
    # The type was checked against the file's first bytes at upload. nosniff stops the browser
    # from guessing another one; inline lets the review screen show it.
    headers = {"X-Content-Type-Options": "nosniff", "Content-Disposition": "inline"}
    return Response(content=content, media_type=file.content_type, headers=headers)
