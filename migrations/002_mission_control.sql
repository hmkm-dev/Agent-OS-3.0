-- Mission Control schema. Purely additive — does not alter or drop
-- any table from 001_init.sql. Idempotent (IF NOT EXISTS throughout),
-- matching the existing migration's style.

CREATE TABLE IF NOT EXISTS missions (
    mission_id       UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_goal        TEXT NOT NULL,
    objective        TEXT,
    constraints      JSONB DEFAULT '{}',
    success_criteria JSONB NOT NULL DEFAULT '[]',
    budget           JSONB DEFAULT '{}',      -- {max_cost, max_tokens, max_runtime_seconds}
    deadline         TIMESTAMPTZ,
    priority         INT NOT NULL DEFAULT 5,
    current_phase    TEXT NOT NULL DEFAULT 'CREATED',
    status           TEXT NOT NULL DEFAULT 'CREATED',
    -- CREATED|ANALYZING|PLANNING|EXECUTING|VERIFYING|BLOCKED|RETRYING|
    -- WAITING_APPROVAL|COMPLETED|FAILED|CANCELLED
    retry_count      INT NOT NULL DEFAULT 0,
    max_retries      INT NOT NULL DEFAULT 3,
    final_verification JSONB,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_missions_status ON missions(status);

CREATE TABLE IF NOT EXISTS mission_tasks (
    task_id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    mission_id         UUID NOT NULL REFERENCES missions(mission_id),
    description        TEXT NOT NULL,
    objective          TEXT,
    dependencies       JSONB DEFAULT '[]',   -- array of task_id (this table's own PK)
    priority           INT NOT NULL DEFAULT 5,
    status             TEXT NOT NULL DEFAULT 'pending',
    -- pending|ready|dispatched|running|passed|failed|blocked|skipped
    assigned_executor  TEXT,                  -- opencode|research|creative
    required_tools     JSONB DEFAULT '[]',
    success_criteria   JSONB DEFAULT '[]',
    verification_method TEXT,
    retry_count        INT NOT NULL DEFAULT 0,
    max_retries        INT NOT NULL DEFAULT 3,
    hermes_task_id     UUID,                  -- correlates to Redis-tracked task, when dispatched
    outputs            JSONB,
    evidence_ids        JSONB DEFAULT '[]',
    errors             JSONB DEFAULT '[]',
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at         TIMESTAMPTZ,
    completed_at       TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_mission_tasks_mission ON mission_tasks(mission_id);
CREATE INDEX IF NOT EXISTS idx_mission_tasks_status ON mission_tasks(status);

CREATE TABLE IF NOT EXISTS mission_evidence (
    evidence_id     UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    mission_id      UUID NOT NULL REFERENCES missions(mission_id),
    task_id         UUID REFERENCES mission_tasks(task_id),
    kind            TEXT NOT NULL,   -- test_result|build_result|source_reference|screenshot_ref|health_check|log_excerpt
    claim           TEXT NOT NULL,   -- what was claimed
    verified        BOOLEAN NOT NULL DEFAULT false,
    verification_detail JSONB DEFAULT '{}',
    r2_key          TEXT,             -- for large evidence (screenshots, logs) stored in R2
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_mission_evidence_mission ON mission_evidence(mission_id);

CREATE TABLE IF NOT EXISTS mission_decisions (
    decision_id     UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    mission_id      UUID NOT NULL REFERENCES missions(mission_id),
    task_id         UUID REFERENCES mission_tasks(task_id),
    decision_type    TEXT NOT NULL,   -- strategy_change|replan|escalate|retry|skip
    reason          TEXT NOT NULL,
    previous_strategy TEXT,
    new_strategy    TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_mission_decisions_mission ON mission_decisions(mission_id);

CREATE TABLE IF NOT EXISTS mission_cost_events (
    cost_event_id   UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    mission_id      UUID NOT NULL REFERENCES missions(mission_id),
    task_id         UUID REFERENCES mission_tasks(task_id),
    model           TEXT,
    prompt_tokens   INT DEFAULT 0,
    completion_tokens INT DEFAULT 0,
    estimated_cost_usd NUMERIC(12,6) DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_mission_cost_events_mission ON mission_cost_events(mission_id);
