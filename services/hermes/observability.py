"""Structured, best-effort observability for Hermes.

Redis remains the task-state source of truth during the current migration
phase. This module adds durable task-event and security-audit records without
making task execution fail when PostgreSQL is unavailable or the observability
migration has not yet been applied.
"""
from __future__ import annotations

import contextvars
import json
import logging
import uuid
from typing import Any

from fastapi import Request

log = logging.getLogger("hermes.observability")
_request_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("request_id", default=None)


def current_request_id() -> str:
    return _request_id.get() or "system-" + uuid.uuid4().hex


async def request_context(request: Request, call_next):
    """Attach a stable request ID to logs, event rows, and the response."""
    supplied = request.headers.get("X-Request-ID", "").strip()
    request_id = supplied[:128] if supplied else uuid.uuid4().hex
    token = _request_id.set(request_id)
    try:
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response
    finally:
        _request_id.reset(token)


class Observability:
    def __init__(self, db):
        self.db = db

    async def task_event(
        self,
        event_type: str,
        *,
        task_key: str | None = None,
        detail: dict[str, Any] | None = None,
        task_id: str | None = None,
    ) -> None:
        """Persist a task event without coupling task execution to Postgres."""
        payload = dict(detail or {})
        payload.setdefault("request_id", current_request_id())
        try:
            await self.db.execute(
                """INSERT INTO task_events
                   (task_id, task_key, request_id, event_type, detail)
                   VALUES ($1, $2, $3, $4, $5::jsonb)""",
                task_id,
                task_key,
                current_request_id(),
                event_type,
                json.dumps(payload),
            )
        except Exception as exc:  # observability must never break execution
            log.warning("task event persistence unavailable event=%s task=%s error=%s", event_type, task_key, exc)

    async def audit(
        self,
        action: str,
        *,
        actor: str = "system",
        resource: str | None = None,
        decision: str | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        payload = dict(detail or {})
        payload.setdefault("request_id", current_request_id())
        try:
            await self.db.execute(
                """INSERT INTO audit_logs (actor, action, resource, decision, detail)
                   VALUES ($1, $2, $3, $4, $5::jsonb)""",
                actor,
                action,
                resource,
                decision,
                json.dumps(payload),
            )
        except Exception as exc:
            log.warning("audit persistence unavailable action=%s resource=%s error=%s", action, resource, exc)
