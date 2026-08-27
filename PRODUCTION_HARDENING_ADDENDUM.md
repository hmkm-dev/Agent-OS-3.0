# Production Hardening Addendum

This addendum records the follow-up hardening completed after the initial production-hardening pass.

## Completed in this follow-up

- **Mission completion integrity:** a task is not marked `passed` when independent verification is pending or failed. `VERIFYING` is now a real task state.
- **Per-task evidence gate:** final mission verification now requires independently verified evidence for every passed/skipped task before the mission can be completed.
- **Research evidence verification:** `source_reference` evidence is independently checked against the claimed URLs instead of being trusted from the worker result.
- **Atomic dispatch claim:** ready tasks are claimed with a PostgreSQL compare-and-set (`pending -> dispatched`) before Redis enqueue, preventing two concurrent Hermes executors from dispatching the same mission task twice.
- **Execution identity:** each dispatch receives a persistent `execution_id`, and the same execution identity is reused during restart reconciliation.
- **Crash recovery:** Hermes startup scans active missions. Queued executions are requeued using the same Hermes task ID; running or missing executions become `unknown_after_crash` instead of being blindly duplicated; terminal Redis executions remain attached for normal reporting.
- **Retry taxonomy:** existing failure categories remain backward compatible while exposing a stable canonical taxonomy for operators/routing.
- **Race-safe mission transitions:** mission completion/blocking transitions use compare-and-set semantics where applicable.
- **Regression tests:** added tests for verification gating, duplicate dispatch prevention, queued restart recovery, ambiguous running recovery, per-task evidence completion gates, source verification, and canonical failure taxonomy.

## Validation

Current local validation:

- `120 passed`
- `14 skipped` (external/live-infrastructure dependent)
- `1 warning` (existing asyncio event-loop deprecation in a resume test)
- Python compile check: `COMPILE_OK`

Docker/live external services were not available in this environment, so those integrations remain subject to the existing integration/E2E checks when the real stack is deployed.

## Safety rule

No existing source file was deleted by this hardening follow-up. Changes are additive or targeted fixes to existing runtime paths.
