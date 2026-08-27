import json

from services.workers.common.base_worker import BaseWorker


class FakeRedis:
    def __init__(self):
        self.lists = {}
        self.values = {}
        self.locks = set()

    def lrange(self, key, start, end):
        return list(self.lists.get(key, []))

    def exists(self, key):
        return key in self.locks

    def get(self, key):
        return self.values.get(key)

    def lpush(self, key, value):
        self.lists.setdefault(key, []).insert(0, value)

    def lrem(self, key, count, value):
        values = self.lists.get(key, [])
        removed = 0
        kept = []
        for item in values:
            if item == value and (count == 0 or removed < count):
                removed += 1
            else:
                kept.append(item)
        self.lists[key] = kept
        return removed


class DummyWorker(BaseWorker):
    worker_type = "test"
    queue_name = "queue:test"

    def handle(self, task):
        return task


def make_worker(redis):
    worker = DummyWorker.__new__(DummyWorker)
    worker.r = redis
    return worker


def test_recovery_skips_live_and_requeues_stale_running_tasks():
    redis = FakeRedis()
    redis.lists["queue:test:processing"] = ["live", "stale", "done"]
    redis.locks.add("task-lock:live")
    redis.values["task:live"] = json.dumps({"status": "running"})
    redis.values["task:stale"] = json.dumps({"status": "running"})
    redis.values["task:done"] = json.dumps({"status": "completed"})

    make_worker(redis)._requeue_inflight()

    assert redis.lists["queue:test:processing"] == ["live"]
    assert redis.lists["queue:test"] == ["stale"]
