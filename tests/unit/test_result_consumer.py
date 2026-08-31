import asyncio
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "hermes"))

from result_consumer import ResultConsumer


class FakeRedis:
    def __init__(self):
        self.queues = {"queue:results": [], "queue:results:processing": []}
        self.data = {}

    def lrange(self, key, start, end):
        return list(self.queues.get(key, []))

    def lpush(self, key, value):
        self.queues.setdefault(key, []).insert(0, value)

    def lrem(self, key, count, value):
        values = self.queues.setdefault(key, [])
        for _ in range(count):
            if value in values:
                values.remove(value)

    def get(self, key):
        return self.data.get(key)

    def set(self, key, value, ex=None):
        self.data[key] = value

    def exists(self, key):
        return key in self.data

    def brpoplpush(self, source, destination, timeout):
        values = self.queues.setdefault(source, [])
        if not values:
            return None
        value = values.pop()
        self.queues.setdefault(destination, []).insert(0, value)
        return value


def run(coro):
    return asyncio.run(coro)


def test_recover_requeues_only_terminal_tasks():
    redis = FakeRedis()
    redis.queues["queue:results:processing"] = ["done", "running", "missing"]
    redis.data["task:done"] = json.dumps({"status": "completed"})
    redis.data["task:running"] = json.dumps({"status": "running"})
    consumer = ResultConsumer(redis, lambda task_id: asyncio.sleep(0))

    consumer._recover()

    assert redis.queues["queue:results"] == ["done"]
    assert redis.queues["queue:results:processing"] == []


def test_result_consumer_marks_success_and_skips_duplicate():
    redis = FakeRedis()
    redis.queues["queue:results"] = ["task-1"]
    seen = []

    async def handler(task_id):
        seen.append(task_id)

    consumer = ResultConsumer(redis, handler)
    assert run(consumer.consume_once()) is True
    assert seen == ["task-1"]
    assert redis.exists("result-consumed:task-1")
