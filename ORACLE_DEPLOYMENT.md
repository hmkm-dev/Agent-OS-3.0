# Oracle VPS Deployment

Target: Ubuntu 24.04, Docker, Docker Compose, Cloudflare Tunnel. Full
config reference: `infrastructure/oracle/README.md` (VM sizing, VCN,
security list) — this doc is the step-by-step flow through to a
running system.

## The 14-step process
1. **Create VPS** — Oracle Console → Compute → Instances → Create Instance (Ubuntu 24.04, `VM.Standard.A1.Flex`). See `infrastructure/oracle/README.md` for exact shape/VCN/security-list settings.
2. **SSH in**:
   ```bash
   ssh -i /path/to/your/key ubuntu@<oracle-instance-public-ip>
   ```
3. **Update system**:
   ```bash
   sudo apt-get update && sudo apt-get upgrade -y
   ```
4. **Install Docker + 5. Install Git** — automated by:
   ```bash
   curl -fsSL https://raw.githubusercontent.com/<you>/agent-os/main/infrastructure/oracle/bootstrap.sh | bash
   # log out and back in (docker group membership), then continue
   ```
   (`bootstrap.sh` also does swap + ufw firewall setup — see its own output for what it did.)
6. **Clone repository**:
   ```bash
   git clone <your-repo-url> && cd agent-os
   ```
7. **Create `.env`**:
   ```bash
   cp .env.example .env
   nano .env   # fill in REDIS_PASSWORD, HERMES_API_KEY, DATABASE_PASSWORD,
               # OPENROUTER_API_KEY at minimum — see docs/ENVIRONMENT.md
   ```
8. **Validate environment**:
   ```bash
   ./scripts/setup.sh   # fails loudly (exit 1) if a required var is missing
   ```
9. **Run migrations**:
   ```bash
   docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d postgres
   ./scripts/run_migrations.sh
   ```
10. **Start Docker Compose**:
    ```bash
    docker compose -f docker-compose.yml -f docker-compose.prod.yml build
    docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
    ```
11. **Run healthcheck**:
    ```bash
    HEALTHCHECK_MODE=production ./scripts/healthcheck.sh
    ```
12. **Configure Cloudflare Tunnel** — full steps in `docs/CLOUDFLARE_DEPLOYMENT.md`; summary: create the tunnel in the Zero Trust dashboard, copy the token into `.env` as `CF_TUNNEL_TOKEN`, add Public Hostnames pointing at `caddy:80`, then:
    ```bash
    docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d cloudflared
    ```
13. **Verify HTTPS**:
    ```bash
    ./scripts/verify_cloudflare_path.sh api.yourdomain.com
    ```
14. **Run smoke test** — the deterministic, credential-free check that the deployed stack is actually alive end-to-end:
    ```bash
    curl -sf https://api.yourdomain.com/health
    ```
    For a fuller check against your live stack (needs real API keys),
    see the E2E test commands in `docs/TESTING.md`.

(`./scripts/deploy.sh` automates steps 9–11 in one command if you
prefer, once step 8 has passed.)

## Reproducibility guarantees
- No fixed hostname/IP/Compose-project-name is assumed anywhere in
  `scripts/` — `healthcheck.sh`, `run_migrations.sh`, `backup.sh`, and
  `restore.sh` all use `docker compose exec <service>`, never a
  hard-coded container name like `agent-os-postgres-1`.
- `scripts/test_fresh_clone.sh` actually re-clones the repo into a temp
  directory and runs the full `setup.sh → deploy.sh → healthcheck.sh`
  sequence, as a repeatable reproducibility check.

## What was and wasn't verified
This document's commands are correct by inspection and were
individually syntax-checked. **They were not executed against a live
Oracle VM** — no Oracle account access exists in the environment that
generated this repo. Running `infrastructure/oracle/bootstrap.sh` on
your own fresh VM is the first real test of this flow.
