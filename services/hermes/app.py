"""
Hermes — supervisor/planner. Real implementation covering spec §5:
receive task, create task IDs, enforce policy, request approval when
required, enqueue to Redis, track status, expose internal
model-routing endpoint for workers, trigger evaluator on completion.

Hermes does NOT execute shell/browser operations directly — those
only happen inside workers via the MCP gateway.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from typing import Literal, Optional

import redis
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

from agents.identity import AgentIdentity
from approval.manager import ApprovalManager
from db import DB, close_pool
from evaluator.evaluator import Evaluator
from handoff.manager import HandoffError, HandoffManager
from memory.pipeline import MemoryPipeline
from mission.control import InvalidTransition, MissionControl
from mission.cost_tracker import CostTracker
from mission.decomposition import DecompositionError, GoalDecomposer
from mission.executor import MissionExecutor
from mission.failure_recovery import FailureRecovery
from mission.mission_evaluator import MissionEvaluator
from mission.task_graph import CyclicDependencyError, TaskGraph
from model_router import ModelRouterError, route
from policy.engine import PolicyEngine
from agent_os30.autonomy import AutonomyController, PersistentGoal, ResourceBudget
from agent_os30.harness import ContinualHarness, RefinementRejected
from agent_os30.prime import RLMManager, RLMResourceLimit
from agent_os30.persistence import AgentOS30Store
from observability import Observability, request_context

REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")
HERMES_API_KEY = os.environ.get("HERMES_API_KEY", "")
APP_ENV = os.environ.get("APP_ENV", "development").lower()
MAX_RETRIES = int(os.environ.get("MAX_AGENT_RETRIES", "3"))

QUEUES = {
    "opencode": "queue:opencode",
    "research": "queue:research",
    "creative": "queue:creative",
}

r = redis.from_url(REDIS_URL, decode_responses=True)
db = DB()
policy_engine = PolicyEngine()
approval_manager = ApprovalManager(db)
evaluator = Evaluator(db, route_fn=route, policy_engine=policy_engine)
identity = AgentIdentity(db)
handoff_manager = HandoffManager(db, r, QUEUES)
memory_pipeline = MemoryPipeline(db)

mission_control = MissionControl(db)
task_graph = TaskGraph(db)
goal_decomposer = GoalDecomposer(db, route)
mission_evaluator = MissionEvaluator(db, route)
cost_tracker = CostTracker(db)
failure_recovery = FailureRecovery(db)

# Agent OS 3.0 additive capability managers. Existing mission/task paths remain unchanged.
rlm_manager = RLMManager()
agent_os30_store = AgentOS30Store(db)
autonomy_controller = AutonomyController(scheduler=__import__("agent_os30.autonomy", fromlist=["Scheduler"]).Scheduler(agent_os30_store))
mission_executor = MissionExecutor(db, r, route, QUEUES, runtime_store=agent_os30_store)
continual_harness = ContinualHarness(os.environ.get("BASE_SYSTEM_PROMPT", "Agent OS base system prompt"))

# Explicit handoff chain: task type -> next worker type, or None to
# terminate. Edit this to change the pipeline shape (e.g. skip creative
# for coding tasks). Hermes decides handoffs, not the workers themselves.
HANDOFF_CHAIN = {
    "research": "creative",
    "creative": "opencode",
    "opencode": None,
}

app = FastAPI(title="Hermes")
app.middleware("http")(request_context)
observability = Observability(db)


async def record_task_event(event_type: str, task: dict, **detail):
    await observability.task_event(
        event_type,
        task_key=str(task.get("task_id")) if task.get("task_id") else None,
        task_id=None,  # Redis task IDs are not rows in the legacy SQL tasks table yet.
        detail={"task_type": task.get("type"), "status": task.get("status"), **detail},
    )


@app.on_event("startup")
async def reconcile_missions_after_restart():
    """Restore durable Agent OS state, then reconcile mission work.

    Agent OS 3.0 state restoration is isolated from the pre-existing mission
    recovery path: a temporary Postgres outage must never prevent Hermes from
    attempting its normal Redis/task reconciliation. No persisted state is
    discarded or silently replaced during startup.
    """
    try:
        for row in await agent_os30_store.load_active_goals():
            gid=str(row["goal_id"])
            if gid in autonomy_controller.goals.goals:
                continue
            budget=ResourceBudget(int(row["turn_limit"]),int(row["token_limit"]),float(row["time_limit_seconds"]),int(row["tool_call_limit"]),int(row["subagent_limit"]),float(row["cost_limit_usd"]))
            goal=PersistentGoal(gid,row["objective"],status=row["status"],autonomous=bool(row["autonomous"]),heartbeat_seconds=int(row["heartbeat_seconds"]),session_id=str(row["session_id"]) if row["session_id"] else None,turn_limit=int(row["turn_limit"]),token_limit=int(row["token_limit"]),time_limit_seconds=float(row["time_limit_seconds"]),budget=budget)
            autonomy_controller.goals.goals[gid]=goal
            autonomy_controller.heartbeats.beat(gid)

        for row in await agent_os30_store.load_sessions():
            try:
                await rlm_manager.restore_persisted_session(row)
            except Exception as exc:
                print(f"[hermes] RLM session {row.get('session_id')} could not be restored: {exc}")

        async def _durable_heartbeat(goal_id=None):
            if goal_id and goal_id in autonomy_controller.goals.goals:
                autonomy_controller.heartbeats.beat(goal_id)
                await agent_os30_store.heartbeat(goal_id)
        # Restore only callbacks whose stable key is explicitly registered.
        # Unknown callbacks are skipped rather than executing arbitrary code.
        autonomy_controller.scheduler.register_callback("heartbeat", lambda: _durable_heartbeat())
        await autonomy_controller.scheduler.restore()

        continual_harness.load_items(await agent_os30_store.load_harness_items())
        for snap in await agent_os30_store.load_harness_snapshots():
            state=snap["state"]
            continual_harness.snapshots[str(snap["snapshot_id"])]={
                "base_digest":snap["base_prompt_digest"],
                "state":state.get("state",state),
                "history_len":state.get("history_len",len(continual_harness.history)),
            }
    except Exception as exc:
        print(f"[hermes] startup Agent OS persistent-state restore unavailable: {exc}")

    try:
        await mission_executor.recover_after_restart()
    except Exception as exc:
        print(f"[hermes] startup mission reconciliation failed: {exc}")

async def _worker_event_exporter():
    """Drain bounded worker lifecycle events into Postgres when available."""
    while True:
        try:
            item = await asyncio.to_thread(r.brpop, "queue:task_events", 1)
            if not item:
                continue
            _, raw = item
            event = json.loads(raw)
            await observability.task_event(
                event.get("event_type", "worker_event"),
                task_key=str(event.get("task_id")) if event.get("task_id") else None,
                detail=event,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print(f"[hermes] worker event export failed: {exc}")
            await asyncio.sleep(1)


async def _agent_os30_scheduler_loop():
    while True:
        try:
            await autonomy_controller.scheduler.tick()
        except Exception as exc:
            print(f"[hermes] durable scheduler tick failed: {exc}")
        await asyncio.sleep(1)


@app.on_event("startup")
async def start_agent_os30_scheduler():
    app.state.agent_os30_scheduler_task = asyncio.create_task(_agent_os30_scheduler_loop())
    app.state.worker_event_exporter_task = asyncio.create_task(_worker_event_exporter())

@app.on_event("shutdown")
async def stop_agent_os30_scheduler():
    for name in ("agent_os30_scheduler_task", "worker_event_exporter_task"):
        task = getattr(app.state, name, None)
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
    await close_pool()

ACTION_FOR_TYPE = {
    "opencode": "GITHUB_WRITE",       # conservative default; refine per-payload if needed
    "research": "BROWSER_NAVIGATION",
    "creative": "EXTERNAL_POST",
}


class TaskRequest(BaseModel):
    type: Literal["opencode", "research", "creative"]
    payload: dict
    priority: Optional[int] = 5
    session_id: Optional[str] = None
    agent_id: Optional[str] = None


class RouteRequest(BaseModel):
    task_type: str
    prompt: str
    max_tokens: Optional[int] = 2000


class ApprovalResolution(BaseModel):
    decision: Literal["approve", "deny"]
    approved_by: str


def check_api_key(x_api_key: Optional[str]):
    if not HERMES_API_KEY:
        if APP_ENV in {"prod", "production"}:
            raise HTTPException(status_code=503, detail="Hermes API authentication is not configured")
        return  # development-only convenience; production fails closed
    if x_api_key != HERMES_API_KEY:
        raise HTTPException(status_code=401, detail="invalid API key")


@app.get("/health")
def health():
    try:
        r.ping()
    except redis.exceptions.RedisError:
        raise HTTPException(status_code=503, detail="redis unreachable")
    return {"status": "ok", "time": time.time()}


@app.get("/ready")
async def ready():
    """Distinguishes 'process is up' (health) from 'dependencies are
    actually usable' (ready) — Postgres may not be deployed yet if
    you're still on early README phases, reflected honestly here
    rather than always returning ok."""
    checks = {"redis": False, "postgres": False}
    try:
        r.ping()
        checks["redis"] = True
    except redis.exceptions.RedisError:
        pass
    try:
        await db.fetchrow("SELECT 1")
        checks["postgres"] = True
    except Exception:
        pass
    return {"ready": all(checks.values()), "checks": checks}


@app.get("/live")
def live():
    return {"status": "alive"}


@app.post("/internal/route")
async def internal_route(req: RouteRequest, x_api_key: Optional[str] = Header(default=None)):
    """Internal endpoint workers call instead of talking to OpenRouter
    directly — keeps OPENROUTER_API_KEY out of worker containers."""
    check_api_key(x_api_key)
    try:
        return await route(req.task_type, req.prompt, req.max_tokens or 2000)
    except ModelRouterError as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.post("/tasks")
async def create_task(task: TaskRequest, x_api_key: Optional[str] = Header(default=None)):
    check_api_key(x_api_key)

    action = ACTION_FOR_TYPE.get(task.type, "EXECUTE_COMMAND")
    decision = policy_engine.evaluate(action, context={"payload": json.dumps(task.payload)})

    task_id = str(uuid.uuid4())
    record = {
        "task_id": task_id,
        "session_id": task.session_id,
        "agent_id": task.agent_id,
        "type": task.type,
        "payload": task.payload,
        "priority": task.priority,
        "status": "queued",
        "created_at": time.time(),
        "retries": 0,
    }

    if decision.result == "DENY":
        record["status"] = "cancelled"
        record["error"] = f"policy denied: {decision.reason}"
        r.set(f"task:{task_id}", json.dumps(record))
        await observability.audit("task_policy", actor=task.agent_id or "system", resource=task_id, decision="deny", detail={"action": action, "reason": decision.reason})
        await record_task_event("created", record, decision="deny", reason=decision.reason)
        raise HTTPException(status_code=403, detail=decision.reason)

    if decision.result == "REQUIRE_APPROVAL":
        record["status"] = "awaiting_approval"
        r.set(f"task:{task_id}", json.dumps(record))
        await observability.audit("task_policy", actor=task.agent_id or "system", resource=task_id, decision="require_approval", detail={"action": action, "reason": decision.reason})
        await record_task_event("created", record, decision="require_approval", reason=decision.reason)
        approval = await approval_manager.request(
            task_id=task_id, agent_id=task.agent_id, action=action, reason=decision.reason
        )
        return {"task_id": task_id, "status": "awaiting_approval", "approval_id": approval["approval_id"]}

    r.set(f"task:{task_id}", json.dumps(record))
    r.lpush(QUEUES[task.type], task_id)
    await observability.audit("task_policy", actor=task.agent_id or "system", resource=task_id, decision="allow", detail={"action": action})
    await record_task_event("queued", record, queue=QUEUES[task.type])
    return {"task_id": task_id, "status": "queued"}


@app.get("/tasks/{task_id}")
def get_task(task_id: str, x_api_key: Optional[str] = Header(default=None)):
    check_api_key(x_api_key)
    raw = r.get(f"task:{task_id}")
    if not raw:
        raise HTTPException(status_code=404, detail="task not found")
    return json.loads(raw)


@app.post("/tasks/{task_id}/cancel")
async def cancel_task(task_id: str, x_api_key: Optional[str] = Header(default=None)):
    check_api_key(x_api_key)
    raw = r.get(f"task:{task_id}")
    if not raw:
        raise HTTPException(status_code=404, detail="task not found")
    task = json.loads(raw)
    if task["status"] in ("completed", "failed", "cancelled"):
        raise HTTPException(status_code=409, detail=f"task already terminal ({task['status']})")
    task["status"] = "cancelled"
    r.set(f"task:{task_id}", json.dumps(task))
    await record_task_event("cancelled", task)
    await observability.audit("task_cancel", actor="system", resource=task_id, decision="allow")
    return {"task_id": task_id, "status": "cancelled"}


@app.post("/approvals/{approval_id}/approve")
async def approve(approval_id: str, body: ApprovalResolution, x_api_key: Optional[str] = Header(default=None)):
    check_api_key(x_api_key)
    return await _resolve_approval(approval_id, "approve", body.approved_by)


@app.post("/approvals/{approval_id}/deny")
async def deny(approval_id: str, body: ApprovalResolution, x_api_key: Optional[str] = Header(default=None)):
    check_api_key(x_api_key)
    return await _resolve_approval(approval_id, "deny", body.approved_by)


async def _resolve_approval(approval_id: str, decision: str, approved_by: str):
    # agent_ids is intentionally empty — this endpoint is only reachable
    # via the human-facing API, no agent code path calls it. ApprovalManager
    # still checks defensively against approved_by matching an agent_id.
    try:
        result = await approval_manager.resolve(approval_id, decision, approved_by, agent_ids=set())
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))

    raw = r.get(f"task:{result['task_id']}")
    if raw:
        task = json.loads(raw)
        if decision == "approve":
            task["status"] = "queued"
            r.set(f"task:{result['task_id']}", json.dumps(task))
            r.lpush(QUEUES[task["type"]], result["task_id"])
        else:
            task["status"] = "cancelled"
            r.set(f"task:{result['task_id']}", json.dumps(task))

    return result


@app.post("/tasks/{task_id}/evaluate")
async def trigger_evaluation(task_id: str, x_api_key: Optional[str] = Header(default=None)):
    """Called after a worker marks a task completed (e.g. by a small
    poller consuming queue:results). Kept as an explicit endpoint
    rather than auto-firing inside the worker so evaluation policy can
    change independently of worker code."""
    check_api_key(x_api_key)
    raw = r.get(f"task:{task_id}")
    if not raw:
        raise HTTPException(status_code=404, detail="task not found")
    task = json.loads(raw)
    await record_task_event("evaluating", task)
    result = await evaluator.evaluate(task)

    if result["verdict"] == "pass":
        task["status"] = "completed"
        await record_task_event("completed", task, verdict=result["verdict"])
        r.set(f"task:{task_id}", json.dumps(task))

        # Store a memory record of this successful task (closes the
        # previously-flagged gap: nothing used to write to Qdrant).
        # Best-effort — a missing EMBEDDING_API_KEY/QDRANT_URL must not
        # block the task from being marked complete.
        try:
            summary = json.dumps(task.get("result"))[:4000]
            await memory_pipeline.store_memory(
                agent_id=task.get("agent_id"), session_id=task.get("session_id"),
                task_id=task_id, source="task_result", type_="task_summary",
                content=summary,
            )
        except Exception as e:
            print(f"[hermes] memory store skipped for task {task_id}: {e}")

        # Real handoff dispatch per HANDOFF_CHAIN, replacing the
        # previously schema-only handoffs table.
        next_worker = HANDOFF_CHAIN.get(task["type"])
        if next_worker:
            try:
                handoff = await handoff_manager.create_handoff(
                    task_id=task_id, source_worker=task["type"], target_worker=next_worker,
                    context={"summary": json.dumps(task.get("result"))[:1500]},
                )
                dispatch = await handoff_manager.dispatch_handoff(handoff["handoff_id"])
                result["handoff"] = dispatch
            except HandoffError as e:
                print(f"[hermes] handoff not dispatched for task {task_id}: {e}")

    elif result["verdict"] == "retry" and task.get("retries", 0) < MAX_RETRIES:
        task["status"] = "queued"
        await record_task_event("retried", task, verdict=result["verdict"], retries=task.get("retries", 0) + 1)
        task["retries"] = task.get("retries", 0) + 1
        r.set(f"task:{task_id}", json.dumps(task))
        r.lpush(QUEUES[task["type"]], task_id)
    elif result["verdict"] == "require_human":
        task["status"] = "awaiting_approval"
        await record_task_event("require_human", task, verdict=result["verdict"])
        r.set(f"task:{task_id}", json.dumps(task))
        await approval_manager.request(
            task_id=task_id, agent_id=task.get("agent_id"),
            action="REVIEW_FAILED_TASK", reason="evaluator could not auto-resolve after max retries",
        )
    else:
        task["status"] = "failed"
        await record_task_event("failed", task, verdict=result["verdict"])
        r.set(f"task:{task_id}", json.dumps(task))

    return result


@app.post("/agents")
async def create_agent(name: str, role: str, x_api_key: Optional[str] = Header(default=None)):
    check_api_key(x_api_key)
    return await identity.create(name=name, role=role)


@app.get("/agents/{agent_id}")
async def get_agent(agent_id: str, x_api_key: Optional[str] = Header(default=None)):
    check_api_key(x_api_key)
    agent = await identity.get(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="agent not found")
    return agent


# ============================================================
# MISSION CONTROL — high-level goal-completion harness endpoints.
# Reuses everything above (QUEUES, r, db, route, check_api_key) rather
# than duplicating task dispatch/evaluation — a mission task becomes
# a real Hermes-tracked task via mission_executor.dispatch_ready_tasks(),
# which enqueues onto the SAME Redis queues the existing workers
# already consume.
# ============================================================

class MissionRequest(BaseModel):
    user_goal: str
    objective: Optional[str] = None
    constraints: Optional[dict] = None
    success_criteria: list[str]
    budget: Optional[dict] = None
    priority: Optional[int] = 5
    max_retries: Optional[int] = 3


@app.post("/missions")
async def create_mission(req: MissionRequest, x_api_key: Optional[str] = Header(default=None)):
    check_api_key(x_api_key)
    try:
        result = await mission_control.create_mission(
            user_goal=req.user_goal, objective=req.objective, constraints=req.constraints,
            success_criteria=req.success_criteria, budget=req.budget,
            priority=req.priority, max_retries=req.max_retries,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    mission_id = result["mission_id"]
    mission = await mission_control.get_mission(mission_id)
    from mission.artifacts import MissionArtifacts
    artifacts = MissionArtifacts(mission_id)
    artifacts.initialize()
    artifacts.write_goal(req.user_goal, req.objective or "", req.success_criteria)

    return result


@app.post("/missions/{mission_id}/plan")
async def plan_mission(mission_id: str, x_api_key: Optional[str] = Header(default=None)):
    """Real goal decomposition — calls the model router to turn the
    mission's goal into a dependency-aware task graph (spec §4)."""
    check_api_key(x_api_key)
    mission = await mission_control.get_mission(mission_id)
    if not mission:
        raise HTTPException(status_code=404, detail="mission not found")

    try:
        await mission_control.transition(mission_id, "ANALYZING")
        await mission_control.transition(mission_id, "PLANNING")
    except InvalidTransition as e:
        raise HTTPException(status_code=409, detail=str(e))

    success_criteria = json.loads(mission["success_criteria"]) if isinstance(mission["success_criteria"], str) else mission["success_criteria"]
    constraints = json.loads(mission["constraints"]) if isinstance(mission["constraints"], str) else mission["constraints"]

    try:
        tasks = await goal_decomposer.decompose(
            mission_id, mission["user_goal"], mission.get("objective") or "", constraints, success_criteria
        )
    except DecompositionError as e:
        await mission_control.transition(mission_id, "BLOCKED", phase="decomposition_failed")
        raise HTTPException(status_code=502, detail=f"goal decomposition failed: {e}")
    except CyclicDependencyError as e:
        await mission_control.transition(mission_id, "BLOCKED", phase="cyclic_plan")
        raise HTTPException(status_code=502, detail=str(e))

    from mission.artifacts import MissionArtifacts
    all_tasks = await task_graph.all_tasks(mission_id)
    MissionArtifacts(mission_id).write_plan(all_tasks)

    return {"mission_id": mission_id, "tasks_created": len(tasks)}


