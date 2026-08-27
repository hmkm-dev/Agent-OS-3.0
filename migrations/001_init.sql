-- agent-os initial schema
-- Apply with: scripts/run_migrations.sh
-- Idempotent: safe to re-run (CREATE TABLE IF NOT EXISTS everywhere)

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ── Agents ────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS agents (
    agent_id      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name          TEXT NOT NULL,
    role          TEXT NOT NULL,              -- opencode | research | creative | hermes
    profile       JSONB DEFAULT '{}',
    preferences   JSONB DEFAULT '{}',
    capabilities  JSONB DEFAULT '[]',
    constraints   JSONB DEFAULT '{}',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── Sessions ──────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS sessions (
    session_id    UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    agent_id      UUID REFERENCES agents(agent_id),
    started_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    ended_at      TIMESTAMPTZ,
    status        TEXT NOT NULL DEFAULT 'active',   -- active | completed | aborted
    metadata      JSONB DEFAULT '{}'
);

-- ── Tasks ─────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS tasks (
    task_id        UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    parent_task_id UUID REFERENCES tasks(task_id),
    session_id     UUID REFERENCES sessions(session_id),
    agent_id       UUID REFERENCES agents(agent_id),
    type           TEXT NOT NULL,              -- opencode | research | creative
    priority       INT NOT NULL DEFAULT 5,
    payload        JSONB NOT NULL,
    status         TEXT NOT NULL DEFAULT 'queued',  -- queued|running|completed|failed|cancelled|awaiting_approval
    result         JSONB,
    error          TEXT,
    retry_count    INT NOT NULL DEFAULT 0,
    deadline       TIMESTAMPTZ,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at     TIMESTAMPTZ,
    completed_at   TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_session ON tasks(session_id);

-- ── Task events (audit trail per task) ───────────────────────
CREATE TABLE IF NOT EXISTS task_events (
    event_id     UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    task_id      UUID REFERENCES tasks(task_id),
    event_type   TEXT NOT NULL,   -- created|queued|started|retried|failed|completed|handoff|evaluated
    detail       JSONB DEFAULT '{}',
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_task_events_task ON task_events(task_id);

-- ── Workers (heartbeat/registry) ─────────────────────────────
CREATE TABLE IF NOT EXISTS workers (
    worker_id     TEXT PRIMARY KEY,       -- hostname:pid or container id
    worker_type   TEXT NOT NULL,          -- opencode|research|creative
    status        TEXT NOT NULL DEFAULT 'online',  -- online|offline|crashed
    last_heartbeat TIMESTAMPTZ NOT NULL DEFAULT now(),
    metadata      JSONB DEFAULT '{}'
);

-- ── Skills ────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS skills (
    skill_id     UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name         TEXT NOT NULL,
    description  TEXT,
    required_tools JSONB DEFAULT '[]',
    inputs       JSONB DEFAULT '{}',
    outputs      JSONB DEFAULT '{}',
    constraints  JSONB DEFAULT '{}',
    status       TEXT NOT NULL DEFAULT 'draft',  -- draft|tested|approved|deprecated
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS skill_versions (
    skill_version_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    skill_id      UUID REFERENCES skills(skill_id),
    version       INT NOT NULL,
    instructions  TEXT NOT NULL,
    examples      JSONB DEFAULT '[]',
    tests         JSONB DEFAULT '[]',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(skill_id, version)
);

-- ── Routines (skill -> schedule -> n8n) ─────────────────────
CREATE TABLE IF NOT EXISTS routines (
    routine_id    UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    skill_id      UUID REFERENCES skills(skill_id),
    schedule      TEXT NOT NULL,     -- cron expression
    parameters    JSONB DEFAULT '{}',
    enabled       BOOLEAN NOT NULL DEFAULT false,
    last_run      TIMESTAMPTZ,
    next_run      TIMESTAMPTZ,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── Approvals ─────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS approvals (
    approval_id   UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    task_id       UUID REFERENCES tasks(task_id),
    agent_id      UUID REFERENCES agents(agent_id),
    action        TEXT NOT NULL,
    reason        TEXT,
    requested_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    status        TEXT NOT NULL DEFAULT 'pending',  -- pending|approved|denied|expired
    approved_by   TEXT,
    approved_at   TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_approvals_status ON approvals(status);

-- ── Handoffs ──────────────────────────────────────────────────
-- NOTE: task_id below is intentionally NOT a foreign key into `tasks`.
-- Live task state is authoritative in Redis (see services/hermes/app.py)
-- until Phase 6 work to make Postgres the task system-of-record is done
-- (see docs/IMPLEMENTATION_STATUS.md). Enforcing the FK here would break
-- handoff/memory writes for every task created before that migration.
CREATE TABLE IF NOT EXISTS handoffs (
    handoff_id    UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    task_id       UUID NOT NULL,
    source_agent  TEXT NOT NULL,
    target_agent  TEXT NOT NULL,
    context       JSONB DEFAULT '{}',
    artifacts     JSONB DEFAULT '[]',   -- references (R2 keys), not raw blobs
    requirements  JSONB DEFAULT '{}',
    constraints   JSONB DEFAULT '{}',
    status        TEXT NOT NULL DEFAULT 'pending',  -- pending|accepted|rejected|completed
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── Evaluations ───────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS evaluations (
    evaluation_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    task_id       UUID REFERENCES tasks(task_id),
    verdict       TEXT NOT NULL,   -- pass|fail|retry|require_human
    checks        JSONB DEFAULT '{}',  -- {completion: bool, correctness: bool, policy_compliance: bool, ...}
    notes         TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── Memory records (pointer table; vectors live in Qdrant) ──
-- agent_id/session_id/task_id below are NOT foreign keys for the same
-- reason as `handoffs` above — Redis is the task system-of-record
-- pre-Phase-6, and agent_id/session_id on a memory write are often
-- null (e.g. Hermes-level task summaries with no bound agent yet).
CREATE TABLE IF NOT EXISTS memory_records (
    memory_id     UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    agent_id      UUID,
    session_id    UUID,
    task_id       UUID,
    source        TEXT NOT NULL,     -- task_result|research|skill|manual
    type          TEXT NOT NULL,     -- fact|summary|experience|workflow
    content       TEXT NOT NULL,
    qdrant_point_id UUID,            -- null until embedded and pushed to Qdrant
    retention_policy TEXT NOT NULL DEFAULT 'default',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── Artifacts (metadata; blobs live in R2) ──────────────────
CREATE TABLE IF NOT EXISTS artifacts (
    artifact_id   UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    task_id       UUID REFERENCES tasks(task_id),
    r2_bucket     TEXT NOT NULL,
    r2_key        TEXT NOT NULL,
    content_type  TEXT,
    size_bytes    BIGINT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── Audit log (security-relevant events) ────────────────────
CREATE TABLE IF NOT EXISTS audit_logs (
    audit_id      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    actor         TEXT NOT NULL,      -- agent_id, "system", or human identifier
    action        TEXT NOT NULL,
    resource      TEXT,
    decision      TEXT,               -- allow|deny|require_approval
    detail        JSONB DEFAULT '{}',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_audit_logs_actor ON audit_logs(actor);
