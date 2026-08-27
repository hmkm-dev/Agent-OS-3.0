"""
MCP gateway — the ONLY thing that talks to real tools. Real
implementation: wired to services/mcp/tools/{search,github,filesystem}.py
and proxies playwright calls to the isolated playwright-service
container. Per-worker-type allowlist enforced before any tool call.
"""

import os
import sys
from typing import Literal

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

sys.path.insert(0, os.path.dirname(__file__))
from tools import filesystem, github, search  # noqa: E402

PLAYWRIGHT_URL = os.environ.get("PLAYWRIGHT_URL", "http://playwright:8200")

app = FastAPI(title="MCP Gateway")

ALLOWLIST = {
    "opencode": {"filesystem", "github"},
    "research": {"search", "playwright"},
    "creative": {"search"},
}


class ToolCall(BaseModel):
    worker_type: Literal["opencode", "research", "creative"]
    tool: Literal["filesystem", "github", "search", "playwright"]
    action: str
    args: dict


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/call")
async def call_tool(req: ToolCall):
    allowed_tools = ALLOWLIST.get(req.worker_type, set())
    if req.tool not in allowed_tools:
        raise HTTPException(
            status_code=403,
            detail=f"worker '{req.worker_type}' is not allowed to use tool '{req.tool}'",
        )

    try:
        if req.tool == "search":
            return await _call_search(req.action, req.args)
        if req.tool == "playwright":
            return await _call_playwright(req.action, req.args)
        if req.tool == "github":
            return await _call_github(req.action, req.args)
        if req.tool == "filesystem":
            return _call_filesystem(req.action, req.args)
    except RuntimeError as e:
        # Adapter raised because it's not configured (missing API key etc.)
        # — surface as 503, not a fabricated result.
        raise HTTPException(status_code=503, detail=str(e))

    raise HTTPException(status_code=400, detail="unknown tool")


async def _call_search(action: str, args: dict) -> dict:
    if action != "query":
        raise HTTPException(status_code=400, detail=f"unsupported search action '{action}'")
    provider = search.get_provider()
    results = await provider.query(args["q"], count=args.get("count", 5))
    return {"results": results}


async def _call_playwright(action: str, args: dict) -> dict:
    async with httpx.AsyncClient(timeout=60) as client:
        if action == "get_text":
            resp = await client.post(f"{PLAYWRIGHT_URL}/get_text", json=args)
        elif action == "navigate":
            resp = await client.post(f"{PLAYWRIGHT_URL}/navigate", json=args)
        else:
            raise HTTPException(status_code=400, detail=f"unsupported playwright action '{action}'")
        resp.raise_for_status()
        return resp.json()


async def _call_github(action: str, args: dict) -> dict:
    if action == "read_repo":
        return await github.read_repo(args["owner"], args["repo"])
    if action == "create_branch":
        return await github.create_branch(args["owner"], args["repo"], args["new_branch"], args.get("base_branch", "main"))
    if action == "commit_file":
        return await github.commit_file(args["owner"], args["repo"], args["branch"], args["path"], args["content"], args["message"])
    if action == "create_pull_request":
        return await github.create_pull_request(args["owner"], args["repo"], args["head"], args["base"], args["title"], args["body"])
    if action == "list_issues":
        return {"issues": await github.list_issues(args["owner"], args["repo"], args.get("state", "open"))}
    raise HTTPException(status_code=400, detail=f"unsupported github action '{action}'")


def _call_filesystem(action: str, args: dict) -> dict:
    if action == "read":
        return {"content": filesystem.read_file(args["agent_id"], args["path"])}
    if action == "write":
        return filesystem.write_file(args["agent_id"], args["path"], args["content"])
    if action == "list":
        return {"entries": filesystem.list_dir(args["agent_id"], args.get("path", "."))}
    raise HTTPException(status_code=400, detail=f"unsupported filesystem action '{action}'")
