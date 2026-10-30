import json
import subprocess
import sys

import pytest
from PIL import Image
from fastapi.testclient import TestClient

from framebound.v2 import storage as S
from framebound.v2.services.assets import import_asset
from framebound.v2.services.authz import Actor
from framebound.v2.services.errors import AuthorizationError
from framebound.v3.services import interventions as I, loop, tasks
from test_agent_loop import setup, import_frames

HUMAN=Actor(type='reviewer',id='alice')
AGENT=Actor(type='orchestrator',id='parent-agent')


def initial_mark(tmp_path, *, grant=False, failed=True):
    project,spec,good=setup(tmp_path)
    assets=import_frames(tmp_path,'bad',{'kind':'flicker'}) if failed else good
    loop.submit(project,'run','base',assets)
    payload=dict(id='hand',revision_id='base',evaluation_id='evaluation:base',
        desired_outcome='Restore the green costume pixels in frame 2; preserve the rest.',
        tick_range=[2,5],roi=dict(left=2,top=3,right=5,bottom=4),authorize_edit_scope=grant)
    mark=I.mark(project,HUMAN,'run',payload)
    return project,spec,good,assets,payload,mark


def test_saved_handoff_fresh_session_repairs_then_owner_resolves(tmp_path):
    project,_,good,_,payload,mark=initial_mark(tmp_path,grant=True)
    assert I.mark(project,HUMAN,'run',payload)==mark
    handoff=I.handoff(project,mark['handoff_id'])
    assert not handoff['stale']
    assert 'frames 2, ticks [2, 5)' in handoff['text']
    assert 'Restore the green costume' in handoff['text']
    assert 'outside' in handoff['text'] and 'sha256' in handoff['text']
    assert handoff['bundle']['continuation']['arguments']['feedback_id']==mark['handoff_id']
    submission=dict(run_id='run',revision_id='fixed',frame_asset_ids=good,
                    parent_revision_id='base',feedback_id=mark['handoff_id'])
    path=tmp_path/'submit.json';path.write_text(json.dumps(submission))
    result=subprocess.run([sys.executable,'-m','framebound','agent-run-submit','--project',project,'--submission',str(path)],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    feedback=json.loads(result.stdout)
    assert feedback['technical_status']=='pass' and feedback['disposition']=='awaiting_decision'
    assert not loop.eligibility(project,'run')['eligible']
    assert I.get(project,'hand')['correction']['status']=='awaiting_comparison'
    current=I.get(project,'hand')
    resolved=I.resolve(project,HUMAN,'hand',dict(expected_version=current['version'],revision_id='fixed',evaluation_id='evaluation:fixed',note='costume restored'))
    assert resolved['correction']['status']=='resolved'
    assert loop.get(project,'run')['lifecycle']=='completed'
    assert loop.get(project,'run')['creative_status']=='unreviewed'
    assert loop.eligibility(project,'run')['eligible']
    assert I.handoff(project,mark['handoff_id'])['stale']
    reopened=I.resolve(project,HUMAN,'hand',dict(expected_version=resolved['version'],revision_id='fixed',evaluation_id='evaluation:fixed',note='one more concern'),reopen=True)
    assert reopened['correction']['status']=='reopened'
    assert not loop.eligibility(project,'run')['eligible']


def test_scope_violation_recorded_and_full_matrix_rechecked(tmp_path):
    project,_,good,_,_,mark=initial_mark(tmp_path,grant=True)
    edited=Image.open(tmp_path/'good-1.png').convert('RGBA')
    edited.putpixel((0,0),(200,100,50,255))
    path=tmp_path/'outside.png';edited.save(path);import_asset(project,str(path),'outside')
    feedback=loop.submit(project,'run','outside', [good[0],'outside',good[2]],parent_revision_id='base',feedback_id=mark['handoff_id'])
    assert feedback['technical_status']=='fail'
    target=next(t for t in feedback['targets'] if t['check_id']=='edit-preservation-1')
    assert target['observed']==1
    assert loop.get(project,'run')['edit_baseline_revision_id']=='base'
    fixed=loop.submit(project,'run','fixed',good,parent_revision_id='outside',feedback_id=feedback['id'])
    assert fixed['technical_status']=='pass' and fixed['disposition']=='awaiting_decision'
    assert loop.get(project,'run')['edit_baseline_revision_id']=='fixed'


def test_markup_without_grant_does_not_implicitly_restrict_or_authorize_scope(tmp_path):
    project,_,good,_,_,mark=initial_mark(tmp_path,grant=False)
    target=next(t for t in mark['feedback']['targets'] if t['id']=='hand')
    assert target['edit_scope_authorized'] is False
    # Existing full-clip task permission remains the authority.
    feedback=loop.submit(project,'run','fixed',good,parent_revision_id='base',feedback_id=mark['handoff_id'])
    evaluation=loop.revision_get(project,'fixed')['evaluation']
    assert not any(r['family']=='edit_preservation' for r in evaluation['results'])
    assert feedback['disposition']=='awaiting_decision'


def test_agent_cannot_impersonate_owner_and_stale_saved_actions_reject(tmp_path):
    project,_,good,_,payload,mark=initial_mark(tmp_path)
    with pytest.raises(AuthorizationError):I.mark(project,AGENT,'run',dict(payload,id='fake'))
    with pytest.raises(S.StaleRevisionError):
        loop.submit(project,'run','stale',good,parent_revision_id='base',feedback_id='feedback:base')
    feedback=loop.submit(project,'run','fixed',good,parent_revision_id='base',feedback_id=mark['handoff_id'])
    with pytest.raises(S.StaleRevisionError):I.mark(project,HUMAN,'run',dict(payload,id='old-selection'))
    current=I.get(project,'hand')
    body=dict(expected_version=current['version'],revision_id='fixed',evaluation_id='evaluation:fixed')
    with pytest.raises(AuthorizationError):I.resolve(project,AGENT,'hand',body)
    with pytest.raises(AuthorizationError):I.resolve(project,Actor(type='reviewer',id='bob'),'hand',body)
    with pytest.raises(S.StaleRevisionError):I.resolve(project,HUMAN,'hand',dict(body,expected_version=1))
    rebase=I.rebase(project,HUMAN,mark['handoff_id'],expected_revision_id='fixed',expected_feedback_id=feedback['id'])
    assert rebase['baseline_revision_id']=='fixed'
    assert not I.handoff(project,rebase['id'])['stale']
    assert I.handoff(project,feedback['id'])['stale']


def test_exact_human_approval_is_separate_from_technical_success(tmp_path):
    project,spec,good=setup(tmp_path)
    spec['id']='review';spec['animation_id']='review';spec['completion']={'id':'human-reviewed-v1','creative_owner':'human'}
    tasks.create(project,spec);loop.start(project,'review','review')
    loop.submit(project,'review','ready',good)
    body=dict(id='approval',revision_id='ready',evaluation_id='evaluation:ready',action='approve',note='Reviewed exact result')
    with pytest.raises(AuthorizationError):I.decision(project,AGENT,'review',body)
    decision=I.decision(project,HUMAN,'review',body)
    assert I.decision(project,HUMAN,'review',body)==decision
    assert loop.get(project,'review')['lifecycle']=='completed'
    assert loop.get(project,'review')['creative_status']=='human_approved'
    assert loop.eligibility(project,'review')['eligible']
    assert decision['feedback']['creative_status']=='human_approved'


def test_reject_keeps_note_and_cannot_be_closed_by_automatic_pass(tmp_path):
    project,_,good=setup(tmp_path)
    loop.submit(project,'run','initial',good)
    decision=I.decision(project,HUMAN,'run',dict(id='reject',revision_id='initial',evaluation_id='evaluation:initial',action='needs_changes',note='The hand should read more clearly.'))
    target=next(t for t in decision['feedback']['targets'] if t['id']=='decision-task:reject')
    assert target['desired_outcome']=='The hand should read more clearly.'
    assert loop.get(project,'run')['creative_status']=='human_needs_changes'
    feedback=loop.submit(project,'run','retry',good,parent_revision_id='initial',feedback_id=decision['feedback']['id'])
    assert feedback['disposition']=='awaiting_decision' and feedback['creative_status']=='unreviewed'
    assert I.get(project,'decision-task:reject')['correction']['status']=='awaiting_comparison'


def test_http_saved_action_download_and_stale_handoff(tmp_path):
    from framebound.v2.api.app import create_app
    from framebound.v2.services.sessions import create_session
    project,_,good=setup(tmp_path)
    bad=import_frames(tmp_path,'bad',{'kind':'flicker'})
    loop.submit(project,'run','base',bad)
    client=TestClient(create_app(project))
    payload=dict(id='http-mark',revision_id='base',evaluation_id='evaluation:base',
        desired_outcome='Restore the green costume',tick_range=[2,5],
        roi=dict(left=2,top=3,right=5,bottom=4),authorize_edit_scope=True)
    assert client.post('/v3/runs/run/interventions',json=payload).status_code==403
    token=create_session(project,'alice')['session_token']
    headers={'X-Session-Token':token}
    response=client.post('/v3/runs/run/interventions',json=payload,headers=headers)
    assert response.status_code==200,response.text
    saved=response.json()
    handoff=client.get('/v3/feedback/'+saved['handoff_id']).json()
    assert not handoff['stale']
    download=client.get('/v3/feedback/'+saved['handoff_id']+'/text')
    assert download.text==handoff['text']
    assert download.headers['x-framebound-handoff-stale']=='false'
    assert 'attachment' in download.headers['content-disposition']
    fixed=client.post('/v3/runs/run/submissions',json=dict(revision_id='fixed',frame_asset_ids=good,
        parent_revision_id='base',feedback_id=saved['handoff_id']))
    assert fixed.status_code==200,fixed.text
    assert client.get('/v3/feedback/'+saved['handoff_id']).json()['stale']
    current=client.get('/v3/interventions/http-mark').json()
    resolution=client.post('/v3/interventions/http-mark/resolve',json=dict(expected_version=current['version'],
        revision_id='fixed',evaluation_id='evaluation:fixed',note='reviewed costume'),headers=headers)
    assert resolution.status_code==200,resolution.text
    assert resolution.json()['feedback']['disposition']=='complete'


def test_initial_generation_with_scoped_child_permission_and_explicit_review(tmp_path):
    project,spec,good=setup(tmp_path)
    spec['id']='scoped';spec['animation_id']='scoped';spec['repair_scope']='declared_regions';spec['intervention']='explicit_review'
    tasks.create(project,spec);loop.start(project,'scoped','scoped')
    first=loop.submit(project,'scoped','scoped-first',good)
    assert first['disposition']=='awaiting_decision'
    from framebound.v2.services.errors import InvalidInput
    with pytest.raises(InvalidInput,match='saved intervention grant'):
        loop.submit(project,'scoped','no-grant',good,parent_revision_id='scoped-first',feedback_id=first['id'])
    decision=I.decision(project,HUMAN,'scoped',dict(id='explicit-review',revision_id='scoped-first',evaluation_id='evaluation:scoped-first',action='approve'))
    assert decision['feedback']['disposition']=='complete'


def test_parent_judgment_does_not_close_human_correction_or_impersonate_approval(tmp_path):
    project,_,good,_,_,mark=initial_mark(tmp_path)
    feedback=loop.submit(project,'run','fixed',good,parent_revision_id='base',feedback_id=mark['handoff_id'])
    judgment=I.agent_satisfied(project,AGENT,'run',revision_id='fixed',evaluation_id='evaluation:fixed',note='The request is satisfied in my judgment.')
    assert judgment['event']['source']=='external_agent'
    assert judgment['feedback']['creative_status']=='agent_satisfied'
    assert loop.get(project,'run')['lifecycle']=='awaiting_decision'
    assert not loop.eligibility(project,'run')['eligible']
    assert I.get(project,'hand')['correction']['status']=='awaiting_comparison'
    con=loop.connect(project)
    assert not I.approved_in(con,'run','fixed','evaluation:fixed')
    con.close()
    with pytest.raises(AuthorizationError):I.agent_satisfied(project,HUMAN,'run',revision_id='fixed',evaluation_id='evaluation:fixed')


def test_technical_completion_selects_repaired_output_after_subjective_resolution(tmp_path):
    project,_,good=setup(tmp_path)
    loop.submit(project,'run','original',good)
    decision=I.decision(project,HUMAN,'run',dict(id='changes',revision_id='original',evaluation_id='evaluation:original',action='needs_changes',note='Clarify the gesture.'))
    bad=import_frames(tmp_path,'bad-costume',{'kind':'flicker'})
    failed=loop.submit(project,'run','gesture-fixed-costume-failed',bad,parent_revision_id='original',feedback_id=decision['feedback']['id'])
    mark=I.get(project,'decision-task:changes')
    resolved=I.resolve(project,HUMAN,mark['id'],dict(expected_version=mark['version'],revision_id='gesture-fixed-costume-failed',evaluation_id='evaluation:gesture-fixed-costume-failed',note='Gesture resolved; technical costume issue remains.'))
    final=loop.submit(project,'run','repaired',good,parent_revision_id='gesture-fixed-costume-failed',feedback_id=resolved['handoff_id'])
    assert final['disposition']=='complete' and final['best_revision_id']=='repaired'
    assert loop.eligibility(project,'run')['revision_id']=='repaired'
    assert final['creative_status']=='unreviewed'
