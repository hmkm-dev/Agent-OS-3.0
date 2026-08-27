"""
E2E: proves the full Research -> Creative -> OpenCode handoff chain
actually dispatches real tasks, not just that HandoffManager's unit
logic works against fakes (see tests/unit/test_handoff.py for that).

Requires a live stack with SEARCH_PROVIDER/BRAVE_SEARCH_API_KEY,
OPENROUTER_API_KEY, and R2 configured. SKIPS honestly if HERMES_URL
isn't set — see test_opencode_execution.py's docstring for the same
disclosure, it applies here too.

    HERMES_URL=http://localhost:8000 HERMES_API_KEY=... \
        python3 -m pytest tests/e2e/test_agent_handoff.py -v -s
"""
import os
import time

import httpx
import pytest

HERMES_URL = os.environ.get("HERMES_URL")
HERMES_API_KEY = os.environ.get("HERMES_API_KEY", "")

pytestmark = [pytest.mark.e2e, pytest.mark.external, pytest.mark.skipif(
    not HERMES_URL,
    reason="EXTERNAL_CREDENTIAL_REQUIRED: HERMES_URL not set — live E2E test, see module docstring.",
)]


def _headers():
    return {"x-api-key": HERMES_API_KEY, "Content-Type": "application/json"}


def _poll_task(client: httpx.Client, task_id: str, timeout_s: int = 90) -> dict:
    started = time.time()
    while time.time() - started < timeout_s:
        resp = client.get(f"{HERMES_URL}/tasks/{task_id}", headers=_headers())
        resp.raise_for_status()
        task = resp.json()
        if task["status"] in ("completed", "failed", "cancelled"):
            return task
        time.sleep(3)
    raise TimeoutError(f"task {task_id} did not reach a terminal state within {timeout_s}s")


def test_research_hands_off_to_creative_then_opencode():
    """This is TEST 3 from the spec: Research -> Creative -> OpenCode.
    Confirms HANDOFF_CHAIN in services/hermes/app.py actually threads
    through all three worker types against a live queue/DB, not just
    one hop."""
    with httpx.Client(timeout=30) as client:
        # 1. Kick off research
        r1 = client.post(
            f"{HERMES_URL}/tasks", headers=_headers(),
            json={"type": "research", "payload": {"query": "silver hardware home decor trends"}},
        )
        assert r1.status_code == 200, r1.text
        research_task_id = r1.json()["task_id"]

        research_task = _poll_task(client, research_task_id)
        assert research_task["status"] == "completed", research_task.get("error")

        # 2. Trigger evaluation — this is what dispatches the handoff
        eval1 = client.post(
            f"{HERMES_URL}/tasks/{research_task_id}/evaluate", headers=_headers()
        )
        assert eval1.status_code == 200, eval1.text
        eval1_body = eval1.json()
        assert eval1_body["verdict"] == "pass", (
            f"research task didn't pass evaluation, got handoff not dispatched: {eval1_body}"
        )
        assert "handoff" in eval1_body, "no handoff dispatched after a passing research task"
        creative_task_id = eval1_body["handoff"]["new_task_id"]

        # 3. Wait for the creative task, evaluate it too
        creative_task = _poll_task(client, creative_task_id)
        assert creative_task["status"] == "completed", creative_task.get("error")

        eval2 = client.post(
            f"{HERMES_URL}/tasks/{creative_task_id}/evaluate", headers=_headers()
        )
        eval2_body = eval2.json()
        assert eval2_body["verdict"] == "pass"
        assert "handoff" in eval2_body, "no second handoff — creative -> opencode chain broken"
        opencode_task_id = eval2_body["handoff"]["new_task_id"]

        # 4. Confirm the final hop actually landed as an opencode task
        opencode_task = client.get(f"{HERMES_URL}/tasks/{opencode_task_id}", headers=_headers()).json()
        assert opencode_task["type"] == "opencode"
        assert opencode_task["parent_task_id"] == creative_task_id
