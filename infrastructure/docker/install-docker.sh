#!/usr/bin/env bash
# Install Docker Engine, Buildx and the Compose plugin on Ubuntu/Debian.
# Uses Docker's official APT repository; intended for production VPS hosts.
set -euo pipefail

if [ "$(id -u)" -eq 0 ]; then SUDO=""; else SUDO="sudo"; fi
log(){ echo "[docker-install] $*"; }
fail(){ echo "[docker-install] ERROR: $*" >&2; exit 1; }

command -v apt-get >/dev/null 2>&1 || fail "apt-get is required."
command -v curl >/dev/null 2>&1 || { $SUDO apt-get update -y; $SUDO apt-get install -y ca-certificates curl; }
. /etc/os-release
case "${ID:-}" in ubuntu|debian) ;; *) fail "Unsupported OS: ${ID:-unknown}" ;; esac
ARCH="$(dpkg --print-architecture)"
CODENAME="${UBUNTU_CODENAME:-${VERSION_CODENAME:-}}"
[ -n "$CODENAME" ] || fail "Could not determine distribution codename."

$SUDO apt-get update -y
$SUDO apt-get install -y ca-certificates curl git gnupg
$SUDO apt-get remove -y docker.io docker-compose docker-compose-v2 docker-doc docker-buildx podman-docker containerd runc 2>/dev/null || true

$SUDO install -m 0755 -d /etc/apt/keyrings
$SUDO curl -fsSL "https://download.docker.com/linux/${ID}/gpg" -o /etc/apt/keyrings/docker.asc
$SUDO chmod a+r /etc/apt/keyrings/docker.asc
$SUDO tee /etc/apt/sources.list.d/docker.sources >/dev/null <<EOT
Types: deb
URIs: https://download.docker.com/linux/${ID}
Suites: ${CODENAME}
Components: stable
Architectures: ${ARCH}
Signed-By: /etc/apt/keyrings/docker.asc
EOT

$SUDO apt-get update -y
$SUDO apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

$SUDO systemctl enable docker.service containerd.service
$SUDO systemctl restart docker

# Add bounded daemon logging only when the host has no existing daemon config.
if [ ! -f /etc/docker/daemon.json ]; then
  $SUDO install -m 0644 /dev/null /etc/docker/daemon.json
  $SUDO tee /etc/docker/daemon.json >/dev/null <<'JSON'
{
  "log-driver": "json-file",
  "log-opts": {"max-size": "10m", "max-file": "3"},
  "live-restore": true
}
JSON
  $SUDO systemctl restart docker
fi

TARGET_USER="${SUDO_USER:-${USER:-}}"
$SUDO groupadd -f docker
if [ -n "$TARGET_USER" ] && id "$TARGET_USER" >/dev/null 2>&1; then
  $SUDO usermod -aG docker "$TARGET_USER"
fi

$SUDO systemctl is-active --quiet docker || fail "Docker daemon is not active. Check: sudo journalctl -u docker --no-pager -n 100"
$SUDO docker version >/dev/null
$SUDO docker compose version >/dev/null
$SUDO docker buildx version >/dev/null
$SUDO docker run --rm hello-world >/dev/null

log "Docker Engine, Buildx and Compose are installed and the daemon is active."
log "Log out/in or run 'newgrp docker' before using docker without sudo."
