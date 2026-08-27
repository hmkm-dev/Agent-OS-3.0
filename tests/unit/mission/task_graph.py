"""
Task graph — dependency-aware task management, per spec §4. Real
graph algorithms (Kahn's algorithm for topological sort + cycle
detection), not a flat TODO list with a "dependencies" field that
nothing actually checks.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone


class CyclicDependencyError(Exception):
    pass


class InvalidTaskTransition(Exception):
    pass


# Real, validated task state machine (spec §11) — rejects illegal
# transitions instead of accepting any status string. Includes
# `unknown_after_crash` (spec §9) as a real, reachable state: a
# dispatched/running task discovered mid-flight after a restart lands
# here rather than being silently assumed either succeeded or failed.
TASK_ALLOWED_TRANSITIONS = {
    "pending": {"dispatched", "skipped"},
    # NOTE: "dispatched" -> "passed"/"blocked" directly (not via "running")
    # reflects actual current runtime behavior: no code path writes an
    # explicit "running" transition yet — a worker either finishes or
    # crashes without a DB write in between. "running" is included as a
    # real, reachable state for future use (e.g. a heartbeat write from
    # base_worker.py) and for crash-recovery classification (spec §9),
    # not because current code populates it — documented here rather
    # than silently claimed as already wired in.
    "dispatched": {"running", "verifying", "passed", "blocked", "pending", "unknown_after_crash"},
    "running": {"verifying", "passed", "blocked", "pending", "unknown_after_crash"},
    "verifying": {"passed", "blocked", "pending", "unknown_after_crash"},
    "unknown_after_crash": {"pending", "blocked", "passed"},  # resolved by crash-recovery logic, see spec §9
    "passed": set(),       # terminal
    "blocked": {"pending"},  # a human/replan can un-block back to pending
    "skipped": set(),       # terminal
}


class TaskGraph:
    def __init__(self, db):
        self.db = db

    async def add_task(self, mission_id: str, description: str, objective: str | None = None,
                        dependencies: list[str] | None = None, priority: int = 5,
                        assigned_executor: str | None = None, required_tools: list | None = None,
                        success_criteria: list | None = None, verification_method: str | None = None,
                        max_retries: int = 3) -> dict:
        task_id = str(uuid.uuid4())
        deps = dependencies or []

        # Validate dependencies actually exist in this mission before
        # inserting — a dangling dependency would silently deadlock
        # task selection later.
        if deps:
            existing = await self.db.fetch(
                "SELECT task_id FROM mission_tasks WHERE mission_id = $1 AND task_id = ANY($2::uuid[])",
                mission_id, deps,
            )
            found_ids = {str(r["task_id"]) for r in existing}
            missing = set(deps) - found_ids
            if missing:
                raise ValueError(f"dependencies not found in mission {mission_id}: {missing}")

        await self.db.execute(
            """
            INSERT INTO mission_tasks (task_id, mission_id, description, objective, dependencies,
                                        priority, status, assigned_executor, required_tools,
                                        success_criteria, verification_method, max_retries)
            VALUES ($1, $2, $3, $4, $5, $6, 'pending', $7, $8, $9, $10, $11)
            """,
            task_id, mission_id, description, objective, json.dumps(deps),
            priority, assigned_executor, json.dumps(required_tools or []),
            json.dumps(success_criteria or []), verification_method, max_retries,
        )
        return {"task_id": task_id, "status": "pending"}

    async def get_task(self, task_id: str) -> dict | None:
        row = await self.db.fetchrow("SELECT * FROM mission_tasks WHERE task_id = $1", task_id)
        return dict(row) if row else None

    async def all_tasks(self, mission_id: str) -> list[dict]:
        rows = await self.db.fetch(
            "SELECT * FROM mission_tasks WHERE mission_id = $1", mission_id
        )
        return [dict(r) for r in rows]

    async def validate_acyclic(self, mission_id: str) -> None:
        """Real cycle detection via DFS. Raises CyclicDependencyError
        with the exact cycle path if one exists — call this after
        building a mission's task graph, before execution starts."""
        tasks = await self.all_tasks(mission_id)
        graph = {t["task_id"]: json.loads(t["dependencies"]) if isinstance(t["dependencies"], str) else t["dependencies"] for t in tasks}

        WHITE, GRAY, BLACK = 0, 1, 2
        color = {tid: WHITE for tid in graph}
        path: list[str] = []

        def dfs(node):
            color[node] = GRAY
            path.append(node)
            for dep in graph.get(node, []):
                if dep not in color:
                    continue  # dependency outside this mission's task set — already validated at add_task time
                if color[dep] == GRAY:
                    cycle_start = path.index(dep)
                    raise CyclicDependencyError(f"cycle detected: {' -> '.join(path[cycle_start:] + [dep])}")
                if color[dep] == WHITE:
                    dfs(dep)
            path.pop()
            color[node] = BLACK

        for tid in graph:
            if color[tid] == WHITE:
                dfs(tid)

    async def topological_order(self, mission_id: str) -> list[str]:
        """Kahn's algorithm. Raises CyclicDependencyError if the graph
        isn't a DAG (via validate_acyclic, called first)."""
        await self.validate_acyclic(mission_id)

        tasks = await self.all_tasks(mission_id)
        deps_of = {t["task_id"]: (json.loads(t["dependencies"]) if isinstance(t["dependencies"], str) else t["dependencies"]) for t in tasks}
        in_degree = {tid: 0 for tid in deps_of}
        for tid, deps in deps_of.items():
            for _ in deps:
                in_degree[tid] += 1

        # Kahn's: repeatedly pull nodes with in_degree 0 (all deps satisfied)
        ready = [tid for tid, deg in in_degree.items() if deg == 0]
        order = []
        dependents = {tid: [] for tid in deps_of}
        for tid, deps in deps_of.items():
            for dep in deps:
                if dep in dependents:
                    dependents[dep].append(tid)

        while ready:
            ready.sort(key=lambda tid: -next((t["priority"] for t in tasks if t["task_id"] == tid), 5))
            node = ready.pop(0)
            order.append(node)
            for dependent in dependents[node]:
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    ready.append(dependent)

        return order

    async def ready_tasks(self, mission_id: str) -> list[dict]:
        """Tasks whose dependencies are ALL in 'passed' status and are
        themselves still 'pending' — the real "what can run right now"
        query, supporting parallel execution where dependencies permit
        (multiple tasks can be ready simultaneously)."""
        tasks = await self.all_tasks(mission_id)
        status_by_id = {t["task_id"]: t["status"] for t in tasks}
        ready = []
        for t in tasks:
            if t["status"] != "pending":
                continue
            deps = json.loads(t["dependencies"]) if isinstance(t["dependencies"], str) else t["dependencies"]
            if all(status_by_id.get(d) == "passed" for d in deps):
                ready.append(t)
        ready.sort(key=lambda t: -t["priority"])
        return ready

    async def claim_for_dispatch(self, task_id: str, executor_type: str,
                                 hermes_task_id: str, execution_id: str, started_at: datetime) -> bool:
        """Atomically claim a pending task for dispatch. This closes the
        check-then-set race where two mission executors could both observe
        the same READY task and enqueue duplicate Hermes tasks."""
        row = await self.db.fetchrow(
            """
            UPDATE mission_tasks
               SET status = 'dispatched', assigned_executor = $1, hermes_task_id = $2,
                   execution_id = $3, started_at = $4
             WHERE task_id = $5 AND status = 'pending'
         RETURNING task_id
            """,
            executor_type, hermes_task_id, execution_id, started_at, task_id,
        )
        return row is not None

    async def update_status(self, task_id: str, status: str, **fields) -> None:
        current = await self.get_task(task_id)
        if current is None:
            raise ValueError(f"task {task_id} not found")
        current_status = current["status"]

        if status != current_status and status not in TASK_ALLOWED_TRANSITIONS.get(current_status, set()):
            raise InvalidTaskTransition(
                f"cannot transition task {task_id} from '{current_status}' to '{status}' — "
                f"allowed next states: {sorted(TASK_ALLOWED_TRANSITIONS.get(current_status, set()))}"
            )

        allowed = {"status", "assigned_executor", "hermes_task_id", "outputs",
                   "errors", "started_at", "completed_at", "retry_count"}
        set_clauses = ["status = $1"]
        params: list = [status]
        idx = 2
        for k, v in fields.items():
            if k not in allowed:
                continue
            set_clauses.append(f"{k} = ${idx}")
            params.append(json.dumps(v) if isinstance(v, (dict, list)) else v)
            idx += 1
        params.append(task_id)
        await self.db.execute(
            f"UPDATE mission_tasks SET {', '.join(set_clauses)} WHERE task_id = ${idx}", *params
        )
