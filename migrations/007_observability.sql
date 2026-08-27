-- Additive observability fields for Redis-authoritative task lifecycle events.
-- task_id remains nullable because Redis task IDs are not yet rows in the
-- legacy SQL tasks table. task_key preserves the exact Redis identifier.
ALTER TABLE task_events ADD COLUMN IF NOT EXISTS task_key TEXT;
ALTER TABLE task_events ADD COLUMN IF NOT EXISTS request_id TEXT;
CREATE INDEX IF NOT EXISTS idx_task_events_task_key ON task_events(task_key);
CREATE INDEX IF NOT EXISTS idx_task_events_request_id ON task_events(request_id);

-- Keep the existing audit log schema intact while making request correlation
-- available through its JSON detail payload.
