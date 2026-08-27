# Final Audit

Phase 1 deliverable for this pass, in the exact requested format
(component / current implementation / status / issue / required fix /
severity). This is the **sixth** continuation pass on this repository
— for full history of everything closed in passes 1–5 (Hermes core,
policy/approval, agent handoff, Qdrant memory, OpenCode install, skill
testing, deployment scripts), see `docs/IMPLEMENTATION_STATUS.md` and
`docs/GITHUB_DEPLOYMENT_AUDIT.md`. This document covers only what this
pass's audit actually found — new issues, not a re-derivation of
everything already closed.

| Component | Current implementation | Status | Issue | Required fix | Severity |
|---|---|---|---|---|---|
| `cloudflared` image | `cloudflare/cloudflared:latest` | Fixed this pass | Unpinned — floats to whatever's newest at build time, breaks reproducibility | Pinned to `2026.8.2` (verified real current tag via Docker Hub) | HIGH |
| `n8n` image | `n8nio/n8n:latest` | Fixed this pass | Same issue | Pinned to `1.82.1` (verified real tag) | HIGH |
| `redis`/`postgres`/`caddy` images | `redis:7-alpine`, `postgres:16-alpine`, `caddy:2-alpine` | Fixed this pass | Minor-version pinned but not patch-pinned — still drifts | Pinned to `7.4-alpine`, `16.4-alpine`, `2.8-alpine` | MEDIUM |
| Custom service base images | `python:3.12-slim` (×5 Dockerfiles) | Fixed this pass | Same floating-patch issue | Pinned to `python:3.12.7-slim` across Hermes, MCP, and all 3 workers | MEDIUM |
| `playwright-service` container user | Ran as root (only service that did) | Fixed this pass | Inconsistent with the non-root posture of Hermes/MCP/research-worker/creative-worker | Added `useradd`+`chown`+`USER pwuser`; documented the `--no-sandbox` fallback if Chromium's sandbox conflicts with non-root | MEDIUM |
| `scripts/setup.sh` required-var handling | Warned only, never blocked | Fixed this pass | A production deploy could proceed with a missing `OPENROUTER_API_KEY`/`DATABASE_PASSWORD`/etc. and fail confusingly later, deep in a worker | Rewrote with `CORE_REQUIRED_VARS` + strict-by-default `exit 1`; `--dev` flag for lenient local iteration. **Actually executed 3 test scenarios with a stubbed docker binary** confirming exit 1/1/0 correctly | HIGH |
| `scripts/healthcheck.sh`, `run_migrations.sh`, `backup.sh`, `restore.sh` | Hard-coded `agent-os-postgres-1` etc. container names | Fixed this pass | Breaks if the Compose project name ever differs from `agent-os` (e.g. cloning into a differently-named directory) | Switched to `docker compose exec <service>` / `docker compose ps --services --filter status=running` throughout. **healthcheck.sh's logic actually executed** with stubbed `docker compose ps` output, confirmed correct classification | HIGH |
| `docs/OPERATIONS.md`, `docs/TROUBLESHOOTING.md` | Referenced `docker exec agent-os-redis-1` in example commands | Fixed this pass | Same hard-coding issue, in documentation this time | Updated to `docker compose exec redis` | LOW |
| `.env.example` completeness | 31 variables documented | Fixed this pass | 9 real variables used in code (`AGENT_RUNTIME`, `MAX_RETRIES`, `MCP_URL`, `MODEL_ROUTER_URL`, `PLAYWRIGHT_URL`, `REDIS_URL`, `WORKSPACE_ROOT`, `OPENAI_API_KEY` fallback) were undocumented | Added all 9 with explanatory comments (most are internal-URL overrides with safe Compose-network defaults) | MEDIUM |
| Test categorization | `tests/unit/`, `tests/e2e/`, `tests/integration/` existed as directories but with no formal marker system | Fixed this pass | No way to programmatically distinguish "needs external credentials" from "needs live Docker but no cloud creds" — Phase 17's explicit requirement | Added `pytest.ini` with 4 registered markers (`unit`/`integration`/`e2e`/`external`); all 7 e2e test files' skip reasons now prefixed `EXTERNAL_CREDENTIAL_REQUIRED:` and grep-able; CI now runs unit and e2e/external as separate steps with a marker filter | MEDIUM |
| Playwright smoke test (credential-free) | Did not exist as a standalone test — Playwright was only exercised indirectly through the research worker's MCP calls | Fixed this pass | Phase 10 explicitly required a dedicated smoke test independent of social media credentials | **New**: `tests/e2e/test_playwright_smoke.py` — hits the playwright-service container directly, uses `example.com` (IANA-reserved test domain), includes a negative test (invalid domain must return a real error, not a fake 200) | MEDIUM |
| `docs/CLOUDFLARE_DEPLOYMENT.md`, `docs/ORACLE_DEPLOYMENT.md`, `docs/ENVIRONMENT.md`, `docs/BACKUP_RESTORE.md`, root `DEPLOYMENT.md` | Did not exist at these exact paths (equivalent content existed under `infrastructure/*/README.md` and `docs/OPERATIONS.md`) | Fixed this pass | Explicitly requested filenames were missing | Created all 5, cross-referencing rather than duplicating the existing `infrastructure/` docs where content overlapped | LOW |
| Logs/secret leakage | N/A (check, not a prior gap) | **Verified clean** | Checked whether any `print()`/log statement could leak `REDIS_URL`, `DATABASE_URL`, or any `*_API_KEY`/`*_PASSWORD`/`*_TOKEN` value | None found — `setup.sh` only compares `$val`, never prints it; `entrypoint.sh` only checks `-n "$OPENROUTER_API_KEY"`, never echoes it | N/A (no issue) |
| Non-root coverage (Hermes, MCP, research-worker, creative-worker) | Already non-root from a prior pass | **Verified still correct** | None found | None needed | N/A |
| `opencode-worker` root user | Intentionally root (documented reason: workspace volume write access + `git clone`) | **Confirmed still intentional, not a regression** | None — this was a deliberate, documented tradeoff, not an oversight | None — flagged here so it isn't mistaken for something this pass missed | N/A (accepted risk, documented) |

## What this pass did NOT touch (by design, per "do not redesign" instructions)
- Hermes/Redis/Worker/MCP/Evaluator/Handoff/Memory core logic — unchanged, already real from prior passes
- OpenCode as the coding worker — unchanged, not replaced
- DSH — still not implemented, still correctly deferred
- Architecture shape (Cloudflare→Tunnel→Caddy→Hermes→Redis→Workers→MCP→Evaluator→Memory→R2→n8n) — unchanged

## Severity legend
- **HIGH**: would cause a real deployment failure or meaningfully weaken reproducibility/security if left unfixed
- **MEDIUM**: real gap, not immediately deployment-blocking, but should be fixed before calling the repo production-hardened
- **LOW**: hygiene/consistency issue
- **N/A**: verification check with no issue found, or an intentional/accepted tradeoff
