# Deployment

This file is the quick-reference deployment index. Detailed platform-specific
instructions live in the linked documentation and must be reviewed before
running a production deployment.

## Local development

```bash
cp .env.example .env
nano .env                         # fill in required development values
./scripts/setup.sh --dev
bash scripts/sync_shared.sh
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d
./scripts/healthcheck.sh
```

For a minimal core stack, start `cloudflared`, `caddy`, `redis`, and `hermes`
explicitly. Add workers and tools as needed for the workflow being tested.

## Production: Oracle and Cloudflare

1. Prepare the VM using `docs/ORACLE_DEPLOYMENT.md`.
2. Configure the Cloudflare Tunnel, DNS, WAF, and access controls using
   `docs/CLOUDFLARE_DEPLOYMENT.md`.
3. Review required and optional environment variables in
   `docs/ENVIRONMENT.md` and create `.env` with secure permissions.
4. Synchronize shared build-context modules and deploy:

   ```bash
   ./scripts/setup.sh
   ./scripts/deploy.sh
   ./scripts/verify_cloudflare_path.sh api.yourdomain.com
   ```

5. Verify the result with `./scripts/healthcheck.sh`, then follow
   `docs/TESTING.md` for live-stack and end-to-end checks.

The deployment scripts build images, apply migrations, start services in
phases, wait for health checks, and report failures. They do not prove that a
live Oracle or Cloudflare environment is configured correctly until those
steps are actually run there.

## Applying database migrations

The production deploy path applies migrations automatically. To apply them
manually or inspect the migration behavior:

```bash
docker compose up -d postgres
bash scripts/run_migrations.sh
```

Do not edit or reorder an already-applied migration without following the
repository’s migration policy and taking a database backup first.

## Enabling n8n: Phase 10+

n8n is intentionally opt-in and is not started by the core deployment script:

```bash
docker compose --profile phase10 up -d n8n
```

The example workflow `skill_routine_trigger.json` calls Hermes through the
internal `POST /tasks` endpoint. See the n8n section in `README.md` for import,
credential, and webhook guidance.

## Updating

```bash
./scripts/update.sh
```

The update procedure pulls the selected revision, rebuilds, migrates, restarts,
health-checks, and rolls back to the previous commit if the post-update check
fails. Review its output rather than assuming that a successful container
start means every integration is healthy.

## Backup and restore

```bash
./scripts/backup.sh
bash scripts/restore.sh
```

For scheduled backups, use a host-level scheduler only after validating the
backup destination and restore procedure:

```cron
0 3 * * * /path/to/agent-os/scripts/backup.sh >> /var/log/agentos-backup.log 2>&1
```

See `docs/BACKUP_RESTORE.md` and `docs/OPERATIONS.md` for the disaster-recovery
drip procedure and retention guidance. Run a restore drill before relying on
backups in an incident.

## Rollback and data protection

Compose services are intended to be stateless except for persistent volumes
such as `redis-data`, `pg-data`, `n8n-data`, and `agent-workspaces`. To roll
back a code change, use the reviewed previous commit and rebuild only the
affected service, for example:

```bash
git checkout <previous-commit> -- services/
docker compose up -d --build <affected-service>
```

A code rollback must not delete or reset data volumes. Database restoration is
a separate, explicitly authorized operation described in
`docs/BACKUP_RESTORE.md`.

## Related documentation

- `docs/ARCHITECTURE.md` — system topology and service boundaries.
- `docs/ENVIRONMENT.md` — configuration reference.
- `docs/ORACLE_DEPLOYMENT.md` — VM preparation and production sequence.
- `docs/CLOUDFLARE_DEPLOYMENT.md` — Tunnel, DNS, WAF, and Access configuration.
- `docs/TESTING.md` — local, integration, and live-stack validation.
- `docs/TROUBLESHOOTING.md` — common operational failure modes.
- `docs/FINAL_AUDIT.md` and `docs/FINAL_REPOSITORY_STATUS.md` — evidence-backed
  verification status and known limitations.

## Honesty note

Every command above is intended to match the repository’s current structure
and is syntax-checked where applicable. Live Docker builds/runs, Oracle VM
configuration, Cloudflare account state, and external service credentials
must be verified in the target environment; this repository does not claim
those steps are complete merely because the files exist.
