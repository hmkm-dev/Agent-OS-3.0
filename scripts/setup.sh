#!/usr/bin/env bash
# One-command setup. In production mode (default), this FAILS (exit 1)
# — not just warns — if a required variable is missing or still a
# placeholder. Use --dev to relax this for local development where you
# may not have every provider key yet.
#
# Usage:
#   ./scripts/setup.sh          # strict, production mode (default)
#   ./scripts/setup.sh --dev    # lenient, warns only
set -euo pipefail
cd "$(dirname "$0")/.."

MODE="prod"
if [ "${1:-}" = "--dev" ]; then
  MODE="dev"
fi

fail() { echo "[setup] ERROR: $1" >&2; exit 1; }
ok()   { echo "[setup] OK: $1"; }
warn() { echo "[setup] WARNING: $1"; }

echo "[setup] === Mode: $MODE ==="

echo "[setup] === Prerequisite checks ==="
command -v docker >/dev/null 2>&1 || fail "docker not found — run infrastructure/oracle/bootstrap.sh first (official Docker Engine install)"
ok "docker CLI found ($(docker --version))"

docker info >/dev/null 2>&1 || fail "Docker daemon is not reachable. Run: sudo systemctl enable --now docker, then ensure your user is in the docker group (newgrp docker)."
ok "docker daemon reachable"

docker compose version >/dev/null 2>&1 || fail "docker compose plugin not found — install the Compose v2 plugin"
ok "docker compose found ($(docker compose version))"

docker buildx version >/dev/null 2>&1 || fail "docker buildx plugin not found — install docker-buildx-plugin"
ok "docker buildx found"

command -v git >/dev/null 2>&1 || fail "git not found"
ok "git found"

command -v curl >/dev/null 2>&1 || fail "curl not found — required by scripts/healthcheck.sh and others"
ok "curl found"

echo "[setup] === Environment file ==="
if [ ! -f .env ]; then
  cp .env.example .env
  echo "[setup] created .env from .env.example — edit it now, then re-run this script."
  if [ "$MODE" = "prod" ]; then
    fail ".env was just created from the template and cannot contain real credentials yet. Edit .env, then re-run ./scripts/setup.sh."
  fi
else
  ok ".env already exists"
fi

echo "[setup] === Validating required production variables ==="
# shellcheck disable=SC1091
set -a; source .env; set +a

# Vars required for the CORE stack (Hermes+Redis+at least one worker
# doing real work) to function at all. This is deliberately a smaller
# set than "every optional integration" — Qdrant/R2/GitHub/Search/
# Telegram/Cloudflare keys are validated separately below as
# feature-scoped, not core-blocking.
CORE_REQUIRED_VARS=(REDIS_PASSWORD HERMES_API_KEY DATABASE_PASSWORD OPENROUTER_API_KEY)
PLACEHOLDER_VALUES=("change-me-strong-random-password" "change-me-strong-random-key" "")

is_placeholder() {
  local val="$1"
  for p in "${PLACEHOLDER_VALUES[@]}"; do
    [ "$val" = "$p" ] && return 0
  done
  return 1
}

missing=0
for v in "${CORE_REQUIRED_VARS[@]}"; do
  val="${!v:-}"
  if is_placeholder "$val"; then
    if [ "$MODE" = "prod" ]; then
      echo "[setup] ERROR: $v is unset or still a placeholder in .env (required)" >&2
    else
      warn "$v is unset or still a placeholder in .env (required for a working deploy)"
    fi
    missing=1
  fi
done

if [ "$missing" -eq 1 ] && [ "$MODE" = "prod" ]; then
  fail "one or more CORE_REQUIRED_VARS are missing/placeholder — see errors above. Fix .env before continuing (or re-run with --dev to bypass for local iteration)."
fi
[ "$missing" -eq 0 ] && ok "all core required variables are set"

if [ "$MODE" = "prod" ]; then
  [ "${APP_ENV:-production}" != "development" ] || fail "APP_ENV=development is not permitted by strict production setup"
  [ "${#HERMES_API_KEY}" -ge 32 ] || fail "HERMES_API_KEY must be at least 32 characters in production"
fi

echo "[setup] === Feature-scoped variable checks (informational only) ==="
declare -A FEATURE_VARS=(
  ["Qdrant memory"]="QDRANT_URL QDRANT_API_KEY EMBEDDING_API_KEY"
  ["R2 artifacts"]="R2_ENDPOINT R2_ACCESS_KEY_ID R2_SECRET_ACCESS_KEY"
  ["GitHub MCP tool"]="GITHUB_TOKEN"
  ["Search MCP tool"]="BRAVE_SEARCH_API_KEY"
  ["Cloudflare Tunnel"]="CF_TUNNEL_TOKEN"
  ["Telegram alerts"]="TELEGRAM_BOT_TOKEN TELEGRAM_CHAT_ID"
)
for feature in "${!FEATURE_VARS[@]}"; do
  feature_missing=0
  for v in ${FEATURE_VARS[$feature]}; do
    val="${!v:-}"
    [ -z "$val" ] && feature_missing=1
  done
  if [ "$feature_missing" -eq 1 ]; then
    warn "$feature is not fully configured — that feature will raise a clear runtime error when used, rather than fake success. Not a setup blocker."
  else
    ok "$feature configured"
  fi
done

echo "[setup] === Syncing shared modules into isolated build contexts ==="
bash scripts/sync_shared.sh

echo "[setup] === Done ==="
echo "[setup] Next steps:"
echo "  1. ./scripts/deploy.sh"
echo "  2. ./scripts/healthcheck.sh"
