import asyncio
from services.hermes.agent_os30.autonomy import GoalManager,AutonomyController,Scheduler

def test_goal_lifecycle():
 g=GoalManager();x=g.create('ship');g.pause(x.goal_id);assert x.status=='paused';g.resume(x.goal_id);assert x.status=='active';g.detach(x.goal_id);assert x.status=='detached'
def test_bounded_continue():
 async def run():
  c=AutonomyController();g=c.goals.create('x',turn_limit=2)
  async def step(_):return {'done':False,'tokens':1}
  assert (await c.bounded_continue(g.goal_id,step))['status']=='turn_limit_reached'
 asyncio.run(run())
def test_scheduler_once():
 async def run():
  s=Scheduler();hits=[]
  async def cb():hits.append(1)
  s.schedule('g',cb,run_at=0);assert await s.tick()==1;assert await s.tick()==0
 asyncio.run(run())
