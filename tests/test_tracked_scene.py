"""Independent procedural scene cases; no generated-art reliability claim."""
import pytest
from PIL import Image
from framebound.v2.services.projects import create_project
from framebound.v2.services.assets import import_asset
from framebound.v3.services import tasks,loop


def scene_task(tmp_path,kind=None):
    project=str(tmp_path);create_project(project,{'id':'p'})
    camera=[];features=[];events=[];links=[];good=[]
    # Distinct camera shifts/scales, a legitimate occlusion and two interacting subjects.
    transforms=[(0,0,1),(2,1,2),(1,2,1)]
    for slot,(tx,ty,scale) in enumerate(transforms):
        camera.append(dict(slot=slot,translation=[tx,ty],scale=scale,source='procedural',provenance='authored camera path'))
        image=Image.new('RGBA',(24,24))
        for subject,color,point in [('hand',[255,0,0,255],(2+slot,3)),('prop',[0,0,255,255],(4,3))]:
            visible=not (subject=='hand' and slot==2)
            if visible:
                x,y=point[0]*scale+tx,point[1]*scale+ty
                if kind=='jump' and subject=='hand' and slot==1:x+=6
                if kind=='wrong_event' and subject=='prop' and slot==1:x+=2
                if kind=='missing' and subject=='prop' and slot==0:pass
                else:image.putpixel((x,y),tuple(color))
                if kind=='duplicated' and subject=='hand' and slot==0:image.putpixel((x+1,y),tuple(color))
            features.append(dict(id=f'{subject}-{slot}',subject_id=subject,slot=slot,
                roi=dict(left=0,top=0,right=24,bottom=24),rgba=color,expected_world=list(point),max_error_world=1.1,
                minimum_pixels=1,maximum_pixels=1,visibility='visible' if visible else 'occluded',
                source='procedural',provenance='independently authored subject trajectory'))
        aid=f'frame-{slot}';path=tmp_path/f'{aid}.png';image.save(path);import_asset(project,str(path),aid,source_kind='procedural');good.append(aid)
    events=[dict(id='touch',kind='contact',left_feature_id='hand-1',right_feature_id='prop-1',distance_world=1,
                 source='procedural',provenance='authored contact at tick 3'),
            dict(id='order',kind='left_of',left_feature_id='hand-0',right_feature_id='prop-0',distance_world=0.5,
                 source='procedural',provenance='hand begins left of prop')]
    links=[dict(id='hand-motion',left_feature_id='hand-0',right_feature_id='hand-1',max_displacement_world=1.1),
           dict(id='occluded-link',left_feature_id='hand-1',right_feature_id='hand-2',max_displacement_world=2,required=False)]
    spec=dict(id='scene',project_id='p',animation_id='interaction',intent='The hand reaches the prop, then is occluded; the camera translates and zooms.',subjects='hand and prop',
        profile='tracked-scene-v1',canvas=dict(width=24,height=24),timing=dict(holds=[3,4,3]),loop=False,
        scene=dict(subjects=['hand','prop'],camera=camera,features=features,links=links,events=events))
    return project,spec,good


def test_correct_camera_motion_scale_and_occlusion_pass_with_declared_limits(tmp_path):
    project,spec,frames=scene_task(tmp_path)
    task=tasks.create(project,spec);assert all(r['applicability']=='supported' for r in task['requirements'])
    loop.start(project,'scene','run');feedback=loop.submit(project,'run','correct',frames)
    assert feedback['disposition']=='complete'
    evaluation=loop.revision_get(project,'correct')['evaluation']
    occluded=next(r for r in evaluation['results'] if r['id']=='scene:hand-2')
    assert occluded['outcome']=='not_applicable'
    advisory=next(r for r in evaluation['results'] if r['id']=='scene:occluded-link')
    assert advisory['outcome']=='unmeasured' and advisory['required'] is False
    assert 'semantics unverified' in loop.eligibility(project,'run')['quality_scope']
    assert evaluation['evidence']['scene']['camera'][1]['scale']==2


@pytest.mark.parametrize('kind,expected',[('jump','scene:hand-1'),('wrong_event','scene:touch'),('missing','scene:prop-0'),('duplicated','scene:hand-0')])
def test_faults_are_localized_in_camera_compensated_scene(tmp_path,kind,expected):
    project,spec,frames=scene_task(tmp_path,kind)
    tasks.create(project,spec);loop.start(project,'scene','run')
    feedback=loop.submit(project,'run','fault',frames)
    target=next(t for t in feedback['targets'] if t['check_id']==expected)
    assert target['outcome']=='fail' and target['slots'] and target['evidence_assets']
    assert feedback['technical_status']=='fail' and feedback['disposition']!='complete'


def test_absent_scene_measurements_remain_unsupported_and_ambiguous_blocks(tmp_path):
    project,spec,frames=scene_task(tmp_path)
    original=dict(spec);original['scene']=None
    record=tasks.create(project,original)
    assert sum(r['applicability']=='unsupported' for r in record['requirements'])==3
    spec['id']='ambiguous';spec['animation_id']='ambiguous';spec['scene']['features'][0]['visibility']='ambiguous'
    tasks.create(project,spec);loop.start(project,'ambiguous','run')
    feedback=loop.submit(project,'run','ambiguous',frames)
    assert feedback['disposition']=='awaiting_input' and feedback['technical_status']=='incomplete'


