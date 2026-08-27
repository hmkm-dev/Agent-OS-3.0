#!/usr/bin/env bash
# Disaster recovery: pulls the latest Postgres backup from R2 and
# restores it. Uses `docker compose exec`/service name, not a
# hard-coded container name.
set -euo pipefail

cd "$(dirname "$0")/.."
set -a; source .env; set +a

COMPOSE="docker compose -f docker-compose.yml"

echo "[restore] finding latest backup in R2..."
LATEST=$(aws s3 ls "s3://${R2_BUCKET_BACKUPS}/" --endpoint-url "$R2_ENDPOINT" \
  | sort | tail -n 1 | awk '{print $4}')

if [ -z "$LATEST" ]; then
  echo "[restore] no backups found in s3://${R2_BUCKET_BACKUPS}/"
  exit 1
fi

echo "[restore] downloading ${LATEST}..."
aws s3 cp "s3://${R2_BUCKET_BACKUPS}/${LATEST}" "/tmp/${LATEST}" --endpoint-url "$R2_ENDPOINT"

echo "[restore] waiting for postgres service to be ready..."
for i in $(seq 1 30); do
  if $COMPOSE exec -T postgres pg_isready -U postgres > /dev/null 2>&1; then
    break
  fi
  [ "$i" -eq 30 ] && { echo "[restore] postgres did not become ready in time"; exit 1; }
  sleep 2
done

echo "[restore] restoring into agentos database..."
gunzip -c "/tmp/${LATEST}" | $COMPOSE exec -T postgres psql -U postgres -d agentos

echo "[restore] verifying restore..."
TABLE_COUNT=$($COMPOSE exec -T postgres psql -U postgres -d agentos -tAc \
  "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'")
echo "[restore] $TABLE_COUNT tables present after restore"
if [ "$TABLE_COUNT" -lt 1 ]; then
  echo "[restore] WARNING: restore produced zero tables — something is wrong, do not trust this restore" >&2
  exit 1
fi
echo "[restore] done."
