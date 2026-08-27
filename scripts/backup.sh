#!/usr/bin/env bash
# Nightly backup: Postgres dump -> verified gzip/checksum -> optional R2.
# The script never deletes repository data; local pruning only removes backup
# artifacts older than BACKUP_RETENTION_DAYS.
set -euo pipefail

cd "$(dirname "$0")/.."
[ -f .env ] || { echo "[backup] .env not found" >&2; exit 1; }
set -a; source .env; set +a

COMPOSE=(docker compose -f docker-compose.yml)
BACKUP_DIR="${BACKUP_LOCAL_DIR:-/tmp/agent-os-backups}"
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-7}"
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
BASENAME="pg-${STAMP}.sql.gz"
TMP_DIR=$(mktemp -d "${BACKUP_DIR}.tmp.XXXXXX")
OUT="$BACKUP_DIR/$BASENAME"
CHECKSUM="$OUT.sha256"

cleanup() { rm -rf "$TMP_DIR"; }
trap cleanup EXIT
mkdir -p "$BACKUP_DIR"
umask 077

case "$RETENTION_DAYS" in
  ''|*[!0-9]*) echo "[backup] BACKUP_RETENTION_DAYS must be a non-negative integer" >&2; exit 1 ;;
esac
command -v gzip >/dev/null 2>&1 || { echo "[backup] gzip is required" >&2; exit 1; }
command -v sha256sum >/dev/null 2>&1 || { echo "[backup] sha256sum is required" >&2; exit 1; }

TMP_BACKUP="$TMP_DIR/$BASENAME"
echo "[backup] dumping postgres to $OUT..."
"${COMPOSE[@]}" exec -T postgres pg_dump --no-owner --no-privileges -U postgres agentos | gzip -n > "$TMP_BACKUP"
gzip -t "$TMP_BACKUP"
sha256sum "$TMP_BACKUP" | sed "s#${TMP_BACKUP}#${BASENAME}#" > "$TMP_DIR/$BASENAME.sha256"

mv "$TMP_BACKUP" "$OUT"
mv "$TMP_DIR/$BASENAME.sha256" "$CHECKSUM"
(cd "$BACKUP_DIR" && sha256sum -c "$(basename "$CHECKSUM")")

if [ -z "${R2_ENDPOINT:-}" ] || [ -z "${R2_BUCKET_BACKUPS:-}" ]; then
  echo "[backup] R2_ENDPOINT/R2_BUCKET_BACKUPS not configured; verified local backup retained at $OUT"
else
  command -v aws >/dev/null 2>&1 || { echo "[backup] aws CLI is required for R2 upload" >&2; exit 1; }
  echo "[backup] uploading verified backup and checksum to R2..."
  aws s3 cp "$OUT" "s3://${R2_BUCKET_BACKUPS}/${BASENAME}" --endpoint-url "$R2_ENDPOINT"
  aws s3 cp "$CHECKSUM" "s3://${R2_BUCKET_BACKUPS}/${BASENAME}.sha256" --endpoint-url "$R2_ENDPOINT"
  echo "[backup] R2 upload complete"
fi

find "$BACKUP_DIR" -maxdepth 1 -type f \( -name 'pg-*.sql.gz' -o -name 'pg-*.sql.gz.sha256' \) -mtime "+$RETENTION_DAYS" -delete
echo "[backup] verified backup complete: $BASENAME"
