#!/usr/bin/env bash
# Disaster recovery for a PostgreSQL backup created by scripts/backup.sh.
# Default mode is transactional import into the existing database. Exact
# database replacement requires RESTORE_MODE=replace plus the explicit
# RESTORE_ALLOW_DESTRUCTIVE=yes guard; this prevents accidental data loss.
set -euo pipefail

cd "$(dirname "$0")/.."
[ -f .env ] || { echo "[restore] .env not found" >&2; exit 1; }
set -a; source .env; set +a

COMPOSE=(docker compose -f docker-compose.yml)
BACKUP_DIR="${BACKUP_LOCAL_DIR:-/tmp/agent-os-backups}"
RESTORE_MODE="${RESTORE_MODE:-transactional}"
BACKUP_FILE="${BACKUP_FILE:-}"
TMP_DIR=$(mktemp -d "${TMPDIR:-/tmp}/agent-os-restore.XXXXXX")
cleanup() { rm -rf "$TMP_DIR"; }
trap cleanup EXIT
umask 077

case "$RESTORE_MODE" in
  transactional) ;;
  replace)
    [ "${RESTORE_ALLOW_DESTRUCTIVE:-no}" = "yes" ] || {
      echo "[restore] replace mode requires RESTORE_ALLOW_DESTRUCTIVE=yes" >&2
      exit 1
    }
    ;;
  *) echo "[restore] RESTORE_MODE must be transactional or replace" >&2; exit 1 ;;
esac

if [ -n "$BACKUP_FILE" ]; then
  case "$BACKUP_FILE" in
    /*) SOURCE_FILE="$BACKUP_FILE" ;;
    *) SOURCE_FILE="$BACKUP_DIR/$BACKUP_FILE" ;;
  esac
else
  if [ -n "${R2_ENDPOINT:-}" ] && [ -n "${R2_BUCKET_BACKUPS:-}" ]; then
    command -v aws >/dev/null 2>&1 || { echo "[restore] aws CLI is required for R2 downloads" >&2; exit 1; }
    echo "[restore] finding latest verified backup in R2..."
    LATEST=$(aws s3 ls "s3://${R2_BUCKET_BACKUPS}/" --endpoint-url "$R2_ENDPOINT" \
      | awk '$4 ~ /^pg-[0-9]{8}T[0-9]{6}Z[.]sql[.]gz$/ {print $4}' | sort | tail -n 1)
    [ -n "$LATEST" ] || { echo "[restore] no valid pg-*.sql.gz backups found in R2" >&2; exit 1; }
    SOURCE_FILE="$TMP_DIR/$LATEST"
    aws s3 cp "s3://${R2_BUCKET_BACKUPS}/${LATEST}" "$SOURCE_FILE" --endpoint-url "$R2_ENDPOINT"
    aws s3 cp "s3://${R2_BUCKET_BACKUPS}/${LATEST}.sha256" "$TMP_DIR/$LATEST.sha256" --endpoint-url "$R2_ENDPOINT"
  else
    SOURCE_FILE=$(find "$BACKUP_DIR" -maxdepth 1 -type f -name 'pg-*.sql.gz' -printf '%T@ %p\n' | sort -nr | head -n 1 | cut -d' ' -f2-)
    [ -n "$SOURCE_FILE" ] || { echo "[restore] no local backup found; set BACKUP_FILE or configure R2" >&2; exit 1; }
  fi
fi

[ -f "$SOURCE_FILE" ] || { echo "[restore] backup not found: $SOURCE_FILE" >&2; exit 1; }
CHECKSUM_FILE="${SOURCE_FILE}.sha256"
if [ ! -f "$CHECKSUM_FILE" ] && [ -n "${R2_ENDPOINT:-}" ] && [ -n "${R2_BUCKET_BACKUPS:-}" ] && [ -z "$BACKUP_FILE" ]; then
  CHECKSUM_FILE="$TMP_DIR/$(basename "$SOURCE_FILE").sha256"
fi
[ -f "$CHECKSUM_FILE" ] || { echo "[restore] checksum file not found for $SOURCE_FILE" >&2; exit 1; }
(cd "$(dirname "$SOURCE_FILE")" && sha256sum -c "$(basename "$CHECKSUM_FILE")")
gzip -t "$SOURCE_FILE"

if [ "$RESTORE_MODE" = "replace" ]; then
  echo "[restore] replacing agentos database after explicit destructive confirmation..."
  "${COMPOSE[@]}" exec -T postgres dropdb --if-exists -U postgres agentos
  "${COMPOSE[@]}" exec -T postgres createdb -U postgres agentos
fi

echo "[restore] waiting for postgres service..."
for i in $(seq 1 30); do
  if "${COMPOSE[@]}" exec -T postgres pg_isready -U postgres >/dev/null 2>&1; then break; fi
  [ "$i" -eq 30 ] && { echo "[restore] postgres did not become ready in time" >&2; exit 1; }
  sleep 2
done

echo "[restore] importing $(basename "$SOURCE_FILE") in $RESTORE_MODE mode..."
gunzip -c "$SOURCE_FILE" | "${COMPOSE[@]}" exec -T postgres psql -v ON_ERROR_STOP=1 --single-transaction -U postgres -d agentos >/dev/null

TABLE_COUNT=$("${COMPOSE[@]}" exec -T postgres psql -U postgres -d agentos -tAc \
  "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'")
TABLE_COUNT=$(printf '%s' "$TABLE_COUNT" | tr -d '[:space:]')
case "$TABLE_COUNT" in
  ''|*[!0-9]*) echo "[restore] invalid table-count verification: $TABLE_COUNT" >&2; exit 1 ;;
esac
[ "$TABLE_COUNT" -ge 1 ] || { echo "[restore] restore verification failed: zero public tables" >&2; exit 1; }
echo "[restore] verified: $TABLE_COUNT public tables present"
echo "[restore] done"
