"""
Verifies spec §5/§6's core property: a failed task is diagnosed and
either retried WITH a recorded strategy change, or escalated — never
silently retried unchanged, and never retried forever.
"""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from mission.control import MissionControl  # noqa: E402
from mission.executor import MissionExecutor  # noqa: E402
from mission.fake_db import FakeDB  # noqa: E402
from mission.task_graph import TaskGraph  # noqa: E402


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class FakeRedis:
    def __init__(self):
        self.store = {}
        self.queues = {}

    def set(self, key, value):
        self.store[key] = value

    def get(self, key):
        return self.store.get(key)

    def lpush(self, queue, value):
        self.queues.setdefault(queue, []).append(value)


async def fake_route(task_type, prompt, max_tokens=2000):
    return {"text": "unused in this test"}


def _setup():
    db = FakeDB()
    redis = FakeRedis()
    executor = MissionExecutor(db, redis, fake_route, {"opencode": "queue:opencode"})
    mc = MissionControl(db)
    tg = TaskGraph(db)
    return db, redis, executor, mc, tg


def test_failed_task_with_transient_error_retries_and_stays_pending():
    db, redis, executor, mc, tg = _setup()
    m = run(mc.create_mission("goal", success_criteria=["x"]))
    mid = m["mission_id"]
    task = run(tg.add_task(mid, "flaky network call", max_retries=3))
    tid = task["task_id"]
    run(tg.update_status(tid, "dispatched"))

    hermes_record = {"status": "failed", "last_error": "connection refused", "result": None}
    outcome = run(executor.process_completed_hermes_task(
        tid, hermes_record, {"verdict": "fail"}
    ))

    assert outcome["action"] == "retry"
    updated_task = run(tg.get_task(tid))
    assert updated_task["status"] == "pending"  # re-queued, not stuck
    assert updated_task["retry_count"] == 1


def test_failed_task_with_auth_error_records_strategy_change():
    db, redis, executor, mc, tg = _setup()
    m = run(mc.create_mission("goal", success_criteria=["x"]))
    mid = m["mission_id"]
    task = run(tg.add_task(mid, "call protected API", max_retries=3))
    tid = task["task_id"]
    run(tg.update_status(tid, "dispatched"))

    hermes_record = {"status": "failed", "last_error": "401 unauthorized: invalid api key", "result": None}
    outcome = run(executor.process_completed_hermes_task(tid, hermes_record, {"verdict": "fail"}))

    assert outcome["action"] == "retry"
    assert outcome["diagnosis"]["new_strategy"] is not None
    # Confirm a real decision record exists — not just an in-memory flag
    assert len(db.mission_decisions) == 1


def test_permission_denial_escalates_and_blocks_mission():
    db, redis, executor, mc, tg = _setup()
    m = run(mc.create_mission("goal", success_criteria=["x"]))
    mid = m["mission_id"]
    run(mc.transition(mid, "ANALYZING"))
    run(mc.transition(mid, "PLANNING"))
    run(mc.transition(mid, "EXECUTING"))
    task = run(tg.add_task(mid, "delete production database", max_retries=3))
    tid = task["task_id"]
    run(tg.update_status(tid, "dispatched"))

    hermes_record = {"status": "failed", "last_error": "403 forbidden: permission denied", "result": None}
    outcome = run(executor.process_completed_hermes_task(tid, hermes_record, {"verdict": "fail"}))

    assert outcome["action"] == "escalate"
    updated_task = run(tg.get_task(tid))
    assert updated_task["status"] == "blocked"
    mission = run(mc.get_mission(mid))
    assert mission["status"] == "BLOCKED"


def test_passed_task_records_evidence_and_advances():
    db, redis, executor, mc, tg = _setup()
    m = run(mc.create_mission("goal", success_criteria=["x"]))
    mid = m["mission_id"]
    task = run(tg.add_task(mid, "simple task"))
    tid = task["task_id"]
    run(tg.update_status(tid, "dispatched"))

    hermes_record = {"status": "completed", "result": {"exit_code": 0}}
    outcome = run(executor.process_completed_hermes_task(tid, hermes_record, {"verdict": "pass"}))

    assert outcome["action"] == "advance"
    updated_task = run(tg.get_task(tid))
    assert updated_task["status"] == "passed"
    assert len(db.mission_evidence) == 1


def test_hybrid_mode_routes_specialist_task_to_opencode(monkeypatch):
    # Import canonical services modules explicitly; this test directory also
    # contains a legacy `mission` compatibility package that must not shadow
    # the production executor under test.
    from services.mission.control import MissionControl as CanonicalMissionControl
    from services.mission.executor import MissionExecutor as CanonicalMissionExecutor
    from services.mission.task_graph import TaskGraph as CanonicalTaskGraph

    db = FakeDB()
    redis = FakeRedis()
    executor = CanonicalMissionExecutor(db, redis, fake_route, {"opencode": "queue:opencode"})
    mc = CanonicalMissionControl(db)
    tg = CanonicalTaskGraph(db)
    monkeypatch.setenv("HYBRID_MODE", "1")
    mission = run(mc.create_mission("research goal", success_criteria=["x"]))
    task = run(tg.add_task(
        mission["mission_id"],
        "research a local fixture",
        assigned_executor="research",
    ))

    dispatched = run(executor.dispatch_ready_tasks(mission["mission_id"]))

    assert dispatched == [task["task_id"]]
    queued_id = redis.queues["queue:opencode"][0]
    record = json.loads(redis.store[f"task:{queued_id}"])
    assert record["type"] == "opencode"
    assert record["payload"]["capability_profile"] == "research"
    assert record["payload"]["skill_name"] == "research"
    assert record["payload"]["required_tools"] == ["search", "playwright"]


def test_hybrid_mode_profiles_route_to_opencode_with_approved_capabilities(monkeypatch):
    from services.mission.control import MissionControl as CanonicalMissionControl
    from services.mission.executor import MissionExecutor as CanonicalMissionExecutor
    from services.mission.task_graph import TaskGraph as CanonicalTaskGraph

    monkeypatch.setenv("HYBRID_MODE", "1")
    db = FakeDB()
    redis = FakeRedis()
    executor = CanonicalMissionExecutor(db, redis, fake_route, {"opencode": "queue:opencode"})
    mc = CanonicalMissionControl(db)
    tg = CanonicalTaskGraph(db)

    for profile in ("seo", "marketing", "devops", "browser", "creative", "research"):
        mission = run(mc.create_mission(f"{profile} goal", success_criteria=["x"]))
        task = run(tg.add_task(mission["mission_id"], f"{profile} fixture task", assigned_executor=profile))
        assert run(executor.dispatch_ready_tasks(mission["mission_id"])) == [task["task_id"]]

    assert len(redis.queues["queue:opencode"]) == 6
    records = [json.loads(redis.store[f"task:{task_id}"]) for task_id in redis.queues["queue:opencode"]]
    assert {r["payload"]["capability_profile"] for r in records} == {
        "seo", "marketing", "devops", "browser", "creative", "research"
    }
    assert all(r["type"] == "opencode" for r in records)
