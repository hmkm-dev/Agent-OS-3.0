import asyncio
import json

from services.hermes.agent_os30.prime import RLMManager
from services.hermes.agent_os30.harness import ContinualHarness


def test_repl_state_export_and_restore():
    async def run():
        manager=RLMManager()
        s=await manager.create_session('persist')
        result=s.repl.execute('x = 41\n_ = x + 1')
        assert result['ok'] is True
        snap=manager.snapshot(s.session_id)
        assert 'state' in snap['repl'] and snap['repl']['state']
        restored=manager.restore_snapshot(snap)
        result=restored.repl.execute('_ = x + 1')
        assert result['ok'] is True
        assert '42' in result['result']
        restored.repl.close(); s.repl.close()
    asyncio.run(run())


def test_harness_snapshot_is_json_serializable():
    h=ContinualHarness('base')
    h.refine(kind='memory',key='x',value='one',evidence_ids=['e'],evidence_verified=True)
    sid=h.snapshot()
    json.dumps(h.snapshots[sid])
    h.refine(kind='memory',key='x',value='two',evidence_ids=['e'],evidence_verified=True)
    h.rollback(sid)
    assert 'one' in h.render_supplemental()
