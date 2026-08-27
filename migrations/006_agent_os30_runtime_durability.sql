-- Agent OS 3.0 runtime durability extension. Additive only.
-- No existing table or data is dropped.
CREATE TABLE IF NOT EXISTS agent_schedules (
    schedule_id UUID PRIMARY KEY,
    goal_id UUID NOT NULL REFERENCES agent_goals(goal_id) ON DELETE CASCADE,
    callback_key TEXT NOT NULL,
    run_at TIMESTAMPTZ NOT NULL,
    interval_seconds DOUBLE PRECISION,
    enabled BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_agent_schedules_due ON agent_schedules(enabled, run_at);
CREATE INDEX IF NOT EXISTS idx_agent_schedules_goal ON agent_schedules(goal_id);
