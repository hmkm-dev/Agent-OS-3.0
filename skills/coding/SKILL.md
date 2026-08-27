# Skill: Coding

**Status: IMPLEMENTED** — runs via the existing OpenCode worker + AgentRuntime abstraction. No external prerequisite beyond `OPENROUTER_API_KEY` (already required for the whole system).

## Purpose
Write, modify, test, and debug code as part of a mission task — repository changes, new files, bug fixes, small utilities.

## Inputs
- `instructions`: natural-language description of the coding task
- `repo_url` (optional): repository to clone into the task workspace first

## Outputs
- `exit_code`, `stdout`, `stderr`, `files_changed`, `duration_seconds` (see `services/runtime/agent_runtime.py:RuntimeResult`)

## Allowed tools
`filesystem`, `github` (per `services/mcp/gateway.py`'s `ALLOWLIST["opencode"]` — unchanged by this pass)

## Workflow
1. Hermes creates a task with `type: "opencode"`, policy-checked (category `GITHUB_WRITE` by default)
2. OpenCode worker clones (if `repo_url` given) into an isolated per-task workspace
3. `OpenCodeRuntime.execute()` runs `opencode run "<instructions>"`, captures real stdout/stderr/exit code
4. Workspace cleaned up after (success or failure)

## Success criteria
- `exit_code == 0`
- For mission tasks: `files_changed` is non-empty when the task implies a change

## Verification (not just claimed)
Test/build execution verified via `EvidenceEngine.verify()` with a real `{"method": "pytest", "exit_code": 0, ...}` detail, not just "OpenCode said it worked".

## Failure handling
Routed through `services/mission/failure_recovery.py`'s classifier — `code_failure`/`test_failure` patterns trigger a strategy-changed retry, not a blind repeat.
