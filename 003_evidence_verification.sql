-- Additive only — extends mission_evidence and mission_tasks from
-- 002_mission_control.sql, does not alter/drop anything. Also adds
-- mission_strategies (real strategy objects, not just a text label)
-- and idempotency tracking for external side effects.

ALTER TABLE mission_evidence ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'claimed';
-- claimed | verification_pending | verified | verification_failed | rejected | expired
ALTER TABLE mission_evidence ADD COLUMN IF NOT EXISTS verifier TEXT;
ALTER TABLE mission_evidence ADD COLUMN IF NOT EXISTS verified_at TIMESTAMPTZ;
ALTER TABLE mission_evidence ADD COLUMN IF NOT EXISTS evidence_hash TEXT;
ALTER TABLE mission_evidence ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ;
CREATE INDEX IF NOT EXISTS idx_mission_evidence_status ON mission_evidence(status);

-- Real strategy objects (spec §7) — a retry's "strategy_changed" must
-- reference an actual row here with real parameters, not just a text
-- label on mission_decisions.
CREATE TABLE IF NOT EXISTS mission_strategies (
    strategy_id       UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    task_id           UUID NOT NULL REFERENCES mission_tasks(task_id),
    version           INT NOT NULL,
    reason            TEXT NOT NULL,
    parameters        JSONB NOT NULL DEFAULT '{}',
    previous_strategy_id UUID REFERENCES mission_strategies(strategy_id),
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_mission_strategies_task ON mission_strategies(task_id);

-- Idempotency (spec §8): before repeating an external side effect,
-- check whether this exact (task_id, idempotency_key) already ran.
CREATE TABLE IF NOT EXISTS mission_idempotency_records (
    idempotency_key   TEXT PRIMARY KEY,
    task_id           UUID NOT NULL REFERENCES mission_tasks(task_id),
    execution_id      UUID NOT NULL,
    side_effect_kind  TEXT NOT NULL,   -- e.g. github_pr, file_write, upload
    result            JSONB,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Task state machine additions: distinguish in-flight vs
-- crash-ambiguous states (spec §9).
ALTER TABLE mission_tasks ADD COLUMN IF NOT EXISTS execution_id UUID;
-- current_status already covers PENDING/READY/RUNNING/etc conceptually
-- via the existing `status` column (services/mission/task_graph.py);
-- this migration doesn't change that column's allowed values (still
-- validated in application code, see task_graph.py's STATUS transitions
-- added this pass) — execution_id is what lets crash-recovery tell
-- "this specific attempt" apart from a stale/duplicate one.


-- Reliability indexes for restart reconciliation and atomic dispatch.
CREATE INDEX IF NOT EXISTS idx_mission_tasks_execution_id ON mission_tasks(execution_id);
CREATE INDEX IF NOT EXISTS idx_mission_tasks_status ON mission_tasks(status);
CREATE INDEX IF NOT EXISTS idx_mission_tasks_hermes_task_id ON mission_tasks(hermes_task_id);
