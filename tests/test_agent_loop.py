"""Procedural engineering benchmark, not a claim about arbitrary generated art."""
from concurrent.futures import ThreadPoolExecutor

import pytest
from PIL import Image

from framebound.v2 import storage as S
from framebound.v2.services.assets import import_asset
from framebound.v2.services.projects import create_project
from framebound.v2.services.errors import InvalidInput
from framebound.v3.services import tasks, loop


def setup(tmp_path, *, profile='fixed-subject-v1', limits=None, faults=None):
    project = str(tmp_path)
    create_project(project, {'id': 'p'})
    regions, temporal = [], []
    for slot in range(3):
        for family, rgba, minimum, maximum, roi in [
            ('feature', [255, 0, 0, 255], 1, 1, [0, 0, 8, 8]),
            ('appearance', [0, 255, 0, 255], 3, 3, [0, 2, 8, 5]),
            ('contact', [0, 0, 255, 255], 2, 2, [0, 7, 8, 8])]:
            regions.append(dict(id=f'{family}-{slot}', family=family, slot=slot,
                roi=dict(zip(('left','top','right','bottom'),roi)), rgba=rgba,
                minimum=minimum, maximum=maximum, provenance='procedural declared event fixture', source='procedural'))
    for left, right in [(0,1),(1,2)]:
        temporal.append(dict(id=f'continuity-{left}', family='continuity', left_slot=left, right_slot=right,
            left_region_id=f'feature-{left}', right_region_id=f'feature-{right}', max_distance_px=1.2,
            provenance='authored controlled feature path', source='procedural'))
        temporal.append(dict(id=f'moving-{left}', family='moving', left_slot=left, right_slot=right,
            provenance='authored moving interval', source='procedural'))
    temporal.append(dict(id='loop', family='loop', left_slot=2, right_slot=0,
        left_region_id='feature-2', right_region_id='feature-0', max_distance_px=0,
        provenance='authored loop anchor', source='procedural'))
    spec = dict(id='task', project_id='p', animation_id='a', intent='A red feature sways above planted blue feet',
                subjects='one procedural subject', canvas={'width':8,'height':8}, timing={'holds':[2,3,2]},
                profile=profile, region_observations=regions, temporal_observations=temporal,
                preserve=['authored timing', 'blue contact'], allowed_changes=['whole clip'])
    if limits:
        spec['limits'] = limits
    tasks.create(project, spec)
    loop.start(project, 'task', 'run')
    return project, spec, import_frames(tmp_path, 'good', faults or {})


def import_frames(tmp_path, prefix, faults=None):
    faults = faults or {}
    images = []
    for slot, x in enumerate([1,2,1]):
        image = Image.new('RGBA',(8,8))
        for greenx in [2,3,4]:
            image.putpixel((greenx,3),(0,255,0,255))
        for bluex in [3,4]:
            image.putpixel((bluex,7),(0,0,255,255))
        image.putpixel((x,1),(255,0,0,255))
        # Legitimate pose deformation is outside constrained costume regions.
        image.putpixel((slot+1,5),(80,80,80,255))
        images.append(image)
    fault = faults.get('kind')
    if fault == 'disappearance': images[1].putpixel((2,1),(0,0,0,0))
    if fault == 'duplication': images[1].putpixel((3,1),(255,0,0,255))
    if fault == 'flicker': images[1].putpixel((3,3),(200,0,200,255))
    if fault == 'discontinuity':
        images[1].putpixel((2,1),(0,0,0,0)); images[1].putpixel((6,1),(255,0,0,255))
    if fault == 'contact': images[1].putpixel((3,7),(0,0,0,0))
    if fault == 'repeated': images[1]=images[0].copy()
    if fault == 'loop':
        images[2].putpixel((1,1),(0,0,0,0)); images[2].putpixel((2,1),(255,0,0,255))
    ids=[]
    for i,image in enumerate(images):
        aid=f'{prefix}-{i}'; path=tmp_path/f'{aid}.png'; image.save(path)
        import_asset(str(tmp_path),str(path),aid,source_kind='procedural')
        ids.append(aid)
    return ids


