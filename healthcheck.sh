#!/usr/bin/env bash
# Produces a clear per-service report using `docker compose ps
# --services --filter status=running` — service-name based, not
# hard-coded container names, so it works regardless of Compose
# project name.
#
# Two modes, controlled by HEALTHCHECK_MODE (env var or .env):
#   dev (default)  — only Redis + Hermes are REQUIRED; everything
#                     else is OPTIONAL/not-yet-deployed, matching
#                     local iterative development where you bring up
#                     services one phase at a time.
#   production     — redis, postgres, hermes, opencode-worker,
#                     research-worker, creative-worker, mcp, and
#                     playwright are ALL REQUIRED. caddy+cloudflared
#                     are REQUIRED too when CF_TUNNEL_TOKEN is set
#                     (i.e. production edge mode is enabled) — if
#                     you're intentionally running production mode
#                     without the Cloudflare edge (e.g. a private
#                     network deployment), they stay optional. n8n
#                     remains optional in both modes (Phase 10).
#
# Usage:
#   ./scripts/healthcheck.sh                       # uses HEALTHCHECK_MODE from .env, defaults to dev
#   HEALTHCHECK_MODE=production ./scripts/healthcheck.sh
set -uo pipefail
cd "$(dirname "$0")/.."

# Capture an explicitly-passed HEALTHCHECK_MODE (e.g. `HEALTHCHECK_MODE=production
# ./scripts/healthcheck.sh`, the documented usage pattern below) BEFORE sourcing
# .env — otherwise `source .env` would silently overwrite it with whatever
# HEALTHCHECK_MODE happens to be set to in .env, breaking that documented override.
_HEALTHCHECK_MODE_OVERRIDE="${HEALTHCHECK_MODE:-}"
set -a; source .env 2>/dev/null || true; set +a
if [ -n "$_HEALTHCHECK_MODE_OVERRIDE" ]; then
  HEALTHCHECK_MODE="$_HEALTHCHECK_MODE_OVERRIDE"
fi

MODE="${HEALTHCHECK_MODE:-dev}"
COMPOSE="docker compose -f docker-compose.yml"
PASS="OK"
FAIL="DOWN"
OPT="OPTIONAL / not running"
overall_ok=0

running_services="$($COMPOSE ps --services --filter status=running 2>/dev/null || true)"

check_service() {
  local service="$1" label="$2" required="$3"
  if echo "$running_services" | grep -qx "$service"; then
    printf "%-16s %s\n" "$label" "$PASS"
  else
    if [ "$required" = "required" ]; then
      printf "%-16s %s\n" "$label" "$FAIL"
      overall_ok=1
    else
      printf "%-16s %s\n" "$label" "$OPT"
    fi
  fi
}

# Hermes's port 8000 is NOT published to the host in production
# (docker-compose.yml / docker-compose.prod.yml have no 'ports:' for
# hermes — only docker-compose.dev.yml does). So in production mode,
# check the endpoint via `docker compose exec` INSIDE the container
# instead of curling localhost:8000 on the host, which would always
# fail there regardless of Hermes's actual health. Dev mode keeps
# using the host port directly (faster, and it's genuinely published
# there) — same script, mode-appropriate mechanism, real result either way.
check_hermes_endpoint() {
  local path="$1" label="$2" required="$3"
  local ok=1
  if [ "$MODE" = "production" ]; then
    if $COMPOSE exec -T hermes curl -fsS --max-time 5 "http://localhost:8000${path}" > /dev/null 2>&1; then
      ok=0
    fi
  else
    if curl -sf --max-time 5 "http://localhost:8000${path}" > /dev/null 2>&1; then
      ok=0
    fi
  fi
  if [ "$ok" -eq 0 ]; then
    printf "%-16s %s\n" "$label" "$PASS"
  else
    if [ "$required" = "required" ]; then
      printf "%-16s %s\n" "$label" "$FAIL"
      overall_ok=1
    else
      printf "%-16s %s\n" "$label" "$OPT"
    fi
  fi
}

# ── Determine required/optional per service based on MODE ──────────
if [ "$MODE" = "production" ]; then
  REQ_DATA="required"
  REQ_WORKERS="required"
  REQ_TOOLS="required"
  # Edge is required in production mode ONLY when the Cloudflare Tunnel
  # is actually configured (CF_TUNNEL_TOKEN set) — a production
  # deployment on a private network without Cloudflare is still valid
  # and shouldn't be marked "DOWN" for not running cloudflared/caddy.
  if [ -n "${CF_TUNNEL_TOKEN:-}" ]; then
    REQ_EDGE="required"
  else
    REQ_EDGE="optional"
  fi
else
  REQ_DATA="optional"
  REQ_WORKERS="optional"
  REQ_TOOLS="optional"
  REQ_EDGE="optional"
fi

echo "=== agent-os health report (mode: $MODE) ==="

echo "--- Core (always required) ---"
check_service "redis"   "Redis"      required
check_service "hermes"  "Hermes"     required
check_hermes_endpoint "/health" "Hermes/health" required

echo "--- Data layer ---"
check_service "postgres" "PostgreSQL" "$REQ_DATA"
check_hermes_endpoint "/ready" "Hermes/ready" "$REQ_DATA"

echo "--- Workers ---"
check_service "opencode-worker" "OpenCode-W"  "$REQ_WORKERS"
check_service "research-worker" "Research-W"  "$REQ_WORKERS"
check_service "creative-worker" "Creative-W"  "$REQ_WORKERS"

echo "--- Tools ---"
check_service "mcp"        "MCP"         "$REQ_TOOLS"
check_service "playwright" "Playwright"  "$REQ_TOOLS"

echo "--- Edge ---"
check_service "caddy"       "Gateway"     "$REQ_EDGE"
check_service "cloudflared" "Cloudflare"  "$REQ_EDGE"

echo "--- Automation (always optional — Phase 10, behind the 'phase10' profile) ---"
check_service "n8n" "n8n" optional

echo "--- External (Qdrant Cloud — not a Docker service) ---"
if [ -n "${QDRANT_URL:-}" ]; then
  if curl -sf --max-time 5 -H "api-key: ${QDRANT_API_KEY:-}" "${QDRANT_URL}/collections" > /dev/null 2>&1; then
    printf "%-16s %s\n" "Qdrant" "$PASS"
  else
    printf "%-16s %s\n" "Qdrant" "$FAIL"
    # Qdrant is a real feature dependency but intentionally never flips
    # overall_ok — even in production mode, a Qdrant outage shouldn't
    # be indistinguishable from "the whole stack is down" in this
    # script's exit code, since memory features degrade gracefully
    # rather than taking down task execution.
  fi
else
  printf "%-16s %s\n" "Qdrant" "not configured"
fi

echo "==============================="
if [ "$overall_ok" -eq 0 ]; then
  echo "Result: all REQUIRED services healthy (mode: $MODE)"
  exit 0
else
  echo "Result: one or more REQUIRED services are down (mode: $MODE)"
  exit 1
fi
