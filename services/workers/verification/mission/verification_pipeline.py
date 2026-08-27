"""
Automatic verification pipeline — per spec §5. This is what makes
verification NOT depend on a developer remembering to call verify().
`VerificationPipeline.claim_and_verify()` is the single entry point
executor.py now calls instead of EvidenceEngine.record_claim() alone —
it records the claim AND immediately attempts real verification,
landing on VERIFIED / VERIFICATION_FAILED / VERIFICATION_PENDING
(never silently staying at CLAIMED with nothing having tried to check it).
"""

from __future__ import annotations

from .evidence import EvidenceEngine
from .verifiers import VERIFIER_REGISTRY, DatabaseVerifier, VerifierUnavailable


class VerificationPipeline:
    def __init__(self, db):
        self.db = db
        self.evidence_engine = EvidenceEngine(db)

    async def claim_and_verify(self, mission_id: str, task_id: str | None, kind: str,
                                claim: str, verification_context: dict | None = None) -> dict:
        """The real end-to-end flow: CLAIMED -> select verifier ->
        execute -> VERIFIED | VERIFICATION_FAILED | VERIFICATION_PENDING.

        verification_context carries whatever the specific verifier
        needs (e.g. {"exit_code": 0} for TestVerifier, {"url": ...}
        for HTTPVerifier) — if it's missing/insufficient, the pipeline
        lands on VERIFICATION_PENDING (not VERIFIED), which is the
        deliberate fail-safe default from spec §5.
        """
        record = await self.evidence_engine.record_claim(mission_id, task_id, kind, claim)
        evidence_id = record["evidence_id"]

        verifier_cls = VERIFIER_REGISTRY.get(kind)
        if verifier_cls is None:
            await self.evidence_engine.mark_pending(evidence_id, reason=f"no verifier registered for kind '{kind}'")
            return {"evidence_id": evidence_id, "status": "verification_pending"}

        verifier = DatabaseVerifier(self.db) if verifier_cls is DatabaseVerifier else verifier_cls()

        try:
            result = await verifier.verify(claim, verification_context or {})
        except VerifierUnavailable as e:
            await self.evidence_engine.mark_pending(evidence_id, reason=str(e))
            return {"evidence_id": evidence_id, "status": "verification_pending", "reason": str(e)}
        except Exception as e:
            # A verifier crashing is itself a verification failure, not
            # a pass — never let an unexpected exception here result in
            # evidence silently staying unverified-but-unflagged.
            await self.evidence_engine.mark_failed(evidence_id, verifier=verifier_cls.__name__,
                                                    detail={"error": f"verifier raised: {e}"})
            return {"evidence_id": evidence_id, "status": "verification_failed", "error": str(e)}

        if result.passed:
            await self.evidence_engine.verify(
                evidence_id, verification_detail=result.detail, evidence_hash=result.evidence_hash,
                verifier=verifier_cls.__name__,
            )
            return {"evidence_id": evidence_id, "status": "verified", "detail": result.detail}
        else:
            await self.evidence_engine.mark_failed(evidence_id, verifier=verifier_cls.__name__, detail=result.detail)
            return {"evidence_id": evidence_id, "status": "verification_failed", "detail": result.detail}
