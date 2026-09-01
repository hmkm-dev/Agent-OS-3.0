#!/usr/bin/env bash
# Deploys the production stack in the phase order documented in README.md.
# Does NOT deploy n8n (behind the phase10 profile) or attempt live
# Cloudflare/Oracle provisioning — those are one-time manual setup steps
# documented in infrastructure/oracle/ and infrastructure/cloudflare/.
set -euo pipefail
cd "$(dirname "$0")/.."

[ -f .env ] || { echo "[deploy] .env not found — run scripts/setup.sh first"; exit 1; }

COMPOSE="docker compose -f docker-compose.yml -f docker-compose.prod.yml"

echo "[deploy] pulling/building images..."
$COMPOSE build

echo "[deploy] starting edge + core..."
$COMPOSE up -d cloudflared caddy redis postgres hermes

echo "[deploy] waiting for hermes to be healthy..."
# Hermes's port 8000 is intentionally NOT published to the host in
# production (docker-compose.yml / docker-compose.prod.yml have no
# 'ports:' for hermes — only docker-compose.dev.yml does, for local
# convenience). So this check runs curl INSIDE the hermes container
# via `docker compose exec`, not against localhost:8000 on the host.
for i in $(seq 1 30); do
  if $COMPOSE exec -T hermes curl -fsS http://localhost:8000/health > /dev/null 2>&1; then
    echo "[deploy] hermes healthy"
    break
  fi
  [ "$i" -eq 30 ] && { echo "[deploy] hermes did not become healthy in time"; exit 1; }
  sleep 2
done

echo "[deploy] running migrations..."
bash scripts/run_migrations.sh

echo "[deploy] starting workers + tools..."
if [ "${HYBRID_MODE:-1}" = "1" ]; then
  echo "[deploy] HYBRID_MODE=1: starting OpenCode universal executor; specialist workers remain available but dormant"
  $COMPOSE up -d opencode-worker mcp playwright
else
  $COMPOSE up -d opencode-worker research-worker creative-worker mcp playwright
fi

echo "[deploy] running healthcheck..."
if [ "${HYBRID_MODE:-1}" = "1" ]; then
  HEALTHCHECK_MODE=hybrid bash scripts/healthcheck.sh
else
  HEALTHCHECK_MODE=production bash scripts/healthcheck.sh
fi

echo "[deploy] done. n8n is NOT started by this script — run:"
echo "  docker compose --profile phase10 up -d n8n"
echo "  once you're ready for README Phase 10."
