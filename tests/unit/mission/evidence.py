"""
Evidence engine — per spec §4/§9. Full status machine:
CLAIMED -> VERIFICATION_PENDING -> VERIFIED | VERIFICATION_FAILED
                                 -> REJECTED (human/evaluator override)
         -> EXPIRED (time-based, via mark_expired / expires_at)

The `verified` boolean column (from the original migration) is kept
and stays in sync with `status == 'verified'` for backward
compatibility with existing callers (mission_evaluator.py's
get_mission_evidence(verified_only=True) still works unchanged) — new
code should prefer `status` for the full picture.

A worker can never call verify() on its own claim through this class
alone — verify() requires a `verifier` name and a `verification_detail`
that only VerificationPipeline (services/mission/verification_pipeline.py)
supplies after actually running an independent Verifier. Nothing in
the executor calls this class's verify()/mark_failed() directly
anymore — see executor.py's use of VerificationPipeline instead.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

VALID_KINDS = {
    "test_result", "build_result", "lint_result", "deployment_health_check",
    "source_reference", "extracted_evidence", "cross_check_result",
    "browser_action_result", "screenshot_ref", "container_health",
    "http_health_check", "service_response", "log_excerpt",
}

VALID_STATUSES = {
    "claimed", "verification_pending", "verified", "verification_failed", "rejected", "expired",
}


class EvidenceEngine:
    def __init__(self, db):
        self.db = db

    async def record_claim(self, mission_id: str, task_id: str | None, kind: str, claim: str) -> dict:
        """Record a CLAIMED result. Status starts at 'claimed' — this
        alone never satisfies success criteria; something must call
        VerificationPipeline (not this method directly) to move it
        forward."""
        if kind not in VALID_KINDS:
            raise ValueError(f"unknown evidence kind '{kind}', expected one of {VALID_KINDS}")

        evidence_id = str(uuid.uuid4())
        await self.db.execute(
            """
            INSERT INTO mission_evidence (evidence_id, mission_id, task_id, kind, claim, verified, status, created_at)
            VALUES ($1, $2, $3, $4, $5, false, 'claimed', $6)
            """,
            evidence_id, mission_id, task_id, kind, claim, datetime.now(timezone.utc),
        )
        return {"evidence_id": evidence_id, "verified": False, "status": "claimed"}

    async def verify(self, evidence_id: str, verification_detail: dict, verifier: str,
                      evidence_hash: str | None = None, r2_key: str | None = None) -> dict:
        """Marks evidence VERIFIED. Requires `verifier` (which
        independent Verifier class actually ran) and a non-empty
        verification_detail — this is intentionally not callable with
        just a claim string, since that would let a worker "verify"
        its own claim by just repeating it."""
        if not verification_detail:
            raise ValueError("verification_detail is required — cannot verify without describing how")
        if not verifier:
            raise ValueError("verifier name is required — evidence cannot self-verify")

        await self.db.execute(
            "UPDATE mission_evidence SET verified = true, status = 'verified', verification_detail = $1, "
            "r2_key = $2, verifier = $3, verified_at = $4, evidence_hash = $5 WHERE evidence_id = $6",
            json.dumps(verification_detail), r2_key, verifier, datetime.now(timezone.utc), evidence_hash, evidence_id,
        )
        return {"evidence_id": evidence_id, "verified": True, "status": "verified"}

    async def mark_pending(self, evidence_id: str, reason: str) -> dict:
        """Verification could not run yet (e.g. missing config/creds
        for that verifier) — this is the deliberate fail-safe default:
        NOT verified, but distinguishable from a failed check."""
        await self.db.execute(
            "UPDATE mission_evidence SET status = 'verification_pending', "
            "verification_detail = $1 WHERE evidence_id = $2",
            json.dumps({"reason": reason}), evidence_id,
        )
        return {"evidence_id": evidence_id, "status": "verification_pending"}

    async def mark_failed(self, evidence_id: str, verifier: str, detail: dict) -> dict:
        """The verifier ran and the claim did NOT check out."""
        await self.db.execute(
            "UPDATE mission_evidence SET status = 'verification_failed', verifier = $1, "
            "verification_detail = $2, verified_at = $3 WHERE evidence_id = $4",
            verifier, json.dumps(detail), datetime.now(timezone.utc), evidence_id,
        )
        return {"evidence_id": evidence_id, "status": "verification_failed"}

    async def reject(self, evidence_id: str, reason: str, rejected_by: str) -> dict:
        """Explicit human/evaluator override — even previously VERIFIED
        evidence can be rejected (e.g. later found stale/wrong).
        `rejected_by` should be a human identifier or 'mission_evaluator',
        never a worker/agent_id — same self-approval-prevention pattern
        as services/approval/manager.py."""
        await self.db.execute(
            "UPDATE mission_evidence SET status = 'rejected', verified = false, "
            "verification_detail = $1 WHERE evidence_id = $2",
            json.dumps({"rejected_reason": reason, "rejected_by": rejected_by}), evidence_id,
        )
        return {"evidence_id": evidence_id, "status": "rejected"}

    async def mark_expired(self, evidence_id: str) -> dict:
        await self.db.execute(
            "UPDATE mission_evidence SET status = 'expired', verified = false WHERE evidence_id = $1",
            evidence_id,
        )
        return {"evidence_id": evidence_id, "status": "expired"}

    async def get_mission_evidence(self, mission_id: str, verified_only: bool = False) -> list[dict]:
        if verified_only:
            rows = await self.db.fetch(
                "SELECT * FROM mission_evidence WHERE mission_id = $1 AND status = 'verified'", mission_id
            )
        else:
            rows = await self.db.fetch(
                "SELECT * FROM mission_evidence WHERE mission_id = $1", mission_id
            )
        return [dict(r) for r in rows]

    async def get_task_evidence(self, task_id: str, status: str | None = None) -> list[dict]:
        """Return evidence for one task, optionally restricted to a status."""
        if status:
            rows = await self.db.fetch(
                "SELECT * FROM mission_evidence WHERE task_id = $1 AND status = $2", task_id, status
            )
        else:
            rows = await self.db.fetch("SELECT * FROM mission_evidence WHERE task_id = $1", task_id)
        return [dict(r) for r in rows]

    async def has_verified_evidence_for_task(self, task_id: str) -> bool:
        row = await self.db.fetchrow(
            "SELECT count(*) AS c FROM mission_evidence WHERE task_id = $1 AND status = 'verified'", task_id
        )
        return row["c"] > 0