def test_scene_repair_passes_and_moved_export_reproduces_evidence(tmp_path):
    import shutil
    from framebound.v2.exports import build_snapshot,validate_snapshot
    source=tmp_path/'project';source.mkdir();project,spec,bad=scene_task(source,'wrong_event')
    tasks.create(project,spec);loop.start(project,'scene','run');failed=loop.submit(project,'run','wrong',bad)
    # Build independent corrected pixels at distinct asset IDs; task assumptions stay frozen.
    for i,aid in enumerate(bad):
        path=source/f'{aid}.png'
        im=Image.open(path).convert('RGBA')
        if i==1:
            im.putpixel((12,7),(0,0,0,0));im.putpixel((10,7),(0,0,255,255))
        corrected=source/f'corrected-{i}.png';im.save(corrected);import_asset(project,str(corrected),f'corrected-{i}',source_kind='procedural')
    repaired=loop.submit(project,'run','fixed',[f'corrected-{i}' for i in range(3)],parent_revision_id='wrong',feedback_id=failed['id'])
    assert repaired['disposition']=='complete'
    out=tmp_path/'snapshot';manifest=build_snapshot(project,'scene',['fixed'],str(out),{'include_automatically_verified':True,'include_procedural_positives':True})
    assert 'declared-color-camera-tracks-v1' in manifest['reader_capabilities']
    moved=tmp_path/'moved';out.rename(moved);shutil.rmtree(source)
    report=validate_snapshot(str(moved));assert report['ok'],report['issues']


def test_quality_benchmark_reports_false_alarms_misses_and_label_provenance(tmp_path):
    import json
    from framebound.v3.benchmark import run
    cases=[]
    for name,kind,defects in [('correct',None,[]),('fault','wrong_event',[dict(check_id='scene:touch',slots=[1])])]:
        folder=tmp_path/name;folder.mkdir();_,spec,frames=scene_task(folder,kind)
        cases.append(dict(id=name,spec=spec,assets={aid:f'{name}/{aid}.png' for aid in frames},frame_asset_ids=frames,
            expected_defects=defects,complete_labels=True,origin='procedural',label_source='procedural',
            label_provenance='Independent authored interaction truth; fixture, not a reviewer decision.',
            generation_provenance='Deterministic camera/landmark fixture',split='held_out'))
    manifest=tmp_path/'benchmark.json';manifest.write_text(json.dumps(dict(id='scene-fixtures',methodology='One independent correct motion and one incorrect contact with stable individual feature bounds.',cases=cases)))
    report=run(manifest)
    assert report['summary']['true_positives']==1
    assert report['summary']['false_negatives']==report['summary']['false_positives']==0
    assert report['summary']['precision']==report['summary']['recall']==1
    assert report['summary']['exact_frame_localizations']==1
    assert report['summary']['independent_reviewed_generated_held_out_cases']==0
    assert report['missing_evidence'] and 'no arbitrary' in report['quality_claim']


def test_scene_measurement_budget_is_frozen_and_rejected_before_submission(tmp_path):
    from framebound.v2.services.errors import InvalidInput
    project,spec,frames=scene_task(tmp_path)
    spec['limits']={'max_measurement_pixels':100}
    tasks.create(project,spec);loop.start(project,'scene','run')
    with pytest.raises(InvalidInput,match='measurement pixel budget'):loop.submit(project,'run','expensive',frames)
    assert loop.get(project,'run')['submission_ids']==[]


@pytest.mark.parametrize('change',['missing-camera','missing-subject-slot','nonfinite','event-time','foreign-subject'])
def test_scene_prerequisites_cannot_be_faked_by_missing_tracks(tmp_path,change):
    from framebound.v2.services.errors import InvalidInput
    project,spec,_=scene_task(tmp_path)
    scene=spec['scene']
    if change=='missing-camera':scene['camera'].pop()
    if change=='missing-subject-slot':scene['features'].pop()
    if change=='nonfinite':scene['camera'][0]['translation'][0]=float('inf')
    if change=='event-time':scene['events'][0]['right_feature_id']='prop-0'
    if change=='foreign-subject':scene['features'][0]['subject_id']='invented'
    with pytest.raises((InvalidInput,ValueError)):tasks.create(project,spec)


def test_checked_in_scene_corpus_has_independent_expected_localization():
    from pathlib import Path
    from framebound.v3.benchmark import run
    report=run(Path(__file__).resolve().parents[1]/'fixtures/quality/tracked-scene-v1/corpus.json')
    assert report['summary']['cases']==6
    assert report['summary']['true_positives']==report['summary']['exact_frame_localizations']==6
    assert report['summary']['false_negatives']==report['summary']['false_positives']==0
    assert report['repairs'][0]['improved_checks']==['scene:touch']
    assert report['repairs'][0]['regressions']==[]
    assert report['summary']['independent_reviewed_generated_held_out_cases']==0