@app.post("/missions/{mission_id}/execute")
async def execute_mission_step(mission_id: str, x_api_key: Optional[str] = Header(default=None)):
    """Advances the mission by one step: dispatches all currently-ready
    tasks. Call this repeatedly (e.g. from a poller or cron) to drive
    the mission forward — this is the real execution loop's dispatch
    half; the completion half is process_completed_hermes_task, wired
    through the existing /tasks/{id}/evaluate flow."""
    check_api_key(x_api_key)
    mission = await mission_control.get_mission(mission_id)
    if not mission:
        raise HTTPException(status_code=404, detail="mission not found")

    if mission["status"] == "PLANNING":
        try:
            await mission_control.transition(mission_id, "EXECUTING")
        except InvalidTransition as e:
            raise HTTPException(status_code=409, detail=str(e))

    progress = await mission_executor.check_mission_progress(mission_id)

    if progress["status"] == "all_passed":
        await mission_control.transition(mission_id, "VERIFYING")
        verdict = await mission_evaluator.evaluate_mission(mission)
        from mission.artifacts import MissionArtifacts
        artifacts = MissionArtifacts(mission_id)
        evidence_count = len(await mission_evaluator.evidence_engine.get_mission_evidence(mission_id))
        if verdict["overall_verdict"] == "COMPLETED":
            await mission_control.transition_if_current(mission_id, "VERIFYING", "COMPLETED")
        else:
            await mission_control.transition_if_current(mission_id, "VERIFYING", "BLOCKED", phase="verification_incomplete")
        artifacts.write_final_report(await mission_control.get_mission(mission_id), verdict, evidence_count)
        return {"mission_id": mission_id, "status": progress["status"], "verification": verdict}

    if progress["status"] == "stuck_blocked":
        await mission_control.transition(mission_id, "BLOCKED", phase="all_remaining_tasks_blocked")
        return {"mission_id": mission_id, "status": "stuck_blocked"}

    dispatched = await mission_executor.dispatch_ready_tasks(mission_id)
    return {"mission_id": mission_id, "status": "dispatched", "dispatched_task_ids": dispatched}


