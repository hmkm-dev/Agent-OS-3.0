#!/usr/bin/env bash
# Lightweight monitoring: checks service /health endpoints and container
# memory pressure, alerts via Telegram on failure. Run via cron, e.g.:
#   */5 * * * * /path/to/agent-os/scripts/healthcheck-alert.sh
set -uo pipefail

cd "$(dirname "$0")/.."
set -a
source .env
set +a

send_alert() {
  local message="$1"
  if [[ -n "${TELEGRAM_BOT_TOKEN:-}" && -n "${TELEGRAM_CHAT_ID:-}" ]]; then
    curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
      -d chat_id="${TELEGRAM_CHAT_ID}" \
      -d text="⚠️ agent-os alert: ${message}" > /dev/null
  fi
  echo "[alert] ${message}"
}

check_endpoint() {
  local name="$1"
  local url="$2"
  if ! curl -sf --max-time 5 "$url" > /dev/null; then
    send_alert "${name} health check failed (${url})"
  fi
}

# Adjust hostnames/ports as your internal routing evolves.
check_endpoint "hermes" "http://localhost:8000/health"
check_endpoint "mcp" "http://localhost:8100/health"

# Memory pressure check
MEM_PCT=$(free | awk '/Mem:/ {printf "%.0f", $3/$2 * 100}')
if [[ "$MEM_PCT" -gt 90 ]]; then
  send_alert "host memory usage at ${MEM_PCT}% — check docker stats"
fi

# Any container restarting in a crash loop
RESTARTING=$(docker ps --filter "status=restarting" --format '{{.Names}}')
if [[ -n "$RESTARTING" ]]; then
  send_alert "container(s) stuck restarting: ${RESTARTING}"
fi
