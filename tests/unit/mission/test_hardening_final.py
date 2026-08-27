import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from mission.control import MissionControl
from mission.executor import MissionExecutor
from mission.fake_db import FakeDB
from mission.mission_evaluator import MissionEvaluator
from mission.task_graph import TaskGraph


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
    return {"text": json.dumps({
        "criteria_results": [{"criterion": "x", "met": True, "reasoning": "verified"}],
        "overall_verdict": "COMPLETED",
        "gaps": [],
    })}


def setup():
    db = FakeDB()
    r = FakeRedis()
    mc = MissionControl(db)
    tg = TaskGraph(db)
    ex = MissionExecutor(db, r, fake_route, {"opencode": "queue:opencode"})
    return db, r, mc, tg, ex


def test_pass_result_without_verifiable_context_cannot_mark_task_passed():
    db, r, mc, tg, ex = setup()
    mid = run(mc.create_mission("goal", success_criteria=["x"]))["mission_id"]
    tid = run(tg.add_task(mid, "research task"))["task_id"]
    run(tg.update_status(tid, "dispatched"))
    out = run(ex.process_completed_hermes_task(
        tid, {"status": "completed", "result": {"text": "done"}}, {"verdict": "pass"}
    ))
    assert out["action"] == "await_verification"
    assert run(tg.get_task(tid))["status"] == "verifying"


def test_atomic_dispatch_claim_prevents_duplicate_redis_enqueue():
    db, r, mc, tg, ex = setup()
    mid = run(mc.create_mission("goal", success_criteria=["x"]))["mission_id"]
    run(tg.add_task(mid, "do work", assigned_executor="opencode"))
    first = run(ex.dispatch_ready_tasks(mid))
    second = run(ex.dispatch_ready_tasks(mid))
    assert len(first) == 1
    assert second == []
    assert len(r.queues["queue:opencode"]) == 1


def test_restart_requeues_same_queued_execution_id_without_minting_duplicate():
    db, r, mc, tg, ex = setup()
    mid = run(mc.create_mission("goal", success_criteria=["x"]))["mission_id"]
    tid = run(tg.add_task(mid, "do work", assigned_executor="opencode"))["task_id"]
    hermes_id = "hermes-existing"
    run(tg.update_status(tid, "dispatched", assigned_executor="opencode", hermes_task_id=hermes_id))
    r.set(f"task:{hermes_id}", json.dumps({"task_id": hermes_id, "type": "opencode", "status": "queued"}))
    recovered = run(ex.recover_after_restart())
    assert recovered[0]["action"] == "requeued_same_execution"
    assert r.queues["queue:opencode"] == [hermes_id]
    assert run(tg.get_task(tid))["hermes_task_id"] == hermes_id


def test_restart_marks_running_execution_unknown_instead_of_duplicating():
    db, r, mc, tg, ex = setup()
    mid = run(mc.create_mission("goal", success_criteria=["x"]))["mission_id"]
    tid = run(tg.add_task(mid, "side effect", assigned_executor="opencode"))["task_id"]
    hermes_id = "hermes-running"
    run(tg.update_status(tid, "dispatched", assigned_executor="opencode", hermes_task_id=hermes_id))
    r.set(f"task:{hermes_id}", json.dumps({"task_id": hermes_id, "type": "opencode", "status": "running"}))
    recovered = run(ex.recover_after_restart())
    assert recovered[0]["action"] == "unknown_after_crash"
    assert run(tg.get_task(tid))["status"] == "unknown_after_crash"
    assert r.queues.get("queue:opencode", []) == []


def test_mission_evaluator_rejects_passed_task_without_verified_evidence():
    db, r, mc, tg, ex = setup()
    mid = run(mc.create_mission("goal", success_criteria=["x"]))["mission_id"]
    tid = run(tg.add_task(mid, "task"))["task_id"]
    run(tg.update_status(tid, "dispatched"))
    run(tg.update_status(tid, "passed"))
    mission = run(mc.get_mission(mid))
    result = run(MissionEvaluator(db, fake_route).evaluate_mission(mission))
    assert result["overall_verdict"] == "INCOMPLETE"
    assert "without independently verified evidence" in result["gaps"][0]

def test_source_reference_claim_is_independently_checked_not_auto_verified():
    from mission.verification_pipeline import VerificationPipeline
    db = FakeDB()
    result = run(VerificationPipeline(db).claim_and_verify(
        "m1", "t1", "source_reference", "source exists",
        {"sources": ["not-a-url"]},
    ))
    assert result["status"] == "verification_failed"
    assert run(__import__('mission.evidence', fromlist=['EvidenceEngine']).EvidenceEngine(db).has_verified_evidence_for_task("t1")) is False


def test_failure_recovery_exposes_stable_canonical_taxonomy():
    from mission.failure_recovery import FailureCategory, FailureRecovery
    fr = FailureRecovery(FakeDB())
    assert fr.canonical_class(FailureCategory.AUTH_FAILURE) == "authentication"
    assert fr.canonical_class(FailureCategory.TIMEOUT) == "timeout"
    assert fr.canonical_class(FailureCategory.PERMISSION_DENIAL) == "authorization"
