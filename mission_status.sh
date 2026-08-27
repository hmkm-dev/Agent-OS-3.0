#!/usr/bin/env bash
# CLI wrapper for GET /missions/{id}/status, per spec §14's
# "mission status <mission_id>" requirement. Thin curl+optional-jq
# wrapper — all real logic lives in the Hermes endpoint itself.
#
# Usage:
#   ./scripts/mission_status.sh <mission_id>
#   ./scripts/mission_status.sh --list          # list active missions
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; source .env 2>/dev/null || true; set +a

HERMES_URL="${HERMES_URL:-http://localhost:8000}"

if [ "${1:-}" = "--list" ]; then
  ENDPOINT="$HERMES_URL/missions"
else
  MISSION_ID="${1:-}"
  if [ -z "$MISSION_ID" ]; then
    echo "Usage: $0 <mission_id>  |  $0 --list"
    exit 1
  fi
  ENDPOINT="$HERMES_URL/missions/$MISSION_ID/status"
fi

RESPONSE=$(curl -sf -H "x-api-key: ${HERMES_API_KEY:-}" "$ENDPOINT")

if command -v jq >/dev/null 2>&1; then
  echo "$RESPONSE" | jq .
else
  echo "$RESPONSE"
  echo "[mission_status] (install jq for pretty-printed output)"
fi
