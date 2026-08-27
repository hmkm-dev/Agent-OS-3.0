import pytest
from services.hermes.agent_os30.workers import WorkerRegistry
from services.hermes.agent_os30.resources import ResourceManager,ModelPolicy
from services.hermes.agent_os30.trajectory import TrajectoryRecorder,CheckpointStore
from services.hermes.agent_os30.skills import ExecutableSkill,SkillValidationError
from services.hermes.agent_os30.security import safe_path,classify_risk

def test_required_worker_roles():assert {'rlm','browser','verification','seo','marketing','devops'}<=set(WorkerRegistry().specs)
def test_resources():
 r=ResourceManager({'tokens':2});r.charge(tokens=1);assert r.remaining()['tokens']==1
 with pytest.raises(RuntimeError):r.charge(tokens=2)
 assert ModelPolicy({'reasoning':'expensive'}).choose('reasoning',remaining_cost=.1)=='google/gemini-2.0-flash-001'
def test_trajectory_checkpoint():
 t=TrajectoryRecorder();t.record(mission_id='m',event_type='a');t.record(mission_id='m',event_type='b');assert t.verify_chain();c=CheckpointStore();cid=c.save('m',{'x':1});assert c.load(cid)['state']=={'x':1}
def test_executable_skill():
 s=ExecutableSkill('double','def main(x):\n return x["n"]*2');assert s.run({'n':4})==8
 with pytest.raises(SkillValidationError):ExecutableSkill('bad','import os\ndef main(x): return 1')
def test_security():
 assert safe_path('/tmp/root','a/b').as_posix().endswith('/tmp/root/a/b')
 with pytest.raises(PermissionError):safe_path('/tmp/root','../secret')
 assert classify_risk('GITHUB_CREATE_PR')=='external_write';assert classify_risk('DELETE_ACCOUNT')=='irreversible'
