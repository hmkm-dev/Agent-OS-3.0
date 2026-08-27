#!/usr/bin/env bash
# Verify a local or R2 backup without modifying PostgreSQL.
set -euo pipefail

cd "$(dirname "$0")/.."
[ -f .env ] || { echo "[verify-backup] .env not found" >&2; exit 1; }
set -a; source .env; set +a

BACKUP_DIR="${BACKUP_LOCAL_DIR:-/tmp/agent-os-backups}"
BACKUP_FILE="${BACKUP_FILE:-}"
MAX_AGE_HOURS="${BACKUP_MAX_AGE_HOURS:-36}"

case "$MAX_AGE_HOURS" in ''|*[!0-9]*) echo "[verify-backup] BACKUP_MAX_AGE_HOURS must be an integer" >&2; exit 1 ;; esac

if [ -z "$BACKUP_FILE" ]; then
  BACKUP_FILE=$(find "$BACKUP_DIR" -maxdepth 1 -type f -name 'pg-*.sql.gz' -printf '%T@ %p\n' 2>/dev/null | sort -nr | head -n 1 | cut -d' ' -f2-)
fi

if [ -n "$BACKUP_FILE" ] && [ -f "$BACKUP_FILE" ]; then
  SOURCE="$BACKUP_FILE"
else
  if [ -z "${R2_ENDPOINT:-}" ] || [ -z "${R2_BUCKET_BACKUPS:-}" ]; then
    echo "[verify-backup] no local backup and R2 is not configured" >&2
    exit 1
  fi
  command -v aws >/dev/null 2>&1 || { echo "[verify-backup] aws CLI is required for R2 verification" >&2; exit 1; }
  LATEST=$(aws s3 ls "s3://${R2_BUCKET_BACKUPS}/" --endpoint-url "$R2_ENDPOINT" \
    | awk '$4 ~ /^pg-[0-9]{8}T[0-9]{6}Z[.]sql[.]gz$/ {print $4}' | sort | tail -n 1)
  [ -n "$LATEST" ] || { echo "[verify-backup] no valid R2 backup found" >&2; exit 1; }
  SOURCE="${BACKUP_DIR}/${LATEST}"
  mkdir -p "$BACKUP_DIR"
  aws s3 cp "s3://${R2_BUCKET_BACKUPS}/${LATEST}" "$SOURCE" --endpoint-url "$R2_ENDPOINT"
  aws s3 cp "s3://${R2_BUCKET_BACKUPS}/${LATEST}.sha256" "${SOURCE}.sha256" --endpoint-url "$R2_ENDPOINT"
fi

[ -f "$SOURCE" ] || { echo "[verify-backup] backup not found: $SOURCE" >&2; exit 1; }
[ -f "${SOURCE}.sha256" ] || { echo "[verify-backup] checksum not found: ${SOURCE}.sha256" >&2; exit 1; }
(cd "$(dirname "$SOURCE")" && sha256sum -c "$(basename "${SOURCE}.sha256")")
gzip -t "$SOURCE"

if [ "$MAX_AGE_HOURS" -gt 0 ]; then
  NOW=$(date +%s)
  MTIME=$(stat -c %Y "$SOURCE")
  AGE=$(( (NOW - MTIME) / 3600 ))
  [ "$AGE" -le "$MAX_AGE_HOURS" ] || { echo "[verify-backup] backup is ${AGE}h old; limit is ${MAX_AGE_HOURS}h" >&2; exit 1; }
fi

echo "[verify-backup] PASS: $(basename "$SOURCE") is a valid, checksum-verified backup"
