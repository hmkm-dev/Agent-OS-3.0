# AI Agent OS

Modular multi-agent system: Hermes orchestrator (policy engine, approval
system, model router, evaluator, agent handoff, semantic memory) plus
OpenCode/Research/Creative workers and an MCP tool gateway, deployed on
Oracle Cloud Always Free behind Cloudflare.

**Before anything else, read `docs/IMPLEMENTATION_STATUS.md` and
`docs/GITHUB_DEPLOYMENT_AUDIT.md`.** They are the authoritative,
section-by-section statements of what is real, what is scaffolded, and what
still needs live credentials or deployment verification. This README documents
intended commands and supported configuration; it does not claim that live
infrastructure steps have been click-tested end to end.

## Features

- **Mission Control**: a goal-completion autonomous harness in which a high-level
  user goal becomes a persistent mission with a dependency-aware task graph,
  failure diagnosis, retry-with-strategy-change, claimed-versus-verified
  evidence, and mission-level success verification.
- Task orchestration with policy gating and human-approval workflow.
- Model routing through OpenRouter.
- OpenCode, Research, and Creative workers with shared retry, heartbeat,
  dead-letter, and timeout logic.
- Agent handoff chains such as Research → Creative → OpenCode.
- Qdrant-backed semantic-memory integration where configured.
- MCP tool gateway with per-worker allowlists for GitHub, search, filesystem,
  and isolated Playwright browser automation.
- Skill engine with teach-to-skill and skill-to-routine workflows, plus the
  `skills/` library for coding, research, SEO, marketing, DevOps, creative,
  Pinterest, and Instagram workflows.
- Cloudflare Tunnel edge deployment, backup/restore tooling, health checks,
  update tooling, and rollback tooling.

## Architecture

See `docs/ARCHITECTURE.md` for the full diagram and design tradeoffs,
including network segmentation, handoff, Mission Control, memory, and
service boundaries. The canonical-versus-copied module relationship is
specified in `scripts/sync_shared.sh`; edit canonical sources first and run
that script before building isolated service contexts.

## Requirements

- Docker with the Docker Compose v2 plugin.
- A domain you control for Cloudflare DNS and Tunnel configuration.
- As applicable: OpenRouter, Cloudflare, Qdrant Cloud, Brave Search, OpenAI
  embeddings, and GitHub accounts or tokens for enabled integrations.
- For production, an Oracle Cloud Always Free tenancy or a VPS with at least
  12 GB RAM and 2 vCPU.

## Quick Start

```bash
cp .env.example .env
nano .env                         # fill in required values
./scripts/setup.sh --dev
./scripts/healthcheck.sh
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d
```

For a minimal core stack, start only the required services:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d \
  cloudflared caddy redis hermes
```

The setup script validates prerequisites and synchronizes shared modules. See
`docs/DEVELOPMENT.md` for local workflows and `docs/ENVIRONMENT.md` for the
complete environment-variable reference.

## Configuration

Every environment variable used by the system is documented in
`.env.example`, grouped by component. Cloudflare Tunnel creation, DNS, and
WAF configuration are account-level steps documented under
`infrastructure/cloudflare/` and cannot be represented solely by environment
variables.

## Local Development and Testing

```bash
./scripts/setup.sh --dev
python3 -m pytest tests/unit -v
```

See `docs/DEVELOPMENT.md` for adding skills, MCP tools, and model providers,
and `docs/TESTING.md` for unit, integration, and live-stack verification
procedures. Tests requiring external services or credentials are not a
substitute for production-like testing.

## Oracle and Cloudflare Deployment

The deployment index is `DEPLOYMENT.md`. Full operational guidance is in
`docs/ORACLE_DEPLOYMENT.md`, `docs/CLOUDFLARE_DEPLOYMENT.md`, and
`docs/ENVIRONMENT.md`.

```bash
cp .env.example .env
nano .env
./scripts/setup.sh
./scripts/deploy.sh
./scripts/verify_cloudflare_path.sh api.yourdomain.com
./scripts/healthcheck.sh
```

The deploy script builds images, applies migrations, starts services in the
required order, and runs health checks. n8n remains opt-in through the
`phase10` Compose profile.

## Security

See `SECURITY.md` for the root-level security summary and reporting guidance,
and `docs/SECURITY.md` for the complete code-enforced controls, remaining
hardening work, and pre-launch checklist. Never commit secrets or API keys;
use `.env`, keep it out of version control, and configure real credentials
only in the deployment environment.

## Backup, Restore, Updating, and Rollback

```bash
./scripts/backup.sh
bash scripts/restore.sh
./scripts/update.sh
```

For scheduled backups, use a host-level scheduler such as:

```cron
0 3 * * * /path/to/agent-os/scripts/backup.sh >> /var/log/agentos-backup.log 2>&1
```

See `docs/OPERATIONS.md` and `docs/BACKUP_RESTORE.md` for disaster-recovery
drills. Code rollback must not be confused with data-volume rollback; review
those procedures before operating on a live system.

## n8n Workflow Quick Reference

`skill_routine_trigger.json` is a **minimal example**, not a production routine.
It demonstrates a schedule trigger calling Hermes’s `POST /tasks` endpoint with
an API-key header. It intentionally uses a single hardcoded task type in
`$json.taskType` rather than pretending to be a general routine engine.

To import it:

1. Open n8n after the Phase 10 profile has been deployed.
2. Choose **Workflows → Import from File** and select
   `skill_routine_trigger.json`.
3. Configure `HERMES_URL` (for example, `http://hermes:8000` on the internal
   Docker network) and `HERMES_API_KEY` using the same values as `.env`.
4. Edit the schedule and JSON body for the intended task, then activate the
   workflow.

The workflow does not require external credentials beyond those environment
variables because it calls Hermes over the internal Docker network. Routines
should call `POST /tasks` rather than workers or MCP directly so that policy,
evaluation, and approval controls remain in the execution path.

For an external webhook trigger, replace the Schedule Trigger with an n8n
Webhook node. Put the resulting webhook endpoint behind Cloudflare Access or
an equivalent shared-secret control because n8n webhook URLs are otherwise
unauthenticated by default.

## Project Structure

```text
.
├── README.md LICENSE CONTRIBUTING.md SECURITY.md CHANGELOG.md
├── .env.example .gitignore
├── docker-compose.yml docker-compose.dev.yml docker-compose.prod.yml
├── migrations/
├── infrastructure/{caddy,cloudflared,oracle,cloudflare}/
├── services/
│   ├── hermes/                    # orchestration API and control flow
│   ├── policy/ approval/ evaluator/ handoff/ memory/ runtime/ skill_engine/
│   ├── workers/{common,opencode,research,creative,rlm,browser,verification,seo,marketing,devops}/
│   ├── mcp/                       # tool gateway and integrations
│   └── playwright-service/         # isolated browser automation service
├── agents/{identity,workspace}.py
├── n8n/workflows/
├── memory/ skills/ tests/
└── scripts/
```

## Limitations and Verification Honesty

Feature names and documentation are not proof of live integration. Consult
`docs/IMPLEMENTATION_STATUS.md`, `docs/FINAL_AUDIT.md`, and
`docs/FINAL_REPOSITORY_STATUS.md` for the evidence-backed implementation
status, required external credentials, and tests that still require a live
stack. Do not label a feature production-tested unless it was tested in a
production-like environment.

## Contributing and License

See `CONTRIBUTING.md`. This project is MIT-licensed; see `LICENSE`.
