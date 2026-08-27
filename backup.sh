#!/usr/bin/env bash
# Nightly backup: Postgres dump -> R2. Uses `docker compose exec`
# against the postgres SERVICE, not a hard-coded container name.
set -euo pipefail

cd "$(dirname "$0")/.."
set -a; source .env; set +a

COMPOSE="docker compose -f docker-compose.yml"
DATE=$(date +%F)
TMP_FILE="/tmp/pg-${DATE}.sql.gz"

echo "[backup] dumping postgres..."
$COMPOSE exec -T postgres pg_dump -U postgres agentos | gzip > "$TMP_FILE"

echo "[backup] uploading to R2..."
if [ -z "${R2_ENDPOINT:-}" ] || [ -z "${R2_BUCKET_BACKUPS:-}" ]; then
  echo "[backup] R2_ENDPOINT/R2_BUCKET_BACKUPS not configured — backup saved locally only at $TMP_FILE" >&2
  exit 0
fi
aws s3 cp "$TMP_FILE" "s3://${R2_BUCKET_BACKUPS}/" --endpoint-url "$R2_ENDPOINT"

echo "[backup] pruning local backups older than 7 days..."
find /tmp -name 'pg-*.sql.gz' -mtime +7 -delete

rm -f "$TMP_FILE"
echo "[backup] done: ${DATE}"
