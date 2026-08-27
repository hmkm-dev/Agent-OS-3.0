import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from mission.evidence import EvidenceEngine  # noqa: E402
from mission.fake_db import FakeDB  # noqa: E402
from mission.mission_evaluator import MissionEvaluator  # noqa: E402


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _mission(mission_id="m1", success_criteria=None):
    return {
        "mission_id": mission_id,
        "user_goal": "deploy a working API",
        "objective": "public HTTPS endpoint returns 200",
        "success_criteria": json.dumps(success_criteria or ["endpoint returns 200 OK"]),
    }


async def _fake_route_says_incomplete(task_type, prompt, max_tokens=2000):
    return {"text": json.dumps({
        "criteria_results": [{"criterion": "endpoint returns 200 OK", "met": False, "reasoning": "no health check evidence found"}],
        "overall_verdict": "INCOMPLETE",
        "gaps": ["no verified HTTP health check exists"],
    })}


async def _fake_route_says_completed(task_type, prompt, max_tokens=2000):
    return {"text": json.dumps({
        "criteria_results": [{"criterion": "endpoint returns 200 OK", "met": True, "reasoning": "verified HTTP 200 response in evidence"}],
        "overall_verdict": "COMPLETED",
        "gaps": [],
    })}


def test_no_verified_evidence_at_all_is_always_incomplete():
    """This is the core property from the spec: 20/20 tasks marked
    'passed' does NOT mean the mission is complete if there's no
    VERIFIED evidence — this must be true even without calling the
    model, as a hard floor."""
    db = FakeDB()
    me = MissionEvaluator(db, route_fn=_fake_route_says_completed)  # even if the model WOULD say completed
    result = run(me.evaluate_mission(_mission()))
    assert result["overall_verdict"] == "INCOMPLETE"
    assert "no verified evidence" in result["gaps"][0]


def test_only_claimed_not_verified_evidence_still_incomplete():
    db = FakeDB()
    ee = EvidenceEngine(db)
    run(ee.record_claim("m1", "t1", "http_health_check", "endpoint returned 200"))  # claimed, never verified
    me = MissionEvaluator(db, route_fn=_fake_route_says_completed)
    result = run(me.evaluate_mission(_mission()))
    assert result["overall_verdict"] == "INCOMPLETE"


def test_verified_evidence_present_but_model_says_incomplete():
    db = FakeDB()
    db.missions["m1"] = {"mission_id": "m1", "final_verification": None}
    ee = EvidenceEngine(db)
    claim = run(ee.record_claim("m1", "t1", "http_health_check", "endpoint returned 200"))
    run(ee.verify(claim["evidence_id"], {"method": "http_get", "status": 200}, verifier="HTTPVerifier"))

    me = MissionEvaluator(db, route_fn=_fake_route_says_incomplete)
    result = run(me.evaluate_mission(_mission()))
    assert result["overall_verdict"] == "INCOMPLETE"


def test_verified_evidence_and_model_agrees_completed():
    db = FakeDB()
    db.missions["m1"] = {"mission_id": "m1", "final_verification": None}
    ee = EvidenceEngine(db)
    claim = run(ee.record_claim("m1", "t1", "http_health_check", "endpoint returned 200"))
    run(ee.verify(claim["evidence_id"], {"method": "http_get", "status": 200}, verifier="HTTPVerifier"))

    me = MissionEvaluator(db, route_fn=_fake_route_says_completed)
    result = run(me.evaluate_mission(_mission()))
    assert result["overall_verdict"] == "COMPLETED"


def test_malformed_model_response_fails_closed_to_incomplete():
    """If the verification call itself is broken, that must NOT be
    interpreted as success."""
    async def broken_route(task_type, prompt, max_tokens=2000):
        return {"text": "not json at all"}

    db = FakeDB()
    db.missions["m1"] = {"mission_id": "m1", "final_verification": None}
    ee = EvidenceEngine(db)
    claim = run(ee.record_claim("m1", "t1", "http_health_check", "endpoint returned 200"))
    run(ee.verify(claim["evidence_id"], {"method": "http_get", "status": 200}, verifier="HTTPVerifier"))

    me = MissionEvaluator(db, route_fn=broken_route)
    result = run(me.evaluate_mission(_mission()))
    assert result["overall_verdict"] == "INCOMPLETE"


def test_final_verification_persisted_to_mission_row():
    db = FakeDB()
    db.missions["m1"] = {"mission_id": "m1", "final_verification": None}
    ee = EvidenceEngine(db)
    claim = run(ee.record_claim("m1", "t1", "http_health_check", "ok"))
    run(ee.verify(claim["evidence_id"], {"method": "http_get", "status": 200}, verifier="HTTPVerifier"))

    me = MissionEvaluator(db, route_fn=_fake_route_says_completed)
    run(me.evaluate_mission(_mission()))
    assert db.missions["m1"]["final_verification"] is not None
