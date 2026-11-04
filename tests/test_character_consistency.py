"""Procedural observation fixtures test gate logic, not model/art quality."""
import copy
import math

import pytest

from framebound.v3.character_consistency import Observation,Policy,evaluate_frame,evaluate_sequence,measurements


def point(x,y):return dict(xy=[x,y],visibility='visible',evidence='TEST-ONLY procedural point')
def feature(status='match'):return dict(status=status,observed='TEST-ONLY visible construction',expected='frozen procedural construction')


def observation(frame='0',sha='1'*64):
    xy={'head_top':(500,100),'chin':(500,200),'head_left':(450,150),'head_right':(550,150),
        'neck':(500,220),'pelvis':(500,450),'chest_left':(440,270),'chest_right':(560,270),
        'waist_left':(460,430),'waist_right':(540,430)}
    for side,x,direction in [('left',450,-1),('right',550,1)]:
        xy.update({side+'_shoulder':(x,240),side+'_elbow':(x+direction*50,340),side+'_wrist':(x+direction*50,450),side+'_hand':(x+direction*50,465),
                   side+'_hip':(x,460),side+'_knee':(x,650),side+'_ankle':(x,850),side+'_arm_inner':(x-10,290),side+'_arm_outer':(x+10,290),
                   side+'_thigh_inner':(x-20,550),side+'_thigh_outer':(x+20,550),side+'_calf_inner':(x-15,750),side+'_calf_outer':(x+15,750)})
    return Observation(image_sha256=sha,frame_id=frame,execution_id='TEST-ONLY',raw_sha256='2'*64,width=1000,height=1000,
        points={k:point(*v) for k,v in xy.items()},features={'face.identity':feature(),'attire.palette:shirt':feature(),'body.proportions':feature()},
        items={'item':dict(visibility='visible',anchor='right_hand',grip=point(600,465),rigid_span=[point(600,450),point(600,510)],
            features={k:feature() for k in ['design','palette','scale','attachment']},evidence='TEST-ONLY item held by right hand')},limitation='Synthetic geometry only; no inference or artistic validation.')


def policy():
    return Policy(request_sha256='3'*64,master=observation('master'),required_features=['face.identity','attire.palette:shirt','body.proportions'],
                  items=[dict(id='item',description='TEST-ONLY generic item',anchor='right_hand',rigid_measurement='rigid component')])


def evaluate(obs,p=None,**kw):return evaluate_frame(p or policy(),obs,image_sha256='1'*64,frame_id='0',**kw)
def codes(report):return {i['code'] for i in report['issues']}


def test_reference_and_generic_visible_inventory_pass():
    assert evaluate(observation())['passed']


def test_bending_a_leg_without_changing_segment_lengths_is_allowed():
    o=observation().model_dump(mode='json');x,y=550,460
    knee=(x+190/math.sqrt(2),y+190/math.sqrt(2));ankle=(knee[0]+200,knee[1])
    o['points']['right_knee']=point(*knee);o['points']['right_ankle']=point(*ankle)
    assert evaluate(o)['passed']


def test_global_scale_is_measured_and_recorded_calibration_can_correct_it():
    o=observation().model_dump(mode='json')
    for p in o['points'].values():p['xy']=[500+(v-500)*1.2 for v in p['xy']]
    for p in [o['items']['item']['grip'],*o['items']['item']['rigid_span']]:p['xy']=[500+(v-500)*1.2 for v in p['xy']]
    assert 'scale_drift' in codes(evaluate(o))
    assert evaluate(o,pixel_scale=1/1.2)['passed']


def test_body_part_volume_and_length_drift_cannot_be_hidden_by_head_calibration():
    o=observation().model_dump(mode='json');o['points']['right_thigh_outer']=point(590,550)
    assert 'part_proportion_drift' in codes(evaluate(o))


@pytest.mark.parametrize('description',['leather weapon','metal shield','lantern','bag'])
def test_design_and_hand_gates_apply_to_any_item(description):
    p=policy().model_dump(mode='json');p['items'][0]['description']=description
    o=observation().model_dump(mode='json');o['items']['item']['anchor']='left_hand';o['items']['item']['features']['design']=feature('mismatch')
    r=evaluate(o,p)
    assert {'item_owner_changed','item_design_changed'}<=codes(r)


