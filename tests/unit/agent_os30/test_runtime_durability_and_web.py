import asyncio
from types import SimpleNamespace

from services.hermes.agent_os30.autonomy import Scheduler
from services.hermes.agent_os30.trajectory import TrajectoryRecorder, CheckpointStore
from services.mcp.tools import agentreach
from services.mcp.tools import crawl4ai


class Store:
    def __init__(self):
        self.trajectories=[]; self.checkpoints=[]; self.schedules=[]
    async def trajectory(self,e): self.trajectories.append(e)
    async def checkpoint(self,e): self.checkpoints.append(e)
    async def load_trajectory(self,mission_id): return [e for e in self.trajectories if e['mission_id']==mission_id]
    async def latest_checkpoint(self,mission_id):
        xs=[e for e in self.checkpoints if e['mission_id']==mission_id]
        return xs[-1] if xs else None
    async def save_schedule(self,s): self.schedules.append(s)
    async def delete_schedule(self,sid): self.schedules=[s for s in self.schedules if s['task_id']!=sid]
    async def load_schedules(self): return list(self.schedules)


def test_durable_trajectory_and_checkpoint():
    async def run():
        st=Store(); tr=TrajectoryRecorder(st); cp=CheckpointStore(st)
        await tr.record_durable(mission_id='m1', event_type='dispatch', payload={'x':1})
        cid=await cp.save_durable('m1', {'status':'running'}, label='runtime')
        assert len(st.trajectories)==1
        assert cid in cp.checkpoints
        assert (await cp.load_latest_durable('m1'))['state']['status']=='running'
        assert tr.verify_chain()
    asyncio.run(run())


def test_scheduler_persists_and_restores_registered_callback():
    async def run():
        st=Store(); seen=[]; s=Scheduler(st)
        async def cb(goal_id): seen.append(goal_id)
        s.register_callback('heartbeat', cb)
        sid=s.schedule('g1', callback_key='heartbeat', run_at=0, interval_seconds=None)
        await asyncio.sleep(0)
        assert st.schedules and st.schedules[0]['task_id']==sid
        await s.tick()
        assert seen==['g1']
        assert st.schedules==[]
    asyncio.run(run())


def test_scheduler_does_not_restore_unknown_callback():
    async def run():
        st=Store(); st.schedules=[{'task_id':'s1','goal_id':'g1','callback_key':'missing','run_at':0,'interval_seconds':None,'enabled':True}]
        s=Scheduler(st)
        assert await s.restore()==[]
        assert s.tasks=={}
    asyncio.run(run())


def test_crawl4ai_rejects_non_http_urls_before_dependency():
    async def run():
        try:
            await crawl4ai.crawl('file:///etc/passwd')
        except ValueError:
            return
        assert False, 'unsafe URL should be rejected'
    asyncio.run(run())


def test_agentreach_requires_explicit_command():
    old=agentreach.COMMAND
    agentreach.COMMAND='definitely-not-installed-agent-reach'
    async def run():
        try:
            await agentreach.run(['doctor'])
        except RuntimeError as e:
            assert 'not installed' in str(e)
            return
        assert False, 'missing Agent Reach must fail explicitly'
    try:
        asyncio.run(run())
    finally:
        agentreach.COMMAND=old
