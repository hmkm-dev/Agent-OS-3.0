#!/usr/bin/env bash
# Integration test: backup -> restore -> verify data survived.
# Requires a LIVE docker-compose stack with postgres running. NOT run
# in CI (needs live infra) and NOT executed in the environment that
# generated this repo (no Docker daemon there). Run it yourself:
#
#   bash tests/integration/test_backup_restore.sh
#
# WARNING: this test writes and then restores over your postgres
# database. Run it against a disposable/dev instance, not a database
# with data you care about, unless you've already confirmed
# scripts/backup.sh + scripts/restore.sh work correctly for you.
set -euo pipefail
cd "$(dirname "$0")/../.."
set -a; source .env; set +a

if [ -z "${R2_ENDPOINT:-}" ] || [ -z "${R2_BUCKET_BACKUPS:-}" ]; then
  echo "[test] SKIP: R2_ENDPOINT/R2_BUCKET_BACKUPS not configured — "
  echo "  scripts/backup.sh saves locally only without R2, and scripts/restore.sh "
  echo "  requires R2 to find the backup, so this specific round-trip test needs R2 configured."
  exit 0
fi

COMPOSE="docker compose -f docker-compose.yml"
MARKER_VALUE="backup-restore-test-$(date +%s)"

echo "[test] === Backup/Restore Integration Test ==="

echo "[test] ensuring postgres is up..."
$COMPOSE up -d postgres
for i in $(seq 1 30); do
  $COMPOSE exec -T postgres pg_isready -U postgres > /dev/null 2>&1 && break
  [ "$i" -eq 30 ] && { echo "[test] FAIL: postgres never became ready"; exit 1; }
  sleep 2
done

echo "[test] applying migrations (idempotent)..."
bash scripts/run_migrations.sh > /dev/null

echo "[test] inserting a marker row..."
$COMPOSE exec -T postgres psql -U postgres -d agentos -c \
  "INSERT INTO audit_logs (actor, action, resource, decision, detail) VALUES ('backup-restore-test', 'marker', '$MARKER_VALUE', 'allow', '{}');"

echo "[test] running scripts/backup.sh..."
bash scripts/backup.sh

echo "[test] deleting the marker row to simulate data loss..."
$COMPOSE exec -T postgres psql -U postgres -d agentos -c \
  "DELETE FROM audit_logs WHERE resource = '$MARKER_VALUE';"

REMAINING=$($COMPOSE exec -T postgres psql -U postgres -d agentos -tAc \
  "SELECT count(*) FROM audit_logs WHERE resource = '$MARKER_VALUE';")
if [ "$REMAINING" != "0" ]; then
  echo "[test] FAIL: marker row deletion didn't work, test setup is broken"
  exit 1
fi
echo "[test] confirmed marker is gone — proceeding to restore"

echo "[test] running scripts/restore.sh..."
RESTORE_MODE=replace RESTORE_ALLOW_DESTRUCTIVE=yes bash scripts/restore.sh

echo "[test] verifying marker row is back..."
RESTORED=$($COMPOSE exec -T postgres psql -U postgres -d agentos -tAc \
  "SELECT count(*) FROM audit_logs WHERE resource = '$MARKER_VALUE';")

if [ "$RESTORED" = "1" ]; then
  echo "[test] PASS: backup -> restore round-trip verified — marker row survived"
  exit 0
else
  echo "[test] FAIL: marker row did NOT come back after restore (found $RESTORED rows) — restore is broken"
  exit 1
fi
