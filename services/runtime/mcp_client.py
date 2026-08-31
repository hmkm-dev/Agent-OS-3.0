"""Controlled client for OpenCode-to-MCP capability calls.

This module does not authenticate as a user or carry provider credentials.
The gateway remains the policy and credential boundary. The client only
prevents an execution from requesting a tool outside its Hermes-issued list.
"""
from __future__ import annotations

from typing import Any

import httpx


class MCPCapabilityDenied(PermissionError):
    pass


class MCPClient:
    def __init__(self, allowed_tools: tuple[str, ...] = (), base_url: str | None = None, timeout: float = 30.0, worker_type: str = "opencode"):
        self.allowed_tools = frozenset(allowed_tools)
        self.base_url = (base_url or "http://mcp:8100").rstrip("/")
        self.timeout = timeout
        self.worker_type = worker_type

    async def call(self, tool: str, **params: Any) -> dict[str, Any]:
        if tool not in self.allowed_tools:
            raise MCPCapabilityDenied(f"tool '{tool}' is not approved for this execution")
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            action = params.pop("action", None)
            args = params.pop("args", params)
            if not action or not isinstance(args, dict):
                raise ValueError("MCP calls require action and args")
            response = await client.post(
                f"{self.base_url}/call",
                json={"worker_type": self.worker_type, "tool": tool, "action": action, "args": args},
            )
            response.raise_for_status()
            data = response.json()
            return data if isinstance(data, dict) else {"result": data}
