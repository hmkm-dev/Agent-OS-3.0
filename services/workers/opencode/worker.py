"""
OpenCode worker — real queue plumbing via BaseWorker, executes via
AgentRuntime (OpenCodeRuntime) rather than shelling out directly.
Swapping runtimes later (DSH) means changing RUNTIME_NAME, not this file.
"""

import asyncio
import os
import shutil
import subprocess

import httpx

from agent_runtime import get_runtime
from base_worker import BaseWorker
from capability_contract import CapabilityRequest, capability_prompt
from mcp_client import MCPClient

WORKSPACE_ROOT = "/workspace"
RUNTIME_NAME = os.environ.get("AGENT_RUNTIME", "opencode")
DEFAULT_TIMEOUT_SECONDS = int(os.environ.get("OPENCODE_TIMEOUT_SECONDS", "100"))
MAX_TIMEOUT_SECONDS = int(os.environ.get("OPENCODE_MAX_TIMEOUT_SECONDS", "900"))


class OpenCodeWorker(BaseWorker):
    worker_type = "opencode"
    queue_name = "queue:opencode"

    def __init__(self):
        super().__init__()
        self.runtime = get_runtime(RUNTIME_NAME)

    def handle(self, task: dict) -> dict:
        task_id = task["task_id"]
        payload = task["payload"]
        instructions = payload.get("instructions")
        repo_url = payload.get("repo_url")

        if not instructions:
            raise ValueError("payload.instructions is required")

        capability_request = CapabilityRequest.from_payload(payload, task_id=task_id)
        instructions = instructions + capability_prompt(capability_request)
        skill_context = self._skill_context(payload)
        if skill_context:
            instructions += "\n\n" + skill_context
        memory_context = self._memory_context(payload)
        if memory_context:
            instructions += "\n\n" + memory_context

        # Capability calls are explicit data in the Hermes-issued payload.
        # OpenCode cannot invent a new tool permission; MCPClient rejects any
        # call outside the approved request and the gateway checks worker policy.
        capability_results = []
        for call in payload.get("capability_calls", []):
            if not isinstance(call, dict):
                raise ValueError("capability_calls entries must be objects")
            tool = call.get("tool")
            if tool not in capability_request.required_tools:
                raise ValueError(f"capability call '{tool}' was not approved for this execution")
            result = asyncio.run(
                MCPClient(capability_request.required_tools).call(
                    tool, action=call.get("action"), args=call.get("args", {})
                )
            )
            capability_results.append({"tool": tool, "action": call.get("action"), "result": result})

        child_results = []
        for child in payload.get("child_agent_requests", []):
            if not isinstance(child, dict) or not child.get("goal"):
                raise ValueError("child_agent_requests entries require a goal")
            parent_session_id = child.get("parent_session_id") or capability_request.parent_session_id
            if not parent_session_id or capability_request.budget.max_subagents < 1:
                raise ValueError("child agent request requires an approved parent_session_id and max_subagents budget")
            child_results.append(self._request_child(parent_session_id, child))

        workspace_dir = os.path.join(WORKSPACE_ROOT, task_id)
        os.makedirs(workspace_dir, exist_ok=True)

        try:
            if repo_url:
                self._clone(repo_url, workspace_dir)

            requested_timeout = int(payload.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS))
            timeout_seconds = max(1, min(requested_timeout, MAX_TIMEOUT_SECONDS))
            result = self.runtime.execute(instructions, workspace_dir, timeout_seconds=timeout_seconds)

            return {
                "exit_code": result.exit_code,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "files_changed": result.files_changed,
                "duration_seconds": result.duration_seconds,
                "runtime": RUNTIME_NAME,
                "execution_id": capability_request.execution_id,
                "capability_request": capability_request.as_dict(),
                "capability_results": capability_results,
                "skill_context_used": bool(skill_context),
                "memory_context_used": bool(memory_context),
                "child_agent_results": child_results,
            }
        finally:
            shutil.rmtree(workspace_dir, ignore_errors=True)

    def _skill_context(self, payload: dict) -> str:
        skill_name = payload.get("skill_name")
        if not skill_name:
            return ""
        url = os.environ.get("HERMES_URL", "http://hermes:8000").rstrip("/")
        headers = {}
        if os.environ.get("HERMES_API_KEY"):
            headers["x-api-key"] = os.environ["HERMES_API_KEY"]
        try:
            response = httpx.get(
                f"{url}/internal/skills/{skill_name}", headers=headers, timeout=20
            )
            if response.status_code == 200:
                skill = response.json()
                return f"[Approved skill instructions v{skill.get('version', 'unknown')}]\n{skill.get('instructions', '')}"
            print(f"[opencode-worker] approved skill unavailable: HTTP {response.status_code}")
        except httpx.HTTPError as exc:
            print(f"[opencode-worker] approved skill unavailable: {exc}")
        return ""

    def _request_child(self, parent_session_id: str, child: dict) -> dict:
        url = os.environ.get("HERMES_URL", "http://hermes:8000").rstrip("/")
        headers = {}
        if os.environ.get("HERMES_API_KEY"):
            headers["x-api-key"] = os.environ["HERMES_API_KEY"]
        response = httpx.post(
            f"{url}/v3/rlm/{parent_session_id}/children",
            json={"goal": child["goal"], "parent_id": parent_session_id, "context": child.get("context", {})},
            headers=headers,
            timeout=30,
        )
        response.raise_for_status()
        return response.json()

    def _memory_context(self, payload: dict) -> str:
        query = payload.get("memory_query")
        if not query:
            return ""
        url = os.environ.get("HERMES_URL", "http://hermes:8000").rstrip("/")
        headers = {}
        if os.environ.get("HERMES_API_KEY"):
            headers["x-api-key"] = os.environ["HERMES_API_KEY"]
        try:
            response = httpx.post(
                f"{url}/internal/memory/context",
                json={"query": query, "agent_id": payload.get("agent_id") or "opencode", "top_k": 5},
                headers=headers,
                timeout=20,
            )
            if response.status_code == 200:
                return response.json().get("context", "")
            print(f"[opencode-worker] memory context unavailable: HTTP {response.status_code}")
        except httpx.HTTPError as exc:
            print(f"[opencode-worker] memory context unavailable: {exc}")
        return ""

    def _clone(self, repo_url: str, workspace_dir: str):
        subprocess.run(
            ["git", "clone", "--depth", "1", repo_url, workspace_dir],
            check=True, capture_output=True, text=True, timeout=60,
        )


if __name__ == "__main__":
    OpenCodeWorker().run()
