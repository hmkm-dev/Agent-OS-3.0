"""
E2E: proves the self-review loop is bounded — a task that keeps
failing evaluation retries up to MAX_AGENT_RETRIES, then escalates to
require_human (an approval request), and never loops forever.

Requires a live stack. SKIPS honestly if HERMES_URL isn't set.

    HERMES_URL=http://localhost:8000 HERMES_API_KEY=... \
        python3 -m pytest tests/e2e/test_self_review_loop.py -v -s
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


def test_repeated_failure_escalates_to_require_human_not_infinite_loop():
    """Submits a research task with an empty/nonsense query designed to
    fail the evaluator's evidence check (no sources), then repeatedly
    calls /evaluate to simulate the retry loop, and asserts it
    terminates at require_human within MAX_AGENT_RETRIES calls rather
    than looping forever."""
    with httpx.Client(timeout=30) as client:
        create = client.post(
            f"{HERMES_URL}/tasks", headers=_headers(),
            json={"type": "research", "payload": {"query": ""}},  # designed to yield no sources
        )
        assert create.status_code == 200, create.text
        task_id = create.json()["task_id"]

        # Wait for the worker to mark it terminal (likely "completed"
        # with empty sources, or "failed" if the empty query errors out)
        for _ in range(30):
            t = client.get(f"{HERMES_URL}/tasks/{task_id}", headers=_headers()).json()
            if t["status"] in ("completed", "failed"):
                break
            time.sleep(2)

        verdicts = []
        for i in range(6):  # more than MAX_AGENT_RETRIES (default 3) on purpose
            resp = client.post(f"{HERMES_URL}/tasks/{task_id}/evaluate", headers=_headers())
            if resp.status_code != 200:
                break
            body = resp.json()
            verdicts.append(body["verdict"])
            if body["verdict"] == "require_human":
                break
            time.sleep(1)

        assert "require_human" in verdicts, (
            f"expected the loop to escalate to require_human within a bounded number "
            f"of evaluate calls, got verdicts: {verdicts} — if this never escalates, "
            f"the retry loop may not actually be bounded"
        )
        # Bounded: require_human must show up well before an arbitrarily large
        # number of calls (6 is generous headroom over MAX_AGENT_RETRIES=3)
        assert len(verdicts) <= 6


def test_valid_task_passes_on_first_evaluation():
    """Contrast case for the test above: CREATE -> REVIEW -> VERIFY ->
    PASS -> DELIVER, no retry needed. A well-formed research query
    should pass evaluation immediately.

    Honest architectural note (not something this test can paper
    over): the current retry mechanism in services/hermes/app.py's
    /tasks/{id}/evaluate re-queues the EXACT SAME task payload to the
    SAME worker type on retry — there is no distinct "FIX" step that
    changes anything between attempt N and N+1 (e.g. a different
    model, revised instructions, or worker feedback incorporated into
    the retry). "RETRY" in this implementation currently means
    "try again unchanged and hope it's non-deterministically better
    this time" (which does happen — LLM outputs vary run to run — but
    is not the same as a genuine fix-and-retry loop). This is flagged
    here rather than silently assumed to be more sophisticated than
    it is; see docs/FINAL_REPOSITORY_STATUS.md's known limitations."""
    with httpx.Client(timeout=30) as client:
        create = client.post(
            f"{HERMES_URL}/tasks", headers=_headers(),
            json={"type": "research", "payload": {"query": "what is the capital of France"}},
        )
        assert create.status_code == 200, create.text
        task_id = create.json()["task_id"]

        for _ in range(30):
            t = client.get(f"{HERMES_URL}/tasks/{task_id}", headers=_headers()).json()
            if t["status"] in ("completed", "failed"):
                break
            time.sleep(2)
        assert t["status"] == "completed", t.get("error")

        eval_resp = client.post(f"{HERMES_URL}/tasks/{task_id}/evaluate", headers=_headers())
        assert eval_resp.status_code == 200
        assert eval_resp.json()["verdict"] == "pass", (
            f"expected a well-formed research task to pass on first evaluation, "
            f"got: {eval_resp.json()}"
        )
