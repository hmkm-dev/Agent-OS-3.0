"""
E2E: proves OpenCode actually executes, not just that the adapter
exists. Requires a live Hermes + Redis + opencode-worker stack
(docker compose up) and OPENROUTER_API_KEY configured.

This is NOT run in CI (see .github/workflows/ci.yml — no live stack
there) and was NOT executed in the environment that generated this
repo (no Docker daemon available there — see
docs/GITHUB_DEPLOYMENT_AUDIT.md). Run it yourself against your
deployed stack:

    HERMES_URL=http://localhost:8000 HERMES_API_KEY=... \
        python3 -m pytest tests/e2e/test_opencode_execution.py -v -s

It SKIPS (not passes, not fails) if HERMES_URL isn't set, so it can't
be mistaken for a passing test when nothing was actually exercised.
"""
import json
import os
import time

import httpx
import pytest

HERMES_URL = os.environ.get("HERMES_URL")
HERMES_API_KEY = os.environ.get("HERMES_API_KEY", "")

pytestmark = [pytest.mark.e2e, pytest.mark.external, pytest.mark.skipif(
    not HERMES_URL,
    reason="EXTERNAL_CREDENTIAL_REQUIRED: HERMES_URL not set. "
           "Set HERMES_URL (and HERMES_API_KEY) to point at your deployed stack.",
)]


def _headers():
    return {"x-api-key": HERMES_API_KEY, "Content-Type": "application/json"}


def _poll_task(client: httpx.Client, task_id: str, timeout_s: int = 150) -> dict:
    started = time.time()
    while time.time() - started < timeout_s:
        resp = client.get(f"{HERMES_URL}/tasks/{task_id}", headers=_headers())
        resp.raise_for_status()
        task = resp.json()
        if task["status"] in ("completed", "failed", "cancelled"):
            return task
        time.sleep(3)
    raise TimeoutError(f"task {task_id} did not reach a terminal state within {timeout_s}s")


def test_opencode_creates_a_real_file():
    """The actual acceptance test from the spec: 'Create a small Python
    utility with tests.' Fails loudly if OpenCode didn't really run —
    checks for a non-empty files_changed list and a zero exit code,
    not just 'the task didn't error'."""
    with httpx.Client(timeout=30) as client:
        create_resp = client.post(
            f"{HERMES_URL}/tasks",
            headers=_headers(),
            json={
                "type": "opencode",
                "payload": {
                    "instructions": (
                        "Create a file called add.py with a function add(a, b) "
                        "that returns a + b, and a file test_add.py with a "
                        "pytest test that checks add(2, 3) == 5."
                    )
                },
            },
        )
        assert create_resp.status_code == 200, create_resp.text
        task_id = create_resp.json()["task_id"]

        task = _poll_task(client, task_id)

        assert task["status"] == "completed", (
            f"OpenCode task did not complete — status={task['status']}, "
            f"error={task.get('error')}, result={task.get('result')}"
        )
        result = task["result"]
        assert result["exit_code"] == 0, f"opencode exited non-zero: {result.get('stderr')}"
        assert len(result["files_changed"]) > 0, (
            "OpenCode ran but no files were changed — check whether it actually "
            "wrote add.py/test_add.py or just talked about doing so"
        )
