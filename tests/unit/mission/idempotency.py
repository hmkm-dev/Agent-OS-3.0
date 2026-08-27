"""
Idempotency — per spec §8. Before repeating an external side effect
(GitHub PR creation, file write, upload, browser submission), check
whether this exact (task_id, idempotency_key) already happened. Real
Postgres uniqueness constraint on idempotency_key (see
migrations/003_evidence_verification.sql's PRIMARY KEY) enforces this
even under concurrent execution, not just an application-level check
that a race condition could slip past.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone


def make_idempotency_key(task_id: str, side_effect_kind: str, payload: dict) -> str:
    """Deterministic key: same task + same side effect + same payload
    always produces the same key, so a genuine retry of the identical
    operation is recognized, while a legitimately different payload
    (e.g. retry with a changed strategy, per strategy.py) gets a new key."""
    payload_hash = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]
    return f"{task_id}:{side_effect_kind}:{payload_hash}"


class IdempotencyViolation(Exception):
    """Raised when the caller tries to record a NEW result for a key
    that already has one — surfaces a bug (re-executing without
    checking first) rather than silently overwriting history."""


class IdempotencyGuard:
    def __init__(self, db):
        self.db = db

    async def check(self, idempotency_key: str) -> dict | None:
        """Returns the previously recorded result if this exact
        operation already ran, else None. Callers MUST call this
        before performing the real side effect, not after."""
        row = await self.db.fetchrow(
            "SELECT * FROM mission_idempotency_records WHERE idempotency_key = $1", idempotency_key
        )
        return dict(row) if row else None

    async def record(self, idempotency_key: str, task_id: str, side_effect_kind: str,
                      result: dict, execution_id: str | None = None) -> dict:
        existing = await self.check(idempotency_key)
        if existing is not None:
            raise IdempotencyViolation(
                f"idempotency key '{idempotency_key}' already has a recorded result — "
                f"call check() first and skip re-execution instead of recording again"
            )

        execution_id = execution_id or str(uuid.uuid4())
        await self.db.execute(
            """
            INSERT INTO mission_idempotency_records (idempotency_key, task_id, execution_id,
                                                       side_effect_kind, result, created_at)
            VALUES ($1, $2, $3, $4, $5, $6)
            """,
            idempotency_key, task_id, execution_id, side_effect_kind, json.dumps(result), datetime.now(timezone.utc),
        )
        return {"idempotency_key": idempotency_key, "execution_id": execution_id}

    async def guarded_execute(self, task_id: str, side_effect_kind: str, payload: dict, execute_fn):
        """The real end-to-end helper: computes the key, checks for a
        prior result, and only calls execute_fn() (the actual side
        effect — e.g. the real GitHub PR-creation call) if nothing has
        run yet. Returns (result, was_replayed: bool)."""
        key = make_idempotency_key(task_id, side_effect_kind, payload)
        existing = await self.check(key)
        if existing is not None:
            existing_result = existing["result"]
            if isinstance(existing_result, str):
                existing_result = json.loads(existing_result)
            return existing_result, True

        result = await execute_fn()
        await self.record(key, task_id, side_effect_kind, result)
        return result, False
