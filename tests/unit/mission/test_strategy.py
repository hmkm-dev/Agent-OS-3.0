import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from mission.fake_db import FakeDB  # noqa: E402
from mission.strategy import StrategyManager, StrategyNotChangedError  # noqa: E402


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_first_strategy_starts_at_version_1():
    sm = StrategyManager(FakeDB())
    result = run(sm.record_strategy("t1", reason="initial attempt", parameters={"approach": "A"}))
    assert result["version"] == 1


def test_second_strategy_increments_version():
    sm = StrategyManager(FakeDB())
    run(sm.record_strategy("t1", reason="attempt 1", parameters={"approach": "A"}))
    result = run(sm.record_strategy("t1", reason="attempt 2", parameters={"approach": "B"}))
    assert result["version"] == 2


def test_require_change_rejects_identical_parameters():
    """The core safety property this module exists for: you cannot
    silently retry with the exact same parameters and call it a
    strategy change."""
    sm = StrategyManager(FakeDB())
    run(sm.record_strategy("t1", reason="attempt 1", parameters={"approach": "A"}))
    try:
        run(sm.record_strategy("t1", reason="attempt 2, same as before", parameters={"approach": "A"}, require_change=True))
        assert False, "expected StrategyNotChangedError"
    except StrategyNotChangedError:
        pass


def test_require_change_allows_genuinely_different_parameters():
    sm = StrategyManager(FakeDB())
    run(sm.record_strategy("t1", reason="attempt 1", parameters={"approach": "A"}))
    result = run(sm.record_strategy("t1", reason="attempt 2, different", parameters={"approach": "B"}, require_change=True))
    assert result["version"] == 2


def test_without_require_change_identical_parameters_allowed():
    """A plain (non-strategy-changing) retry legitimately CAN repeat
    the same parameters — only require_change=True enforces difference."""
    sm = StrategyManager(FakeDB())
    run(sm.record_strategy("t1", reason="attempt 1", parameters={"approach": "A"}))
    result = run(sm.record_strategy("t1", reason="attempt 2, transient retry", parameters={"approach": "A"}, require_change=False))
    assert result["version"] == 2


def test_next_template_cycles_through_real_alternatives():
    sm = StrategyManager(FakeDB())
    t0 = sm.next_template("browser_failure", 0)
    t1 = sm.next_template("browser_failure", 1)
    t2 = sm.next_template("browser_failure", 2)
    assert t0 != t1
    assert t1 != t2
    assert t0["playwright_strategy"] != t1["playwright_strategy"]


def test_next_template_generic_fallback_still_varies_by_attempt():
    """Even for a category without a specific template, the fallback
    must not return byte-identical params across attempts (which
    would make require_change=True spuriously fail forever)."""
    sm = StrategyManager(FakeDB())
    t0 = sm.next_template("unknown_category", 0)
    t1 = sm.next_template("unknown_category", 1)
    assert t0 != t1


def test_get_current_strategy_returns_latest_version():
    sm = StrategyManager(FakeDB())
    run(sm.record_strategy("t1", reason="v1", parameters={"approach": "A"}))
    run(sm.record_strategy("t1", reason="v2", parameters={"approach": "B"}))
    current = run(sm.get_current_strategy("t1"))
    assert current["version"] == 2
    assert current["reason"] == "v2"
