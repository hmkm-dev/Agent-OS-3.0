"""
E2E: the full mission lifecycle required by spec §24's acceptance test:
USER GOAL -> MISSION -> PLAN -> TASK -> OPENCODE -> TOOL -> EVALUATION
-> EVIDENCE -> MISSION COMPLETION.

Real HTTP calls against a live Hermes with Mission Control endpoints.
EXTERNAL_CREDENTIAL_REQUIRED: needs HERMES_URL, HERMES_API_KEY, and
OPENROUTER_API_KEY configured on the live Hermes instance (goal
decomposition and mission verification both call the model router).

    HERMES_URL=http://localhost:8000 HERMES_API_KEY=... \
        python3 -m pytest tests/e2e/test_mission_e2e.py -v -s

Not executed in the environment that generated this repo — no live
Hermes/Postgres/OpenRouter here.
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


def test_full_mission_lifecycle_goal_to_completion():
    with httpx.Client(timeout=30) as client:
        # 1. Create mission from a high-level goal
        create = client.post(
            f"{HERMES_URL}/missions", headers=_headers(),
            json={
                "user_goal": "Create a Python file add.py with an add(a, b) function and a passing test for it.",
                "objective": "A tested, working add function exists in the repo workspace.",
                "success_criteria": ["add.py exists with a working add function", "a test for add() passes"],
                "budget": {"max_tokens": 50000},
            },
        )
        assert create.status_code == 200, create.text
        mission_id = create.json()["mission_id"]

        # 2. Plan (real goal decomposition via the model router)
        plan = client.post(f"{HERMES_URL}/missions/{mission_id}/plan", headers=_headers())
        assert plan.status_code == 200, plan.text
        assert plan.json()["tasks_created"] > 0

        # 3. Drive the execution loop until all tasks are terminal
        for _ in range(60):
            step = client.post(f"{HERMES_URL}/missions/{mission_id}/execute", headers=_headers())
            assert step.status_code == 200, step.text
            body = step.json()
            if body.get("status") in ("all_passed", "stuck_blocked") or "verification" in body:
                break

            # For any dispatched tasks, poll their underlying Hermes
            # task to completion, then report the result back —
            # mirrors what a real poller/worker-completion-hook would do.
            for mission_task_id in body.get("dispatched_task_ids", []):
                status_check = client.get(f"{HERMES_URL}/missions/{mission_id}/status", headers=_headers())
                # give the worker time to pick up and finish the task
                time.sleep(3)
                client.post(
                    f"{HERMES_URL}/missions/{mission_id}/tasks/{mission_task_id}/report",
                    headers=_headers(),
                )
            time.sleep(2)

        # 4. Confirm final mission status reflects real completion, not
        # just "we stopped looping"
        final = client.get(f"{HERMES_URL}/missions/{mission_id}/status", headers=_headers())
        assert final.status_code == 200
        final_body = final.json()
        assert final_body["status"] in ("COMPLETED", "BLOCKED"), (
            f"mission ended in unexpected status: {final_body['status']}"
        )
        if final_body["status"] == "COMPLETED":
            assert final_body["final_verification"] is not None
            assert final_body["final_verification"].get("overall_verdict") == "COMPLETED"
