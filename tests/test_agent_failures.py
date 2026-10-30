"""Parent reports persist without pretending to be provider receipts or pixel evidence."""
import asyncio
import json
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

from framebound.v2 import storage as S
from framebound.v2.api.app import create_app
from framebound.v2.exports import build_snapshot, validate_snapshot
from framebound.v2.mcp.server import build_server
from framebound.v2.services.errors import InvalidInput
from framebound.v3.services import failures as F, interventions as I, loop, tasks, desk
from test_agent_loop import setup, import_frames


def report(kind='provider_failure', **kw):
    return dict(id='attempt-1',kind=kind,reason='External attempt failed before usable pixels were returned.',outcome_known=True,**kw)


def test_initial_failure_replay_current_handoff_and_first_submission_binding(tmp_path):
    project,_,good=setup(tmp_path)
    payload=report('tool_error')
    saved=F.record(project,'run',payload)
    assert F.record(project,'run',payload)==saved
    run=loop.get(project,'run')
    assert run['external_failures']==1 and run['submission_ids']==[]
    assert run['feedback']['evaluation_id'] is None and run['feedback']['technical_status']=='unevaluated'
    assert desk.snapshot(project)['runs'][0]['needs_intervention']
    handoff=I.handoff(project,saved['feedback']['id'])
    assert not handoff['stale'] and 'No candidate has been registered' in handoff['text']
    assert 'not independent provider evidence' in handoff['text']
    with pytest.raises(S.ConflictError):F.record(project,'run',dict(payload,reason='different'))
    with pytest.raises(S.StaleRevisionError):loop.submit(project,'run','unbound',good)
    completed=loop.submit(project,'run','first',good,feedback_id=saved['feedback']['id'])
    assert completed['disposition']=='complete'
    assert I.handoff(project,saved['feedback']['id'])['stale']
    assert F.record(project,'run',payload)==saved
    with pytest.raises(InvalidInput):F.record(project,'run',dict(payload,id='new'))


@pytest.mark.parametrize('kind,limits,count',[('provider_failure',{'max_provider_failures':2},2),('tool_error',{'max_external_failures':2},2)])
def test_failures_stop_across_restarts_and_no_alias_or_task_budget_reset(tmp_path,kind,limits,count):
    project,spec,good=setup(tmp_path,limits=limits)
    for index in range(count):F.record(project,'run',dict(report(kind),id=str(index)))
    run=loop.get(project,'run')
    assert run['external_failures']==count and run['lifecycle']=='blocked'
    assert run['feedback']['continuation']['submission_allowed'] is False
    with pytest.raises(InvalidInput):loop.submit(project,'run','pixels',good,feedback_id=run['feedback']['id'])
    with pytest.raises(S.ConflictError):loop.start(project,'task','new-name')
    spec.update(id='new-task',supersedes='task',change_reason='Cannot reset a spent budget')
    tasks.create(project,spec)
    with pytest.raises(InvalidInput,match='persistent external-failure'):loop.revise_task(project,'run','new-task',run['version'])


def test_unknown_provider_outcome_stops_without_redispatch_and_cannot_retask(tmp_path):
    project,spec,_=setup(tmp_path)
    saved=F.record(project,'run',dict(report(),outcome_known=False,external_request_id='receipt-unknown'))
    run=loop.get(project,'run')
    assert run['blocker_kind']=='provider_outcome_unknown' and run['lifecycle']=='blocked'
    assert 'do not blindly redispatch' in run['stop_reason']
    assert saved['event']['source']=='external_agent'
    spec.update(id='new-task',supersedes='task',change_reason='New evidence needed')
    tasks.create(project,spec)
    with pytest.raises(InvalidInput,match='unknown provider outcome'):loop.revise_task(project,'run','new-task',run['version'])
    assert 'stopped' in I.handoff(project,saved['feedback']['id'])['text']
    loop.cancel(project,'run','No provider retry authorized')
    current=loop.get(project,'run')['feedback']
    assert current['reason']=='No provider retry authorized' and current['continuation']['submission_allowed'] is False
    assert I.handoff(project,saved['feedback']['id'])['stale']


