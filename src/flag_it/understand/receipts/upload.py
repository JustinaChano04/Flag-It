"""POST /transactions/{txn_id}/receipt: store the file, record it, queue a read_receipt job.

The job is queued before the request's transaction commits (get_conn commits when the request
ends), so the handler treats a missing receipt_file row as "not ready yet" and retries.
Settings: FLAG_IT_REDIS_URL for the queue; the store's settings are in store.py.
"""

import asyncio
import hashlib
import os
from datetime import datetime, timezone
from functools import lru_cache
from typing import Annotated, Protocol
from uuid import UUID, uuid4

from arq import create_pool
from arq.connections import RedisSettings
from fastapi import APIRouter, Depends, HTTPException, UploadFile

from flag_it.contracts.api import ReceiptAccepted
from flag_it.contracts.jobs import ReadReceiptJob
from flag_it.db import records
from flag_it.db.connection import Conn
from flag_it.db.rows import ReceiptFile
from flag_it.deps import get_conn
from flag_it.understand.receipts.store import ReceiptStore, store_from_env
from flag_it.understand.receipts.worker import JOB_NAME

ALLOWED_TYPES = {"application/pdf": ".pdf", "image/jpeg": ".jpg", "image/png": ".png"}
# The first bytes of each type. The declared content type alone is the client's word for it.
MAGIC = {"application/pdf": b"%PDF-", "image/jpeg": b"\xff\xd8\xff", "image/png": b"\x89PNG\r\n\x1a\n"}
MAX_BYTES = 10 * 1024 * 1024


class JobQueue(Protocol):
    def enqueue_read_receipt(self, job: ReadReceiptJob) -> None: ...


class ArqQueue:
    """Queues jobs on Redis with Arq. Plan 21's worker runs them."""

    def __init__(self, redis_url: str):
        self.redis_url = redis_url

    def enqueue_read_receipt(self, job: ReadReceiptJob) -> None:
        # The route runs in a worker thread with no event loop, so asyncio.run is safe here.
        asyncio.run(self._enqueue(job))

    async def _enqueue(self, job: ReadReceiptJob) -> None:
        pool = await create_pool(RedisSettings.from_dsn(self.redis_url))
        try:
            # One job per receipt: Arq ignores a second enqueue with the same job ID.
            await pool.enqueue_job(JOB_NAME, job.model_dump(mode="json"), _job_id=f"{JOB_NAME}:{job.receipt_id}")
        finally:
            await pool.aclose()


@lru_cache
def get_store() -> ReceiptStore:
    return store_from_env()


def get_queue() -> JobQueue:
    return ArqQueue(os.environ["FLAG_IT_REDIS_URL"])


router = APIRouter(tags=["receipts"])


@router.post("/transactions/{txn_id}/receipt", status_code=202, response_model=ReceiptAccepted)
def upload_receipt(
    txn_id: UUID,
    file: UploadFile,
    conn: Annotated[Conn, Depends(get_conn)],
    store: Annotated[ReceiptStore, Depends(get_store)],
    queue: Annotated[JobQueue, Depends(get_queue)],
) -> ReceiptAccepted:
    if conn.execute("SELECT 1 FROM txn WHERE txn_id = %s", (txn_id,)).fetchone() is None:
        raise HTTPException(status_code=404, detail="unknown txn_id")
    content_type = (file.content_type or "").split(";")[0].strip().lower()
    if content_type not in ALLOWED_TYPES:
        raise HTTPException(status_code=415, detail=f"receipts must be one of {sorted(ALLOWED_TYPES)}")
    content = file.file.read(MAX_BYTES + 1)
    if not content:
        raise HTTPException(status_code=422, detail="the file is empty")
    if len(content) > MAX_BYTES:
        raise HTTPException(status_code=413, detail=f"receipts are limited to {MAX_BYTES} bytes")
    if not content.startswith(MAGIC[content_type]):
        raise HTTPException(status_code=415, detail=f"the file's contents are not {content_type}")

    receipt_id = uuid4()
    key = f"receipts/{txn_id}/{receipt_id}{ALLOWED_TYPES[content_type]}"
    store.put(key, content, content_type)
    records.save_receipt_file(
        conn,
        ReceiptFile(
            receipt_id=receipt_id,
            txn_id=txn_id,
            storage_key=key,
            content_type=content_type,
            sha256=hashlib.sha256(content).hexdigest(),
            size_bytes=len(content),
            uploaded_at=datetime.now(timezone.utc),
        ),
    )
    queue.enqueue_read_receipt(ReadReceiptJob(receipt_id=receipt_id, txn_id=txn_id))
    return ReceiptAccepted(receipt_id=receipt_id, txn_id=txn_id)
