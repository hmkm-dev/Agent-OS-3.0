import json, os, sys
sys.path.insert(0, '/app')
from base_worker import BaseWorker
from agent_os30.prime import RLMManager
class RLMWorker(BaseWorker):
    worker_type='rlm'; queue_name='queue:rlm'
    def __init__(self): super().__init__(); self.manager=RLMManager(max_depth=int(os.getenv('RLM_MAX_DEPTH','4')))
    def handle(self,task):
        # Worker-level REPL execution is persistent for the process lifetime.
        goal=task['payload'].get('goal','recursive task'); code=task['payload'].get('code','print(_context)')
        import asyncio
        async def run():
            s=await self.manager.create_session(goal,context=task['payload'].get('context',{})); return s.repl.execute(code,context=s.context)
        return asyncio.run(run())
if __name__=='__main__': RLMWorker().run()
