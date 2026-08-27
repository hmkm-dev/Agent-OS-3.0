"""Durable persistence for Agent OS 3.0 runtime state.

All operations are additive and use the existing async Postgres wrapper.
The database is the source of truth for resumable goals, RLM sessions,
harness state, trajectories and checkpoints. Runtime managers may cache
objects, but restart recovery reconstructs them from these records.
"""
from __future__ import annotations
import json
from datetime import datetime, timezone

class AgentOS30Store:
    def __init__(self, db): self.db=db

    async def save_goal(self, goal):
        await self.db.execute("""INSERT INTO agent_goals (goal_id,objective,status,autonomous,heartbeat_seconds,session_id,turn_limit,token_limit,time_limit_seconds,tool_call_limit,subagent_limit,cost_limit_usd,next_run_at,created_at,updated_at) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15) ON CONFLICT (goal_id) DO UPDATE SET objective=EXCLUDED.objective,status=EXCLUDED.status,autonomous=EXCLUDED.autonomous,heartbeat_seconds=EXCLUDED.heartbeat_seconds,session_id=EXCLUDED.session_id,turn_limit=EXCLUDED.turn_limit,token_limit=EXCLUDED.token_limit,time_limit_seconds=EXCLUDED.time_limit_seconds,tool_call_limit=EXCLUDED.tool_call_limit,subagent_limit=EXCLUDED.subagent_limit,cost_limit_usd=EXCLUDED.cost_limit_usd,updated_at=EXCLUDED.updated_at""", goal.goal_id,goal.objective,goal.status,goal.autonomous,goal.heartbeat_seconds,goal.session_id,goal.turn_limit,goal.token_limit,goal.time_limit_seconds,goal.budget.max_tool_calls,goal.budget.max_subagents,goal.budget.max_cost_usd,getattr(goal, "next_run_at", None),datetime.now(timezone.utc),datetime.now(timezone.utc))

    async def load_active_goals(self):
        rows=await self.db.fetch("SELECT * FROM agent_goals WHERE status NOT IN ('completed','cancelled','budget_exhausted','turn_limit_reached') ORDER BY created_at")
        return [dict(r) for r in rows]

    async def heartbeat(self,goal_id,missed_count=0):
        await self.db.execute("""INSERT INTO agent_heartbeats(goal_id,last_heartbeat,missed_count) VALUES ($1,$2,$3) ON CONFLICT (goal_id) DO UPDATE SET last_heartbeat=EXCLUDED.last_heartbeat,missed_count=EXCLUDED.missed_count""",goal_id,datetime.now(timezone.utc),missed_count)

    async def save_session(self,session):
        state=session.repl.export_state()
        await self.db.execute("""INSERT INTO agent_sessions(session_id,parent_session_id,goal,status,backend,context,state_blob,messages,created_at,updated_at) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10) ON CONFLICT (session_id) DO UPDATE SET status=EXCLUDED.status,context=EXCLUDED.context,state_blob=EXCLUDED.state_blob,messages=EXCLUDED.messages,updated_at=EXCLUDED.updated_at""",session.session_id,session.parent_id,session.goal,session.status,session.repl.backend,json.dumps(session.context),json.dumps(state).encode(),json.dumps(session.messages),datetime.now(timezone.utc),datetime.now(timezone.utc))

    async def load_sessions(self):
        rows=await self.db.fetch("SELECT session_id,parent_session_id,goal,status,backend,context,state_blob,messages,created_at,updated_at FROM agent_sessions WHERE status NOT IN ('closed','deleted') ORDER BY created_at")
        result=[]
        for r in rows:
            d=dict(r)
            for key in ('context','messages'):
                if isinstance(d.get(key),str): d[key]=json.loads(d[key])
            blob=d.get('state_blob')
            if blob:
                try: d['state']=json.loads(bytes(blob).decode())
                except Exception: d['state']={}
            else: d['state']={}
            result.append(d)
        return result

    async def trajectory(self,event):
        await self.db.execute("INSERT INTO agent_trajectory(event_id,mission_id,task_id,actor,event_type,payload,prev_hash,event_hash) VALUES ($1,$2,$3,$4,$5,$6,$7,$8)",event["id"],event["mission_id"],event.get("task_id"),event["actor"],event["event_type"],json.dumps(event["payload"]),event["prev_hash"],event["hash"])

    async def load_trajectory(self,mission_id):
        rows=await self.db.fetch("SELECT event_id AS id,mission_id,task_id,actor,event_type,payload,prev_hash,event_hash AS hash,EXTRACT(EPOCH FROM created_at) AS timestamp FROM agent_trajectory WHERE mission_id=$1 ORDER BY created_at,event_id",mission_id)
        result=[]
        for r in rows:
            d=dict(r)
            if isinstance(d.get('payload'),str): d['payload']=json.loads(d['payload'])
            result.append(d)
        return result

    async def checkpoint(self,checkpoint):
        await self.db.execute("INSERT INTO agent_checkpoints(checkpoint_id,mission_id,label,state) VALUES ($1,$2,$3,$4) ON CONFLICT (checkpoint_id) DO NOTHING",checkpoint["checkpoint_id"],checkpoint["mission_id"],checkpoint["label"],json.dumps(checkpoint["state"]))

    async def latest_checkpoint(self,mission_id):
        row=await self.db.fetchrow("SELECT checkpoint_id,mission_id,label,state,EXTRACT(EPOCH FROM created_at) AS created_at FROM agent_checkpoints WHERE mission_id=$1 ORDER BY created_at DESC LIMIT 1",mission_id)
        if not row:return None
        d=dict(row)
        if isinstance(d.get('state'),str):d['state']=json.loads(d['state'])
        return d

    async def save_schedule(self, schedule):
        await self.db.execute("""INSERT INTO agent_schedules(schedule_id,goal_id,callback_key,run_at,interval_seconds,enabled,updated_at) VALUES ($1,$2,$3,$4,$5,$6,$7) ON CONFLICT (schedule_id) DO UPDATE SET run_at=EXCLUDED.run_at,interval_seconds=EXCLUDED.interval_seconds,enabled=EXCLUDED.enabled,updated_at=EXCLUDED.updated_at""", schedule["task_id"], schedule["goal_id"], schedule["callback_key"], datetime.fromtimestamp(schedule["run_at"], timezone.utc), schedule.get("interval_seconds"), schedule.get("enabled", True), datetime.now(timezone.utc))

    async def delete_schedule(self, schedule_id):
        await self.db.execute("DELETE FROM agent_schedules WHERE schedule_id=$1", schedule_id)

    async def load_schedules(self):
        rows=await self.db.fetch("SELECT schedule_id,goal_id,callback_key,EXTRACT(EPOCH FROM run_at) AS run_at,interval_seconds,enabled FROM agent_schedules WHERE enabled=true ORDER BY run_at")
        return [dict(r) for r in rows]

    async def save_harness_item(self,item):
        await self.db.execute("""INSERT INTO harness_items(item_id,kind,item_key,value,version,enabled,updated_at) VALUES ($1,$2,$3,$4,$5,$6,$7) ON CONFLICT (item_id) DO UPDATE SET kind=EXCLUDED.kind,item_key=EXCLUDED.item_key,value=EXCLUDED.value,version=EXCLUDED.version,enabled=EXCLUDED.enabled,updated_at=EXCLUDED.updated_at""",item.item_id,item.kind,item.key,item.value,item.version,item.enabled,datetime.now(timezone.utc))

    async def delete_harness_item(self,item_id):
        await self.db.execute("DELETE FROM harness_items WHERE item_id=$1",item_id)

    async def record_refinement(self,item_id,action,evidence_ids):
        await self.db.execute("INSERT INTO harness_refinements(refinement_id,item_id,action,evidence_ids) VALUES (uuid_generate_v4(),$1,$2,$3)",item_id,action,json.dumps(list(evidence_ids)))

    async def load_harness_items(self):
        rows=await self.db.fetch("SELECT item_id,kind,item_key,value,version,enabled,EXTRACT(EPOCH FROM updated_at) AS updated_at FROM harness_items ORDER BY updated_at,item_id")
        return [dict(r) for r in rows]

    async def harness_snapshot(self,snapshot_id,base_digest,state):
        await self.db.execute("INSERT INTO harness_snapshots(snapshot_id,base_prompt_digest,state) VALUES ($1,$2,$3) ON CONFLICT (snapshot_id) DO NOTHING",snapshot_id,base_digest,json.dumps(state))

    async def load_harness_snapshots(self):
        rows=await self.db.fetch("SELECT snapshot_id,base_prompt_digest,state,EXTRACT(EPOCH FROM created_at) AS created_at FROM harness_snapshots ORDER BY created_at")
        result=[]
        for r in rows:
            d=dict(r)
            if isinstance(d.get('state'),str):d['state']=json.loads(d['state'])
            result.append(d)
        return result

    async def resource_event(self,event):
        await self.db.execute("INSERT INTO agent_resource_events(event_id,mission_id,task_id,tokens,tool_calls,subagents,runtime_seconds,cost_usd) VALUES ($1,$2,$3,$4,$5,$6,$7,$8)",event["event_id"],event.get("mission_id"),event.get("task_id"),event.get("tokens",0),event.get("tool_calls",0),event.get("subagents",0),event.get("runtime_seconds",0),event.get("cost_usd",0))
