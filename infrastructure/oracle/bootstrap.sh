#!/usr/bin/env bash
# One-time host bootstrap for a fresh Oracle Cloud Ubuntu VPS.
# Adds the Oracle-specific swap/firewall preparation, then delegates Docker
# installation to the shared production installer.
set -euo pipefail

if [ "$(id -u)" -eq 0 ]; then SUDO=""; else SUDO="sudo"; fi
log(){ echo "[bootstrap] $*"; }
fail(){ echo "[bootstrap] ERROR: $*" >&2; exit 1; }

command -v apt-get >/dev/null 2>&1 || fail "apt-get is required."
command -v curl >/dev/null 2>&1 || { $SUDO apt-get update -y; $SUDO apt-get install -y ca-certificates curl; }
. /etc/os-release
[ "${ID:-}" = "ubuntu" ] || fail "Oracle bootstrap targets Ubuntu. Use infrastructure/docker/bootstrap-ubuntu.sh for a generic Ubuntu/Debian VPS."

log "=== Oracle swap ==="
SWAP_SIZE_GB="${AGENT_OS_SWAP_GB:-8}"
if [ ! -f /swapfile ]; then
  $SUDO fallocate -l "${SWAP_SIZE_GB}G" /swapfile
  $SUDO chmod 600 /swapfile
  $SUDO mkswap /swapfile >/dev/null
  $SUDO swapon /swapfile
  grep -q '^/swapfile ' /etc/fstab || echo '/swapfile none swap sw 0 0' | $SUDO tee -a /etc/fstab >/dev/null
  log "OK: ${SWAP_SIZE_GB}GB swap enabled"
else
  log "OK: /swapfile already exists; preserving it"
fi

log "=== Oracle firewall ==="
if command -v ufw >/dev/null 2>&1; then
  $SUDO ufw --force default deny incoming
  $SUDO ufw --force default allow outgoing
  $SUDO ufw --force allow OpenSSH
  $SUDO ufw --force enable
  log "OK: UFW enabled; SSH only inbound (Cloudflare Tunnel needs no public 80/443)"
fi

log "=== Docker Engine + Buildx + Compose ==="
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
bash "$SCRIPT_DIR/../docker/install-docker.sh"

log "=== Oracle host bootstrap complete ==="
log "Log out/in or run 'newgrp docker' before using docker without sudo."
log "Then clone the repo, create .env, run ./scripts/setup.sh, and ./scripts/deploy.sh."