@app.post("/missions/{mission_id}/tasks/{mission_task_id}/report")
async def report_mission_task_result(mission_id: str, mission_task_id: str,
                                      x_api_key: Optional[str] = Header(default=None)):
    """Called once the underlying Hermes task (created by
    dispatch_ready_tasks) has reached a terminal state and been
    evaluated — feeds that verdict back into the mission-level
    failure-recovery/advance logic. Looks up the Hermes task record
    from Redis and re-runs the existing task evaluator, reusing it
    rather than duplicating evaluation logic."""
    check_api_key(x_api_key)
    mtask = await task_graph.get_task(mission_task_id)
    if not mtask or mtask["mission_id"] != mission_id:
        raise HTTPException(status_code=404, detail="mission task not found")
    if not mtask["hermes_task_id"]:
        raise HTTPException(status_code=409, detail="mission task has not been dispatched yet")

    raw = r.get(f"task:{mtask['hermes_task_id']}")
    if not raw:
        raise HTTPException(status_code=404, detail="underlying hermes task not found in redis")
    hermes_task = json.loads(raw)
    if hermes_task["status"] not in ("completed", "failed"):
        raise HTTPException(status_code=409, detail=f"underlying task not terminal yet (status={hermes_task['status']})")

    verdict = await evaluator.evaluate(hermes_task)
    outcome = await mission_executor.process_completed_hermes_task(mission_task_id, hermes_task, verdict)
    return outcome


