#!/usr/bin/env bash
# Rolls the repo back to a specific commit (or the previous one if none
# given) and restarts services. Does NOT roll back database migrations —
# migrations in this repo are additive/idempotent (IF NOT EXISTS), not
# reversible; a schema rollback would need a hand-written down-migration,
# which is intentionally not auto-generated here.
set -euo pipefail
cd "$(dirname "$0")/.."

TARGET_COMMIT="${1:-}"
if [ -z "$TARGET_COMMIT" ]; then
  TARGET_COMMIT=$(git rev-parse HEAD~1)
  echo "[rollback] no commit given, defaulting to previous commit: $TARGET_COMMIT"
fi

echo "[rollback] checking out $TARGET_COMMIT..."
git checkout "$TARGET_COMMIT" -- services/ docker-compose.yml docker-compose.prod.yml docker-compose.dev.yml

bash scripts/sync_shared.sh

COMPOSE="docker compose -f docker-compose.yml -f docker-compose.prod.yml"
echo "[rollback] rebuilding and restarting..."
$COMPOSE build
$COMPOSE up -d

sleep 10
bash scripts/healthcheck.sh && echo "[rollback] rollback successful, services healthy" \
  || echo "[rollback] WARNING: still unhealthy after rollback — manual intervention needed"
