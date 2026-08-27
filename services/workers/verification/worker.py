import asyncio, os, sys
sys.path.insert(0,'/app')
from base_worker import BaseWorker
from mission.verification_pipeline import VerificationPipeline
from db import DB
class VerificationWorker(BaseWorker):
    worker_type='verification';queue_name='queue:verification'
    def __init__(self):super().__init__();self.pipeline=VerificationPipeline(DB())
    def handle(self,task):
        p=task['payload'];return asyncio.run(self.pipeline.claim_and_verify(p['mission_id'],p.get('task_id'),p['kind'],p['claim'],p.get('verification_context',{})))
if __name__=='__main__':VerificationWorker().run()
