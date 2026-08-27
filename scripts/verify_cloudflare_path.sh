#!/usr/bin/env bash
# Verifies the full public path: Internet -> Cloudflare -> Tunnel ->
# Caddy -> Hermes actually works, not just that each hop is
# individually configured. Run this AFTER deploying to Oracle with a
# real domain and a live Cloudflare Tunnel — it makes a real public
# HTTPS request, it does not just check local container status.
#
# Usage: ./scripts/verify_cloudflare_path.sh api.yourdomain.com
set -euo pipefail
cd "$(dirname "$0")/.."

DOMAIN="${1:-}"
if [ -z "$DOMAIN" ]; then
  echo "Usage: $0 <your-api-domain>  (e.g. api.yourdomain.com)"
  exit 1
fi

COMPOSE="docker compose -f docker-compose.yml"

echo "[verify] === Step 1: local cloudflared container is running ==="
if $COMPOSE ps --services --filter status=running | grep -qx cloudflared; then
  echo "[verify] OK: cloudflared container running"
else
  echo "[verify] FAIL: cloudflared container is not running — check 'docker compose logs cloudflared'"
  exit 1
fi

echo "[verify] === Step 2: local Hermes is healthy (internal, pre-tunnel check) ==="
if $COMPOSE exec -T hermes curl -fsS --max-time 5 http://localhost:8000/health > /dev/null 2>&1; then
  echo "[verify] OK: Hermes healthy on the internal network"
else
  echo "[verify] FAIL: Hermes not healthy locally — fix this before testing the public path, "
  echo "  since a failure through Cloudflare could just be this, not a Cloudflare config issue"
  exit 1
fi

echo "[verify] === Step 3: full public path through Cloudflare ==="
HTTP_CODE=$(curl -sf -o /tmp/cf_verify_response.json -w "%{http_code}" \
  --max-time 15 "https://${DOMAIN}/health" 2>&1) || HTTP_CODE="curl_failed"

if [ "$HTTP_CODE" = "200" ]; then
  echo "[verify] OK: https://${DOMAIN}/health returned 200"
  echo "[verify] response body:"
  cat /tmp/cf_verify_response.json
  rm -f /tmp/cf_verify_response.json
else
  echo "[verify] FAIL: https://${DOMAIN}/health did not return 200 (got: $HTTP_CODE)"
  echo "[verify] Checklist if this fails:"
  echo "  - DNS: is ${DOMAIN} showing an orange-cloud (proxied) CNAME in Cloudflare DNS?"
  echo "  - Tunnel: does the tunnel's Public Hostname config route ${DOMAIN} -> caddy:80 (or hermes:8000)?"
  echo "  - Caddyfile: does infrastructure/caddy/Caddyfile actually route /health to hermes:8000?"
  echo "  - WAF/rate limiting: is a WAF rule blocking this request? Check Cloudflare Security Events."
  exit 1
fi

echo "[verify] === Step 4: confirm origin is NOT directly reachable (Tunnel is doing its job) ==="
echo "[verify] This step is informational only — it can't be fully automated without your Oracle "
echo "  instance's public IP. Manually confirm: 'curl --max-time 5 http://<oracle-ip>/health' times "
echo "  out or refuses (no direct route), proving the origin has no public listening port."

echo "[verify] === Done — Cloudflare Tunnel -> Caddy -> Hermes path verified ==="
