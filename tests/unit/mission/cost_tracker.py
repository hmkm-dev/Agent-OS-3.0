"""
Cost/resource control — per spec §13. Real accounting, fed by
model_router.py's `raw_usage` field which was already returned by
every route() call but previously unused by any caller. This module
is the first consumer of it — model_router.py itself is unchanged.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

# Rough per-1K-token USD estimates for cost tracking purposes only —
# NOT used for billing, just to give a mission a directional cost
# signal and to enforce max_cost budgets. Update as needed; these are
# deliberately approximate and documented as such rather than
# presented as precise.
_APPROX_COST_PER_1K_TOKENS = {
    "default": 0.003,
}


class BudgetExceededError(Exception):
    pass


class CostTracker:
    def __init__(self, db):
        self.db = db

    async def record_usage(self, mission_id: str, task_id: str | None, model: str, raw_usage: dict) -> dict:
        prompt_tokens = raw_usage.get("prompt_tokens", 0)
        completion_tokens = raw_usage.get("completion_tokens", 0)
        total = prompt_tokens + completion_tokens
        rate = _APPROX_COST_PER_1K_TOKENS.get(model, _APPROX_COST_PER_1K_TOKENS["default"])
        estimated_cost = round((total / 1000) * rate, 6)

        cost_event_id = str(uuid.uuid4())
        await self.db.execute(
            """
            INSERT INTO mission_cost_events (cost_event_id, mission_id, task_id, model,
                                              prompt_tokens, completion_tokens, estimated_cost_usd, created_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            """,
            cost_event_id, mission_id, task_id, model, prompt_tokens, completion_tokens,
            estimated_cost, datetime.now(timezone.utc),
        )
        return {"cost_event_id": cost_event_id, "estimated_cost_usd": estimated_cost}

    async def mission_totals(self, mission_id: str) -> dict:
        row = await self.db.fetchrow(
            """
            SELECT COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
                   COALESCE(SUM(completion_tokens), 0) AS completion_tokens,
                   COALESCE(SUM(estimated_cost_usd), 0) AS estimated_cost_usd,
                   COUNT(*) AS model_calls
            FROM mission_cost_events WHERE mission_id = $1
            """,
            mission_id,
        )
        return dict(row)

    async def check_budget(self, mission_id: str, budget: dict) -> None:
        """Raises BudgetExceededError if the mission has exceeded any
        configured limit. Call before dispatching each new task —
        this is what actually prevents uncontrolled spend, not just a
        field that exists in the schema and nothing reads."""
        max_cost = budget.get("max_cost")
        max_tokens = budget.get("max_tokens")
        if max_cost is None and max_tokens is None:
            return  # no budget configured — unbounded by design, not by omission

        totals = await self.mission_totals(mission_id)
        if max_cost is not None and float(totals["estimated_cost_usd"]) >= float(max_cost):
            raise BudgetExceededError(
                f"mission {mission_id} has spent an estimated ${totals['estimated_cost_usd']}, "
                f"at or over max_cost=${max_cost}"
            )
        total_tokens = totals["prompt_tokens"] + totals["completion_tokens"]
        if max_tokens is not None and total_tokens >= max_tokens:
            raise BudgetExceededError(
                f"mission {mission_id} has used {total_tokens} tokens, at or over max_tokens={max_tokens}"
            )
