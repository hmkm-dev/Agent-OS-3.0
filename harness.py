from __future__ import annotations
import copy,hashlib,time,uuid
from dataclasses import dataclass,field
class RefinementRejected(Exception):pass
@dataclass(frozen=True)
class BaseSystemPrompt:
    content:str
    digest:str=field(init=False)
    def __post_init__(self):object.__setattr__(self,"digest",hashlib.sha256(self.content.encode()).hexdigest())
@dataclass
class SupplementalItem:
    item_id:str;kind:str;key:str;value:str;version:int=1;enabled:bool=True;updated_at:float=field(default_factory=time.time)
class ContinualHarness:
    ALLOWED={"prompt_note","memory","skill","subagent_spec"}
    def __init__(self,base_prompt):self.base=BaseSystemPrompt(base_prompt);self.items={};self.snapshots={};self.history=[]
    def refine(self,*,kind,key,value,evidence_ids,evidence_verified,action="upsert",item_id=None):
        if kind not in self.ALLOWED:raise RefinementRejected("unsupported refinement kind")
        if not evidence_ids or not evidence_verified:raise RefinementRejected("/refine requires verified evidence")
        if action not in {"upsert","delete"}:raise RefinementRejected("invalid action")
        if action=="delete":
            if item_id not in self.items:raise KeyError(item_id)
            old=self.items.pop(item_id);self.history.append({"action":"delete","item":old.__dict__.copy(),"evidence_ids":list(evidence_ids)});return old
        if item_id and item_id in self.items:item=self.items[item_id];item.version+=1;item.value=value;item.updated_at=time.time()
        else:item=SupplementalItem(item_id or str(uuid.uuid4()),kind,key,value);self.items[item.item_id]=item
        self.history.append({"action":"upsert","item":item.__dict__.copy(),"evidence_ids":list(evidence_ids)});return item
    def snapshot(self):
        sid=str(uuid.uuid4());self.snapshots[sid]={"base_digest":self.base.digest,"state":self.snapshot_state(),"history_len":len(self.history)};return sid
    def rollback(self,sid):
        s=self.snapshots[sid]
        if s["base_digest"]!=self.base.digest:raise RefinementRejected("base prompt digest changed")
        self.restore_snapshot_state(s["state"]);self.history=self.history[:s["history_len"]]
    def load_items(self, rows):
        self.items={}
        for row in rows:
            item=SupplementalItem(str(row["item_id"]),row["kind"],row["item_key"],row["value"],int(row.get("version",1)),bool(row.get("enabled",True)),float(row.get("updated_at",time.time())))
            self.items[item.item_id]=item

    def snapshot_state(self):
        return {"items":{k:v.__dict__.copy() for k,v in self.items.items()},"history":copy.deepcopy(self.history)}

    def restore_snapshot_state(self,state):
        self.items={}
        for k,v in (state.get("items") or {}).items():
            self.items[k]=SupplementalItem(**v)
        self.history=copy.deepcopy(state.get("history") or [])

    def render_supplemental(self):return "\n".join(f"[{i.kind}:{i.key}:v{i.version}] {i.value}" for i in self.items.values() if i.enabled)
