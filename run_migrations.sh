#!/usr/bin/env bash
# Applies all .sql files in migrations/ in order, against the running
# postgres SERVICE via `docker compose exec` — not a hard-coded
# container name. This is resilient to Compose project name changes
# (project name defaults to the directory name, e.g. cloning into
# "agent-os-2" instead of "agent-os" would break a hard-coded
# "agent-os-postgres-1" reference, but not this).
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; source .env; set +a

COMPOSE="docker compose -f docker-compose.yml"

for f in migrations/*.sql; do
  echo "[migrate] applying $f"
  $COMPOSE exec -T postgres psql -U postgres -d agentos < "$f"
done

echo "[migrate] done"
