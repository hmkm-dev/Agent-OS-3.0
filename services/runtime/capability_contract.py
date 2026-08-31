"""Contracts for the additive OpenCode universal-executor path.

The contract is deliberately dependency-free and backward compatible with the
existing Redis task payloads. Hermes remains the authority that creates and
approves these requests; OpenCode only validates and executes them.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class CapabilityContractError(ValueError):
    """Raised when a capability request is malformed or exceeds its bounds."""


@dataclass(frozen=True)
class CapabilityBudget:
    timeout_seconds: int = 120
    max_tool_calls: int = 50
    max_subagents: int = 0
    max_cost_usd: float = 5.0

    def __post_init__(self) -> None:
        if not 1 <= self.timeout_seconds <= 900:
            raise CapabilityContractError("timeout_seconds must be between 1 and 900")
        if not 0 <= self.max_tool_calls <= 500:
            raise CapabilityContractError("max_tool_calls must be between 0 and 500")
        if not 0 <= self.max_subagents <= 32:
            raise CapabilityContractError("max_subagents must be between 0 and 32")
        if not 0 <= self.max_cost_usd <= 100:
            raise CapabilityContractError("max_cost_usd must be between 0 and 100")


@dataclass(frozen=True)
class CapabilityRequest:
    """Validated capability metadata attached to one OpenCode execution."""

    execution_id: str
    mission_id: str | None = None
    mission_task_id: str | None = None
    skill_id: str | None = None
    skill_version: int | None = None
    required_tools: tuple[str, ...] = field(default_factory=tuple)
    parent_session_id: str | None = None
    budget: CapabilityBudget = field(default_factory=CapabilityBudget)
    policy_actions: tuple[str, ...] = field(default_factory=tuple)
    context_references: tuple[str, ...] = field(default_factory=tuple)

    @classmethod
    def from_payload(cls, payload: dict[str, Any], *, task_id: str) -> "CapabilityRequest":
        raw = payload.get("capability_request") or {}
        if not isinstance(raw, dict):
            raise CapabilityContractError("capability_request must be an object")
        execution_id = str(raw.get("execution_id") or payload.get("execution_id") or task_id)
        if not execution_id.strip():
            raise CapabilityContractError("execution_id is required")

        def strings(name: str) -> tuple[str, ...]:
            values = raw.get(name) or payload.get(name) or []
            if not isinstance(values, (list, tuple)) or any(not isinstance(v, str) or not v.strip() for v in values):
                raise CapabilityContractError(f"{name} must be a list of non-empty strings")
            return tuple(dict.fromkeys(v.strip() for v in values))

        raw_budget = raw.get("budget") or payload.get("budget") or {}
        if not isinstance(raw_budget, dict):
            raise CapabilityContractError("budget must be an object")
        budget = CapabilityBudget(
            timeout_seconds=int(raw_budget.get("timeout_seconds", payload.get("timeout_seconds", 120))),
            max_tool_calls=int(raw_budget.get("max_tool_calls", 50)),
            max_subagents=int(raw_budget.get("max_subagents", 0)),
            max_cost_usd=float(raw_budget.get("max_cost_usd", 5.0)),
        )
        version = raw.get("skill_version")
        if version is not None:
            version = int(version)
            if version < 1:
                raise CapabilityContractError("skill_version must be positive")
        return cls(
            execution_id=execution_id,
            mission_id=raw.get("mission_id") or payload.get("mission_id"),
            mission_task_id=raw.get("mission_task_id") or payload.get("mission_task_id"),
            skill_id=raw.get("skill_id"),
            skill_version=version,
            required_tools=strings("required_tools"),
            parent_session_id=raw.get("parent_session_id"),
            budget=budget,
            policy_actions=strings("policy_actions"),
            context_references=strings("context_references"),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "execution_id": self.execution_id,
            "mission_id": self.mission_id,
            "mission_task_id": self.mission_task_id,
            "skill_id": self.skill_id,
            "skill_version": self.skill_version,
            "required_tools": list(self.required_tools),
            "parent_session_id": self.parent_session_id,
            "budget": {
                "timeout_seconds": self.budget.timeout_seconds,
                "max_tool_calls": self.budget.max_tool_calls,
                "max_subagents": self.budget.max_subagents,
                "max_cost_usd": self.budget.max_cost_usd,
            },
            "policy_actions": list(self.policy_actions),
            "context_references": list(self.context_references),
        }


def capability_prompt(request: CapabilityRequest) -> str:
    """Render non-secret execution metadata for an OpenCode prompt."""
    tools = ", ".join(request.required_tools) or "none"
    refs = ", ".join(request.context_references) or "none"
    skill = request.skill_id or "default"
    return (
        "\n\n[Agent OS capability contract]\n"
        f"Approved skill: {skill} (version {request.skill_version or 'default'})\n"
        f"Approved tools: {tools}\n"
        f"Context references: {refs}\n"
        f"Tool-call budget: {request.budget.max_tool_calls}; child budget: {request.budget.max_subagents}\n"
        "Use only the approved capabilities. Do not claim verification; return evidence references."
    )