def test_failure_after_candidate_keeps_evaluation_and_human_tasks(tmp_path):
    project,_,good=setup(tmp_path)
    bad=import_frames(tmp_path,'bad',{'kind':'flicker'})
    old=loop.submit(project,'run','bad',bad)
    saved=F.record(project,'run',report())
    assert saved['feedback']['evaluation_id']==old['evaluation_id']
    assert saved['feedback']['evidence_digest']==old['evidence_digest']
    assert saved['feedback']['continuation']['arguments']['feedback_id']==saved['feedback']['id']
    with pytest.raises(S.StaleRevisionError):loop.submit(project,'run','stale',good,parent_revision_id='bad',feedback_id=old['id'])
    fixed=loop.submit(project,'run','fixed',good,parent_revision_id='bad',feedback_id=saved['feedback']['id'])
    assert fixed['disposition']=='complete' and loop.get(project,'run')['provider_failures']==1


@pytest.mark.parametrize('cancel',[False,True])
def test_pre_submission_retask_history_and_reports_are_portable(tmp_path,cancel):
    project,spec,good=setup(tmp_path)
    saved=F.record(project,'run',report('missing_input'))
    spec.update(id='new-task',supersedes='task',change_reason='Clarify available generation inputs')
    tasks.create(project,spec);loop.revise_task(project,'run','new-task',loop.get(project,'run')['version'])
    feedback=loop.get(project,'run')['feedback']
    assert feedback['task_id']=='task' and feedback['next_task_id']=='new-task'
    assert feedback['continuation']['arguments']['task_id']=='new-task'
    assert '--task-id new-task;' in I.handoff(project,feedback['id'])['text']
    assert I.handoff(project,saved['feedback']['id'])['stale']
    bad=import_frames(tmp_path,'bad',{'kind':'flicker'})
    loop.submit(project,'run','bad',bad,feedback_id=feedback['id'])
    if cancel:loop.cancel(project,'run','Keep failed attempt for research')
    out=tmp_path/'snapshot'
    manifest=build_snapshot(project,'failures',['bad'],str(out),{'include_procedural_positives':True})
    assert 'pre-submission-feedback-v1' in manifest['reader_capabilities']
    result=validate_snapshot(str(out));assert result['ok'],result['issues']
    events=[json.loads(line) for line in (out/'closure/events.jsonl').read_text().splitlines()]
    assert any(e.get('report')==saved['event']['report'] for e in events)
    assert not any(e['source']=='human' for e in events)


def test_failure_public_transports_use_same_saved_service(tmp_path):
    project,_,_=setup(tmp_path)
    path=tmp_path/'failure.json';payload=report();path.write_text(json.dumps(payload))
    completed=subprocess.run([sys.executable,'-m','framebound','agent-run-report-failure','--project',project,'--run-id','run','--report',str(path)],capture_output=True,text=True)
    assert completed.returncode==0,completed.stderr
    saved=json.loads(completed.stdout)
    client=TestClient(create_app(project))
    replay=client.post('/v3/runs/run/failures',json=payload)
    assert replay.status_code==200 and replay.json()==saved
    assert client.get('/v3/feedback/'+saved['feedback']['id']).json()['stale'] is False
    assert client.post('/v3/runs/run/failures',json=dict(payload,outcome_known='yes')).status_code==422
    assert 'agent_run_report_failure' in {tool.name for tool in asyncio.run(build_server(project).list_tools())}


def test_human_decision_does_not_clear_unknown_provider_outcome(tmp_path):
    from framebound.v2.services.authz import Actor
    project,spec,good=setup(tmp_path)
    spec.update(id='review-task',supersedes='task',change_reason='Request an exact decision',intervention='explicit_review')
    tasks.create(project,spec);loop.revise_task(project,'run','review-task',loop.get(project,'run')['version'])
    initial=loop.submit(project,'run','first',good)
    assert initial['disposition']=='awaiting_decision'
    F.record(project,'run',dict(report(),outcome_known=False))
    decision=I.decision(project,Actor(type='reviewer',id='actual-reviewer'),'run',dict(id='quality-approval',revision_id='first',evaluation_id='evaluation:first',action='approve'))
    assert decision['feedback']['disposition']=='blocked'
    run=loop.get(project,'run')
    assert run['creative_status']=='human_approved' and run['lifecycle']=='blocked'
    assert not loop.eligibility(project,'run')['eligible']


def test_lowered_failure_budget_stops_at_retained_spending(tmp_path):
    project,spec,good=setup(tmp_path)
    F.record(project,'run',report())
    spec.update(id='new-task',supersedes='task',change_reason='Reduce external failure budget',limits={'max_provider_failures':1})
    tasks.create(project,spec)
    run=loop.revise_task(project,'run','new-task',loop.get(project,'run')['version'])
    assert run['lifecycle']=='blocked' and run['provider_failures']==1
    with pytest.raises(InvalidInput):loop.submit(project,'run','first',good,feedback_id=run['feedback_id'])
