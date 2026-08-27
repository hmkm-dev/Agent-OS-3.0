# Cloudflare Deployment

Architecture (fixed, do not change): `Internet → Cloudflare → Cloudflare
Tunnel → Caddy → Hermes`. Hermes is never exposed directly to the
public internet. Full config reference: `infrastructure/cloudflare/README.md`
— this doc is the step-by-step walkthrough.

## 1. Create a Cloudflare account
cloudflare.com → sign up (free plan is sufficient for everything here).

## 2. Add your domain
Dashboard → Add a Site → enter your domain → follow the nameserver
change instructions at your registrar. Wait for "Active" status.

## 3. Create a tunnel
Zero Trust dashboard → Networks → Tunnels → **Create a tunnel** →
choose "Cloudflare-managed" → name it (e.g. `agent-os`).

## 4. Authenticate cloudflared
Not a separate manual step in Token mode (the mode this repo uses) —
the **Tunnel Token** shown after step 3 IS your authentication. Copy
it into `.env` as `CF_TUNNEL_TOKEN`. **Never commit this token.**

## 5. Configure the tunnel
Still in the tunnel creation wizard, add **Public Hostnames**:
- `api.yourdomain.com` → Service type `HTTP` → URL `caddy:80`
- `n8n.yourdomain.com` → Service type `HTTP` → URL `caddy:80` (once you deploy n8n)

These are internal Docker service names — Cloudflare reaches them
through the tunnel's private connection to your `cloudflared`
container, not over the public internet.

## 6. Configure DNS
Automatic — the tunnel wizard creates the (orange-cloud/proxied) CNAME
records for you when you add the Public Hostnames above. No manual DNS
step needed.

## 7. Configure Caddy
`infrastructure/caddy/Caddyfile` already routes `/hermes/*` → `hermes:8000`
and `/n8n/*` → `n8n:5678` under the shared `:80` internal listener.
No changes needed unless you're adding a new internal route.

## 8. Start services
```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d cloudflared caddy redis postgres hermes
```

## 9. Test the HTTPS endpoint
```bash
./scripts/verify_cloudflare_path.sh api.yourdomain.com
```
This makes a **real public HTTPS request** and reports pass/fail with
a specific checklist if it fails (DNS/Tunnel/Caddyfile/WAF). **This
script was written but not executed against a live domain in the
environment that generated this repo** — running it against your real
domain is the actual test, not this document.

## 10. Troubleshooting
| Symptom | Likely cause |
|---|---|
| `curl https://api.yourdomain.com/health` times out | DNS not proxied (grey-cloud instead of orange-cloud), or tunnel not running |
| 502/523 from Cloudflare | `cloudflared` container down, or Public Hostname points at the wrong internal service/port |
| 404 from Caddy | Caddyfile route doesn't match the path Cloudflare is forwarding |
| Works via `curl http://localhost:8000` but not through the domain | Confirms the issue is Cloudflare/Tunnel config, not Hermes itself — re-check steps 3–6 |

## WAF / rate limiting / Access
See `infrastructure/cloudflare/README.md` for the free-plan WAF ruleset,
rate-limiting rule setup, and Cloudflare Access configuration (gate
`n8n.yourdomain.com` only — never `api.yourdomain.com`, which needs
programmatic access via `HERMES_API_KEY`).
