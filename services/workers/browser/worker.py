import os, httpx
from base_worker import BaseWorker
class BrowserWorker(BaseWorker):
    worker_type='browser'; queue_name='queue:browser'
    def handle(self,task):
        p=task['payload']; url=p.get('url')
        if not url: raise ValueError('payload.url is required')
        resp=httpx.post(f"{os.getenv('MCP_URL','http://mcp:8100')}/call",json={'worker_type':'browser','tool':'playwright','action':p.get('action','get_text'),'args':p.get('args',{'url':url})},timeout=30);resp.raise_for_status();return resp.json()
if __name__=='__main__': BrowserWorker().run()
