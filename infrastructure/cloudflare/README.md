# Cloudflare Deployment

Architecture decision (unchanged from earlier passes, re-confirmed
here): **Cloudflare Tunnel**, not direct origin exposure. The Oracle
instance never opens 443/80 to the public internet.

## Why Tunnel over direct origin
| | Direct origin | Tunnel (chosen) |
|---|---|---|
| Oracle public IP exposed | Yes | No |
| Inbound firewall rules needed | Yes (443, CF IP allowlist) | No |
| Setup | Nginx/Caddy + cert + firewall | `cloudflared` container + one token |

## Setup (dashboard steps — no CLI-only path exists for Tunnel Token mode)
1. **Cloudflare Zero Trust dashboard → Networks → Tunnels → Create a
   tunnel** → choose "Cloudflare-managed" → name it (e.g. `agent-os`).
2. Copy the **Tunnel Token** shown — this goes in `.env` as
   `CF_TUNNEL_TOKEN`. **Never commit this token.**
3. Still in the tunnel setup wizard, add **Public Hostnames**:
   - `api.yourdomain.com` → `HTTP` → `caddy:80` (internal Docker service name)
   - `n8n.yourdomain.com` → `HTTP` → `caddy:80` (once Phase 10 is deployed)
4. **DNS**: the tunnel wizard creates the CNAME records for you
   automatically (orange-cloud/proxied). No manual DNS entry needed.

## WAF / rate limiting (free plan)
Dashboard → Security → WAF:
- Enable the free Managed Ruleset.
- Security → Rate Limiting Rules → add a rule for `api.yourdomain.com/*`:
  e.g. 60 requests/minute per IP, block for 10 minutes on breach (exact
  numbers are a starting point — tune based on real traffic).
- Bot Fight Mode: on (free).

## Cloudflare Access (human-facing admin surfaces only)
Dashboard → Access → Applications → Add an application → Self-hosted:
- Application domain: `n8n.yourdomain.com`
- Policy: your email (one-time PIN) or GitHub SSO
- Do NOT put `api.yourdomain.com` behind Access — it's called by your
  Telegram bot / programmatic clients using `HERMES_API_KEY`, and
  Access expects an interactive login, which would break that.

## What's not automated here
There's no Cloudflare Terraform/API script in this repo for the same
honesty reason as Oracle (`infrastructure/oracle/README.md`) — it
can't be tested against a live account from this environment. The
`cloudflare` provider for Terraform (`cloudflare/cloudflare`) is the
real tool if you want to script this yourself later.
