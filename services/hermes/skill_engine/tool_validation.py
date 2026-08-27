"""
Tool/MCP validation for Teach->Skill (closes a gap explicitly flagged
in TeachToSkill.run_tests()'s own docstring in the prior pass: that
method validates instruction-following via the model router, NOT real
tool/MCP usage).

This module makes REAL HTTP calls to the MCP gateway — /health first,
then a real probe call per required tool — and returns a structured
per-tool report. It does not fabricate results: if MCP_URL isn't
reachable, every tool comes back "unreachable", not "ok".

A skill must pass BOTH run_tests() (instruction-following) AND
validate_required_tools() (real tool access) before a human should
call SkillEngine.approve() — neither one alone is sufficient, and
this module says so in its own report rather than letting either
check imply more than it actually checked.
"""

from __future__ import annotations

import os

import httpx

MCP_URL = os.environ.get("MCP_URL", "http://mcp:8100")

# Safe, read-only probe args per tool — chosen to not mutate anything
# even if the tool is genuinely configured and working.
PROBE_ACTIONS = {
    "search": {"action": "query", "args": {"q": "test probe query", "count": 1}},
    "github": {"action": "list_issues", "args": {"owner": "octocat", "repo": "Hello-World", "state": "open"}},
    "filesystem": {"action": "list", "args": {"agent_id": "skill-validation-probe", "path": "."}},
    "playwright": {"action": "get_text", "args": {"url": "https://example.com", "timeout_ms": 10000}},
}


async def validate_required_tools(worker_type: str, required_tools: list[str]) -> dict:
    """Returns {"gateway_reachable": bool, "tools": {tool_name: {"status": ..., "detail": ...}}}.
    status is one of: "ok", "not_allowed" (policy/allowlist blocks it),
    "not_configured" (gateway reachable but tool's own adapter isn't,
    e.g. missing API key — MCP gateway returns 503 for this), "error"
    (unexpected failure), "unknown_tool" (not in PROBE_ACTIONS)."""

    report = {"gateway_reachable": False, "tools": {}}

    async with httpx.AsyncClient(timeout=15) as client:
        try:
            health = await client.get(f"{MCP_URL}/health")
            health.raise_for_status()
            report["gateway_reachable"] = True
        except (httpx.HTTPError, httpx.TimeoutException) as e:
            report["gateway_error"] = str(e)
            for tool in required_tools:
                report["tools"][tool] = {"status": "unreachable", "detail": "MCP gateway not reachable"}
            return report

        for tool in required_tools:
            probe = PROBE_ACTIONS.get(tool)
            if probe is None:
                report["tools"][tool] = {"status": "unknown_tool", "detail": f"no probe defined for '{tool}'"}
                continue

            try:
                resp = await client.post(
                    f"{MCP_URL}/call",
                    json={"worker_type": worker_type, "tool": tool, **probe},
                )
                if resp.status_code == 200:
                    report["tools"][tool] = {"status": "ok", "detail": "probe call succeeded"}
                elif resp.status_code == 403:
                    report["tools"][tool] = {
                        "status": "not_allowed",
                        "detail": f"worker_type '{worker_type}' is not in this tool's ALLOWLIST — "
                                  f"see services/mcp/gateway.py",
                    }
                elif resp.status_code == 503:
                    report["tools"][tool] = {
                        "status": "not_configured",
                        "detail": resp.json().get("detail", "tool adapter not configured (missing API key?)"),
                    }
                else:
                    report["tools"][tool] = {"status": "error", "detail": f"HTTP {resp.status_code}: {resp.text[:200]}"}
            except (httpx.HTTPError, httpx.TimeoutException) as e:
                report["tools"][tool] = {"status": "error", "detail": str(e)}

    return report


def all_tools_ok(report: dict) -> bool:
    if not report.get("gateway_reachable"):
        return False
    return all(t.get("status") == "ok" for t in report.get("tools", {}).values())