@app.get("/missions/{mission_id}/status")
async def mission_status(mission_id: str, x_api_key: Optional[str] = Header(default=None)):
    """Observability endpoint per spec §14 ('mission status <id>').
    scripts/mission_status.sh wraps this with a curl+jq CLI."""
    check_api_key(x_api_key)
    mission = await mission_control.get_mission(mission_id)
    if not mission:
        raise HTTPException(status_code=404, detail="mission not found")

    tasks = await task_graph.all_tasks(mission_id)
    completed = [t for t in tasks if t["status"] == "passed"]
    failed = [t for t in tasks if t["status"] == "blocked"]
    in_progress = [t for t in tasks if t["status"] in ("dispatched", "running")]
    budget = json.loads(mission["budget"]) if isinstance(mission["budget"], str) else mission["budget"]
    cost_totals = await cost_tracker.mission_totals(mission_id)

    return {
        "mission_id": mission_id,
        "goal": mission["user_goal"],
        "current_phase": mission["current_phase"],
        "status": mission["status"],
        "tasks_total": len(tasks),
        "tasks_completed": len(completed),
        "tasks_failed_blocked": len(failed),
        "tasks_in_progress": len(in_progress),
        "retry_count": mission["retry_count"],
        "budget": budget,
        "cost_so_far": cost_totals,
        "final_verification": mission.get("final_verification"),
    }


