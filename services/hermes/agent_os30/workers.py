from __future__ import annotations
from dataclasses import dataclass
@dataclass(frozen=True)
class WorkerSpec:
    name:str;queue:str;capabilities:tuple[str,...];tools:tuple[str,...];isolated:bool=True
DEFAULT_WORKERS={
"opencode":WorkerSpec("opencode","queue:opencode",("coding","execution"),("filesystem","github")),
"rlm":WorkerSpec("rlm","queue:rlm",("recursive_reasoning","python_repl"),("python",)),
"research":WorkerSpec("research","queue:research",("research",),("search","playwright")),
"creative":WorkerSpec("creative","queue:creative",("creative",),("filesystem","r2")),
"browser":WorkerSpec("browser","queue:browser",("browser_automation",),("playwright",)),
"verification":WorkerSpec("verification","queue:verification",("independent_verification",),("filesystem","github","http","r2")),
"seo":WorkerSpec("seo","queue:seo",("seo","research","content_audit"),("search","playwright","filesystem")),
"marketing":WorkerSpec("marketing","queue:marketing",("marketing","campaign_planning","analytics"),("search","filesystem")),
"devops":WorkerSpec("devops","queue:devops",("devops","deployment","observability"),("filesystem","github","http")),}
class WorkerRegistry:
    def __init__(self,specs=None):self.specs=dict(specs or DEFAULT_WORKERS)
    def get(self,name):return self.specs[name]
    def permissions(self,name):return set(self.specs[name].tools)
    def queues(self):return {k:v.queue for k,v in self.specs.items()}