@pytest.mark.parametrize('fault,expected', [('disappearance','feature-1'),('duplication','feature-1'),
    ('flicker','appearance-1'),('discontinuity','continuity-0'),('contact','contact-1'),
    ('repeated','moving-0'),('loop','loop')])
def test_localized_fail_repair_pass_and_restart(tmp_path, fault, expected):
    project, _, good = setup(tmp_path)
    bad = import_frames(tmp_path,'bad',{'kind':fault})
    feedback = loop.submit(project,'run','bad',bad)
    assert feedback['technical_status'] == 'fail'
    target = next(t for t in feedback['targets'] if t['check_id']==expected)
    assert target['display_numbers'] and target['tick_range'] and target['evidence_assets']
    assert target['desired_outcome'] and target['coordinate_space']=='native_px'
    assert loop.get(project,'run')['feedback']==feedback
    repaired = loop.submit(project,'run','fixed',good,parent_revision_id='bad',feedback_id=feedback['id'])
    assert repaired['disposition']=='complete'
    assert repaired['creative_status']=='unreviewed'
    assert repaired['best_revision_id']=='fixed'
    assert loop.submit(project,'run','fixed',good,parent_revision_id='bad',feedback_id=feedback['id'])==repaired
    assert len(loop.get(project,'run')['submission_ids'])==2


def test_required_gap_prevents_completion_and_policy_weakening(tmp_path):
    project,spec,good=setup(tmp_path,profile='structural-v1')
    spec['id']='prose-action';spec['animation_id']='b'
    spec['requirements']=[dict(id='action',check='arbitrary_action',desired_outcome='wave correctly')]
    tasks.create(project,spec);loop.start(project,'prose-action','other')
    feedback=loop.submit(project,'other','unmeasured',good)
    assert feedback['technical_status']=='incomplete' and feedback['disposition']!='complete'
    with pytest.raises(S.ConflictError):loop.start(project,'prose-action','budget-reset')
    changed=dict(spec);changed['requirements']=[]
    with pytest.raises(S.ConflictError):tasks.create(project,changed)


def test_bounded_oscillation_best_and_stale_submissions(tmp_path):
    project,_,good=setup(tmp_path,limits={'max_submissions':8,'max_unchanged':2})
    first=import_frames(tmp_path,'a',{'kind':'flicker'})
    second=import_frames(tmp_path,'b',{'kind':'disappearance'})
    previous=None
    for i,assets in enumerate([first,second,first,second]):
        feedback=loop.submit(project,'run',f'r{i}',assets,parent_revision_id=previous,
                             feedback_id=f'feedback:{previous}' if previous else None)
        previous=f'r{i}'
    run=loop.get(project,'run')
    assert run['lifecycle']=='blocked' and run['best_revision_id']=='r0'
    assert feedback['regressions']
    with pytest.raises(InvalidInput,match='blocked'):loop.submit(project,'run','r4',good,parent_revision_id='r3',feedback_id='feedback:r3')
    assert loop.start(project,'task','run')['limits']['max_submissions']==8


def test_simultaneous_submissions_have_single_winner(tmp_path):
    project,_,_=setup(tmp_path)
    bad=import_frames(tmp_path,'bad',{'kind':'flicker'})
    def submit(name):
        try:return loop.submit(project,'run',name,bad)
        except S.StaleRevisionError:return 'stale'
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(submit,['a','b']))
    assert results.count('stale')==1
    assert len(loop.get(project,'run')['submission_ids'])==1


def test_unreadable_is_tool_error_not_redraw(tmp_path):
    project,_,good=setup(tmp_path)
    con=S.connect(project)
    asset,_=S.get(con,'assets',good[1]);con.close()
    S.blob_path(project,asset['byte_sha256']).unlink()
    feedback=loop.submit(project,'run','broken',good)
    assert feedback['technical_status']=='error'
    assert next(t for t in feedback['targets'] if t['check_id']=='media-1')['suggested_operation']=='recover_media_or_evidence'


