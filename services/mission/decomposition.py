"""
Goal decomposition — turns a high-level user goal into a dependency-
aware task graph, per spec §4. Real call through the existing model
router (services/hermes/model_router.py), not a hard-coded template.
The model's output is parsed into structured tasks and validated
before being inserted into the TaskGraph — malformed output raises,
it does not get silently coerced into something that looks valid.
"""

from __future__ import annotations

import json

from .task_graph import TaskGraph

DECOMPOSITION_PROMPT = """You are decomposing a high-level goal into a dependency-aware task graph for an autonomous execution system.

Goal: {goal}
Objective: {objective}
Constraints: {constraints}
Success criteria: {success_criteria}

Output ONLY a JSON array of task objects, no other text. Each task object:
{{
  "description": "short imperative description",
  "objective": "what this task should accomplish",
  "depends_on_indices": [list of 0-based indices of tasks in THIS array that must complete first, or []],
  "priority": 1-10 (10 = highest),
  "assigned_executor": "opencode" | "research" | "creative",
  "required_tools": ["search", "playwright", "github", "filesystem"] (subset, only what's actually needed),
  "success_criteria": ["specific, checkable criteria for this task"],
  "verification_method": "how completion should be verified (e.g. 'run pytest', 'check HTTP 200', 'confirm file exists and contains X')"
}}

Order tasks so earlier indices can be dependencies of later ones. Keep the graph as small as correctly captures the goal — do not pad with unnecessary tasks."""


class DecompositionError(Exception):
    pass


class GoalDecomposer:
    def __init__(self, db, route_fn):
        """route_fn: async callable(task_type, prompt) -> {"text": ...},
        pass services.hermes.model_router.route."""
        self.task_graph = TaskGraph(db)
        self.route_fn = route_fn

    async def decompose(self, mission_id: str, goal: str, objective: str,
                         constraints: dict, success_criteria: list) -> list[dict]:
        prompt = DECOMPOSITION_PROMPT.format(
            goal=goal, objective=objective or "(none stated)",
            constraints=json.dumps(constraints), success_criteria=json.dumps(success_criteria),
        )
        response = await self.route_fn("reasoning", prompt)
        raw_tasks = self._parse_response(response["text"])

        # Two-pass insert: first pass creates all tasks with no
        # dependencies (so we have real task_ids to reference), second
        # pass... actually TaskGraph.add_task validates dependencies
        # exist at insert time, so we must insert in dependency order
        # and translate index-based deps to real task_ids as we go.
        index_to_id: dict[int, str] = {}
        created = []
        for i, t in enumerate(raw_tasks):
            dep_indices = t.get("depends_on_indices", [])
            for d in dep_indices:
                if d not in index_to_id:
                    raise DecompositionError(
                        f"task {i} depends on index {d}, which either doesn't exist or "
                        f"hasn't been created yet (deps must reference earlier indices)"
                    )
            dep_ids = [index_to_id[d] for d in dep_indices]

            result = await self.task_graph.add_task(
                mission_id=mission_id,
                description=t["description"],
                objective=t.get("objective"),
                dependencies=dep_ids,
                priority=t.get("priority", 5),
                assigned_executor=t.get("assigned_executor", "opencode"),
                required_tools=t.get("required_tools", []),
                success_criteria=t.get("success_criteria", []),
                verification_method=t.get("verification_method"),
            )
            index_to_id[i] = result["task_id"]
            created.append(result)

        await self.task_graph.validate_acyclic(mission_id)
        return created

    def _parse_response(self, text: str) -> list[dict]:
        text = text.strip()
        # Models sometimes wrap JSON in markdown fences despite instructions — strip if present.
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()

        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as e:
            raise DecompositionError(
                f"model did not return valid JSON for goal decomposition: {e}. "
                f"Raw response (truncated): {text[:500]}"
            ) from e

        if not isinstance(parsed, list) or not parsed:
            raise DecompositionError("expected a non-empty JSON array of task objects")

        for i, t in enumerate(parsed):
            if "description" not in t:
                raise DecompositionError(f"task {i} missing required 'description' field")

        return parsed
