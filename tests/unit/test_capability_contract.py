from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "runtime"))

import pytest

from capability_contract import CapabilityContractError, CapabilityRequest, capability_prompt


def test_legacy_payload_is_accepted_with_safe_defaults():
    request = CapabilityRequest.from_payload(
        {"instructions": "inspect repository", "execution_id": "exec-1", "required_tools": ["filesystem"]},
        task_id="task-1",
    )
    assert request.execution_id == "exec-1"
    assert request.required_tools == ("filesystem",)
    assert request.budget.max_subagents == 0
    assert "Approved tools: filesystem" in capability_prompt(request)


def test_nested_capability_request_overrides_legacy_fields():
    request = CapabilityRequest.from_payload(
        {
            "execution_id": "legacy",
            "required_tools": ["filesystem"],
            "capability_request": {
                "execution_id": "exec-2",
                "skill_id": "research",
                "skill_version": 2,
                "required_tools": ["search", "playwright", "search"],
                "budget": {"timeout_seconds": 300, "max_tool_calls": 20, "max_subagents": 2},
            },
        },
        task_id="task-2",
    )
    assert request.execution_id == "exec-2"
    assert request.skill_id == "research"
    assert request.required_tools == ("search", "playwright")
    assert request.budget.timeout_seconds == 300


def test_budget_and_tool_contract_fail_closed():
    with pytest.raises(CapabilityContractError):
        CapabilityRequest.from_payload(
            {"capability_request": {"budget": {"max_tool_calls": 501}}}, task_id="task-3"
        )
    with pytest.raises(CapabilityContractError):
        CapabilityRequest.from_payload(
            {"capability_request": {"required_tools": ["", "filesystem"]}}, task_id="task-4"
        )