def test_item_rigid_span_and_grip_attachment_are_measured():
    o=observation().model_dump(mode='json');o['items']['item']['rigid_span'][1]=point(600,550);o['items']['item']['grip']=point(800,465)
    assert {'item_scale_drift','item_detached'}<=codes(evaluate(o))


def test_hidden_item_is_not_a_free_pass_and_transfer_must_be_declared():
    o=observation().model_dump(mode='json');o['items']['item']['visibility']='occluded'
    assert 'item_unmeasured' in codes(evaluate(o))
    p=policy().model_dump(mode='json');p['items'][0]['occluded_frames']=['0']
    assert evaluate(o,p)['passed']
    o=observation().model_dump(mode='json');o['items']['item']['anchor']='left_hand';o['items']['item']['grip']=point(400,465)
    p['items'][0]['anchor_by_frame']={'0':'left_hand'}
    assert evaluate(o,p)['passed']


def test_request_exception_is_exact_feature_and_frame_not_blanket_identity_permission():
    p=policy().model_dump(mode='json');p['allowances']=[dict(feature='attire.palette:shirt',frames=['0'],reason='Explicit wet shirt request',request_sha256=p['request_sha256'])]
    o=observation().model_dump(mode='json');o['features']['attire.palette:shirt']=feature('mismatch')
    assert evaluate(o,p)['passed']
    o['features']['face.identity']=feature('mismatch')
    assert not evaluate(o,p)['passed']
    p['allowances'][0]['request_sha256']='4'*64
    with pytest.raises(ValueError):Policy.model_validate(p)


def test_uncertain_and_stale_evidence_never_pass():
    o=observation().model_dump(mode='json');o['features']['face.identity']=feature('uncertain')
    assert 'feature_unmeasured' in codes(evaluate(o))
    o['image_sha256']='5'*64
    assert 'stale_evidence' in codes(evaluate(o))


def test_adjacent_pulse_is_checked_even_inside_global_tolerance():
    a=observation();b=observation('1')
    ar=a.model_dump(mode='json');br=b.model_dump(mode='json')
    ar['points']['right_arm_outer']=point(556.5,290);br['points']['right_arm_outer']=point(563.5,290)
    r=evaluate_sequence(policy(),[ar,br],['1'*64]*2,['0','1'],pairs=[(0,1),(1,0)])
    assert r['temporal_issues'] and not r['passed']


def test_duplicate_or_extra_visible_item_is_a_failure():
    o=observation().model_dump(mode='json');o['items']['extra']=copy.deepcopy(o['items']['item'])
    assert 'unexpected_item' in codes(evaluate(o))


def test_mounted_item_uses_visible_attachment_location():
    p=policy().model_dump(mode='json');p['items'][0].update(description='backpack',anchor='back_mount')
    for obs in (p['master'],):
        obs['points']['back_mount']=point(480,300)
        obs['items']['item'].update(anchor='back_mount',grip=point(480,300))
    o=copy.deepcopy(p['master']);o['frame_id']='0'
    assert evaluate(o,p)['passed']
    o['items']['item']['grip']=point(750,300)
    assert 'item_detached' in codes(evaluate(o,p))
    del o['points']['back_mount']
    assert 'attachment_unmeasured' in codes(evaluate(o,p))


