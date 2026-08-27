# Contabo VPS Deployment

Same application, same architecture (Cloudflare → Tunnel → Caddy →
Hermes → Redis → Workers → MCP → Evaluator → Memory → R2 → n8n) — this
doc only covers what's Contabo-specific instead of Oracle-specific.
For everything after "system is bootstrapped," follow
`docs/DEPLOYMENT.md` / `docs/ENVIRONMENT.md` exactly as written for
Oracle; nothing in the application layer changes based on which VPS
provider you use.

No IP address or hostname is hard-coded anywhere below — substitute
your own throughout.

## Recommended minimum resources
Contabo's VPS plans aren't free-tier like Oracle Always Free, so pick
based on the same budget this repo was designed around:
- **Minimum**: 4 vCPU / 8GB RAM / 75GB+ NVMe (a Contabo "Cloud VPS 10"
  class or similar) — workable but tight once you add Postgres +
  Qdrant-adjacent workloads; expect to run fewer concurrent workers
  than the sizing guidance in `docs/ARCHITECTURE.md` assumes for a
  12GB box.
- **Recommended**: 6 vCPU / 16GB RAM — comfortable headroom for the
  full stack (Hermes + 3 workers + MCP + Playwright + Postgres +
  Redis + Caddy + cloudflared) simultaneously, matching or exceeding
  the Oracle Always Free reference point this repo targets.
- **Storage**: 75GB+ — Docker images, Postgres data, Playwright
  browser cache, and local backup staging in `/tmp` all need room;
  100GB+ is safer if you're not offloading backups to R2 promptly.

## 1. Ubuntu setup
Order a Contabo VPS with the **Ubuntu 24.04 LTS** image at signup —
this avoids a manual OS reinstall. Contabo emails you root credentials
(username + password, not a key by default).

## 2. SSH hardening
Contabo's default is password-based root SSH — harden this before
doing anything else:
```bash
ssh root@<your-contabo-ip>

# create a non-root sudo user
adduser deploy
usermod -aG sudo deploy

# copy your public key over (from your local machine, in a new terminal)
ssh-copy-id deploy@<your-contabo-ip>

# back on the VPS, as root: disable root login + password auth
sudo sed -i 's/^PermitRootLogin.*/PermitRootLogin no/' /etc/ssh/sshd_config
sudo sed -i 's/^PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
sudo systemctl restart sshd
```
From here on, SSH in as `deploy@<your-contabo-ip>`, not root.

## 3. Docker installation
Use the repository's provider-neutral Docker bootstrap. It installs Docker
Engine + Buildx + Compose from Docker's official APT repository, enables the
daemon, verifies it with `hello-world`, and does **not** change the Contabo
firewall or create Oracle-specific swap.
```bash
cd /path/to/agent-os
bash infrastructure/docker/bootstrap-ubuntu.sh
# log out/in, or run: newgrp docker
docker version
docker compose version
```

## 4. Git installation
```bash
sudo apt-get install -y git
```

## 5. Repository cloning
```bash
git clone <your-repo-url> && cd agent-os
```

## 6. Environment setup
```bash
cp .env.example .env
nano .env   # fill in REDIS_PASSWORD, HERMES_API_KEY, DATABASE_PASSWORD,
            # OPENROUTER_API_KEY at minimum — see docs/ENVIRONMENT.md
./scripts/setup.sh
```

## 7. Firewall
Contabo VPS instances are NOT behind a provider-managed security list
the way Oracle's VCN is — `ufw` on the box itself is your only layer
unless you also configure Contabo's optional Cloud Panel firewall.
```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow OpenSSH
sudo ufw enable
```
As with Oracle, **do not open 80/443** — Cloudflare Tunnel needs no
inbound rule, so the origin stays fully closed to the public internet.

## 8. Docker deployment
```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml build
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d postgres
./scripts/run_migrations.sh
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```
(or `./scripts/deploy.sh` once step 6 passes)

## 9. Cloudflare Tunnel
Identical to Oracle — see `docs/CLOUDFLARE_DEPLOYMENT.md`. The tunnel
doesn't care which VPS provider is on the other end; it connects
outbound from `cloudflared` regardless of host.

## 10. Healthcheck
```bash
HEALTHCHECK_MODE=production ./scripts/healthcheck.sh
./scripts/verify_cloudflare_path.sh api.yourdomain.com
```

## 11. Backup
```bash
crontab -e
0 3 * * * /path/to/agent-os/scripts/backup.sh >> /var/log/agentos-backup.log 2>&1
```
Same as Oracle — see `docs/BACKUP_RESTORE.md`, nothing Contabo-specific
here since backups go to R2, not provider-local storage.

## 12. Update procedure
```bash
./scripts/update.sh
```
Same script as Oracle — pulls, rebuilds, migrates, restarts,
health-checks, auto-rolls-back on failure.

## 13. Rollback procedure
```bash
./scripts/rollback.sh [<commit-sha>]
```
Same as Oracle.

## What's genuinely different from Oracle
- No Always Free RAM ceiling to work around — size your Contabo plan
  generously and you likely don't need the swap-file workaround
- No Oracle VCN/security-list equivalent — `ufw` on the box is your
  only network-layer firewall unless you configure Contabo's panel
- Root SSH access by default — hardening (step 2) is a Contabo-specific
  first step that Oracle's image doesn't require in the same way

## What was and wasn't verified
Written from Contabo's actual current provisioning flow (Ubuntu 24.04
image selection, default root/password SSH) and cross-checked against
this repo's existing Oracle instructions for anything that carries
over unchanged. **Not executed against a live Contabo VPS** — no
Contabo account access exists in the environment that generated this
repo, consistent with the same honest disclosure for Oracle.
