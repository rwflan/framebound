from fastapi.testclient import TestClient

from framebound.v2.api.app import create_app
from framebound.v3.services import desk,loop,tasks
from framebound.v3.services import interventions as I
from framebound.v2.services.authz import Actor
from test_agent_loop import setup,import_frames


def test_run_documentation_requires_no_packets_and_clean_unreviewed_is_not_intervention(tmp_path):
    project,_,good=setup(tmp_path)
    loop.submit(project,'run','good',good)
    data=desk.snapshot(project)
    assert len(data['runs'])==1
    assert not data['runs'][0]['needs_intervention']
    assert data['runs'][0]['creative_status']=='unreviewed'
    assert data['events'][-1]['revision_id']=='good'
    assert data['events'][-1]['source']=='framework'
    con=loop.connect(project)
    assert con.execute('SELECT count(*) FROM review_packets').fetchone()[0]==0
    con.close()
    client=TestClient(create_app(project))
    assert client.get('/v3/desk').json()==data
    bundle=client.get('/v3/desk/revisions/good').json()
    assert bundle['task']['id']=='task' and len(bundle['frames'])==3
    assert bundle['feedback']['disposition']=='complete'


def test_history_keeps_exact_revision_and_manual_intervention_source(tmp_path):
    project,_,good=setup(tmp_path)
    bad=import_frames(tmp_path,'bad',{'kind':'flicker'})
    loop.submit(project,'run','bad',bad)
    mark=I.mark(project,Actor(type='reviewer',id='human'),'run',dict(id='marked',revision_id='bad',
        evaluation_id='evaluation:bad',tick_range=[2,5],desired_outcome='fix the costume'))
    loop.submit(project,'run','fixed',good,parent_revision_id='bad',feedback_id=mark['handoff_id'])
    data=desk.snapshot(project)
    assert data['runs'][0]['needs_intervention']
    manual=next(e for e in data['events'] if e['event']=='mark_issue')
    assert manual['source']=='human' and manual['revision_id']=='bad'
    historical=desk.revision(project,manual['revision_id'])
    assert historical['evaluation']['technical_status']=='fail'
    assert historical['current_revision_id']=='fixed'
    assert historical['revision']['id']=='bad'
    assert historical['frames'][1]['asset_id']=='bad-1'
    assert desk.revision(project,'fixed')['evaluation']['technical_status']=='pass'


def test_cancelled_run_leaves_unresolved_work_in_history_without_actionable_queue(tmp_path):
    project,_,good=setup(tmp_path)
    bad=import_frames(tmp_path,'bad',{'kind':'flicker'});loop.submit(project,'run','bad',bad)
    I.mark(project,Actor(type='reviewer',id='human'),'run',dict(id='open',revision_id='bad',evaluation_id='evaluation:bad',tick_range=[0,2],desired_outcome='A subjective concern'))
    loop.cancel(project,'run','User stopped the run')
    data=desk.snapshot(project)
    assert data['runs'][0]['lifecycle']=='cancelled'
    assert not data['runs'][0]['needs_intervention']
    assert data['runs'][0]['interventions'][0]['correction']['status']=='open'
    assert data['events'][-1]['event']=='cancelled'
