#!/usr/bin/env bash
# Real reproducibility test: clones THIS repo (from its local git
# history — works against any remote too if you pass one) into a
# clean temp directory and runs the exact documented fresh-clone flow.
# This is the closest thing to an automated version of docs/TESTING.md's
# "Fresh clone test" section.
#
# Usage:
#   ./scripts/test_fresh_clone.sh                  # clones local .git
#   ./scripts/test_fresh_clone.sh <remote-url>      # clones a remote
#
# Requires a real .env with real credentials to exist at
# ../agent-os/.env relative to this script (it copies YOUR .env into
# the fresh clone rather than making you re-enter credentials) —
# this is a test convenience, never do this for an actual deployment
# clone; a real deployment should always start from .env.example.
set -euo pipefail
cd "$(dirname "$0")/.."
SOURCE_DIR="$(pwd)"
REMOTE="${1:-$SOURCE_DIR}"

TEST_DIR="$(mktemp -d)/agent-os-freshclone-test"
echo "[fresh-clone-test] cloning into $TEST_DIR ..."
git clone "$REMOTE" "$TEST_DIR"
cd "$TEST_DIR"

if [ -f "$SOURCE_DIR/.env" ]; then
  echo "[fresh-clone-test] copying real .env from source repo for this test run"
  cp "$SOURCE_DIR/.env" .env
else
  echo "[fresh-clone-test] no .env in source repo — using .env.example (will fail setup.sh's required-var check, which is the correct behavior to verify)"
  cp .env.example .env
fi

echo "[fresh-clone-test] === Running ./scripts/setup.sh ==="
./scripts/setup.sh

echo "[fresh-clone-test] === Running ./scripts/deploy.sh ==="
./scripts/deploy.sh

echo "[fresh-clone-test] === Running ./scripts/healthcheck.sh ==="
./scripts/healthcheck.sh

echo "[fresh-clone-test] === Running unit tests ==="
python3 -m pytest tests/unit -v

echo "[fresh-clone-test] === SUCCESS ==="
echo "[fresh-clone-test] Test directory: $TEST_DIR"
echo "[fresh-clone-test] Tear down with: cd $TEST_DIR && docker compose down -v && cd / && rm -rf $TEST_DIR"
