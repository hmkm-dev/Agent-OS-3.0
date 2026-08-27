import os,httpx
from base_worker import BaseWorker
class MarketingWorker(BaseWorker):
    worker_type='marketing';queue_name='queue:marketing'
    def handle(self,task):
        p=task['payload']; prompt=p.get('prompt') or p.get('instructions')
        if not prompt: raise ValueError('payload.prompt or payload.instructions is required')
        r=httpx.post(os.getenv('MODEL_ROUTER_URL','http://hermes:8000/internal/route'),json={'task_type':'reasoning','prompt':prompt},timeout=90);r.raise_for_status();return {'role':'marketing','text':r.json().get('text',''),'model':r.json().get('model')}
if __name__=='__main__':MarketingWorker().run()
