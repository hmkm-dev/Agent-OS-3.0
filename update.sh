#!/usr/bin/env bash
# git pull -> rebuild -> migrate -> restart -> healthcheck -> auto-rollback
# on healthcheck failure. This is the only sanctioned update path — avoid
# manually rebuilding individual services out of this order.
set -uo pipefail
cd "$(dirname "$0")/.."

PREV_COMMIT=$(git rev-parse HEAD)
echo "[update] current commit: $PREV_COMMIT"

echo "[update] pulling latest..."
git pull --ff-only || { echo "[update] git pull failed (not a fast-forward?) — resolve manually"; exit 1; }

bash scripts/sync_shared.sh

COMPOSE="docker compose -f docker-compose.yml -f docker-compose.prod.yml"

echo "[update] rebuilding images..."
$COMPOSE build

echo "[update] running any new migrations..."
bash scripts/run_migrations.sh || echo "[update] migration step reported an issue — check output above"

echo "[update] restarting services..."
$COMPOSE up -d

echo "[update] waiting 10s then health-checking..."
sleep 10
if bash scripts/healthcheck.sh; then
  echo "[update] SUCCESS — now on commit $(git rev-parse HEAD)"
  exit 0
else
  echo "[update] HEALTHCHECK FAILED — rolling back to $PREV_COMMIT"
  bash scripts/rollback.sh "$PREV_COMMIT"
  exit 1
fi
