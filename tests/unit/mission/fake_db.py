"""
Minimal but REAL async fake Postgres — implements enough of asyncpg's
row-returning behavior (dict-like rows, positional $N params) to
exercise the actual SQL-adjacent logic in services/mission/*.py
against real control flow, not a mocked-out version of that logic.
Intentionally simple: parses just enough of each query shape this
test suite actually issues.
"""
import re
import uuid


class FakeRow(dict):
    def __getitem__(self, key):
        return super().__getitem__(key)


class FakeDB:
    def __init__(self):
        self.missions = {}
        self.mission_tasks = {}
        self.mission_evidence = {}
        self.mission_decisions = {}
        self.mission_cost_events = {}
        self.mission_strategies = {}
        self.mission_idempotency_records = {}

    async def execute(self, query, *args):
        q = " ".join(query.split())

        if q.startswith("INSERT INTO missions"):
            (mid, goal, obj, constraints, sc, budget, deadline, priority, max_retries) = args
            self.missions[mid] = FakeRow(
                mission_id=mid, user_goal=goal, objective=obj, constraints=constraints,
                success_criteria=sc, budget=budget, deadline=deadline, priority=priority,
                current_phase="CREATED", status="CREATED", retry_count=0, max_retries=max_retries,
                final_verification=None,
            )
            return

        if q.startswith("UPDATE missions SET status") and "WHERE mission_id = $4 AND status = $5" in q:
            new_status, phase, updated_at, mid, expected = args
            if self.missions[mid]["status"] != expected:
                return None
            self.missions[mid]["status"] = new_status
            self.missions[mid]["current_phase"] = phase
            return FakeRow(mission_id=mid)

        if q.startswith("UPDATE missions SET status"):
            new_status, phase, updated_at, mid = args
            self.missions[mid]["status"] = new_status
            self.missions[mid]["current_phase"] = phase
            return

        if q.startswith("UPDATE missions SET final_verification"):
            verification, updated_at, mid = args
            self.missions[mid]["final_verification"] = verification
            return

        if q.startswith("INSERT INTO mission_tasks"):
            (tid, mid, desc, obj, deps, priority, executor, tools, sc, vm, max_retries) = args
            self.mission_tasks[tid] = FakeRow(
                task_id=tid, mission_id=mid, description=desc, objective=obj, dependencies=deps,
                priority=priority, status="pending", assigned_executor=executor, required_tools=tools,
                success_criteria=sc, verification_method=vm, retry_count=0, max_retries=max_retries,
                hermes_task_id=None, execution_id=None, outputs=None, evidence_ids="[]", errors="[]",
                started_at=None, completed_at=None,
            )
            return

        if q.startswith("UPDATE mission_tasks SET"):
            # dynamic SET clause from TaskGraph.update_status
            set_part = q[len("UPDATE mission_tasks SET "):q.index(" WHERE")]
            cols = [c.split("=")[0].strip() for c in set_part.split(",")]
            *values, tid = args
            for col, val in zip(cols, values):
                self.mission_tasks[tid][col] = val
            return

        if q.startswith("INSERT INTO mission_evidence"):
            (eid, mid, tid, kind, claim, created_at) = args
            self.mission_evidence[eid] = FakeRow(
                evidence_id=eid, mission_id=mid, task_id=tid, kind=kind, claim=claim,
                verified=False, status="claimed", verification_detail="{}", r2_key=None,
                verifier=None, verified_at=None, evidence_hash=None, expires_at=None,
            )
            return

        if q.startswith("UPDATE mission_evidence SET verified = true, status = 'verified'"):
            detail, r2_key, verifier, verified_at, evidence_hash, eid = args
            e = self.mission_evidence[eid]
            e["verified"] = True
            e["status"] = "verified"
            e["verification_detail"] = detail
            e["r2_key"] = r2_key
            e["verifier"] = verifier
            e["verified_at"] = verified_at
            e["evidence_hash"] = evidence_hash
            return

        if q.startswith("UPDATE mission_evidence SET status = 'verification_pending'"):
            detail, eid = args
            e = self.mission_evidence[eid]
            e["status"] = "verification_pending"
            e["verification_detail"] = detail
            return

        if q.startswith("UPDATE mission_evidence SET status = 'verification_failed'"):
            verifier, detail, verified_at, eid = args
            e = self.mission_evidence[eid]
            e["status"] = "verification_failed"
            e["verifier"] = verifier
            e["verification_detail"] = detail
            e["verified_at"] = verified_at
            return

        if q.startswith("UPDATE mission_evidence SET status = 'rejected'"):
            detail, eid = args
            e = self.mission_evidence[eid]
            e["status"] = "rejected"
            e["verified"] = False
            e["verification_detail"] = detail
            return

        if q.startswith("UPDATE mission_evidence SET status = 'expired'"):
            eid = args[0]
            e = self.mission_evidence[eid]
            e["status"] = "expired"
            e["verified"] = False
            return

        if q.startswith("INSERT INTO mission_strategies"):
            (sid, tid, version, reason, params, prev_sid, created_at) = args
            self.mission_strategies[sid] = FakeRow(
                strategy_id=sid, task_id=tid, version=version, reason=reason,
                parameters=params, previous_strategy_id=prev_sid, created_at=created_at,
            )
            return

        if q.startswith("INSERT INTO mission_idempotency_records"):
            (key, tid, exec_id, kind, result, created_at) = args
            self.mission_idempotency_records[key] = FakeRow(
                idempotency_key=key, task_id=tid, execution_id=exec_id,
                side_effect_kind=kind, result=result, created_at=created_at,
            )
            return

        if q.startswith("INSERT INTO mission_decisions"):
            (did, mid, tid, dtype, reason, prev, new, created_at) = args
            self.mission_decisions[did] = FakeRow(
                decision_id=did, mission_id=mid, task_id=tid, decision_type=dtype,
                reason=reason, previous_strategy=prev, new_strategy=new,
            )
            return

        if q.startswith("INSERT INTO mission_cost_events"):
            (cid, mid, tid, model, pt, ct, cost, created_at) = args
            self.mission_cost_events[cid] = FakeRow(
                cost_event_id=cid, mission_id=mid, task_id=tid, model=model,
                prompt_tokens=pt, completion_tokens=ct, estimated_cost_usd=cost,
            )
            return

        raise NotImplementedError(f"FakeDB.execute doesn't handle: {q[:80]}")

    async def fetchrow(self, query, *args):
        q = " ".join(query.split())

        if q.startswith("SELECT * FROM missions WHERE mission_id"):
            return self.missions.get(args[0])

        if q.startswith("UPDATE missions SET status = $1, current_phase = $2") and "RETURNING mission_id" in q:
            new_status, phase, updated_at, mid, expected = args
            mission = self.missions.get(mid)
            if not mission or mission["status"] != expected:
                return None
            mission["status"] = new_status
            mission["current_phase"] = phase
            return FakeRow(mission_id=mid)

        if q.startswith("UPDATE missions SET retry_count"):
            updated_at, mid = args
            self.missions[mid]["retry_count"] += 1
            return FakeRow(retry_count=self.missions[mid]["retry_count"])

        if q.startswith("UPDATE mission_tasks SET status = 'dispatched'") and "AND status = 'pending'" in q:
            executor, hermes_id, execution_id, started_at, tid = args
            task = self.mission_tasks.get(tid)
            if not task or task["status"] != "pending":
                return None
            task["status"] = "dispatched"
            task["assigned_executor"] = executor
            task["hermes_task_id"] = hermes_id
            task["execution_id"] = execution_id
            task["started_at"] = started_at
            return FakeRow(task_id=tid)

        if q.startswith("UPDATE mission_tasks SET") and "AND status =" in q and "RETURNING task_id" in q:
            # Compare-and-set support for the production task state machine.
            # This models the atomic WHERE task_id=? AND status=? guard.
            values = list(args)
            tid = values[-2]
            expected = values[-1]
            task = self.mission_tasks.get(tid)
            if not task or task["status"] != expected:
                return None
            set_part = q[len("UPDATE mission_tasks SET "):q.index(" WHERE")]
            cols = [c.split("=")[0].strip() for c in set_part.split(",")]
            for col, val in zip(cols, values[:-2]):
                task[col] = val
            return FakeRow(task_id=tid)

        if q.startswith("SELECT * FROM mission_tasks WHERE task_id"):
            return self.mission_tasks.get(args[0])

        if q.startswith("SELECT count(*) AS c FROM mission_evidence"):
            tid = args[0]
            c = sum(1 for e in self.mission_evidence.values() if e["task_id"] == tid and e["status"] == "verified")
            return FakeRow(c=c)

        if q.startswith("SELECT * FROM mission_strategies WHERE task_id"):
            tid = args[0]
            versions = [s for s in self.mission_strategies.values() if s["task_id"] == tid]
            if not versions:
                return None
            return max(versions, key=lambda s: s["version"])

        if q.startswith("SELECT * FROM mission_idempotency_records WHERE idempotency_key"):
            return self.mission_idempotency_records.get(args[0])

        if q.startswith("SELECT COALESCE(SUM(prompt_tokens)"):
            mid = args[0]
            events = [e for e in self.mission_cost_events.values() if e["mission_id"] == mid]
            return FakeRow(
                prompt_tokens=sum(e["prompt_tokens"] for e in events),
                completion_tokens=sum(e["completion_tokens"] for e in events),
                estimated_cost_usd=sum(e["estimated_cost_usd"] for e in events),
                model_calls=len(events),
            )

        raise NotImplementedError(f"FakeDB.fetchrow doesn't handle: {q[:80]}")

    async def fetch(self, query, *args):
        q = " ".join(query.split())

        if "FROM mission_tasks WHERE mission_id = $1 AND task_id = ANY" in q:
            mid, ids = args
            return [t for t in self.mission_tasks.values() if t["mission_id"] == mid and t["task_id"] in ids]

        if q.startswith("SELECT * FROM mission_tasks WHERE mission_id"):
            return [t for t in self.mission_tasks.values() if t["mission_id"] == args[0]]

        if q.startswith("SELECT * FROM mission_evidence WHERE task_id = $1 AND status = $2"):
            return [e for e in self.mission_evidence.values() if e["task_id"] == args[0] and e["status"] == args[1]]

        if q.startswith("SELECT * FROM mission_evidence WHERE task_id = $1"):
            return [e for e in self.mission_evidence.values() if e["task_id"] == args[0]]

        if q.startswith("SELECT * FROM mission_evidence WHERE mission_id = $1 AND status = 'verified'"):
            return [e for e in self.mission_evidence.values() if e["mission_id"] == args[0] and e["status"] == "verified"]

        if q.startswith("SELECT * FROM mission_evidence WHERE mission_id"):
            return [e for e in self.mission_evidence.values() if e["mission_id"] == args[0]]

        if q.startswith("SELECT * FROM missions WHERE status NOT IN"):
            return [m for m in self.missions.values() if m["status"] not in ("COMPLETED", "FAILED", "CANCELLED")]

        if q.startswith("SELECT * FROM mission_decisions WHERE mission_id"):
            mid = args[0]
            decisions = [d for d in self.mission_decisions.values() if d["mission_id"] == mid]
            return decisions[:20]

        raise NotImplementedError(f"FakeDB.fetch doesn't handle: {q[:80]}")
