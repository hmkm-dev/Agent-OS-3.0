"""
BaseWorker — shared, real (not stubbed) implementation of the queue
loop, retry/dead-letter handling, idempotency, heartbeat, and graceful
shutdown that every worker (OpenCode/Research/Creative) uses.

Each worker subclasses this and implements `handle(task: dict) -> dict`.
Everything else (queue consumption, retries, timeouts, heartbeat,
signal handling) is implemented once here so it's correct in one
place instead of copy-pasted three times.
"""

from __future__ import annotations

import json
import os
import signal
import socket
import time
import traceback
import uuid
from abc import ABC, abstractmethod

import redis

REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")
RESULTS_QUEUE = "queue:results"
TASK_EVENTS_QUEUE = "queue:task_events"
DEAD_LETTER_QUEUE = "queue:failed"
MAX_RETRIES = int(os.environ.get("MAX_RETRIES", "3"))
TASK_TIMEOUT_SECONDS = int(os.environ.get("TASK_TIMEOUT", "120"))
HEARTBEAT_INTERVAL = 15  # seconds
WORKER_LOCK_TTL = max(TASK_TIMEOUT_SECONDS + 60, 180)


class TimeoutError_(Exception):
    pass


def _alarm_handler(signum, frame):
    raise TimeoutError_("task exceeded TASK_TIMEOUT_SECONDS")


