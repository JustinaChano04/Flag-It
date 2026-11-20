"""Enqueue a JobSpec on Redis with Arq.

ArqStageQueue.enqueue is synchronous so request threads and `asyncio.to_thread` can call it. It keeps one
Redis pool per instance, on a small event loop of its own that runs in a background thread, so a batch or
a file load does not open a connection per job and a call from inside a running loop does not fail
(asyncio.run does). Arq ignores an enqueue whose job ID is already queued or running, or whose result is
still kept, so enqueuing the same job twice is harmless.

Settings: FLAG_IT_REDIS_URL. Without it, intake uses NoOpQueue and nothing runs after a transaction is
accepted; the sweeps and a worker are the way to catch up once Redis is configured.
"""

import asyncio
import logging
import os
import threading
from functools import lru_cache

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

from flag_it.pipeline.jobs import JobSpec, StageQueue

REDIS_URL_ENV = "FLAG_IT_REDIS_URL"

log = logging.getLogger(__name__)


class ArqStageQueue:
    def __init__(self, redis_url: str) -> None:
        self.redis_url = redis_url
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._pool: ArqRedis | None = None

    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        with self._lock:
            if self._loop is None:
                loop = asyncio.new_event_loop()
                threading.Thread(target=loop.run_forever, name="arq-stage-queue", daemon=True).start()
                self._loop = loop
            return self._loop

    async def _enqueue(self, spec: JobSpec) -> None:
        if self._pool is None:
            self._pool = await create_pool(RedisSettings.from_dsn(self.redis_url))
        await self._pool.enqueue_job(spec.name, spec.payload, _job_id=spec.job_id)

    def enqueue(self, spec: JobSpec) -> None:
        asyncio.run_coroutine_threadsafe(self._enqueue(spec), self._ensure_loop()).result()

    def close(self) -> None:
        loop = self._loop
        if loop is None:
            return
        if self._pool is not None:
            asyncio.run_coroutine_threadsafe(self._pool.aclose(), loop).result()
            self._pool = None
        loop.call_soon_threadsafe(loop.stop)
        self._loop = None


class NoOpQueue:
    """Used when FLAG_IT_REDIS_URL is not set: accepts every job and drops it."""

    def enqueue(self, spec: JobSpec) -> None:
        log.debug("no queue configured: dropping job %s", spec.job_id)


@lru_cache
def get_job_queue() -> StageQueue:
    """The FastAPI dependency intake uses to queue the next stage."""
    url = os.environ.get(REDIS_URL_ENV)
    return ArqStageQueue(url) if url else NoOpQueue()


def warn_if_no_queue() -> None:
    """Loud, once, at startup: without a queue a transaction is stored but never decided."""
    if not os.environ.get(REDIS_URL_ENV):
        log.warning(
            "%s is not set: intake stores transactions but queues nothing, so none will be "
            "categorized or decided until Redis and a worker are configured",
            REDIS_URL_ENV,
        )
