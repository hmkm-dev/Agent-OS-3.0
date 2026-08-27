# Troubleshooting

**Hermes `/health` fails** → Redis is down or unreachable. Check
`docker compose logs redis` and confirm `REDIS_PASSWORD` matches
between `.env` and what Redis was started with.

**Hermes `/ready` shows `postgres: false`** → expected until README
Phase 6. If you're past that phase, check `docker compose logs
postgres` and that migrations were applied (`scripts/run_migrations.sh`).

**Task stuck in `queued` forever** → check the relevant worker is
actually running: `docker compose ps`. Check
`docker compose exec redis redis-cli -a $REDIS_PASSWORD LLEN
queue:<type>` — if it's growing and never shrinking, the worker isn't
consuming (crashed or never started).

**OpenCode worker fails with "binary not found"** → this should not
happen with a correctly built image — `services/workers/opencode/Dockerfile`
installs `opencode-ai@1.18.20` via npm at build time. If you see this,
check the build log for that `RUN npm install -g opencode-ai@1.18.20`
step actually succeeding, and that you rebuilt the image after any
Dockerfile change (`docker compose build opencode-worker`). See
`docs/IMPLEMENTATION_STATUS.md` for the current install status.

**Research worker fails with "SEARCH_PROVIDER not configured"** → set
`SEARCH_PROVIDER=brave` and `BRAVE_SEARCH_API_KEY` in `.env`, then
`docker compose up -d --build research-worker`.

**"OPENROUTER_API_KEY is not set" errors anywhere** → set it in `.env`,
this is required for Hermes's `/internal/route`, which every worker's
text-generation path depends on.

**Container OOM-killed** → check `docker stats`, likely you added a
service without a memory limit or exceeded the 12GB ceiling. See
docs/OPERATIONS.md's resource budget section.

**`sync_shared.sh` seems to have no effect after editing a shared file**
→ you likely edited the wrong copy. `agents/workspace.py` and
`services/workers/common/base_worker.py` are the canonical sources;
edit those, then re-run `scripts/sync_shared.sh`, then rebuild.
