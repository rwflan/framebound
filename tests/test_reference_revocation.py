"""Real reviewer revocation blocks frozen work without substituting another guide."""
import json
import pytest
from framebound.v2 import storage as S
from framebound.v2.services import auto_repair as A,briefs,jobs as J
from framebound.v2.services.errors import InvalidInput
from test_automatic_execution import setup_work
from test_public_creation import cli


def test_reviewer_revocation_blocks_old_briefs_work_and_release(tmp_path,monkeypatch):
    project,client,headers,_,_=setup_work(tmp_path,monkeypatch)
    prepared=briefs.compile_reference_brief(str(project),'automatic-contract',0)
    approval=prepared['approval_id']
    body={'event_id':'test-revocation','note':'test input: source is no longer authorized'}
    assert client.post(f'/api/references/{approval}/revoke',json=body).status_code==403
    revoked=client.post(f'/api/references/{approval}/revoke',json=body,headers=headers)
    assert revoked.status_code==200,revoked.text
    assert client.post(f'/api/references/{approval}/revoke',json=body,headers=headers).json()==revoked.json()
    with pytest.raises(InvalidInput,match='revoked'):briefs.compile_reference_brief(str(project),'automatic-contract',0)
    with pytest.raises(InvalidInput,match='revoked'):J.submit_generation(str(project),prepared['brief'],[],'after-revocation')
    result=A.run_automatic(str(project),'faulty')
    assert result['status']=='blocked' and 'revoked' in result['blocker']
    eligibility=client.get('/api/eligibility/faulty').json()
    assert not eligibility['eligible'] and any('reference authority' in reason for reason in eligibility['reasons'])
    assert approval in client.get('/api/references').json()['revoked_approval_ids']
    # A newly approved unrelated guide cannot revive the old contract.
    guide=next(g for g in client.get('/api/references').json()['motion_guides'] if g['id']=='automatic-guide')
    guide['id']='unrelated-new-guide';path=tmp_path/'other.json';path.write_text(json.dumps(guide));cli(project,'guide-propose','--guide',str(path))
    assert client.post('/api/references/approve',json={'character_revision_id':'char','motion_guide_id':guide['id']},headers=headers).status_code==200
    with pytest.raises(InvalidInput,match='revoked'):A.compile_plan(str(project),'automatic-contract')


def test_review_event_replay_is_bound_to_roi_note_packet_and_actor(tmp_path,monkeypatch):
    project,client,headers,_,_=setup_work(tmp_path,monkeypatch)
    ev=cli(project,'clip-evaluate','--revision-id','faulty')
    cli(project,'packet-create','--packet-id','packet','--revision-id','faulty','--evaluation-id',ev['artifacts'][0]['id'])
    body={'id':'test-issue','clip_revision_id':'faulty','packet_id':'packet',
          'roi':{'left':0,'top':0,'right':1,'bottom':1},'frame_range':[0,3],'note':'test input'}
    first=client.post('/api/issues',json=body,headers=headers);assert first.status_code==201,first.text
    changed={**body,'note':'different intended fix','roi':{'left':0,'top':0,'right':20,'bottom':20}}
    assert client.post('/api/issues',json=changed,headers=headers).status_code==409
