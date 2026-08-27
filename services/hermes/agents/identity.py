"""
Agent identity — persistent profile, preferences, capabilities,
constraints, history. Backed by the `agents` table (migrations/001_init.sql).
Real CRUD implementation, not a stub.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone


class AgentIdentity:
    def __init__(self, db):
        self.db = db

    async def create(self, name: str, role: str, profile: dict | None = None,
                      preferences: dict | None = None, capabilities: list | None = None,
                      constraints: dict | None = None) -> dict:
        agent_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        await self.db.execute(
            """
            INSERT INTO agents (agent_id, name, role, profile, preferences, capabilities, constraints, created_at, updated_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $8)
            """,
            agent_id, name, role,
            json.dumps(profile or {}), json.dumps(preferences or {}),
            json.dumps(capabilities or []), json.dumps(constraints or {}),
            now,
        )
        return {"agent_id": agent_id, "name": name, "role": role}

    async def get(self, agent_id: str) -> dict | None:
        row = await self.db.fetchrow("SELECT * FROM agents WHERE agent_id = $1", agent_id)
        return dict(row) if row else None

    async def update_preferences(self, agent_id: str, preferences: dict) -> None:
        await self.db.execute(
            "UPDATE agents SET preferences = $1, updated_at = $2 WHERE agent_id = $3",
            json.dumps(preferences), datetime.now(timezone.utc), agent_id,
        )

    async def list_by_role(self, role: str) -> list[dict]:
        rows = await self.db.fetch("SELECT * FROM agents WHERE role = $1", role)
        return [dict(r) for r in rows]
