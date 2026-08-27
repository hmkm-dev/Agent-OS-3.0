# Environment Variables

Full source of truth: `.env.example` (every variable the system reads
is there, grouped by component). This doc adds the REQUIRED/OPTIONAL
split and what breaks if each is missing.

## REQUIRED — setup.sh exits 1 without these (production mode)
| Variable | Used for | If missing |
|---|---|---|
| `HERMES_API_KEY` | Authenticates all `/tasks`, `/agents`, `/approvals` calls | Hermes accepts unauthenticated requests (dev-only behavior) |
| `REDIS_PASSWORD` | Redis auth, task queues | Nothing works — Redis is the task backbone |
| `DATABASE_URL` (or `DATABASE_PASSWORD`, auto-assembled) | Postgres — policy/approval/handoff/memory persistence | Everything beyond basic task queueing fails |
| `OPENROUTER_API_KEY` | Model routing — every worker's text generation | All 3 workers fail immediately on any real task |

If you're using Qdrant Cloud, R2, or a Cloudflare Tunnel deployment,
these become required too (see Phase 4 of the original request this
doc responds to):
| Variable | Required when |
|---|---|
| `QDRANT_URL`, `QDRANT_API_KEY`, `EMBEDDING_API_KEY` | Any semantic memory feature is used |
| `R2_ENDPOINT`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY` | Creative worker artifacts, backups |
| `CF_TUNNEL_TOKEN` | Cloudflare Tunnel deployment (production) |

## OPTIONAL — feature-scoped, warn-only in setup.sh
| Variable | Feature | Behavior if unset |
|---|---|---|
| `BRAVE_SEARCH_API_KEY` | Search MCP tool | Research worker's search calls raise a clear 503, don't fake results |
| `GITHUB_TOKEN` | GitHub MCP tool | GitHub tool calls raise a clear error |
| `N8N_ENCRYPTION_KEY`, `N8N_HOST` | n8n automation | n8n stays undeployed (behind the `phase10` Compose profile) — n8n is intentionally optional for local development |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | Approval/alert notifications | Approvals still work, just without a Telegram ping |
| `PLAYWRIGHT_TIMEOUT_MS`, `OPENCODE_MODEL`, `AGENT_RUNTIME`, `MAX_RETRIES`, `WORKSPACE_ROOT`, internal `*_URL` overrides | Tuning/internal wiring | Sane defaults matching the Docker internal network |

## Validation
```bash
./scripts/setup.sh          # strict — exits 1 on missing REQUIRED vars, never prints their values
./scripts/setup.sh --dev    # lenient — warns only, for local iteration without every key yet
```
`setup.sh` never echoes a secret's actual value — only whether it's
set/unset/still-a-placeholder. Verified by inspection (`grep '$val'
scripts/setup.sh` shows only comparisons, never a print of the value).

## Never commit
`.env` is gitignored. `.env.example` contains only placeholders —
verified via a repo-wide secret scan (regex for `sk-`, `ghp_`, `AKIA`,
PEM headers) in `docs/GITHUB_DEPLOYMENT_AUDIT.md`, and CI runs
`gitleaks-action` on every push as a standing check.
