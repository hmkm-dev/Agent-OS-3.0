# Testing

## Test categories
This repo uses 4 pytest markers (registered in `pytest.ini`), applied
consistently across `tests/e2e/*.py`:
- `unit` — `tests/unit/`, no external dependencies, always runs in CI
- `integration` — needs a live local Docker stack, no external cloud creds (`tests/integration/`)
- `e2e` — full live-stack flow
- `external` — additionally requires real external credentials (OpenRouter/Qdrant/R2/Brave/GitHub/Cloudflare/n8n)

Every `e2e`+`external` test's skip reason is prefixed
`EXTERNAL_CREDENTIAL_REQUIRED:` so you can grep for exactly which
tests need what before running them:
```bash
python3 -m pytest tests/e2e -v -m "not external"   # would run nothing right now — all e2e tests currently need external creds
python3 -m pytest tests/e2e -v --collect-only | grep EXTERNAL_CREDENTIAL_REQUIRED
```

## Unit tests (run these — they actually pass)
```bash
python3 -m pip install pyyaml pytest httpx redis --break-system-packages
python3 -m pytest tests/unit -v
```
68 tests verified passing as of this pass, spanning: policy engine (6
core + 8 extended permission classes), workspace path-scoping (2),
handoff manager (3), skill testing (4), tool validation (5, needs
`httpx`), embeddings (4, needs `httpx`), and **53 Mission Control
tests** (`tests/unit/mission/`) — mission state machine, task graph
cycle detection/topological sort, failure classification, evidence
claimed-vs-verified enforcement, cost/budget tracking, the two-level
evaluator's "20/20 tasks ≠ mission complete" property, context
resume-after-restart, and the executor's diagnose→retry/escalate path.
All use real in-memory fakes (`tests/unit/mission/fake_db.py`) that
exercise the actual SQL-adjacent control flow, not mocked-out logic.
`httpx`-dependent tests (9 total) could not be executed in the
generating sandbox
(no network access to install `httpx` there) — inspect
`tests/unit/test_embeddings.py` before trusting it blindly; run it
yourself once you have network access.

## Integration tests (need a live stack)
Bring up core services (see docs/DEPLOYMENT.md), then:

```bash
# Hermes <-> Redis
curl http://localhost:8000/health

# Hermes <-> Postgres
curl http://localhost:8000/ready

# Full task lifecycle: research -> evaluate -> handoff to creative
curl -X POST http://localhost:8000/tasks \
  -H "x-api-key: $HERMES_API_KEY" -H "Content-Type: application/json" \
  -d '{"type":"research","payload":{"query":"best silver hardware home decor trends 2026"}}'
# note the task_id, then poll:
curl http://localhost:8000/tasks/<task_id> -H "x-api-key: $HERMES_API_KEY"
# once status=completed:
curl -X POST http://localhost:8000/tasks/<task_id>/evaluate -H "x-api-key: $HERMES_API_KEY"
# check the response for a "handoff" key with a new_task_id — confirms
# HandoffManager actually dispatched a follow-on creative task
curl http://localhost:8000/tasks/<new_task_id> -H "x-api-key: $HERMES_API_KEY"
```

## E2E tests (real test files, need a live stack)
`tests/e2e/` now contains real pytest files (not just documented curl
sequences), one per required E2E flow. Each **skips cleanly** — not a
false pass — if its required environment variables aren't set, so you
can't mistake "didn't run" for "passed":

```bash
python3 -m pip install pytest httpx redis asyncpg --break-system-packages

# 1. OpenCode real execution
HERMES_URL=http://localhost:8000 HERMES_API_KEY=$HERMES_API_KEY \
  python3 -m pytest tests/e2e/test_opencode_execution.py -v -s

# 2. Agent handoff chain (research -> creative -> opencode)
HERMES_URL=http://localhost:8000 HERMES_API_KEY=$HERMES_API_KEY \
  python3 -m pytest tests/e2e/test_agent_handoff.py -v -s

# 3. Qdrant memory write -> search -> retrieve
DATABASE_URL=... QDRANT_URL=... QDRANT_API_KEY=... \
EMBEDDING_PROVIDER=openai EMBEDDING_API_KEY=... \
  python3 -m pytest tests/e2e/test_memory.py -v -s

# 4. Bounded retry -> require_human (never infinite loop)
HERMES_URL=http://localhost:8000 HERMES_API_KEY=$HERMES_API_KEY \
  python3 -m pytest tests/e2e/test_self_review_loop.py -v -s
```

**None of these were executed in the environment that generated this
repo** — no Docker daemon, no live Postgres/Qdrant/Oracle/Cloudflare
there (see `docs/GITHUB_DEPLOYMENT_AUDIT.md`). They're written to
actually exercise the real HTTP API and make real assertions (exit
codes, non-empty file lists, handoff chain task IDs matching) rather
than smoke-testing "did it not throw" — but the very first time you
run them against your deployed stack is the real proof, not this repo.

## Fresh clone test (do this yourself before trusting this repo)
```bash
cd /tmp && git clone <your-repo-url> agent-os-freshtest && cd agent-os-freshtest
cp .env.example .env && nano .env   # fill in real keys
./scripts/setup.sh
./scripts/deploy.sh
./scripts/healthcheck.sh
python3 -m pytest tests/unit -v
# then the tests/e2e/ commands above, once services are confirmed healthy
```
If any step here requires something not documented in `.env.example`
or `README.md`, that's a real gap — please open an issue (or just fix
it, see `CONTRIBUTING.md`) rather than working around it silently,
since the whole point of this checklist is that nothing should require
tribal knowledge.


## Why these aren't automated in CI
CI (`.github/workflows/ci.yml`) validates the code (lint, unit tests,
Docker builds) on every push, but does not spin up Postgres/Redis/live
API keys — that would require storing your production credentials in
GitHub Actions secrets, which isn't done here without your explicit
choice to do so. If you want CI-driven integration tests later, add a
`services:` block to the workflow for Postgres+Redis containers and
inject test-only API keys via repo secrets.
