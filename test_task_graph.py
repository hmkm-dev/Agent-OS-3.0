import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from mission.control import MissionControl  # noqa: E402
from mission.fake_db import FakeDB  # noqa: E402
from mission.task_graph import CyclicDependencyError, TaskGraph  # noqa: E402


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _mission_with_graph():
    db = FakeDB()
    mc = MissionControl(db)
    tg = TaskGraph(db)
    m = run(mc.create_mission("build something", success_criteria=["x"]))
    return db, tg, m["mission_id"]


def test_add_task_rejects_missing_dependency():
    db, tg, mid = _mission_with_graph()
    try:
        run(tg.add_task(mid, "task A", dependencies=["nonexistent-id"]))
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_linear_chain_topological_order():
    db, tg, mid = _mission_with_graph()
    a = run(tg.add_task(mid, "A"))["task_id"]
    b = run(tg.add_task(mid, "B", dependencies=[a]))["task_id"]
    c = run(tg.add_task(mid, "C", dependencies=[b]))["task_id"]

    order = run(tg.topological_order(mid))
    assert order.index(a) < order.index(b) < order.index(c)


def test_diamond_dependency_topological_order():
    """A -> B, A -> C, B+C -> D. D must come after both B and C."""
    db, tg, mid = _mission_with_graph()
    a = run(tg.add_task(mid, "A"))["task_id"]
    b = run(tg.add_task(mid, "B", dependencies=[a]))["task_id"]
    c = run(tg.add_task(mid, "C", dependencies=[a]))["task_id"]
    d = run(tg.add_task(mid, "D", dependencies=[b, c]))["task_id"]

    order = run(tg.topological_order(mid))
    assert order.index(a) < order.index(b)
    assert order.index(a) < order.index(c)
    assert order.index(b) < order.index(d)
    assert order.index(c) < order.index(d)


def test_cycle_detected_and_rejected():
    """The real thing this must catch: A depends on B, B depends on A
    — manually constructed since add_task's own validation prevents
    creating this through the normal API (deps must already exist),
    so we simulate a corrupted/manually-edited graph state."""
    db, tg, mid = _mission_with_graph()
    a = run(tg.add_task(mid, "A"))["task_id"]
    b = run(tg.add_task(mid, "B", dependencies=[a]))["task_id"]
    # Manually corrupt: make A depend on B too, creating a cycle A->B->A
    import json
    db.mission_tasks[a]["dependencies"] = json.dumps([b])

    try:
        run(tg.validate_acyclic(mid))
        assert False, "expected CyclicDependencyError"
    except CyclicDependencyError:
        pass


def test_ready_tasks_only_returns_satisfied_dependencies():
    db, tg, mid = _mission_with_graph()
    a = run(tg.add_task(mid, "A"))["task_id"]
    b = run(tg.add_task(mid, "B", dependencies=[a]))["task_id"]

    ready = run(tg.ready_tasks(mid))
    ready_ids = {t["task_id"] for t in ready}
    assert a in ready_ids
    assert b not in ready_ids, "B should not be ready — A hasn't passed yet"

    run(tg.update_status(a, "dispatched"))
    run(tg.update_status(a, "passed"))
    ready = run(tg.ready_tasks(mid))
    ready_ids = {t["task_id"] for t in ready}
    assert b in ready_ids, "B should be ready now that A passed"
    assert a not in ready_ids, "A should not be ready again — it's no longer pending"


def test_ready_tasks_respects_priority_order():
    db, tg, mid = _mission_with_graph()
    run(tg.add_task(mid, "low", priority=1))
    run(tg.add_task(mid, "high", priority=9))
    ready = run(tg.ready_tasks(mid))
    assert ready[0]["description"] == "high"
