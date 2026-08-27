from __future__ import annotations
import ast,json,subprocess,sys
class SkillValidationError(Exception):pass
class PythonSkillValidator:
    BLOCKED_IMPORTS={"os","subprocess","socket","ctypes","multiprocessing"};BLOCKED_CALLS={"eval","exec","compile","__import__","open"}
    def validate(self,source):
        tree=ast.parse(source)
        for n in ast.walk(tree):
            if isinstance(n,ast.Import) and any(a.name.split('.')[0] in self.BLOCKED_IMPORTS for a in n.names):raise SkillValidationError("blocked import")
            if isinstance(n,ast.ImportFrom) and n.module and n.module.split('.')[0] in self.BLOCKED_IMPORTS:raise SkillValidationError("blocked import")
            if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id in self.BLOCKED_CALLS:raise SkillValidationError(f"blocked call: {n.func.id}")
        return True
class ExecutableSkill:
    def __init__(self,name,source,validator=None):self.name=name;self.source=source;self.validator=validator or PythonSkillValidator();self.validator.validate(source)
    def run(self,payload,timeout=20):
        code="import json\nINPUT="+repr(payload)+"\n"+self.source+"\nprint(json.dumps(main(INPUT)))\n";self.validator.validate(code);p=subprocess.run([sys.executable,"-I","-S","-c",code],capture_output=True,text=True,timeout=timeout)
        if p.returncode:raise RuntimeError(p.stderr[-2000:])
        return json.loads(p.stdout.strip().splitlines()[-1])
