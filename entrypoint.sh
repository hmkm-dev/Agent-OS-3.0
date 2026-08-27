#!/bin/sh
# Renders ~/.config/opencode/opencode.json from OPENROUTER_API_KEY before
# starting the worker.
#
# Config verified against current official OpenCode 1.x documentation
# (opencode.ai/docs/config/, opencode.ai/docs/providers — checked Aug
# 2026):
#   - "openrouter" is OpenCode's built-in provider ID for OpenRouter.
#     It is NOT the npm package "@openrouter/ai-sdk-provider" — that
#     was wrong in a prior version of this file and has been corrected.
#   - {env:VARIABLE_NAME} interpolation is officially supported inside
#     opencode.json and is used here for apiKey instead of writing the
#     raw secret into the file — OpenCode resolves it from the
#     container's own process environment at startup (OPENROUTER_API_KEY
#     is already passed in via docker-compose.yml's `env_file: .env`
#     on the opencode-worker service, so this is guaranteed to be set
#     whenever OPENROUTER_API_KEY itself is).
#   - OPENCODE_MODEL support is unchanged by this fix — model selection
#     is still handled via the `--model` CLI flag in
#     services/runtime/agent_runtime.py, not through this config file.
set -e

CONFIG_DIR="$HOME/.config/opencode"
mkdir -p "$CONFIG_DIR"

if [ -n "$OPENROUTER_API_KEY" ]; then
  cat > "$CONFIG_DIR/opencode.json" << 'EOF'
{
  "$schema": "https://opencode.ai/config.json",
  "provider": {
    "openrouter": {
      "options": {
        "apiKey": "{env:OPENROUTER_API_KEY}"
      }
    }
  }
}
EOF
  # Note: the heredoc above is intentionally unquoted-free of shell
  # variable expansion ('EOF' is quoted) — {env:OPENROUTER_API_KEY} is
  # literal text that OpenCode itself interpolates at startup, NOT a
  # shell variable. This is what keeps the actual key value out of the
  # file entirely; only the literal placeholder string is written.
else
  echo "[entrypoint] WARNING: OPENROUTER_API_KEY not set — opencode.json not written." \
       "OpenCode will fail auth until you set OPENROUTER_API_KEY in .env." >&2
fi

exec "$@"
