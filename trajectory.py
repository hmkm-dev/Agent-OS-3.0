from __future__ import annotations
import hashlib,json,time,uuid
class TrajectoryRecorder:
    def __init__(self):self.events=[]
    def record(self,*,mission_id,task_id=None,actor="system",event_type,payload=None):
        prev=self.events[-1]["hash"] if self.events else "GENESIS";e={"id":str(uuid.uuid4()),"mission_id":mission_id,"task_id":task_id,"actor":actor,"event_type":event_type,"payload":payload or {},"timestamp":time.time(),"prev_hash":prev};e["hash"]=hashlib.sha256(json.dumps(e,sort_keys=True).encode()).hexdigest();self.events.append(e);return e
    def verify_chain(self):
        prev="GENESIS"
        for e in self.events:
            if e["prev_hash"]!=prev:return False
            c=dict(e);digest=c.pop("hash")
            if hashlib.sha256(json.dumps(c,sort_keys=True).encode()).hexdigest()!=digest:return False
            prev=digest
        return True
class CheckpointStore:
    def __init__(self):self.checkpoints={}
    def save(self,mission_id,state,*,label="auto"):
        cid=str(uuid.uuid4());self.checkpoints[cid]={"checkpoint_id":cid,"mission_id":mission_id,"label":label,"state":state,"created_at":time.time()};return cid
    def load(self,cid):return self.checkpoints[cid]
