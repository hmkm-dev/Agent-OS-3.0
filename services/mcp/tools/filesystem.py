"""
Filesystem tool adapter — real read/write, hard-scoped to a caller's
workspace via agents.workspace.AgentWorkspace.path_for(). This module
never accepts a raw absolute path from a worker; it only accepts
(agent_id, relative_path) and resolves it itself, so a prompt-injected
"../../etc/passwd" style path cannot escape the sandbox.

Note: agents/workspace.py is copied into services/mcp/agents/ at build
time (see scripts/sync_shared.sh) since each service has its own
isolated Docker build context. Keep the two files in sync, or move to
a shared base image if this grows further.
"""

from __future__ import annotations

import os

from agents.workspace import AgentWorkspace


def read_file(agent_id: str, relative_path: str) -> str:
    ws = AgentWorkspace(agent_id)
    full_path = ws.path_for(relative_path)
    if not os.path.isfile(full_path):
        raise FileNotFoundError(f"{relative_path} not found in agent {agent_id}'s workspace")
    with open(full_path, "r") as f:
        return f.read()


def write_file(agent_id: str, relative_path: str, content: str) -> dict:
    ws = AgentWorkspace(agent_id)
    full_path = ws.path_for(relative_path)
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    with open(full_path, "w") as f:
        f.write(content)
    return {"path": relative_path, "bytes_written": len(content.encode())}


def list_dir(agent_id: str, relative_path: str = ".") -> list[str]:
    ws = AgentWorkspace(agent_id)
    full_path = ws.path_for(relative_path)
    if not os.path.isdir(full_path):
        raise NotADirectoryError(f"{relative_path} is not a directory")
    return sorted(os.listdir(full_path))