@app.get("/missions")
async def list_active_missions(x_api_key: Optional[str] = Header(default=None)):
    check_api_key(x_api_key)
    return {"missions": await mission_control.list_active()}


class V3GoalRequest(BaseModel):
    objective: str
    autonomous: bool = False
    heartbeat_seconds: int = 30
    turn_limit: int = 100
    token_limit: int = 100000
    time_limit_seconds: float = 3600
    tool_call_limit: int = 500
    subagent_limit: int = 32
    cost_limit_usd: float = 10.0


class V3RLMSessionRequest(BaseModel):
    goal: str
    parent_id: Optional[str] = None
    context: dict = {}
    backend: Literal["python", "ipython"] = "python"


class V3RLMExecuteRequest(BaseModel):
    code: str
    context: dict = {}


class V3RefineRequest(BaseModel):
    kind: Literal["prompt_note", "memory", "skill", "subagent_spec"]
    key: str
    value: str
    evidence_ids: list[str]
    evidence_verified: bool
    action: Literal["upsert", "delete"] = "upsert"
    item_id: Optional[str] = None


@app.post("/v3/goals")
async def v3_create_goal(req: V3GoalRequest, x_api_key: Optional[str] = Header(default=None)):
    check_api_key(x_api_key)
    goal = autonomy_controller.goals.create(req.objective, autonomous=req.autonomous, heartbeat_seconds=req.heartbeat_seconds,
        turn_limit=req.turn_limit, token_limit=req.token_limit, time_limit_seconds=req.time_limit_seconds,
        tool_call_limit=req.tool_call_limit, subagent_limit=req.subagent_limit, cost_limit_usd=req.cost_limit_usd)
    await agent_os30_store.save_goal(goal)
    await agent_os30_store.heartbeat(goal.goal_id)
    return {"goal_id": goal.goal_id, "status": goal.status, "autonomous": goal.autonomous}


