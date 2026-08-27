import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from mission.control import InvalidTransition, MissionControl  # noqa: E402
from mission.fake_db import FakeDB  # noqa: E402


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_create_mission_requires_success_criteria():
    mc = MissionControl(FakeDB())
    try:
        run(mc.create_mission("do something", success_criteria=[]))
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_create_mission_starts_in_created_status():
    mc = MissionControl(FakeDB())
    result = run(mc.create_mission("build a thing", success_criteria=["thing exists"]))
    assert result["status"] == "CREATED"
    mission = run(mc.get_mission(result["mission_id"]))
    assert mission["status"] == "CREATED"


def test_valid_transition_succeeds():
    mc = MissionControl(FakeDB())
    m = run(mc.create_mission("goal", success_criteria=["x"]))
    result = run(mc.transition(m["mission_id"], "ANALYZING"))
    assert result["status"] == "ANALYZING"


def test_invalid_transition_rejected():
    """The real bug this guards against: jumping straight from CREATED
    to COMPLETED without ever executing or verifying anything."""
    mc = MissionControl(FakeDB())
    m = run(mc.create_mission("goal", success_criteria=["x"]))
    try:
        run(mc.transition(m["mission_id"], "COMPLETED"))
        assert False, "expected InvalidTransition"
    except InvalidTransition:
        pass


def test_full_valid_path_to_completed():
    mc = MissionControl(FakeDB())
    m = run(mc.create_mission("goal", success_criteria=["x"]))
    mid = m["mission_id"]
    for status in ("ANALYZING", "PLANNING", "EXECUTING", "VERIFYING", "COMPLETED"):
        result = run(mc.transition(mid, status))
        assert result["status"] == status


def test_terminal_states_have_no_outgoing_transitions():
    mc = MissionControl(FakeDB())
    m = run(mc.create_mission("goal", success_criteria=["x"]))
    mid = m["mission_id"]
    run(mc.transition(mid, "CANCELLED"))
    try:
        run(mc.transition(mid, "EXECUTING"))
        assert False, "expected InvalidTransition — CANCELLED is terminal"
    except InvalidTransition:
        pass
