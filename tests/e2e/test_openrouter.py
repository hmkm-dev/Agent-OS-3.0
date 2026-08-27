"""
OpenRouter smoke test: Hermes -> Model Router -> OpenRouter ->
configured model -> response. Does NOT call OpenRouter directly —
goes through Hermes's real `/internal/route` endpoint (the same path
every worker uses), so this also incidentally verifies that endpoint
is reachable and authenticated correctly, not just that OpenRouter
itself works in isolation.

    HERMES_URL=http://localhost:8000 HERMES_API_KEY=... \
        python3 -m pytest tests/e2e/test_openrouter.py -v -s

SKIPS honestly (EXTERNAL_CREDENTIAL_REQUIRED) if HERMES_URL isn't set.
Not executed in the environment that generated this repo — no live
Hermes instance or OPENROUTER_API_KEY exists here. Does not change
model routing — this only calls the existing, unmodified
`services/hermes/model_router.py` code path.
"""
import os

import httpx
import pytest

HERMES_URL = os.environ.get("HERMES_URL")
HERMES_API_KEY = os.environ.get("HERMES_API_KEY", "")

pytestmark = [pytest.mark.e2e, pytest.mark.external, pytest.mark.skipif(
    not HERMES_URL,
    reason="EXTERNAL_CREDENTIAL_REQUIRED: HERMES_URL not set (and Hermes itself needs "
           "OPENROUTER_API_KEY configured) — live E2E test, see module docstring.",
)]


def test_model_router_returns_a_real_completion():
    """A minimal, cheap prompt — this test exists to prove the plumbing
    works (Hermes reaches OpenRouter, auth succeeds, a real model
    responds), not to evaluate model quality."""
    resp = httpx.post(
        f"{HERMES_URL}/internal/route",
        headers={"x-api-key": HERMES_API_KEY, "Content-Type": "application/json"},
        json={"task_type": "fast", "prompt": "Reply with exactly one word: pong", "max_tokens": 10},
        timeout=30,
    )
    assert resp.status_code == 200, (
        f"expected 200 from /internal/route, got {resp.status_code}: {resp.text} — "
        f"if this is 502, OPENROUTER_API_KEY is likely missing/invalid on the Hermes container"
    )
    body = resp.json()
    assert "text" in body and len(body["text"].strip()) > 0, (
        f"expected a non-empty completion, got: {body}"
    )
    assert "model" in body, "response should report which model actually answered"


def test_model_router_rejects_unauthenticated_requests():
    """Confirms Hermes's own auth is enforced on this endpoint too —
    not just /tasks. A missing/wrong API key must not silently succeed."""
    resp = httpx.post(
        f"{HERMES_URL}/internal/route",
        headers={"x-api-key": "definitely-not-the-real-key", "Content-Type": "application/json"},
        json={"task_type": "fast", "prompt": "test", "max_tokens": 5},
        timeout=15,
    )
    assert resp.status_code == 401, (
        f"expected 401 for a wrong API key, got {resp.status_code} — "
        f"if this passes, HERMES_API_KEY enforcement may not be active"
    )
