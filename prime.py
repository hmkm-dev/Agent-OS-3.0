from __future__ import annotations
import asyncio, base64, contextlib, json, pickle, subprocess, sys, threading, time, uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

class RLMError(Exception): pass
class RLMResourceLimit(RLMError): pass
class ToolCallError(RLMError): pass

@dataclass
class ToolSpec:
    name: str
    handler: Callable[..., Any]
    allowed_agents: set[str] = field(default_factory=set)
    risk: str = "low"

class ToolRegistry:
    def __init__(self): self._tools: dict[str, ToolSpec] = {}
    def register(self,name,handler,*,allowed_agents=None,risk="low"):
        if not name or not callable(handler): raise ValueError("tool name and callable handler are required")
        self._tools[name]=ToolSpec(name,handler,allowed_agents or set(),risk)
    async def call(self,agent_id,name,**kwargs):
        spec=self._tools.get(name)
        if spec is None: raise ToolCallError(f"unknown tool: {name}")
        if spec.allowed_agents and agent_id not in spec.allowed_agents: raise PermissionError(f"agent '{agent_id}' is not allowed to call '{name}'")
        result=spec.handler(**kwargs)
        return await result if asyncio.iscoroutine(result) else result
    def allowed_tools(self,agent_id): return sorted(n for n,s in self._tools.items() if not s.allowed_agents or agent_id in s.allowed_agents)

_PY_BOOTSTRAP=r'''
import contextlib,io,json,sys,traceback
ns={"__name__":"__agent_os_repl__"}
for line in sys.stdin:
    try:
        req=json.loads(line)
        if req.get("op")=="reset": ns={"__name__":"__agent_os_repl__"}; out={"ok":True,"result":None}
        elif req.get("op")=="dump":
            import base64,pickle
            safe={}
            for k,v in ns.items():
                if k.startswith("__") or k in {"_context"}: continue
                try: safe[k]=base64.b64encode(pickle.dumps(v, protocol=5)).decode("ascii")
                except Exception: pass
            out={"ok":True,"state":safe}
        elif req.get("op")=="load":
            import base64,pickle
            for k,v in (req.get("state") or {}).items():
                try: ns[k]=pickle.loads(base64.b64decode(v))
                except Exception: pass
            out={"ok":True,"result":None}
        elif req.get("op")=="exec":
            stdout,stderr=io.StringIO(),io.StringIO()
            try:
                with contextlib.redirect_stdout(stdout),contextlib.redirect_stderr(stderr): exec(compile(req.get("code",""),"<agent-os-repl>","exec"),ns,ns)
                out={"ok":True,"result":repr(ns.get("_")),"stdout":stdout.getvalue(),"stderr":stderr.getvalue()}
            except Exception as e: out={"ok":False,"error":f"{type(e).__name__}: {e}","stdout":stdout.getvalue(),"stderr":stderr.getvalue(),"traceback":traceback.format_exc(limit=8)}
        else: out={"ok":False,"error":"unknown operation"}
    except Exception as e: out={"ok":False,"error":f"protocol error: {e}"}
    sys.stdout.write(json.dumps(out,ensure_ascii=False)+"\n"); sys.stdout.flush()
'''

_IPY_BOOTSTRAP=r'''
import contextlib,io,json,sys,traceback
from IPython.core.interactiveshell import InteractiveShell
shell=InteractiveShell.instance()
for line in sys.stdin:
    try:
        req=json.loads(line)
        if req.get("op")=="reset": shell=InteractiveShell.instance(); out={"ok":True,"result":None}
        elif req.get("op")=="dump":
            import base64,pickle
            safe={}
            for k,v in shell.user_ns.items():
                if k.startswith("_") or k in {"In","Out","get_ipython"}: continue
                try: safe[k]=base64.b64encode(pickle.dumps(v, protocol=5)).decode("ascii")
                except Exception: pass
            out={"ok":True,"state":safe}
        elif req.get("op")=="load":
            import base64,pickle
            for k,v in (req.get("state") or {}).items():
                try: shell.user_ns[k]=pickle.loads(base64.b64decode(v))
                except Exception: pass
            out={"ok":True,"result":None}
        elif req.get("op")=="exec":
            stdout,stderr=io.StringIO(),io.StringIO()
            try:
                with contextlib.redirect_stdout(stdout),contextlib.redirect_stderr(stderr):
                    result=shell.run_cell(req.get("code",""),store_history=True)
                err=str(result.error_in_exec) if result.error_in_exec else None
                out={"ok":err is None,"result":repr(result.result),"stdout":stdout.getvalue(),"stderr":stderr.getvalue()}
                if err: out["error"]=err
            except Exception as e: out={"ok":False,"error":f"{type(e).__name__}: {e}","stdout":stdout.getvalue(),"stderr":stderr.getvalue(),"traceback":traceback.format_exc(limit=8)}
        else: out={"ok":False,"error":"unknown operation"}
    except Exception as e: out={"ok":False,"error":f"protocol error: {e}"}
    sys.stdout.write(json.dumps(out,ensure_ascii=False)+"\n"); sys.stdout.flush()
'''