def test_correct_hold_occlusion_and_pose_changes_are_not_defects(tmp_path):
    project,spec,good=setup(tmp_path)
    # A separately frozen task declares a hold and an occluded feature.
    spec['id']='counterexamples';spec['animation_id']='counterexamples'
    spec['temporal_observations']=[t for t in spec['temporal_observations']
                                  if t['family']=='loop' or t['id']=='moving-1']
    for r in spec['region_observations']:
        if r['family']=='feature' and r['slot']==1:r['visibility']='occluded'
    tasks.create(project,spec);loop.start(project,'counterexamples','counterexamples')
    # Maintain other independent checks; occluded feature measurement is explicitly exempt.
    result=loop.submit(project,'counterexamples','valid-counterexample',good)
    # Continuity was deliberately omitted, so the profile cannot claim complete quality coverage.
    assert result['technical_status']=='incomplete'
    con=loop.connect(project)
    evaluation=loop.get_in(con,'agent_evaluations','evaluation:valid-counterexample');con.close()
    assert next(r for r in evaluation['results'] if r['id']=='feature-1')['outcome']=='not_applicable'
    assert all(r['outcome']!='fail' for r in evaluation['results'])


def test_atomic_failure_rolls_back_frames_and_budget(tmp_path,monkeypatch):
    project,_,good=setup(tmp_path)
    original=loop.insert
    def crash(con,table,record):
        if table=='agent_feedback':raise RuntimeError('simulated process failure before commit')
        return original(con,table,record)
    monkeypatch.setattr(loop,'insert',crash)
    with pytest.raises(RuntimeError):loop.submit(project,'run','crashed',good)
    assert loop.get(project,'run')['submission_ids']==[]
    con=loop.connect(project)
    assert con.execute("SELECT count(*) FROM frame_instances WHERE json_extract(data, '$.clip_revision_id')='crashed'").fetchone()[0]==0
    con.close()
    monkeypatch.setattr(loop,'insert',original)
    assert loop.submit(project,'run','crashed',good)['disposition']=='complete'


def test_http_and_cli_journey(tmp_path):
    import json, subprocess, sys
    from fastapi.testclient import TestClient
    from framebound.v2.api.app import create_app
    project,_,good=setup(tmp_path)
    bad=import_frames(tmp_path,'bad',{'kind':'contact'})
    client=TestClient(create_app(project))
    response=client.post('/v3/runs/run/submissions',json={'revision_id':'bad','frame_asset_ids':bad})
    assert response.status_code==200,response.text
    submission=tmp_path/'submission.json'
    submission.write_text(json.dumps(dict(run_id='run',revision_id='fixed',frame_asset_ids=good,
        parent_revision_id='bad',feedback_id=response.json()['id'])))
    repaired=subprocess.run([sys.executable,'-m','framebound','agent-run-submit','--project',project,
                             '--submission',str(submission)],capture_output=True,text=True)
    assert repaired.returncode==0,repaired.stderr
    assert json.loads(repaired.stdout)['disposition']=='complete'
    assert client.get('/v3/runs/run').json()['creative_status']=='unreviewed'


def test_automatic_eligibility_is_fresh_and_never_human_approval(tmp_path):
    project,_,good=setup(tmp_path)
    loop.submit(project,'run','good',good)
    result=loop.eligibility(project,'run')
    assert result['eligible'] and result['creative_status']=='unreviewed'
    con=S.connect(project);asset,_=S.get(con,'assets',good[0]);con.close()
    path=S.blob_path(project,asset['byte_sha256']);data=path.read_bytes();path.unlink()
    assert not loop.eligibility(project,'run')['eligible']
    path.write_bytes(data)
    assert loop.eligibility(project,'run')['eligible']


def test_declared_hold_passes_without_destroying_intended_motion(tmp_path):
    project,spec,good=setup(tmp_path)
    spec['id']='held';spec['animation_id']='held'
    spec['temporal_observations']=[t for t in spec['temporal_observations'] if t['id']!='moving-0']
    tasks.create(project,spec);loop.start(project,'held','held')
    feedback=loop.submit(project,'held','hold-good',[good[0],good[0],good[2]])
    assert feedback['disposition']=='complete'


