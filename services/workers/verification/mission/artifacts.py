"""
Persistent mission artifacts — per spec §7. Real files written to
disk via the SAME workspace-scoping pattern already used by
agents/workspace.py (path_for() rejects escapes), not a new,
parallel, unaudited filesystem mechanism. Mission state is NOT stored
in conversation history — everything needed to resume a mission is
either here or in Postgres (missions/mission_tasks tables), so a
process/Docker/server restart or a model context reset does not lose
mission state.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

MISSIONS_ROOT = os.environ.get("MISSIONS_ROOT", "/workspaces/missions")


class MissionArtifacts:
    def __init__(self, mission_id: str):
        self.mission_id = mission_id
        self.root = os.path.join(MISSIONS_ROOT, mission_id)

    def initialize(self) -> str:
        os.makedirs(self.root, exist_ok=True)
        os.makedirs(os.path.join(self.root, "EVIDENCE"), exist_ok=True)
        os.makedirs(os.path.join(self.root, "ARTIFACTS"), exist_ok=True)
        return self.root

    def _path_for(self, filename: str) -> str:
        """Same escape-prevention pattern as agents/workspace.py — a
        mission_id or filename can never resolve outside this
        mission's own directory."""
        candidate = os.path.realpath(os.path.join(self.root, filename))
        root_real = os.path.realpath(self.root)
        if not candidate.startswith(root_real + os.sep) and candidate != root_real:
            raise ValueError(f"'{filename}' resolves outside mission {self.mission_id}'s artifact directory")
        return candidate

    def write_goal(self, goal: str, objective: str, success_criteria: list) -> None:
        content = f"# Goal\n\n{goal}\n\n## Objective\n\n{objective}\n\n## Success Criteria\n\n"
        content += "\n".join(f"- {c}" for c in success_criteria)
        self._write("GOAL.md", content)

    def write_plan(self, tasks: list[dict]) -> None:
        content = "# Plan\n\n"
        for t in tasks:
            content += f"- [{t.get('status', 'pending')}] {t['description']}"
            if t.get("dependencies"):
                content += f" (depends on: {t['dependencies']})"
            content += "\n"
        self._write("PLAN.md", content)

    def write_state(self, state: dict) -> None:
        self._write("STATE.json", json.dumps(state, indent=2, default=str))

    def read_state(self) -> dict | None:
        path = self._path_for("STATE.json")
        if not os.path.isfile(path):
            return None
        with open(path) as f:
            return json.load(f)

    def append_progress(self, note: str) -> None:
        self._append("PROGRESS.md", f"- [{datetime.now(timezone.utc).isoformat()}] {note}\n")

    def append_decision(self, decision_type: str, reason: str) -> None:
        self._append("DECISIONS.md", f"- [{datetime.now(timezone.utc).isoformat()}] **{decision_type}**: {reason}\n")

    def append_failure(self, task_desc: str, category: str, reason: str) -> None:
        self._append("FAILURES.md", f"- [{datetime.now(timezone.utc).isoformat()}] **{task_desc}** ({category}): {reason}\n")

    def write_todo(self, pending_tasks: list[dict]) -> None:
        content = "# TODO\n\n" + "\n".join(f"- {t['description']}" for t in pending_tasks)
        self._write("TODO.md", content)

    def write_final_report(self, mission: dict, verification: dict, evidence_count: int) -> None:
        content = f"""# Final Report

## Goal
{mission['user_goal']}

## Status
{mission['status']}

## Final Verification
{json.dumps(verification, indent=2)}

## Evidence Collected
{evidence_count} evidence records (see EVIDENCE/ and Postgres mission_evidence table)

## Generated
{datetime.now(timezone.utc).isoformat()}
"""
        self._write("FINAL_REPORT.md", content)

    def _write(self, filename: str, content: str) -> None:
        os.makedirs(self.root, exist_ok=True)  # idempotent — callers no longer need to remember .initialize() first
        with open(self._path_for(filename), "w") as f:
            f.write(content)

    def _append(self, filename: str, content: str) -> None:
        os.makedirs(self.root, exist_ok=True)
        with open(self._path_for(filename), "a") as f:
            f.write(content)
