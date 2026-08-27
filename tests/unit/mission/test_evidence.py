import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from mission.evidence import EvidenceEngine  # noqa: E402
from mission.fake_db import FakeDB  # noqa: E402


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_claim_starts_unverified():
    ee = EvidenceEngine(FakeDB())
    result = run(ee.record_claim("m1", "t1", "test_result", "all tests passed"))
    assert result["verified"] is False
    assert result["status"] == "claimed"


def test_unknown_kind_rejected():
    ee = EvidenceEngine(FakeDB())
    try:
        run(ee.record_claim("m1", "t1", "vibes", "it felt right"))
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_verify_requires_real_detail():
    ee = EvidenceEngine(FakeDB())
    claim = run(ee.record_claim("m1", "t1", "test_result", "tests passed"))
    try:
        run(ee.verify(claim["evidence_id"], verification_detail={}, verifier="TestVerifier"))
        assert False, "expected ValueError for empty verification_detail"
    except ValueError:
        pass


def test_verify_requires_verifier_name():
    """The core anti-self-verification property: verify() cannot be
    called without naming which independent verifier actually ran."""
    ee = EvidenceEngine(FakeDB())
    claim = run(ee.record_claim("m1", "t1", "test_result", "tests passed"))
    try:
        run(ee.verify(claim["evidence_id"], verification_detail={"exit_code": 0}, verifier=""))
        assert False, "expected ValueError for missing verifier name"
    except ValueError:
        pass


def test_verify_with_real_detail_succeeds():
    ee = EvidenceEngine(FakeDB())
    claim = run(ee.record_claim("m1", "t1", "test_result", "tests passed"))
    result = run(ee.verify(claim["evidence_id"], verification_detail={"method": "pytest", "exit_code": 0}, verifier="TestVerifier"))
    assert result["verified"] is True
    assert result["status"] == "verified"


def test_mark_pending_does_not_count_as_verified():
    ee = EvidenceEngine(FakeDB())
    claim = run(ee.record_claim("m1", "t1", "test_result", "tests passed"))
    result = run(ee.mark_pending(claim["evidence_id"], reason="verifier unavailable"))
    assert result["status"] == "verification_pending"
    assert run(ee.has_verified_evidence_for_task("t1")) is False


def test_mark_failed_does_not_count_as_verified():
    ee = EvidenceEngine(FakeDB())
    claim = run(ee.record_claim("m1", "t1", "test_result", "tests passed"))
    result = run(ee.mark_failed(claim["evidence_id"], verifier="TestVerifier", detail={"exit_code": 1}))
    assert result["status"] == "verification_failed"
    assert run(ee.has_verified_evidence_for_task("t1")) is False


def test_reject_reverts_previously_verified_evidence():
    """Even VERIFIED evidence can be rejected later — e.g. found stale."""
    ee = EvidenceEngine(FakeDB())
    claim = run(ee.record_claim("m1", "t1", "test_result", "tests passed"))
    run(ee.verify(claim["evidence_id"], {"exit_code": 0}, verifier="TestVerifier"))
    assert run(ee.has_verified_evidence_for_task("t1")) is True

    run(ee.reject(claim["evidence_id"], reason="found to be stale", rejected_by="mission_evaluator"))
    assert run(ee.has_verified_evidence_for_task("t1")) is False


def test_get_mission_evidence_verified_only_filter():
    ee = EvidenceEngine(FakeDB())
    run(ee.record_claim("m1", "t1", "test_result", "claim A"))
    verified_one = run(ee.record_claim("m1", "t2", "build_result", "claim B"))
    run(ee.verify(verified_one["evidence_id"], {"method": "docker build", "exit_code": 0}, verifier="TestVerifier"))

    all_evidence = run(ee.get_mission_evidence("m1", verified_only=False))
    verified_evidence = run(ee.get_mission_evidence("m1", verified_only=True))

    assert len(all_evidence) == 2
    assert len(verified_evidence) == 1
    assert verified_evidence[0]["evidence_id"] == verified_one["evidence_id"]


def test_has_verified_evidence_for_task():
    ee = EvidenceEngine(FakeDB())
    claim = run(ee.record_claim("m1", "t1", "test_result", "claim"))
    assert run(ee.has_verified_evidence_for_task("t1")) is False
    run(ee.verify(claim["evidence_id"], {"method": "manual check"}, verifier="TestVerifier"))
    assert run(ee.has_verified_evidence_for_task("t1")) is True
