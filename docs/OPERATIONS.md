# Operations

## Cron jobs to set up
```bash
crontab -e
# nightly Postgres -> R2 backup
0 3 * * * /home/ubuntu/agent-os/scripts/backup.sh >> /var/log/agentos-backup.log 2>&1
# health check + Telegram alert every 5 minutes
*/5 * * * * /home/ubuntu/agent-os/scripts/healthcheck-alert.sh
```

## Checking system state
```bash
docker compose ps                          # container status
docker stats --no-stream                   # live resource usage
curl http://localhost:8000/ready            # dependency health (redis+postgres)
docker compose exec redis redis-cli -a $REDIS_PASSWORD LLEN queue:failed   # dead-letter depth
```

## Restarting a stuck worker
```bash
docker compose restart opencode-worker
```
Workers handle SIGTERM gracefully (finish current task, then exit) —
`docker compose restart` will not corrupt in-flight task state; the
in-progress task is re-picked-up on next run via the idempotency
check in `base_worker.py`.

## Disaster recovery drill (do this once, before you need it)
```bash
# on a fresh instance:
git clone <repo> && cd agent-os
cp .env.example .env   # restore real values from your password manager
bash scripts/sync_shared.sh
docker compose up -d postgres && bash scripts/run_migrations.sh
bash scripts/restore.sh
docker compose up -d
```

## Resource budget
Every service has an explicit `deploy.resources.limits.memory` in
`docker-compose.yml`. Before adding a new always-on service, total the
limits and confirm you're under ~10.5GB (leaving ~1.5GB for the OS and
Docker daemon on the 12GB Oracle Always Free ceiling).
