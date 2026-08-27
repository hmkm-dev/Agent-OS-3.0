"""
Skill -> Routine workflow: turns an approved skill into a scheduled
routine. This module owns the `routines` table; the actual cron
trigger lives in n8n (Phase 10 of the README) and calls back into
Hermes's /tasks endpoint with the routine's skill + parameters — n8n
never re-implements orchestration logic itself, per spec §29.
"""

from __future__ import annotations

import uuid


class RoutineManager:
    def __init__(self, db):
        self.db = db

    async def create(self, skill_id: str, schedule_cron: str, parameters: dict,
                      enabled: bool = False) -> dict:
        """enabled defaults to False — a routine derived from a freshly
        approved skill should be reviewed once before it starts firing
        unattended."""
        routine_id = str(uuid.uuid4())
        await self.db.execute(
            """
            INSERT INTO routines (routine_id, skill_id, schedule, parameters, enabled)
            VALUES ($1, $2, $3, $4, $5)
            """,
            routine_id, skill_id, schedule_cron, __import__("json").dumps(parameters), enabled,
        )
        return {"routine_id": routine_id, "enabled": enabled}

    async def enable(self, routine_id: str) -> None:
        await self.db.execute("UPDATE routines SET enabled = true WHERE routine_id = $1", routine_id)

    async def disable(self, routine_id: str) -> None:
        await self.db.execute("UPDATE routines SET enabled = false WHERE routine_id = $1", routine_id)

    async def record_run(self, routine_id: str, next_run) -> None:
        await self.db.execute(
            "UPDATE routines SET last_run = now(), next_run = $1 WHERE routine_id = $2",
            next_run, routine_id,
        )

    async def list_enabled(self) -> list[dict]:
        rows = await self.db.fetch("SELECT * FROM routines WHERE enabled = true")
        return [dict(r) for r in rows]