def test_submission_requires_source_bound_item_evidence(tmp_path):
    from PIL import Image,ImageDraw
    from framebound.v2.services.projects import create_project
    from framebound.v2.services.assets import import_asset
    from framebound.v3.services import tasks,loop
    from framebound.v3.character_consistency import image_digest
    project=str(tmp_path);create_project(project,{'id':'p'})
    image=Image.new('RGBA',(1000,1000));ImageDraw.Draw(image).rectangle((350,100,650,850),fill='red')
    path=tmp_path/'fixture.png';image.save(path)
    import_asset(project,str(path),'identity',source_kind='procedural')
    p=policy().model_dump(mode='json');p['master_asset_id']='identity'
    p['master']['image_sha256']=image_digest(image)
    tasks.create(project,dict(id='character',project_id='p',animation_id='a',intent='Hold a procedural test object',subjects='procedural figure',
        canvas=dict(width=1000,height=1000),timing=dict(holds=[1]),loop=False,
        inputs=[dict(asset_id='identity',role='identity',provenance='procedural fixture',designated_by='test',basis='test invariant source')],character_consistency=p))
    loop.start(project,'character','run')
    missing=loop.submit(project,'run','missing',['identity'])
    assert missing['technical_status']!='pass'
    o=copy.deepcopy(p['master']);o['frame_id']='0';o['items']['item']['features']['design']=feature('mismatch')
    changed=loop.submit(project,'run','changed',['identity'],parent_revision_id='missing',feedback_id=missing['id'],generation_metadata={'character_consistency':{'observations':[o]}})
    assert changed['technical_status']!='pass'
    assert 'item_design_changed' in str(changed), changed


def test_external_geometry_requests_generic_mounts_and_does_not_retry_unknown(tmp_path):
    from PIL import Image
    from framebound.v3.character_observations import propose_observation
    calls=[]
    def dispatch(root,key,model,prompt,images):
        calls.append(prompt)
        raise TimeoutError('TEST-ONLY unknown provider acceptance')
    with pytest.raises(TimeoutError):
        propose_observation(tmp_path,'0',Image.new('RGBA',(32,32)),Image.new('RGBA',(32,32)),['face.identity'],
            [dict(id='bag',anchor='back_mount',anchor_by_frame={'1':'hip_mount'})],
            'TEST-ONLY mounted bag',dispatch=dispatch,persist=lambda *a:None,geometry_external=True)
    assert len(calls)==1
    landmarks=calls[0].split('Landmarks: ')[1].split('\n')[0]
    assert 'back_mount' in landmarks and 'hip_mount' in landmarks
    assert 'right_hand' not in landmarks


def test_arm_length_cannot_substitute_for_missing_volume_measurement():
    o=observation().model_dump(mode='json');p=policy().model_dump(mode='json')
    for v in [o,p['master']]:
        for side in ('left','right'):
            for edge in ('inner','outer'):v['points'][side+'_arm_'+edge]=dict(xy=None,visibility='uncertain',evidence='TEST-ONLY ambiguous width')
    assert 'coverage_gap' in codes(evaluate(o,p))
    p['required_features'].append('body.upper_arm_bulk');o['features']['body.upper_arm_bulk']=feature('mismatch')
    assert 'feature_changed' in codes(evaluate(o,p))
    assert not evaluate(o,p)['passed']
    o['features']['body.upper_arm_bulk']=feature('match')
    assert evaluate(o,p)['passed']


def test_rigid_item_can_pass_master_bounds_but_fail_adjacent_size_pulse():
    p=policy();a=observation('0');b=observation('1').model_dump(mode='json')
    a=a.model_dump(mode='json');a['items']['item']['rigid_span'][1]=point(600,504)
    b['items']['item']['rigid_span'][1]=point(600,516)
    result=evaluate_sequence(p,[a,b],['1'*64]*2,['0','1'],pairs=[(0,1)])
    assert all(f['passed'] for f in result['frames'])
    assert any(i['code']=='item_size_pulse' for i in result['temporal_issues'])


def test_neighbour_change_invalidates_retained_whole_sequence_review():
    p=policy();a=observation('0').model_dump(mode='json');b=observation('1').model_dump(mode='json')
    a['measurement_sources']['cohort_review']=dict(reference_sha256=p.master.image_sha256,context_sha256s={'0':'1'*64,'1':'1'*64})
    assert evaluate_sequence(p,[a,b],['1'*64]*2,['0','1'])['passed']
    b['image_sha256']='3'*64
    result=evaluate_sequence(p,[a,b],['1'*64,'3'*64],['0','1'])
    assert not result['passed']
    assert any(i['code']=='stale_cohort_context' for i in result['frames'][0]['issues'])
