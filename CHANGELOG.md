# Changelog

## [Unreleased] — GitHub/Deployment readiness pass
### Added
- Real OpenCode CLI installation in `services/workers/opencode/Dockerfile`
  (`npm install -g opencode-ai`, verified against official docs), replacing
  the previous "binary not installed" gap.
- `entrypoint.sh` for the OpenCode worker to render provider config from
  `OPENROUTER_API_KEY` at container start.
- `scripts/setup.sh`, `scripts/deploy.sh`, `scripts/update.sh`,
  `scripts/rollback.sh`, `scripts/healthcheck.sh` — full deployment
  lifecycle automation.
- `docs/GITHUB_DEPLOYMENT_AUDIT.md` — repo-wide audit against deployment
  readiness criteria.
- `n8n/workflows/` — example workflow export + import instructions.
- `infrastructure/oracle/`, `infrastructure/cloudflare/` — deployment-specific
  configuration and docs, cross-referenced from `docs/DEPLOYMENT.md`.
- Root-level `LICENSE`, `CONTRIBUTING.md`, `SECURITY.md`, `CHANGELOG.md`.
- Secret-scanning step added to CI (`.github/workflows/ci.yml`).

### Fixed
- N/A this pass beyond what's listed above — see prior entries in
  `docs/IMPLEMENTATION_STATUS.md` for the FK-constraint bug fixed in the
  previous pass (handoffs/memory_records no longer reference a
  not-yet-populated `tasks` table).

### Known limitations (see docs/GITHUB_DEPLOYMENT_AUDIT.md for full list)
- Docker builds and live deployment have **not** been executed in the
  environment that generated this repo (no Docker daemon, no Oracle/
  Cloudflare account access there). Treat the first real `docker compose
  build` on your machine as the actual first test.
- n8n workflow import is documented but the workflow itself is a minimal
  example, not a production-ready routine.
- Teach→Skill testing stage remains `NotImplementedError` (unchanged from
  previous pass) — deferred honestly rather than faked.

## [Previous passes]
See `docs/IMPLEMENTATION_STATUS.md` for the full history of what was
implemented in earlier continuation passes (Hermes core, policy/approval,
Agent Handoff, Qdrant memory pipeline, OpenCode runtime abstraction).

## 2026-08-24 — Release gate hardening

- Added a real Docker/Compose core-stack smoke test.
- CI now runs the smoke test after the Docker build matrix.
- Added release-gate documentation and clarified external E2E acceptance criteria.
