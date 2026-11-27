import asyncio
import os
from uuid import uuid4

import pytest

from flag_it.workers import queue as queue_module
from flag_it.workers.queue import ArqStageQueue, NoOpQueue, get_job_queue, warn_if_no_queue
from flag_it.pipeline.jobs import JobSpec, understand_spec


class FakePool:
    def __init__(self):
        self.calls = []

    async def enqueue_job(self, name, payload, _job_id):
        self.calls.append((name, payload, _job_id))

    async def aclose(self):
        pass


def test_enqueue_sends_the_spec_with_its_job_id_and_reuses_one_pool(monkeypatch):
    pool, created = FakePool(), []

    async def fake_create_pool(settings):
        created.append(settings)
        return pool

    monkeypatch.setattr(queue_module, "create_pool", fake_create_pool)
    queue = ArqStageQueue("redis://localhost:6379/0")
    one, two = understand_spec(uuid4()), understand_spec(uuid4())
    queue.enqueue(one)
    queue.enqueue(two)
    assert pool.calls == [(one.name, one.payload, one.job_id), (two.name, two.payload, two.job_id)]
    assert len(created) == 1
    queue.close()


def test_enqueue_works_from_inside_a_running_event_loop(monkeypatch):
    pool = FakePool()

    async def fake_create_pool(settings):
        return pool

    monkeypatch.setattr(queue_module, "create_pool", fake_create_pool)
    queue = ArqStageQueue("redis://localhost:6379/0")
    spec = understand_spec(uuid4())

    async def caller():
        await asyncio.to_thread(queue.enqueue, spec)

    asyncio.run(caller())
    assert pool.calls == [(spec.name, spec.payload, spec.job_id)]
    queue.close()


def test_without_a_redis_url_the_dependency_is_a_no_op_and_the_startup_warns(monkeypatch, caplog):
    monkeypatch.delenv("FLAG_IT_REDIS_URL", raising=False)
    get_job_queue.cache_clear()
    try:
        assert isinstance(get_job_queue(), NoOpQueue)
        get_job_queue().enqueue(JobSpec("understand", {}, "understand:x"))  # accepted and dropped
        with caplog.at_level("WARNING"):
            warn_if_no_queue()
        assert "FLAG_IT_REDIS_URL" in caplog.text
    finally:
        get_job_queue.cache_clear()


def test_with_a_redis_url_the_dependency_is_the_arq_queue(monkeypatch):
    monkeypatch.setenv("FLAG_IT_REDIS_URL", "redis://localhost:6379/0")
    get_job_queue.cache_clear()
    try:
        assert isinstance(get_job_queue(), ArqStageQueue)
    finally:
        get_job_queue.cache_clear()


@pytest.mark.skipif(not os.environ.get("FLAG_IT_TEST_REDIS_URL"), reason="set FLAG_IT_TEST_REDIS_URL to test Redis")
def test_a_real_redis_ignores_a_second_enqueue_of_the_same_job_id():
    from arq import create_pool
    from arq.connections import RedisSettings

    url = os.environ["FLAG_IT_TEST_REDIS_URL"]
    queue = ArqStageQueue(url)
    spec = understand_spec(uuid4())

    async def count() -> int:
        pool = await create_pool(RedisSettings.from_dsn(url))
        try:
            return len([j for j in await pool.queued_jobs() if j.job_id == spec.job_id])
        finally:
            await pool.aclose()

    try:
        queue.enqueue(spec)
        queue.enqueue(spec)
        assert asyncio.run(count()) == 1
    finally:
        queue.close()
