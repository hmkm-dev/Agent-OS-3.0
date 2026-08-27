# Security

This document is the root-level security summary. The detailed control and
hardening record is in `docs/SECURITY.md`; deployment-specific checks are in
`docs/GITHUB_DEPLOYMENT_AUDIT.md` and `docs/ENVIRONMENT.md`.

## Reporting a vulnerability

This is currently a solo or small-scale project without a dedicated security
contact or bug bounty. If you find a vulnerability, use GitHub’s private
**Report a vulnerability** feature in this repository’s Security tab rather
than opening a public issue.

## Boundaries enforced in code

The following controls are intended to be code-enforced rather than merely
conventional:

- **Workspace escape prevention:** `agents/workspace.py:path_for()` resolves
  paths and rejects paths outside the agent workspace root.
- **Credential isolation:** provider and tool credentials are read by the MCP
  gateway or Hermes service; workers call those internal services rather than
  receiving raw credentials directly.
- **No agent self-approval:** `services/approval/manager.py:resolve()` rejects
  an approval when the approver is one of the agent IDs involved in the action.
- **Policy-first execution:** Hermes evaluates tasks through the policy engine
  before enqueueing them; denied work must not reach a worker.
- **Network segmentation:** Redis and PostgreSQL are attached to internal/data
  networks and are not exposed on the edge network.

These claims must remain aligned with the implementation and are subject to
local and live-stack verification; documentation alone is not evidence that a
control works in every deployment.

## Current hardening status

The package includes non-root container hardening for Hermes, MCP,
research-worker, and creative-worker. `opencode-worker` currently runs as root
because it needs write access to the shared workspace volume; this is a known
follow-up rather than a hidden assumption. Verify the effective user and
permissions for every additional worker profile before production use.

The following items are not fully hardened or have not been independently
verified:

- Read-only container root filesystems are not yet implemented globally.
- Automated secret rotation is not implemented; rotation is manual.
- Terraform or other full IaC for Cloudflare configuration is not included;
  account configuration remains a documented manual step.
- No penetration test has been performed. Treat the system as early-stage until
  it has real deployment hours and a separate security review.

## Secret handling and launch checklist

`.env` is gitignored and `.env.example` must contain placeholders only. Never
hardcode or commit API keys. Before going live:

- [ ] Set `HERMES_API_KEY` to a strong, random value; an unset value is
      development-only and must not be accepted in production.
- [ ] Use strong, unique `REDIS_PASSWORD` and `DATABASE_PASSWORD` values.
- [ ] Store `.env` with restrictive permissions such as `chmod 600`.
- [ ] Enable GitHub secret scanning and review its alerts.
- [ ] Restrict SSH to known IP ranges and key-only authentication.
- [ ] Put n8n and administrative interfaces behind Cloudflare Access or an
      equivalent access-control layer.
- [ ] Verify worker filesystem permissions and network reachability from the
      target deployment.
- [ ] Run the repository’s security and integration checks against a live-like
      environment before declaring production readiness.

See `docs/SECURITY.md` for the detailed pre-launch checklist and the explicit
list of known limitations.
