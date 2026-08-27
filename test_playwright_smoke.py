"""
Playwright smoke test — hits the isolated playwright-service directly
(not through the full Hermes/MCP/worker pipeline) to prove the
container itself can actually launch a browser and navigate. Uses
example.com, a stable, credential-free public page — never real
social media accounts, per the requirement that automated tests must
not depend on Pinterest/Instagram credentials.

    PLAYWRIGHT_URL=http://localhost:8200 \
        python3 -m pytest tests/e2e/test_playwright_smoke.py -v -s

SKIPS honestly if PLAYWRIGHT_URL isn't set. Not executed in the
environment that generated this repo (no live container here).
"""
import os

import httpx
import pytest

PLAYWRIGHT_URL = os.environ.get("PLAYWRIGHT_URL")

pytestmark = [pytest.mark.e2e, pytest.mark.external, pytest.mark.skipif(
    not PLAYWRIGHT_URL,
    reason="EXTERNAL_CREDENTIAL_REQUIRED: PLAYWRIGHT_URL not set — live E2E test against the playwright-service container.",
)]


def test_service_health():
    resp = httpx.get(f"{PLAYWRIGHT_URL}/health", timeout=10)
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_navigate_and_extract_title_from_stable_public_page():
    """example.com is IANA-reserved for documentation/testing use and
    has been stable for decades — a deliberate choice so this test
    never depends on a real account or a page that could change/break."""
    resp = httpx.post(
        f"{PLAYWRIGHT_URL}/get_text",
        json={"url": "https://example.com", "timeout_ms": 15000},
        timeout=30,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "Example Domain" in body["text"], (
        f"expected 'Example Domain' text from example.com, got: {body['text'][:200]}"
    )


def test_navigation_failure_is_reported_not_silently_swallowed():
    """A deliberately invalid URL should come back as a real error
    (502/504), not a fake 200 with empty content — proves failure
    handling actually works, not just the happy path."""
    resp = httpx.post(
        f"{PLAYWRIGHT_URL}/get_text",
        json={"url": "https://this-domain-does-not-exist-agentos-test.invalid", "timeout_ms": 8000},
        timeout=20,
    )
    assert resp.status_code in (502, 504), (
        f"expected a real failure status for an unresolvable domain, got {resp.status_code}"
    )
