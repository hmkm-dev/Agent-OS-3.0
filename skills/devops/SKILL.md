# Skill: DevOps

**Status: PARTIALLY IMPLEMENTED** — this repo's OWN deployment tooling (`scripts/deploy.sh`, `scripts/healthcheck.sh`, Docker Compose) is real and can be invoked by OpenCode as shell commands (policy category `EXECUTE_COMMAND` / `DEPLOYMENT`, both `REQUIRE_APPROVAL` by default — see `services/policy/rules.yaml`). No separate DevOps worker or Terraform/cloud-provider API integration exists.

## Purpose
Deployment, infrastructure changes, container/service management as OpenCode-executed shell commands, gated by policy.

## Inputs
- `instructions` describing the infra task (same shape as the coding skill — this is OpenCode running commands, not a separate execution engine)

## Outputs
Same as the coding skill: exit code, stdout/stderr, files changed (e.g. modified compose/config files)

## Allowed tools
`filesystem`, `github` — same as coding, since this IS OpenCode, not a new worker

## What's an integration point (not built, not faked)
- Direct cloud provider API calls (Oracle OCI SDK, Terraform providers) — not wired in; OpenCode can shell out to `oci` CLI or `terraform` if those binaries are installed in its container (they currently are NOT — would need adding to `services/workers/opencode/Dockerfile` if you want this, following the same real-install-and-verify pattern used for the OpenCode CLI itself).

## Success criteria / verification
- `deployment_health_check`, `container_health`, `http_health_check` evidence kinds exist specifically for this skill — verification means actually calling `scripts/healthcheck.sh` or curling a real endpoint and recording the real exit code/HTTP status, not trusting a "deployment successful" claim.

## Failure handling
DEPLOY-class actions are `REQUIRE_APPROVAL` (spec §12's risk tiers) — a DevOps mission task cannot auto-approve its own production deployment step.
