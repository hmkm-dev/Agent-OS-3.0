import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from mission.fake_db import FakeDB  # noqa: E402
from mission.idempotency import (  # noqa: E402
    IdempotencyGuard, IdempotencyViolation, make_idempotency_key,
)


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_same_task_and_payload_produce_same_key():
    k1 = make_idempotency_key("t1", "github_pr", {"branch": "feature-x"})
    k2 = make_idempotency_key("t1", "github_pr", {"branch": "feature-x"})
    assert k1 == k2


def test_different_payload_produces_different_key():
    """A legitimately different retry (e.g. after a strategy change)
    must NOT be blocked as a duplicate."""
    k1 = make_idempotency_key("t1", "github_pr", {"branch": "feature-x"})
    k2 = make_idempotency_key("t1", "github_pr", {"branch": "feature-y"})
    assert k1 != k2


def test_check_returns_none_for_unseen_key():
    guard = IdempotencyGuard(FakeDB())
    result = run(guard.check("some-key"))
    assert result is None


def test_record_then_check_finds_prior_result():
    guard = IdempotencyGuard(FakeDB())
    run(guard.record("key1", "t1", "file_write", {"path": "/tmp/x"}))
    found = run(guard.check("key1"))
    assert found is not None
    assert found["task_id"] == "t1"


def test_recording_same_key_twice_raises():
    guard = IdempotencyGuard(FakeDB())
    run(guard.record("key1", "t1", "file_write", {"path": "/tmp/x"}))
    try:
        run(guard.record("key1", "t1", "file_write", {"path": "/tmp/x"}))
        assert False, "expected IdempotencyViolation"
    except IdempotencyViolation:
        pass


def test_guarded_execute_runs_real_side_effect_only_once():
    """The core end-to-end property: the second call with the SAME
    payload must NOT re-execute the side effect function."""
    guard = IdempotencyGuard(FakeDB())
    call_count = {"n": 0}

    async def side_effect():
        call_count["n"] += 1
        return {"pr_url": "https://github.com/x/y/pull/1"}

    result1, replayed1 = run(guard.guarded_execute("t1", "github_pr", {"branch": "x"}, side_effect))
    result2, replayed2 = run(guard.guarded_execute("t1", "github_pr", {"branch": "x"}, side_effect))

    assert call_count["n"] == 1, "side effect must only actually execute once"
    assert replayed1 is False
    assert replayed2 is True
    assert result1 == result2


def test_guarded_execute_with_different_payload_runs_again():
    guard = IdempotencyGuard(FakeDB())
    call_count = {"n": 0}

    async def side_effect():
        call_count["n"] += 1
        return {"call": call_count["n"]}

    run(guard.guarded_execute("t1", "github_pr", {"branch": "x"}, side_effect))
    run(guard.guarded_execute("t1", "github_pr", {"branch": "y"}, side_effect))

    assert call_count["n"] == 2, "genuinely different payload must execute again, not be blocked"
