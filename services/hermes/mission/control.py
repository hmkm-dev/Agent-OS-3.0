"""
Mission Control — persistent state for a high-level user goal, per
spec §3. Real Postgres-backed CRUD, not an in-memory placeholder.

Mission states: CREATED -> ANALYZING -> PLANNING -> EXECUTING ->
VERIFYING -> COMPLETED, with BLOCKED/RETRYING/WAITING_APPROVAL/FAILED/
CANCELLED as alternate states. Transitions are validated here — this
module is the only place mission.status should be written from, so
invalid transitions (e.g. CREATED -> COMPLETED, skipping everything)
are rejected rather than silently allowed.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

VALID_STATUSES = {
    "CREATED", "ANALYZING", "PLANNING", "EXECUTING", "VERIFYING",
    "BLOCKED", "RETRYING", "WAITING_APPROVAL", "COMPLETED", "FAILED", "CANCELLED",
}

# Allowed transitions. Not exhaustive of every reasonable path, but
# blocks the clearly-wrong ones (e.g. jumping straight to COMPLETED).
ALLOWED_TRANSITIONS = {
    "CREATED": {"ANALYZING", "CANCELLED"},
    "ANALYZING": {"PLANNING", "BLOCKED", "FAILED", "CANCELLED"},
    "PLANNING": {"EXECUTING", "BLOCKED", "FAILED", "CANCELLED"},
    "EXECUTING": {"VERIFYING", "BLOCKED", "RETRYING", "WAITING_APPROVAL", "FAILED", "CANCELLED"},
    "VERIFYING": {"COMPLETED", "EXECUTING", "FAILED", "BLOCKED"},
    "BLOCKED": {"EXECUTING", "PLANNING", "FAILED", "CANCELLED"},
    "RETRYING": {"EXECUTING", "FAILED", "BLOCKED"},
    "WAITING_APPROVAL": {"EXECUTING", "CANCELLED", "FAILED"},
    "COMPLETED": set(),
    "FAILED": set(),
    "CANCELLED": set(),
}


class InvalidTransition(Exception):
    pass


class MissionControl:
    def __init__(self, db):
        self.db = db

    async def create_mission(self, user_goal: str, objective: str | None = None,
                              constraints: dict | None = None, success_criteria: list | None = None,
                              budget: dict | None = None, deadline=None, priority: int = 5,
                              max_retries: int = 3) -> dict:
        if not success_criteria:
            raise ValueError(
                "success_criteria is required and must be non-empty — a mission without "
                "explicit success criteria can never be verifiably completed, only claimed done"
            )

        mission_id = str(uuid.uuid4())
        await self.db.execute(
            """
            INSERT INTO missions (mission_id, user_goal, objective, constraints, success_criteria,
                                   budget, deadline, priority, current_phase, status, max_retries)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, 'CREATED', 'CREATED', $9)
            """,
            mission_id, user_goal, objective, json.dumps(constraints or {}),
            json.dumps(success_criteria), json.dumps(budget or {}), deadline, priority, max_retries,
        )
        return {"mission_id": mission_id, "status": "CREATED"}

    async def get_mission(self, mission_id: str) -> dict | None:
        row = await self.db.fetchrow("SELECT * FROM missions WHERE mission_id = $1", mission_id)
        return dict(row) if row else None

    async def transition(self, mission_id: str, new_status: str, phase: str | None = None) -> dict:
        if new_status not in VALID_STATUSES:
            raise ValueError(f"unknown mission status '{new_status}'")

        mission = await self.get_mission(mission_id)
        if mission is None:
            raise LookupError(f"mission {mission_id} not found")

        current = mission["status"]
        if new_status not in ALLOWED_TRANSITIONS.get(current, set()) and new_status != current:
            raise InvalidTransition(
                f"cannot transition mission {mission_id} from {current} to {new_status} — "
                f"allowed next states: {sorted(ALLOWED_TRANSITIONS.get(current, set()))}"
            )

        # Compare-and-set the status to prevent two concurrent orchestrators
        # from both applying a transition after validating the same old state.
        row = await self.db.fetchrow(
            "UPDATE missions SET status = $1, current_phase = $2, updated_at = $3 "
            "WHERE mission_id = $4 AND status = $5 RETURNING mission_id",
            new_status, phase or new_status, datetime.now(timezone.utc), mission_id, current,
        )
        if row is None:
            raise InvalidTransition(
                f"concurrent mission transition rejected for {mission_id}: expected status {current}"
            )
        return {"mission_id": mission_id, "status": new_status, "phase": phase or new_status}

    async def transition_if_current(self, mission_id: str, expected_status: str,
                                     new_status: str, phase: str | None = None) -> bool:
        """Atomically transition only if the mission is still in the expected
        state. Prevents two concurrent executors from both completing or
        blocking the same mission."""
        if new_status not in VALID_STATUSES:
            raise ValueError(f"unknown mission status '{new_status}'")
        if new_status not in ALLOWED_TRANSITIONS.get(expected_status, set()) and new_status != expected_status:
            raise InvalidTransition(f"cannot transition mission from {expected_status} to {new_status}")
        row = await self.db.fetchrow(
            """UPDATE missions SET status = $1, current_phase = $2, updated_at = $3
               WHERE mission_id = $4 AND status = $5 RETURNING mission_id""",
            new_status, phase or new_status, datetime.now(timezone.utc), mission_id, expected_status,
        )
        return row is not None

    async def increment_retry(self, mission_id: str) -> int:
        row = await self.db.fetchrow(
            "UPDATE missions SET retry_count = retry_count + 1, updated_at = $1 "
            "WHERE mission_id = $2 RETURNING retry_count",
            datetime.now(timezone.utc), mission_id,
        )
        return row["retry_count"]

    async def set_final_verification(self, mission_id: str, verification: dict) -> None:
        await self.db.execute(
            "UPDATE missions SET final_verification = $1, updated_at = $2 WHERE mission_id = $3",
            json.dumps(verification), datetime.now(timezone.utc), mission_id,
        )

    async def list_active(self) -> list[dict]:
        """Missions not in a terminal state — used to find resumable
        missions after a restart (spec §7)."""
        rows = await self.db.fetch(
            "SELECT * FROM missions WHERE status NOT IN ('COMPLETED', 'FAILED', 'CANCELLED') "
            "ORDER BY priority DESC, created_at ASC"
        )
        return [dict(r) for r in rows]
