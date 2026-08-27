import asyncio
from services.hermes.agent_os30.prime import RLMManager,PersistentREPLSession,RLMResourceLimit,ToolRegistry,ContextCompactor

def test_repl_persists_state():
 s=PersistentREPLSession(timeout=5)
 try: assert s.execute('x=41')['ok']; assert '42' in s.execute('print(x+1)')['stdout']
 finally:s.close()
def test_repl_timeout_does_not_block_on_pipe_read():
 s=PersistentREPLSession(timeout=0.1)
 try:
  try:
   s.execute('while True: pass')
   assert False
  except RLMResourceLimit:
   pass
 finally:s.close()

def test_children_and_limits():
 async def run():
  m=RLMManager(max_depth=2,max_children_per_session=2);p=await m.create_session('p');cs=await m.fan_out(p.session_id,['a','b']);assert len(cs)==2
  try:await m.rlm(p.session_id,'c');assert False
  except RLMResourceLimit:pass
 asyncio.run(run())
def test_compaction():
 out=ContextCompactor(max_chars=150,keep_recent=1).compact([{'role':'u','content':'x'*100},{'role':'a','content':'y'*100}]);assert out[0]['type']=='compaction'
def test_tool_permissions():
 async def run():
  r=ToolRegistry();r.register('add',lambda a,b:a+b,allowed_agents={'a'});assert await r.call('a','add',a=2,b=3)==5
  try:await r.call('b','add',a=1,b=1);assert False
  except PermissionError:pass
 asyncio.run(run())
