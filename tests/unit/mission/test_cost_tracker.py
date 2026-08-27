import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from mission.cost_tracker import BudgetExceededError, CostTracker  # noqa: E402
from mission.fake_db import FakeDB  # noqa: E402


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_record_usage_accumulates():
    ct = CostTracker(FakeDB())
    run(ct.record_usage("m1", "t1", "default", {"prompt_tokens": 100, "completion_tokens": 50}))
    run(ct.record_usage("m1", "t2", "default", {"prompt_tokens": 200, "completion_tokens": 100}))
    totals = run(ct.mission_totals("m1"))
    assert totals["prompt_tokens"] == 300
    assert totals["completion_tokens"] == 150
    assert totals["model_calls"] == 2


def test_no_budget_configured_never_raises():
    ct = CostTracker(FakeDB())
    run(ct.record_usage("m1", "t1", "default", {"prompt_tokens": 999999, "completion_tokens": 999999}))
    run(ct.check_budget("m1", {}))  # should not raise


def test_max_tokens_budget_enforced():
    ct = CostTracker(FakeDB())
    run(ct.record_usage("m1", "t1", "default", {"prompt_tokens": 5000, "completion_tokens": 5000}))
    try:
        run(ct.check_budget("m1", {"max_tokens": 5000}))
        assert False, "expected BudgetExceededError"
    except BudgetExceededError:
        pass


def test_under_budget_does_not_raise():
    ct = CostTracker(FakeDB())
    run(ct.record_usage("m1", "t1", "default", {"prompt_tokens": 100, "completion_tokens": 100}))
    run(ct.check_budget("m1", {"max_tokens": 10000}))  # should not raise


def test_max_cost_budget_enforced():
    ct = CostTracker(FakeDB())
    # 1,000,000 tokens at 0.003/1K = $3.00
    run(ct.record_usage("m1", "t1", "default", {"prompt_tokens": 500000, "completion_tokens": 500000}))
    try:
        run(ct.check_budget("m1", {"max_cost": 1.0}))
        assert False, "expected BudgetExceededError"
    except BudgetExceededError:
        pass