@app.post("/v3/goals/{goal_id}/{action}")
async def v3_goal_action(goal_id: str, action: Literal["pause", "detach", "resume"], x_api_key: Optional[str] = Header(default=None)):
    check_api_key(x_api_key)
    if goal_id not in autonomy_controller.goals.goals: raise HTTPException(status_code=404, detail="goal not found in active Hermes process")
    getattr(autonomy_controller.goals, action if action != "resume" else "resume")(goal_id)
    goal=autonomy_controller.goals.goals[goal_id]
    await agent_os30_store.save_goal(goal)
    return {"goal_id": goal_id, "status": goal.status}


class V3ScheduleRequest(BaseModel):
    goal_id: str
    run_at: Optional[float] = None
    interval_seconds: Optional[float] = None
    callback_key: Literal["heartbeat"] = "heartbeat"

@app.post("/v3/schedules")
async def v3_schedule(req: V3ScheduleRequest, x_api_key: Optional[str] = Header(default=None)):
    check_api_key(x_api_key)
    if req.goal_id not in autonomy_controller.goals.goals:
        raise HTTPException(status_code=404, detail="goal not found")
    tid=autonomy_controller.scheduler.schedule(req.goal_id, callback_key=req.callback_key, run_at=req.run_at, interval_seconds=req.interval_seconds)
    return {"schedule_id":tid,"goal_id":req.goal_id,"callback_key":req.callback_key}

