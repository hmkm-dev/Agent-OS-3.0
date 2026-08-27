"""Agent Reach adapter.

Agent Reach is treated as an external capability layer. The gateway invokes
its installed CLI only; credentials and platform-specific sessions stay
outside Agent OS. No fake result is returned when it is unavailable.
"""
from __future__ import annotations
import asyncio, json, os, shutil

COMMAND=os.environ.get("AGENTREACH_BIN", "agent-reach")

async def run(args: list[str], *, timeout: float = 60.0) -> dict:
    if not args or any(not isinstance(x,str) for x in args):
        raise ValueError("args must be a non-empty list of strings")
    binary=shutil.which(COMMAND)
    if not binary:
        raise RuntimeError("Agent Reach CLI is not installed/configured")
    proc=await asyncio.create_subprocess_exec(binary,*args,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
    try:
        stdout,stderr=await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill(); await proc.communicate(); raise RuntimeError("Agent Reach request timed out")
    out=stdout.decode("utf-8",errors="replace"); err=stderr.decode("utf-8",errors="replace")
    if proc.returncode != 0:
        raise RuntimeError(f"Agent Reach failed ({proc.returncode}): {err[-2000:]}")
    try:
        payload=json.loads(out)
    except json.JSONDecodeError:
        payload={"output":out}
    return {"success":True,"result":payload}
