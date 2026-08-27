# Gap Analysis — Goal-Completion Agent Harness Upgrade

Against the Mission Control spec. This is Step 2-3 of the requested
procedure: what exists, what's partial, what's missing, what should
NOT change.

## What already exists (do not touch)
- Hermes as supervisor/orchestrator (`services/hermes/app.py`) — task creation, policy check, approval gating, Redis enqueue, status tracking
- Model router with task-type routing + fallback (`services/hermes/model_router.py`)
- Policy engine, YAML-configured (`services/policy/`)
- Approval system, human-only enforcement (`services/approval/`)
- Task-level evaluator (`services/evaluator/`)
- Agent handoff (`services/handoff/`) — research→creative→opencode chain
- Qdrant memory pipeline (`services/memory/`)
- Skill engine with teach-to-skill + tool validation (`services/skill_engine/`)
- OpenCode worker + AgentRuntime abstraction (`services/runtime/`, `services/workers/opencode/`)
- Research/Creative workers (kept — see decision below on NOT merging into OpenCode)
- MCP gateway with per-worker allowlists (`services/mcp/`)
- Postgres schema (`migrations/001_init.sql`), Redis queues, R2 (creative worker), n8n (optional)
- Docker Compose (base/dev/prod), CI, deployment scripts, docs — all from prior passes

## Explicit architecture decision: OpenCode as universal executor
The spec says "do not create separate Research/Coding/Creative workers
unless a real technical reason exists" and "OpenCode remains the
universal execution worker." **This repo already has separate
Research and Creative workers from prior passes.** Per the strict
"do not remove working components" / "do not break existing working
code" rules governing this whole task, I am **not deleting** those
workers — that would be a real architectural removal, which the task
explicitly also forbids elsewhere ("DO NOT remove working
components"). These two instructions are in tension for this specific
point; I'm resolving it conservatively: existing Research/Creative
workers stay as-is (untouched, still functional), and **Mission
Control's task graph is written to be executor-agnostic** — a task
can be assigned to `opencode`, `research`, or `creative` — so new
mission-driven work can lean on OpenCode as the primary/default
executor per the spec's intent, without deleting working code. This
is flagged here explicitly rather than silently deciding one way.

## What's missing — being built this pass (real code, not stubs)
| Component | Plan |
|---|---|
| Mission Control persistence | New `missions`/`mission_tasks` tables (migration 002), `services/mission/control.py` — real Postgres CRUD |
| Goal decomposition engine | `services/mission/decomposition.py` — real call through the existing model router to turn a goal into a task graph |
| Task graph | `services/mission/task_graph.py` — dependency-aware, topological execution order, cycle detection |
| Autonomous execution loop | `services/mission/executor.py` — drives PLAN→SELECT→EXECUTE→INSPECT→EVALUATE→PASS/FAIL→DIAGNOSE→REPLAN→RETRY, dispatches real tasks through the existing Hermes `/tasks` + `/tasks/{id}/evaluate` machinery (reuses it, doesn't duplicate it) |
| Failure recovery / classification | `services/mission/failure_recovery.py` — real classifier (pattern-matches error text/context into the requested categories), strategy-change logic, bounded retry |
| Evidence engine | `services/mission/evidence.py` — Postgres-backed evidence records, `claimed vs verified` distinction |
| Two-level evaluator | `services/mission/mission_evaluator.py` — wraps the existing task evaluator, adds a real mission-level check against `success_criteria` |
| Persistent mission artifacts | `services/mission/artifacts.py` — writes `GOAL.md/PLAN.md/STATE.json/PROGRESS.md/DECISIONS.md/FAILURES.md/TODO.md/FINAL_REPORT.md` per mission, backed by the workspace pattern already in `agents/workspace.py` |
| Context management | `services/mission/context.py` — summarization-on-threshold using the model router, persists to `STATE.json`/Postgres rather than relying on conversation history (real, but the "when is context too large" threshold is necessarily a configured heuristic, documented as such) |
| Policy permission classes | Extend `services/policy/rules.yaml` with the requested classes (READ/WRITE/EXECUTE/NETWORK/BROWSER/GITHUB/DEPLOY/SOCIAL_POST/FINANCIAL/DESTRUCTIVE) — additive, doesn't touch existing categories |
| Cost/resource control | `services/mission/cost_tracker.py` — real token/cost accounting fed by `model_router.py`'s existing `raw_usage` response field (already returned, previously unused) |
| Observability / CLI | New Hermes endpoint `GET /missions/{id}/status` + `scripts/mission_status.sh` (curl wrapper, consistent with existing script patterns) |
| Skills directory restructure | `skills/{coding,research,seo,marketing,devops,creative,pinterest,instagram}/SKILL.md` — real structure, each skill's SKILL.md **honestly marks** which parts are implemented (coding via OpenCode, research via MCP search) vs. external-prerequisite integration points (Pinterest/Instagram APIs — no fake success) |

## What's explicitly NOT being built (external prerequisites, documented not faked)
- Real Cloudflare Queues integration — needs a live Cloudflare account/API token this session doesn't have. Documented as an integration point in `docs/ARCHITECTURE.md`'s update, with the real Cloudflare Queues API referenced accurately, not fabricated.
- Real Pinterest/Instagram API calls — needs OAuth app registration + approval, external to this repo. `skills/pinterest/SKILL.md` and `skills/instagram/SKILL.md` document exactly what credentials/setup are needed and mark the tool-call layer as an integration point.
- Crawl4AI/SearXNG MCP servers — not currently deployed in this repo; documented as optional, config-gated additions in the MCP layer's enable/disable mechanism, not implemented as running services (no evidence they're needed yet vs. the existing Brave Search adapter).

## Database changes
One new additive migration (`migrations/002_mission_control.sql`) —
does not alter or drop any existing table. `missions`, `mission_tasks`,
`mission_evidence`, `mission_decisions`, `mission_cost_events` tables,
all `IF NOT EXISTS`, matching the existing migration's idempotent style.