@app.delete("/v3/schedules/{schedule_id}")
async def v3_cancel_schedule(schedule_id: str, x_api_key: Optional[str] = Header(default=None)):
    check_api_key(x_api_key)
    if schedule_id not in autonomy_controller.scheduler.tasks:
        raise HTTPException(status_code=404, detail="schedule not found")
    autonomy_controller.scheduler.cancel(schedule_id)
    return {"status":"cancelled","schedule_id":schedule_id}

@app.post("/v3/rlm/sessions")
async def v3_create_rlm_session(req: V3RLMSessionRequest, x_api_key: Optional[str] = Header(default=None)):
    check_api_key(x_api_key)
    try:
        session = await rlm_manager.create_session(req.goal, parent_id=req.parent_id, backend=req.backend, context=req.context)
        await agent_os30_store.save_session(session)
    except (KeyError, RLMResourceLimit, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"session_id": session.session_id, "parent_id": session.parent_id, "status": session.status, "backend": session.repl.backend}


@app.post("/v3/rlm/{session_id}/children")
async def v3_create_child(session_id: str, req: V3RLMSessionRequest, x_api_key: Optional[str] = Header(default=None)):
    check_api_key(x_api_key)
    try: child = await rlm_manager.rlm(session_id, req.goal, context=req.context)
    except (KeyError, RLMResourceLimit) as exc: raise HTTPException(status_code=400, detail=str(exc))
    await agent_os30_store.save_session(child)
    # Child creation mutates the parent's child list and message inbox;
    # persist the parent too so restart recovery does not lose topology.
    parent = rlm_manager.sessions.get(session_id)
    if parent:
        await agent_os30_store.save_session(parent)
    return {"session_id": child.session_id, "parent_id": child.parent_id, "status": child.status}


