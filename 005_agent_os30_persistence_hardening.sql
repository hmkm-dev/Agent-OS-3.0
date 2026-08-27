-- Agent OS 3.0 persistence hardening. Additive only: no existing table/data is dropped.
ALTER TABLE agent_sessions ADD COLUMN IF NOT EXISTS state_blob BYTEA;
ALTER TABLE agent_sessions ADD COLUMN IF NOT EXISTS messages JSONB NOT NULL DEFAULT '[]';
CREATE INDEX IF NOT EXISTS idx_agent_sessions_status ON agent_sessions(status);
CREATE INDEX IF NOT EXISTS idx_agent_goals_active ON agent_goals(status, next_run_at);
CREATE INDEX IF NOT EXISTS idx_agent_checkpoints_mission_created ON agent_checkpoints(mission_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_harness_refinements_item_created ON harness_refinements(item_id, created_at DESC);
