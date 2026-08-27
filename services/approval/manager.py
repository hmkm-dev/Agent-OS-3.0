"""
Approval manager — implements the human approval loop.

Flow (per spec §8):
  Agent -> Sensitive Action -> Policy -> REQUIRE_APPROVAL
    -> ApprovalManager.request() -> stored in Postgres, status=pending
    -> notification sent (Telegram)
    -> human calls /approvals/{id}/approve or /deny
    -> ApprovalManager.resolve() updates status, task can proceed/cancel

Hard rule enforced here: an agent can never approve its own action.
`approved_by` must be a human identifier, never an agent_id — this is
checked in `resolve()`, not just documented.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import Optional

import httpx

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")


class ApprovalManager:
    def __init__(self, db):
        """db: an object exposing .execute(query, *args) and .fetchrow(query, *args),
        see services/hermes/db.py for the concrete implementation used in this repo."""
        self.db = db

    async def request(self, task_id: str, agent_id: Optional[str], action: str, reason: str) -> dict:
        approval_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        await self.db.execute(
            """
            INSERT INTO approvals (approval_id, task_id, agent_id, action, reason, requested_at, status)
            VALUES ($1, $2, $3, $4, $5, $6, 'pending')
            """,
            approval_id, task_id, agent_id, action, reason, now,
        )
        await self._notify(approval_id, task_id, action, reason)
        return {"approval_id": approval_id, "status": "pending"}

    async def resolve(self, approval_id: str, decision: str, approved_by: str, agent_ids: set[str]) -> dict:
        """decision: 'approve' or 'deny'. approved_by must be a human identifier."""
        if approved_by in agent_ids:
            raise PermissionError("an agent cannot approve or deny its own action")

        if decision not in ("approve", "deny"):
            raise ValueError("decision must be 'approve' or 'deny'")

        status = "approved" if decision == "approve" else "denied"
        now = datetime.now(timezone.utc)

        row = await self.db.fetchrow(
            """
            UPDATE approvals
            SET status = $1, approved_by = $2, approved_at = $3
            WHERE approval_id = $4 AND status = 'pending'
            RETURNING approval_id, task_id, status
            """,
            status, approved_by, now, approval_id,
        )
        if row is None:
            raise LookupError(f"approval {approval_id} not found or already resolved")
        return dict(row)

    async def _notify(self, approval_id: str, task_id: str, action: str, reason: str):
        if not (TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID):
            print(f"[approval] pending approval {approval_id} for task {task_id} "
                  f"(action={action}) — TELEGRAM_BOT_TOKEN/CHAT_ID not set, no notification sent")
            return
        text = (
            f"🔔 Approval needed\n"
            f"task: {task_id}\naction: {action}\nreason: {reason}\n"
            f"approval_id: {approval_id}\n\n"
            f"POST /approvals/{approval_id}/approve or /deny to resolve."
        )
        async with httpx.AsyncClient(timeout=5) as client:
            try:
                await client.post(
                    f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                    data={"chat_id": TELEGRAM_CHAT_ID, "text": text},
                )
            except httpx.HTTPError as e:
                print(f"[approval] failed to send Telegram notification: {e}")
