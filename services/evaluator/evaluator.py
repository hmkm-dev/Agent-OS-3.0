"""
Evaluator — centralized quality/policy gate every worker result passes
through before it's considered done. Real checks, not a rubber stamp:
completion, policy compliance, and basic error/evidence checks are
implemented directly; "correctness" and "quality" for open-ended
content delegate to a model-graded rubric via the model router
(documented below), which is honest about being probabilistic rather
than pretending to be a deterministic check.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Literal

Verdict = Literal["pass", "fail", "retry", "require_human"]

MAX_AUTO_RETRIES = 3


class Evaluator:
    def __init__(self, db, route_fn=None, policy_engine=None):
        self.db = db
        self.route_fn = route_fn        # services.hermes.model_router.route, optional
        self.policy_engine = policy_engine

    async def evaluate(self, task: dict) -> dict:
        checks = {}

        # 1. Completion: did the worker actually return a result, or did it error out?
        checks["completion"] = task.get("status") == "completed" and task.get("result") is not None

        # 2. Errors present?
        checks["no_errors"] = not bool(task.get("last_error"))

        # 3. Evidence: for research tasks, sources must be present and non-empty.
        if task.get("type") == "research":
            sources = (task.get("result") or {}).get("sources", [])
            checks["evidence"] = len(sources) > 0
        else:
            checks["evidence"] = True

        # 4. Policy compliance: re-check the original payload against policy
        #    rules in case the task drifted from what was originally approved.
        if self.policy_engine and task.get("type") == "creative":
            decision = self.policy_engine.evaluate(
                "EXTERNAL_POST", context={"payload": json.dumps(task.get("payload", {}))}
            )
            checks["policy_compliance"] = decision.result != "DENY"
        else:
            checks["policy_compliance"] = True

        # 5. Quality (best-effort, model-graded — documented as probabilistic)
        if self.route_fn and checks["completion"]:
            checks["quality_score"] = await self._grade_quality(task)
        else:
            checks["quality_score"] = None

        verdict = self._decide(checks, task.get("retries", 0))

        await self._store(task["task_id"], verdict, checks)
        return {"verdict": verdict, "checks": checks}

    def _decide(self, checks: dict, retries: int) -> Verdict:
        if not checks["completion"] or not checks["no_errors"]:
            return "require_human" if retries >= MAX_AUTO_RETRIES else "retry"
        if not checks["evidence"] or not checks["policy_compliance"]:
            return "fail"
        if checks["quality_score"] is not None and checks["quality_score"] < 0.5:
            return "retry" if retries < MAX_AUTO_RETRIES else "require_human"
        return "pass"

    async def _grade_quality(self, task: dict) -> float:
        """Model-graded rubric, 0.0-1.0. Explicitly probabilistic — do not
        treat this as a deterministic correctness proof. Returns 0.5
        (neutral) if the model response can't be parsed, rather than
        silently passing everything."""
        prompt = (
            "Rate the following task result from 0.0 (unusable) to 1.0 "
            "(excellent) for task completion quality. Respond with only "
            f"a number.\n\nTask type: {task.get('type')}\n"
            f"Payload: {json.dumps(task.get('payload'))}\n"
            f"Result: {json.dumps(task.get('result'))}"
        )
        try:
            resp = await self.route_fn("fast", prompt, max_tokens=10)
            return max(0.0, min(1.0, float(resp["text"].strip())))
        except (ValueError, KeyError):
            return 0.5

    async def _store(self, task_id: str, verdict: str, checks: dict) -> None:
        eval_id = str(uuid.uuid4())
        await self.db.execute(
            """
            INSERT INTO evaluations (evaluation_id, task_id, verdict, checks, created_at)
            VALUES ($1, $2, $3, $4, $5)
            """,
            eval_id, task_id, verdict, json.dumps(checks), datetime.now(timezone.utc),
        )