class BaseWorker(ABC):
    worker_type: str
    queue_name: str

    def __init__(self):
        self.r = redis.from_url(REDIS_URL, decode_responses=True)
        self.worker_id = f"{socket.gethostname()}:{os.getpid()}"
        self._shutdown = False
        self._last_heartbeat = 0.0
        signal.signal(signal.SIGTERM, self._handle_shutdown)
        signal.signal(signal.SIGINT, self._handle_shutdown)
        if hasattr(signal, "SIGALRM"):
            signal.signal(signal.SIGALRM, _alarm_handler)

    def _handle_shutdown(self, signum, frame):
        print(f"[{self.worker_type}-worker] received signal {signum}, "
              f"finishing current task then exiting")
        self._shutdown = True

    @abstractmethod
    def handle(self, task: dict) -> dict:
        """Do the actual work. Raise on failure. Return a result dict on success."""
        raise NotImplementedError

    def _emit_event(self, event_type: str, task_id: str, **detail):
        """Publish a bounded lifecycle event without affecting task execution."""
        event = {"event_type": event_type, "task_id": task_id, "worker_type": self.worker_type, **detail}
        try:
            self.r.lpush(TASK_EVENTS_QUEUE, json.dumps(event))
            self.r.ltrim(TASK_EVENTS_QUEUE, 0, 9999)
        except redis.exceptions.RedisError as exc:
            print(f"[{self.worker_type}-worker] lifecycle event skipped: {exc}")

    @property
    def processing_queue(self):
        return f"{self.queue_name}:processing"

    def _requeue_inflight(self):
        """Return only stale, unlocked tasks left by a crashed worker.

        The processing list is shared by replicas of one worker type. A live
        task still owns its Redis lock, so startup/recovery must never steal
        it from another healthy replica.
        """
        for task_id in self.r.lrange(self.processing_queue, 0, -1):
            if self.r.exists(f"task-lock:{task_id}"):
                continue
            raw = self.r.get(f"task:{task_id}")
            if not raw or json.loads(raw).get("status") != "running":
                self.r.lrem(self.processing_queue, 1, task_id)
                continue
            self.r.lpush(self.queue_name, task_id)
            self.r.lrem(self.processing_queue, 1, task_id)
            print(f"[{self.worker_type}-worker] requeued stale in-flight task {task_id}")

    def _heartbeat(self):
        now = time.time()
        if now - self._last_heartbeat < HEARTBEAT_INTERVAL:
            return
        self._last_heartbeat = now
        self.r.set(f"worker:heartbeat:{self.worker_id}", now, ex=HEARTBEAT_INTERVAL * 3)

    def _already_processed(self, task_id: str) -> bool:
        """Idempotency check: if this task_id already has a terminal
        status recorded, don't process it again (handles the case
        where a task is re-delivered after a crash mid-processing)."""
        raw = self.r.get(f"task:{task_id}")
        if not raw:
            return False
        task = json.loads(raw)
        return task.get("status") in ("completed", "failed", "cancelled")

    def process(self, task_id: str):
        if self._already_processed(task_id):
            print(f"[{self.worker_type}-worker] task {task_id} already terminal, skipping (idempotency)")
            return

        # Claim the Redis task atomically before running user code. This
        # closes the concurrent-redelivery race where two workers both read
        # a queued task before either writes status=running. The lease is
        # deliberately bounded; restart reconciliation remains the source of
        # truth for ambiguous in-flight work.
        lock_key = f"task-lock:{task_id}"
        lock_token = uuid.uuid4().hex
        if not self.r.set(lock_key, lock_token, nx=True, ex=WORKER_LOCK_TTL):
            print(f"[{self.worker_type}-worker] task {task_id} is already claimed, skipping duplicate delivery")
            return

        raw = self.r.get(f"task:{task_id}")
        if not raw:
            print(f"[{self.worker_type}-worker] task {task_id} not found, skipping")
            return

        task = json.loads(raw)
        task["status"] = "running"
        task["started_at"] = time.time()
        self._emit_event("started", task_id, status=task["status"])
        task["worker_id"] = self.worker_id
        self.r.set(f"task:{task_id}", json.dumps(task))

        use_alarm = hasattr(signal, "SIGALRM")
        try:
            if use_alarm:
                signal.alarm(TASK_TIMEOUT_SECONDS)
            result = self.handle(task)
            task["status"] = "completed"
            task["result"] = result
            self._emit_event("completed", task_id, status=task["status"])
        except TimeoutError_:
            self._retry_or_fail(task, f"task exceeded {TASK_TIMEOUT_SECONDS}s timeout")
        except Exception as e:
            self._retry_or_fail(task, f"{e}\n{traceback.format_exc()}")
        finally:
            if use_alarm:
                signal.alarm(0)
            task["completed_at"] = time.time()
            self.r.set(f"task:{task_id}", json.dumps(task))
            self.r.lpush(RESULTS_QUEUE, task_id)
            # Delete only our own lease; never clear another worker's lock.
            try:
                if self.r.get(lock_key) == lock_token:
                    self.r.delete(lock_key)
            except redis.exceptions.RedisError:
                # A Redis outage is handled by the normal worker loop; the
                # TTL prevents a permanent lock if deletion cannot happen.
                pass

    def _retry_or_fail(self, task: dict, error: str):
        retries = task.get("retries", 0) + 1
        task["retries"] = retries
        task["last_error"] = error
        if retries >= MAX_RETRIES:
            task["status"] = "failed"
            self._emit_event("failed", task["task_id"], status=task["status"], retries=retries, error=error[-1000:])
            self.r.lpush(DEAD_LETTER_QUEUE, task["task_id"])
            print(f"[{self.worker_type}-worker] task {task['task_id']} failed permanently "
                  f"after {retries} retries -> dead-letter")
        else:
            task["status"] = "queued"
            self._emit_event("retried", task["task_id"], status=task["status"], retries=retries, error=error[-1000:])
            self.r.lpush(self.queue_name, task["task_id"])
            print(f"[{self.worker_type}-worker] task {task['task_id']} failed "
                  f"(attempt {retries}/{MAX_RETRIES}), re-queued")

    def run(self):
        print(f"[{self.worker_type}-worker] {self.worker_id} listening on {self.queue_name} "
              f"(max_retries={MAX_RETRIES}, timeout={TASK_TIMEOUT_SECONDS}s)")
        try:
            self._requeue_inflight()
        except redis.exceptions.RedisError as e:
            print(f"[{self.worker_type}-worker] could not recover in-flight tasks: {e}")
        while not self._shutdown:
            try:
                self._requeue_inflight()
                self._heartbeat()
            except redis.exceptions.RedisError as e:
                print(f"[{self.worker_type}-worker] heartbeat unavailable: {e}")
            try:
                task_id = self.r.brpoplpush(self.queue_name, self.processing_queue, timeout=5)
            except redis.exceptions.RedisError as e:
                print(f"[{self.worker_type}-worker] redis error: {e}, backing off 3s")
                time.sleep(3)
                continue
            if task_id is None:
                continue
            try:
                self.process(task_id)
            except redis.exceptions.RedisError as e:
                print(f"[{self.worker_type}-worker] task {task_id} lost Redis access; leaving it for recovery: {e}")
                time.sleep(3)
                continue
            finally:
                try:
                    self.r.lrem(self.processing_queue, 1, task_id)
                except redis.exceptions.RedisError as e:
                    print(f"[{self.worker_type}-worker] could not acknowledge {task_id}; restart recovery will retry: {e}")
        print(f"[{self.worker_type}-worker] {self.worker_id} shut down cleanly")
