"""
Agent Handoff — Phase B. Real orchestration, not schema-only.

Hermes is the only caller of create_handoff()/dispatch_handoff() —
workers never invoke another worker directly (spec §B: "A worker
should not arbitrarily invoke another worker"). Enforced here by
convention (this module has no HTTP-facing route reachable from
workers) plus by the MCP allowlist never granting workers access to
Hermes's task-creation endpoint.

Context is passed by reference: `context_reference` points at a
Postgres task_id/memory_id, `artifact_references` point at R2 keys.
Raw blobs are never embedded directly in the handoff payload — this
is enforced by `create_handoff()` rejecting oversized inline content.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

MAX_INLINE_CONTEXT_BYTES = 2000  # forces reference-passing for anything bigger
DEFAULT_HANDOFF_TIMEOUT_SECONDS = 180
MAX_HANDOFF_RETRIES = 2


class HandoffError(Exception):
    pass


class HandoffManager:
    def __init__(self, db, redis_client, queues: dict[str, str]):
        self.db = db
        self.r = redis_client
        self.queues = queues  # {"opencode": "queue:opencode", ...}

    async def create_handoff(self, task_id: str, source_worker: str, target_worker: str,
                              context: dict, artifact_references: list[str] | None = None,
                              requirements: dict | None = None, constraints: dict | None = None) -> dict:
        context_str = json.dumps(context)
        if len(context_str.encode()) > MAX_INLINE_CONTEXT_BYTES:
            raise HandoffError(
                f"handoff context is {len(context_str.encode())} bytes, exceeds the "
                f"{MAX_INLINE_CONTEXT_BYTES}-byte inline limit. Store the large content "
                "as a memory_record or R2 artifact and pass its id/key in context instead "
                "of the raw payload — this is enforced, not just documented."
            )

        handoff_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        await self.db.execute(
            """
            INSERT INTO handoffs (handoff_id, task_id, source_agent, target_agent, context,
                                   artifacts, requirements, constraints, status, created_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, 'pending', $9)
            """,
            handoff_id, task_id, source_worker, target_worker,
            context_str, json.dumps(artifact_references or []),
            json.dumps(requirements or {}), json.dumps(constraints or {}), now,
        )
        return {"handoff_id": handoff_id, "status": "pending"}

    async def dispatch_handoff(self, handoff_id: str) -> dict:
        """Creates a new task for the target worker and enqueues it,
        carrying the handoff context forward. This is the only place
        a new task gets created as a result of another task's output —
        Hermes calls this, not the worker."""
        row = await self.db.fetchrow("SELECT * FROM handoffs WHERE handoff_id = $1", handoff_id)
        if row is None:
            raise HandoffError(f"handoff {handoff_id} not found")
        if row["status"] != "pending":
            raise HandoffError(f"handoff {handoff_id} is not pending (status={row['status']})")

        target_worker = row["target_agent"]
        context = json.loads(row["context"])
        artifacts = json.loads(row["artifacts"])

        new_task_id = str(uuid.uuid4())
        task_record = {
            "task_id": new_task_id,
            "parent_task_id": row["task_id"],
            "type": target_worker,
            "payload": {**context, "artifact_references": artifacts, "handoff_id": handoff_id},
            "status": "queued",
            "created_at": datetime.now(timezone.utc).timestamp(),
            "retries": 0,
        }
        self.r.set(f"task:{new_task_id}", json.dumps(task_record))
        self.r.lpush(self.queues[target_worker], new_task_id)

        await self.db.execute(
            "UPDATE handoffs SET status = 'accepted' WHERE handoff_id = $1", handoff_id
        )
        return {"handoff_id": handoff_id, "new_task_id": new_task_id, "status": "accepted"}

    async def complete_handoff(self, handoff_id: str) -> None:
        await self.db.execute(
            "UPDATE handoffs SET status = 'completed' WHERE handoff_id = $1", handoff_id
        )

    async def fail_handoff(self, handoff_id: str, reason: str) -> dict:
        row = await self.db.fetchrow("SELECT * FROM handoffs WHERE handoff_id = $1", handoff_id)
        if row is None:
            raise HandoffError(f"handoff {handoff_id} not found")

        retries = json.loads(row.get("constraints") or "{}").get("_handoff_retries", 0)
        if retries >= MAX_HANDOFF_RETRIES:
            await self.db.execute(
                "UPDATE handoffs SET status = 'rejected' WHERE handoff_id = $1", handoff_id
            )
            return {"handoff_id": handoff_id, "status": "rejected", "reason": reason, "escalate": True}

        constraints = json.loads(row["constraints"] or "{}")
        constraints["_handoff_retries"] = retries + 1
        await self.db.execute(
            "UPDATE handoffs SET status = 'pending', constraints = $1 WHERE handoff_id = $2",
            json.dumps(constraints), handoff_id,
        )
        return {"handoff_id": handoff_id, "status": "pending", "retried": True}

    async def receive_handoff(self, task_id: str) -> dict | None:
        """Called by the target worker's task processing path (via the
        task payload's `handoff_id`) to fetch the full handoff record
        if it needs the original requirements/constraints beyond what
        was copied into the task payload."""
        row = await self.db.fetchrow(
            "SELECT * FROM handoffs WHERE task_id = (SELECT parent_task_id FROM tasks WHERE task_id = $1)",
            task_id,
        )
        return dict(row) if row else None
