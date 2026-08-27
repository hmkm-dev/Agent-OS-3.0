import pytest
from services.hermes.agent_os30.harness import ContinualHarness,RefinementRejected

def test_evidence_gate_and_immutable_base():
 h=ContinualHarness('BASE');d=h.base.digest
 with pytest.raises(RefinementRejected):h.refine(kind='skill',key='x',value='y',evidence_ids=['e'],evidence_verified=False)
 h.refine(kind='skill',key='x',value='y',evidence_ids=['e'],evidence_verified=True);assert h.base.digest==d
def test_snapshot_rollback():
 h=ContinualHarness('base');h.refine(kind='memory',key='x',value='one',evidence_ids=['e'],evidence_verified=True);sid=h.snapshot();h.refine(kind='memory',key='x',value='two',evidence_ids=['e'],evidence_verified=True);h.rollback(sid);assert 'one' in h.render_supplemental()
