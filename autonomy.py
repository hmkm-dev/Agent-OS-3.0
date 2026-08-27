from __future__ import annotations
import asyncio,time,uuid
from dataclasses import dataclass,field
from typing import Awaitable,Callable
class AutonomyLimit(Exception): pass
@dataclass
class ResourceBudget:
    max_turns:int=100; max_tokens:int=100000; max_runtime_seconds:float=3600; max_tool_calls:int=500; max_subagents:int=32; max_cost_usd:float=10.0
    turns:int=0; tokens:int=0; tool_calls:int=0; subagents:int=0; cost_usd:float=0.0; runtime_started:float=field(default_factory=time.monotonic)
    def consume(self,**v):
        self.turns+=1; self.tokens+=v.get("tokens",0); self.tool_calls+=v.get("tool_calls",0); self.subagents+=v.get("subagents",0); self.cost_usd+=v.get("cost_usd",0)
        if self.turns>self.max_turns or self.tokens>self.max_tokens or time.monotonic()-self.runtime_started>self.max_runtime_seconds or self.tool_calls>self.max_tool_calls or self.subagents>self.max_subagents or self.cost_usd>self.max_cost_usd: raise AutonomyLimit("autonomous resource budget exhausted")
@dataclass
class PersistentGoal:
    goal_id:str; objective:str; status:str="active"; autonomous:bool=False; heartbeat_seconds:int=30; session_id:str|None=None; turn_limit:int=100; token_limit:int=100000; time_limit_seconds:float=3600; created_at:float=field(default_factory=time.time); updated_at:float=field(default_factory=time.time); budget:ResourceBudget|None=None
class GoalManager:
    def __init__(self):self.goals={}
    def create(self,objective,*,autonomous=False,heartbeat_seconds=30,**limits):
        if heartbeat_seconds<1:raise ValueError("heartbeat_seconds must be positive")
        g=PersistentGoal(str(uuid.uuid4()),objective,autonomous=autonomous,heartbeat_seconds=heartbeat_seconds,turn_limit=limits.get("turn_limit",100),token_limit=limits.get("token_limit",100000),time_limit_seconds=limits.get("time_limit_seconds",3600)); g.budget=ResourceBudget(g.turn_limit,g.token_limit,g.time_limit_seconds,limits.get("tool_call_limit",500),limits.get("subagent_limit",32),limits.get("cost_limit_usd",10)); self.goals[g.goal_id]=g; return g
    def pause(self,gid):self.goals[gid].status="paused"
    def detach(self,gid):self.goals[gid].status="detached"
    def reattach(self,gid):self.goals[gid].status="active"
    def resume(self,gid):self.reattach(gid);return self.goals[gid]
class HeartbeatManager:
    def __init__(self):self.last={};self.missed={}
    def beat(self,gid):self.last[gid]=time.time();self.missed[gid]=0
    def check(self,goal):
        missed=int(max(0,(time.time()-self.last.get(goal.goal_id,goal.updated_at))//goal.heartbeat_seconds));self.missed[goal.goal_id]=missed;return missed==0
@dataclass
class ScheduledTask:
    task_id:str;goal_id:str;run_at:float;callback:Callable[[],Awaitable[object]];interval_seconds:float|None=None;enabled:bool=True
class Scheduler:
    def __init__(self):self.tasks={}
    def schedule(self,gid,callback,*,run_at=None,interval_seconds=None):
        if interval_seconds is not None and interval_seconds<=0:raise ValueError("interval_seconds must be positive")
        tid=str(uuid.uuid4());self.tasks[tid]=ScheduledTask(tid,gid,run_at or time.time(),callback,interval_seconds);return tid
    def cancel(self,tid):self.tasks[tid].enabled=False
    async def tick(self):
        ran=0;now=time.time()
        for t in list(self.tasks.values()):
            if t.enabled and t.run_at<=now:
                await t.callback();ran+=1;t.run_at=now+t.interval_seconds if t.interval_seconds else t.run_at;t.enabled=bool(t.interval_seconds)
        return ran
class AutonomyController:
    def __init__(self,goals=None,heartbeats=None,scheduler=None):self.goals=goals or GoalManager();self.heartbeats=heartbeats or HeartbeatManager();self.scheduler=scheduler or Scheduler()
    async def bounded_continue(self,gid,step,*,turns=None):
        g=self.goals.goals[gid]
        if g.status not in {"active","resumed"}:raise AutonomyLimit(f"goal is {g.status}")
        results=[]
        for _ in range(turns or g.turn_limit):
            self.heartbeats.beat(gid)
            result=await step(g);results.append(result)
            try:g.budget.consume(tokens=int(result.get("tokens",0)),tool_calls=int(result.get("tool_calls",0)),subagents=int(result.get("subagents",0)),cost_usd=float(result.get("cost_usd",0)))
            except AutonomyLimit:g.status="budget_exhausted";raise
            if result.get("done"):g.status="completed";break
        else:g.status="turn_limit_reached"
        g.updated_at=time.time();return {"goal_id":gid,"status":g.status,"results":results}