@app.post("/v3/rlm/{session_id}/execute")
async def v3_execute_rlm(session_id: str, req: V3RLMExecuteRequest, x_api_key: Optional[str] = Header(default=None)):
    check_api_key(x_api_key)
    session=rlm_manager.sessions.get(session_id)
    if not session: raise HTTPException(status_code=404, detail="RLM session not found")
    try: result=session.repl.execute(req.code, context=req.context)
    except RLMResourceLimit as exc: raise HTTPException(status_code=408, detail=str(exc))
    await agent_os30_store.save_session(session)
    return result


@app.get("/v3/rlm/{session_id}/snapshot")
def v3_rlm_snapshot(session_id: str, x_api_key: Optional[str] = Header(default=None)):
    check_api_key(x_api_key)
    if session_id not in rlm_manager.sessions: raise HTTPException(status_code=404, detail="RLM session not found")
    return rlm_manager.snapshot(session_id)


@app.post("/v3/refine")
async def v3_refine(req: V3RefineRequest, x_api_key: Optional[str] = Header(default=None)):
    check_api_key(x_api_key)
    try:
        item=continual_harness.refine(kind=req.kind,key=req.key,value=req.value,evidence_ids=req.evidence_ids,evidence_verified=req.evidence_verified,action=req.action,item_id=req.item_id)
        if req.action == "delete":
            await agent_os30_store.delete_harness_item(item.item_id)
        else:
            await agent_os30_store.save_harness_item(item)
        await agent_os30_store.record_refinement(item.item_id, req.action, req.evidence_ids)
    except (RefinementRejected, KeyError) as exc: raise HTTPException(status_code=400, detail=str(exc))
    return {"item_id": item.item_id, "kind": item.kind, "version": item.version}


@app.post("/v3/refine/snapshot")
async def v3_refine_snapshot(x_api_key: Optional[str] = Header(default=None)):
    check_api_key(x_api_key)
    sid=continual_harness.snapshot()
    state=continual_harness.snapshots[sid]
    await agent_os30_store.harness_snapshot(sid, continual_harness.base.digest, state)
    return {"snapshot_id": sid, "base_prompt_digest": continual_harness.base.digest}

class V3RefineRollbackRequest(BaseModel):
    snapshot_id: str

@app.post("/v3/refine/rollback")
async def v3_refine_rollback(req: V3RefineRollbackRequest, x_api_key: Optional[str] = Header(default=None)):
    check_api_key(x_api_key)
    if req.snapshot_id not in continual_harness.snapshots:
        raise HTTPException(status_code=404, detail="snapshot not found")
    continual_harness.rollback(req.snapshot_id)
    # Reconcile DB with the in-memory snapshot without deleting the
    # historical refinement records; history remains an audit trail.
    existing=await agent_os30_store.load_harness_items()
    current=set(continual_harness.items)
    for row in existing:
        if str(row["item_id"]) not in current:
            await agent_os30_store.delete_harness_item(str(row["item_id"]))
    for item in continual_harness.items.values():
        await agent_os30_store.save_harness_item(item)
    return {"status":"rolled_back", "snapshot_id":req.snapshot_id, "item_count":len(continual_harness.items)}
