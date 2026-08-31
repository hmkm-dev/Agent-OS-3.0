"""Hermes-owned result consumption for the existing Redis worker contract."""
from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any


class ResultConsumer:
    def __init__(self, redis_client: Any, handler: Callable[[str], Awaitable[None]], queue: str = "queue:results"):
        self.redis = redis_client
        self.handler = handler
        self.queue = queue
        self.processing = f"{queue}:processing"
        self._stopped = False

    async def run(self) -> None:
        self._recover()
        while not self._stopped:
            await self.consume_once()

    async def consume_once(self) -> bool:
        """Consume one result; return False when the queue is empty."""
        try:
            task_id = await asyncio.to_thread(
                self.redis.brpoplpush, self.queue, self.processing, 1
            )
            if task_id is None:
                return False
            marker = f"result-consumed:{task_id}"
            if self.redis.exists(marker):
                self.redis.lrem(self.processing, 1, task_id)
                return True
            await self.handler(task_id)
            self.redis.set(marker, "1", ex=86400)
            self.redis.lrem(self.processing, 1, task_id)
            return True
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # Leave the item in the processing list. A later restart can
            # retry it; no result is silently acknowledged on failure.
            print(f"[hermes] result consumer error: {exc}")
            await asyncio.sleep(1)
            return False

    def _recover(self) -> None:
        for task_id in self.redis.lrange(self.processing, 0, -1):
            raw = self.redis.get(f"task:{task_id}")
            if not raw:
                self.redis.lrem(self.processing, 1, task_id)
                continue
            try:
                status = json.loads(raw).get("status")
            except (TypeError, json.JSONDecodeError):
                status = None
            if status in {"completed", "failed"}:
                self.redis.lpush(self.queue, task_id)
            self.redis.lrem(self.processing, 1, task_id)

    def stop(self) -> None:
        self._stopped = True
