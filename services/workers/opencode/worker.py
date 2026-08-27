"""
OpenCode worker — real queue plumbing via BaseWorker, executes via
AgentRuntime (OpenCodeRuntime) rather than shelling out directly.
Swapping runtimes later (DSH) means changing RUNTIME_NAME, not this file.
"""

import os
import shutil
import subprocess

from agent_runtime import get_runtime
from base_worker import BaseWorker

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
            }
        finally:
            shutil.rmtree(workspace_dir, ignore_errors=True)

    def _clone(self, repo_url: str, workspace_dir: str):
        subprocess.run(
            ["git", "clone", "--depth", "1", repo_url, workspace_dir],
            check=True, capture_output=True, text=True, timeout=60,
        )


if __name__ == "__main__":
    OpenCodeWorker().run()
