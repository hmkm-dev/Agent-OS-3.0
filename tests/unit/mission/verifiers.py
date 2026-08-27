"""
Independent verifiers — per spec §4. A worker's own claim is never
sufficient; each verifier here checks REAL external state (a file on
disk, an HTTP response, an R2 object, a GitHub PR) rather than trusting
the claim text. Every verifier returns a structured result; none of
them can be satisfied by the claim string alone.

Verifiers that need live credentials (GitHubVerifier, ArtifactVerifier
against real R2) raise a clear, typed error when unconfigured — same
pattern as services/mcp/tools/*.py — rather than fabricating a pass.
"""

from __future__ import annotations

import hashlib
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class VerificationResult:
    passed: bool
    detail: dict
    evidence_hash: str | None = None


class VerifierUnavailable(Exception):
    """Raised when a verifier cannot run at all (missing config/creds)
    — this must NEVER be treated as a pass. Callers should record
    VERIFICATION_FAILED (or leave VERIFICATION_PENDING for manual
    follow-up), never VERIFIED, when this is raised."""


class Verifier(ABC):
    @abstractmethod
    async def verify(self, claim: str, context: dict) -> VerificationResult:
        raise NotImplementedError


class FileVerifier(Verifier):
    """Confirms a file actually exists (and optionally contains
    expected content) on disk — real os.path check, not a claim."""

    async def verify(self, claim: str, context: dict) -> VerificationResult:
        path = context.get("path")
        if not path:
            raise VerifierUnavailable("FileVerifier requires context['path']")

        if not os.path.isfile(path):
            return VerificationResult(passed=False, detail={"path": path, "reason": "file does not exist"})

        with open(path, "rb") as f:
            content = f.read()
        file_hash = hashlib.sha256(content).hexdigest()

        expected_substring = context.get("expected_substring")
        if expected_substring and expected_substring.encode() not in content:
            return VerificationResult(
                passed=False,
                detail={"path": path, "reason": "expected_substring not found", "size_bytes": len(content)},
                evidence_hash=file_hash,
            )

        return VerificationResult(
            passed=True, detail={"path": path, "size_bytes": len(content)}, evidence_hash=file_hash,
        )


class HTTPVerifier(Verifier):
    """Real HTTP call — confirms an endpoint actually responds with
    the expected status, not a claimed 'deployment successful'."""

    async def verify(self, claim: str, context: dict) -> VerificationResult:
        url = context.get("url")
        if not url:
            raise VerifierUnavailable("HTTPVerifier requires context['url']")
        expected_status = context.get("expected_status", 200)
        timeout = context.get("timeout_seconds", 10)

        import httpx
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.get(url)
        except (httpx.HTTPError, httpx.TimeoutException) as e:
            return VerificationResult(passed=False, detail={"url": url, "error": str(e)})

        passed = resp.status_code == expected_status
        return VerificationResult(
            passed=passed,
            detail={"url": url, "status_code": resp.status_code, "expected_status": expected_status},
            evidence_hash=hashlib.sha256(resp.content).hexdigest() if resp.content else None,
        )


class TestVerifier(Verifier):
    """Confirms a test/build actually ran with the claimed result —
    reads structured data the worker attached (real exit code, real
    pass/fail counts from OpenCode's RuntimeResult), not free text."""

    async def verify(self, claim: str, context: dict) -> VerificationResult:
        exit_code = context.get("exit_code")
        if exit_code is None:
            raise VerifierUnavailable("TestVerifier requires context['exit_code'] from the actual run")

        passed = exit_code == 0
        detail = {"exit_code": exit_code}
        if "stdout" in context:
            detail["stdout_excerpt"] = context["stdout"][-500:]
        if "tests_passed" in context or "tests_failed" in context:
            detail["tests_passed"] = context.get("tests_passed")
            detail["tests_failed"] = context.get("tests_failed")
            passed = passed and context.get("tests_failed", 0) == 0

        return VerificationResult(passed=passed, detail=detail)


class ArtifactVerifier(Verifier):
    """Confirms an R2 object actually exists — real boto3 head_object
    call, same pattern as services/workers/creative/worker.py."""

    async def verify(self, claim: str, context: dict) -> VerificationResult:
        r2_key = context.get("r2_key")
        bucket = context.get("bucket") or os.environ.get("R2_BUCKET_ARTIFACTS")
        if not r2_key:
            raise VerifierUnavailable("ArtifactVerifier requires context['r2_key']")

        endpoint = os.environ.get("R2_ENDPOINT")
        access_key = os.environ.get("R2_ACCESS_KEY_ID")
        secret_key = os.environ.get("R2_SECRET_ACCESS_KEY")
        if not (endpoint and access_key and secret_key):
            raise VerifierUnavailable("R2 credentials not configured — cannot verify artifact existence")

        import boto3
        client = boto3.client("s3", endpoint_url=endpoint, aws_access_key_id=access_key, aws_secret_access_key=secret_key)
        try:
            head = client.head_object(Bucket=bucket, Key=r2_key)
        except Exception as e:  # boto3 raises a botocore ClientError subtype; caught broadly here
            return VerificationResult(passed=False, detail={"bucket": bucket, "r2_key": r2_key, "error": str(e)})

        return VerificationResult(
            passed=True, detail={"bucket": bucket, "r2_key": r2_key, "size_bytes": head.get("ContentLength")},
        )


