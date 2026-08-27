# Architecture

## Layers

```
Cloudflare (WAF/Auth/RateLimit/Tunnel)
        │
   Origin Gateway (Caddy)
        │
      Hermes  ── policy engine, approval manager, model router, evaluator
        │
      Redis (task queues: opencode/research/creative + results + dead-letter)
        │
 ┌──────┼──────┐
 ▼      ▼      ▼
OpenCode Research Creative   (workers — BaseWorker shared retry/heartbeat/timeout)
 │      │      │
 └──────┼──────┘
        ▼
   MCP Gateway (per-worker tool allowlists)
        │
 ┌──────┼──────┐
 ▼      ▼      ▼
Search GitHub Playwright(isolated container)
        │
   PostgreSQL (structured state) + Qdrant Cloud (semantic memory) + R2 (blobs)
        │
       n8n (schedules/webhooks, Phase 10+)
```

## Why Qdrant is not self-hosted

Self-hosted Qdrant idles at 300-500MB+ RAM and grows with vector
count. On a 12GB Oracle Always Free box shared with Postgres, Redis,
Hermes, three workers, MCP, and Playwright, that's not a good trade.
Qdrant Cloud's free tier (1GB) covers early-stage usage at zero RAM
cost on the VM. Revisit only once you outgrow 1GB.

## Why no Prometheus/Grafana by default

That stack alone can consume 1-1.5GB RAM. `scripts/healthcheck-alert.sh`
(cron + Telegram) covers "is anything broken" at near-zero cost. Add
real dashboards once you have paid/larger infra or genuinely need
historical metrics, not before.

## Network segmentation

Three Docker networks:
- `edge` — only `cloudflared` and `caddy`. Nothing else touches it.
- `internal` — Hermes, workers, MCP, Playwright, n8n.
- `data` — Redis, Postgres. Also on `internal` so Hermes/workers can
  reach them, but never on `edge`.

## Agent handoff (implemented)

The Research → Creative → Coding handoff chain described in earlier
drafts of this doc is implemented — see `services/handoff/manager.py`
and its wiring into `services/hermes/app.py`'s `/tasks/{id}/evaluate`
endpoint via `HANDOFF_CHAIN`. A passing task automatically constructs
and dispatches a real follow-on task for the next worker type.

## Mission Control (goal-completion harness)

On top of the task-level system above, `services/mission/` adds a
persistent, goal-driven layer per the autonomous-agent-harness spec:

```
USER GOAL
  ↓
POST /missions          (MissionControl — Postgres-persisted, state-machine-validated)
  ↓
POST /missions/{id}/plan (GoalDecomposer — real model-router call → dependency-aware TaskGraph)
  ↓
POST /missions/{id}/execute  (MissionExecutor — dispatches ready tasks onto the
  ↓                           SAME Redis queues/workers described above)
  worker executes (existing OpenCode/Research/Creative + MCP + evaluator, unchanged)
  ↓
POST /missions/{id}/tasks/{task_id}/report  (feeds the task evaluator's verdict
  ↓                                          back into FailureRecovery or EvidenceEngine)
FAIL → FailureRecovery.diagnose_and_decide() → retry-with-strategy-change | escalate
PASS → EvidenceEngine.record_claim() (CLAIMED, not yet VERIFIED)
  ↓
all tasks terminal → MissionEvaluator.evaluate_mission()
  (mission-level check against success_criteria, using ONLY verified evidence —
   "20/20 tasks passed" is explicitly NOT sufficient on its own)
  ↓
COMPLETED (only if verified) | BLOCKED (with a clear reason)
```

Key design choice: Mission Control does **not** duplicate task
execution — it reuses the exact Redis queues, workers, MCP gateway,
and task-level evaluator described above. It adds the goal→task-graph
→verification layer on top, per `docs/MISSION_CONTROL_GAP_ANALYSIS.md`.

Persistent artifacts (`GOAL.md`, `PLAN.md`, `STATE.json`, `PROGRESS.md`,
`DECISIONS.md`, `FAILURES.md`, `TODO.md`, `FINAL_REPORT.md`) are
written per-mission via `services/mission/artifacts.py`, so a mission
can resume after a process/Docker restart from Postgres + these files
alone — never from conversation history.
