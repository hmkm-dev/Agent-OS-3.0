from __future__ import annotations
import hashlib,json,time,uuid
from typing import Any


def _digest(event: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(event, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


class TrajectoryRecorder:
    """Hash-chained trajectory recorder with optional durable persistence.

    The synchronous API remains backward compatible. Call ``record_durable``
    from async orchestration paths when PostgreSQL durability is required.
    """
    def __init__(self, store=None):
        self.events=[]
        self.store=store

    def record(self,*,mission_id,task_id=None,actor="system",event_type,payload=None):
        prev=self.events[-1]["hash"] if self.events else "GENESIS"
        e={"id":str(uuid.uuid4()),"mission_id":mission_id,"task_id":task_id,"actor":actor,"event_type":event_type,"payload":payload or {},"timestamp":time.time(),"prev_hash":prev}
        e["hash"]=_digest(e)
        self.events.append(e)
        return e

    async def record_durable(self,*,mission_id,task_id=None,actor="system",event_type,payload=None):
        e=self.record(mission_id=mission_id,task_id=task_id,actor=actor,event_type=event_type,payload=payload)
        if self.store:
            await self.store.trajectory(e)
        return e

    async def restore(self, mission_id: str):
        if not self.store:
            return []
        events=await self.store.load_trajectory(mission_id)
        if events:
            self.events=[dict(e) for e in events]
        return list(self.events)

    def verify_chain(self):
        prev="GENESIS"
        for e in self.events:
            if e["prev_hash"]!=prev:return False
            c=dict(e);digest=c.pop("hash")
            if _digest(c)!=digest:return False
            prev=digest
        return True


class CheckpointStore:
    """Checkpoint cache with optional PostgreSQL durability."""
    def __init__(self, store=None):
        self.checkpoints={}
        self.store=store

    def save(self,mission_id,state,*,label="auto"):
        cid=str(uuid.uuid4())
        self.checkpoints[cid]={"checkpoint_id":cid,"mission_id":mission_id,"label":label,"state":state,"created_at":time.time()}
        return cid

    async def save_durable(self,mission_id,state,*,label="auto"):
        cid=self.save(mission_id,state,label=label)
        if self.store:
            await self.store.checkpoint(self.checkpoints[cid])
        return cid

    def load(self,cid):
        return self.checkpoints[cid]

    async def load_latest_durable(self,mission_id):
        if not self.store:
            return None
        row=await self.store.latest_checkpoint(mission_id)
        if row:
            self.checkpoints[str(row["checkpoint_id"])]=row
        return row
