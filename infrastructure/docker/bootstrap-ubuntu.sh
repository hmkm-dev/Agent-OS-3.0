#!/usr/bin/env bash
# Generic Ubuntu/Debian VPS bootstrap for Agent OS (Contabo and similar VPSs).
# Unlike the Oracle bootstrap, this does not create swap or change the firewall.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec bash "$SCRIPT_DIR/install-docker.sh" "$@"
