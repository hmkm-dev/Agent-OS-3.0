"""
Failure recovery — per spec §6. Classifies failures by real
pattern-matching against error text/context (not a hard-coded single
category), decides whether retry is safe, and requires a strategy
change be recorded before a retry is allowed (no blind identical
retries).
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from enum import Enum


class FailureCategory(str, Enum):
    MODEL_FAILURE = "model_failure"
    TOOL_FAILURE = "tool_failure"
    API_FAILURE = "api_failure"
    NETWORK_FAILURE = "network_failure"
    AUTH_FAILURE = "authentication_failure"
    BROWSER_FAILURE = "browser_failure"
    CODE_FAILURE = "code_failure"
    TEST_FAILURE = "test_failure"
    BAD_PLAN = "bad_plan"
    MISSING_INFORMATION = "missing_information"
    PERMISSION_DENIAL = "permission_denial"
    EXTERNAL_SERVICE_FAILURE = "external_service_failure"
    TIMEOUT = "timeout"
    RESOURCE_EXHAUSTION = "resource_exhaustion"
    UNKNOWN = "unknown"


CANONICAL_FAILURE_CLASSES = {
    "transient", "rate_limit", "timeout", "network", "dependency_unavailable",
    "authentication", "authorization", "validation", "policy", "tool_failure",
    "browser_failure", "data_error", "model_error", "logic_error", "unknown",
}

CATEGORY_TO_CANONICAL = {
    FailureCategory.MODEL_FAILURE: "model_error",
    FailureCategory.TOOL_FAILURE: "tool_failure",
    FailureCategory.API_FAILURE: "validation",
    FailureCategory.NETWORK_FAILURE: "network",
    FailureCategory.AUTH_FAILURE: "authentication",
    FailureCategory.BROWSER_FAILURE: "browser_failure",
    FailureCategory.CODE_FAILURE: "logic_error",
    FailureCategory.TEST_FAILURE: "logic_error",
    FailureCategory.BAD_PLAN: "logic_error",
    FailureCategory.MISSING_INFORMATION: "data_error",
    FailureCategory.PERMISSION_DENIAL: "authorization",
    FailureCategory.EXTERNAL_SERVICE_FAILURE: "dependency_unavailable",
    FailureCategory.TIMEOUT: "timeout",
    FailureCategory.RESOURCE_EXHAUSTION: "rate_limit",
    FailureCategory.UNKNOWN: "unknown",
}


# Ordered: more specific patterns first, since some error strings could
# match multiple categories (e.g. "401" is both API and auth-shaped).
_PATTERNS: list[tuple[FailureCategory, re.Pattern]] = [
    (FailureCategory.AUTH_FAILURE, re.compile(r"\b(401|unauthorized|invalid api key|authentication failed|invalid_api_key)\b", re.I)),
    (FailureCategory.PERMISSION_DENIAL, re.compile(r"\b(403|forbidden|permission denied|not allowed|access denied)\b", re.I)),
    (FailureCategory.TIMEOUT, re.compile(r"\b(timeout|timed out|deadline exceeded|504)\b", re.I)),
    (FailureCategory.RESOURCE_EXHAUSTION, re.compile(r"\b(out of memory|oom|disk full|no space left)\b", re.I)),
    (FailureCategory.RESOURCE_EXHAUSTION, re.compile(r"\b(rate limit|429|too many requests)\b", re.I)),
    (FailureCategory.NETWORK_FAILURE, re.compile(r"\b(connection refused|connection reset|dns|name resolution|network unreachable|econnrefused)\b", re.I)),
    (FailureCategory.BROWSER_FAILURE, re.compile(r"\b(playwright|browser|navigation failed|page crash|chromium)\b", re.I)),
    (FailureCategory.TEST_FAILURE, re.compile(r"\b(assertionerror|test.*failed|pytest|\d+ failed,)\b", re.I)),
    (FailureCategory.CODE_FAILURE, re.compile(r"\b(syntaxerror|typeerror|nameerror|traceback|exit code [1-9]|compilation failed)\b", re.I)),
    (FailureCategory.EXTERNAL_SERVICE_FAILURE, re.compile(r"\b(502|503|bad gateway|service unavailable|upstream)\b", re.I)),
    (FailureCategory.API_FAILURE, re.compile(r"\b(400|422|api error|invalid request)\b", re.I)),
    (FailureCategory.TOOL_FAILURE, re.compile(r"\b(tool.*not (allowed|configured)|mcp.*error)\b", re.I)),
    (FailureCategory.MISSING_INFORMATION, re.compile(r"\b(not found|no such file|missing required|undefined|does not exist)\b", re.I)),
    (FailureCategory.MODEL_FAILURE, re.compile(r"\b(model did not return|invalid json|hallucinat|malformed response)\b", re.I)),
]

# Categories where retrying without a strategy change is almost never
# useful — these should force a strategy change or escalate rather
# than a bare retry.
_REQUIRES_STRATEGY_CHANGE = {
    FailureCategory.AUTH_FAILURE, FailureCategory.PERMISSION_DENIAL,
    FailureCategory.BAD_PLAN, FailureCategory.MISSING_INFORMATION,
}

# Categories that should never be retried automatically at all —
# these need human escalation immediately.
_NEVER_AUTO_RETRY = {
    FailureCategory.PERMISSION_DENIAL,
}


class FailureRecovery:
    def __init__(self, db):
        self.db = db

    def classify(self, error_text: str) -> FailureCategory:
        for category, pattern in _PATTERNS:
            if pattern.search(error_text):
                return category
        return FailureCategory.UNKNOWN

    def canonical_class(self, category: FailureCategory) -> str:
        """Map the backwards-compatible internal category to the stable
        taxonomy exposed to operators and future policy/routing code."""
        return CATEGORY_TO_CANONICAL[category]

    def decide(self, category: FailureCategory, retry_count: int, max_retries: int) -> dict:
        """Returns {"action": "retry"|"retry_with_strategy_change"|"escalate",
        "reason": str}."""
        if category in _NEVER_AUTO_RETRY:
            return {"action": "escalate", "reason": f"{category.value} requires human review, never auto-retried"}

        if retry_count >= max_retries:
            return {"action": "escalate", "reason": f"exhausted {max_retries} retries for {category.value}"}

        if category in _REQUIRES_STRATEGY_CHANGE:
            return {"action": "retry_with_strategy_change",
                    "reason": f"{category.value} rarely resolves by repeating the identical action"}

        return {"action": "retry", "reason": f"{category.value} may be transient"}

    async def record_decision(self, mission_id: str, task_id: str | None, category: FailureCategory,
                               failed_step: str, error_context: str, previous_strategy: str | None,
                               new_strategy: str | None, retry_number: int) -> dict:
        decision_id = str(uuid.uuid4())
        decision_type = "strategy_change" if new_strategy and new_strategy != previous_strategy else "retry"
        reason = f"[{category.value}] failed_step={failed_step} retry#{retry_number}: {error_context[:500]}"

        await self.db.execute(
            """
            INSERT INTO mission_decisions (decision_id, mission_id, task_id, decision_type, reason,
                                            previous_strategy, new_strategy, created_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            """,
            decision_id, mission_id, task_id, decision_type, reason,
            previous_strategy, new_strategy, datetime.now(timezone.utc),
        )
        return {"decision_id": decision_id, "decision_type": decision_type}

    async def diagnose_and_decide(self, mission_id: str, task_id: str, failed_step: str,
                                   error_text: str, retry_count: int, max_retries: int,
                                   previous_strategy: str | None = None) -> dict:
        """The real end-to-end entry point: classify -> decide -> record.
        Returns a structured result the mission executor acts on."""
        category = self.classify(error_text)
        decision = self.decide(category, retry_count, max_retries)

        new_strategy = None
        if decision["action"] == "retry_with_strategy_change":
            new_strategy = (
                f"revised approach after {category.value}: incorporate the failure reason "
                f"into the next attempt's instructions rather than repeating them unchanged"
            )

        record = await self.record_decision(
            mission_id, task_id, category, failed_step, error_text,
            previous_strategy, new_strategy, retry_count + 1,
        )

        return {
            "category": category.value,
            "action": decision["action"],
            "reason": decision["reason"],
            "new_strategy": new_strategy,
            "decision_id": record["decision_id"],
        }
