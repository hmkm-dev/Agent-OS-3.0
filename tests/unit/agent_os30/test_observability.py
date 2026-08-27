import asyncio
import json

from services.hermes.observability import Observability, _request_id


class RecordingDB:
    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    async def execute(self, query, *args):
        if self.fail:
            raise RuntimeError("database unavailable")
        self.calls.append((query, args))


def test_task_event_and_audit_include_request_id():
    async def run():
        db = RecordingDB()
        obs = Observability(db)
        token = _request_id.set("req-test-123")
        try:
            await obs.task_event("queued", task_key="task-1", detail={"queue": "queue:test"})
            await obs.audit("task_policy", resource="task-1", decision="allow")
        finally:
            _request_id.reset(token)
        assert len(db.calls) == 2
        event_payload = json.loads(db.calls[0][1][-1])
        audit_payload = json.loads(db.calls[1][1][-1])
        assert event_payload["request_id"] == "req-test-123"
        assert audit_payload["request_id"] == "req-test-123"

    asyncio.run(run())


def test_observability_failure_is_non_blocking():
    async def run():
        obs = Observability(RecordingDB(fail=True))
        await obs.task_event("failed", task_key="task-1")
        await obs.audit("task_failure", resource="task-1", decision="deny")

    asyncio.run(run())
