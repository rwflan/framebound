import pytest
from framebound.v2 import storage as S
from framebound.v2.services.errors import InvalidInput
from framebound.v3.services import tasks,loop,interventions as I
from test_agent_loop import setup,import_frames


def test_explicit_task_revision_preserves_limits_history_and_truthful_bindings(tmp_path):
    project,spec,good=setup(tmp_path)
    bad=import_frames(tmp_path,'bad',{'kind':'flicker'})
    first=loop.submit(project,'run','bad',bad)
    spec['id']='revised';spec['supersedes']='task';spec['change_reason']='Make the authored requested action more explicit.'
    spec['limits']={'max_submissions':100,'max_unchanged':50}
    tasks.create(project,spec)
    before=loop.get(project,'run')
    run=loop.revise_task(project,'run','revised',before['version'])
    assert run['limits']['max_submissions']==8 and run['limits']['max_unchanged']==2
    assert run['submission_ids']==['bad'] and run['fingerprints']==before['fingerprints']
    assert run['best_by_task']['task']=='bad' and run['best_revision_id'] is None
    feedback=loop.get(project,'run')['feedback']
    assert feedback['task_id']=='task' and feedback['next_task_id']=='revised'
    assert feedback['evaluation_id']=='evaluation:bad' and feedback['disposition']=='continue'
    assert not I.handoff(project,feedback['id'])['stale']
    with pytest.raises(S.StaleRevisionError):loop.submit(project,'run','stale',good,parent_revision_id='bad',feedback_id=first['id'])
    fixed=loop.submit(project,'run','fixed',good,parent_revision_id='bad',feedback_id=feedback['id'])
    assert fixed['disposition']=='complete' and fixed['task_id']=='revised'
    assert loop.get(project,'run')['best_revision_id']=='fixed'


def test_cancelled_handoff_is_a_durable_stop_and_supersedes_continuation(tmp_path):
    project,_,_=setup(tmp_path)
    bad=import_frames(tmp_path,'bad',{'kind':'flicker'})
    old=loop.submit(project,'run','bad',bad)
    loop.cancel(project,'run','Stop this request.')
    run=loop.get(project,'run');feedback=run['feedback']
    assert feedback['disposition']=='blocked' and feedback['reason']=='Stop this request.'
    assert I.handoff(project,old['id'])['stale']
    assert not I.handoff(project,feedback['id'])['stale']
    assert loop.cancel(project,'run','ignored replay')['lifecycle']=='cancelled'


def test_task_revision_cannot_reset_exhausted_or_cancelled_run(tmp_path):
    project,spec,_=setup(tmp_path,limits={'max_submissions':1})
    bad=import_frames(tmp_path,'bad',{'kind':'flicker'});loop.submit(project,'run','bad',bad)
    spec['id']='revised';spec['supersedes']='task';spec['change_reason']='Need another attempt'
    tasks.create(project,spec)
    with pytest.raises(InvalidInput,match='persistent run limit'):loop.revise_task(project,'run','revised',loop.get(project,'run')['version'])


def test_task_revision_and_cancel_feedback_remain_portable(tmp_path):
    from framebound.v2.exports import build_snapshot,validate_snapshot
    project,spec,good=setup(tmp_path)
    bad=import_frames(tmp_path,'bad',{'kind':'flicker'});loop.submit(project,'run','bad',bad)
    spec['id']='revised';spec['supersedes']='task';spec['change_reason']='Clarified intent'
    tasks.create(project,spec);loop.revise_task(project,'run','revised',loop.get(project,'run')['version'])
    loop.cancel(project,'run','Stop before next candidate')
    feedback=loop.get(project,'run')['feedback']
    assert feedback['task_id']=='task' and feedback['next_task_id']=='revised'
    assert feedback['continuation']['submission_allowed'] is False
    out=tmp_path/'snapshot'
    build_snapshot(project,'pending-task',['bad'],str(out),{'include_procedural_positives':True})
    report=validate_snapshot(str(out));assert report['ok'],report['issues']


def test_task_revision_validates_version_and_retains_open_human_scope(tmp_path):
    from framebound.v2.services.authz import Actor
    project,spec,good=setup(tmp_path)
    bad=import_frames(tmp_path,'bad',{'kind':'flicker'});loop.submit(project,'run','bad',bad)
    I.mark(project,Actor(type='reviewer',id='human'),'run',dict(id='mark',revision_id='bad',evaluation_id='evaluation:bad',tick_range=[2,5],desired_outcome='Fix costume'))
    spec['id']='revised';spec['supersedes']='task';spec['change_reason']='Different timing';spec['timing']['holds']=[3,3,3]
    tasks.create(project,spec)
    version=loop.get(project,'run')['version']
    with pytest.raises(S.StaleRevisionError):loop.revise_task(project,'run','revised',version-1)
    with pytest.raises(InvalidInput,match='saved human scope'):loop.revise_task(project,'run','revised',version)


def test_completion_continuation_checks_eligibility_and_revised_task_can_resume(tmp_path):
    project,spec,good=setup(tmp_path)
    complete=loop.submit(project,'run','good',good)
    assert complete['continuation']==dict(operation='agent_run_eligibility',arguments={'run_id':'run'},submission_allowed=False)
    assert 'Before delivery' in I.handoff(project,complete['id'])['text']
    spec['id']='next-task';spec['supersedes']='task';spec['change_reason']='Explicit subsequent task revision'
    tasks.create(project,spec)
    loop.revise_task(project,'run','next-task',loop.get(project,'run')['version'])
    feedback=loop.get(project,'run')['feedback']
    assert feedback['continuation']['operation']=='agent_run_submit'
    assert feedback['continuation']['arguments']['parent_revision_id']=='good'
    assert loop.submit(project,'run','next',good,parent_revision_id='good',feedback_id=feedback['id'])['disposition']=='complete'