def test_optional_alias_cannot_weaken_required_media_check(tmp_path):
    project,spec,good=setup(tmp_path)
    spec['id']='alias';spec['animation_id']='alias'
    spec['requirements']=[dict(id='optional-media-alias',check='media',required=False,desired_outcome='optional alias')]
    tasks.create(project,spec);loop.start(project,'alias','alias')
    blank=tmp_path/'blank.png';Image.new('RGBA',(8,8)).save(blank)
    import_asset(project,str(blank),'blank',source_kind='procedural')
    feedback=loop.submit(project,'alias','blank-revision',['blank',good[1],good[2]])
    assert feedback['technical_status']=='error'
    assert feedback['disposition']!='complete'


def test_cancel_and_pixel_budget_survive_restart(tmp_path):
    project,_,good=setup(tmp_path,limits={'max_evaluation_pixels':64})
    with pytest.raises(InvalidInput,match='pixel budget'):loop.submit(project,'run','too-large',good)
    assert loop.get(project,'run')['submission_ids']==[]
    assert loop.cancel(project,'run','user stopped')['lifecycle']=='cancelled'
    assert loop.get(project,'run')['stop_reason']=='user stopped'
    with pytest.raises(InvalidInput,match='cancelled'):loop.submit(project,'run','late',good)


def test_human_policy_cannot_bypass_submission_budget(tmp_path):
    project,spec,good=setup(tmp_path)
    spec['id']='reviewed';spec['animation_id']='reviewed'
    spec['limits']={'max_submissions':1}
    spec['completion']={'id':'human-reviewed-v1','creative_owner':'human'}
    tasks.create(project,spec);loop.start(project,'reviewed','reviewed')
    feedback=loop.submit(project,'reviewed','pending-review',good)
    assert feedback['disposition']=='awaiting_decision'
    assert not loop.eligibility(project,'reviewed')['eligible']
    with pytest.raises(InvalidInput,match='budget exhausted'):
        loop.submit(project,'reviewed','over-budget',good,parent_revision_id='pending-review',feedback_id=feedback['id'])


def test_real_process_death_rolls_back_and_replays(tmp_path):
    import json,os,subprocess,sys
    project,_,good=setup(tmp_path)
    script='''
import json,os,sys
from framebound.v3.services import loop
original=loop.insert
def die(con,table,record):
    if table=='agent_feedback': os._exit(73)
    return original(con,table,record)
loop.insert=die
loop.submit(sys.argv[1],'run','killed',json.loads(sys.argv[2]))
'''
    result=subprocess.run([sys.executable,'-c',script,project,json.dumps(good)])
    assert result.returncode==73
    assert loop.get(project,'run')['submission_ids']==[]
    feedback=loop.submit(project,'run','killed',good)
    assert feedback['disposition']=='complete'
    assert loop.revision_get(project,'killed')['evaluation']['evidence_digest']==feedback['evidence_digest']


def test_related_symptoms_group_without_discarding_checks_or_turning_defect_into_tool_error(tmp_path):
    project,_,_=setup(tmp_path)
    bad=import_frames(tmp_path,'bad',{'kind':'disappearance'})
    feedback=loop.submit(project,'run','absent',bad)
    assert feedback['bundle_version']==2
    target_ids={t['id'] for t in feedback['targets']}
    assert {tid for group in feedback['correction_groups'] for tid in group['target_ids']}==target_ids
    dependent=next(t for t in feedback['targets'] if t['check_id']=='continuity-0')
    assert dependent['outcome']=='unmeasured'
    assert dependent['depends_on_check_ids']==['feature-1']
    assert dependent['suggested_operation']=='restore_failed_visible_feature_then_remeasure'
    assert any(group['category']=='candidate_defect' and {'feature-1','continuity-0','continuity-1'}<=set(group['verification_checks']) for group in feedback['correction_groups'])
