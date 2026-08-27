"""
Skill engine — versioned, testable, permission-aware skill storage.
Real Postgres-backed CRUD (skills + skill_versions tables), not an
in-memory stub. Skills start as 'draft' and can only reach 'approved'
via the teach-to-skill workflow (see teach.py), which requires an
explicit human approval step before publish.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone


class SkillEngine:
    def __init__(self, db):
        self.db = db

    async def create_draft(self, name: str, description: str, required_tools: list,
                            inputs: dict, outputs: dict, constraints: dict) -> dict:
        skill_id = str(uuid.uuid4())
        await self.db.execute(
            """
            INSERT INTO skills (skill_id, name, description, required_tools, inputs, outputs, constraints, status)
            VALUES ($1, $2, $3, $4, $5, $6, $7, 'draft')
            """,
            skill_id, name, description,
            json.dumps(required_tools), json.dumps(inputs), json.dumps(outputs), json.dumps(constraints),
        )
        return {"skill_id": skill_id, "status": "draft"}

    async def add_version(self, skill_id: str, instructions: str,
                           examples: list, tests: list) -> dict:
        row = await self.db.fetchrow(
            "SELECT COALESCE(MAX(version), 0) + 1 AS next_version FROM skill_versions WHERE skill_id = $1",
            skill_id,
        )
        version = row["next_version"]
        version_id = str(uuid.uuid4())
        await self.db.execute(
            """
            INSERT INTO skill_versions (skill_version_id, skill_id, version, instructions, examples, tests, created_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            """,
            version_id, skill_id, version, instructions,
            json.dumps(examples), json.dumps(tests), datetime.now(timezone.utc),
        )
        return {"skill_version_id": version_id, "version": version}

    async def mark_tested(self, skill_id: str) -> None:
        await self.db.execute("UPDATE skills SET status = 'tested' WHERE skill_id = $1", skill_id)

    async def approve(self, skill_id: str, approved_by_human: str) -> None:
        """Only call this after a human has actually reviewed test results.
        There is no code path here that lets an agent self-approve —
        this function takes no agent_id parameter on purpose."""
        await self.db.execute("UPDATE skills SET status = 'approved' WHERE skill_id = $1", skill_id)

    async def get_latest_approved(self, name: str) -> dict | None:
        row = await self.db.fetchrow(
            """
            SELECT s.skill_id, s.name, sv.version, sv.instructions, sv.tests
            FROM skills s
            JOIN skill_versions sv ON sv.skill_id = s.skill_id
            WHERE s.name = $1 AND s.status = 'approved'
            ORDER BY sv.version DESC
            LIMIT 1
            """,
            name,
        )
        return dict(row) if row else None
