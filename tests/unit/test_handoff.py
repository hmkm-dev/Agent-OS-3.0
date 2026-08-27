"""
Real tests against HandoffManager's actual logic (create/dispatch/fail),
using a minimal in-memory fake for db + redis rather than mocking the
manager itself. This exercises the real code path, including the
inline-context-size guard and the FK-free schema assumption.
"""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from handoff_manager import HandoffError, HandoffManager  # noqa: E402


class FakeDB:
    def __init__(self):
        self.rows = {}

    async def execute(self, query, *args):
        if "INSERT INTO handoffs" in query:
            (handoff_id, task_id, source_agent, target_agent, context,
             artifacts, requirements, constraints, created_at) = args
            self.rows[handoff_id] = {
                "handoff_id": handoff_id, "task_id": task_id,
                "source_agent": source_agent, "target_agent": target_agent,
                "context": context, "artifacts": artifacts,
                "requirements": requirements, "constraints": constraints,
                "status": "pending",
            }
        elif "UPDATE handoffs SET status = 'accepted'" in query:
            self.rows[args[0]]["status"] = "accepted"
        elif "UPDATE handoffs SET status = 'completed'" in query:
            self.rows[args[0]]["status"] = "completed"
        elif "UPDATE handoffs SET status = 'rejected'" in query:
            self.rows[args[0]]["status"] = "rejected"
        elif "UPDATE handoffs SET status = 'pending', constraints" in query:
            constraints, handoff_id = args
            self.rows[handoff_id]["status"] = "pending"
            self.rows[handoff_id]["constraints"] = constraints

    async def fetchrow(self, query, *args):
        if "WHERE handoff_id = $1" in query:
            return self.rows.get(args[0])
        return None


class FakeRedis:
    def __init__(self):
        self.store = {}
        self.queues = {}

    def set(self, key, value):
        self.store[key] = value

    def lpush(self, queue, value):
        self.queues.setdefault(queue, []).append(value)


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_create_handoff_rejects_oversized_context():
    db = FakeDB()
    mgr = HandoffManager(db, FakeRedis(), {"creative": "queue:creative"})
    big_context = {"data": "x" * 3000}
    try:
        run(mgr.create_handoff("task-1", "research", "creative", big_context))
        assert False, "expected HandoffError"
    except HandoffError:
        pass


def test_create_and_dispatch_handoff_enqueues_task():
    db = FakeDB()
    redis = FakeRedis()
    mgr = HandoffManager(db, redis, {"creative": "queue:creative"})

    created = run(mgr.create_handoff("task-1", "research", "creative", {"summary": "ok"}))
    assert created["status"] == "pending"

    dispatched = run(mgr.dispatch_handoff(created["handoff_id"]))
    assert dispatched["status"] == "accepted"
    assert redis.queues["queue:creative"] == [dispatched["new_task_id"]]

    new_task = json.loads(redis.store[f"task:{dispatched['new_task_id']}"])
    assert new_task["type"] == "creative"
    assert new_task["parent_task_id"] == "task-1"


def test_fail_handoff_retries_then_rejects():
    db = FakeDB()
    mgr = HandoffManager(db, FakeRedis(), {"creative": "queue:creative"})
    created = run(mgr.create_handoff("task-1", "research", "creative", {"summary": "ok"}))
    hid = created["handoff_id"]

    r1 = run(mgr.fail_handoff(hid, "worker crashed"))
    assert r1["status"] == "pending" and r1["retried"] is True

    r2 = run(mgr.fail_handoff(hid, "worker crashed again"))
    assert r2["status"] == "pending" and r2["retried"] is True

    r3 = run(mgr.fail_handoff(hid, "worker crashed a third time"))
    assert r3["status"] == "rejected" and r3["escalate"] is True
