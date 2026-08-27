# Security

## Boundaries enforced in code (not just convention)

- **Workspace escape prevention**: `agents/workspace.py:path_for()`
  resolves every path and rejects anything outside the agent's
  workspace root — a prompt-injected `../../etc/passwd` cannot escape.
- **Credential isolation**: `GITHUB_TOKEN`, `OPENROUTER_API_KEY`, R2
  keys are read only inside the MCP gateway / Hermes containers.
  Workers never receive raw credentials — they call the MCP gateway
  or Hermes's internal `/internal/route`, which hold the secrets.
- **No self-approval**: `services/approval/manager.py:resolve()`
  raises `PermissionError` if `approved_by` matches any agent_id
  passed in — this is a code check, not just a documented rule.
- **Policy-first execution**: every task passes through
  `PolicyEngine.evaluate()` in Hermes before being enqueued. DENY
  results never reach a worker.
- **Network segmentation**: Redis/Postgres are only on the `data` +
  `internal` networks — never `edge`. See docs/ARCHITECTURE.md.

## Not yet implemented (tracked, not hidden)

- Non-root container users
- Read-only root filesystems
- Automated secret rotation
- Terraform/IaC for Cloudflare config (currently manual dashboard setup)

## Secrets checklist before going live

- [ ] `HERMES_API_KEY` set to a real random value (unset = no auth, dev-only)
- [ ] `REDIS_PASSWORD` / `DATABASE_PASSWORD` are strong, unique, not reused
- [ ] `.env` is `chmod 600` on the VM
- [ ] GitHub secret scanning enabled on the repo
- [ ] SSH restricted to a known IP, key-only auth
- [ ] Cloudflare Access enabled on `n8n.yourdomain.com` and any admin UI
