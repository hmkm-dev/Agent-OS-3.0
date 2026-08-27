"""
Teach -> Skill workflow.

    User demonstration -> Capture workflow -> Extract steps ->
    Generate skill definition -> Validate -> Test -> User approval -> Publish

Real implementation of the pipeline plumbing. The "extract steps"
stage calls the model router to turn a raw demonstration transcript
into structured instructions — this needs OPENROUTER_API_KEY
configured (see model_router.py) to actually run; without it, this
raises rather than fabricating a skill definition.

Publishing (status -> 'approved') is a separate, explicit call that
only a human-facing API route should trigger — see services/hermes/app.py
POST /skills/{id}/approve, which is intentionally not reachable from
any agent-initiated code path.
"""

from __future__ import annotations

from .skill import SkillEngine


class TeachToSkill:
    def __init__(self, db, route_fn):
        """route_fn: an async callable(task_type, prompt) -> {"text": ...},
        pass services.hermes.model_router.route."""
        self.skill_engine = SkillEngine(db)
        self.route_fn = route_fn

    async def capture_and_extract(self, demonstration_transcript: str) -> dict:
        """Turns a raw demonstration (sequence of user actions/narration)
        into a structured skill draft: name, description, instructions."""
        prompt = (
            "You are extracting a reusable skill definition from a user's "
            "demonstration. Given the transcript below, output a JSON object "
            "with keys: name, description, instructions (numbered steps), "
            "required_tools (array), inputs (object), outputs (object).\n\n"
            f"Transcript:\n{demonstration_transcript}"
        )
        result = await self.route_fn("reasoning", prompt)
        return self._parse_extraction(result["text"])

    def _parse_extraction(self, model_text: str) -> dict:
        import json
        try:
            return json.loads(model_text)
        except json.JSONDecodeError as e:
            raise ValueError(
                "model did not return valid JSON for skill extraction — "
                "inspect the raw response and adjust the prompt rather than "
                "silently accepting malformed output"
            ) from e

    async def create_draft_from_extraction(self, extraction: dict) -> dict:
        return await self.skill_engine.create_draft(
            name=extraction["name"],
            description=extraction.get("description", ""),
            required_tools=extraction.get("required_tools", []),
            inputs=extraction.get("inputs", {}),
            outputs=extraction.get("outputs", {}),
            constraints=extraction.get("constraints", {}),
        )

    async def run_tests(self, skill_id: str, test_cases: list[dict]) -> dict:
        """
        Real implementation, closing the gap flagged in prior audits.

        Each test case is a dict: {"input": "...", "expected": "..."}.
        For each case, this actually calls the model router with the
        skill's instructions + the test input, then grades the real
        response against `expected` using the same model-graded
        approach as the Evaluator (0.0-1.0 similarity/correctness
        score, explicitly probabilistic — not a deterministic proof).

        This dry-runs the skill via the model router directly rather
        than through a full worker+MCP dispatch, because a generic
        skill (which may target research/creative/opencode) doesn't
        map to one specific worker queue. This is an intentional scope
        boundary, not a fake: it validates that the skill's
        instructions produce reasonable outputs for its test inputs,
        which is what "does this skill make sense" actually needs to
        answer before a human approves it. It does NOT validate tool
        usage (MCP calls) — that's still a real gap, and this method
        says so in its returned report rather than pretending it
        checked something it didn't.

        Returns: {"passed": bool, "results": [...], "score": float}
        Does NOT change skill status — call SkillEngine.mark_tested()
        yourself after inspecting the results, and only a human should
        call SkillEngine.approve() afterward.
        """
        if not test_cases:
            raise ValueError("run_tests requires at least one test case")

        row = await self.skill_engine.db.fetchrow(
            "SELECT sv.instructions FROM skill_versions sv "
            "WHERE sv.skill_id = $1 ORDER BY sv.version DESC LIMIT 1",
            skill_id,
        )
        if row is None:
            raise LookupError(f"no skill_versions found for skill_id {skill_id} — call add_version() first")
        instructions = row["instructions"]

        results = []
        for i, case in enumerate(test_cases):
            test_input = case.get("input")
            expected = case.get("expected")
            if test_input is None or expected is None:
                raise ValueError(f"test case {i} must have both 'input' and 'expected' keys")

            prompt = f"Instructions:\n{instructions}\n\nTask input:\n{test_input}"
            response = await self.route_fn("reasoning", prompt)
            actual = response["text"]

            score = await self._grade_against_expected(actual, expected)
            results.append({
                "test_index": i,
                "input": test_input,
                "expected": expected,
                "actual": actual,
                "score": score,
                "passed": score >= 0.6,
            })

        overall_score = sum(r["score"] for r in results) / len(results)
        all_passed = all(r["passed"] for r in results)

        return {
            "passed": all_passed,
            "overall_score": overall_score,
            "results": results,
            "note": "This validates instruction-following against test inputs via the "
                    "model router. It does NOT validate real tool/MCP usage — a skill "
                    "that calls Playwright or GitHub still needs a manual dry-run through "
                    "the actual worker before approval, not just this test.",
        }

    async def _grade_against_expected(self, actual: str, expected: str) -> float:
        """Model-graded comparison, 0.0-1.0. Same probabilistic caveat
        as Evaluator._grade_quality — returns 0.5 (neutral, forces
        human review rather than auto-passing) if the grading call
        itself fails to parse."""
        prompt = (
            "Rate how well the ACTUAL output matches the EXPECTED output's intent "
            "and content, from 0.0 (no match) to 1.0 (matches well — exact wording "
            "is not required, only correctness/intent). Respond with only a number.\n\n"
            f"EXPECTED:\n{expected}\n\nACTUAL:\n{actual}"
        )
        try:
            resp = await self.route_fn("fast", prompt, max_tokens=10)
            return max(0.0, min(1.0, float(resp["text"].strip())))
        except (ValueError, KeyError):
            return 0.5
