from __future__ import annotations
from dataclasses import dataclass
@dataclass
class ResourceSnapshot:
    tokens:int=0;tool_calls:int=0;subagents:int=0;runtime_seconds:float=0;cost_usd:float=0
class ResourceManager:
    def __init__(self,limits=None):self.limits={"tokens":100000,"tool_calls":500,"subagents":32,"runtime_seconds":3600.0,"cost_usd":10.0,**(limits or {})};self.used=ResourceSnapshot()
    def charge(self,**v):
        for k,x in v.items():
            if hasattr(self.used,k):setattr(self.used,k,getattr(self.used,k)+x)
        for k,limit in self.limits.items():
            if getattr(self.used,k)>limit:raise RuntimeError(f"resource budget exceeded: {k}")
    def remaining(self):return {k:max(0,self.limits[k]-getattr(self.used,k)) for k in self.limits}
class ModelPolicy:
    def __init__(self,primary=None,fallback="google/gemini-2.0-flash-001"):self.primary=primary or {};self.fallback=fallback
    def choose(self,task_type,*,remaining_cost,prefer_cheap=False):return self.fallback if prefer_cheap or remaining_cost<=.25 else self.primary.get(task_type,self.fallback)