class PersistentREPLSession:
    """Persistent model-facing Python REPL. State survives across execute calls."""
    def __init__(self,session_id=None,*,backend="python",timeout=30.0,max_output=100_000):
        if backend not in {"python","ipython"}: raise ValueError("backend must be python or ipython")
        if backend=="ipython":
            try: import IPython  # noqa
            except ImportError as e: raise RLMError("IPython backend is not installed") from e
        self.session_id=session_id or str(uuid.uuid4()); self.backend=backend; self.timeout=timeout; self.max_output=max_output
        self.process=subprocess.Popen([sys.executable,"-u","-c",_IPY_BOOTSTRAP if backend=="ipython" else _PY_BOOTSTRAP],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,bufsize=1)
        self.lock=threading.Lock(); self.closed=False; self.context={}
    def execute(self,code,*,context=None):
        if self.closed: raise RLMError("REPL session is closed")
        if len(code)>self.max_output: raise RLMResourceLimit("code exceeds input limit")
        if context: self.context.update(context); code="_context="+repr(self.context)+"\n"+code
        with self.lock:
            assert self.process.stdin and self.process.stdout
            self.process.stdin.write(json.dumps({"op":"exec","code":code})+"\n"); self.process.stdin.flush()
            deadline=time.monotonic()+self.timeout
            while time.monotonic()<deadline:
                line=self.process.stdout.readline()
                if line:
                    result=json.loads(line)
                    for k in ("stdout","stderr","traceback"):
                        if len(result.get(k,""))>self.max_output: result[k]=result[k][-self.max_output:]
                    return result
                if self.process.poll() is not None: raise RLMError("REPL process exited unexpectedly")
                time.sleep(.01)
        raise RLMResourceLimit("REPL execution timed out")
    def export_state(self, *, max_bytes=4_000_000):
        if self.closed: raise RLMError("REPL session is closed")
        with self.lock:
            assert self.process.stdin and self.process.stdout
            self.process.stdin.write(json.dumps({"op":"dump"})+"\n"); self.process.stdin.flush()
            deadline=time.monotonic()+self.timeout
            while time.monotonic()<deadline:
                line=self.process.stdout.readline()
                if line:
                    result=json.loads(line)
                    if not result.get("ok"): raise RLMError(result.get("error","state export failed"))
                    blob=json.dumps(result.get("state",{}), separators=(",",":" )).encode()
                    if len(blob)>max_bytes: raise RLMResourceLimit("REPL state exceeds persistence limit")
                    return result.get("state",{})
                if self.process.poll() is not None: raise RLMError("REPL process exited unexpectedly")
                time.sleep(.01)
        raise RLMResourceLimit("REPL state export timed out")
    def import_state(self, state):
        if self.closed: raise RLMError("REPL session is closed")
        with self.lock:
            assert self.process.stdin and self.process.stdout
            self.process.stdin.write(json.dumps({"op":"load","state":state})+"\n"); self.process.stdin.flush()
            deadline=time.monotonic()+self.timeout
            while time.monotonic()<deadline:
                line=self.process.stdout.readline()
                if line:
                    result=json.loads(line)
                    if not result.get("ok"): raise RLMError(result.get("error","state import failed"))
                    return result
                if self.process.poll() is not None: raise RLMError("REPL process exited unexpectedly")
                time.sleep(.01)
        raise RLMResourceLimit("REPL state import timed out")
    def snapshot(self): return {"session_id":self.session_id,"backend":self.backend,"context":dict(self.context),"closed":self.closed,"state":self.export_state()}
    def close(self):
        if self.closed:return
        self.closed=True
        if self.process.stdin: 
            with contextlib.suppress(Exception): self.process.stdin.close()
        with contextlib.suppress(Exception): self.process.terminate(); self.process.wait(timeout=2)
        if self.process.poll() is None:
            with contextlib.suppress(Exception): self.process.kill()

@dataclass
class RLMSession:
    session_id:str; parent_id:str|None; goal:str; repl:PersistentREPLSession
    created_at:float=field(default_factory=time.time); status:str="active"
    children:list[str]=field(default_factory=list); messages:list[dict[str,Any]]=field(default_factory=list); context:dict[str,Any]=field(default_factory=dict)

