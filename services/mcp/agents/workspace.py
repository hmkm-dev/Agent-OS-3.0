"""
Agent workspace manager — real filesystem isolation, not a convention
that workers are just trusted to follow. `path_for()` is the only
sanctioned way workers should build a file path, and it refuses to
return anything outside the agent's own workspace root.

Layout:
    /workspaces/
        <agent_id>/
            sessions/<session_id>/
            research/
            coding/
            creative/
            artifacts/
            temp/
"""

from __future__ import annotations

import os
import shutil
import time

WORKSPACE_ROOT = os.environ.get("WORKSPACE_ROOT", "/workspaces")
SUBDIRS = ("research", "coding", "creative", "artifacts", "temp")


class WorkspaceError(Exception):
    pass


class AgentWorkspace:
    def __init__(self, agent_id: str):
        self.agent_id = agent_id
        self.root = os.path.join(WORKSPACE_ROOT, agent_id)

    def initialize(self) -> str:
        os.makedirs(self.root, exist_ok=True)
        os.makedirs(os.path.join(self.root, "sessions"), exist_ok=True)
        for sub in SUBDIRS:
            os.makedirs(os.path.join(self.root, sub), exist_ok=True)
        return self.root

    def session_dir(self, session_id: str) -> str:
        d = os.path.join(self.root, "sessions", session_id)
        os.makedirs(d, exist_ok=True)
        return d

    def path_for(self, *parts: str) -> str:
        """The only sanctioned way to build a path inside this agent's
        workspace. Raises WorkspaceError if the resolved path would
        escape the workspace root (e.g. via '..' segments)."""
        candidate = os.path.realpath(os.path.join(self.root, *parts))
        root_real = os.path.realpath(self.root)
        if not candidate.startswith(root_real + os.sep) and candidate != root_real:
            raise WorkspaceError(
                f"path '{os.path.join(*parts)}' resolves outside agent workspace "
                f"({candidate} is not under {root_real}) — refusing"
            )
        return candidate

    def cleanup_temp(self, older_than_seconds: int = 3600):
        temp_dir = os.path.join(self.root, "temp")
        if not os.path.isdir(temp_dir):
            return
        now = time.time()
        for entry in os.listdir(temp_dir):
            full = os.path.join(temp_dir, entry)
            try:
                if now - os.path.getmtime(full) > older_than_seconds:
                    if os.path.isdir(full):
                        shutil.rmtree(full, ignore_errors=True)
                    else:
                        os.remove(full)
            except FileNotFoundError:
                pass

    def archive(self, destination: str) -> str:
        """Tar the whole workspace to `destination` (e.g. before deleting
        an agent). Caller is responsible for uploading it to R2."""
        shutil.make_archive(destination, "gztar", self.root)
        return f"{destination}.tar.gz"
