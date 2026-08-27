"""
Policy engine — every sensitive action passes through here before
execution. Rules are loaded from rules.yaml so they're editable
without a code change. Real implementation, not a stub: it makes an
actual ALLOW/DENY/REQUIRE_APPROVAL decision based on configured rules
and logs every decision to the audit_logs table (via the caller).

Usage:
    from policy.engine import PolicyEngine
    engine = PolicyEngine()
    decision = engine.evaluate(action="EXTERNAL_POST", context={...})
    # decision.result in {"ALLOW", "DENY", "REQUIRE_APPROVAL"}
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal

import yaml

DecisionResult = Literal["ALLOW", "DENY", "REQUIRE_APPROVAL"]

ACTION_CATEGORIES = {
    "READ_FILE",
    "WRITE_FILE",
    "EXECUTE_COMMAND",
    "BROWSER_NAVIGATION",
    "EXTERNAL_POST",
    "GITHUB_WRITE",
    "DEPLOYMENT",
    "CREDENTIAL_ACCESS",
    "DATABASE_WRITE",
}

DEFAULT_RULES_PATH = os.path.join(os.path.dirname(__file__), "rules.yaml")


@dataclass
class PolicyDecision:
    action: str
    result: DecisionResult
    reason: str
    matched_rule: str | None = None


class PolicyEngine:
    def __init__(self, rules_path: str = DEFAULT_RULES_PATH):
        self.rules_path = rules_path
        self.rules = self._load_rules()

    def _load_rules(self) -> dict:
        if not os.path.exists(self.rules_path):
            raise FileNotFoundError(
                f"policy rules file not found at {self.rules_path} — "
                "the system refuses to run with an undefined policy rather "
                "than silently allowing everything."
            )
        with open(self.rules_path) as f:
            data = yaml.safe_load(f) or {}
        for action in data.get("rules", {}):
            if action not in ACTION_CATEGORIES:
                raise ValueError(f"unknown action category in rules.yaml: {action}")
        return data

    def reload(self):
        """Hot-reload rules without restarting Hermes."""
        self.rules = self._load_rules()

    def evaluate(self, action: str, context: dict | None = None) -> PolicyDecision:
        context = context or {}

        if action not in ACTION_CATEGORIES:
            return PolicyDecision(
                action=action,
                result="DENY",
                reason=f"unknown action category '{action}' — deny by default",
            )

        rule = self.rules.get("rules", {}).get(action)
        if rule is None:
            default = self.rules.get("default", "REQUIRE_APPROVAL")
            return PolicyDecision(
                action=action,
                result=default,
                reason=f"no explicit rule for '{action}', using default policy",
            )

        base_result: DecisionResult = rule.get("decision", "REQUIRE_APPROVAL")

        # Conditional escalation: e.g. destructive keyword match forces approval
        # even if the base rule for the category is ALLOW.
        blocklist = rule.get("deny_if_contains", [])
        payload_str = str(context.get("payload", "")).lower()
        for kw in blocklist:
            if kw.lower() in payload_str:
                return PolicyDecision(
                    action=action,
                    result="DENY",
                    reason=f"payload matched restricted term '{kw}'",
                    matched_rule=action,
                )

        escalate_if = rule.get("require_approval_if_contains", [])
        for kw in escalate_if:
            if kw.lower() in payload_str:
                return PolicyDecision(
                    action=action,
                    result="REQUIRE_APPROVAL",
                    reason=f"payload matched escalation term '{kw}'",
                    matched_rule=action,
                )

        return PolicyDecision(
            action=action,
            result=base_result,
            reason=rule.get("reason", "matched configured rule"),
            matched_rule=action,
        )