class GitHubVerifier(Verifier):
    """Confirms a claimed PR/commit/branch actually exists via a real
    GitHub API call — reuses services/mcp/tools/github.py's adapter
    pattern (GITHUB_TOKEN required, raises clearly if unset)."""

    async def verify(self, claim: str, context: dict) -> VerificationResult:
        owner = context.get("owner")
        repo = context.get("repo")
        pr_number = context.get("pr_number")
        if not (owner and repo and pr_number):
            raise VerifierUnavailable("GitHubVerifier requires context['owner'], ['repo'], ['pr_number']")

        token = os.environ.get("GITHUB_TOKEN")
        if not token:
            raise VerifierUnavailable("GITHUB_TOKEN not configured — cannot verify PR state")

        import httpx
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}",
                headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
            )
        if resp.status_code != 200:
            return VerificationResult(passed=False, detail={"owner": owner, "repo": repo, "pr_number": pr_number, "http_status": resp.status_code})

        pr_data = resp.json()
        expected_branch = context.get("expected_head_branch")
        if expected_branch and pr_data.get("head", {}).get("ref") != expected_branch:
            return VerificationResult(
                passed=False,
                detail={"reason": "branch mismatch", "expected": expected_branch, "actual": pr_data.get("head", {}).get("ref")},
            )

        return VerificationResult(
            passed=True,
            detail={"pr_url": pr_data.get("html_url"), "state": pr_data.get("state"), "merged": pr_data.get("merged")},
        )


class BrowserVerifier(Verifier):
    """Confirms a claimed page state via a real call to the isolated
    playwright-service — reuses the existing get_text endpoint rather
    than a new browser instance."""

    async def verify(self, claim: str, context: dict) -> VerificationResult:
        url = context.get("url")
        expected_text = context.get("expected_text")
        if not url:
            raise VerifierUnavailable("BrowserVerifier requires context['url']")

        playwright_url = os.environ.get("PLAYWRIGHT_URL", "http://playwright:8200")
        import httpx
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(f"{playwright_url}/get_text", json={"url": url, "timeout_ms": 15000})
        except (httpx.HTTPError, httpx.TimeoutException) as e:
            return VerificationResult(passed=False, detail={"url": url, "error": str(e)})

        if resp.status_code != 200:
            return VerificationResult(passed=False, detail={"url": url, "http_status": resp.status_code})

        page_text = resp.json().get("text", "")
        passed = (expected_text in page_text) if expected_text else True
        return VerificationResult(passed=passed, detail={"url": url, "text_length": len(page_text)})


class DatabaseVerifier(Verifier):
    """Confirms a row actually exists matching given criteria — takes
    a fully parameterized query only (never string-interpolates
    caller-supplied values) to avoid SQL injection via a claim/context."""

    def __init__(self, db):
        self.db = db

    async def verify(self, claim: str, context: dict) -> VerificationResult:
        query = context.get("query")
        params = context.get("params", [])
        if not query:
            raise VerifierUnavailable("DatabaseVerifier requires context['query'] (a parameterized SELECT)")
        if not query.strip().upper().startswith("SELECT"):
            raise VerifierUnavailable("DatabaseVerifier only accepts SELECT queries")

        row = await self.db.fetchrow(query, *params)
        passed = row is not None
        return VerificationResult(passed=passed, detail={"query": query, "found": passed})



class SourceReferenceVerifier(Verifier):
    """Independently checks that claimed research sources are reachable.
    A worker's source list is treated only as a claim; this verifier makes
    fresh HTTP requests and records the observed status codes."""

    async def verify(self, claim: str, context: dict) -> VerificationResult:
        sources = context.get("sources") or []
        if not sources:
            raise VerifierUnavailable("SourceReferenceVerifier requires context['sources']")

        import httpx
        observations = []
        passed = True
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            for source in sources[:10]:
                url = source if isinstance(source, str) else source.get("url")
                if not url or not str(url).startswith(("http://", "https://")):
                    observations.append({"url": url, "reachable": False, "reason": "invalid_url"})
                    passed = False
                    continue
                try:
                    resp = await client.get(url, headers={"User-Agent": "AgentOS-Verifier/1.0"})
                    ok = 200 <= resp.status_code < 400
                    observations.append({"url": url, "status_code": resp.status_code, "reachable": ok})
                    passed = passed and ok
                except httpx.HTTPError as e:
                    observations.append({"url": url, "reachable": False, "error": str(e)})
                    passed = False

        return VerificationResult(
            passed=passed,
            detail={"sources_checked": len(observations), "observations": observations},
        )

# Registry mapping evidence kind -> verifier class, so the automatic
# pipeline (verification_pipeline.py) can select the right one without
# every caller needing to know the mapping.
VERIFIER_REGISTRY: dict[str, type[Verifier]] = {
    "test_result": TestVerifier,
    "build_result": TestVerifier,
    "lint_result": TestVerifier,
    "deployment_health_check": HTTPVerifier,
    "http_health_check": HTTPVerifier,
    "service_response": HTTPVerifier,
    "screenshot_ref": ArtifactVerifier,
    "container_health": HTTPVerifier,
    "browser_action_result": BrowserVerifier,
    "source_reference": SourceReferenceVerifier,
}
