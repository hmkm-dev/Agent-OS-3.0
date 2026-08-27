#!/usr/bin/env bash
set -euo pipefail

# CI-only integration smoke test. Uses synthetic credentials and never calls
# external providers. It proves the Docker/Compose wiring, startup ordering,
# health endpoints, and OpenCode container basics on a real Docker runner.

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

cleanup() {
  docker compose -f docker-compose.yml -f docker-compose.prod.yml down -v --remove-orphans >/dev/null 2>&1 || true
  rm -f .env
}
trap cleanup EXIT

cat > .env <<'EOF'
APP_ENV=test
MAX_AGENT_RETRIES=1
TASK_TIMEOUT=30
APPROVAL_TIMEOUT=30
HEALTHCHECK_MODE=production
DATABASE_PASSWORD=ci-postgres-password
DATABASE_URL=
REDIS_PASSWORD=ci-redis-password
OPENROUTER_API_KEY=
MODEL_REASONING=
MODEL_CODING=
MODEL_CREATIVE=
MODEL_FAST=
MODEL_FALLBACK=
OPENCODE_BIN=opencode
OPENCODE_MODEL=
AGENT_RUNTIME=opencode
MCP_URL=http://mcp:8100
MODEL_ROUTER_URL=http://hermes:8000/internal/route
PLAYWRIGHT_URL=http://playwright:8200
WORKSPACE_ROOT=/workspace
MAX_RETRIES=1
REDIS_URL=
CF_TUNNEL_TOKEN=
CLOUDFLARE_ACCOUNT_ID=
CLOUDFLARE_API_TOKEN=
GITHUB_TOKEN=
SEARCH_PROVIDER=brave
BRAVE_SEARCH_API_KEY=
PLAYWRIGHT_TIMEOUT_MS=10000
QDRANT_URL=
QDRANT_API_KEY=
QDRANT_COLLECTION=agent_memory
EMBEDDING_PROVIDER=openai
EMBEDDING_API_KEY=
OPENAI_API_KEY=
R2_ENDPOINT=
R2_ACCESS_KEY_ID=
R2_SECRET_ACCESS_KEY=
R2_BUCKET_ARTIFACTS=agentos-artifacts
R2_BUCKET_BACKUPS=agentos-backups
N8N_ENCRYPTION_KEY=
N8N_HOST=n8n.yourdomain.com
HERMES_URL=http://hermes:8000
HERMES_API_KEY=ci-hermes-api-key
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
EOF

COMPOSE=(docker compose -f docker-compose.yml -f docker-compose.prod.yml)

echo "[ci-smoke] validating Compose configuration"
"${COMPOSE[@]}" config -q

echo "[ci-smoke] building and starting core stack"
"${COMPOSE[@]}" up -d --build --wait --wait-timeout 240 \
  hermes opencode-worker research-worker creative-worker mcp playwright

echo "[ci-smoke] checking service state"
"${COMPOSE[@]}" ps

echo "[ci-smoke] checking Hermes health"
"${COMPOSE[@]}" exec -T hermes curl -fsS http://localhost:8000/health >/dev/null
"${COMPOSE[@]}" exec -T hermes curl -fsS http://localhost:8000/ready >/dev/null

echo "[ci-smoke] checking MCP health"
"${COMPOSE[@]}" exec -T mcp python -c \
  "import urllib.request; urllib.request.urlopen('http://localhost:8100/health', timeout=5).read()"

echo "[ci-smoke] checking Playwright health"
"${COMPOSE[@]}" exec -T playwright python -c \
  "import urllib.request; urllib.request.urlopen('http://localhost:8200/health', timeout=5).read()"

echo "[ci-smoke] checking OpenCode binary and writable workspace"
"${COMPOSE[@]}" exec -T opencode-worker sh -lc \
  'id && test -w /workspace && opencode --version'

echo "[ci-smoke] checking worker containers are running"
for svc in opencode-worker research-worker creative-worker; do
  state="$("${COMPOSE[@]}" ps --format json "$svc" | python -c 'import json,sys; print(json.load(sys.stdin)["State"])')"
  test "$state" = "running" || { echo "worker $svc is not running: $state"; exit 1; }
done

echo "[ci-smoke] PASS: Docker/Compose core-stack smoke test completed."
