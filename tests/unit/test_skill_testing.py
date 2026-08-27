"""
Real test proving TeachToSkill.run_tests() actually dispatches to a
route_fn and grades results — not just that it no longer raises
NotImplementedError. Uses a fake db + a fake route_fn that returns
deterministic text so grading logic is exercised without a live API.
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from skill_engine.teach import TeachToSkill  # noqa: E402


class FakeDB:
    def __init__(self, instructions):
        self.instructions = instructions

    async def fetchrow(self, query, *args):
        if "skill_versions" in query:
            return {"instructions": self.instructions}
        return None

    async def execute(self, query, *args):
        pass


async def fake_route_good(task_type, prompt, max_tokens=2000):
    # For the grading call, always return a high score; for the
    # "actual output" call, echo something plausible.
    if "Rate how well" in prompt:
        return {"text": "0.9"}
    return {"text": "The capital of France is Paris."}


async def fake_route_bad_grading(task_type, prompt, max_tokens=2000):
    if "Rate how well" in prompt:
        return {"text": "not-a-number"}  # forces the 0.5 fallback path
    return {"text": "some output"}


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_run_tests_passes_with_high_grading_score():
    db = FakeDB(instructions="Answer geography questions concisely.")
    engine = TeachToSkill(db, fake_route_good)
    result = run(engine.run_tests("skill-1", [
        {"input": "What is the capital of France?", "expected": "Paris"},
    ]))
    assert result["passed"] is True
    assert result["overall_score"] == 0.9
    assert result["results"][0]["actual"] == "The capital of France is Paris."


def test_run_tests_falls_back_to_neutral_score_on_bad_grading_response():
    db = FakeDB(instructions="Answer geography questions concisely.")
    engine = TeachToSkill(db, fake_route_bad_grading)
    result = run(engine.run_tests("skill-1", [
        {"input": "What is the capital of France?", "expected": "Paris"},
    ]))
    # 0.5 fallback is below the 0.6 pass threshold — must NOT silently pass
    assert result["results"][0]["score"] == 0.5
    assert result["results"][0]["passed"] is False


def test_run_tests_requires_at_least_one_case():
    db = FakeDB(instructions="x")
    engine = TeachToSkill(db, fake_route_good)
    try:
        run(engine.run_tests("skill-1", []))
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_run_tests_raises_if_no_skill_version_exists():
    class EmptyDB(FakeDB):
        async def fetchrow(self, query, *args):
            return None
    engine = TeachToSkill(EmptyDB(instructions=""), fake_route_good)
    try:
        run(engine.run_tests("skill-missing", [{"input": "x", "expected": "y"}]))
        assert False, "expected LookupError"
    except LookupError:
        pass
