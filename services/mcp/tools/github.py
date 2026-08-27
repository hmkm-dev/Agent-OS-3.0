"""
GitHub tool adapter — real calls to the GitHub REST API via httpx.
GITHUB_TOKEN lives only here (injected from env), never passed to
workers or agents directly, per spec §20. Write operations
(create_branch, commit, create_pr) must have already passed the
policy engine's GITHUB_WRITE check before this module is called —
this module does not re-check policy itself, that's the gateway's job.
"""

from __future__ import annotations

import base64
import os

import httpx

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
GITHUB_API = "https://api.github.com"


def _headers() -> dict:
    if not GITHUB_TOKEN:
        raise RuntimeError("GITHUB_TOKEN not configured — GitHub tool is unavailable.")
    return {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


async def read_repo(owner: str, repo: str) -> dict:
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(f"{GITHUB_API}/repos/{owner}/{repo}", headers=_headers())
        resp.raise_for_status()
        return resp.json()


async def create_branch(owner: str, repo: str, new_branch: str, base_branch: str = "main") -> dict:
    async with httpx.AsyncClient(timeout=15) as client:
        base_ref = await client.get(
            f"{GITHUB_API}/repos/{owner}/{repo}/git/ref/heads/{base_branch}", headers=_headers()
        )
        base_ref.raise_for_status()
        sha = base_ref.json()["object"]["sha"]

        resp = await client.post(
            f"{GITHUB_API}/repos/{owner}/{repo}/git/refs",
            headers=_headers(),
            json={"ref": f"refs/heads/{new_branch}", "sha": sha},
        )
        resp.raise_for_status()
        return resp.json()


async def commit_file(owner: str, repo: str, branch: str, path: str,
                       content: str, message: str) -> dict:
    async with httpx.AsyncClient(timeout=15) as client:
        existing = await client.get(
            f"{GITHUB_API}/repos/{owner}/{repo}/contents/{path}",
            headers=_headers(), params={"ref": branch},
        )
        sha = existing.json().get("sha") if existing.status_code == 200 else None

        body = {
            "message": message,
            "content": base64.b64encode(content.encode()).decode(),
            "branch": branch,
        }
        if sha:
            body["sha"] = sha

        resp = await client.put(
            f"{GITHUB_API}/repos/{owner}/{repo}/contents/{path}", headers=_headers(), json=body
        )
        resp.raise_for_status()
        return resp.json()


async def create_pull_request(owner: str, repo: str, head: str, base: str,
                               title: str, body: str) -> dict:
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"{GITHUB_API}/repos/{owner}/{repo}/pulls",
            headers=_headers(),
            json={"title": title, "head": head, "base": base, "body": body},
        )
        resp.raise_for_status()
        return resp.json()


async def list_issues(owner: str, repo: str, state: str = "open") -> list[dict]:
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            f"{GITHUB_API}/repos/{owner}/{repo}/issues", headers=_headers(), params={"state": state}
        )
        resp.raise_for_status()
        return resp.json()