class ContextCompactor:
    def __init__(self,max_chars=24_000,keep_recent=12): self.max_chars=max_chars; self.keep_recent=keep_recent
    def compact(self,messages):
        if len(json.dumps(messages,ensure_ascii=False))<=self.max_chars:return messages
        recent=messages[-self.keep_recent:]; return [{"role":"system","type":"compaction","content":f"Compacted {len(messages)-len(recent)} older messages; durable facts should be in session context."},*recent]

class RLMManager:
    def __init__(self,*,max_depth=4,max_children_per_session=8,max_total_sessions=64,compactor=None):
        self.max_depth=max_depth; self.max_children_per_session=max_children_per_session; self.max_total_sessions=max_total_sessions; self.compactor=compactor or ContextCompactor(); self.sessions={}; self.background_tasks={}; self._lock=asyncio.Lock()
    async def create_session(self,goal,*,parent_id=None,backend="python",context=None):
        async with self._lock:
            if len(self.sessions)>=self.max_total_sessions: raise RLMResourceLimit("maximum total RLM sessions reached")
            if parent_id:
                parent=self.sessions.get(parent_id)
                if not parent: raise KeyError(parent_id)
                if self._depth(parent_id)>=self.max_depth: raise RLMResourceLimit("maximum recursive RLM depth reached")
                if len(parent.children)>=self.max_children_per_session: raise RLMResourceLimit("maximum children per session reached")
            sid=str(uuid.uuid4()); s=RLMSession(sid,parent_id,goal,PersistentREPLSession(sid,backend=backend),context=dict(context or {})); self.sessions[sid]=s
            if parent_id:self.sessions[parent_id].children.append(sid)
            return s
    def _depth(self,sid):
        d=0; cur=self.sessions[sid]
        while cur.parent_id:d+=1; cur=self.sessions[cur.parent_id]
        return d
    async def rlm(self,parent_id,goal,*,context=None):
        child=await self.create_session(goal,parent_id=parent_id,context=context); self.send(parent_id,{"type":"child_created","child_id":child.session_id,"goal":goal}); return child
    def send(self,sid,message):
        s=self.sessions[sid]; s.messages.append({"timestamp":time.time(),**message}); s.messages=self.compactor.compact(s.messages)
    def receive(self,sid): return list(self.sessions[sid].messages)
    def set_context(self,sid,key,value): self.sessions[sid].context[key]=value
    def get_context(self,sid,key,default=None): return self.sessions[sid].context.get(key,default)
    async def fan_out(self,parent_id,goals):
        if len(goals)>self.max_children_per_session: raise RLMResourceLimit("fan-out exceeds child limit")
        return await asyncio.gather(*(self.rlm(parent_id,g) for g in goals))
    def background(self,sid,coro):
        if sid not in self.sessions: raise KeyError(sid)
        t=asyncio.create_task(coro); self.background_tasks[sid]=t; return t
    def detach(self,sid): self.sessions[sid].status="detached"
    def snapshot(self,sid):
        s=self.sessions[sid]; return {"session":{"session_id":s.session_id,"parent_id":s.parent_id,"goal":s.goal,"status":s.status,"context":s.context},"messages":s.messages,"repl":s.repl.snapshot()}
    async def restore_persisted_session(self, raw):
        async with self._lock:
            sid=str(raw["session_id"])
            if sid in self.sessions:
                return self.sessions[sid]
            parent_id=str(raw["parent_session_id"]) if raw.get("parent_session_id") else None
            if parent_id and parent_id not in self.sessions:
                parent_id=None
            repl=PersistentREPLSession(sid, backend=raw.get("backend","python"))
            state=raw.get("state") or {}
            if state:
                repl.import_state(state)
            s=RLMSession(sid,parent_id,raw["goal"],repl,status="resumed",messages=list(raw.get("messages") or []),context=dict(raw.get("context") or {}))
            self.sessions[sid]=s
            if parent_id and sid not in self.sessions[parent_id].children:
                self.sessions[parent_id].children.append(sid)
            return s
    def restore_snapshot(self,snapshot):
        raw=snapshot["session"]; s=RLMSession(raw["session_id"],raw.get("parent_id"),raw["goal"],PersistentREPLSession(raw["session_id"],backend=snapshot.get("repl",{}).get("backend","python")),status="resumed",messages=list(snapshot.get("messages",[])),context=dict(raw.get("context",{}))); self.sessions[s.session_id]=s
        state=snapshot.get("repl",{}).get("state") or {}
        if state: s.repl.import_state(state)
        return s
