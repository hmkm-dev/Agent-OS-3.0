import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from mission.evidence import EvidenceEngine  # noqa: E402
from mission.fake_db import FakeDB  # noqa: E402
from mission.verification_pipeline import VerificationPipeline  # noqa: E402


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_pipeline_auto_verifies_with_correct_context():
    """The core spec §5 property: verification happens automatically
    as part of claim_and_verify(), no separate manual verify() call
    needed by the caller."""
    db = FakeDB()
    pipeline = VerificationPipeline(db)
    result = run(pipeline.claim_and_verify(
        "m1", "t1", "test_result", claim="tests passed",
        verification_context={"exit_code": 0},
    ))
    assert result["status"] == "verified"
    ee = EvidenceEngine(db)
    assert run(ee.has_verified_evidence_for_task("t1")) is True


def test_pipeline_lands_on_verification_failed_for_real_failure():
    db = FakeDB()
    pipeline = VerificationPipeline(db)
    result = run(pipeline.claim_and_verify(
        "m1", "t1", "test_result", claim="tests passed (lie)",
        verification_context={"exit_code": 1},
    ))
    assert result["status"] == "verification_failed"
    ee = EvidenceEngine(db)
    assert run(ee.has_verified_evidence_for_task("t1")) is False


def test_pipeline_lands_on_verification_pending_when_context_insufficient():
    """The deliberate fail-safe: missing verification_context must
    NEVER result in a fake VERIFIED — it lands on pending instead."""
    db = FakeDB()
    pipeline = VerificationPipeline(db)
    result = run(pipeline.claim_and_verify(
        "m1", "t1", "test_result", claim="tests passed", verification_context={},
    ))
    assert result["status"] == "verification_pending"
    ee = EvidenceEngine(db)
    assert run(ee.has_verified_evidence_for_task("t1")) is False


def test_pipeline_lands_on_verification_pending_for_unregistered_kind():
    """Evidence kinds with no registered verifier (e.g. source_reference,
    which needs a human/cross-check flow) must not be silently marked
    verified either."""
    db = FakeDB()
    pipeline = VerificationPipeline(db)
    result = run(pipeline.claim_and_verify(
        "m1", "t1", "source_reference", claim="found a source", verification_context={},
    ))
    assert result["status"] == "verification_pending"


def test_pipeline_verifier_unavailable_never_becomes_verified():
    """ArtifactVerifier requires r2_key — omitting it must land on
    pending, not a silent pass."""
    db = FakeDB()
    pipeline = VerificationPipeline(db)
    result = run(pipeline.claim_and_verify(
        "m1", "t1", "screenshot_ref", claim="screenshot exists",
        verification_context={},
    ))
    assert result["status"] in ("verification_pending", "verification_failed")
    ee = EvidenceEngine(db)
    assert run(ee.has_verified_evidence_for_task("t1")) is False


def test_pipeline_records_a_real_claim_even_when_verification_fails():
    """The claim itself is always recorded (spec §4/§9's evidence
    trail) even when verification doesn't succeed — failure to verify
    is not the same as failure to record."""
    db = FakeDB()
    pipeline = VerificationPipeline(db)
    result = run(pipeline.claim_and_verify(
        "m1", "t1", "test_result", claim="tests passed", verification_context={"exit_code": 1},
    ))
    ee = EvidenceEngine(db)
    all_evidence = run(ee.get_mission_evidence("m1"))
    assert len(all_evidence) == 1
    assert all_evidence[0]["claim"] == "tests passed"
