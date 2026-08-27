"""
Context management — per spec §8. The mission's source of truth is
Postgres (missions/mission_tasks/mission_decisions/mission_evidence
tables) + STATE.json (services/mission/artifacts.py), NEVER
conversation history. This module's job is specifically the
"context became too large" case: summarizing completed work via the
model router and persisting that summary, so a fresh Hermes process
(after a restart, or literally a different conversation) can resume
a mission using only persisted state.

The "too large" threshold is a configured heuristic (character count
of accumulated progress notes) — documented as approximate rather
than an exact token count, since computing exact token counts would
require a tokenizer dependency this repo doesn't otherwise need.
"""

from __future__ import annotations

import datetime
import os

SUMMARIZE_THRESHOLD_CHARS = int(os.environ.get("CONTEXT_SUMMARIZE_THRESHOLD_CHARS", "8000"))


class ContextManager:
    def __init__(self, db, route_fn, artifacts_factory):
        """artifacts_factory: callable(mission_id) -> MissionArtifacts,
        so this class doesn't import artifacts.py directly and create
        an import cycle; pass `lambda mid: MissionArtifacts(mid)`."""
        self.db = db
        self.route_fn = route_fn
        self.artifacts_factory = artifacts_factory

    async def maybe_summarize(self, mission_id: str, progress_text: str) -> str | None:
        """If accumulated progress text exceeds the threshold, produce
        a real summary via the model router and persist it as the new
        baseline context. Returns the summary if one was made, else None."""
        if len(progress_text) < SUMMARIZE_THRESHOLD_CHARS:
            return None

        prompt = (
            "Summarize the following mission progress log into a concise brief "
            "that preserves: key decisions made, what's been completed, what "
            "failed and why, and what remains unresolved. This summary will "
            "REPLACE the full log as the working context, so do not drop "
            "anything a future continuation would need to know.\n\n"
            f"{progress_text}"
        )
        response = await self.route_fn("reasoning", prompt)
        summary = response["text"]

        artifacts = self.artifacts_factory(mission_id)
        state = artifacts.read_state() or {}
        state["context_summary"] = summary
        state["context_summarized_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        artifacts.write_state(state)

        return summary

    async def resume_context(self, mission_id: str) -> dict:
        """Real resume path: reads Postgres for structured state
        (mission row, tasks, decisions, evidence) plus the persisted
        STATE.json summary if one exists — this is what a mission
        executor should call after a restart instead of assuming any
        prior conversation is still available."""
        artifacts = self.artifacts_factory(mission_id)
        state = artifacts.read_state() or {}

        mission_row = await self.db.fetchrow("SELECT * FROM missions WHERE mission_id = $1", mission_id)
        tasks = await self.db.fetch("SELECT * FROM mission_tasks WHERE mission_id = $1", mission_id)
        decisions = await self.db.fetch(
            "SELECT * FROM mission_decisions WHERE mission_id = $1 ORDER BY created_at DESC LIMIT 20",
            mission_id,
        )

        return {
            "mission": dict(mission_row) if mission_row else None,
            "tasks": [dict(t) for t in tasks],
            "recent_decisions": [dict(d) for d in decisions],
            "context_summary": state.get("context_summary"),
        }
