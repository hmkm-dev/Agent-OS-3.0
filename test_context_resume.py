"""
Verifies spec §7/§9's requirement: a mission can resume using ONLY
persisted state (Postgres + STATE.json), simulating a process/Docker
restart by constructing a fresh ContextManager against the same
FakeDB — nothing here depends on any in-memory state carried over
from a "previous" object, which is the actual property being tested.
"""
import asyncio
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Point MissionArtifacts at a throwaway temp dir for this test run,
# BEFORE importing anything that reads MISSIONS_ROOT at import time.
_TMP_MISSIONS_ROOT = tempfile.mkdtemp()
os.environ["MISSIONS_ROOT"] = _TMP_MISSIONS_ROOT

from mission.artifacts import MissionArtifacts  # noqa: E402
from mission.context import ContextManager  # noqa: E402
from mission.control import MissionControl  # noqa: E402
from mission.fake_db import FakeDB  # noqa: E402
from mission.task_graph import TaskGraph  # noqa: E402


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


async def fake_route(task_type, prompt, max_tokens=2000):
    return {"text": "Summary: made progress on task A, hit an auth error on task B, retrying with new strategy."}


def test_resume_after_simulated_restart_uses_only_persisted_state():
    db = FakeDB()
    mc = MissionControl(db)
    tg = TaskGraph(db)
    cm = ContextManager(db, fake_route, lambda mid: MissionArtifacts(mid))

    m = run(mc.create_mission("build a thing", success_criteria=["thing works"]))
    mid = m["mission_id"]
    run(tg.add_task(mid, "task A"))
    run(mc.transition(mid, "ANALYZING"))
    run(mc.transition(mid, "PLANNING"))
    run(mc.transition(mid, "EXECUTING"))

    # Force a context summary to be written (simulates a long-running
    # mission that hit the summarization threshold before "restarting")
    long_progress = "x" * 9000
    summary = run(cm.maybe_summarize(mid, long_progress))
    assert summary is not None

    # Simulate restart: construct a BRAND NEW ContextManager (nothing
    # carried over in memory), resume purely from db + disk.
    fresh_cm = ContextManager(db, fake_route, lambda m_id: MissionArtifacts(m_id))
    resumed = run(fresh_cm.resume_context(mid))

    assert resumed["mission"]["status"] == "EXECUTING"
    assert len(resumed["tasks"]) == 1
    assert resumed["context_summary"] is not None
    assert "auth error" in resumed["context_summary"]


def test_resume_with_no_prior_summary_still_returns_structured_state():
    """A mission that never hit the summarization threshold should
    still resume cleanly — context_summary is None, not an error."""
    db = FakeDB()
    mc = MissionControl(db)
    cm = ContextManager(db, fake_route, lambda mid: MissionArtifacts(mid))

    m = run(mc.create_mission("small goal", success_criteria=["done"]))
    resumed = run(cm.resume_context(m["mission_id"]))

    assert resumed["mission"] is not None
    assert resumed["context_summary"] is None
