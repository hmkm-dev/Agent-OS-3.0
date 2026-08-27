# Backup & Restore

## PostgreSQL
```bash
bash scripts/backup.sh     # pg_dump -> gzip -> R2 (via `docker compose exec postgres`, no hard-coded container name)
bash scripts/restore.sh    # latest R2 backup -> restore -> verifies table count > 0 after restore
```
Cron for nightly backups:
```bash
crontab -e
0 3 * * * /path/to/agent-os/scripts/backup.sh >> /var/log/agentos-backup.log 2>&1
```
**Retention:** `backup.sh` prunes local `/tmp` copies older than 7
days. R2-side retention (how long backups stay in the bucket) is not
automated — configure an R2 lifecycle rule in the Cloudflare dashboard
if you want automatic expiry there, or prune manually.

**Verification test:** `tests/integration/test_backup_restore.sh` —
inserts a real marker row, backs up, deletes the row, restores,
confirms the row is back. **Written and syntax-checked, not executed**
(needs a live Postgres + R2 — see docs/TESTING.md's honesty note on
this).

## Qdrant (separate strategy — do not conflate with Postgres backup)
Qdrant Cloud (the chosen deployment — see docs/ARCHITECTURE.md for
why not self-hosted) handles its own durability/replication as part
of its managed service. This repo does not implement a separate Qdrant
backup script. If you want an independent snapshot:
```bash
# Qdrant's own snapshot API (real endpoint, run manually or cron it yourself):
curl -X POST "${QDRANT_URL}/collections/${QDRANT_COLLECTION}/snapshots" \
  -H "api-key: ${QDRANT_API_KEY}"
# then download and store the snapshot file in R2 yourself if you want
# an out-of-band copy beyond what Qdrant Cloud already retains.
```
This is documented as a real, callable API — not wrapped in a script
in this repo, since most users will find Qdrant Cloud's own retention
sufficient and this is a genuine "nice to have," not a load-bearing
requirement the way Postgres backup is (Postgres holds policy/approval/
handoff state that has no other copy).

## Configuration/state backup
`scripts/backup.sh` covers Postgres only. Your `.env` and any manually
configured Cloudflare/n8n settings are NOT backed up by this repo —
keep `.env`'s real values in a password manager (never in Git), and
Cloudflare/n8n dashboard configuration is recreated from
`docs/CLOUDFLARE_DEPLOYMENT.md` / `n8n/workflows/` if lost.

## Disaster recovery drill (do this once, before you need it)
```bash
# On a second, disposable VM/instance:
git clone <repo> && cd agent-os
cp .env.example .env   # restore real values from your password manager
./scripts/setup.sh
docker compose up -d postgres && bash scripts/run_migrations.sh
bash scripts/restore.sh
docker compose up -d
./scripts/healthcheck.sh
```
This repo does not claim backups "work" until you've personally run
this drill — see `docs/OPERATIONS.md` for the same procedure in
context of the fuller operations runbook.
