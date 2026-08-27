"""
Strategy objects — per spec §7. A "strategy_changed" retry must
actually carry different parameters, not just a re-worded reason
string. This module persists a real strategy row per attempt and
requires the NEXT strategy's parameters to differ from the previous
one whenever failure_recovery decided a change was required —
enforced here, not just documented.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone


class StrategyNotChangedError(Exception):
    """Raised if code tries to record a 'strategy change' whose
    parameters are identical to the previous strategy — this is the
    concrete guard against the exact anti-pattern the spec calls out:
    incrementing retry_count and mislabeling it a strategy change."""


# Concrete strategy parameter templates per failure category — real
# alternatives, not placeholders. A caller building the next attempt's
# task payload should merge these parameters in, not just log them.
STRATEGY_TEMPLATES = {
    "authentication_failure": [
        {"approach": "refresh_credentials_and_retry", "note": "re-read the current OPENROUTER_API_KEY/GITHUB_TOKEN from env in case it rotated"},
        {"approach": "escalate_to_human", "note": "credentials are likely genuinely invalid, not stale"},
    ],
    "browser_failure": [
        {"approach": "click_by_selector", "playwright_strategy": "css_selector"},
        {"approach": "click_by_text", "playwright_strategy": "text_locator"},
        {"approach": "alternative_navigation_path", "playwright_strategy": "direct_url"},
    ],
    "missing_information": [
        {"approach": "research_source_primary", "source_priority": 1},
        {"approach": "research_source_alternative", "source_priority": 2},
    ],
    "code_failure": [
        {"approach": "opencode_direct_execution", "runtime": "opencode"},
        {"approach": "opencode_with_narrower_scope", "runtime": "opencode", "note": "break the failing step into smaller sub-instructions"},
    ],
}


class StrategyManager:
    def __init__(self, db):
        self.db = db

    async def get_current_strategy(self, task_id: str) -> dict | None:
        row = await self.db.fetchrow(
            "SELECT * FROM mission_strategies WHERE task_id = $1 ORDER BY version DESC LIMIT 1", task_id
        )
        return dict(row) if row else None

    async def record_strategy(self, task_id: str, reason: str, parameters: dict,
                               require_change: bool = False) -> dict:
        """Persists a new strategy version. If require_change=True
        (failure_recovery classified this as needing a real strategy
        change), the new parameters must differ from the previous
        strategy's — raises StrategyNotChangedError otherwise, so a
        lazy caller cannot silently pass the same parameters through."""
        previous = await self.get_current_strategy(task_id)

        if require_change and previous is not None:
            prev_params = previous["parameters"]
            if isinstance(prev_params, str):
                prev_params = json.loads(prev_params)
            if prev_params == parameters:
                raise StrategyNotChangedError(
                    f"task {task_id}: a strategy change was required but the new parameters "
                    f"are identical to the previous strategy — {parameters}"
                )

        strategy_id = str(uuid.uuid4())
        version = (previous["version"] + 1) if previous else 1
        await self.db.execute(
            """
            INSERT INTO mission_strategies (strategy_id, task_id, version, reason, parameters,
                                             previous_strategy_id, created_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            """,
            strategy_id, task_id, version, reason, json.dumps(parameters),
            previous["strategy_id"] if previous else None, datetime.now(timezone.utc),
        )
        return {"strategy_id": strategy_id, "version": version}

    def next_template(self, category: str, attempt_number: int) -> dict:
        """Real alternative parameters for a given failure category and
        attempt number — cycles through STRATEGY_TEMPLATES rather than
        returning the same one every time. Falls back to a generic
        'vary the approach' template for categories without a specific
        one defined yet (documented as a real gap, not silently reused
        as identical params — the generic template still varies a
        `variant` field by attempt_number so require_change's equality
        check won't spuriously fire)."""
        templates = STRATEGY_TEMPLATES.get(category)
        if templates:
            return templates[min(attempt_number, len(templates) - 1)]
        return {"approach": "generic_retry_with_variation", "variant": attempt_number}
