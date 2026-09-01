"""
Autonomous execution loop — per spec §5. This is the orchestration
glue: PLAN -> SELECT NEXT TASK(S) -> DISPATCH -> (worker executes,
existing machinery) -> EVALUATE -> PASS/FAIL -> DIAGNOSE -> REPLAN ->
RETRY, at the mission level.

Deliberately reuses the EXISTING Hermes task dispatch (POST /tasks
equivalent — here called in-process via the same Redis enqueue path)
and the EXISTING task-level evaluator, rather than duplicating that
logic. This module adds the mission-level loop ON TOP of what already
works; it does not reimplement task execution.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone

from .artifacts import MissionArtifacts
from .control import MissionControl
from .cost_tracker import BudgetExceededError, CostTracker
from .evidence import EvidenceEngine
from .verification_pipeline import VerificationPipeline
from .failure_recovery import FailureRecovery
from .strategy import StrategyManager, StrategyNotChangedError
from .task_graph import TaskGraph
try:
    from agent_os30.trajectory import TrajectoryRecorder, CheckpointStore
except ModuleNotFoundError:  # legacy root tests import services/mission directly
    from services.hermes.agent_os30.trajectory import TrajectoryRecorder, CheckpointStore

MAX_MISSION_ITERATIONS = 500  # hard ceiling — never loop forever even if every other guard fails


class MissionExecutor:
    def __init__(self, db, redis_client, route_fn, queues: dict[str, str], runtime_store=None):
        self.db = db
        self.r = redis_client
        self.route_fn = route_fn
        self.queues = queues

        self.control = MissionControl(db)
        self.task_graph = TaskGraph(db)
        self.cost_tracker = CostTracker(db)
        self.evidence_engine = EvidenceEngine(db)
        self.verification_pipeline = VerificationPipeline(db)
        self.failure_recovery = FailureRecovery(db)
        self.strategy_manager = StrategyManager(db)
        self.runtime_store = runtime_store
        self.trajectory = TrajectoryRecorder(runtime_store)
        self.checkpoints = CheckpointStore(runtime_store)

    def _artifacts(self, mission_id: str) -> MissionArtifacts:
        a = MissionArtifacts(mission_id)
        a.initialize()
        return a

    async def dispatch_ready_tasks(self, mission_id: str) -> list[str]:
        """Enqueues every currently-ready task (dependencies satisfied)
        onto the SAME Redis queues Hermes's own workers already
        consume from — a mission task becomes a real Hermes-tracked
        task, not a parallel task system. Returns the list of
        mission_task_ids dispatched this call."""
        mission = await self.control.get_mission(mission_id)
        budget = json.loads(mission["budget"]) if isinstance(mission["budget"], str) else mission["budget"]
        try:
            await self.cost_tracker.check_budget(mission_id, budget)
        except BudgetExceededError as e:
            await self.control.transition(mission_id, "BLOCKED", phase="budget_exceeded")
            self._artifacts(mission_id).append_progress(f"BLOCKED: {e}")
            return []

        ready = await self.task_graph.ready_tasks(mission_id)
        dispatched = []
        for task in ready:
            hermes_task_id = str(uuid.uuid4())
            execution_id = str(uuid.uuid4())
            requested_executor = task["assigned_executor"] or "opencode"
            executor_type = requested_executor
            # In resource-efficient hybrid mode, OpenCode is the universal
            # executor. Preserve the requested role in the payload so skill
            # selection and rollback can still distinguish it, while routing
            # execution to the live OpenCode queue.
            if os.getenv("HYBRID_MODE", "0") == "1" and executor_type != "opencode":
                executor_type = "opencode"

            # If this task has a recorded strategy (from a prior
            # strategy-changed retry), actually merge it into the
            # dispatched payload — otherwise recording it would be
            # inert bookkeeping that never changes real behavior.
            strategy = await self.strategy_manager.get_current_strategy(task["task_id"])
            strategy_note = ""
            if strategy:
                params = strategy["parameters"]
                if isinstance(params, str):
                    params = json.loads(params)
                strategy_note = f"\n\n[Retry strategy v{strategy['version']}: {params}]"

            required_tools = task.get("required_tools") or []
            if isinstance(required_tools, str):
                required_tools = json.loads(required_tools)
            payload = {
                "instructions": task["description"] + strategy_note,
                "objective": task.get("objective"),
                "mission_id": mission_id,
                "mission_task_id": task["task_id"],
                "required_tools": required_tools,
                "memory_query": task.get("objective") or task["description"],
                "capability_profile": requested_executor,
                "capability_request": {
                    "execution_id": execution_id,
                    "mission_id": mission_id,
                    "mission_task_id": task["task_id"],
                    "required_tools": required_tools,
                    "budget": {"timeout_seconds": 120, "max_tool_calls": 50, "max_subagents": 0},
                },
            } if executor_type == "opencode" else {
                "query": task["description"] + strategy_note,
                "mission_id": mission_id,
                "mission_task_id": task["task_id"],
                "capability_profile": requested_executor,
            }

            payload["execution_id"] = execution_id
            payload["idempotency_scope"] = f"{mission_id}:{task['task_id']}:{execution_id}"
            record = {
                "task_id": hermes_task_id,
                "type": executor_type,
                "payload": payload,
                "status": "queued",
                "created_at": datetime.now(timezone.utc).timestamp(),
                "retries": 0,
            }

            claimed = await self.task_graph.claim_for_dispatch(
                task["task_id"], executor_type, hermes_task_id, execution_id, datetime.now(timezone.utc)
            )
            if not claimed:
                continue
            try:
                self.r.set(f"task:{hermes_task_id}", json.dumps(record))
                self.r.lpush(self.queues[executor_type], hermes_task_id)
            except Exception:
                await self.task_graph.update_status(task["task_id"], "pending", errors=["redis dispatch failed"])
                raise
            dispatched.append(task["task_id"])
            self._artifacts(mission_id).append_progress(f"dispatched task: {task['description']}")
            if self.runtime_store:
                await self.trajectory.record_durable(mission_id=mission_id, task_id=task["task_id"], actor="hermes", event_type="task_dispatched", payload={"execution_id": execution_id, "hermes_task_id": hermes_task_id, "executor": executor_type})
                await self.checkpoints.save_durable(mission_id, {"task_id": task["task_id"], "execution_id": execution_id, "status": "dispatched"}, label="task-dispatched")

        return dispatched

    async def process_completed_hermes_task(self, mission_task_id: str, hermes_task_record: dict,
                                             evaluator_verdict: dict) -> dict:
        """Called once a dispatched task's underlying Hermes task has
        been evaluated by the EXISTING task-level evaluator
        (services/evaluator/evaluator.py) — this method reacts to that
        verdict at the mission level: records evidence, updates the
        task graph, and runs failure-recovery on FAIL rather than
        blindly retrying."""
        mission_task = await self.task_graph.get_task(mission_task_id)
        mission_id = mission_task["mission_id"]

        if evaluator_verdict["verdict"] == "pass":
            result_data = hermes_task_record.get("result") or {}
            # verification_context: real fields from the actual worker
            # result when present (e.g. OpenCode's exit_code) — the
            # pipeline falls back to VERIFICATION_PENDING, never a fake
            # VERIFIED, when a task type doesn't provide what its
            # verifier needs (e.g. a research task has no exit_code).
            evidence_kind, verification_context = self._verification_spec(mission_task, result_data)
            verification = await self.verification_pipeline.claim_and_verify(
                mission_id, mission_task_id, evidence_kind,
                claim=json.dumps(result_data)[:2000],
                verification_context=verification_context,
            )
            if verification["status"] == "verified":
                await self.task_graph.update_status(
                    mission_task_id, "passed",
                    outputs=hermes_task_record.get("result"), completed_at=datetime.now(timezone.utc),
                )
                self._artifacts(mission_id).append_progress(f"PASSED: {mission_task['description']}")
                if self.runtime_store:
                    await self.trajectory.record_durable(mission_id=mission_id, task_id=mission_task_id, actor="hermes", event_type="task_verified", payload={"verification": verification})
                    await self.checkpoints.save_durable(mission_id, {"task_id": mission_task_id, "status": "passed", "verification": verification}, label="task-verified")
                return {"action": "advance", "verification": verification}
            if verification["status"] == "verification_pending":
                await self.task_graph.update_status(
                    mission_task_id, "verifying", outputs=hermes_task_record.get("result"),
                )
                return {"action": "await_verification", "verification": verification}

            evaluator_verdict = {
                "verdict": "fail",
                "reason": f"independent verification failed: {verification}",
            }
            hermes_task_record = dict(hermes_task_record)
            hermes_task_record["last_error"] = evaluator_verdict["reason"]

        # FAIL path — real diagnose -> decide -> (retry with strategy
        # change | escalate), never a blind identical retry.
        error_text = hermes_task_record.get("last_error") or json.dumps(evaluator_verdict)
        diagnosis = await self.failure_recovery.diagnose_and_decide(
            mission_id=mission_id, task_id=mission_task_id,
            failed_step=mission_task["description"], error_text=error_text,
            retry_count=mission_task["retry_count"], max_retries=mission_task["max_retries"],
        )
        self._artifacts(mission_id).append_failure(
            mission_task["description"], diagnosis["category"], diagnosis["reason"]
        )
        if self.runtime_store:
            await self.trajectory.record_durable(mission_id=mission_id, task_id=mission_task_id, actor="hermes", event_type="task_failed", payload={"category": diagnosis["category"], "reason": diagnosis["reason"]})

        if diagnosis["action"] == "escalate":
            await self.task_graph.update_status(mission_task_id, "blocked", errors=[error_text])
            await self.control.transition(mission_id, "BLOCKED", phase=f"task_escalated:{diagnosis['category']}")
            return {"action": "escalate", "diagnosis": diagnosis}

        # retry or retry_with_strategy_change: re-queue as a fresh
        # pending task so dispatch_ready_tasks picks it up again.
        await self.task_graph.update_status(
            mission_task_id, "pending", retry_count=mission_task["retry_count"] + 1, errors=[error_text],
        )
        if diagnosis["new_strategy"]:
            # Real strategy object, not just a text label — record_strategy
            # enforces that these parameters actually differ from the
            # previous attempt's (raises StrategyNotChangedError otherwise).
            template = self.strategy_manager.next_template(diagnosis["category"], mission_task["retry_count"])
            try:
                await self.strategy_manager.record_strategy(
                    mission_task_id, reason=diagnosis["reason"], parameters=template, require_change=True,
                )
            except StrategyNotChangedError as e:
                # The template cycle ran out of distinct options — this
                # is a real limitation (see strategy.py's module docstring),
                # not something to paper over: escalate instead of
                # pretending a change happened.
                await self.task_graph.update_status(mission_task_id, "blocked", errors=[error_text, str(e)])
                await self.control.transition(mission_id, "BLOCKED", phase="strategy_options_exhausted")
                self._artifacts(mission_id).append_failure(mission_task["description"], "strategy_exhausted", str(e))
                return {"action": "escalate", "diagnosis": diagnosis, "reason": "strategy_options_exhausted"}
            self._artifacts(mission_id).append_decision("strategy_change", f"{diagnosis['new_strategy']} -> {template}")
        return {"action": "retry", "diagnosis": diagnosis}

    def _verification_spec(self, mission_task: dict, result_data: dict) -> tuple[str, dict]:
        """Choose a verifier from concrete worker output; never assume a
        successful verification method when the result lacks evidence context."""
        if "exit_code" in result_data:
            return "test_result", {
                "exit_code": result_data.get("exit_code"),
                "stdout": result_data.get("stdout", ""),
                "tests_passed": result_data.get("tests_passed", 0),
                "tests_failed": result_data.get("tests_failed", 0),
            }
        if result_data.get("sources"):
            return "source_reference", {"sources": result_data["sources"]}
        if result_data.get("r2_key"):
            return "screenshot_ref", {"r2_key": result_data["r2_key"], "bucket": result_data.get("r2_bucket")}
        if result_data.get("url"):
            return "http_health_check", {"url": result_data["url"], "expected_status": result_data.get("status_code", 200)}
        return "test_result", {}

    async def recover_after_restart(self) -> list[dict]:
        """Reconcile in-flight mission tasks after restart. Reuse the same
        Hermes task id for queued work; ambiguous running/missing work is
        surfaced as unknown_after_crash instead of blindly duplicated."""
        recovered = []
        for mission in await self.control.list_active():
            for task in await self.task_graph.all_tasks(mission["mission_id"]):
                if task["status"] not in ("dispatched", "running"):
                    continue
                hermes_id = task.get("hermes_task_id")
                raw = self.r.get(f"task:{hermes_id}") if hermes_id else None
                if not raw:
                    await self.task_graph.update_status(task["task_id"], "unknown_after_crash",
                        errors=["Hermes task record missing during startup reconciliation"])
                    recovered.append({"task_id": task["task_id"], "action": "unknown_after_crash"})
                    continue
                record = json.loads(raw)
                status = record.get("status")
                if status == "queued":
                    queue = self.queues.get(record.get("type"))
                    if queue:
                        already_queued = False
                        lpos = getattr(self.r, "lpos", None)
                        if lpos is not None:
                            already_queued = lpos(queue, hermes_id) is not None
                        if not already_queued:
                            self.r.lpush(queue, hermes_id)
                        recovered.append({"task_id": task["task_id"], "action": "requeued_same_execution", "already_queued": already_queued})
                elif status == "running":
                    await self.task_graph.update_status(task["task_id"], "unknown_after_crash",
                        errors=["worker execution was in-flight at Hermes restart; side effect outcome is ambiguous"])
                    recovered.append({"task_id": task["task_id"], "action": "unknown_after_crash"})
                elif status in ("completed", "failed"):
                    recovered.append({"task_id": task["task_id"], "action": "awaiting_report", "status": status})
        return recovered

    async def check_mission_progress(self, mission_id: str) -> dict:
        """Returns whether the mission is ready to move to VERIFYING
        (all tasks terminal) or should keep executing / is stuck."""
        tasks = await self.task_graph.all_tasks(mission_id)
        if not tasks:
            return {"status": "no_tasks"}

        statuses = {t["status"] for t in tasks}
        if statuses <= {"passed", "skipped"}:
            return {"status": "all_passed"}
        if "blocked" in statuses and not (statuses - {"blocked", "passed", "skipped"}):
            return {"status": "stuck_blocked"}
        return {"status": "in_progress"}
