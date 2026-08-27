# Deployment

See README.md for the full phase-by-phase order — this doc covers the
mechanics once you're ready to run each phase.

## Local dev
```bash
cp .env.example .env   # fill in at least REDIS_PASSWORD, HERMES_API_KEY
bash scripts/sync_shared.sh
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d cloudflared caddy redis hermes
curl http://localhost:8000/health
```

## Production (Oracle Always Free)
```bash
git clone <repo> && cd agent-os
cp .env.example .env && nano .env
bash scripts/sync_shared.sh
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d cloudflared caddy redis hermes
# then proceed through README's phase order, adding one service at a time
```

## Applying database migrations
```bash
docker compose up -d postgres
bash scripts/run_migrations.sh
```

## Enabling n8n (Phase 10+)
```bash
docker compose --profile phase10 up -d n8n
```

## Rollback
Compose services are stateless except for volumes (`redis-data`,
`pg-data`, `n8n-data`, `agent-workspaces`). To roll back a bad code
change: `git checkout <previous-commit> -- services/` then
`docker compose up -d --build <affected-service>`. Data volumes are
untouched by a code rollback.
