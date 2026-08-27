import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from mission.failure_recovery import FailureCategory, FailureRecovery  # noqa: E402
from mission.fake_db import FakeDB  # noqa: E402


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_classify_auth_failure():
    fr = FailureRecovery(FakeDB())
    assert fr.classify("401 Unauthorized: invalid API key") == FailureCategory.AUTH_FAILURE


def test_classify_timeout():
    fr = FailureRecovery(FakeDB())
    assert fr.classify("Error: request timed out after 30s") == FailureCategory.TIMEOUT


def test_classify_test_failure():
    fr = FailureRecovery(FakeDB())
    assert fr.classify("2 failed, 8 passed in 3.2s (pytest)") == FailureCategory.TEST_FAILURE


def test_classify_browser_failure():
    fr = FailureRecovery(FakeDB())
    assert fr.classify("Playwright navigation failed: net::ERR_NAME_NOT_RESOLVED") == FailureCategory.BROWSER_FAILURE


def test_classify_unknown_when_no_pattern_matches():
    fr = FailureRecovery(FakeDB())
    assert fr.classify("something vague went wrong") == FailureCategory.UNKNOWN


def test_permission_denial_never_auto_retries():
    """The real safety property: a 403 must never be silently retried
    — it always escalates."""
    fr = FailureRecovery(FakeDB())
    decision = fr.decide(FailureCategory.PERMISSION_DENIAL, retry_count=0, max_retries=5)
    assert decision["action"] == "escalate"


def test_auth_failure_requires_strategy_change_not_blind_retry():
    fr = FailureRecovery(FakeDB())
    decision = fr.decide(FailureCategory.AUTH_FAILURE, retry_count=0, max_retries=3)
    assert decision["action"] == "retry_with_strategy_change"


def test_transient_failure_allows_plain_retry():
    fr = FailureRecovery(FakeDB())
    decision = fr.decide(FailureCategory.NETWORK_FAILURE, retry_count=0, max_retries=3)
    assert decision["action"] == "retry"


def test_exhausted_retries_escalates_regardless_of_category():
    """Bounded retry — never loop forever even for a normally-retryable category."""
    fr = FailureRecovery(FakeDB())
    decision = fr.decide(FailureCategory.NETWORK_FAILURE, retry_count=3, max_retries=3)
    assert decision["action"] == "escalate"


def test_diagnose_and_decide_records_a_real_decision():
    db = FakeDB()
    fr = FailureRecovery(db)
    result = run(fr.diagnose_and_decide(
        mission_id="m1", task_id="t1", failed_step="deploy",
        error_text="401 unauthorized", retry_count=0, max_retries=3,
    ))
    assert result["category"] == "authentication_failure"
    assert result["action"] == "retry_with_strategy_change"
    assert result["new_strategy"] is not None
    assert result["decision_id"] in db.mission_decisions
