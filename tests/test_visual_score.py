import pytest
from PIL import Image, ImageDraw

from framebound.v3.domain import TaskSpec
from framebound.v3 import visual_score
from framebound.v3 import evaluate as base_evaluate
from framebound.v3.services import tasks, loop
from framebound.v2.services.assets import import_asset
from framebound.v2.services.projects import create_project


def drawing(body_x=5, support=True, swollen=False):
    image = Image.new('RGBA', (32, 32))
    draw = ImageDraw.Draw(image)
    draw.rectangle((body_x, 5, body_x + (12 if swollen else 8), 16), fill=(255, 90, 30, 255))
    if support:
        draw.rectangle((body_x, 23, body_x + 8, 23), fill=(255, 90, 30, 255))
    return image


def spec():
    return TaskSpec.model_validate(dict(id='visual', project_id='project', animation_id='visual',
        intent='Match two declared phases and retain the planted support and body shape.',
        subjects='one isolated figure', canvas={'width':32,'height':32},
        timing={'ticks_per_second':24,'holds':[4,4]},
        inputs=[dict(asset_id=aid,role='known_good_animation',provenance='procedural fixture',
                     designated_by='fixture author',basis='frozen pose reference') for aid in ('early','late')],
        visual_observations=[
            dict(id='push-off',kind='phase',slot=0,roi=dict(left=2,top=3,right=30,bottom=19),
                 reference_asset_id='early',competing_asset_ids=['late'],minimum_similarity=.85,
                 minimum_margin=.05,provenance='declared phase',source='procedural'),
            dict(id='planted',kind='contact_span',slot=0,roi=dict(left=2,top=22,right=30,bottom=25),
                 minimum_span_px=7,provenance='declared visible support',source='procedural'),
            dict(id='body',kind='same_pose_shape',slot=0,roi=dict(left=2,top=3,right=30,bottom=19),
                 reference_asset_id='early',minimum_similarity=.7,minimum_area_ratio=.8,
                 maximum_area_ratio=1.2,provenance='same-pose same-view reference',source='procedural')]))


def test_castlevania_adversarial_shapes_are_localized():
    task=spec();references={'early':drawing(5),'late':drawing(17)}
    clean={r['id']:r for r in visual_score.evaluate(task,[drawing(5),drawing(17)],references)}
    assert {r['outcome'] for r in clean.values()} == {'pass'}
    repeated={r['id']:r for r in visual_score.evaluate(task,[drawing(17),drawing(17)],references)}
    assert repeated['push-off']['outcome']=='fail'
    assert repeated['push-off']['observed']['margin'] < 0
    lifted={r['id']:r for r in visual_score.evaluate(task,[drawing(5,support=False),drawing(17)],references)}
    assert lifted['planted']['outcome']=='fail'
    swollen={r['id']:r for r in visual_score.evaluate(task,[drawing(5,swollen=True),drawing(17)],references)}
    assert swollen['body']['outcome']=='fail'
    assert clean['push-off']['tick_range']==[0,4]


def test_scoring_benchmark_detects_three_defects_base_checks_miss():
    task=spec();references={'early':drawing(5),'late':drawing(17)}
    cases=[(drawing(17),'push-off'),(drawing(5,support=False),'planted'),
           (drawing(5,swollen=True),'body')]
    for candidate, expected_failure in cases:
        images=[candidate,drawing(17)]
        baseline,_,_=base_evaluate.evaluate(task,images,[{},{}],task.timing.holds)
        assert all(r['outcome']=='pass' for r in baseline), expected_failure
        scored=visual_score.evaluate(task,images,references)
        assert expected_failure in {r['id'] for r in scored if r['outcome']=='fail'}


def test_missing_reference_and_occlusion_do_not_claim_pass():
    task=spec();references={'early':drawing(5),'late':None}
    results={r['id']:r for r in visual_score.evaluate(task,[drawing(5),drawing(17)],references)}
    assert results['push-off']['outcome']=='unmeasured'
    task.visual_observations[0].visibility='occluded'
    results={r['id']:r for r in visual_score.evaluate(task,[drawing(5),drawing(17)],references)}
    assert results['push-off']['outcome']=='not_applicable'


def test_scoring_changes_submission_status_with_frozen_reference(tmp_path):
    project=str(tmp_path);create_project(project,{'id':'project'})
    for aid,image in [('early',drawing(5)),('late',drawing(17)),('wrong',drawing(17))]:
        path=tmp_path/f'{aid}.png';image.save(path)
        import_asset(project,str(path),aid,source_kind='procedural')
    tasks.create(project,spec().model_dump(mode='json'))
    loop.start(project,'visual','run')
    feedback=loop.submit(project,'run','bad',['wrong','late'])
    assert feedback['technical_status']=='fail'
    assert any(t['check_id']=='push-off' for t in feedback['targets'])
    evaluation=loop.revision_get(project,'bad')['evaluation']
    assert evaluation['evidence']['visual_score']['assets'][0]['id']=='early'
    repaired=loop.submit(project,'run','good',['early','late'],parent_revision_id='bad',feedback_id=feedback['id'])
    assert repaired['technical_status']=='pass'
    assert repaired['creative_status']=='unreviewed'


def test_unbound_reference_rejected():
    task=spec();task.inputs=[]
    with pytest.raises(ValueError,match='known_good_animation'):
        visual_score.validate(task)
