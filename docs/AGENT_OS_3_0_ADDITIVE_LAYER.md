# Agent OS 3.0 — Additive Capability Layer

This release adds Prime/RLM-style execution, long-running autonomy, continual harness refinement, dedicated worker role specifications, resource accounting, trajectory/checkpoints, executable Python-backed skills and security helpers **without deleting or replacing existing Agent OS services**.

## Prime/RLM
Persistent Python REPL, optional IPython availability check, recursive `rlm()` child sessions, bounded parallel fan-out, background sessions, parent/child messaging, context-as-variable, compaction, snapshots/resume and programmatic tool calls with per-agent allowlists.

## Long-running autonomy
Persistent goals, autonomous mode, heartbeats, bounded continuation, scheduling, detach/reattach/resume and turn/token/time/tool/sub-agent/cost budgets.

## Continual Harness
`ContinualHarness.refine()` is evidence-gated. The base system prompt is immutable. Only supplemental prompt notes, memories, skills and sub-agent specifications are mutable. Snapshots and rollback are supported.

## Workers
Existing OpenCode/Research/Creative workers are untouched. `WorkerRegistry` adds RLM, Browser, Verification, SEO, Marketing and DevOps role specifications and least-privilege tool sets.

## Resource / audit / safety
Token/time/tool/sub-agent/cost accounting, cheap-model policy, hash-chained trajectories, checkpoints, AST-validated Python skills and sandbox path checks are included.

## Persistence
`migrations/004_agent_os_3_0.sql` adds only new tables; it does not drop or alter existing tables.
